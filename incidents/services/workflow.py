
from django.core.exceptions import ValidationError

from incidents.models import Incident


ALLOWED_TRANSITIONS = {
    Incident.Status.NEW: Incident.Status.ASSIGNED,
    Incident.Status.ASSIGNED: Incident.Status.IN_PROGRESS,
    Incident.Status.IN_PROGRESS: Incident.Status.RESOLVED,
}


def can_transition(current_status, new_status):
    return ALLOWED_TRANSITIONS.get(current_status) == new_status


def update_incident_status(incident, new_status):
    if not can_transition(incident.status, new_status):
        raise ValidationError(
            f"Invalid status transition: "
            f"{incident.status} -> {new_status}"
        )

    incident.status = new_status
    incident.save(update_fields=["status", "updated_at"])

    return incident
