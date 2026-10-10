from django.core.management.base import BaseCommand

from incidents.models import Incident, IncidentSource, Location, Team


class Command(BaseCommand):
    help = "Create repeatable ExpoPulse demo data."

    def handle(self, *args, **options):
        locations = self._create_locations()
        sources = self._create_sources()
        teams = self._create_teams(locations)
        incidents = self._create_incidents(locations, sources)

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded "
                f"{len(locations)} locations, {len(sources)} sources, "
                f"{len(teams)} teams, and {len(incidents)} incidents."
            )
        )

    def _create_locations(self):
        location_data = {
            "Gate 1": ("North Gate", Location.ImportanceLevel.HIGH),
            "Gate 4": ("East Gate", Location.ImportanceLevel.HIGH),
            "Zone A": ("Exhibition Hall A", Location.ImportanceLevel.MEDIUM),
            "Zone B": ("Exhibition Hall B", Location.ImportanceLevel.MEDIUM),
            "Zone C": ("Exhibition Hall C", Location.ImportanceLevel.MEDIUM),
            "Pavilion 12": ("Pavilion 12", Location.ImportanceLevel.MEDIUM),
            "Food Court": ("Central Food Court", Location.ImportanceLevel.MEDIUM),
            "Main Entrance": ("Main Entrance", Location.ImportanceLevel.CRITICAL),
            "Transport Hub": ("Transport Hub", Location.ImportanceLevel.HIGH),
            "Visitor Services Center": (
                "Visitor Services",
                Location.ImportanceLevel.MEDIUM,
            ),
        }
        locations = {}
        for name, (zone, importance_level) in location_data.items():
            location, _ = Location.objects.update_or_create(
                name=name,
                defaults={"zone": zone, "importance_level": importance_level},
            )
            locations[name] = location
        return locations

    def _create_sources(self):
        source_data = {
            "Security Staff": IncidentSource.SourceType.SECURITY,
            "Visitor Services": IncidentSource.SourceType.VISITOR_SERVICE,
            "CCTV Monitoring": IncidentSource.SourceType.SENSOR,
            "Maintenance System": IncidentSource.SourceType.MAINTENANCE,
            "IT Monitoring": IncidentSource.SourceType.SYSTEM,
            "Cleaning Team": IncidentSource.SourceType.STAFF,
            "Access Control System": IncidentSource.SourceType.SYSTEM,
            "Sensor Network": IncidentSource.SourceType.SENSOR,
        }
        sources = {}
        for name, source_type in source_data.items():
            source, _ = IncidentSource.objects.update_or_create(
                name=name,
                defaults={"source_type": source_type},
            )
            sources[name] = source
        return sources

    def _create_teams(self, locations):
        team_data = {
            "Security Team 1": (
                Team.TeamType.SECURITY,
                Team.Status.AVAILABLE,
                "Gate 4",
            ),
            "Security Team 2": (
                Team.TeamType.SECURITY,
                Team.Status.AVAILABLE,
                "Zone B",
            ),
            "Medical Team 1": (
                Team.TeamType.MEDICAL,
                Team.Status.AVAILABLE,
                "Zone C",
            ),
            "Maintenance Team 1": (
                Team.TeamType.MAINTENANCE,
                Team.Status.AVAILABLE,
                "Pavilion 12",
            ),
            "IT Team 1": (
                Team.TeamType.IT,
                Team.Status.AVAILABLE,
                "Main Entrance",
            ),
            "Cleaning Team 1": (
                Team.TeamType.CLEANING,
                Team.Status.AVAILABLE,
                "Food Court",
            ),
            "Visitor Services Team 1": (
                Team.TeamType.VISITOR_SERVICES,
                Team.Status.AVAILABLE,
                "Visitor Services Center",
            ),
        }
        teams = {}
        for name, (team_type, status, location_name) in team_data.items():
            # Existing operational teams must retain their live status and assignments.
            team, _ = Team.objects.get_or_create(
                name=name,
                defaults={
                    "team_type": team_type,
                    "status": status,
                    "current_location": locations[location_name],
                },
            )
            teams[name] = team
        return teams

    def _create_incidents(self, locations, sources):
        incident_data = [
            {
                "title": "Medical Emergency",
                "description": "A visitor requires immediate medical assistance.",
                "incident_type": Incident.IncidentType.MEDICAL,
                "location": locations["Zone C"],
                "severity": Incident.Severity.CRITICAL,
                "people_affected": 1,
                "priority_score": 100,
                "priority_level": Incident.PriorityLevel.CRITICAL,
                "source": sources["Visitor Services"],
            },
            {
                "title": "Heavy Crowd at Gate 4",
                "description": "A large crowd is forming at the east gate.",
                "incident_type": Incident.IncidentType.CROWDING,
                "location": locations["Gate 4"],
                "severity": Incident.Severity.HIGH,
                "people_affected": 120,
                "priority_score": 80,
                "priority_level": Incident.PriorityLevel.HIGH,
                "source": sources["CCTV Monitoring"],
            },
            {
                "title": "Visitor Congestion at Gate 4",
                "description": "Security staff report continued congestion at the east gate.",
                "incident_type": Incident.IncidentType.CROWDING,
                "location": locations["Gate 4"],
                "severity": Incident.Severity.HIGH,
                "people_affected": 100,
                "priority_score": 75,
                "priority_level": Incident.PriorityLevel.HIGH,
                "source": sources["Security Staff"],
            },
            {
                "title": "Elevator Failure",
                "description": "The main elevator in Pavilion 12 is not operating.",
                "incident_type": Incident.IncidentType.MAINTENANCE,
                "location": locations["Pavilion 12"],
                "severity": Incident.Severity.MEDIUM,
                "people_affected": 20,
                "priority_score": 50,
                "priority_level": Incident.PriorityLevel.MEDIUM,
                "source": sources["Maintenance System"],
            },
            {
                "title": "Access Scanner Offline",
                "description": "The access scanner at the main entrance is offline.",
                "incident_type": Incident.IncidentType.IT,
                "location": locations["Main Entrance"],
                "severity": Incident.Severity.HIGH,
                "people_affected": 50,
                "priority_score": 70,
                "priority_level": Incident.PriorityLevel.HIGH,
                "source": sources["IT Monitoring"],
            },
            {
                "title": "Spill in Food Court",
                "description": "A spill has been reported near the central seating area.",
                "incident_type": Incident.IncidentType.CLEANING,
                "location": locations["Food Court"],
                "severity": Incident.Severity.LOW,
                "people_affected": 5,
                "priority_score": 20,
                "priority_level": Incident.PriorityLevel.LOW,
                "source": sources["Cleaning Team"],
            },
        ]
        incidents = {}
        for data in incident_data:
            title = data.pop("title")
            incident, _ = Incident.objects.update_or_create(
                title=title,
                defaults=data,
            )
            incidents[title] = incident

        duplicate = incidents["Visitor Congestion at Gate 4"]
        duplicate.possible_duplicate_of = incidents["Heavy Crowd at Gate 4"]
        duplicate.save(update_fields=["possible_duplicate_of", "updated_at"])
        return incidents
