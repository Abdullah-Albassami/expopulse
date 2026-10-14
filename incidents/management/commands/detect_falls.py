import math
import time
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
    NOT_LYING,
    UNCERTAIN,
    FallEventTracker,
    FallIncidentNotifier,
    IoUTrackAssociator,
    PoseObservation,
    PostureThresholds,
    StreamClock,
    classify_posture,
    describe_transition,
)
from incidents.models import IncidentSource, Location


VIDEO_SUFFIXES = (".mp4", ".avi", ".mov", ".m4v")
STREAM_WRITER_FPS = 10.0  # annotated-video FPS when a live stream reports none
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
        "Watch a recorded CCTV MP4 or a simulated live HLS stream for a possible fall "
        "(sustained lying posture) and create an operator-verifiable Medical incident."
    )

    def add_arguments(self, parser):
        parser.add_argument("--video", required=True, help="Local MP4 path or HTTP(S) HLS playlist URL.")
        parser.add_argument("--demo-priority", choices=["critical"], default=None, help="Explicit demo-only incident priority.")
        parser.add_argument("--location", required=True, help="Exact existing Location name.")
        parser.add_argument("--confirm-frames", type=int, default=5,
                            help="Lying observations of one person (processed frames) needed to confirm.")
        parser.add_argument("--clear-frames", type=int, default=10,
                            help="Not-lying observations of one person needed to clear a confirmed event.")
        parser.add_argument("--sample-every", type=int, default=5, help="Process every Nth video frame.")
        parser.add_argument("--confidence", type=float, default=0.35, help="Person detection confidence.")
        parser.add_argument("--cooldown", type=float, default=120.0,
                            help="Minimum seconds between incidents created by this run (video time for "
                                 "files, monotonic time for streams).")
        parser.add_argument("--track-expiry", type=float, default=3.0,
                            help="Seconds a person may be unseen before their track is dropped.")
        parser.add_argument("--keypoint-confidence", type=float, default=PostureThresholds.keypoint_confidence)
        parser.add_argument("--lying-angle", type=float, default=PostureThresholds.lying_axis_degrees,
                            help="Minimum body-axis angle from vertical (degrees) for a lying posture.")
        parser.add_argument("--rapid-descent", type=float, default=FallEventTracker.rapid_descent_seconds,
                            help="Max seconds from standing to lying that counts as a rapid (fall-like) transition.")
        parser.add_argument("--slow-lying-hold", type=float, default=FallEventTracker.slow_lying_hold_seconds,
                            help="Seconds a person who was seen lying down slowly must keep lying before an "
                                 "alert (0 = alert as soon as confirmed).")
        parser.add_argument("--model", default="yolo11n-pose.pt")
        parser.add_argument("--save-annotated", default="",
                            help="Optional output: .mp4/.avi writes annotated video; an image path saves the first confirmed frame.")
        parser.add_argument("--retry-delay", type=float, default=5.0,
                            help="Seconds to wait before reconnecting to an HLS stream.")
        parser.add_argument("--max-retries", type=int, default=0,
                            help="Consecutive HLS reconnect attempts before giving up (0 = unlimited).")

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
        rapid_descent = options["rapid_descent"]
        slow_lying_hold = options["slow_lying_hold"]
        save_annotated = options["save_annotated"]
        retry_delay = options["retry_delay"]
        max_retries = options["max_retries"]

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
        if rapid_descent < 0 or slow_lying_hold < 0:
            raise CommandError("--rapid-descent and --slow-lying-hold must be nonnegative.")
        if retry_delay <= 0:
            raise CommandError("--retry-delay must be greater than zero.")
        if max_retries < 0:
            raise CommandError("--max-retries must be nonnegative.")

        try:
            location = Location.objects.get(name=options["location"])
        except Location.DoesNotExist as exc:
            raise CommandError(
                f"Location '{options['location']}' not found. Run python manage.py seed_data first."
            ) from exc
        except Location.MultipleObjectsReturned as exc:
            raise CommandError(f"Location name '{options['location']}' is not unique.") from exc

        is_stream = str(video).lower().startswith(("http://", "https://"))
        if not is_stream and not Path(video).is_file():
            raise CommandError(f"Video file not found: {video}")

        thresholds = PostureThresholds(
            keypoint_confidence=keypoint_confidence,
            lying_axis_degrees=lying_angle,
        )

        self.stdout.write(f"Loading YOLO11 pose model ({options['model']})...")
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

        self.stdout.write(self.style.SUCCESS("CCTV Fall Detection started"))
        self.stdout.write(f"Location: {location.name}")
        self.stdout.write(
            f"Source: {'HLS stream' if is_stream else 'local video'} {video}\n"
            f"Settings: sample_every={sample_every} confirm={confirm_frames} clear={clear_frames} "
            f"lying_angle>={thresholds.lying_axis_degrees:g} rapid_descent<={rapid_descent:g}s "
            f"slow_lying_hold={slow_lying_hold:g}s cooldown={cooldown:g}s"
        )

        capture = None
        writer = None
        fps = None
        retries = 0
        clock = StreamClock(time.monotonic) if is_stream else None
        time_base_logged = False
        try:
            associator = IoUTrackAssociator(expiry_seconds=track_expiry)
            tracker = FallEventTracker(
                confirm_frames=confirm_frames,
                clear_frames=clear_frames,
                expiry_seconds=track_expiry,
                rapid_descent_seconds=rapid_descent,
                slow_lying_hold_seconds=slow_lying_hold,
            )
            notifier = FallIncidentNotifier(location=location, source=source, cooldown_seconds=cooldown, demo_priority=options["demo_priority"])
            pending_alert = None
            annotated_saved = False
            warned_no_keypoints = False
            last_posture = {}
            frame_index = 0

            while True:
                if capture is None:
                    self.stdout.write("Connecting to HLS stream..." if is_stream else "Opening video...")
                    capture = cv2.VideoCapture(str(video))
                    if not capture.isOpened():
                        capture.release()
                        capture = None
                        if not is_stream:
                            raise CommandError(f"Unable to open video: {video}")
                        retries = self._wait_for_stream("Stream unavailable", retries, retry_delay, max_retries)
                        continue
                    if fps is None:
                        fps = capture.get(cv2.CAP_PROP_FPS)
                        if not fps or not math.isfinite(fps) or fps <= 0:
                            if not is_stream:
                                raise CommandError(f"Video has no usable FPS metadata: {video}")
                            fps = None  # not needed: live streams use the stream clock
                    if clock is not None:
                        clock.reconnect()
                        time_base_logged = False
                    self.stdout.write(self.style.SUCCESS("Video source connected."))

                success, frame = capture.read()
                if not success:
                    if is_stream:
                        capture.release()
                        capture = None
                        # Frames before and after an outage cannot be trusted to show the
                        # same people, so drop all per-person evidence. A fall still visible
                        # after reconnecting is re-confirmed and the open incident blocks a
                        # second row.
                        associator.reset()
                        tracker.reset()
                        last_posture.clear()
                        self.stdout.write(self.style.WARNING("Stream interrupted; tracking state reset."))
                        retries = self._wait_for_stream("Reconnecting", retries, retry_delay, max_retries)
                        continue
                    if frame_index == 0:
                        raise CommandError(f"Unable to read any frames from video: {video}")
                    self.stdout.write("End of video reached; detector exiting.")
                    break
                retries = 0
                frame_index += 1
                if frame_index % sample_every != 0:
                    continue

                if clock is not None:
                    # Stream presentation time, falling back to the monotonic clock (see StreamClock).
                    timestamp = clock.tick(capture.get(cv2.CAP_PROP_POS_MSEC))
                    if not time_base_logged:
                        self.stdout.write(
                            "Time base: stream timestamps." if clock.using_timestamps
                            else "Time base: monotonic clock (stream has no timestamps)."
                        )
                        time_base_logged = True
                else:
                    # Video time (not wall-clock), so recorded runs are reproducible.
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
                    [
                        (track_id, assessment.posture, obs.box)
                        for track_id, assessment, obs in zip(track_ids, assessments, observations)
                    ],
                )
                self._log_postures(timestamp, track_ids, assessments, tracker, last_posture)

                for event in events:
                    self._log_event(event)
                    if event.kind == "confirmed" and pending_alert is None:
                        pending_alert = event
                    if event.kind in ("expired", "cleared"):
                        last_posture.pop(event.track_id, None)

                if pending_alert is not None and self._notify(notifier, timestamp, pending_alert):
                    pending_alert = None

                if save_annotated:
                    confirmed = any(event.kind == "confirmed" for event in events)
                    annotated = self._annotate(frame, observations, track_ids, assessments, tracker, timestamp)
                    if save_annotated.lower().endswith(VIDEO_SUFFIXES):
                        if writer is None:
                            height, width = annotated.shape[:2]
                            Path(save_annotated).parent.mkdir(parents=True, exist_ok=True)
                            writer = cv2.VideoWriter(
                                save_annotated, cv2.VideoWriter_fourcc(*"mp4v"),
                                (fps or STREAM_WRITER_FPS * sample_every) / sample_every, (width, height),
                            )
                        writer.write(annotated)
                    elif confirmed and not annotated_saved:
                        Path(save_annotated).parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(save_annotated, annotated)
                        annotated_saved = True
                        self.stdout.write(f"Annotated confirmation frame saved to {save_annotated}")

            if pending_alert is not None:
                self.stderr.write("A confirmed possible fall could not be recorded before the video ended.")
        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped by operator.")
        finally:
            if capture is not None:
                capture.release()
            if writer is not None:
                writer.release()

        self.stdout.write(self.style.SUCCESS("Fall detection finished."))

    def _wait_for_stream(self, message, retries, retry_delay, max_retries):
        retries += 1
        if max_retries and retries > max_retries:
            raise CommandError(f"{message}; maximum reconnect attempts ({max_retries}) reached.")
        self.stdout.write(self.style.WARNING(f"{message}. Retry {retries} in {retry_delay:g} seconds."))
        time.sleep(retry_delay)
        return retries

    def _log_postures(self, timestamp, track_ids, assessments, tracker, last_posture):
        """Log new tracks and posture changes once, instead of every frame."""
        for track_id, assessment in zip(track_ids, assessments):
            previous = last_posture.get(track_id)
            if previous == assessment.posture:
                continue
            prefix = f"[t={timestamp:.2f}s]"
            if previous is None:
                self.stdout.write(f"{prefix} Person track {track_id} detected.")
            if assessment.posture == NOT_LYING:
                self.stdout.write(f"{prefix} Track {track_id}: upright posture.")
            elif assessment.posture == UNCERTAIN:
                track = tracker.tracks.get(track_id)
                if track is not None and track.state != "idle":
                    self.stdout.write(f"{prefix} Track {track_id}: pose uncertain ({assessment.reason}).")
            last_posture[track_id] = assessment.posture

    def _log_event(self, event):
        prefix = f"[t={event.timestamp:.2f}s] Track {event.track_id}:"
        if event.kind == "candidate":
            transition = ""
            if event.detail.startswith("1/"):
                transition = {
                    "rapid": f", rapid descent {event.descent_seconds:.1f}s" if event.descent_seconds is not None else "",
                    "slow": f", slow descent {event.descent_seconds:.1f}s" if event.descent_seconds is not None else "",
                    "unobserved": ", already lying when first seen",
                }.get(event.transition, "")
            self.stdout.write(f"{prefix} possible lying posture ({event.detail}{transition}).")
        elif event.kind == "held":
            self.stdout.write(f"{prefix} {event.detail}.")
        elif event.kind == "candidate_reset":
            self.stdout.write(f"{prefix} candidate reset ({event.detail}).")
        elif event.kind == "confirmed":
            self.stdout.write(self.style.WARNING(
                f"{prefix} Possible Fall Detected — operator verification required."
            ))
        elif event.kind == "recovering":
            self.stdout.write(f"{prefix} recovering ({event.detail}).")
        elif event.kind == "cleared":
            self.stdout.write(self.style.SUCCESS(
                f"{prefix} visual event cleared ({event.detail}); any open incident stays open for the operator."
            ))
        elif event.kind == "expired":
            self.stdout.write(
                f"{prefix} person no longer visible; visual event cleared. Any open incident stays open for the operator."
            )

    def _notify(self, notifier, timestamp, event):
        """Try to record a confirmed event; return True when it was handled."""
        try:
            result = notifier.notify(timestamp, evidence=describe_transition(event.transition, event.descent_seconds))
        except (DatabaseError, ValidationError) as exc:
            self.stderr.write(f"Failed to record possible fall incident; will retry: {exc}")
            return False

        if result.outcome == "cooldown":
            self.stdout.write("Cooldown active; incident creation suppressed.")
        elif result.outcome == "already_active":
            self.stdout.write("Repeated event detected.")
            self.stdout.write(f"Existing unresolved fall incident #{result.incident.pk}.")
            self.stdout.write(self.style.WARNING("Duplicate suppressed."))
        else:
            incident = result.incident
            self.stdout.write(self.style.SUCCESS(f"Medical incident #{incident.pk} created: {incident.title}"))
            if incident.possible_duplicate_of_id:
                self.stdout.write(self.style.WARNING(
                    f"Possible duplicate of incident #{incident.possible_duplicate_of_id}; team assignment skipped."
                ))
            elif result.team:
                self.stdout.write(self.style.SUCCESS(f"Assigned team: {result.team.name}."))
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
