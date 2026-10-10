"""
Automated tests for simulated equipment fault monitoring.

Covers the 12 required cases from docs/Nasser_Equipment_Fault_Detection_Task.md
(section 8). All readings are synthetic demonstration data.
"""

import io
import json
import os
from unittest import mock
from urllib.error import HTTPError, URLError

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase

from incidents.models import Incident, IncidentSource, Location, Team
from incidents.services.assignment import release_team_from_incident
from incidents.services.equipment_monitoring import SOURCE_NAME, incident_title

URL = "/api/equipment/readings/"
TOKEN = "test-equipment-token"
TOKEN_ENV_VAR = "EXPOPULSE_EQUIPMENT_API_TOKEN"
SIMULATOR = "incidents.management.commands.simulate_equipment"


def make_reading(**overrides):
    reading = {
        "equipment_id": "ELEV-A1",
        "equipment_type": "elevator",
        "location": "Main Entrance",
        "status": "normal",
        "fault_code": None,
        "motor_temperature": 42.5,
        "timestamp": "2026-10-10T10:00:00Z",
    }
    reading.update(overrides)
    return reading


def make_fault(equipment_id="ELEV-A1", fault_code="DOOR_STUCK", **overrides):
    return make_reading(
        equipment_id=equipment_id, status="fault", fault_code=fault_code, **overrides
    )


class EquipmentTestCase(TestCase):
    """Shared setup: one location, the API token, and a POST helper."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {TOKEN_ENV_VAR: TOKEN})
        env.start()
        self.addCleanup(env.stop)
        self.location = Location.objects.create(name="Main Entrance")

    def add_maintenance_team(self, name="Maintenance Team 1"):
        return Team.objects.create(
            name=name,
            team_type=Team.TeamType.MAINTENANCE,
            status=Team.Status.AVAILABLE,
        )

    def post(self, payload, token=TOKEN, content_type="application/json"):
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        extra = {}
        if token is not None:
            extra["HTTP_X_EQUIPMENT_TOKEN"] = token
        return self.client.post(URL, data=body, content_type=content_type, **extra)

    def equipment_incidents(self, equipment_id):
        return Incident.objects.filter(title=incident_title(equipment_id)).order_by("id")


class FaultLifecycleTests(EquipmentTestCase):
    # 1. Valid normal packet: accepted, no incident.
    def test_normal_reading_is_accepted_without_incident(self):
        response = self.post(make_reading())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "accepted": True,
                "equipment_id": "ELEV-A1",
                "action": "normal",
                "incident_id": None,
            },
        )
        self.assertEqual(Incident.objects.count(), 0)

    # 2. First fault: exactly one Maintenance incident with correct fields.
    def test_first_fault_creates_one_maintenance_incident(self):
        response = self.post(make_fault())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Incident.objects.count(), 1)
        incident = Incident.objects.get()
        self.assertEqual(
            response.json(),
            {
                "accepted": True,
                "equipment_id": "ELEV-A1",
                "action": "created",
                "incident_id": incident.id,
            },
        )
        self.assertEqual(incident.title, "Equipment Fault [ELEV-A1]")
        self.assertEqual(incident.incident_type, Incident.IncidentType.MAINTENANCE)
        self.assertEqual(incident.source.name, SOURCE_NAME)
        self.assertEqual(incident.source.source_type, IncidentSource.SourceType.SENSOR)
        self.assertEqual(incident.location, self.location)
        self.assertEqual(incident.severity, Incident.Severity.HIGH)
        self.assertEqual(incident.people_affected, 0)
        self.assertIn("DOOR_STUCK", incident.description)
        self.assertIn("Simulated", incident.description)

    def test_synthetic_severity_map(self):
        expected = {
            "EMERGENCY_STOP": Incident.Severity.CRITICAL,
            "DOOR_STUCK": Incident.Severity.HIGH,
            "MOTOR_FAULT": Incident.Severity.HIGH,
            "SOMETHING_ELSE": Incident.Severity.MEDIUM,
        }
        for number, (fault_code, severity) in enumerate(expected.items()):
            equipment_id = f"DEV-{number}"
            response = self.post(make_fault(equipment_id, fault_code))
            self.assertEqual(response.status_code, 201, fault_code)
            incident = self.equipment_incidents(equipment_id).get()
            self.assertEqual(incident.severity, severity, fault_code)

    def test_equipment_source_is_reused(self):
        self.post(make_fault("ELEV-A1"))
        self.post(make_fault("ESC-001", "EMERGENCY_STOP", equipment_type="escalator"))

        self.assertEqual(IncidentSource.objects.filter(name=SOURCE_NAME).count(), 1)

    # 3. Repeated identical fault: no second incident.
    def test_repeated_fault_does_not_create_second_incident(self):
        first = self.post(make_fault())
        second = self.post(make_fault(timestamp="2026-10-10T10:00:02Z"))
        third = self.post(make_fault(timestamp="2026-10-10T10:00:04Z"))

        incident_id = first.json()["incident_id"]
        for response in (second, third):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["action"], "already_active")
            self.assertEqual(response.json()["incident_id"], incident_id)
        self.assertEqual(Incident.objects.count(), 1)

    # 4. Another fault code while already active: no second incident.
    def test_different_fault_code_while_active_is_suppressed(self):
        first = self.post(make_fault(fault_code="DOOR_STUCK"))
        second = self.post(make_fault(fault_code="EMERGENCY_STOP"))

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["action"], "already_active")
        self.assertEqual(second.json()["incident_id"], first.json()["incident_id"])
        self.assertEqual(Incident.objects.count(), 1)
        self.assertEqual(Incident.objects.get().severity, Incident.Severity.HIGH)

    # 5. Recovery: no new incident, nothing resolved, team not released.
    def test_recovery_does_not_resolve_incident_or_release_team(self):
        team = self.add_maintenance_team()
        created = self.post(make_fault())
        incident_id = created.json()["incident_id"]

        response = self.post(make_reading(status="recovered"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "recovered")
        self.assertEqual(response.json()["incident_id"], incident_id)
        self.assertEqual(Incident.objects.count(), 1)
        incident = Incident.objects.get()
        self.assertEqual(incident.status, Incident.Status.ASSIGNED)
        self.assertEqual(incident.assigned_team, team)
        team.refresh_from_db()
        self.assertEqual(team.status, Team.Status.BUSY)

    def test_recovery_without_open_incident_is_a_no_op(self):
        response = self.post(make_reading(status="recovered"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "recovered")
        self.assertIsNone(response.json()["incident_id"])
        self.assertEqual(Incident.objects.count(), 0)

    # 6. Restart-equivalent: fault after recovery while still unresolved.
    def test_fault_after_recovery_is_suppressed_while_incident_unresolved(self):
        first = self.post(make_fault())
        self.post(make_reading(status="recovered"))
        self.post(make_reading(status="normal"))

        again = self.post(make_fault())

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["action"], "already_active")
        self.assertEqual(again.json()["incident_id"], first.json()["incident_id"])
        self.assertEqual(Incident.objects.count(), 1)

    def test_fault_is_suppressed_for_every_unresolved_status(self):
        self.post(make_fault())
        incident = Incident.objects.get()

        for status in (
            Incident.Status.NEW,
            Incident.Status.ASSIGNED,
            Incident.Status.IN_PROGRESS,
        ):
            Incident.objects.filter(pk=incident.pk).update(status=status)
            response = self.post(make_fault())
            self.assertEqual(response.json()["action"], "already_active", status)
        self.assertEqual(Incident.objects.count(), 1)

    # 7. Resolved incident followed by a new fault: a new incident is created.
    def test_new_fault_after_resolution_creates_new_incident(self):
        team = self.add_maintenance_team()
        first = self.post(make_fault())
        old_incident = Incident.objects.get(pk=first.json()["incident_id"])
        release_team_from_incident(old_incident)

        second = self.post(make_fault())

        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["action"], "created")
        self.assertNotEqual(second.json()["incident_id"], old_incident.id)
        self.assertEqual(self.equipment_incidents("ELEV-A1").count(), 2)
        old_incident.refresh_from_db()
        self.assertEqual(old_incident.status, Incident.Status.RESOLVED)
        new_incident = Incident.objects.get(pk=second.json()["incident_id"])
        self.assertEqual(new_incident.status, Incident.Status.ASSIGNED)
        self.assertEqual(new_incident.assigned_team, team)

    # 8. Different equipment IDs at the same location are independent.
    def test_different_devices_at_same_location_get_separate_incidents(self):
        team_one = self.add_maintenance_team("Maintenance Team 1")
        team_two = self.add_maintenance_team("Maintenance Team 2")

        first = self.post(make_fault("ELEV-A1", "DOOR_STUCK"))
        second = self.post(make_fault("ELEV-A2", "MOTOR_FAULT"))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Incident.objects.count(), 2)
        first_incident = self.equipment_incidents("ELEV-A1").get()
        second_incident = self.equipment_incidents("ELEV-A2").get()
        self.assertEqual(first_incident.assigned_team, team_one)

        # Different devices at the same location are distinct equipment faults.
        # Both receive an available Maintenance team, without a false duplicate.
        self.assertIsNone(first_incident.possible_duplicate_of)
        self.assertIsNone(second_incident.possible_duplicate_of)
        self.assertEqual(second_incident.assigned_team, team_two)
        self.assertEqual(second_incident.status, Incident.Status.ASSIGNED)
        team_two.refresh_from_db()
        self.assertEqual(team_two.status, Team.Status.BUSY)

    def test_equipment_fault_still_flags_non_equipment_maintenance_duplicate(self):
        # Preserve the shared detector for a human-reported Maintenance incident.
        self.add_maintenance_team()
        other_source = IncidentSource.objects.create(
            name="Staff report", source_type=IncidentSource.SourceType.STAFF
        )
        from incidents.services.incident_service import create_incident

        existing = create_incident(
            title="Lift maintenance reported by staff",
            description="Maintenance requested",
            incident_type=Incident.IncidentType.MAINTENANCE,
            source=other_source,
            location=self.location,
            severity=Incident.Severity.HIGH,
        )
        response = self.post(make_fault("ELEV-A1"))
        self.assertEqual(response.status_code, 201)
        equipment_incident = self.equipment_incidents("ELEV-A1").get()
        self.assertEqual(equipment_incident.possible_duplicate_of, existing)
        self.assertIsNone(equipment_incident.assigned_team)

    def test_similar_equipment_ids_do_not_collide(self):
        self.post(make_fault("ELEV-A1"))

        response = self.post(make_fault("ELEV-A10"))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.equipment_incidents("ELEV-A1").count(), 1)
        self.assertEqual(self.equipment_incidents("ELEV-A10").count(), 1)

    # 9. Team assignment.
    def test_available_maintenance_team_is_assigned(self):
        team = self.add_maintenance_team()
        Team.objects.create(
            name="Security Team 1",
            team_type=Team.TeamType.SECURITY,
            status=Team.Status.AVAILABLE,
        )

        self.post(make_fault())

        incident = Incident.objects.get()
        self.assertIsNone(incident.possible_duplicate_of)
        self.assertEqual(incident.assigned_team, team)
        self.assertEqual(incident.status, Incident.Status.ASSIGNED)
        team.refresh_from_db()
        self.assertEqual(team.status, Team.Status.BUSY)

    def test_incident_stays_new_when_no_team_is_available(self):
        busy_team = self.add_maintenance_team()
        Team.objects.filter(pk=busy_team.pk).update(status=Team.Status.BUSY)

        response = self.post(make_fault())

        self.assertEqual(response.status_code, 201)
        incident = Incident.objects.get()
        self.assertIsNone(incident.assigned_team)
        self.assertEqual(incident.status, Incident.Status.NEW)

    def test_repeated_fault_does_not_reassign_a_team(self):
        self.post(make_fault())  # no team exists yet -> stays New
        self.add_maintenance_team()

        self.post(make_fault())

        incident = Incident.objects.get()
        self.assertIsNone(incident.assigned_team)
        self.assertEqual(incident.status, Incident.Status.NEW)


class InvalidRequestTests(EquipmentTestCase):
    # 10. Invalid input returns a useful error and never creates an incident.
    def assert_rejected(self, response, status_code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertIs(body["accepted"], False)
        self.assertTrue(body["error"])
        self.assertEqual(Incident.objects.count(), 0)

    def test_bad_json(self):
        self.assert_rejected(self.post("{not valid json"), 400)

    def test_json_that_is_not_an_object(self):
        self.assert_rejected(self.post([make_fault()]), 400)

    def test_missing_required_fields(self):
        for field in ("equipment_id", "equipment_type", "location", "status", "timestamp"):
            payload = make_fault()
            del payload[field]
            response = self.post(payload)
            self.assert_rejected(response, 400)
            self.assertIn(field, response.json()["error"])

    def test_unknown_field(self):
        response = self.post(make_fault(firmware="1.2.3"))

        self.assert_rejected(response, 400)
        self.assertIn("firmware", response.json()["error"])

    def test_invalid_field_values(self):
        invalid_payloads = {
            "blank equipment_id": make_fault(equipment_id=""),
            "unsafe equipment_id": make_fault(equipment_id="ELEV A1]"),
            "long equipment_id": make_fault(equipment_id="E" * 65),
            "non-string equipment_id": make_fault(equipment_id=7),
            "equipment_type": make_fault(equipment_type="travelator"),
            "status": make_reading(status="broken"),
            "blank location": make_fault(location="   "),
            "fault without fault_code": make_reading(status="fault", fault_code=None),
            "fault with blank fault_code": make_reading(status="fault", fault_code=""),
            "normal with fault_code": make_reading(status="normal", fault_code="DOOR_STUCK"),
            "recovered with fault_code": make_reading(status="recovered", fault_code="X"),
            "text temperature": make_fault(motor_temperature="hot"),
            "boolean temperature": make_fault(motor_temperature=True),
        }
        for label, payload in invalid_payloads.items():
            with self.subTest(label):
                self.assert_rejected(self.post(payload), 400)

    def test_non_finite_temperature(self):
        body = json.dumps(make_fault()).replace("42.5", "NaN")

        self.assert_rejected(self.post(body), 400)

    def test_bad_timestamps(self):
        for timestamp in (
            "not-a-date",
            "2026-13-45T10:00:00Z",
            "2026-10-10T10:00:00",  # no timezone
            "",
            1791647263,
            None,
        ):
            with self.subTest(timestamp=timestamp):
                self.assert_rejected(self.post(make_fault(timestamp=timestamp)), 400)

    def test_timestamp_with_offset_is_accepted(self):
        response = self.post(make_reading(timestamp="2026-10-10T13:00:00+03:00"))

        self.assertEqual(response.status_code, 200)

    def test_optional_temperature_may_be_omitted(self):
        payload = make_reading()
        del payload["motor_temperature"]
        del payload["fault_code"]

        self.assertEqual(self.post(payload).status_code, 200)

    def test_unknown_location(self):
        response = self.post(make_fault(location="Atlantis Pavilion"))

        self.assert_rejected(response, 404)

    def test_wrong_method(self):
        for method in (self.client.get, self.client.put, self.client.delete):
            response = method(URL, HTTP_X_EQUIPMENT_TOKEN=TOKEN)
            self.assert_rejected(response, 405)
            self.assertEqual(response["Allow"], "POST")

    def test_wrong_content_type(self):
        response = self.post(json.dumps(make_fault()), content_type="text/plain")

        self.assert_rejected(response, 415)

    def test_oversized_body(self):
        response = self.post(make_fault(location="x" * 5000))

        self.assert_rejected(response, 413)


class TokenTests(EquipmentTestCase):
    # 11. Missing/invalid API token is rejected; the correct token is accepted.
    def test_missing_token_is_rejected(self):
        response = self.post(make_fault(), token=None)

        self.assertEqual(response.status_code, 401)
        self.assertIs(response.json()["accepted"], False)
        self.assertEqual(Incident.objects.count(), 0)

    def test_wrong_token_is_rejected(self):
        for token in ("wrong-token", TOKEN + "x", TOKEN.upper(), ""):
            with self.subTest(token=token):
                response = self.post(make_fault(), token=token)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn(TOKEN, response.content.decode())
        self.assertEqual(Incident.objects.count(), 0)

    def test_correct_token_is_accepted(self):
        response = self.post(make_fault())

        self.assertEqual(response.status_code, 201)
        self.assertNotIn(TOKEN, response.content.decode())

    def test_endpoint_is_closed_when_server_token_is_not_configured(self):
        with mock.patch.dict(os.environ):
            del os.environ[TOKEN_ENV_VAR]
            for token in (None, "", "anything"):
                response = self.post(make_fault(), token=token)
                self.assertEqual(response.status_code, 503)
        self.assertEqual(Incident.objects.count(), 0)


class FakeHTTPResponse:
    def __init__(self, status, content):
        self.status = status
        self._content = content

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class SimulatorTests(EquipmentTestCase):
    # 12. The simulator sends real HTTP JSON messages and survives errors.
    def setUp(self):
        super().setUp()
        sleep = mock.patch(f"{SIMULATOR}.time.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def run_simulator(self, *args):
        out = io.StringIO()
        call_command("simulate_equipment", "--interval", "0", *args, stdout=out)
        return out.getvalue()

    def forward_to_django(self, request, timeout=None):
        """Stand-in for urlopen: deliver the simulator's request to the real view."""
        self.sent_requests.append(request)
        response = Client().post(
            URL,
            data=request.data,
            content_type=request.get_header("Content-type"),
            HTTP_X_EQUIPMENT_TOKEN=request.get_header("X-equipment-token"),
        )
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                "error",
                None,
                io.BytesIO(response.content),
            )
        return FakeHTTPResponse(response.status_code, response.content)

    def test_simulator_posts_json_readings_and_creates_one_incident_per_device(self):
        self.add_maintenance_team()
        self.sent_requests = []

        with mock.patch(f"{SIMULATOR}.urlopen", side_effect=self.forward_to_django):
            output = self.run_simulator()

        self.assertEqual(len(self.sent_requests), 17)
        for request in self.sent_requests:
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.full_url, "http://127.0.0.1:8000" + URL)
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertEqual(request.get_header("X-equipment-token"), TOKEN)
            reading = json.loads(request.data.decode("utf-8"))
            self.assertEqual(reading["location"], "Main Entrance")
            self.assertTrue(reading["timestamp"].endswith("Z"))

        sent = [json.loads(request.data.decode("utf-8")) for request in self.sent_requests]
        self.assertEqual(
            {reading["equipment_id"] for reading in sent},
            {"ELEV-A1", "ESC-001", "ELEV-A2"},
        )
        self.assertEqual(
            {reading["status"] for reading in sent}, {"normal", "fault", "recovered"}
        )
        self.assertIn("DOOR_STUCK", {reading["fault_code"] for reading in sent})
        self.assertIn("EMERGENCY_STOP", {reading["fault_code"] for reading in sent})

        self.assertEqual(Incident.objects.count(), 3)
        for equipment_id in ("ELEV-A1", "ESC-001", "ELEV-A2"):
            self.assertEqual(self.equipment_incidents(equipment_id).count(), 1)
        self.assertEqual(
            self.equipment_incidents("ESC-001").get().severity,
            Incident.Severity.CRITICAL,
        )
        self.assertIn(
            "17 sent, 3 incident(s) created, 6 repeat fault(s) suppressed, 0 error(s)",
            output,
        )
        self.assertNotIn(TOKEN, output)

    def test_restarting_simulator_does_not_create_more_incidents(self):
        self.sent_requests = []

        with mock.patch(f"{SIMULATOR}.urlopen", side_effect=self.forward_to_django):
            self.run_simulator()
            output = self.run_simulator()

        self.assertEqual(Incident.objects.count(), 3)
        self.assertIn(
            "17 sent, 0 incident(s) created, 9 repeat fault(s) suppressed, 0 error(s)",
            output,
        )

    def test_simulator_stops_cleanly_when_server_is_unreachable(self):
        with mock.patch(
            f"{SIMULATOR}.urlopen", side_effect=URLError("connection refused")
        ) as urlopen:
            output = self.run_simulator()

        self.assertEqual(urlopen.call_count, 3)
        self.assertIn("cannot reach server", output)
        self.assertIn("0 sent", output)
        self.assertIn("3 error(s)", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn(TOKEN, output)
        self.assertEqual(Incident.objects.count(), 0)

    def test_simulator_reports_http_errors_without_crashing(self):
        def unauthorized(request, timeout=None):
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                None,
                io.BytesIO(b'{"accepted": false, "error": "Missing or invalid token."}'),
            )

        with mock.patch(f"{SIMULATOR}.urlopen", side_effect=unauthorized) as urlopen:
            output = self.run_simulator()

        self.assertEqual(urlopen.call_count, 17)
        self.assertIn("HTTP 401 ERROR: Missing or invalid token.", output)
        self.assertIn("17 error(s)", output)
        self.assertNotIn(TOKEN, output)

    def test_simulator_stops_cleanly_on_ctrl_c(self):
        with mock.patch(f"{SIMULATOR}.urlopen", side_effect=KeyboardInterrupt):
            output = self.run_simulator("--loop")

        self.assertIn("Stopped by user", output)

    def test_simulator_requires_token(self):
        with mock.patch.dict(os.environ):
            del os.environ[TOKEN_ENV_VAR]
            with mock.patch(f"{SIMULATOR}.urlopen") as urlopen:
                with self.assertRaises(CommandError):
                    self.run_simulator()
        urlopen.assert_not_called()

    def test_simulator_rejects_negative_interval_and_bad_url(self):
        with mock.patch(f"{SIMULATOR}.urlopen") as urlopen:
            with self.assertRaises(CommandError):
                call_command("simulate_equipment", "--interval", "-1", stdout=io.StringIO())
            with self.assertRaises(CommandError):
                call_command(
                    "simulate_equipment",
                    "--interval",
                    "0",
                    "--url",
                    "file:///etc/passwd",
                    stdout=io.StringIO(),
                )
        urlopen.assert_not_called()
