
from django.db import transaction

from incidents.models import Incident
from incidents.services.priority import set_incident_priority
from incidents.services.duplicates import set_possible_duplicate


@transaction.atomic
def create_incident(
    title,
    description,
    incident_type,
    source,
    location,
    severity,
    people_affected=0,
):
    incident = Incident(
        title=title,
        description=description,
        incident_type=incident_type,
        source=source,
        location=location,
        severity=severity,
        people_affected=people_affected,
    )

    # Validate required fields and model choices
    incident.full_clean()

    # Calculate priority and detect possible duplicates
    set_incident_priority(incident)
    set_possible_duplicate(incident)

    # Save the incident with calculated fields
    incident.full_clean()
    incident.save()

    return incident

