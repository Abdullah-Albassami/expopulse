import json
import time
from pathlib import Path

import cv2
import numpy as np
from django.core.management.base import BaseCommand, CommandError
from ultralytics import YOLO

from incidents.cctv.restricted_area import (
    ZoneConfigError,
    ZonePresenceTracker,
    find_active_restricted_zone_incident,
    get_bottom_center_from_xyxy,
    is_point_in_zone,
    load_zone_config,
)
from incidents.models import Incident, IncidentSource, Location
from incidents.services.assignment import assign_team_to_incident
from incidents.services.incident_service import create_incident


class Command(BaseCommand):
    help = "Monitor a fixed camera for restricted-zone person presence and create Security incidents."

    def add_arguments(self, parser):
        parser.add_argument("--video", required=True, help="MP4 path or HLS URL.")
        parser.add_argument("--location", required=True, help="Exact existing Location name.")
        parser.add_argument("--zone-config", required=True, help="JSON file with zone_id, name, and polygon.")
        parser.add_argument("--confirm-frames", type=int, default=5)
        parser.add_argument("--clear-frames", type=int, default=10)
        parser.add_argument("--sample-every", type=int, default=1)
        parser.add_argument("--confidence", type=float, default=0.35)
        parser.add_argument("--cooldown", type=float, default=60.0)
        parser.add_argument("--model", default="yolo11n.pt")
        parser.add_argument("--save-annotated", default="", help="Optional path for annotated output frame/video.")
        parser.add_argument("--show", action="store_true", help="Optional OpenCV display; not required for MVP.")
        parser.add_argument("--retry-delay", type=float, default=5.0)
        parser.add_argument("--max-retries", type=int, default=0)

    def handle(self, *args, **options):
        video = options["video"]
        location_name = options["location"]
        zone_config_path = options["zone_config"]
        confirm_frames = options["confirm_frames"]
        clear_frames = options["clear_frames"]
        sample_every = options["sample_every"]
        confidence = options["confidence"]
        cooldown = options["cooldown"]
        model_name = options["model"]
        save_annotated = options["save_annotated"]
        show = options["show"]
        retry_delay = options["retry_delay"]
        max_retries = options["max_retries"]

        if confirm_frames < 1 or clear_frames < 1 or sample_every < 1:
            raise CommandError("--confirm-frames, --clear-frames, and --sample-every must be positive integers.")
        if not 0 < confidence <= 1:
            raise CommandError("--confidence must be within (0, 1].")
        if cooldown < 0:
            raise CommandError("--cooldown must be nonnegative.")
        if retry_delay <= 0:
            raise CommandError("--retry-delay must be greater than zero.")
        if max_retries < 0:
            raise CommandError("--max-retries must be nonnegative.")

        try:
            zone = load_zone_config(zone_config_path)
        except (FileNotFoundError, json.JSONDecodeError, ZoneConfigError) as exc:
            raise CommandError(f"Invalid zone config: {exc}") from exc

        if not location_name:
            raise CommandError("A valid --location is required.")

        try:
            location = Location.objects.get(name=location_name)
        except Location.DoesNotExist as exc:
            raise CommandError(f"Location '{location_name}' not found. Run python manage.py seed_data first.") from exc
        except Location.MultipleObjectsReturned as exc:
            raise CommandError(f"Location name '{location_name}' is not unique.") from exc

        source, _ = IncidentSource.objects.get_or_create(
            name="CCTV Monitoring",
            defaults={"source_type": IncidentSource.SourceType.SENSOR},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Restricted-area detector started | location={location.name} | zone_id={zone.zone_id} | polygon={zone.polygon.points}"
            )
        )

        is_stream = str(video).lower().startswith(("http://", "https://"))
        capture = None
        model = YOLO(model_name)
        tracker = ZonePresenceTracker(confirm_frames=confirm_frames, clear_frames=clear_frames)
        alert_active = False
        last_alert_time = float("-inf")
        retries = 0
        frame_index = 0

        try:
            while True:
                if capture is None:
                    self.stdout.write(f"Opening video source: {video}")
                    capture = cv2.VideoCapture(video)
                    if not capture.isOpened():
                        capture.release()
                        capture = None
                        if not is_stream:
                            raise CommandError(f"Unable to open local video: {video}")
                        retries += 1
                        if max_retries and retries > max_retries:
                            raise CommandError("Maximum HLS retry attempts reached.")
                        self.stdout.write(self.style.WARNING(f"Stream unavailable. Retry {retries} in {retry_delay:g} seconds."))
                        time.sleep(retry_delay)
                        continue
                    self.stdout.write(self.style.SUCCESS("Video source connected."))
                    retries = 0

                success, frame = capture.read()
                if not success:
                    capture.release()
                    capture = None
                    if not is_stream:
                        self.stdout.write("Local MP4 finished; detector exiting cleanly.")
                        break
                    retries += 1
                    if max_retries and retries > max_retries:
                        raise CommandError("Maximum stream reconnection attempts reached.")
                    self.stdout.write(self.style.WARNING(f"Stream interrupted. Reconnecting in {retry_delay:g} seconds."))
                    time.sleep(retry_delay)
                    continue

                frame_index += 1
                if frame_index % sample_every != 0:
                    continue

                height, width = frame.shape[:2]
                if show:
                    cv2.imshow("Restricted area detector", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                results = model.track(
                    frame,
                    persist=True,
                    classes=[0],
                    conf=confidence,
                    device="cpu",
                    verbose=False,
                )

                if not results or len(results) == 0:
                    continue
                result = results[0]
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue

                track_ids = getattr(boxes, "id", None)
                if track_ids is not None:
                    if hasattr(track_ids, "cpu"):
                        track_ids = [int(item) for item in track_ids.cpu().tolist()]
                    else:
                        track_ids = [int(item) for item in track_ids]
                else:
                    track_ids = [None] * len(boxes.xyxy)

                boxes_xyxy = boxes.xyxy.cpu().tolist() if hasattr(boxes.xyxy, "cpu") else boxes.xyxy.tolist()

                detections = []
                for index, box in enumerate(boxes_xyxy):
                    track_id = track_ids[index] if index < len(track_ids) else None
                    x1, y1, x2, y2 = [float(value) for value in box]
                    bottom_center = get_bottom_center_from_xyxy([x1, y1, x2, y2])
                    inside = is_point_in_zone(zone, bottom_center[0], bottom_center[1], frame_width=width, frame_height=height)
                    detections.append((track_id, inside, bottom_center))

                for track_id, inside, bottom_center in detections:
                    decision = tracker.observe(track_id, inside)
                    if decision == "candidate":
                        self.stdout.write(f"Candidate inside zone: track={track_id} point={bottom_center}")
                    elif decision == "confirmed":
                        self.stdout.write(self.style.WARNING(f"Zone confirmed for track {track_id}."))
                    elif decision == "cleared":
                        self.stdout.write(self.style.WARNING("Restricted-zone event cleared."))
                    elif decision == "ignored":
                        self.stdout.write(f"Skipping untracked detection at {bottom_center}.")

                if tracker.state == "confirmed" and not alert_active:
                    now = time.monotonic()
                    if now - last_alert_time < cooldown:
                        self.stdout.write("Cooldown active; incident remains suppressed.")
                        continue

                    active_incident = find_active_restricted_zone_incident(location, zone.zone_id)
                    if active_incident is not None:
                        self.stdout.write(self.style.WARNING(f"already_active: incident #{active_incident.pk} for zone {zone.zone_id}."))
                        alert_active = True
                        last_alert_time = now
                        continue

                    incident_title = f"CCTV Restricted Zone [{zone.zone_id}] - {location.name}"
                    incident = create_incident(
                        title=incident_title,
                        description=(
                            f"Possible person presence detected in restricted area '{zone.name}' at {location.name}. "
                            "Authorization is unknown; operator verification required."
                        ),
                        incident_type=Incident.IncidentType.SECURITY,
                        source=source,
                        location=location,
                        severity=Incident.Severity.HIGH,
                        people_affected=1,
                    )
                    self.stdout.write(self.style.SUCCESS(f"Incident #{incident.pk} created for zone {zone.zone_id}."))
                    if incident.possible_duplicate_of_id:
                        self.stdout.write(self.style.WARNING("Possible duplicate of an existing Security incident; team assignment suppressed."))
                    else:
                        team = assign_team_to_incident(incident)
                        if team:
                            self.stdout.write(self.style.SUCCESS(f"Assigned team: {team.name}"))
                        else:
                            self.stdout.write(self.style.WARNING("No matching available team. Incident remains New."))

                    alert_active = True
                    last_alert_time = now

                if tracker.state in {"outside", "clearing"}:
                    alert_active = False

                if save_annotated and frame is not None:
                    annotated = frame.copy()
                    polygon = zone.to_pixel_points(width, height)
                    cv2.polylines(annotated, [np.asarray(polygon, dtype=np.int32)], True, (0, 255, 0), 2)
                    for track_id, inside, bottom_center in detections:
                        if track_id is None:
                            continue
                        x, y = bottom_center
                        cv2.circle(annotated, (int(round(x)), int(round(y))), 6, (0, 0, 255) if inside else (255, 0, 0), -1)
                    base = Path(save_annotated)
                    base.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(base), annotated)
                    break

        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped by operator.")
        finally:
            if capture is not None:
                capture.release()
            if show:
                cv2.destroyAllWindows()

        self.stdout.write(self.style.SUCCESS("Restricted-area monitoring finished."))
