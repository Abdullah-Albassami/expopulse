"""Possible-fall / sustained lying-posture logic for CCTV pose estimates.

The YOLO pose model only returns person boxes and 17 COCO keypoints; it has
no fall classifier. This module adds a small, explicit rule set on top:

1. ``classify_posture`` turns one person's keypoints into LYING, NOT_LYING or
   UNCERTAIN using the principal axis of the confident body keypoints.
2. ``IoUTrackAssociator`` gives detections stable per-person track IDs.
3. ``FallEventTracker`` runs a candidate -> confirmed -> cleared state machine
   per track, using processed observations and video (or monotonic) time.
   It also measures how quickly the person went from standing to lying: a
   slow, observed lie-down (e.g. lying on a bed or floor on purpose) is only
   alerted if the lying lasts much longer.
4. ``FallIncidentNotifier`` turns a confirmation into at most one Medical
   incident per Location while a matching CCTV incident is unresolved.

Results are "possible fall" hints that need operator verification; they are
not a medical diagnosis and carry no measured accuracy.
"""

import math
import time
from collections import deque
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

RAPID = "rapid"
SLOW = "slow"
UNOBSERVED = "unobserved"

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


class StreamClock:
    """Timeline (seconds) for live HLS streams.

    HLS frames arrive in bursts: a 2 s segment may be decoded in 0.1 s and
    then nothing arrives for 2 s, so arrival time (wall or monotonic clock)
    says little about how fast something happened in the scene. The clock
    therefore follows the stream's presentation timestamps
    (``CAP_PROP_POS_MSEC``) when they are present and moving forward. When
    they are missing it falls back to the monotonic clock, and when they jump
    backwards it re-anchors. The timeline never runs backwards and continues
    across reconnects, where an outage counts at least its monotonic duration
    (so cooldowns stay meaningful).
    """

    def __init__(self, monotonic=None):
        self._monotonic = monotonic or time.monotonic
        self._start = self._monotonic()
        self._last = 0.0
        self._anchor = None  # (stream_seconds, timeline_seconds)
        self._last_position = None
        self.using_timestamps = False

    def reconnect(self):
        self._anchor = None
        self._last_position = None
        self._last = max(self._last, self._monotonic() - self._start)

    def tick(self, position_ms):
        position = position_ms / 1000.0 if position_ms and math.isfinite(position_ms) and position_ms > 0 else None
        if position is None:
            self.using_timestamps = False
            self._anchor = None
            self._last = max(self._last, self._monotonic() - self._start)
            return self._last
        self.using_timestamps = True
        if self._anchor is None or position < self._last_position:
            self._anchor = (position, self._last)
        self._last_position = position
        self._last = max(self._last, self._anchor[1] + (position - self._anchor[0]))
        return self._last


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

    def reset(self):
        """Forget all tracks (e.g. after a stream outage). IDs are still never reused."""
        self.tracks.clear()

    def expire(self, timestamp):
        for track_id, (_, last_seen) in list(self.tracks.items()):
            if timestamp - last_seen > self.expiry_seconds:
                del self.tracks[track_id]


@dataclass(frozen=True)
class FallEvent:
    kind: str  # candidate, held, candidate_reset, confirmed, recovering, cleared, expired
    track_id: int
    timestamp: float
    detail: str = ""
    transition: str = ""  # rapid, slow, unobserved (set on candidate/held/confirmed)
    descent_seconds: float | None = None


@dataclass
class _TrackState:
    state: str = "idle"  # idle, candidate, confirmed
    lying_count: int = 0
    uncertain_count: int = 0
    recovery_count: int = 0
    last_seen: float = 0.0
    candidate_start: float | None = None
    transition: str = ""
    descent_seconds: float | None = None
    held_reported: bool = False


def measure_descent(history, timestamp, lying_box, lookback_seconds=6.0):
    """Seconds from the last full-height standing observation to ``timestamp``.

    ``history`` holds (timestamp, box) of recent detections of *any* track,
    because the tracker often assigns a new ID while a person falls. Only
    boxes horizontally near the lying box are used. A box at least 1.5x as
    tall as it is wide counts as standing; the person was still standing
    while their box top was within 20% of standing height of the highest
    standing box top. Returns None when nobody was seen standing nearby
    (e.g. the person was already lying when first observed).
    """
    x1, _, x2, _ = lying_box
    length = x2 - x1
    nearby = [
        (seen_at, box) for seen_at, box in history
        if timestamp - seen_at <= lookback_seconds
        and x1 - length / 2 <= (box[0] + box[2]) / 2 <= x2 + length / 2
    ]
    standing = [box for _, box in nearby if (box[3] - box[1]) >= 1.5 * (box[2] - box[0])]
    if not standing:
        return None
    height = max(box[3] - box[1] for box in standing)
    top = min(box[1] for box in standing)
    last_standing = max(seen_at for seen_at, box in nearby if box[1] <= top + 0.2 * height)
    return timestamp - last_standing


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
    - Transition evidence (only when observations include boxes): when a
      candidate starts, ``measure_descent`` classifies it as RAPID
      (<= ``rapid_descent_seconds``), SLOW, or UNOBSERVED. RAPID and
      UNOBSERVED confirm normally, so someone first seen already lying is
      still alerted. A SLOW, observed lie-down confirms only after
      ``slow_lying_hold_seconds`` of continued lying (0 disables the hold).
    """

    confirm_frames: int = 5
    clear_frames: int = 10
    expiry_seconds: float = 3.0
    rapid_descent_seconds: float = 1.1
    slow_lying_hold_seconds: float = 60.0
    lookback_seconds: float = 6.0
    tracks: dict = field(default_factory=dict)
    history: deque = field(default_factory=deque)

    def __post_init__(self):
        if self.confirm_frames < 1 or self.clear_frames < 1:
            raise ValueError("Frame thresholds must be positive.")
        if self.expiry_seconds < 0:
            raise ValueError("Track expiry must be nonnegative.")
        if self.rapid_descent_seconds < 0 or self.slow_lying_hold_seconds < 0:
            raise ValueError("Transition thresholds must be nonnegative.")

    def reset(self):
        """Drop all per-person evidence, e.g. after a stream outage.

        Frames before and after a gap may show different people or a changed
        scene, so candidate counts must not be combined across it. A fall that
        is still visible after reconnecting is confirmed again from fresh
        evidence, and the unresolved-incident check prevents a second row.
        """
        self.tracks.clear()
        self.history.clear()

    @property
    def confirmed_tracks(self):
        return [track_id for track_id, track in self.tracks.items() if track.state == "confirmed"]

    def observe(self, timestamp, observations):
        """Process one sampled frame.

        ``observations`` is [(track_id, posture), ...] or
        [(track_id, posture, box), ...]; boxes enable transition evidence.
        """
        events = []
        for observation in observations:
            track_id, posture = observation[0], observation[1]
            box = observation[2] if len(observation) > 2 else None
            if track_id is None:
                continue
            track = self.tracks.setdefault(track_id, _TrackState())
            track.last_seen = timestamp
            events.extend(self._step(track_id, track, posture, timestamp, box))
        for observation in observations:
            if len(observation) > 2 and observation[2] is not None:
                self.history.append((timestamp, tuple(observation[2])))
        while self.history and timestamp - self.history[0][0] > self.lookback_seconds:
            self.history.popleft()
        events.extend(self._expire(timestamp))
        return events

    def _event(self, kind, track_id, track, timestamp, detail=""):
        return FallEvent(kind, track_id, timestamp, detail, track.transition, track.descent_seconds)

    def _step(self, track_id, track, posture, timestamp, box=None):
        if posture == LYING:
            track.uncertain_count = 0
            if track.state == "confirmed":
                track.recovery_count = 0
                return []
            if track.state == "idle":
                track.state = "candidate"
                if not track.transition:
                    track.candidate_start = timestamp
                    track.descent_seconds = (
                        measure_descent(self.history, timestamp, box, self.lookback_seconds)
                        if box is not None else None
                    )
                    if track.descent_seconds is None:
                        track.transition = UNOBSERVED
                    elif track.descent_seconds <= self.rapid_descent_seconds:
                        track.transition = RAPID
                    else:
                        track.transition = SLOW
            track.lying_count += 1
            if track.lying_count < self.confirm_frames:
                return [self._event("candidate", track_id, track, timestamp, f"{track.lying_count}/{self.confirm_frames}")]
            if (
                track.transition == SLOW
                and self.slow_lying_hold_seconds > 0
                and timestamp - track.candidate_start < self.slow_lying_hold_seconds
            ):
                if track.held_reported:
                    return []
                track.held_reported = True
                return [self._event(
                    "held", track_id, track, timestamp,
                    f"slow lie-down ({track.descent_seconds:.1f}s); alert only if lying continues "
                    f"{self.slow_lying_hold_seconds:g}s",
                )]
            track.state = "confirmed"
            track.recovery_count = 0
            return [self._event("confirmed", track_id, track, timestamp)]

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
                # The person was never seen getting up, so keep the transition
                # evidence (and a slow lie-down's hold timer) for when lying resumes.
                self._reset(track, keep_transition=True)
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
    def _reset(track, keep_transition=False):
        track.state = "idle"
        track.lying_count = 0
        track.uncertain_count = 0
        track.recovery_count = 0
        if not keep_transition:
            track.candidate_start = None
            track.transition = ""
            track.descent_seconds = None
            track.held_reported = False


def describe_transition(transition, descent_seconds):
    """Operator-facing summary of the transition evidence for a confirmation."""
    if transition == RAPID:
        return f"Rapid standing-to-lying transition observed ({descent_seconds:.1f} s)."
    if transition == SLOW:
        return f"Slow lie-down observed ({descent_seconds:.1f} s) and the person stayed lying."
    return "Person was already lying when first observed; no standing-to-lying transition seen."


def fall_incident_title(location):
    return f"CCTV Possible Fall - {location.name}"


def find_active_fall_incident(location, *, source_name=CCTV_SOURCE_NAME):
    """Return the unresolved CCTV possible-fall incident at this Location, if any.

    Fall incidents are identified by their stable title, so other Medical
    incidents at the same Location (staff reports or other CCTV detectors)
    are never treated as the same fall.
    """
    return (
        Incident.objects.filter(
            incident_type=Incident.IncidentType.MEDICAL,
            source__name=source_name,
            location=location,
            title=fall_incident_title(location),
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

    def notify(self, timestamp, evidence=""):
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
                + (f"{evidence} " if evidence else "")
                + "Operator verification required."
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
