
from incidents.services.incident_service import create_incident
from incidents.services.workflow import (
    can_transition,
    update_incident_status,
)
from django.core.exceptions import ValidationError
from incidents.services.duplicates import find_possible_duplicate
from django.utils import timezone
from datetime import timedelta
from django.test import TestCase

from incidents.models import Incident, IncidentSource, Location
from incidents.services.priority import (
    calculate_priority_score,
    get_priority_level,
    set_incident_priority,
)


class PriorityScoringTests(TestCase):

    def setUp(self):
        self.location = Location.objects.create(
            name="Zone C",
            importance_level=Location.ImportanceLevel.HIGH,
        )

        self.source = IncidentSource.objects.create(
            name="Security Control",
            source_type=IncidentSource.SourceType.SECURITY,
        )

    def test_critical_medical_incident(self):
        incident = Incident.objects.create(
            title="Medical Emergency",
            description="Visitor needs medical assistance",
            incident_type=Incident.IncidentType.MEDICAL,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.CRITICAL,
            people_affected=30,
        )

        score = calculate_priority_score(incident)

        self.assertEqual(score, 85)
        self.assertEqual(
            get_priority_level(score),
            Incident.PriorityLevel.CRITICAL,
        )

    def test_low_cleaning_incident(self):
        self.location.importance_level = (
            Location.ImportanceLevel.LOW
        )
        self.location.save()

        incident = Incident.objects.create(
            title="Cleaning Request",
            description="Cleaning required",
            incident_type=Incident.IncidentType.CLEANING,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.LOW,
            people_affected=2,
        )

        score = calculate_priority_score(incident)

        self.assertEqual(score, 23)
        self.assertEqual(
            get_priority_level(score),
            Incident.PriorityLevel.LOW,
        )

    def test_priority_fields_are_updated(self):
        incident = Incident.objects.create(
            title="Medical Emergency",
            description="Emergency at Zone C",
            incident_type=Incident.IncidentType.MEDICAL,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.CRITICAL,
            people_affected=30,
        )

        set_incident_priority(incident)
        incident.save()

        incident.refresh_from_db()

        self.assertEqual(incident.priority_score, 85)
        self.assertEqual(
            incident.priority_level,
            Incident.PriorityLevel.CRITICAL,
        )

    def test_priority_boundaries(self):
        self.assertEqual(
            get_priority_level(25),
            Incident.PriorityLevel.LOW,
        )
        self.assertEqual(
            get_priority_level(26),
            Incident.PriorityLevel.MEDIUM,
        )
        self.assertEqual(
            get_priority_level(50),
            Incident.PriorityLevel.MEDIUM,
        )
        self.assertEqual(
            get_priority_level(51),
            Incident.PriorityLevel.HIGH,
        )
        self.assertEqual(
            get_priority_level(75),
            Incident.PriorityLevel.HIGH,
        )
        self.assertEqual(
            get_priority_level(76),
            Incident.PriorityLevel.CRITICAL,
        )


class DuplicateDetectionTests(TestCase):

    def setUp(self):
        self.location = Location.objects.create(
            name="Gate 4"
        )

        self.other_location = Location.objects.create(
            name="Gate 3"
        )

        self.source = IncidentSource.objects.create(
            name="Security",
            source_type=IncidentSource.SourceType.SECURITY,
        )

    def create_incident(self, location=None, status=None):
        return Incident.objects.create(
            title="Crowding",
            description="Crowding detected",
            incident_type=Incident.IncidentType.CROWDING,
            source=self.source,
            location=location or self.location,
            severity=Incident.Severity.HIGH,
            people_affected=30,
            status=status or Incident.Status.NEW,
        )

    def test_duplicate_detected(self):
        original = self.create_incident()
        new_incident = self.create_incident()

        duplicate = find_possible_duplicate(new_incident)

        self.assertEqual(duplicate, original)

    def test_different_location(self):
        self.create_incident()
        new_incident = self.create_incident(
            location=self.other_location
        )

        duplicate = find_possible_duplicate(new_incident)

        self.assertIsNone(duplicate)

    def test_old_incident(self):
        original = self.create_incident()

        Incident.objects.filter(pk=original.pk).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )

        new_incident = self.create_incident()

        duplicate = find_possible_duplicate(new_incident)

        self.assertIsNone(duplicate)

    def test_resolved_incident(self):
        self.create_incident(
            status=Incident.Status.RESOLVED
        )

        new_incident = self.create_incident()

        duplicate = find_possible_duplicate(new_incident)

        self.assertIsNone(duplicate)


class IncidentWorkflowTests(TestCase):

    def setUp(self):
        self.location = Location.objects.create(
            name="Gate 4"
        )

        self.source = IncidentSource.objects.create(
            name="Security",
            source_type=IncidentSource.SourceType.SECURITY,
        )

        self.incident = Incident.objects.create(
            title="Crowding",
            description="Heavy crowding at Gate 4",
            incident_type=Incident.IncidentType.CROWDING,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.HIGH,
            people_affected=30,
        )

    def test_valid_transitions(self):
        self.assertTrue(
            can_transition(
                Incident.Status.NEW,
                Incident.Status.ASSIGNED,
            )
        )

        self.assertTrue(
            can_transition(
                Incident.Status.ASSIGNED,
                Incident.Status.IN_PROGRESS,
            )
        )

        self.assertTrue(
            can_transition(
                Incident.Status.IN_PROGRESS,
                Incident.Status.RESOLVED,
            )
        )

    def test_invalid_transitions(self):
        self.assertFalse(
            can_transition(
                Incident.Status.NEW,
                Incident.Status.RESOLVED,
            )
        )

        self.assertFalse(
            can_transition(
                Incident.Status.RESOLVED,
                Incident.Status.ASSIGNED,
            )
        )

    def test_complete_workflow(self):
        update_incident_status(
            self.incident,
            Incident.Status.ASSIGNED,
        )

        update_incident_status(
            self.incident,
            Incident.Status.IN_PROGRESS,
        )

        update_incident_status(
            self.incident,
            Incident.Status.RESOLVED,
        )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            Incident.Status.RESOLVED,
        )

    def test_invalid_status_update(self):
        with self.assertRaises(ValidationError):
            update_incident_status(
                self.incident,
                Incident.Status.RESOLVED,
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            Incident.Status.NEW,
        )


class IncidentCreationTests(TestCase):

    def setUp(self):
        self.location = Location.objects.create(
            name="Zone C",
            importance_level=Location.ImportanceLevel.HIGH,
        )

        self.source = IncidentSource.objects.create(
            name="Control Center",
            source_type=IncidentSource.SourceType.SYSTEM,
        )

    def create_medical_incident(self):
        return create_incident(
            title="Medical Emergency",
            description="Visitor needs medical assistance",
            incident_type=Incident.IncidentType.MEDICAL,
            source=self.source,
            location=self.location,
            severity=Incident.Severity.CRITICAL,
            people_affected=30,
        )

    def test_priority_is_saved_automatically(self):
        incident = self.create_medical_incident()

        incident.refresh_from_db()

        self.assertEqual(incident.priority_score, 85)
        self.assertEqual(
            incident.priority_level,
            Incident.PriorityLevel.CRITICAL,
        )

    def test_duplicate_reference_is_saved(self):
        original = self.create_medical_incident()
        duplicate = self.create_medical_incident()

        duplicate.refresh_from_db()

        self.assertEqual(
            duplicate.possible_duplicate_of,
            original,
        )

    def test_first_incident_has_no_duplicate(self):
        incident = self.create_medical_incident()

        self.assertIsNone(incident.possible_duplicate_of)


class IncidentManagementTests(TestCase):
    def setUp(self):
        from incidents.models import Team
        self.location = Location.objects.create(name="Demo Zone")
        self.source = IncidentSource.objects.create(name="Camera", source_type="system")
        self.team = Team.objects.create(name="Demo Security", team_type="security", status="busy")
        self.active = Incident.objects.create(
            title="Live crowd", description="Demo", incident_type="crowding",
            source=self.source, location=self.location, severity="high",
            assigned_team=self.team, status="assigned",
        )
        self.resolved = Incident.objects.create(
            title="Old alert", description="Demo", incident_type="crowding",
            source=self.source, location=self.location, severity="low",
            status="resolved",
        )

    def test_get_does_not_modify(self):
        response = self.client.get("/incidents/manage/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Incident.objects.filter(is_archived=True).count(), 0)

    def test_archive_resolved_only(self):
        response = self.client.post("/incidents/manage/", {"action": "archive_resolved", "confirm": "yes"})
        self.assertEqual(response.status_code, 302)
        self.active.refresh_from_db()
        self.resolved.refresh_from_db()
        self.assertFalse(self.active.is_archived)
        self.assertTrue(self.resolved.is_archived)

    def test_selected_active_cannot_be_archived(self):
        self.client.post("/incidents/manage/", {
            "action": "archive_selected", "confirm": "yes", "incident_ids": [self.active.pk]
        })
        self.active.refresh_from_db()
        self.assertFalse(self.active.is_archived)

    def test_prepare_demo_preserves_and_releases(self):
        from incidents.models import Team
        self.client.post("/incidents/manage/", {"action": "prepare_demo", "confirm": "yes"})
        self.active.refresh_from_db()
        self.resolved.refresh_from_db()
        self.team.refresh_from_db()
        self.assertTrue(self.active.is_archived)
        self.assertTrue(self.resolved.is_archived)
        self.assertEqual(self.active.status, "resolved")
        self.assertEqual(self.team.status, Team.Status.AVAILABLE)
        self.assertEqual(Incident.objects.count(), 2)
        self.assertEqual(Incident.objects.filter(is_archived=False).count(), 0)

    def test_restore_selected(self):
        self.resolved.is_archived = True
        self.resolved.save(update_fields=["is_archived"])
        self.client.post("/incidents/manage/", {
            "action": "restore_selected", "confirm": "yes",
            "incident_ids": [self.resolved.pk],
        })
        self.resolved.refresh_from_db()
        self.assertFalse(self.resolved.is_archived)

    def test_archived_ignored_for_duplicates(self):
        self.active.is_archived = True
        self.active.save(update_fields=["is_archived"])
        self.assertIsNone(find_possible_duplicate(self.resolved))
