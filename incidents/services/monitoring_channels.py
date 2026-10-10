"""Human-readable monitoring channel labels. Incident categories remain stable."""
from incidents.models import Incident

def monitoring_channel(incident):
    title = incident.title.lower()
    source = incident.source.name if incident.source_id else ""
    if source == "CCTV Monitoring":
        if title.startswith("cctv restricted zone ["):
            return "CCTV Restricted-Area Detection"
        if "fall" in title and incident.incident_type == Incident.IncidentType.MEDICAL:
            return "CCTV Fall Detection"
        if "crowd" in title and incident.incident_type == Incident.IncidentType.CROWDING:
            return "CCTV Crowd Detection"
        return "CCTV Monitoring"
    if source == "Equipment Monitoring" and title.startswith("equipment fault ["):
        return "Elevator & Escalator Fault Monitoring"
    if source == "Manual Report":
        return "Operator report"
    return source or "Other source"
