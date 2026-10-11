"""Regression coverage for operations-center presentation and operator workflow."""
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from incidents.models import Incident, IncidentSource, Location, Team
from incidents.services.monitoring_channels import monitoring_channel


class OperationsCenterTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(name="Zone A")
        self.cctv = IncidentSource.objects.create(
            name="CCTV Monitoring", source_type=IncidentSource.SourceType.SENSOR
        )

    def incident(self, title, kind, source=None):
        return Incident.objects.create(
            title=title,
            description="Sample event",
            incident_type=kind,
            source=source or self.cctv,
            location=self.location,
            severity=Incident.Severity.HIGH,
            people_affected=1,
        )

    def test_monitoring_channels_are_specific_without_changing_incident_type(self):
        examples = (
            ("CCTV Crowding Alert - Zone A", Incident.IncidentType.CROWDING, "CCTV Crowd Detection"),
            ("CCTV Restricted Zone [STAFF_ONLY_A] - Zone A", Incident.IncidentType.SECURITY, "CCTV Restricted-Area Detection"),
            ("CCTV Fall Alert - Zone A", Incident.IncidentType.MEDICAL, "CCTV Fall Detection"),
        )
        for title, kind, expected in examples:
            with self.subTest(title=title):
                record = self.incident(title, kind)
                self.assertEqual(monitoring_channel(record), expected)
                self.assertEqual(record.incident_type, kind)

    def test_equipment_monitoring_channel(self):
        source = IncidentSource.objects.create(
            name="Equipment Monitoring", source_type=IncidentSource.SourceType.SENSOR
        )
        record = self.incident("Equipment Fault [ESC-001]", Incident.IncidentType.MAINTENANCE, source)
        self.assertEqual(monitoring_channel(record), "Elevator & Escalator Fault Monitoring")

    def test_manual_form_does_not_offer_automated_source(self):
        response = self.client.get(reverse("incident_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("source", response.context["form"].fields)
        self.assertContains(response, "Report incident manually")

    def test_post_manual_report_sets_trusted_source(self):
        response = self.client.post(reverse("incident_create"), {
            "title": "Reported fall",
            "description": "Visitor needs help",
            "incident_type": Incident.IncidentType.MEDICAL,
            "source": str(self.cctv.pk),
            "location": str(self.location.pk),
            "severity": Incident.Severity.HIGH,
            "people_affected": "1",
        })
        self.assertEqual(response.status_code, 302)
        report = Incident.objects.get(title="Reported fall")
        self.assertEqual(report.source.name, "Manual Report")
        self.assertEqual(report.source.source_type, IncidentSource.SourceType.STAFF)

    def test_seed_does_not_reset_busy_team(self):
        call_command("seed_data", verbosity=0)
        team = Team.objects.get(name="Security Team 1")
        team.status = Team.Status.BUSY
        team.save(update_fields=["status"])
        call_command("seed_data", verbosity=0)
        team.refresh_from_db()
        self.assertEqual(team.status, Team.Status.BUSY)

    def test_dashboard_feed_exposes_channel_label(self):
        self.incident("CCTV Restricted Zone [STAFF_ONLY_A] - Zone A", Incident.IncidentType.SECURITY)
        response = self.client.get(reverse("dashboard_data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["incidents"][0]["module"], "CCTV Restricted-Area Detection")

    def test_equipment_detail_shows_fault_without_zero_people_affected(self):
        source = IncidentSource.objects.create(
            name="Equipment Monitoring", source_type=IncidentSource.SourceType.SENSOR
        )
        record = self.incident("Equipment Fault [ELEV-A1]", Incident.IncidentType.MAINTENANCE, source)
        record.description = (
            "Simulated elevator fault DOOR_STUCK at Zone A (equipment ELEV-A1). "
            "Synthetic demonstration telemetry; operator verification required."
        )
        record.people_affected = 0
        record.save()
        response = self.client.get(reverse("incident_detail", args=[record.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elevator Door Stuck")
        self.assertContains(response, "ELEV-A1")
        self.assertContains(response, "Passenger impact")
        self.assertContains(response, "Not reported")
        self.assertNotContains(response, "People affected (reported)")
        record.refresh_from_db()
        self.assertEqual(record.title, "Equipment Fault [ELEV-A1]")

    def test_unrecognized_equipment_fault_does_not_make_up_details(self):
        source = IncidentSource.objects.create(
            name="Equipment Monitoring", source_type=IncidentSource.SourceType.SENSOR
        )
        record = self.incident("Equipment Fault [ESC-2]", Incident.IncidentType.MAINTENANCE, source)
        response = self.client.get(reverse("incident_detail", args=[record.pk]))
        self.assertContains(response, "Equipment Fault Detected")
        self.assertContains(response, "ESC-2")

    def test_manual_incident_keeps_reported_people_count(self):
        source = IncidentSource.objects.create(
            name="Manual Report", source_type=IncidentSource.SourceType.STAFF
        )
        record = self.incident("Spill near entrance", Incident.IncidentType.CLEANING, source)
        response = self.client.get(reverse("incident_detail", args=[record.pk]))
        self.assertContains(response, "People affected (reported)")
