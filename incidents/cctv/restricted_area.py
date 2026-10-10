import json
import math
import re
from dataclasses import dataclass
from numbers import Real
from pathlib import Path

import cv2
import numpy as np

from incidents.models import Incident


ZONE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ZoneConfigError(ValueError):
    """Raised for malformed restricted-zone configuration files."""


@dataclass(frozen=True)
class NormalizedPolygon:
    points: tuple[tuple[float, float], ...]

    def __post_init__(self):
        if len(self.points) < 3:
            raise ZoneConfigError("Polygon must have at least 3 vertices.")

        normalized = []
        seen = set()
        for idx, point in enumerate(self.points):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ZoneConfigError(
                    f"Polygon point #{idx + 1} must be a two-item coordinate."
                )
            x, y = point
            if not isinstance(x, Real) or not math.isfinite(float(x)):
                raise ZoneConfigError(f"Polygon x value at point #{idx + 1} is invalid.")
            if not isinstance(y, Real) or not math.isfinite(float(y)):
                raise ZoneConfigError(f"Polygon y value at point #{idx + 1} is invalid.")
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ZoneConfigError(
                    "Polygon coordinates must remain between 0 and 1 inclusive."
                )
            normalized.append((float(x), float(y)))
            seen.add((round(x, 12), round(y, 12)))
        if len(seen) != len(normalized):
            raise ZoneConfigError("Polygon vertices must be distinct.")
        if _polygon_area(normalized) <= 0:
            raise ZoneConfigError("Polygon area must be non-zero.")
        if _self_intersects(normalized):
            raise ZoneConfigError("Polygon must not self-intersect.")
        object.__setattr__(self, "points", tuple(normalized))

    @property
    def width(self):
        return 1.0

    @property
    def height(self):
        return 1.0

    def to_pixel_points(self, frame_width, frame_height):
        if frame_width <= 0 or frame_height <= 0:
            raise ZoneConfigError("Frame size must be positive.")
        return [
            (float(x) * float(frame_width), float(y) * float(frame_height))
            for x, y in self.points
        ]

    def contains_point(self, x, y, *, include_boundary=True):
        value = cv2.pointPolygonTest(
            np.asarray(self.points, dtype=np.float32),
            (float(x), float(y)),
            measureDist=False,
        )
        if include_boundary:
            return value >= 0
        return value > 0


class PolygonZone:
    def __init__(self, zone_id, name, polygon_points):
        self.zone_id = validate_zone_id(zone_id)
        self.name = name
        self.polygon = NormalizedPolygon(tuple(polygon_points))

    @classmethod
    def from_config(cls, config):
        try:
            zone_id = config["zone_id"]
            name = config["name"]
            points = config["polygon"]
        except KeyError as exc:
            raise ZoneConfigError(f"Missing required config field: {exc.args[0]}") from exc
        return cls(zone_id=zone_id, name=name, polygon_points=points)

    def to_pixel_points(self, frame_width, frame_height):
        return self.polygon.to_pixel_points(frame_width, frame_height)

    def contains_point(self, x, y, *, include_boundary=True, frame_width=None, frame_height=None):
        polygon_points = self.polygon.points
        if frame_width is not None and frame_height is not None:
            polygon_points = self.to_pixel_points(frame_width, frame_height)
        value = cv2.pointPolygonTest(
            np.asarray(polygon_points, dtype=np.float32),
            (float(x), float(y)),
            measureDist=False,
        )
        if include_boundary:
            return value >= 0
        return value > 0

    def contains_bbox_bottom_center(self, box_xyxy, frame_width=None, frame_height=None):
        x1, y1, x2, y2 = [float(value) for value in box_xyxy]
        px = (x1 + x2) / 2.0
        py = y2
        return self.contains_point(px, py, include_boundary=True, frame_width=frame_width, frame_height=frame_height)

    def contains_box_bottom_center(self, box_xyxy, frame_width=None, frame_height=None):
        return self.contains_bbox_bottom_center(box_xyxy, frame_width=frame_width, frame_height=frame_height)


def validate_zone_id(zone_id):
    if not isinstance(zone_id, str):
        raise ZoneConfigError("zone_id must be a string.")
    zone_id = zone_id.strip()
    if not ZONE_ID_PATTERN.fullmatch(zone_id):
        raise ZoneConfigError(
            "zone_id must be 1-64 chars and contain only letters, numbers, hyphens, or underscores."
        )
    return zone_id


def load_zone_config(config_path):
    path = Path(config_path)
    if not path.exists():
        raise ZoneConfigError(f"Zone config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ZoneConfigError("Zone config JSON must contain an object.")
    return PolygonZone.from_config(data)


def _polygon_area(points):
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        x1, y1 = point
        x2, y2 = next_point
        area += (x1 * y2) - (x2 * y1)
    return abs(area) / 2.0


def _self_intersects(points):
    count = len(points)
    for index in range(count):
        p1 = points[index]
        p2 = points[(index + 1) % count]
        for other_index in range(index + 1, count):
            if other_index in (index, (index + 1) % count, (index - 1) % count):
                continue
            q1 = points[other_index]
            q2 = points[(other_index + 1) % count]
            if p1 in (q1, q2) or p2 in (q1, q2):
                continue
            if _segments_intersect(p1, p2, q1, q2):
                return True
    return False


def _segments_intersect(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    o1 = orient(p1, p2, q1)
    o2 = orient(p1, p2, q2)
    o3 = orient(q1, q2, p1)
    o4 = orient(q1, q2, p2)

    if (o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0):
        if (o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0):
            return True
    if abs(o1) < 1e-9 and _on_segment(p1, q1, p2):
        return True
    if abs(o2) < 1e-9 and _on_segment(p1, q2, p2):
        return True
    if abs(o3) < 1e-9 and _on_segment(q1, p1, q2):
        return True
    if abs(o4) < 1e-9 and _on_segment(q1, p2, q2):
        return True
    return False


def _on_segment(a, b, c):
    return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])


def get_bottom_center_from_xyxy(box_xyxy):
    x1, y1, x2, y2 = [float(value) for value in box_xyxy]
    return ((x1 + x2) / 2.0, y2)


def is_point_in_zone(zone, point_x, point_y, *, frame_width=None, frame_height=None):
    if frame_width is not None and frame_height is not None:
        pixel_polygon = zone.to_pixel_points(frame_width, frame_height)
        return cv2.pointPolygonTest(
            np.asarray(pixel_polygon, dtype=np.float32),
            (float(point_x), float(point_y)),
            measureDist=False,
        ) >= 0
    return cv2.pointPolygonTest(
        np.asarray(zone.polygon.points, dtype=np.float32),
        (float(point_x), float(point_y)),
        measureDist=False,
    ) >= 0


@dataclass
class ZonePresenceTracker:
    confirm_frames: int = 5
    clear_frames: int = 10
    active_track_id: str | None = None
    state: str = "outside"
    candidate_counter: int = 0
    clear_counter: int = 0
    active_event: bool = False

    def reset(self):
        self.active_track_id = None
        self.state = "outside"
        self.candidate_counter = 0
        self.clear_counter = 0
        self.active_event = False

    def observe(self, track_id, inside_zone):
        if track_id is None:
            return "ignored"

        if inside_zone:
            if self.state == "outside":
                self.active_track_id = str(track_id)
                self.state = "candidate_inside"
                self.candidate_counter = 1
                self.clear_counter = 0
                return "candidate"

            if self.state == "candidate_inside":
                if self.active_track_id != str(track_id):
                    self.active_track_id = str(track_id)
                    self.candidate_counter = 1
                    self.clear_counter = 0
                    return "candidate"
                self.candidate_counter += 1
                if self.candidate_counter >= self.confirm_frames:
                    self.state = "confirmed"
                    self.active_event = True
                    return "confirmed"
                return "candidate"

            if self.state == "clearing":
                if self.active_track_id != str(track_id):
                    return "confirmed"
                self.clear_counter = 0
                self.state = "confirmed"
                self.active_event = True
                return "confirmed"

            if self.state == "confirmed":
                self.active_event = True
                return "confirmed"

            return self.state

        if self.state == "candidate_inside":
            if self.active_track_id == str(track_id):
                self.reset()
            return "outside"

        if self.state == "confirmed":
            if self.active_track_id == str(track_id):
                self.state = "clearing"
                self.clear_counter = 1
                self.active_event = True
                return "clearing"
            return "confirmed"

        if self.state == "clearing":
            if self.active_track_id == str(track_id):
                self.clear_counter += 1
                if self.clear_counter >= self.clear_frames:
                    self.reset()
                    return "cleared"
                return "clearing"
            return "clearing"

        return "outside"


def find_active_restricted_zone_incident(location, zone_id, *, source_name="CCTV Monitoring"):
    from incidents.models import IncidentSource

    return (
        Incident.objects.filter(
            incident_type=Incident.IncidentType.SECURITY,
            source__name=source_name,
            location=location,
            title=f"CCTV Restricted Zone [{zone_id}] - {location.name}",
            status__in=[
                Incident.Status.NEW,
                Incident.Status.ASSIGNED,
                Incident.Status.IN_PROGRESS,
            ],
        )
        .exclude(status=Incident.Status.RESOLVED)
        .first()
    )
