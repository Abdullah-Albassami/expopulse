"""Regression tests for deterministic demo priorities and safe re-seeding."""

from django.core.management import call_command
from django.test import TestCase

from incidents.models import Incident, Team


class DemoSeedTests(TestCase):
    def seed(self):
        call_command("seed_data", verbosity=0)

    def test_fresh_samples_have_all_four_priority_levels(self):
        self.seed()
        priorities = {
            incident.title: incident.priority_level
            for incident in Incident.objects.all()
        }
        self.assertEqual(len(priorities), 6)
        self.assertEqual(priorities["Medical Emergency"], Incident.PriorityLevel.CRITICAL)
        self.assertEqual(priorities["Heavy Crowd at Gate 4"], Incident.PriorityLevel.HIGH)
        self.assertEqual(priorities["Visitor Congestion at Gate 4"], Incident.PriorityLevel.MEDIUM)
        self.assertEqual(priorities["Spill in Food Court"], Incident.PriorityLevel.LOW)

    def test_reseed_keeps_active_assignment_and_team_busy(self):
        self.seed()
        incident = Incident.objects.get(title="Access Scanner Offline")
        team = Team.objects.get(name="IT Team 1")
        incident.status = Incident.Status.IN_PROGRESS
        incident.assigned_team = team
        incident.save(update_fields=["status", "assigned_team"])
        team.status = Team.Status.BUSY
        team.save(update_fields=["status"])

        self.seed()
        incident.refresh_from_db()
        team.refresh_from_db()
        self.assertEqual(Incident.objects.count(), 6)
        self.assertEqual(incident.status, Incident.Status.IN_PROGRESS)
        self.assertEqual(incident.assigned_team, team)
        self.assertEqual(team.status, Team.Status.BUSY)

    def test_reseed_restores_archived_sample_without_resetting_active_teams(self):
        self.seed()
        sample = Incident.objects.get(title="Spill in Food Court")
        sample.is_archived = True
        sample.status = Incident.Status.RESOLVED
        sample.save(update_fields=["is_archived", "status"])
        self.seed()
        sample.refresh_from_db()
        self.assertFalse(sample.is_archived)
        self.assertEqual(sample.status, Incident.Status.NEW)
        self.assertIsNone(sample.assigned_team)
