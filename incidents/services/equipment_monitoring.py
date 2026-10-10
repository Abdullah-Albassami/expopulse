"""
Equipment fault monitoring service (PROTOTYPE - simulated telemetry only).

Receives one validated telemetry reading for an elevator or escalator and
decides whether an ExpoPulse Maintenance incident must be created.

Central rule
------------
One active fault per equipment ID = at most one unresolved incident.

How an incident is linked to a device (no schema change)
--------------------------------------------------------
The incident title follows an exact naming convention:

    Equipment Fault [<equipment_id>]

The lookup uses an exact title match, and equipment IDs are restricted to
letters, digits, hyphens and underscores, so "ELEV-A1" can never collide
with "ELEV-A10".

Limitations
-----------
* All readings, fault codes and severities are synthetic demonstration data.
  They are not manufacturer telemetry or approved safety thresholds.
* Duplicate prevention is "check, then create" guarded by a process-level
  lock. That is safe for the local single-process demo (runserver). It is
  NOT an atomic uniqueness guarantee: several server processes could still
  race, because there is no database constraint.
* This is not industrial telemetry event sourcing; normal and recovered
  readings are only logged, not stored.
"""

import logging
import math
import re
import threading

from django.utils.dateparse import parse_datetime

from incidents.models import Incident, IncidentSource, Location
from incidents.services.assignment import assign_team_to_incident
from incidents.services.incident_service import create_incident

logger = logging.getLogger(__name__)

SOURCE_NAME = "Equipment Monitoring"
TITLE_TEMPLATE = "Equipment Fault [{equipment_id}]"

REQUIRED_FIELDS = ("equipment_id", "equipment_type", "location", "status", "timestamp")
OPTIONAL_FIELDS = ("fault_code", "motor_temperature")
ALLOWED_FIELDS = frozenset(REQUIRED_FIELDS + OPTIONAL_FIELDS)

EQUIPMENT_TYPES = ("elevator", "escalator")
STATUSES = ("normal", "fault", "recovered")

SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_LOCATION_LENGTH = 100

# Synthetic demo mapping. Unknown fault codes fall back to MEDIUM.
FAULT_SEVERITY = {
    "EMERGENCY_STOP": Incident.Severity.CRITICAL,
    "DOOR_STUCK": Incident.Severity.HIGH,
    "MOTOR_FAULT": Incident.Severity.HIGH,
}
DEFAULT_FAULT_SEVERITY = Incident.Severity.MEDIUM

# Serialises "check for active incident, then create" inside this process.
_processing_lock = threading.Lock()


class EquipmentReadingError(Exception):
    """The reading is invalid (HTTP 400)."""


class UnknownLocationError(Exception):
    """The reading refers to a location that does not exist (HTTP 404)."""


def incident_title(equipment_id):
    return TITLE_TEMPLATE.format(equipment_id=equipment_id)


def validate_reading(payload):
    """Return a cleaned copy of the reading or raise EquipmentReadingError."""
    if not isinstance(payload, dict):
        raise EquipmentReadingError("Request body must be a JSON object.")

    unknown = sorted(str(key) for key in payload if key not in ALLOWED_FIELDS)
    if unknown:
        raise EquipmentReadingError(f"Unknown field(s): {', '.join(unknown)}.")

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise EquipmentReadingError(f"Missing required field(s): {', '.join(missing)}.")

    equipment_id = payload["equipment_id"]
    if not isinstance(equipment_id, str) or not SAFE_ID_PATTERN.fullmatch(equipment_id):
        raise EquipmentReadingError(
            "equipment_id must be 1-64 characters: letters, digits, hyphens, underscores."
        )

    equipment_type = payload["equipment_type"]
    if equipment_type not in EQUIPMENT_TYPES or not isinstance(equipment_type, str):
        raise EquipmentReadingError("equipment_type must be 'elevator' or 'escalator'.")

    status = payload["status"]
    if status not in STATUSES or not isinstance(status, str):
        raise EquipmentReadingError("status must be 'normal', 'fault' or 'recovered'.")

    location_name = payload["location"]
    if (
        not isinstance(location_name, str)
        or not location_name.strip()
        or len(location_name) > MAX_LOCATION_LENGTH
    ):
        raise EquipmentReadingError("location must be a non-blank string (max 100 characters).")
    location_name = location_name.strip()

    fault_code = payload.get("fault_code")
    if status == "fault":
        if not isinstance(fault_code, str) or not SAFE_ID_PATTERN.fullmatch(fault_code):
            raise EquipmentReadingError(
                "fault_code is required when status is 'fault' "
                "(1-64 characters: letters, digits, hyphens, underscores)."
            )
    elif fault_code is not None:
        raise EquipmentReadingError("fault_code must be null unless status is 'fault'.")

    raw_timestamp = payload["timestamp"]
    if not isinstance(raw_timestamp, str):
        raise EquipmentReadingError("timestamp must be an ISO 8601 string.")
    try:
        timestamp = parse_datetime(raw_timestamp)
    except ValueError:
        timestamp = None
    if timestamp is None:
        raise EquipmentReadingError("timestamp must be a valid ISO 8601 date-time.")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise EquipmentReadingError("timestamp must include a timezone (e.g. 'Z' or '+03:00').")

    motor_temperature = payload.get("motor_temperature")
    if motor_temperature is not None:
        is_number = isinstance(motor_temperature, (int, float)) and not isinstance(
            motor_temperature, bool
        )
        try:
            finite = is_number and math.isfinite(motor_temperature)
        except OverflowError:
            finite = False
        if not finite:
            raise EquipmentReadingError("motor_temperature must be a finite number.")

    return {
        "equipment_id": equipment_id,
        "equipment_type": equipment_type,
        "location": location_name,
        "status": status,
        "fault_code": fault_code,
        "timestamp": timestamp,
        "motor_temperature": motor_temperature,
    }


def get_equipment_source():
    """Return the 'Equipment Monitoring' source, creating it on first use."""
    source = IncidentSource.objects.filter(name=SOURCE_NAME).order_by("id").first()
    if source is None:
        source = IncidentSource.objects.create(
            name=SOURCE_NAME,
            source_type=IncidentSource.SourceType.SENSOR,
        )
    return source


def find_active_incident(equipment_id):
    """Return the unresolved incident for this exact equipment ID, if any."""
    return (
        Incident.objects.filter(
            title=incident_title(equipment_id),
            incident_type=Incident.IncidentType.MAINTENANCE,
            source__name=SOURCE_NAME,
        )
        .exclude(status=Incident.Status.RESOLVED)
        .order_by("id")
        .first()
    )


def severity_for_fault(fault_code):
    return FAULT_SEVERITY.get(fault_code, DEFAULT_FAULT_SEVERITY)


def _result(reading, action, incident=None):
    return {
        "accepted": True,
        "equipment_id": reading["equipment_id"],
        "action": action,
        "incident_id": incident.id if incident else None,
    }


def process_reading(payload):
    """
    Validate one telemetry reading and apply the fault lifecycle.

    Returns a dict with: accepted, equipment_id, action, incident_id.
    action is one of: normal, created, already_active, recovered.

    Raises EquipmentReadingError (invalid input) or UnknownLocationError.
    """
    reading = validate_reading(payload)

    location = Location.objects.filter(name=reading["location"]).order_by("id").first()
    if location is None:
        raise UnknownLocationError(f"Unknown location: {reading['location']}.")

    equipment_id = reading["equipment_id"]
    status = reading["status"]

    if status == "normal":
        logger.debug("Equipment %s reported normal.", equipment_id)
        return _result(reading, "normal")

    if status == "recovered":
        # Recovery is only logged. Resolving the incident and releasing the
        # team stays the operator's responsibility.
        active = find_active_incident(equipment_id)
        logger.info(
            "Equipment %s reported recovered (open incident: %s).",
            equipment_id,
            active.id if active else "none",
        )
        return _result(reading, "recovered", active)

    # status == "fault"
    fault_code = reading["fault_code"]
    with _processing_lock:
        active = find_active_incident(equipment_id)
        if active is not None:
            logger.info(
                "Equipment %s fault %s suppressed; incident #%s is still open.",
                equipment_id,
                fault_code,
                active.id,
            )
            return _result(reading, "already_active", active)

        incident = create_incident(
            title=incident_title(equipment_id),
            description=(
                f"Simulated {reading['equipment_type']} fault {fault_code} "
                f"at {location.name} (equipment {equipment_id}). "
                "Synthetic demonstration telemetry; operator verification required."
            ),
            incident_type=Incident.IncidentType.MAINTENANCE,
            source=get_equipment_source(),
            location=location,
            severity=severity_for_fault(fault_code),
            people_affected=0,
        )

        # The general duplicate detector matches by type, location and time.
        # Different equipment devices are independent faults, even at the same
        # location. Clear only this equipment-to-equipment false positive;
        # keep duplicate warnings involving other types of Maintenance reports.
        duplicate = incident.possible_duplicate_of
        if (
            duplicate is not None
            and duplicate.source.name == SOURCE_NAME
            and duplicate.title.startswith("Equipment Fault [")
            and duplicate.title.endswith("]")
            and duplicate.title != incident.title
        ):
            incident.possible_duplicate_of = None
            incident.save(update_fields=["possible_duplicate_of"])

        if not incident.possible_duplicate_of_id:
            assign_team_to_incident(incident)

    logger.info(
        "Equipment %s fault %s created incident #%s.", equipment_id, fault_code, incident.id
    )
    return _result(reading, "created", incident)
