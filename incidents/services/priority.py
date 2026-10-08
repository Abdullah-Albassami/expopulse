
from incidents.models import Incident, Location


SEVERITY_SCORES = {
    Incident.Severity.LOW: 10,
    Incident.Severity.MEDIUM: 20,
    Incident.Severity.HIGH: 30,
    Incident.Severity.CRITICAL: 40,
}

PEOPLE_SCORES = [
    (5, 5),
    (20, 10),
    (50, 15),
    (100, 20),
]

LOCATION_SCORES = {
    Location.ImportanceLevel.LOW: 5,
    Location.ImportanceLevel.MEDIUM: 10,
    Location.ImportanceLevel.HIGH: 15,
    Location.ImportanceLevel.CRITICAL: 20,
}

SAFETY_SCORES = {
    Incident.IncidentType.MEDICAL: 15,
    Incident.IncidentType.SECURITY: 15,
    Incident.IncidentType.CROWDING: 12,
    Incident.IncidentType.ACCESSIBILITY: 10,
    Incident.IncidentType.MAINTENANCE: 8,
    Incident.IncidentType.IT: 6,
    Incident.IncidentType.CLEANING: 3,
    Incident.IncidentType.OTHER: 5,
}


def get_people_score(people_affected):
    for maximum, score in PEOPLE_SCORES:
        if people_affected <= maximum:
            return score

    return 25


def get_priority_level(score):
    if score <= 25:
        return Incident.PriorityLevel.LOW
    if score <= 50:
        return Incident.PriorityLevel.MEDIUM
    if score <= 75:
        return Incident.PriorityLevel.HIGH

    return Incident.PriorityLevel.CRITICAL


def calculate_priority_score(incident):
    severity_score = SEVERITY_SCORES[incident.severity]

    people_score = get_people_score(
        incident.people_affected
    )

    location_score = LOCATION_SCORES[
        incident.location.importance_level
    ]

    safety_score = SAFETY_SCORES[incident.incident_type]

    total_score = (
        severity_score
        + people_score
        + location_score
        + safety_score
    )

    return min(100, max(0, total_score))


def set_incident_priority(incident):
    score = calculate_priority_score(incident)

    incident.priority_score = score
    incident.priority_level = get_priority_level(score)

    return incident
