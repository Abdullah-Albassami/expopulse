"""Possible-fall / sustained lying-posture logic for CCTV pose estimates.

The YOLO pose model only returns person boxes and 17 COCO keypoints; it has
no fall classifier. This module adds a small, explicit rule set on top:

1. ``classify_posture`` turns one person's keypoints into LYING, NOT_LYING or
   UNCERTAIN using the principal axis of the confident body keypoints.
2. ``IoUTrackAssociator`` gives detections stable per-person track IDs.
3. ``FallEventTracker`` runs a candidate -> confirmed -> cleared state machine
   per track, using processed observations and video time.
4. ``FallIncidentNotifier`` turns a confirmation into at most one Medical
   incident per Location while a matching CCTV incident is unresolved.

Results are "possible fall" hints that need operator verification; they are
not a medical diagnosis and carry no measured accuracy.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from incidents.models import Incident


CCTV_SOURCE_NAME = "CCTV Monitoring"

# COCO keypoint indices used by YOLO pose models.
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12
BODY_KEYPOINTS = tuple(range(5, 17))  # shoulders to ankles; face points excluded
SHOULDERS = (LEFT_SHOULDER, RIGHT_SHOULDER)
HIPS = (LEFT_HIP, RIGHT_HIP)

LYING = "lying"
NOT_LYING = "not_lying"
UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class PostureThresholds:
    """Adjustable posture thresholds, tuned on side-view staged footage.

    ``lying_axis_degrees`` and ``upright_axis_degrees`` are measured between
    the body's principal keypoint axis and the image vertical (0 = upright,
    90 = horizontal). ``lying_extent_ratio`` is horizontal / vertical extent
    of the confident body keypoints. ``min_box_aspect`` is a supporting cue
    only: it can veto a lying classification but never cause one.
    """

    keypoint_confidence: float = 0.4
    min_body_keypoints: int = 6
    lying_axis_degrees: float = 55.0
    upright_axis_degrees: float = 35.0
    lying_extent_ratio: float = 1.2
    min_box_aspect: float = 0.8


@dataclass(frozen=True)
class PoseObservation:
    """One detected person in one processed frame."""

    box: tuple  # (x1, y1, x2, y2) in pixels
    keypoints: tuple  # 17 (x, y) pairs in pixels
    keypoint_confidence: tuple  # 17 confidences in [0, 1]


@dataclass(frozen=True)
class PostureAssessment:
    posture: str
    reason: str
    axis_degrees: float | None = None
    extent_ratio: float | None = None
    box_aspect: float | None = None
    keypoints_used: int = 0


def classify_posture(observation, thresholds=PostureThresholds()):
    """Classify one person's pose as LYING, NOT_LYING or UNCERTAIN."""
    x1, y1, x2, y2 = (float(value) for value in observation.box)
    box_aspect = (x2 - x1) / max(y2 - y1, 1e-6)

    keypoints = observation.keypoints
    confidence = observation.keypoint_confidence
    if keypoints is None or confidence is None or len(keypoints) < 17 or len(confidence) < 17:
        return PostureAssessment(UNCERTAIN, "keypoints missing", box_aspect=box_aspect)

    confident = [
        index for index in BODY_KEYPOINTS
        if float(confidence[index]) >= thresholds.keypoint_confidence
    ]
    if len(confident) < thresholds.min_body_keypoints:
        return PostureAssessment(
            UNCERTAIN,
            f"only {len(confident)} confident body keypoints",
            box_aspect=box_aspect,
            keypoints_used=len(confident),
        )
    if not any(index in confident for index in SHOULDERS) or not any(index in confident for index in HIPS):
        return PostureAssessment(
            UNCERTAIN,
            "shoulder or hip not confidently visible",
            box_aspect=box_aspect,
            keypoints_used=len(confident),
        )

    points = np.asarray([keypoints[index] for index in confident], dtype=float)
    centered = points - points.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(centered.T))
    major_axis = eigenvectors[:, int(np.argmax(eigenvalues))]
    axis_degrees = math.degrees(math.atan2(abs(major_axis[0]), abs(major_axis[1])))
    extent_ratio = float(np.ptp(points[:, 0])) / max(float(np.ptp(points[:, 1])), 1e-6)

    details = dict(
        axis_degrees=axis_degrees,
        extent_ratio=extent_ratio,
        box_aspect=box_aspect,
        keypoints_used=len(confident),
    )
    if (
        axis_degrees >= thresholds.lying_axis_degrees
        and extent_ratio >= thresholds.lying_extent_ratio
    ):
        if box_aspect < thresholds.min_box_aspect:
            return PostureAssessment(UNCERTAIN, "keypoints horizontal but box is tall", **details)
        return PostureAssessment(LYING, "body axis horizontal", **details)
    if axis_degrees <= thresholds.upright_axis_degrees and extent_ratio < 1.0:
        return PostureAssessment(NOT_LYING, "body axis near vertical", **details)
    return PostureAssessment(UNCERTAIN, "body axis oblique", **details)


def box_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_w * inter_h
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


@dataclass
class IoUTrackAssociator:
    """Greedy IoU association of detections to short-lived person tracks.

    Used instead of the Ultralytics tracker because ByteTrack frequently left
    low-confidence lying people without an ID in the test footage. A detection
    joins the existing track whose last box overlaps it most (IoU >= threshold);
    otherwise it starts a new track. Tracks unseen for ``expiry_seconds`` of
    video time are dropped, so evidence never carries over to a later person.
    Overlapping people can still swap IDs; that risk is documented.
    """

    iou_threshold: float = 0.3
    expiry_seconds: float = 3.0
    next_id: int = 1
    tracks: dict = field(default_factory=dict)  # track_id -> (last_box, last_seen)

    def assign(self, boxes, timestamp):
        self.expire(timestamp)
        candidates = sorted(
            (
                (box_iou(box, last_box), index, track_id)
                for index, box in enumerate(boxes)
                for track_id, (last_box, _) in self.tracks.items()
            ),
            reverse=True,
        )
        assigned = [None] * len(boxes)
        used_tracks = set()
        for iou, index, track_id in candidates:
            if iou < self.iou_threshold:
                break
            if assigned[index] is not None or track_id in used_tracks:
                continue
            assigned[index] = track_id
            used_tracks.add(track_id)

        for index, box in enumerate(boxes):
            if assigned[index] is None:
                assigned[index] = self.next_id
                self.next_id += 1
            self.tracks[assigned[index]] = (tuple(float(value) for value in box), timestamp)
        return assigned

    def expire(self, timestamp):
        for track_id, (_, last_seen) in list(self.tracks.items()):
            if timestamp - last_seen > self.expiry_seconds:
                del self.tracks[track_id]


@dataclass(frozen=True)
class FallEvent:
    kind: str  # candidate, candidate_reset, confirmed, recovering, cleared, expired
    track_id: int
    timestamp: float
    detail: str = ""


@dataclass
class _TrackState:
    state: str = "idle"  # idle, candidate, confirmed
    lying_count: int = 0
    uncertain_count: int = 0
    recovery_count: int = 0
    last_seen: float = 0.0


@dataclass
class FallEventTracker:
    """Per-track candidate -> confirmed -> cleared state machine.

    Counts are processed observations of the same track, not raw video frames.
    - ``confirm_frames`` LYING observations confirm a possible fall.
      UNCERTAIN observations neither count nor reset, but more than
      ``clear_frames`` in a row drop a candidate.
    - A NOT_LYING observation resets a candidate. While confirmed, it counts
      toward ``clear_frames`` recovery observations; LYING restarts recovery.
    - A track missing for more than ``expiry_seconds`` of video time is
      dropped; a confirmed track is then reported as expired (cleared by
      absence). Short gaps do not clear anything.
    """

    confirm_frames: int = 5
    clear_frames: int = 10
    expiry_seconds: float = 3.0
    tracks: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.confirm_frames < 1 or self.clear_frames < 1:
            raise ValueError("Frame thresholds must be positive.")
        if self.expiry_seconds < 0:
            raise ValueError("Track expiry must be nonnegative.")

    @property
    def confirmed_tracks(self):
        return [track_id for track_id, track in self.tracks.items() if track.state == "confirmed"]

    def observe(self, timestamp, observations):
        """Process one sampled frame: ``observations`` is [(track_id, posture), ...]."""
        events = []
        for track_id, posture in observations:
            if track_id is None:
                continue
            track = self.tracks.setdefault(track_id, _TrackState())
            track.last_seen = timestamp
            events.extend(self._step(track_id, track, posture, timestamp))
        events.extend(self._expire(timestamp))
        return events

    def _step(self, track_id, track, posture, timestamp):
        if posture == LYING:
            track.uncertain_count = 0
            if track.state == "confirmed":
                track.recovery_count = 0
                return []
            track.state = "candidate"
            track.lying_count += 1
            if track.lying_count >= self.confirm_frames:
                track.state = "confirmed"
                track.recovery_count = 0
                return [FallEvent("confirmed", track_id, timestamp)]
            return [FallEvent("candidate", track_id, timestamp, f"{track.lying_count}/{self.confirm_frames}")]

        if posture == NOT_LYING:
            track.uncertain_count = 0
            if track.state == "candidate":
                self._reset(track)
                return [FallEvent("candidate_reset", track_id, timestamp, "person not lying")]
            if track.state == "confirmed":
                track.recovery_count += 1
                if track.recovery_count >= self.clear_frames:
                    self._reset(track)
                    return [FallEvent("cleared", track_id, timestamp, "person recovered")]
                return [FallEvent("recovering", track_id, timestamp, f"{track.recovery_count}/{self.clear_frames}")]
            return []

        # UNCERTAIN: hold the current evidence without counting it.
        if track.state == "candidate":
            track.uncertain_count += 1
            if track.uncertain_count > self.clear_frames:
                self._reset(track)
                return [FallEvent("candidate_reset", track_id, timestamp, "pose uncertain too long")]
        return []

    def _expire(self, timestamp):
        events = []
        for track_id, track in list(self.tracks.items()):
            if timestamp - track.last_seen > self.expiry_seconds:
                if track.state == "confirmed":
                    events.append(FallEvent("expired", track_id, timestamp, "track absent"))
                del self.tracks[track_id]
        return events

    @staticmethod
    def _reset(track):
        track.state = "idle"
        track.lying_count = 0
        track.uncertain_count = 0
        track.recovery_count = 0


def fall_incident_title(location):
    return f"CCTV Possible Fall - {location.name}"


def find_active_fall_incident(location, *, source_name=CCTV_SOURCE_NAME):
    """Return an unresolved Medical CCTV incident at this Location, if any."""
    return (
        Incident.objects.filter(
            incident_type=Incident.IncidentType.MEDICAL,
            source__name=source_name,
            location=location,
        )
        .exclude(status=Incident.Status.RESOLVED)
        .order_by("-created_at", "-pk")
        .first()
    )


@dataclass(frozen=True)
class NotifyResult:
    outcome: str  # created, already_active, cooldown
    incident: Incident | None = None
    team: object = None


@dataclass
class FallIncidentNotifier:
    """Create at most one Medical incident per Location for confirmed falls.

    ``cooldown_seconds`` is measured in video time since the last incident
    this process created, so recorded-video runs are reproducible. The cooldown
    is in memory only; the unresolved-incident database check is what keeps
    suppression working after the detector restarts. The check is a plain
    pre-insert query, not a concurrency-safe uniqueness guarantee.
    """

    location: object
    source: object
    cooldown_seconds: float = 120.0
    last_created_at: float | None = None

    def notify(self, timestamp):
        from incidents.services.assignment import assign_team_to_incident
        from incidents.services.incident_service import create_incident

        if self.last_created_at is not None and timestamp - self.last_created_at < self.cooldown_seconds:
            return NotifyResult("cooldown")

        active = find_active_fall_incident(self.location, source_name=self.source.name)
        if active is not None:
            return NotifyResult("already_active", incident=active)

        incident = create_incident(
            title=fall_incident_title(self.location),
            description=(
                "Possible fall or sustained lying posture detected from CCTV pose evidence. "
                "Operator verification required."
            ),
            incident_type=Incident.IncidentType.MEDICAL,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.HIGH,
            people_affected=1,
        )
        self.last_created_at = timestamp

        team = None
        if not incident.possible_duplicate_of_id:
            team = assign_team_to_incident(incident)
        return NotifyResult("created", incident=incident, team=team)
