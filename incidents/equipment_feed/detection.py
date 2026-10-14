"""
Rule-based fault detection over normalized equipment-status records.

Why rules and not machine learning
----------------------------------
The Paris feed only says whether a device is working or out of order. There
are no sensor measurements to learn from and no verified fault labels, so a
model would add nothing but a claim. A transparent state machine per
equipment ID is easier to explain and to audit.

Rules (each equipment ID is tracked independently)
--------------------------------------------------
operational, first time seen          -> NORMAL_FIRST_SEEN   send "normal"
operational, was operational          -> NORMAL_UNCHANGED    nothing sent
operational, was out of service       -> RECOVERED           send "recovered"
out of service, was operational       -> FAULT_NEW           send "fault"
out of service, first time seen       -> FAULT_FIRST_SEEN    send "fault"
out of service, was out of service    -> FAULT_REPEAT        send "fault" (server suppresses)
not remotely monitored                -> NOT_MONITORED       nothing sent
missing / unreadable / unknown data   -> INVALID             nothing sent
status older than the stale limit     -> STALE               nothing sent (unless allowed)
older than a report already processed -> OUTDATED            nothing sent

A fault is always reported with the generic code OUT_OF_SERVICE. The feed does
not say why a device stopped, so no mechanical cause (motor, door, ...) is
ever invented. Recovery is reported but never resolves the incident: that
remains the operator's decision on the ExpoPulse side.
"""

from dataclasses import dataclass
from datetime import timedelta, timezone

from incidents.equipment_feed.paris_open_data import State

FAULT_CODE = "OUT_OF_SERVICE"
FUTURE_TOLERANCE = timedelta(minutes=10)
DEFAULT_STALE_AFTER = timedelta(days=7)
MAX_REFERENCE_LENGTH = 200


class Kind:
    NORMAL_FIRST_SEEN = "normal_first_seen"
    NORMAL_UNCHANGED = "normal_unchanged"
    FAULT_NEW = "fault_new"
    FAULT_FIRST_SEEN = "fault_first_seen"
    FAULT_REPEAT = "fault_repeat"
    RECOVERED = "recovered"
    NOT_MONITORED = "not_monitored"
    INVALID = "invalid"
    STALE = "stale"
    OUTDATED = "outdated"


SEND_STATUS = {
    Kind.NORMAL_FIRST_SEEN: "normal",
    Kind.FAULT_NEW: "fault",
    Kind.FAULT_FIRST_SEEN: "fault",
    Kind.FAULT_REPEAT: "fault",
    Kind.RECOVERED: "recovered",
}


@dataclass
class Detection:
    kind: str
    record: object
    note: str = ""
    reading: dict | None = None  # ExpoPulse payload, or None if nothing is sent


def iso_utc(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_text(text):
    return "".join(ch if ch.isprintable() else " " for ch in text)


def source_reference(record):
    """Short, human-readable pointer back to the original row."""
    since = iso_utc(record.status_changed_at) if record.status_changed_at else "unknown time"
    text = (
        f"Paris equipment {record.equipment_ref} ({record.describe_place()}); "
        f"source status '{record.raw_status}' since {since}"
    )
    text = _clean_text(text)
    if len(text) > MAX_REFERENCE_LENGTH:
        text = text[: MAX_REFERENCE_LENGTH - 3] + "..."
    return text


def build_reading(record, status, location, data_source):
    """Payload for the existing /api/equipment/readings/ endpoint."""
    return {
        "equipment_id": record.equipment_id,
        "equipment_type": record.equipment_type,
        "location": location,
        "status": status,
        "fault_code": FAULT_CODE if status == "fault" else None,
        "timestamp": iso_utc(record.status_changed_at),
        "data_source": data_source,
        "source_reference": source_reference(record),
    }


class EquipmentStateTracker:
    """Remembers the last accepted state of every equipment ID."""

    def __init__(self, stale_after=DEFAULT_STALE_AFTER, include_stale=False):
        self.stale_after = stale_after
        self.include_stale = include_stale
        self._last = {}  # equipment_id -> (state, status_changed_at)

    def last_state(self, equipment_id):
        entry = self._last.get(equipment_id)
        return entry[0] if entry else None

    def process(self, record, reference_time, location, data_source):
        """Classify one record and, if needed, build the reading to send."""
        if record.state == State.NOT_MONITORED:
            return Detection(Kind.NOT_MONITORED, record, "device is not remotely monitored")

        if not record.is_valid:
            return Detection(Kind.INVALID, record, "; ".join(record.problems))

        changed_at = record.status_changed_at
        if changed_at > reference_time + FUTURE_TOLERANCE:
            return Detection(
                Kind.INVALID, record, f"status timestamp {iso_utc(changed_at)} is in the future"
            )

        previous = self._last.get(record.equipment_id)
        if previous is not None and changed_at < previous[1]:
            return Detection(
                Kind.OUTDATED,
                record,
                f"older than the report already processed ({iso_utc(previous[1])})",
            )

        age = reference_time - changed_at
        if age > self.stale_after and not self.include_stale:
            return Detection(
                Kind.STALE,
                record,
                f"status '{record.raw_status}' not refreshed for {age.days} day(s) "
                f"(limit {self.stale_after.days}); cannot confirm it is current",
            )

        previous_state = previous[0] if previous else None
        self._last[record.equipment_id] = (record.state, changed_at)

        if record.state == State.OUT_OF_SERVICE:
            if previous_state == State.OPERATIONAL:
                kind, note = Kind.FAULT_NEW, "changed from working to out of service"
            elif previous_state == State.OUT_OF_SERVICE:
                kind, note = Kind.FAULT_REPEAT, "still out of service"
            else:
                kind, note = Kind.FAULT_FIRST_SEEN, "out of service when first observed"
        elif previous_state == State.OUT_OF_SERVICE:
            kind, note = Kind.RECOVERED, "back in service"
        elif previous_state == State.OPERATIONAL:
            kind, note = Kind.NORMAL_UNCHANGED, "still working"
        else:
            kind, note = Kind.NORMAL_FIRST_SEEN, "working"

        reading = None
        if kind in SEND_STATUS:
            reading = build_reading(record, SEND_STATUS[kind], location, data_source)
        return Detection(kind, record, note, reading)


def timeline(records):
    """Valid records ordered by status time; records without a time go last."""
    dated = [r for r in records if r.status_changed_at is not None]
    undated = [r for r in records if r.status_changed_at is None]
    dated.sort(key=lambda r: (r.status_changed_at, r.line_number))
    return dated + undated


def reference_time_for(records):
    """For a replayed snapshot: the newest status time it contains."""
    times = [r.status_changed_at for r in records if r.status_changed_at is not None]
    return max(times) if times else None
