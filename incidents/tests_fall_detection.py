"""Offline tests for CCTV possible-fall detection.

All pose data is synthetic and YOLO / VideoCapture are mocked, so these tests
never download weights or read real video.
"""

import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from incidents.cctv.fall_detection import (
    LYING,
    NOT_LYING,
    UNCERTAIN,
    FallEventTracker,
    FallIncidentNotifier,
    IoUTrackAssociator,
    PoseObservation,
    classify_posture,
    find_active_fall_incident,
)
from incidents.models import Incident, IncidentSource, Location, Team
from incidents.services.assignment import release_team_from_incident
from incidents.services.incident_service import create_incident


# Synthetic COCO skeletons (keypoint index -> pixel x, y). Face points 0-4
# are left out, as the classifier only uses shoulders to ankles.
UPRIGHT = {
    5: (95, 50), 6: (105, 50), 7: (92, 80), 8: (108, 80), 9: (90, 105), 10: (110, 105),
    11: (96, 110), 12: (104, 110), 13: (97, 155), 14: (103, 155), 15: (97, 200), 16: (103, 200),
}
LYING_FLAT = {
    5: (50, 195), 6: (50, 205), 7: (80, 190), 8: (80, 210), 9: (105, 188), 10: (105, 212),
    11: (110, 197), 12: (110, 203), 13: (155, 197), 14: (155, 203), 15: (200, 197), 16: (200, 203),
}
SITTING = {
    5: (95, 50), 6: (105, 50), 7: (97, 80), 8: (107, 80), 9: (110, 100), 10: (115, 100),
    11: (97, 110), 12: (103, 110), 13: (135, 112), 14: (140, 112), 15: (135, 160), 16: (140, 160),
}
CROUCHING = {
    5: (100, 120), 6: (108, 120), 7: (112, 140), 8: (118, 140), 9: (122, 155), 10: (126, 155),
    11: (110, 150), 12: (116, 150), 13: (130, 140), 14: (134, 140), 15: (118, 172), 16: (122, 172),
}
UPRIGHT_BOX = (80, 20, 120, 205)
LYING_BOX = (20, 180, 210, 215)
SITTING_BOX = (85, 25, 150, 165)
CROUCHING_BOX = (90, 100, 140, 178)


def make_observation(points, box, confidence=0.9, low_confidence=()):
    keypoints = [(0.0, 0.0)] * 17
    scores = [0.0] * 17
    for index, (x, y) in points.items():
        keypoints[index] = (float(x), float(y))
        scores[index] = 0.1 if index in low_confidence else confidence
    return PoseObservation(tuple(float(v) for v in box), tuple(keypoints), tuple(scores))


def shifted(points, dx):
    return {index: (x + dx, y) for index, (x, y) in points.items()}


class PostureClassificationTests(TestCase):
    def test_upright_pose_is_not_lying(self):
        self.assertEqual(classify_posture(make_observation(UPRIGHT, UPRIGHT_BOX)).posture, NOT_LYING)

    def test_flat_pose_is_lying(self):
        assessment = classify_posture(make_observation(LYING_FLAT, LYING_BOX))
        self.assertEqual(assessment.posture, LYING)
        self.assertGreater(assessment.axis_degrees, 80)

    def test_sitting_and_crouching_are_not_lying(self):
        self.assertNotEqual(classify_posture(make_observation(SITTING, SITTING_BOX)).posture, LYING)
        self.assertNotEqual(classify_posture(make_observation(CROUCHING, CROUCHING_BOX)).posture, LYING)

    def test_low_confidence_or_missing_keypoints_are_uncertain(self):
        low = make_observation(LYING_FLAT, LYING_BOX, low_confidence=(5, 6, 7, 8, 9, 10, 11))
        self.assertEqual(classify_posture(low).posture, UNCERTAIN)
        no_hips = make_observation(LYING_FLAT, LYING_BOX, low_confidence=(11, 12))
        self.assertEqual(classify_posture(no_hips).posture, UNCERTAIN)
        missing = PoseObservation(LYING_BOX, None, None)
        self.assertEqual(classify_posture(missing).posture, UNCERTAIN)

    def test_box_aspect_alone_cannot_create_lying(self):
        # Wide box with an upright skeleton (e.g. arms outstretched) stays not lying.
        self.assertEqual(classify_posture(make_observation(UPRIGHT, (0, 20, 300, 205))).posture, NOT_LYING)
        # Horizontal keypoints inside a tall box are vetoed to uncertain.
        self.assertEqual(classify_posture(make_observation(LYING_FLAT, (40, 0, 210, 215))).posture, UNCERTAIN)


class FallEventTrackerTests(TestCase):
    def run_sequence(self, tracker, postures, track_id=1, start=0.0, step=0.2):
        events = []
        for index, posture in enumerate(postures):
            events.extend(tracker.observe(start + index * step, [(track_id, posture)]))
        return [event.kind for event in events]

    def test_upright_walking_produces_no_event(self):
        tracker = FallEventTracker(confirm_frames=3)
        self.assertEqual(self.run_sequence(tracker, [NOT_LYING] * 20), [])
        self.assertEqual(tracker.confirmed_tracks, [])

    def test_single_brief_lying_frame_does_not_confirm(self):
        tracker = FallEventTracker(confirm_frames=3)
        kinds = self.run_sequence(tracker, [NOT_LYING, LYING, NOT_LYING, NOT_LYING])
        self.assertNotIn("confirmed", kinds)
        self.assertIn("candidate_reset", kinds)

    def test_sustained_lying_confirms_exactly_once(self):
        tracker = FallEventTracker(confirm_frames=3)
        kinds = self.run_sequence(tracker, [LYING] * 10)
        self.assertEqual(kinds.count("confirmed"), 1)
        self.assertEqual(tracker.confirmed_tracks, [1])

    def test_different_tracks_cannot_combine_evidence(self):
        tracker = FallEventTracker(confirm_frames=3)
        kinds = []
        for index, track_id in enumerate([1, 2, 1, 2]):
            kinds += [event.kind for event in tracker.observe(index * 0.2, [(track_id, LYING)])]
        self.assertNotIn("confirmed", kinds)

    def test_untracked_detections_are_ignored(self):
        tracker = FallEventTracker(confirm_frames=1)
        self.assertEqual(tracker.observe(0.0, [(None, LYING)]), [])

    def test_uncertain_and_occlusion_hold_without_repeat_confirmation(self):
        tracker = FallEventTracker(confirm_frames=3, clear_frames=3, expiry_seconds=2.0)
        kinds = self.run_sequence(tracker, [LYING, UNCERTAIN, LYING, LYING])
        self.assertEqual(kinds.count("confirmed"), 1)
        # Short occlusion (track missing for 1.5s) then lying again: no second confirmation.
        tracker.observe(2.0, [])
        kinds = [event.kind for event in tracker.observe(2.1, [(1, LYING)])]
        self.assertEqual(kinds, [])
        self.assertEqual(tracker.confirmed_tracks, [1])

    def test_candidate_dropped_after_long_uncertainty(self):
        tracker = FallEventTracker(confirm_frames=3, clear_frames=2)
        kinds = self.run_sequence(tracker, [LYING, UNCERTAIN, UNCERTAIN, UNCERTAIN, LYING, LYING])
        self.assertNotIn("confirmed", kinds)
        self.assertIn("candidate_reset", kinds)

    def test_sitting_crouching_sequence_does_not_trigger(self):
        tracker = FallEventTracker(confirm_frames=3)
        postures = [
            classify_posture(make_observation(points, box)).posture
            for points, box in [(UPRIGHT, UPRIGHT_BOX), (SITTING, SITTING_BOX), (CROUCHING, CROUCHING_BOX)] * 4
        ]
        self.assertNotIn("confirmed", self.run_sequence(tracker, postures))

    def test_confirmed_event_clears_only_after_recovery_interval(self):
        tracker = FallEventTracker(confirm_frames=2, clear_frames=3)
        self.run_sequence(tracker, [LYING, LYING])
        kinds = self.run_sequence(tracker, [NOT_LYING, NOT_LYING, LYING, NOT_LYING, NOT_LYING], start=1.0)
        self.assertNotIn("cleared", kinds)
        self.assertEqual(tracker.confirmed_tracks, [1])
        kinds = self.run_sequence(tracker, [NOT_LYING], start=3.0)
        self.assertEqual(kinds, ["cleared"])
        self.assertEqual(tracker.confirmed_tracks, [])

    def test_confirmed_event_clears_after_absence_interval(self):
        tracker = FallEventTracker(confirm_frames=2, expiry_seconds=3.0)
        self.run_sequence(tracker, [LYING, LYING])  # last seen at t=0.2
        self.assertEqual(tracker.observe(3.0, []), [])
        self.assertEqual([event.kind for event in tracker.observe(3.3, [])], ["expired"])

    def test_new_track_does_not_inherit_confirmation(self):
        tracker = FallEventTracker(confirm_frames=3, expiry_seconds=1.0)
        self.run_sequence(tracker, [LYING] * 3)
        kinds = [event.kind for event in tracker.observe(5.0, [(2, LYING)])]
        self.assertIn("expired", kinds)
        self.assertNotIn("confirmed", kinds)
        self.assertEqual(tracker.tracks[2].lying_count, 1)


class IoUTrackAssociatorTests(TestCase):
    def test_overlapping_boxes_keep_id_and_distant_boxes_get_new_ids(self):
        associator = IoUTrackAssociator(iou_threshold=0.3, expiry_seconds=1.0)
        first = associator.assign([LYING_BOX, (400, 20, 440, 200)], 0.0)
        second = associator.assign([(25, 182, 212, 216), (400, 20, 440, 200)], 0.2)
        self.assertEqual(first, second)
        self.assertNotEqual(first[0], first[1])

    def test_expired_track_id_is_not_reused(self):
        associator = IoUTrackAssociator(expiry_seconds=1.0)
        [first] = associator.assign([LYING_BOX], 0.0)
        [later] = associator.assign([LYING_BOX], 2.0)
        self.assertNotEqual(first, later)


class FallIncidentTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(name="Zone C", importance_level=Location.ImportanceLevel.MEDIUM)
        self.source = IncidentSource.objects.create(
            name="CCTV Monitoring", source_type=IncidentSource.SourceType.SENSOR,
        )
        self.team = Team.objects.create(
            name="Medical Team 1", team_type=Team.TeamType.MEDICAL, status=Team.Status.AVAILABLE,
        )

    def notifier(self, cooldown=120.0):
        return FallIncidentNotifier(location=self.location, source=self.source, cooldown_seconds=cooldown)

    def test_confirmed_event_creates_one_medical_incident_with_auto_priority(self):
        result = self.notifier().notify(10.0)
        self.assertEqual(result.outcome, "created")
        incident = result.incident
        self.assertEqual(incident.incident_type, Incident.IncidentType.MEDICAL)
        self.assertEqual(incident.source, self.source)
        self.assertEqual(incident.location, self.location)
        self.assertEqual(incident.title, "CCTV Possible Fall - Zone C")
        self.assertIn("Operator verification required", incident.description)
        self.assertGreater(incident.priority_score, 0)
        self.assertEqual(Incident.objects.count(), 1)

    def test_unresolved_incident_blocks_second_row_even_after_restart(self):
        first = self.notifier(cooldown=0).notify(10.0)
        again = self.notifier(cooldown=0).notify(0.0)  # fresh process: video clock restarts
        self.assertEqual(again.outcome, "already_active")
        self.assertEqual(again.incident.pk, first.incident.pk)
        self.assertEqual(Incident.objects.count(), 1)

    def test_resolved_incident_allows_new_episode(self):
        notifier = self.notifier(cooldown=0)
        first = notifier.notify(10.0).incident
        release_team_from_incident(first)
        second = notifier.notify(200.0)
        self.assertEqual(second.outcome, "created")
        self.assertNotEqual(second.incident.pk, first.pk)
        self.assertIsNone(find_active_fall_incident(self.location).possible_duplicate_of)

    def test_cooldown_suppresses_repeats_in_video_time(self):
        notifier = self.notifier(cooldown=120)
        first = notifier.notify(10.0).incident
        release_team_from_incident(first)
        self.assertEqual(notifier.notify(60.0).outcome, "cooldown")
        self.assertEqual(notifier.notify(131.0).outcome, "created")

    def test_available_medical_team_is_assigned(self):
        result = self.notifier().notify(0.0)
        self.assertEqual(result.team, self.team)
        result.incident.refresh_from_db()
        self.assertEqual(result.incident.status, Incident.Status.ASSIGNED)

    def test_incident_stays_new_without_available_team(self):
        self.team.status = Team.Status.BUSY
        self.team.save()
        result = self.notifier().notify(0.0)
        self.assertIsNone(result.team)
        self.assertEqual(result.incident.status, Incident.Status.NEW)

    def test_possible_duplicate_skips_assignment(self):
        staff = IncidentSource.objects.create(name="Staff", source_type=IncidentSource.SourceType.STAFF)
        existing = create_incident(
            title="Visitor fainted", description="Staff report", incident_type=Incident.IncidentType.MEDICAL,
            source=staff, location=self.location, severity=Incident.Severity.HIGH, people_affected=1,
        )
        result = self.notifier().notify(0.0)
        self.assertEqual(result.outcome, "created")
        self.assertEqual(result.incident.possible_duplicate_of, existing)
        self.assertIsNone(result.team)
        self.assertEqual(result.incident.status, Incident.Status.NEW)


class FakeCapture:
    def __init__(self, frames, fps=10.0, opened=True):
        self.frames = list(frames)
        self.fps = fps
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def get(self, prop):
        return self.fps

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.released = True


def fake_result(observations):
    if not observations:
        return SimpleNamespace(boxes=SimpleNamespace(xyxy=np.zeros((0, 4))), keypoints=None)
    return SimpleNamespace(
        boxes=SimpleNamespace(xyxy=np.array([obs.box for obs in observations])),
        keypoints=SimpleNamespace(
            xy=np.array([obs.keypoints for obs in observations]),
            conf=np.array([obs.keypoint_confidence for obs in observations]),
        ),
    )


class DetectFallsCommandTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(name="Zone C")
        Team.objects.create(name="Medical Team 1", team_type=Team.TeamType.MEDICAL)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.video = Path(tmp.name) / "clip.mp4"
        self.video.write_bytes(b"not a real video")

    def run_command(self, pose_frames, capture=None, **options):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        capture = capture or FakeCapture([frame] * len(pose_frames))
        model = MagicMock(task="pose")
        model.predict.side_effect = [[fake_result(observations)] for observations in pose_frames]
        stdout = StringIO()
        defaults = dict(video=str(self.video), location="Zone C", confirm_frames=3, sample_every=1, cooldown=0)
        defaults.update(options)
        with patch("incidents.management.commands.detect_falls.YOLO", return_value=model), \
                patch("incidents.management.commands.detect_falls.cv2.VideoCapture", return_value=capture):
            call_command("detect_falls", stdout=stdout, stderr=StringIO(), **defaults)
        return stdout.getvalue(), capture

    def test_positive_fixture_creates_one_incident_and_then_clears(self):
        lying = [make_observation(LYING_FLAT, LYING_BOX)]
        standing = [make_observation(UPRIGHT, (20, 130, 210, 215))]  # same spot, IoU 0.41 with the lying box
        output, capture = self.run_command(
            [[make_observation(UPRIGHT, UPRIGHT_BOX)]] + [lying] * 6 + [standing] * 3,
            clear_frames=3,
        )
        self.assertIn("Possible Fall confirmed", output)
        self.assertIn("Assigned team: Medical Team 1", output)
        self.assertIn("visual event cleared", output)
        self.assertEqual(Incident.objects.filter(incident_type=Incident.IncidentType.MEDICAL).count(), 1)
        self.assertTrue(capture.released)

    def test_negative_fixture_creates_no_incident(self):
        frames = [
            [make_observation(points, box)]
            for points, box in [(UPRIGHT, UPRIGHT_BOX), (SITTING, SITTING_BOX), (CROUCHING, CROUCHING_BOX)] * 4
        ]
        frames.append([])  # empty frame
        output, _ = self.run_command(frames)
        self.assertNotIn("confirmed", output)
        self.assertEqual(Incident.objects.count(), 0)

    def test_rerun_on_same_footage_is_suppressed(self):
        frames = [[make_observation(LYING_FLAT, LYING_BOX)]] * 4
        self.run_command(frames)
        output, _ = self.run_command(frames)
        self.assertIn("Suppressed: unresolved CCTV Medical incident", output)
        self.assertEqual(Incident.objects.count(), 1)

    def test_sample_every_counts_processed_frames_only(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        lying = [[make_observation(LYING_FLAT, LYING_BOX)]] * 2
        output, _ = self.run_command(lying, capture=FakeCapture([frame] * 6), sample_every=3, confirm_frames=3)
        self.assertNotIn("confirmed", output)

    def test_absent_keypoints_are_reported_and_never_confirm(self):
        frames = [[PoseObservation(LYING_BOX, None, None)]] * 5
        with patch("incidents.management.commands.detect_falls.extract_pose_observations",
                   return_value=(frames[0], True)):
            output, _ = self.run_command(frames)
        self.assertIn("no keypoints", output)
        self.assertEqual(Incident.objects.count(), 0)

    def test_invalid_options_raise_useful_errors(self):
        cases = [
            (dict(confirm_frames=0), "--confirm-frames"),
            (dict(sample_every=0), "--sample-every"),
            (dict(confidence=0), "--confidence"),
            (dict(confidence=1.5), "--confidence"),
            (dict(cooldown=-1), "--cooldown"),
            (dict(location="Nowhere"), "not found"),
            (dict(video="missing.mp4"), "Video file not found"),
        ]
        for options, message in cases:
            with self.subTest(options=options), self.assertRaisesMessage(CommandError, message):
                self.run_command([], **options)

    def test_unreadable_video_reports_error_and_releases_capture(self):
        for capture, message in [
            (FakeCapture([], opened=False), "Unable to open video"),
            (FakeCapture([]), "Unable to read any frames"),
            (FakeCapture([], fps=0), "no usable FPS"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesMessage(CommandError, message):
                    self.run_command([], capture=capture)
                self.assertTrue(capture.released)

    def test_model_load_failure_is_reported(self):
        with patch("incidents.management.commands.detect_falls.YOLO", side_effect=RuntimeError("bad weights")):
            with self.assertRaisesMessage(CommandError, "Unable to load pose model"):
                call_command("detect_falls", video=str(self.video), location="Zone C", stdout=StringIO())

    def test_non_pose_model_is_rejected(self):
        with patch("incidents.management.commands.detect_falls.YOLO", return_value=MagicMock(task="detect")):
            with self.assertRaisesMessage(CommandError, "not a pose model"):
                call_command("detect_falls", video=str(self.video), location="Zone C", stdout=StringIO())
