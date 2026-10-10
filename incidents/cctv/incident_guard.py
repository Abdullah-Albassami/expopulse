"""CCTV-specific incident suppression (separate from general duplicate linking)."""

from django.db import transaction

from incidents.models import Incident, Location
from incidents.services.incident_service import create_incident


@transaction.atomic
def get_or_create_cctv_crowding_incident(*, source, location, people_count):
    """Return (incident, created).

    Lock the location row to serialize cooperating detector processes on
    databases supporting SELECT FOR UPDATE (e.g. PostgreSQL). SQLite does
    not provide equivalent row-level locking; no exactly-once guarantee there.
    """
    Location.objects.select_for_update().get(pk=location.pk)
    existing = (
        Incident.objects.filter(
            incident_type=Incident.IncidentType.CROWDING,
            source_id=source.pk,
            location_id=location.pk,
        )
        .exclude(status=Incident.Status.RESOLVED)
        .order_by("-created_at", "-pk")
        .first()
    )
    if existing is not None:
        return existing, False

    incident = create_incident(
        title=f"CCTV Crowding Alert - {location.name}",
        description=(
            f"Automated CCTV monitoring detected {people_count} people "
            f"at {location.name}. Operator verification required."
        ),
        incident_type=Incident.IncidentType.CROWDING,
        source=source,
        location=location,
        severity=Incident.Severity.HIGH,
        people_affected=people_count,
    )
    return incident, True
