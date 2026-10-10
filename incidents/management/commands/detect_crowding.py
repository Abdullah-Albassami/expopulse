import time

import cv2
from ultralytics import YOLO

from django.core.management.base import BaseCommand, CommandError

from incidents.models import Incident, IncidentSource, Location
from incidents.services.assignment import assign_team_to_incident
from incidents.services.incident_service import create_incident


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

        if min(threshold, required_frames, sample_every) < 1:
            raise CommandError(
                "Threshold, frames, and sample-every must be at least 1."
            )

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

        self.stdout.write("Loading YOLO11n model...")
        model = YOLO("yolo11n.pt")

        self.stdout.write(
            self.style.SUCCESS(
                f"CCTV monitoring started | Location: {location.name} | "
                f"Threshold: {threshold} | Frames: {required_frames}"
            )
        )

        frame_number = 0
        consecutive_high = 0
        consecutive_low = 0

        # True while one crowding episode is active.
        alert_active = False

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
                    consecutive_high = 0
                    consecutive_low = 0

                    # Do not reset alert_active or last_alert_time:
                    # a reconnection must not create a duplicate episode.

                    retries = 0

                success, frame = capture.read()

                if not success:
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
                    device="cpu",
                    verbose=False,
                )

                people_count = len(results[0].boxes)

                self.stdout.write(
                    f"Frame {frame_number}: "
                    f"{people_count} people detected"
                )

                if people_count >= threshold:
                    consecutive_high += 1
                    consecutive_low = 0
                else:
                    consecutive_low += 1
                    consecutive_high = 0

                    if (
                        alert_active
                        and consecutive_low >= required_frames
                    ):
                        alert_active = False
                        self.stdout.write(
                            "Crowding cleared. Waiting for a new episode."
                        )

                if consecutive_high < required_frames:
                    continue

                if alert_active:
                    continue

                now = time.monotonic()

                if now - last_alert_time < cooldown:
                    # Suppress this episode until the crowd clears.
                    alert_active = True
                    self.stdout.write(
                        "Crowding detected, but cooldown is active. "
                        "No new incident created."
                    )
                    continue

                self.stdout.write(
                    self.style.WARNING(
                        f"CROWDING DETECTED: {people_count} people "
                        f"at {location.name}"
                    )
                )

                incident = create_incident(
                    title=f"CCTV Crowding Alert - {location.name}",
                    description=(
                        "Automated CCTV monitoring detected "
                        f"{people_count} people at {location.name}. "
                        "Operator verification required."
                    ),
                    incident_type=Incident.IncidentType.CROWDING,
                    source=source,
                    location=location,
                    severity=Incident.Severity.HIGH,
                    people_affected=people_count,
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Incident #{incident.pk} created | "
                        f"Priority: {incident.priority_level} "
                        f"({incident.priority_score})"
                    )
                )

                if incident.possible_duplicate_of_id:
                    self.stdout.write(
                        self.style.WARNING(
                            "Possible duplicate of incident "
                            f"#{incident.possible_duplicate_of_id}. "
                            "No additional team assigned."
                        )
                    )
                else:
                    team = assign_team_to_incident(incident)

                    if team:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Assigned team: {team.name}"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                "No matching available team. "
                                "Incident remains New."
                            )
                        )

                alert_active = True
                last_alert_time = time.monotonic()

        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped by operator.")

        finally:
            if capture is not None:
                capture.release()

        self.stdout.write(
            self.style.SUCCESS("CCTV monitoring finished.")
        )
