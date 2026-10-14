"""Create removable priority examples for an ExpoPulse classroom demonstration.

Never changes CCTV events, live monitoring, or priority thresholds.
Usage:
    python manage.py demo_priority_mix
    python manage.py demo_priority_mix --remove
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from incidents.models import Incident, IncidentSource, Location
from incidents.services.incident_service import create_incident

DEMO_PREFIX = "[DEMO PRIORITY]"


class Command(BaseCommand):
    help = "Create or remove three illustrative incidents with naturally calculated priorities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--remove", action="store_true", help="Delete only incidents created by this command."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        source_name = "Priority Mix Demo"
        if options["remove"]:
            count, _ = Incident.objects.filter(
                source__name=source_name, title__startswith=DEMO_PREFIX
            ).delete()
            self.stdout.write(self.style.SUCCESS(f"Removed {count} demo incident(s)."))
            return

        source, _ = IncidentSource.objects.get_or_create(
            name=source_name,
            defaults={"source_type": IncidentSource.SourceType.STAFF},
        )
        scenarios = (
            ("LOW", "Routine cleaning request", "Demo Low-Risk Area",
             Location.ImportanceLevel.LOW, Incident.IncidentType.CLEANING,
             Incident.Severity.LOW, 1, Incident.PriorityLevel.LOW),
            ("MEDIUM", "IT workstation connectivity issue", "Demo Standard Area",
             Location.ImportanceLevel.MEDIUM, Incident.IncidentType.IT,
             Incident.Severity.MEDIUM, 1, Incident.PriorityLevel.MEDIUM),
            ("CRITICAL", "Large-scale medical emergency exercise", "Demo Critical Area",
             Location.ImportanceLevel.CRITICAL, Incident.IncidentType.MEDICAL,
             Incident.Severity.CRITICAL, 100, Incident.PriorityLevel.CRITICAL),
        )
        for label, description, location_name, importance, kind, severity, people, expected in scenarios:
            title = f"{DEMO_PREFIX} {label} - {description}"
            location, _ = Location.objects.get_or_create(
                name=location_name,
                defaults={"importance_level": importance},
            )
            if location.importance_level != importance:
                raise ValueError(f"Demo location {location_name} has unexpected importance.")
            existing = Incident.objects.filter(source=source, title=title).first()
            if existing:
                self.stdout.write(f"Already exists: #{existing.pk} {title}")
                continue
            incident = create_incident(
                title=title,
                description="Illustrative training scenario only. Not a real CCTV or sensor alert.",
                incident_type=kind,
                source=source,
                location=location,
                severity=severity,
                people_affected=people,
            )
            if incident.priority_level != expected:
                raise ValueError(
                    f"Unexpected {label} priority for #{incident.pk}: "
                    f"{incident.priority_level} (score {incident.priority_score})."
                )
            self.stdout.write(self.style.SUCCESS(
                f"Created #{incident.pk}: {label} (calculated score {incident.priority_score})"
            ))
        self.stdout.write("Existing High-priority CCTV incidents remain unchanged.")
