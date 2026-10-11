import math
from pathlib import Path

import cv2
import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.core.exceptions import ValidationError
from ultralytics import YOLO

from incidents.cctv.fall_detection import (
    CCTV_SOURCE_NAME,
    LYING,
    UNCERTAIN,
    FallEventTracker,
    FallIncidentNotifier,
    IoUTrackAssociator,
    PoseObservation,
    PostureThresholds,
    classify_posture,
)
from incidents.models import IncidentSource, Location


VIDEO_SUFFIXES = (".mp4", ".avi", ".mov", ".m4v")
POSTURE_COLORS = {LYING: (0, 0, 255), UNCERTAIN: (0, 200, 255)}


def _as_array(value):
    if value is None:
        return None
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value, dtype=float)


def extract_pose_observations(result):
    """Convert one Ultralytics pose result into PoseObservation objects."""
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return [], False
    boxes_xyxy = _as_array(boxes.xyxy)
    if boxes_xyxy is None or len(boxes_xyxy) == 0:
        return [], False

    keypoints = getattr(result, "keypoints", None)
    keypoints_xy = _as_array(getattr(keypoints, "xy", None)) if keypoints is not None else None
    keypoints_conf = _as_array(getattr(keypoints, "conf", None)) if keypoints is not None else None
    keypoints_missing = (
        keypoints_xy is None or keypoints_conf is None or len(keypoints_xy) != len(boxes_xyxy)
    )

    observations = []
    for index, box in enumerate(boxes_xyxy):
        if keypoints_missing:
            observations.append(PoseObservation(tuple(box), None, None))
        else:
            observations.append(
                PoseObservation(
                    tuple(box),
                    tuple(map(tuple, keypoints_xy[index])),
                    tuple(keypoints_conf[index]),
                )
            )
    return observations, keypoints_missing


class Command(BaseCommand):
    help = (
        "Watch a recorded CCTV MP4 for a possible fall / sustained lying posture "
        "and create an operator-verifiable Medical incident."
    )

    def add_arguments(self, parser):
        parser.add_argument("--video", required=True, help="Local MP4 path.")
        parser.add_argument("--location", required=True, help="Exact existing Location name.")
        parser.add_argument("--confirm-frames", type=int, default=5,
                            help="Lying observations of one person (processed frames) needed to confirm.")
        parser.add_argument("--clear-frames", type=int, default=10,
                            help="Not-lying observations of one person needed to clear a confirmed event.")
        parser.add_argument("--sample-every", type=int, default=5, help="Process every Nth video frame.")
        parser.add_argument("--confidence", type=float, default=0.35, help="Person detection confidence.")
        parser.add_argument("--cooldown", type=float, default=120.0,
                            help="Minimum video seconds between incidents created by this run.")
        parser.add_argument("--track-expiry", type=float, default=3.0,
                            help="Video seconds a person may be unseen before their track is dropped.")
        parser.add_argument("--keypoint-confidence", type=float, default=PostureThresholds.keypoint_confidence)
        parser.add_argument("--lying-angle", type=float, default=PostureThresholds.lying_axis_degrees,
                            help="Minimum body-axis angle from vertical (degrees) for a lying posture.")
        parser.add_argument("--model", default="yolo11n-pose.pt")
        parser.add_argument("--save-annotated", default="",
                            help="Optional output: .mp4/.avi writes annotated video; an image path saves the first confirmed frame.")

    def handle(self, *args, **options):
        video = options["video"]
        confirm_frames = options["confirm_frames"]
        clear_frames = options["clear_frames"]
        sample_every = options["sample_every"]
        confidence = options["confidence"]
        cooldown = options["cooldown"]
        track_expiry = options["track_expiry"]
        keypoint_confidence = options["keypoint_confidence"]
        lying_angle = options["lying_angle"]
        save_annotated = options["save_annotated"]

        if confirm_frames < 1 or clear_frames < 1 or sample_every < 1:
            raise CommandError("--confirm-frames, --clear-frames, and --sample-every must be >= 1.")
        if not 0 < confidence <= 1:
            raise CommandError("--confidence must be within (0, 1].")
        if not 0 < keypoint_confidence <= 1:
            raise CommandError("--keypoint-confidence must be within (0, 1].")
        if not 0 < lying_angle <= 90:
            raise CommandError("--lying-angle must be within (0, 90].")
        if cooldown < 0 or track_expiry < 0:
            raise CommandError("--cooldown and --track-expiry must be nonnegative.")

        try:
            location = Location.objects.get(name=options["location"])
        except Location.DoesNotExist as exc:
            raise CommandError(
                f"Location '{options['location']}' not found. Run python manage.py seed_data first."
            ) from exc
        except Location.MultipleObjectsReturned as exc:
            raise CommandError(f"Location name '{options['location']}' is not unique.") from exc

        if str(video).lower().startswith(("http://", "https://")):
            raise CommandError("Only local MP4 files are supported by detect_falls.")
        if not Path(video).is_file():
            raise CommandError(f"Video file not found: {video}")

        thresholds = PostureThresholds(
            keypoint_confidence=keypoint_confidence,
            lying_axis_degrees=lying_angle,
        )

        try:
            model = YOLO(options["model"])
        except Exception as exc:
            raise CommandError(f"Unable to load pose model '{options['model']}': {exc}") from exc
        if getattr(model, "task", "pose") != "pose":
            raise CommandError(f"Model '{options['model']}' is not a pose model (task={model.task}).")

        source, _ = IncidentSource.objects.get_or_create(
            name=CCTV_SOURCE_NAME,
            defaults={"source_type": IncidentSource.SourceType.SENSOR},
        )

        capture = cv2.VideoCapture(str(video))
        writer = None
        try:
            if not capture.isOpened():
                raise CommandError(f"Unable to open video: {video}")
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not fps or not math.isfinite(fps) or fps <= 0:
                raise CommandError(f"Video has no usable FPS metadata: {video}")

            self.stdout.write(self.style.SUCCESS(
                f"Fall detector started | location={location.name} | fps={fps:g} | "
                f"sample_every={sample_every} | confirm={confirm_frames} | clear={clear_frames} | "
                f"lying_angle>={thresholds.lying_axis_degrees:g} | cooldown={cooldown:g}s video time"
            ))

            associator = IoUTrackAssociator(expiry_seconds=track_expiry)
            tracker = FallEventTracker(
                confirm_frames=confirm_frames,
                clear_frames=clear_frames,
                expiry_seconds=track_expiry,
            )
            notifier = FallIncidentNotifier(location=location, source=source, cooldown_seconds=cooldown)
            pending_alert = False
            annotated_saved = False
            warned_no_keypoints = False
            frame_index = 0

            while True:
                success, frame = capture.read()
                if not success:
                    if frame_index == 0:
                        raise CommandError(f"Unable to read any frames from video: {video}")
                    self.stdout.write("End of video reached; detector exiting.")
                    break
                frame_index += 1
                if frame_index % sample_every != 0:
                    continue

                # Video time, not wall-clock time, so recorded runs are reproducible.
                timestamp = (frame_index - 1) / fps

                try:
                    results = model.predict(frame, conf=confidence, classes=[0], device="cpu", verbose=False)
                except Exception as exc:
                    raise CommandError(f"Pose model failed on frame {frame_index}: {exc}") from exc

                observations, keypoints_missing = extract_pose_observations(results[0]) if results else ([], False)
                if keypoints_missing and not warned_no_keypoints:
                    self.stdout.write(self.style.WARNING(
                        "Model returned no keypoints; detections are treated as uncertain."
                    ))
                    warned_no_keypoints = True

                track_ids = associator.assign([obs.box for obs in observations], timestamp)
                assessments = [classify_posture(obs, thresholds) for obs in observations]
                events = tracker.observe(
                    timestamp,
                    [(track_id, assessment.posture) for track_id, assessment in zip(track_ids, assessments)],
                )

                for track_id, assessment in zip(track_ids, assessments):
                    if assessment.posture == UNCERTAIN and track_id in tracker.tracks \
                            and tracker.tracks[track_id].state != "idle":
                        self.stdout.write(f"[t={timestamp:.2f}s] track {track_id}: pose uncertain ({assessment.reason}).")

                for event in events:
                    self._log_event(event)
                    if event.kind == "confirmed":
                        pending_alert = True

                if pending_alert:
                    pending_alert = not self._notify(notifier, timestamp)

                if save_annotated:
                    confirmed = any(event.kind == "confirmed" for event in events)
                    annotated = self._annotate(frame, observations, track_ids, assessments, tracker, timestamp)
                    if save_annotated.lower().endswith(VIDEO_SUFFIXES):
                        if writer is None:
                            height, width = annotated.shape[:2]
                            Path(save_annotated).parent.mkdir(parents=True, exist_ok=True)
                            writer = cv2.VideoWriter(
                                save_annotated, cv2.VideoWriter_fourcc(*"mp4v"),
                                fps / sample_every, (width, height),
                            )
                        writer.write(annotated)
                    elif confirmed and not annotated_saved:
                        Path(save_annotated).parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(save_annotated, annotated)
                        annotated_saved = True
                        self.stdout.write(f"Annotated confirmation frame saved to {save_annotated}")

            if pending_alert:
                self.stderr.write("A confirmed possible fall could not be recorded before the video ended.")
        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped by operator.")
        finally:
            capture.release()
            if writer is not None:
                writer.release()

        self.stdout.write(self.style.SUCCESS("Fall detection finished."))

    def _log_event(self, event):
        prefix = f"[t={event.timestamp:.2f}s] track {event.track_id}:"
        if event.kind == "candidate":
            self.stdout.write(f"{prefix} candidate lying posture ({event.detail}).")
        elif event.kind == "candidate_reset":
            self.stdout.write(f"{prefix} candidate reset ({event.detail}).")
        elif event.kind == "confirmed":
            self.stdout.write(self.style.WARNING(
                f"{prefix} Possible Fall confirmed — operator verification required."
            ))
        elif event.kind == "recovering":
            self.stdout.write(f"{prefix} recovering ({event.detail}).")
        elif event.kind == "cleared":
            self.stdout.write(self.style.SUCCESS(f"{prefix} visual event cleared ({event.detail})."))
        elif event.kind == "expired":
            self.stdout.write(f"{prefix} confirmed track absent too long; visual event cleared.")

    def _notify(self, notifier, timestamp):
        """Try to record a confirmed event; return True when it was handled."""
        try:
            result = notifier.notify(timestamp)
        except (DatabaseError, ValidationError) as exc:
            self.stderr.write(f"Failed to record possible fall incident; will retry: {exc}")
            return False

        if result.outcome == "cooldown":
            self.stdout.write("Cooldown active; incident creation suppressed.")
        elif result.outcome == "already_active":
            self.stdout.write(self.style.WARNING(
                f"Suppressed: unresolved CCTV Medical incident #{result.incident.pk} already open at this location."
            ))
        else:
            incident = result.incident
            self.stdout.write(self.style.SUCCESS(f"Incident #{incident.pk} created: {incident.title}"))
            if incident.possible_duplicate_of_id:
                self.stdout.write(self.style.WARNING(
                    f"Possible duplicate of incident #{incident.possible_duplicate_of_id}; team assignment skipped."
                ))
            elif result.team:
                self.stdout.write(self.style.SUCCESS(f"Assigned team: {result.team.name}"))
            else:
                self.stdout.write(self.style.WARNING("No available Medical team. Incident remains New."))
        return True

    @staticmethod
    def _annotate(frame, observations, track_ids, assessments, tracker, timestamp):
        annotated = frame.copy()
        for obs, track_id, assessment in zip(observations, track_ids, assessments):
            x1, y1, x2, y2 = (int(round(value)) for value in obs.box)
            track = tracker.tracks.get(track_id)
            confirmed = track is not None and track.state == "confirmed"
            color = (0, 0, 255) if confirmed else POSTURE_COLORS.get(assessment.posture, (0, 200, 0))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            if obs.keypoints is not None:
                for (x, y), conf in zip(obs.keypoints, obs.keypoint_confidence):
                    if conf >= 0.4:
                        cv2.circle(annotated, (int(round(x)), int(round(y))), 3, color, -1)
            angle = "" if assessment.axis_degrees is None else f" {assessment.axis_degrees:.0f}deg"
            label = f"T{track_id} {'POSSIBLE FALL' if confirmed else assessment.posture}{angle}"
            cv2.putText(annotated, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        cv2.putText(annotated, f"t={timestamp:.2f}s", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        return annotated
