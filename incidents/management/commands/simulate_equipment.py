"""
Live IoT equipment simulator (PROTOTYPE - synthetic data only).

Generates elevator/escalator telemetry readings at runtime and sends each one
to the Django receiver as an HTTP POST with a JSON body. Nothing is read from
a prerecorded file.

    python manage.py simulate_equipment --interval 2
    python manage.py simulate_equipment --interval 2 --loop

The API token is read from the EXPOPULSE_EQUIPMENT_API_TOKEN environment
variable and is never printed.
"""

import json
import math
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

TOKEN_ENV_VAR = "EXPOPULSE_EQUIPMENT_API_TOKEN"
TOKEN_HEADER = "X-Equipment-Token"
DEFAULT_URL = "http://127.0.0.1:8000/api/equipment/readings/"
DEFAULT_LOCATION = "Main Entrance"
REQUEST_TIMEOUT_SECONDS = 5
MAX_CONSECUTIVE_FAILURES = 3


def nonnegative_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        raise CommandError("--interval must be a number.")
    if not math.isfinite(seconds) or seconds < 0:
        raise CommandError("--interval must be zero or a positive number.")
    return seconds


def build_sequence(location):
    """Deterministic demo scenario. Timestamps are added when each reading is sent."""
    steps = []

    def add(equipment_id, equipment_type, status, fault_code=None, temperature=42.5):
        steps.append(
            {
                "equipment_id": equipment_id,
                "equipment_type": equipment_type,
                "location": location,
                "status": status,
                "fault_code": fault_code,
                "motor_temperature": temperature,
            }
        )

    # 1. Elevator: normal -> DOOR_STUCK -> repeated fault readings -> recovered
    add("ELEV-A1", "elevator", "normal", temperature=42.5)
    add("ELEV-A1", "elevator", "normal", temperature=43.1)
    add("ELEV-A1", "elevator", "fault", "DOOR_STUCK", 55.0)
    add("ELEV-A1", "elevator", "fault", "DOOR_STUCK", 55.4)
    add("ELEV-A1", "elevator", "fault", "DOOR_STUCK", 55.9)
    add("ELEV-A1", "elevator", "fault", "DOOR_STUCK", 56.2)
    add("ELEV-A1", "elevator", "recovered", temperature=44.0)

    # 2. Escalator: normal -> EMERGENCY_STOP -> repeated fault readings -> recovered
    add("ESC-001", "escalator", "normal", temperature=48.0)
    add("ESC-001", "escalator", "normal", temperature=48.6)
    add("ESC-001", "escalator", "fault", "EMERGENCY_STOP", 91.2)
    add("ESC-001", "escalator", "fault", "EMERGENCY_STOP", 91.5)
    add("ESC-001", "escalator", "fault", "EMERGENCY_STOP", 91.9)
    add("ESC-001", "escalator", "recovered", temperature=50.3)

    # 3. A second elevator at the same location: a distinct equipment ID
    add("ELEV-A2", "elevator", "normal", temperature=41.8)
    add("ELEV-A2", "elevator", "fault", "MOTOR_FAULT", 78.4)
    add("ELEV-A2", "elevator", "fault", "MOTOR_FAULT", 78.9)
    add("ELEV-A2", "elevator", "recovered", temperature=45.2)

    return steps


def current_timestamp():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return now.replace("+00:00", "Z")


def send_reading(url, token, reading, timeout=REQUEST_TIMEOUT_SECONDS):
    """
    POST one reading as JSON. Returns (http_status, response_dict).
    Raises URLError / OSError when the server cannot be reached.
    """
    request = Request(
        url,
        data=json.dumps(reading).encode("utf-8"),
        headers={"Content-Type": "application/json", TOKEN_HEADER: token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except HTTPError as error:
        status = error.code
        raw = error.read()

    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    return status, body


class Command(BaseCommand):
    help = "Send simulated live elevator/escalator telemetry to ExpoPulse over HTTP JSON."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=DEFAULT_URL, help="Receiver URL.")
        parser.add_argument(
            "--interval",
            type=nonnegative_seconds,
            default=2.0,
            help="Seconds between readings (default 2).",
        )
        parser.add_argument(
            "--location",
            default=DEFAULT_LOCATION,
            help="Existing ExpoPulse location name (default 'Main Entrance').",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Repeat the scenario until Ctrl+C.",
        )

    def handle(self, *args, **options):
        url = options["url"]
        if urlsplit(url).scheme not in ("http", "https"):
            raise CommandError("--url must start with http:// or https://")

        token = os.environ.get(TOKEN_ENV_VAR)
        if not token:
            raise CommandError(
                f"Set the {TOKEN_ENV_VAR} environment variable before running the simulator."
            )

        interval = options["interval"]
        sequence = build_sequence(options["location"])
        self.stats = {"sent": 0, "created": 0, "suppressed": 0, "errors": 0}
        self.consecutive_failures = 0

        self.stdout.write(
            f"Simulated equipment telemetry -> {url} "
            f"(interval {interval:g}s, synthetic data)"
        )

        try:
            cycle = 0
            while True:
                cycle += 1
                if options["loop"]:
                    self.stdout.write(f"--- cycle {cycle} ---")
                completed = self.run_sequence(url, token, sequence, interval)
                if not completed or not options["loop"]:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nStopped by user (Ctrl+C).")

        stats = self.stats
        self.stdout.write(
            f"Done: {stats['sent']} sent, {stats['created']} incident(s) created, "
            f"{stats['suppressed']} repeat fault(s) suppressed, {stats['errors']} error(s)."
        )

    def run_sequence(self, url, token, sequence, interval):
        """Send every step once. Returns False if the server became unreachable."""
        total = len(sequence)
        for index, step in enumerate(sequence, start=1):
            reading = dict(step, timestamp=current_timestamp())
            label = f"[{index}/{total}] {reading['equipment_id']} {reading['status']}"
            if reading["fault_code"]:
                label += f" {reading['fault_code']}"

            try:
                status, body = send_reading(url, token, reading)
            except (URLError, OSError) as error:
                reason = getattr(error, "reason", error)
                self.stats["errors"] += 1
                self.consecutive_failures += 1
                self.stdout.write(f"{label} -> cannot reach server ({reason})")
                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.stdout.write(
                        "Server unreachable several times in a row. "
                        "Is 'python manage.py runserver' running? Stopping."
                    )
                    return False
            else:
                self.consecutive_failures = 0
                self.stats["sent"] += 1
                self.report(label, status, body)

            if index < total:
                time.sleep(interval)
        return True

    def report(self, label, status, body):
        action = body.get("action")
        incident_id = body.get("incident_id")

        if status >= 400:
            self.stats["errors"] += 1
            message = body.get("error", "no details")
            self.stdout.write(f"{label} -> HTTP {status} ERROR: {message}")
        elif action == "created":
            self.stats["created"] += 1
            self.stdout.write(f"{label} -> HTTP {status} created incident #{incident_id}")
        elif action == "already_active":
            self.stats["suppressed"] += 1
            self.stdout.write(
                f"{label} -> HTTP {status} already_active (incident #{incident_id}, no new row)"
            )
        else:
            self.stdout.write(f"{label} -> HTTP {status} {action}")
