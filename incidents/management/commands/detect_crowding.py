import time

import cv2
from ultralytics import YOLO

from django.core.management.base import BaseCommand, CommandError

from incidents.models import Incident, IncidentSource, Location
from incidents.services.assignment import assign_team_to_incident
from incidents.cctv.crowding_state import CrowdingState
from incidents.cctv.incident_guard import get_or_create_cctv_crowding_incident


class Command(BaseCommand):
    help = "Monitor CCTV footage for crowding and create ExpoPulse incidents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--video",
            required=True,
            help="Local MP4 path or HTTP(S) HLS/M3U8 URL.",
        )
        parser.add_argument("--location", default="Gate 1")
        parser.add_argument("--threshold", type=int, default=5)
        parser.add_argument("--frames", type=int, default=3)
        parser.add_argument("--sample-every", type=int, default=5)
        parser.add_argument("--confidence", type=float, default=0.35)
        parser.add_argument("--model", default="yolo11n.pt")
        parser.add_argument("--imgsz", type=int, default=640)
        parser.add_argument("--clear-threshold", type=int)
        parser.add_argument("--clear-seconds", type=float, default=10)
        parser.add_argument(
            "--cooldown",
            type=float,
            default=60,
            help="Minimum seconds between generated alerts.",
        )
        parser.add_argument(
            "--retry-delay",
            type=float,
            default=5,
            help="Seconds between HLS reconnection attempts.",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=0,
            help="Maximum consecutive HLS retries; 0 means unlimited.",
        )

    def handle(self, *args, **options):
        video = options["video"]
        location_name = options["location"]
        threshold = options["threshold"]
        required_frames = options["frames"]
        sample_every = options["sample_every"]
        confidence = options["confidence"]
        cooldown = options["cooldown"]
        retry_delay = options["retry_delay"]
        max_retries = options["max_retries"]
        imgsz = options["imgsz"]
        model_path = options["model"]
        clear_seconds = options["clear_seconds"]
        clear_threshold = options["clear_threshold"]
        if clear_threshold is None:
            clear_threshold = max(0, threshold - 2)

        if min(threshold, required_frames, sample_every) < 1:
            raise CommandError(
                "Threshold, frames, and sample-every must be at least 1."
            )

        if imgsz < 32 or clear_seconds < 0:
            raise CommandError("Invalid image size or clearance duration.")
        try:
            state = CrowdingState(threshold, clear_threshold, required_frames, clear_seconds)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if not 0 < confidence <= 1:
            raise CommandError("Confidence must be between 0 and 1.")

        if cooldown < 0 or retry_delay <= 0 or max_retries < 0:
            raise CommandError("Invalid cooldown or reconnection settings.")

        try:
            location = Location.objects.get(name=location_name)
        except Location.DoesNotExist as exc:
            raise CommandError(
                f"Location '{location_name}' not found. "
                "Run python manage.py seed_data first."
            ) from exc
        except Location.MultipleObjectsReturned as exc:
            raise CommandError("Location name is not unique.") from exc

        source, _ = IncidentSource.objects.get_or_create(
            name="CCTV Monitoring",
            defaults={
                "source_type": IncidentSource.SourceType.SENSOR,
            },
        )

        is_stream = video.lower().startswith(("http://", "https://"))

        self.stdout.write(f"Loading YOLO model: {model_path}...")
        model = YOLO(model_path)

        self.stdout.write(
            self.style.SUCCESS(
                f"CCTV monitoring started | Location: {location.name} | "
                f"Threshold: {threshold} | Frames: {required_frames}"
            )
        )

        frame_number = 0
        # Monotonic time avoids system-clock changes affecting cooldown.
        last_alert_time = float("-inf")
        retries = 0
        capture = None

        try:
            while True:
                if capture is None:
                    self.stdout.write(f"Opening video source: {video}")
                    capture = cv2.VideoCapture(video)

                    if not capture.isOpened():
                        capture.release()
                        capture = None

                        if not is_stream:
                            raise CommandError(
                                f"Cannot open local video: {video}"
                            )

                        retries += 1

                        if max_retries and retries > max_retries:
                            raise CommandError(
                                "Maximum stream reconnection attempts reached."
                            )

                        self.stdout.write(
                            self.style.WARNING(
                                f"Stream unavailable. Retry {retries} "
                                f"in {retry_delay:g} seconds..."
                            )
                        )
                        time.sleep(retry_delay)
                        continue

                    self.stdout.write(
                        self.style.SUCCESS("Video source connected.")
                    )

                    frame_number = 0
                    # Retain episode and cooldown state across reconnects.

                    retries = 0

                success, frame = capture.read()

                if not success:
                    state.interrupt()
                    capture.release()
                    capture = None

                    if not is_stream:
                        self.stdout.write("Local video finished.")
                        break

                    retries += 1

                    if max_retries and retries > max_retries:
                        raise CommandError(
                            "Maximum stream reconnection attempts reached."
                        )

                    self.stdout.write(
                        self.style.WARNING(
                            f"Stream interrupted. Reconnecting in "
                            f"{retry_delay:g} seconds..."
                        )
                    )
                    time.sleep(retry_delay)
                    continue

                frame_number += 1

                if frame_number % sample_every != 0:
                    continue

                results = model.predict(
                    frame,
                    classes=[0],
                    conf=confidence,
                    imgsz=imgsz,
                    device="cpu",
                    verbose=False,
                )

                people_count = len(results[0].boxes)

                self.stdout.write(
                    f"Frame {frame_number}: "
                    f"{people_count} people detected"
                )

                event = state.update(people_count, time.monotonic())
                if event == "clear":
                    self.stdout.write("Crowding visually cleared; incident remains open.")
                    continue
                if event != "trigger":
                    continue
                now = time.monotonic()
                if now - last_alert_time < cooldown:
                    self.stdout.write("New episode detected during cooldown; suppressed.")
                    continue
                self.stdout.write(self.style.WARNING(f"CROWDING DETECTED: {people_count} people at {location.name}"))
                incident, created = get_or_create_cctv_crowding_incident(
                    source=source, location=location, people_count=people_count
                )
                if not created:
                    self.stdout.write(f"Existing unresolved CCTV incident #{incident.pk}; duplicate suppressed.")
                else:
                    self.stdout.write(self.style.SUCCESS(f"Incident #{incident.pk} created | Priority: {incident.priority_level} ({incident.priority_score})"))
                    if incident.possible_duplicate_of_id:
                        self.stdout.write(f"Possible duplicate of #{incident.possible_duplicate_of_id}; no additional team assigned.")
                    else:
                        try:
                            team = assign_team_to_incident(incident)
                        except Exception:
                            self.stderr.write(self.style.ERROR(f"Incident #{incident.pk} created but assignment failed."))
                            raise
                        if team:
                            self.stdout.write(self.style.SUCCESS(f"Assigned team: {team.name}"))
                        else:
                            self.stdout.write("No matching available team. Incident remains New.")
                last_alert_time = time.monotonic()

        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped by operator.")

        finally:
            if capture is not None:
                capture.release()

        self.stdout.write(
            self.style.SUCCESS("CCTV monitoring finished.")
        )
