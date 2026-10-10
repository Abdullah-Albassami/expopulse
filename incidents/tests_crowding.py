"""Deterministic tests; no models, weights or video downloads required for state tests."""

from django.test import SimpleTestCase, TestCase

from incidents.cctv.crowding_state import CrowdingState, Phase
from incidents.cctv.incident_guard import get_or_create_cctv_crowding_incident
from incidents.models import Incident, IncidentSource, Location, Team
from incidents.services.assignment import assign_team_to_incident


class CrowdingStateTests(SimpleTestCase):
    def new_state(self):
        return CrowdingState(threshold=5, clear_threshold=3, frames=3, clear_seconds=10)

    def test_low_counts_never_trigger(self):
        state = self.new_state()
        self.assertEqual([state.update(2, i) for i in range(30)].count("trigger"), 0)

    def test_sustained_high_counts_trigger_once(self):
        state = self.new_state()
        events = [state.update(7, i) for i in range(300)]
        self.assertEqual(events.count("trigger"), 1)
        self.assertEqual(state.phase, Phase.ACTIVE)

    def test_flicker_does_not_flood(self):
        state = self.new_state()
        counts = [4, 5, 4, 7, 5, 3, 7, 7, 7, 4, 3, 7, 3, 5, 7, 7]
        self.assertEqual(
            [state.update(count, i) for i, count in enumerate(counts)].count("trigger"),
            1,
        )

    def test_clear_requires_sustained_low_count(self):
        state = self.new_state()
        for i in range(3):
            state.update(8, i)
        self.assertIsNone(state.update(2, 3))
        self.assertIsNone(state.update(7, 4))
        self.assertIsNone(state.update(2, 5))
        self.assertIsNone(state.update(2, 14))
        self.assertEqual(state.update(2, 15), "clear")
        self.assertEqual(state.phase, Phase.NORMAL)

    def test_disconnect_does_not_clear(self):
        state = self.new_state()
        for i in range(3):
            state.update(8, i)
        state.update(2, 3)
        state.interrupt()
        self.assertEqual(state.phase, Phase.ACTIVE)
        self.assertIsNone(state.update(2, 100))
        self.assertEqual(state.phase, Phase.RECOVERING)
        self.assertIsNone(state.update(2, 109))
        self.assertEqual(state.update(2, 110), "clear")

    def test_new_episode_after_clear(self):
        state = CrowdingState(5, 3, 2, 5)
        counts_times = [(6, 0), (6, 1), (2, 2), (2, 7), (6, 8), (6, 9)]
        events = [state.update(count, time) for count, time in counts_times]
        self.assertEqual(events, [None, "trigger", None, "clear", None, "trigger"])

    def test_invalid_configuration(self):
        with self.assertRaises(ValueError):
            CrowdingState(5, 5, 3, 10)


class CCTVIncidentGuardTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(name="Transport Hub")
        self.other_location = Location.objects.create(name="Gate 1")
        self.source = IncidentSource.objects.create(
            name="CCTV Monitoring", source_type=IncidentSource.SourceType.SENSOR
        )
        self.other_source = IncidentSource.objects.create(
            name="Staff", source_type=IncidentSource.SourceType.STAFF
        )

    def create(self, location=None, source=None):
        return get_or_create_cctv_crowding_incident(
            location=location or self.location,
            source=source or self.source,
            people_count=8,
        )

    def test_same_unresolved_alert_does_not_insert_again(self):
        incident, created = self.create()
        self.assertTrue(created)
        again, created = self.create()
        self.assertFalse(created)
        self.assertEqual(again.pk, incident.pk)
        self.assertEqual(Incident.objects.count(), 1)

    def test_after_restart_guard_still_finds_record(self):
        self.create()
        self.assertFalse(self.create()[1])

    def test_resolved_alert_allows_new_one(self):
        old, _ = self.create()
        old.status = Incident.Status.RESOLVED
        old.save()
        new, created = self.create()
        self.assertTrue(created)
        self.assertNotEqual(old.pk, new.pk)

    def test_other_location_and_source_independent(self):
        self.create()
        self.assertTrue(self.create(location=self.other_location)[1])
        self.assertTrue(self.create(source=self.other_source)[1])

    def test_other_type_not_blocked(self):
        Incident.objects.create(
            title="Other", description="Other", incident_type=Incident.IncidentType.IT,
            source=self.source, location=self.location, severity=Incident.Severity.LOW,
        )
        self.assertTrue(self.create()[1])

    def test_staff_crowding_not_blocked(self):
        Incident.objects.create(
            title="Staff report", description="Busy", incident_type=Incident.IncidentType.CROWDING,
            source=self.other_source, location=self.location, severity=Incident.Severity.HIGH,
        )
        self.assertTrue(self.create()[1])

    def test_team_assignment_only_for_new_incident(self):
        team = Team.objects.create(
            name="Security One", team_type=Team.TeamType.SECURITY,
            status=Team.Status.AVAILABLE, current_location=self.location,
        )
        first, created = self.create()
        if created:
            assign_team_to_incident(first)
        second, created = self.create()
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        team.refresh_from_db()
        self.assertEqual(team.status, Team.Status.BUSY)
        self.assertEqual(Incident.objects.count(), 1)
