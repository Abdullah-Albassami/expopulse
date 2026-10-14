
from datetime import timedelta

from django.utils import timezone

from incidents.models import Incident


def find_possible_duplicate(incident, minutes=15):
    """
    Find a recent unresolved incident with the same
    incident type and location.
    """

    time_threshold = timezone.now() - timedelta(
        minutes=minutes
    )

    duplicates = Incident.objects.filter(
        is_archived=False,
        incident_type=incident.incident_type,
        location=incident.location,
        created_at__gte=time_threshold,
    ).exclude(
        status=Incident.Status.RESOLVED
    )

    if incident.pk is not None:
        duplicates = duplicates.exclude(pk=incident.pk)

    return duplicates.order_by("-created_at", "-pk").first()


def set_possible_duplicate(incident):
    duplicate = find_possible_duplicate(incident)

    incident.possible_duplicate_of = duplicate

    return incident
