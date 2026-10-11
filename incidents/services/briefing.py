"""Presentation-only incident briefing. Never change stored detector identifiers."""
import re

from incidents.models import Incident
from incidents.services.monitoring_channels import monitoring_channel

_EQUIPMENT_ID = re.compile(r"^Equipment Fault \[([A-Za-z0-9_-]+)\]$")
_FAULT = re.compile(r"\b(elevator|escalator) fault ([A-Za-z0-9_-]+) at ", re.IGNORECASE)
_FRIENDLY = {
    "DOOR_STUCK": "Door Stuck",
    "EMERGENCY_STOP": "Emergency Stop",
    "MOTOR_FAULT": "Motor Fault",
}

def incident_briefing(incident):
    channel = monitoring_channel(incident)
    briefing = {
        "title": incident.title,
        "equipment_id": None,
        "equipment_type": None,
        "fault": None,
        "response": None,
        "show_people": True,
    }
    if channel == "Elevator & Escalator Fault Monitoring":
        match = _EQUIPMENT_ID.fullmatch(incident.title)
        detected = _FAULT.search(incident.description or "")
        device_id = match.group(1) if match else None
        equipment_type = detected.group(1).capitalize() if detected else "Equipment"
        fault_code = detected.group(2).upper() if detected else None
        fault_label = _FRIENDLY.get(fault_code, fault_code.replace("_", " ").title() if fault_code else "Fault Detected")
        briefing.update(
            title=f"{equipment_type} {fault_label} — {incident.location.name}",
            equipment_id=device_id,
            equipment_type=equipment_type,
            fault=fault_label,
            response=(
                "Have maintenance verify the reported fault, check whether anyone needs assistance, "
                "and assess safe operation. Escalate immediately if people are trapped or injured. "
                "The simulated telemetry has not confirmed passenger impact."
            ),
            show_people=False,
        )
    elif channel == "CCTV Restricted-Area Detection":
        briefing["title"] = f"Possible Restricted-Area Entry — {incident.location.name}"
        briefing["response"] = "Ask security to verify the footage and check the restricted zone before taking action."
    elif channel == "CCTV Crowd Detection":
        briefing["title"] = f"Possible Crowd Congestion — {incident.location.name}"
        briefing["response"] = "Ask security to verify crowding and assess safe movement through the affected area."
    elif channel == "CCTV Fall Detection":
        briefing["title"] = f"Possible Person Fall — {incident.location.name}"
        briefing["response"] = "Request immediate operator verification and medical assessment where necessary."
    return briefing
