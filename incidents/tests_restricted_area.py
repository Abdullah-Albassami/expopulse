import json
import tempfile
from pathlib import Path

from django.test import TestCase

from incidents.cctv.restricted_area import (
    PolygonZone,
    ZoneConfigError,
    ZonePresenceTracker,
    find_active_restricted_zone_incident,
    load_zone_config,
)
from incidents.models import Incident, IncidentSource, Location
from incidents.services.incident_service import create_incident


class RestrictedAreaGeometryTests(TestCase):
    def test_normalized_polygon_contains_expected_points(self):
        zone = PolygonZone("ZONE_A", "Zone A", [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]])
        self.assertTrue(zone.contains_point(0.5, 0.5))
        self.assertTrue(zone.contains_point(0.1, 0.1))
        self.assertFalse(zone.contains_point(0.95, 0.95))

    def test_rejects_invalid_polygon_config(self):
        with self.assertRaises(ZoneConfigError):
            PolygonZone("BAD", "Bad", [[0.2, 0.2], [0.3, 0.3]])

        with self.assertRaises(ZoneConfigError):
            PolygonZone("BAD", "Bad", [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

    def test_load_zone_config_reads_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "zone.json"
            config_path.write_text(json.dumps({
                "zone_id": "ZONE_1",
                "name": "Test Zone",
                "polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
            }), encoding="utf-8")
            zone = load_zone_config(str(config_path))
            self.assertEqual(zone.zone_id, "ZONE_1")
            self.assertEqual(zone.name, "Test Zone")

    def test_tracker_requires_same_track_for_confirmation(self):
        tracker = ZonePresenceTracker(confirm_frames=3, clear_frames=2)
        self.assertEqual(tracker.observe("A", True), "candidate")
        self.assertEqual(tracker.observe("A", True), "candidate")
        self.assertEqual(tracker.observe("B", True), "candidate")
        self.assertEqual(tracker.state, "candidate_inside")


class RestrictedAreaIncidentTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(name="Zone A")
        self.source = IncidentSource.objects.create(name="CCTV Monitoring", source_type=IncidentSource.SourceType.SENSOR)

    def test_same_unresolved_incident_suppresses_duplicate_row(self):
        zone_id = "STAFF_ONLY_A"
        title = f"CCTV Restricted Zone [{zone_id}] - {self.location.name}"

        first = create_incident(
            title=title,
            description="Possible person presence detected in restricted area.",
            incident_type=Incident.IncidentType.SECURITY,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.HIGH,
            people_affected=1,
        )

        active = find_active_restricted_zone_incident(self.location, zone_id)
        self.assertEqual(active.pk, first.pk)

    def test_unrelated_security_incident_is_not_treated_as_same_zone(self):
        other_title = f"CCTV Restricted Zone [OTHER_ZONE] - {self.location.name}"
        create_incident(
            title=other_title,
            description="Different zone",
            incident_type=Incident.IncidentType.SECURITY,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.HIGH,
            people_affected=1,
        )
        self.assertIsNone(find_active_restricted_zone_incident(self.location, "STAFF_ONLY_A"))
