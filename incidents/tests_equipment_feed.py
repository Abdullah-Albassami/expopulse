"""
Tests for the external equipment-status feed (Paris Open Data).

* Normalization and fault-detection rules run without Django.
* The end-to-end tests replay the REAL snapshot stored in
  data/equipment/paris/ through the real /api/equipment/readings/ view.
* Small inline CSV fixtures (marked "TEST FIXTURE") reuse the real column
  layout to exercise transitions that a single snapshot cannot show
  (working -> out of service -> working).
"""

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase

from incidents.equipment_feed import paris_open_data as paris
from incidents.equipment_feed.detection import (
    FAULT_CODE,
    EquipmentStateTracker,
    Kind,
    timeline,
)
from incidents.models import Incident, Team
from incidents.services.briefing import incident_briefing
from incidents.services.equipment_monitoring import incident_title
from incidents.tests_equipment import (
    URL,
    EquipmentTestCase,
    FakeHTTPResponse,
    make_fault,
    make_reading,
)

REAL_SNAPSHOT = Path(settings.BASE_DIR) / "data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv"
COMMAND = "incidents.management.commands.monitor_equipment_feed"
HEADER = (
    "Identifiant télésurveillance;Equipement Télésurveillé;Identifiant;Equipement;"
    "Identifiant réf-équipement;Nom équipement;Type équipement;Arrondissement;Adresse;"
    "Code Postal;Ville;Complement localisation;Coordonnées géograhiques;Heure ouverture;"
    "Statut équipement;Horodatage statut"
)
NOW = datetime(2026, 10, 14, 17, 0, tzinfo=timezone.utc)


class FakeDownload(FakeHTTPResponse):
    def read(self, size=-1):
        return self._content if size < 0 else self._content[:size]


def row(ref, status, when, name="ASCENSEUR VOIE PUBLIQUE", monitored="Télé-surveillé"):
    """TEST FIXTURE row in the real Paris column layout."""
    return (
        f"1;{monitored};{ref};SITE;;{name};Ascenseur voie publique;13;1 RUE TEST;75013;PARIS;"
        f"Voie publique;48.8, 2.3;;{status};{when}"
    )


def csv_text(*rows):
    return "\n".join((HEADER,) + rows) + "\n"


def records(*rows):
    return paris.parse_snapshot(csv_text(*rows))


class NormalizationTests(SimpleTestCase):
    def test_real_snapshot_is_parsed(self):
        snapshot = paris.load_snapshot_file(REAL_SNAPSHOT)
        by_state = {}
        for record in snapshot.records:
            by_state[record.state] = by_state.get(record.state, 0) + 1
        self.assertEqual(len(snapshot.records), 33)
        self.assertEqual(by_state[paris.State.OPERATIONAL], 12)
        self.assertEqual(by_state[paris.State.OUT_OF_SERVICE], 13)
        self.assertEqual(by_state[paris.State.NOT_MONITORED], 8)

        record = next(r for r in snapshot.records if r.equipment_ref == "13904_A")
        self.assertEqual(record.equipment_id, "PARIS-13904_A")
        self.assertEqual(record.equipment_type, "elevator")
        self.assertEqual(record.state, paris.State.OUT_OF_SERVICE)
        self.assertEqual(record.raw_status, "En panne")
        self.assertEqual(
            record.status_changed_at, datetime(2026, 10, 14, 10, 49, 3, tzinfo=timezone.utc)
        )
        self.assertTrue(record.is_valid)

    def test_equipment_types(self):
        parsed = records(
            row("A1", "En fonctionnement", "2026-10-14T10:00:00+00:00", "ESCALIER VOIE PUBLIQUE"),
            row("A2", "En fonctionnement", "2026-10-14T10:00:00+00:00", "EPMR VOIE PUBLIQUE"),
            row("A3", "En fonctionnement", "2026-10-14T10:00:00+00:00", "ASCENSEUR VOIE PUBLIQUE"),
        )
        self.assertEqual([r.equipment_type for r in parsed], ["escalator", "elevator", "elevator"])

    def test_api_style_field_names_are_accepted(self):
        record = paris.normalize_row(
            {
                "identifiant": "13906",
                "nom_equipement": "ESCALIER VOIE PUBLIQUE",
                "statut_equipement": "En panne",
                "horodatage_statut": "2026-10-14T10:32:12+00:00",
            },
            1,
        )
        self.assertTrue(record.is_valid)
        self.assertEqual(record.equipment_id, "PARIS-13906")
        self.assertEqual(record.equipment_type, "escalator")

    def test_malformed_rows_are_flagged_not_guessed(self):
        parsed = records(
            row("", "En panne", "2026-10-14T10:00:00+00:00"),
            row("BAD ID!", "En panne", "2026-10-14T10:00:00+00:00"),
            row("B1", "En maintenance", "2026-10-14T10:00:00+00:00"),
            row("B2", "", "2026-10-14T10:00:00+00:00"),
            row("B3", "En panne", "not-a-date"),
            row("B4", "En panne", ""),
            row("B5", "En panne", "2026-10-14T10:00:00"),
        )
        self.assertTrue(all(not r.is_valid for r in parsed))
        self.assertIn("missing equipment identifier", parsed[0].problems)
        self.assertIn("unrecognised status 'En maintenance'", parsed[2].problems)
        self.assertEqual(parsed[2].state, paris.State.UNKNOWN)
        self.assertIn("missing status timestamp", parsed[5].problems)
        self.assertIn("no timezone", parsed[6].problems[0])

    def test_not_monitored_rows_need_no_timestamp(self):
        (record,) = records(row("C1", "Non télé-surveillé", "", monitored="Non télé-surveillé"))
        self.assertEqual(record.state, paris.State.NOT_MONITORED)
        self.assertTrue(record.is_valid)

    def test_api_export_header_is_accepted(self):
        # Header exactly as returned by the live API export (checked 2026-10-14).
        api_header = (
            "identifiant_telesurveillance;equipement_telesurveille;identifiant;equipement;"
            "identifiant_ref_equipement;nom_equipement;type_equipement;arrondissement;adresse;"
            "code_postal;ville;complement_localisation;coordonnees_geograhiques;"
            "heure_ouverture;statut;timestamp"
        )
        text = api_header + "\n" + row("13906", "En panne", "2026-10-14T10:32:12+00:00") + "\n"
        (record,) = paris.parse_snapshot(text)
        self.assertTrue(record.is_valid, record.problems)
        self.assertEqual(record.state, paris.State.OUT_OF_SERVICE)
        self.assertEqual(
            record.status_changed_at, datetime(2026, 10, 14, 10, 32, 12, tzinfo=timezone.utc)
        )

    def test_wrong_file_is_rejected(self):
        with self.assertRaises(ValueError):
            paris.parse_snapshot("name,value\nx,1\n")


class DetectionRuleTests(SimpleTestCase):
    def setUp(self):
        self.tracker = EquipmentStateTracker(stale_after=timedelta(days=7))

    def run_rows(self, *rows, now=NOW):
        return [
            self.tracker.process(r, now, "Main Entrance", "paris_open_data_replay")
            for r in records(*rows)
        ]

    def test_full_lifecycle_for_one_device(self):
        detections = self.run_rows(
            row("D1", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
            row("D1", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
            row("D1", "En panne", "2026-10-14T09:00:00+00:00"),
            row("D1", "En panne", "2026-10-14T09:00:00+00:00"),
            row("D1", "En fonctionnement", "2026-10-14T10:00:00+00:00"),
        )
        self.assertEqual(
            [d.kind for d in detections],
            [
                Kind.NORMAL_FIRST_SEEN,
                Kind.NORMAL_UNCHANGED,
                Kind.FAULT_NEW,
                Kind.FAULT_REPEAT,
                Kind.RECOVERED,
            ],
        )
        self.assertEqual(
            [d.reading["status"] if d.reading else None for d in detections],
            ["normal", None, "fault", "fault", "recovered"],
        )

    def test_fault_reading_uses_generic_code_and_points_to_source(self):
        (detection,) = self.run_rows(row("D2", "En panne", "2026-10-14T09:00:00+00:00"))
        self.assertEqual(detection.kind, Kind.FAULT_FIRST_SEEN)
        reading = detection.reading
        self.assertEqual(reading["equipment_id"], "PARIS-D2")
        self.assertEqual(reading["fault_code"], FAULT_CODE)
        self.assertEqual(reading["timestamp"], "2026-10-14T09:00:00Z")
        self.assertEqual(reading["data_source"], "paris_open_data_replay")
        self.assertIn("'En panne' since 2026-10-14T09:00:00Z", reading["source_reference"])
        self.assertNotIn("motor_temperature", reading)  # never invented

    def test_devices_are_tracked_independently(self):
        detections = self.run_rows(
            row("E1", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
            row("E2", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
            row("E1", "En panne", "2026-10-14T09:00:00+00:00"),
            row("E2", "En fonctionnement", "2026-10-14T09:30:00+00:00"),
        )
        self.assertEqual(detections[2].kind, Kind.FAULT_NEW)
        self.assertEqual(detections[3].kind, Kind.NORMAL_UNCHANGED)
        self.assertEqual(self.tracker.last_state("PARIS-E2"), paris.State.OPERATIONAL)

    def test_stale_invalid_future_outdated_and_unmonitored(self):
        detections = self.run_rows(
            row("F1", "En panne", "2026-08-01T00:00:00+00:00"),
            row("F2", "En panne", "2026-10-15T09:00:00+00:00"),
            row("F3", "En panne", "garbage"),
            row("F4", "Non télé-surveillé", "", monitored="Non télé-surveillé"),
            row("F5", "En panne", "2026-10-14T12:00:00+00:00"),
            row("F5", "En fonctionnement", "2026-10-14T11:00:00+00:00"),
        )
        kinds = [d.kind for d in detections]
        self.assertEqual(
            kinds,
            [Kind.STALE, Kind.INVALID, Kind.INVALID, Kind.NOT_MONITORED, Kind.FAULT_FIRST_SEEN,
             Kind.OUTDATED],
        )
        self.assertIn("in the future", detections[1].note)
        self.assertTrue(all(d.reading is None for i, d in enumerate(detections) if i != 4))

    def test_include_stale_acts_on_old_status(self):
        self.tracker = EquipmentStateTracker(stale_after=timedelta(days=7), include_stale=True)
        (detection,) = self.run_rows(row("G1", "En panne", "2026-08-01T00:00:00+00:00"))
        self.assertEqual(detection.kind, Kind.FAULT_FIRST_SEEN)

    def test_timeline_orders_by_status_time(self):
        ordered = timeline(
            records(
                row("H1", "En panne", "2026-10-14T12:00:00+00:00"),
                row("H2", "En panne", ""),
                row("H3", "En panne", "2026-10-14T08:00:00+00:00"),
            )
        )
        self.assertEqual([r.equipment_ref for r in ordered], ["H3", "H1", "H2"])


class ExternalReadingEndpointTests(EquipmentTestCase):
    """The existing endpoint accepts the two new optional fields only."""

    def test_external_fault_creates_honest_incident(self):
        self.add_maintenance_team()
        response = self.post(
            make_fault(
                "PARIS-13904_A",
                "OUT_OF_SERVICE",
                motor_temperature=None,
                data_source="paris_open_data_replay",
                source_reference="Paris equipment 13904_A; source status 'En panne'",
            )
        )
        self.assertEqual(response.status_code, 201)
        incident = Incident.objects.get()
        self.assertEqual(incident.severity, Incident.Severity.MEDIUM)
        self.assertEqual(incident.status, Incident.Status.ASSIGNED)
        self.assertIn("Replayed historical Paris Open Data record", incident.description)
        self.assertIn("13904_A", incident.description)
        self.assertNotIn("Simulated", incident.description)
        self.assertNotIn("Synthetic", incident.description)

        briefing = incident_briefing(incident)
        self.assertEqual(briefing["fault"], "Out of Service")
        self.assertEqual(briefing["equipment_id"], "PARIS-13904_A")
        self.assertNotIn("simulated", briefing["response"])

    def test_simulated_readings_are_unchanged(self):
        self.post(make_fault())
        self.assertIn("Simulated elevator fault DOOR_STUCK", Incident.objects.get().description)

    def test_new_fields_are_validated(self):
        bad = [
            {"data_source": "twitter"},
            {"data_source": 5},
            {"source_reference": ""},
            {"source_reference": "x" * 201},
            {"source_reference": "line\nbreak"},
            {"source_reference": 12},
        ]
        for overrides in bad:
            response = self.post(make_reading(**overrides))
            self.assertEqual(response.status_code, 400, overrides)


class MonitorCommandTests(EquipmentTestCase):
    def setUp(self):
        super().setUp()
        sleep = mock.patch(f"{COMMAND}.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.sent = []

    def forward_to_django(self, request, timeout=None):
        """Stand-in for urlopen: deliver the command's request to the real view."""
        self.sent.append(json.loads(request.data))
        response = Client().post(
            URL,
            data=request.data,
            content_type=request.get_header("Content-type"),
            HTTP_X_EQUIPMENT_TOKEN=request.get_header("X-equipment-token"),
        )
        return FakeHTTPResponse(response.status_code, response.content)

    def run_command(self, *args):
        out = io.StringIO()
        with mock.patch(
            "incidents.management.commands.simulate_equipment.urlopen",
            side_effect=self.forward_to_django,
        ):
            call_command("monitor_equipment_feed", "--interval", "0", *args, stdout=out)
        return out.getvalue()

    def write_fixture(self, name, *rows):
        path = Path(self.tmp) / name
        path.write_text(csv_text(*rows), encoding="utf-8")
        return str(path)

    @property
    def tmp(self):
        import tempfile

        if not hasattr(self, "_tmp"):
            self._tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmp.cleanup)
        return self._tmp.name

    # Acceptance criterion: a real external record produces an incident.
    def test_real_snapshot_creates_incidents_for_fresh_outages_only(self):
        self.add_maintenance_team()
        output = self.run_command("--replay", str(REAL_SNAPSHOT))

        created = Incident.objects.filter(title__startswith="Equipment Fault [PARIS-")
        self.assertEqual(
            sorted(i.title for i in created),
            sorted(
                incident_title(f"PARIS-{ref}")
                for ref in ("17802_B", "15804", "13906", "13904_A", "13918", "13917", "13922")
            ),
        )
        self.assertIn("REPLAYED HISTORICAL DATA (not live equipment telemetry)", output)
        self.assertIn("PARIS-13904_A elevator 'En panne' since 2026-10-14T10:49:03Z", output)
        self.assertIn("SKIPPED stale", output)  # e.g. 13910, out of order since 2024
        self.assertFalse(Incident.objects.filter(title=incident_title("PARIS-13910")).exists())
        self.assertTrue(all(r["fault_code"] in (None, FAULT_CODE) for r in self.sent))
        escalator = created.get(title=incident_title("PARIS-13906"))
        self.assertIn("escalator fault OUT_OF_SERVICE", escalator.description)
        # The first fault takes the only available Maintenance team.
        self.assertEqual(created.filter(status=Incident.Status.ASSIGNED).count(), 1)

    def test_replaying_again_creates_no_duplicates(self):
        self.run_command("--replay", str(REAL_SNAPSHOT), "--equipment", "13904_A")
        output = self.run_command("--replay", str(REAL_SNAPSHOT), "--equipment", "13904_A")
        self.assertEqual(self.equipment_incidents("PARIS-13904_A").count(), 1)
        self.assertIn("already_active", output)

    def test_transition_repeat_and_recovery_across_snapshots(self):
        team = self.add_maintenance_team()
        first = self.write_fixture(
            "s1.csv",
            row("T1", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
            row("T2", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
        )
        second = self.write_fixture(
            "s2.csv",
            row("T1", "En panne", "2026-10-14T09:00:00+00:00"),
            row("T2", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
        )
        third = self.write_fixture(
            "s3.csv",
            row("T1", "En panne", "2026-10-14T09:00:00+00:00"),
            row("T2", "En fonctionnement", "2026-10-14T08:00:00+00:00"),
        )
        fourth = self.write_fixture(
            "s4.csv",
            row("T1", "En fonctionnement", "2026-10-14T10:00:00+00:00"),
        )
        output = self.run_command("--replay", first, second, third, fourth)

        incidents = self.equipment_incidents("PARIS-T1")
        self.assertEqual(incidents.count(), 1)
        incident = incidents.get()
        self.assertEqual(incident.status, Incident.Status.ASSIGNED)  # not auto-resolved
        team.refresh_from_db()
        self.assertEqual(team.status, Team.Status.BUSY)  # not auto-released
        self.assertFalse(self.equipment_incidents("PARIS-T2").exists())
        self.assertIn("FAULT (changed from working to out of service)", output)
        self.assertIn("already_active", output)
        self.assertIn(f"recovered (incident #{incident.id} stays open)", output)
        self.assertEqual(
            [r["status"] for r in self.sent if r["equipment_id"] == "PARIS-T1"],
            ["normal", "fault", "fault", "recovered"],
        )

    def test_malformed_file_rows_are_skipped_without_sending(self):
        path = self.write_fixture(
            "bad.csv",
            row("M1", "En panne", "not-a-date"),
            row("M2", "Inconnu", "2026-10-14T09:00:00+00:00"),
            row("M3", "En panne", "2026-10-14T09:00:00+00:00"),
        )
        output = self.run_command("--replay", path)
        self.assertEqual([r["equipment_id"] for r in self.sent], ["PARIS-M3"])
        self.assertIn("SKIPPED invalid", output)

    def test_dry_run_sends_nothing_and_needs_no_token(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            output = self.run_command("--replay", str(REAL_SNAPSHOT), "--dry-run")
        self.assertEqual(self.sent, [])
        self.assertEqual(Incident.objects.count(), 0)
        self.assertIn("would send 'fault'", output)
        self.assertIn("Nothing was sent", output)

    def test_live_mode_fetches_the_paris_export(self):
        payload = csv_text(row("L1", "En panne", datetime.now(timezone.utc).isoformat())).encode()
        with mock.patch(f"{paris.__name__}.urlopen", return_value=FakeDownload(200, payload)) as fetch:
            output = self.run_command("--live", "--polls", "1")
        self.assertIn(paris.DATASET_ID, fetch.call_args[0][0].full_url)
        self.assertIn("LIVE DATA, poll 1", output)
        incident = self.equipment_incidents("PARIS-L1").get()
        self.assertIn("Paris Open Data live status feed", incident.description)

    def test_live_fetch_failure_is_reported(self):
        with mock.patch(f"{paris.__name__}.urlopen", side_effect=URLError("blocked")):
            output = self.run_command("--live", "--polls", "1")
        self.assertIn("cannot fetch the Paris feed", output)
        self.assertEqual(Incident.objects.count(), 0)

    def test_argument_errors(self):
        with self.assertRaises(CommandError):
            self.run_command("--replay", "does-not-exist.csv")
        with self.assertRaises(CommandError):
            self.run_command("--live", "--poll-interval", "5")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CommandError):
                self.run_command("--replay", str(REAL_SNAPSHOT))
