import time
from pathlib import Path

import cv2
from ultralytics import YOLO

from django.core.management.base import BaseCommand, CommandError

from incidents.models import Incident, IncidentSource, Location
from incidents.services.assignment import assign_team_to_incident
from incidents.services.incident_service import create_incident


class Command(BaseCommand):
    help = "Detect crowding in CCTV footage and create ExpoPulse incidents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--video",
            required=True,
            help="Path to an MP4 file or URL to an HLS stream.",
        )
        parser.add_argument(
            "--location",
            default="Gate 1",
            help="Existing ExpoPulse location name.",
        )
        parser.add_argument(
            "--threshold",
            type=int,
            default=5,
            help="Minimum number of detected people for crowding.",
        )
        parser.add_argument(
            "--frames",
            type=int,
            default=3,
            help="Consecutive sampled frames required to trigger.",
        )
        parser.add_argument(
            "--sample-every",
            type=int,
            default=5,
            help="Analyze one frame out of every N frames.",
        )
        parser.add_argument(
            "--cooldown",
            type=float,
            default=60,
            help="Minimum seconds between new alerts.",
        )
        parser.add_argument(
            "--confidence",
            type=float,
            default=0.35,
            help="Minimum YOLO detection confidence.",
        )

    def handle(self, *args, **options):
        video = options["video"]
        threshold = options["threshold"]
        required_frames = options["frames"]
        sample_every = options["sample_every"]
        cooldown = options["cooldown"]
        confidence = options["confidence"]

        if threshold < 1 or required_frames < 1 or sample_every < 1:
            raise CommandError(
                "Threshold, frames, and sample-every must be positive."
            )

        if cooldown < 0 or not 0 < confidence <= 1:
            raise CommandError("Invalid cooldown or confidence value.")

        try:
            location = Location.objects.get(name=options["location"])
        except Location.DoesNotExist:
            raise CommandError(
                f"Location '{options['location']}' not found. "
                "Run python manage.py seed_data first."
            )
        except Location.MultipleObjectsReturned:
            raise CommandError("Location name is not unique.")

        source, _ = IncidentSource.objects.get_or_create(
            name="CCTV Monitoring",
            defaults={
                "source_type": IncidentSource.SourceType.SENSOR,
            },
        )

        self.stdout.write("Loading YOLO11n model...")
        model = YOLO("yolo11n.pt")

        capture = cv2.VideoCapture(video)

        if not capture.isOpened():
            raise CommandError(f"Cannot open video source: {video}")

        self.stdout.write(
            self.style.SUCCESS(
                f"CCTV detection started at {location.name}"
            )
        )

        frame_number = 0
        consecutive_high = 0
        consecutive_low = 0
        alert_active = False
        last_alert_time = float("-inf")

        try:
            while True:
                success, frame = capture.read()

                if not success:
                    self.stdout.write("Video ended or stream disconnected.")
                    break

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

                    if consecutive_low >= required_frames:
                        alert_active = False

                now = time.monotonic()

                if (
                    not alert_active
                    and consecutive_high >= required_frames
                    and now - last_alert_time >= cooldown
                ):
                    incident = create_incident(
                        title=f"CCTV Crowding Alert - {location.name}",
                        description=(
                            "Automated CCTV detection identified "
                            f"{people_count} people in the monitored area. "
                            "Operator verification required."
                        ),
                        incident_type=Incident.IncidentType.CROWDING,
                        source=source,
                        location=location,
                        severity=Incident.Severity.HIGH,
                        people_affected=people_count,
                    )

                    self.stdout.write(
                        self.style.WARNING(
                            f"Incident #{incident.pk} created | "
                            f"Priority: {incident.priority_level} "
                            f"({incident.priority_score})"
                        )
                    )

                    if incident.possible_duplicate_of_id:
                        self.stdout.write(
                            f"Possible duplicate of incident "
                            f"#{incident.possible_duplicate_of_id}. "
                            "No second team assigned."
                        )
                    else:
                        team = assign_team_to_incident(incident)

                        if team:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Automatically assigned: {team.name}"
                                )
                            )
                        else:
                            self.stdout.write(
                                "No matching available team. "
                                "Incident remains New."
                            )

                    alert_active = True
                    last_alert_time = now

        except KeyboardInterrupt:
            self.stdout.write("\nDetection stopped by operator.")

        finally:
            capture.release()

        self.stdout.write(self.style.SUCCESS("CCTV detection finished."))
