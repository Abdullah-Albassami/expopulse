"""
Paris Open Data adapter: lift & escalator remote-monitoring status.

Dataset   : "Ascenseurs / Escalators - Télé-surveillance temps réel"
Publisher : Ville de Paris (Direction Constructions Publiques et Architecture)
Portal    : https://opendata.paris.fr/explore/dataset/ascenseurs-escalators-tele-surveillance-temps-reel/
Mirror    : https://www.data.gouv.fr/datasets/ascenseurs-escalators-tele-surveillance-temps-reel
Licence   : Open Database License (ODbL)

The feed is a *status snapshot*: one row per public lift/escalator with its
current operational status and the time that status was last pushed by the
remote-monitoring operator (GETRALINE). It contains NO sensor measurements and
NO fault codes - only states such as "En fonctionnement" (working) and
"En panne" (out of order).

This module only reads and normalizes the data. It never decides whether an
incident is needed (see ``detection``) and never talks to Django.
"""

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

DATASET_ID = "ascenseurs-escalators-tele-surveillance-temps-reel"
DATASET_TITLE = "Ascenseurs / Escalators - Télé-surveillance temps réel (Ville de Paris)"
DATASET_PAGE = f"https://opendata.paris.fr/explore/dataset/{DATASET_ID}/"
LICENCE = "ODbL"

# Opendatasoft "export" endpoint: returns the whole dataset as CSV, in the same
# format as the file downloaded from the portal / data.gouv.fr.
LIVE_EXPORT_URL = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
    f"{DATASET_ID}/exports/csv?delimiter=%3B"
)
FETCH_TIMEOUT_SECONDS = 20
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024

ID_PREFIX = "PARIS-"
_SAFE_REF = re.compile(r"[A-Za-z0-9_-]{1,58}")  # 6-char prefix + 58 = 64 max


class State:
    """Normalized operational state. Deliberately coarse: it is all the feed says."""

    OPERATIONAL = "operational"
    OUT_OF_SERVICE = "out_of_service"
    NOT_MONITORED = "not_monitored"
    UNKNOWN = "unknown"


# Only values actually observed in the published data are mapped. Anything else
# is reported as UNKNOWN rather than guessed.
_STATUS_MAP = {
    "en fonctionnement": State.OPERATIONAL,
    "en panne": State.OUT_OF_SERVICE,
    "non tele-surveille": State.NOT_MONITORED,
}


def _fold(text):
    """Lower-case, accent-free, single-spaced text for robust comparisons."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


# The portal download and the API export name two columns differently.
STATUS_KEYS = ("statut_equipement", "statut")
TIMESTAMP_KEYS = ("horodatage_statut", "timestamp")


def _first(data, keys):
    for key in keys:
        if key in data:
            return data[key]
    return ""


def field_key(header):
    """'Statut équipement' -> 'statut_equipement' (also matches API field ids)."""
    return re.sub(r"[^a-z0-9]+", "_", _fold(header)).strip("_")


@dataclass
class StatusRecord:
    """One normalized row of the Paris feed."""

    line_number: int
    equipment_ref: str
    equipment_id: str | None
    equipment_type: str | None
    state: str
    raw_status: str
    status_changed_at: datetime | None
    site: str = ""
    address: str = ""
    postcode: str = ""
    problems: list = field(default_factory=list)

    @property
    def is_valid(self):
        return not self.problems

    def describe_place(self):
        parts = [part for part in (self.site, self.address, self.postcode) if part]
        return ", ".join(parts) or "address not given"


def _equipment_type(name, type_label):
    """
    'ESCALIER VOIE PUBLIQUE' is read as an escalator (escalier mécanique): the
    dataset only covers lifts and escalators. 'ASCENSEUR' and 'EPMR' (platform
    lift for reduced-mobility users) are treated as elevators.
    """
    folded = _fold(name)
    if "escalier" in folded or "escalator" in folded:
        return "escalator"
    if "ascenseur" in folded or "epmr" in folded or "elevateur" in folded:
        return "elevator"
    folded_type = _fold(type_label)
    if "escal" in folded_type:
        return "escalator"
    if "ascenseur" in folded_type:
        return "elevator"
    return None


def _parse_timestamp(value):
    value = (value or "").strip()
    if not value:
        return None, "missing status timestamp"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, f"unreadable status timestamp {value!r}"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, f"status timestamp {value!r} has no timezone"
    return parsed, None


def normalize_row(row, line_number):
    """Turn one CSV/API row (any header spelling) into a StatusRecord."""
    data = {field_key(key): (value or "").strip() for key, value in row.items() if key}
    problems = []

    ref = data.get("identifiant", "")
    equipment_id = None
    if not ref:
        problems.append("missing equipment identifier")
    elif not _SAFE_REF.fullmatch(ref):
        problems.append(f"unsafe equipment identifier {ref!r}")
    else:
        equipment_id = ID_PREFIX + ref

    raw_status = _first(data, STATUS_KEYS)
    state = _STATUS_MAP.get(_fold(raw_status), State.UNKNOWN)
    if _fold(data.get("equipement_telesurveille", "")) == "non tele-surveille":
        state = State.NOT_MONITORED
    if state == State.UNKNOWN:
        problems.append(
            f"unrecognised status {raw_status!r}" if raw_status else "missing status"
        )

    timestamp = None
    if state != State.NOT_MONITORED:
        timestamp, timestamp_problem = _parse_timestamp(_first(data, TIMESTAMP_KEYS))
        if timestamp_problem:
            problems.append(timestamp_problem)

    equipment_type = _equipment_type(data.get("nom_equipement"), data.get("type_equipement"))
    if equipment_type is None:
        problems.append("cannot tell whether this is an elevator or an escalator")

    return StatusRecord(
        line_number=line_number,
        equipment_ref=ref,
        equipment_id=equipment_id,
        equipment_type=equipment_type,
        state=state,
        raw_status=raw_status,
        status_changed_at=timestamp,
        site=data.get("equipement", ""),
        address=data.get("adresse", ""),
        postcode=data.get("code_postal", ""),
        problems=problems,
    )


def parse_snapshot(text):
    """Parse a CSV snapshot (as exported by the portal) into StatusRecords."""
    text = text.lstrip("﻿")
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    keys = {field_key(name) for name in (reader.fieldnames or [])}
    if "identifiant" not in keys or not keys & set(STATUS_KEYS):
        found = ", ".join(sorted(keys)[:8]) or "none"
        raise ValueError(
            "Not a Paris lift/escalator status file: expected an 'Identifiant' column "
            f"and a status column ('Statut équipement' or 'statut'). Columns found: {found}."
        )
    records = []
    for row in reader:
        if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
            continue  # blank line
        records.append(normalize_row(row, reader.line_num))
    return records


@dataclass
class Snapshot:
    """A parsed snapshot plus where it came from."""

    origin: str  # file path or URL
    mode: str  # "replay" or "live"
    sha256: str
    records: list


def load_snapshot_file(path):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    return Snapshot(
        origin=str(path),
        mode="replay",
        sha256=hashlib.sha256(raw).hexdigest(),
        records=parse_snapshot(text),
    )


def fetch_live_snapshot(url=LIVE_EXPORT_URL, timeout=FETCH_TIMEOUT_SECONDS):
    """Download the current status of every lift/escalator from the Paris API."""
    request = Request(url, headers={"Accept": "text/csv", "User-Agent": "ExpoPulse/1.0"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Paris feed response is unexpectedly large; refusing to parse it.")
    return Snapshot(
        origin=url,
        mode="live",
        sha256=hashlib.sha256(raw).hexdigest(),
        records=parse_snapshot(raw.decode("utf-8-sig")),
    ), raw
