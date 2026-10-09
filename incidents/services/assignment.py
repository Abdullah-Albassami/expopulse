from django.db import transaction

from incidents.models import Incident, Team


INCIDENT_TYPE_TO_TEAM_TYPE = {
    Incident.IncidentType.MEDICAL: Team.TeamType.MEDICAL,
    Incident.IncidentType.SECURITY: Team.TeamType.SECURITY,
    Incident.IncidentType.CROWDING: Team.TeamType.SECURITY,
    Incident.IncidentType.MAINTENANCE: Team.TeamType.MAINTENANCE,
    Incident.IncidentType.IT: Team.TeamType.IT,
    Incident.IncidentType.CLEANING: Team.TeamType.CLEANING,
    Incident.IncidentType.ACCESSIBILITY: Team.TeamType.VISITOR_SERVICES,
    Incident.IncidentType.OTHER: Team.TeamType.VISITOR_SERVICES,
}


def get_required_team_type(incident_type):
    """Return the response team type required for an incident type."""
    try:
        return INCIDENT_TYPE_TO_TEAM_TYPE[incident_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported incident type: {incident_type}") from exc


def find_suitable_team(incident):
    """Suggest the first available matching team, preferring its incident location."""
    required_team_type = get_required_team_type(incident.incident_type)
    available_teams = Team.objects.filter(
        team_type=required_team_type,
        status=Team.Status.AVAILABLE,
    ).order_by("id")

    same_location_team = available_teams.filter(
        current_location=incident.location,
    ).first()
    return same_location_team or available_teams.first()


@transaction.atomic
def assign_team_to_incident(incident, team=None):
    """Assign a suitable or explicitly selected available team to an incident."""
    if incident.assigned_team_id and team is None:
        return incident.assigned_team

    required_team_type = get_required_team_type(incident.incident_type)
    if team is None:
        team = find_suitable_team(incident)
    else:
        team = Team.objects.select_for_update().get(pk=team.pk)

    if team is None:
        return None
    if team.team_type != required_team_type:
        raise ValueError("Selected team does not match the incident type")
    if team.status != Team.Status.AVAILABLE:
        raise ValueError("Selected team is not available")

    team.status = Team.Status.BUSY
    team.save(update_fields=["status"])
    incident.assigned_team = team
    incident.status = Incident.Status.ASSIGNED
    incident.save(update_fields=["assigned_team", "status", "updated_at"])
    return team


@transaction.atomic
def release_team_from_incident(incident):
    """Resolve an incident and make its assigned team available again."""
    if incident.assigned_team_id:
        team = Team.objects.select_for_update().get(pk=incident.assigned_team_id)
        team.status = Team.Status.AVAILABLE
        team.save(update_fields=["status"])

    incident.status = Incident.Status.RESOLVED
    incident.save(update_fields=["status", "updated_at"])
    return incident
