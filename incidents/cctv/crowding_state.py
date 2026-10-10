"""Deterministic crowding episode state; independent of Django and YOLO."""

from enum import Enum


class Phase(str, Enum):
    NORMAL = "normal"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RECOVERING = "recovering"


class CrowdingState:
    """One trigger per confirmed episode.

    Missing observations must not be passed to update(). While recovering,
    an unobserved interval does not constitute evidence of sustained clearance.
    """

    def __init__(self, threshold, clear_threshold, frames, clear_seconds):
        if threshold < 1 or not 0 <= clear_threshold < threshold:
            raise ValueError("Require 0 <= clear_threshold < threshold")
        if frames < 1 or clear_seconds < 0:
            raise ValueError("frames must be positive and clear_seconds nonnegative")
        self.threshold = threshold
        self.clear_threshold = clear_threshold
        self.frames = frames
        self.clear_seconds = clear_seconds
        self.phase = Phase.NORMAL
        self.high_streak = 0
        self.clear_since = None
        self.last_observation = None

    def interrupt(self):
        """Pause clearance evidence during stream loss; retain an active episode."""
        if self.phase == Phase.RECOVERING:
            self.phase = Phase.ACTIVE
            self.clear_since = None
        self.last_observation = None

    def update(self, people_count, now):
        """Return 'trigger', 'clear', or None, using caller-supplied elapsed time."""
        if people_count < 0:
            raise ValueError("People count cannot be negative")
        if self.last_observation is not None and now < self.last_observation:
            raise ValueError("Observation time must not move backwards")
        self.last_observation = now

        if self.phase in (Phase.NORMAL, Phase.CANDIDATE):
            if people_count >= self.threshold:
                self.high_streak += 1
                self.phase = Phase.CANDIDATE
                if self.high_streak >= self.frames:
                    self.phase = Phase.ACTIVE
                    self.high_streak = 0
                    return "trigger"
            else:
                self.phase = Phase.NORMAL
                self.high_streak = 0
            return None

        if people_count <= self.clear_threshold:
            if self.phase != Phase.RECOVERING:
                self.phase = Phase.RECOVERING
                self.clear_since = now
            if now - self.clear_since >= self.clear_seconds:
                self.phase = Phase.NORMAL
                self.clear_since = None
                return "clear"
        else:
            self.phase = Phase.ACTIVE
            self.clear_since = None
        return None
