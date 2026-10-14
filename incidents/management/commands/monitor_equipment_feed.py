"""
External equipment-status monitor (Paris Open Data lifts & escalators).

Reads REAL equipment status records, detects faults with transparent rules,
and sends the detected events to ExpoPulse through the existing
/api/equipment/readings/ endpoint - exactly like the simulator does.

Two ways to get the data:

    # Replayed historical data (a snapshot file downloaded from the portal)
    python manage.py monitor_equipment_feed --replay data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv

    # Live data from the Paris Open Data API (polls every 5 minutes)
    python manage.py monitor_equipment_feed --live --polls 0 --poll-interval 300

Add --dry-run to see what would be detected without sending anything.

The simulated demo (simulate_equipment) is unchanged and remains the fallback.
The API token is read from EXPOPULSE_EQUIPMENT_API_TOKEN and never printed.
"""

import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

from incidents.equipment_feed import paris_open_data
from incidents.equipment_feed.detection import (
    SEND_STATUS,
    EquipmentStateTracker,
    Kind,
    iso_utc,
    reference_time_for,
    timeline,
)
from incidents.management.commands.simulate_equipment import (
    DEFAULT_LOCATION,
    DEFAULT_URL,
    MAX_CONSECUTIVE_FAILURES,
    TOKEN_ENV_VAR,
    send_reading,
)

MIN_POLL_INTERVAL = 30.0
FEED_STALE_WARNING = timedelta(hours=24)

KIND_LABELS = {
    Kind.NORMAL_FIRST_SEEN: "NORMAL",
    Kind.NORMAL_UNCHANGED: "NORMAL (unchanged)",
    Kind.FAULT_NEW: "FAULT",
    Kind.FAULT_FIRST_SEEN: "FAULT",
    Kind.FAULT_REPEAT: "FAULT (repeat)",
    Kind.RECOVERED: "RECOVERED",
    Kind.NOT_MONITORED: "SKIPPED not monitored",
    Kind.INVALID: "SKIPPED invalid",
    Kind.STALE: "SKIPPED stale",
    Kind.OUTDATED: "SKIPPED outdated",
}


def _nonnegative(name):
    def parse(value):
        try:
            number = float(value)
        except ValueError:
            raise CommandError(f"{name} must be a number.")
        if not math.isfinite(number) or number < 0:
            raise CommandError(f"{name} must be zero or a positive number.")
        return number

    return parse


def _nonnegative_int(name):
    def parse(value):
        try:
            number = int(value)
        except ValueError:
            raise CommandError(f"{name} must be a whole number.")
        if number < 0:
            raise CommandError(f"{name} must be zero or more.")
        return number

    return parse


class Command(BaseCommand):
    help = (
        "Detect elevator/escalator faults from real Paris Open Data status records "
        "(live or replayed) and send them to ExpoPulse over HTTP JSON."
    )

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            "--replay",
            nargs="+",
            metavar="CSV",
            help="Replay one or more downloaded snapshot files, in the given order.",
        )
        source.add_argument(
            "--live", action="store_true", help="Fetch the current status from the Paris API."
        )
        parser.add_argument("--url", default=DEFAULT_URL, help="ExpoPulse receiver URL.")
        parser.add_argument(
            "--location",
            default=DEFAULT_LOCATION,
            help="Existing ExpoPulse location to file incidents under (default 'Main Entrance').",
        )
        parser.add_argument(
            "--interval",
            type=_nonnegative("--interval"),
            default=1.0,
            help="Seconds between sent readings (default 1).",
        )
        parser.add_argument(
            "--polls",
            type=_nonnegative_int("--polls"),
            default=1,
            help="Live mode: number of fetches (default 1, 0 = until Ctrl+C).",
        )
        parser.add_argument(
            "--poll-interval",
            type=_nonnegative("--poll-interval"),
            default=300.0,
            help=f"Live mode: seconds between fetches (default 300, minimum {MIN_POLL_INTERVAL:g}).",
        )
        parser.add_argument(
            "--stale-after-days",
            type=_nonnegative_int("--stale-after-days"),
            default=7,
            help="Ignore statuses not refreshed for this many days (default 7).",
        )
        parser.add_argument(
            "--include-stale",
            action="store_true",
            help="Also act on statuses older than --stale-after-days.",
        )
        parser.add_argument(
            "--equipment",
            nargs="+",
            metavar="ID",
            help="Only process these Paris equipment IDs (e.g. 13904_A or PARIS-13904_A).",
        )
        parser.add_argument(
            "--save-snapshots",
            metavar="DIR",
            help="Live mode: save every downloaded snapshot here for later replay.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Detect and print, but do not send anything to ExpoPulse.",
        )

    # ------------------------------------------------------------------ setup

    def handle(self, *args, **options):
        self.options = options
        self.url = options["url"]
        if urlsplit(self.url).scheme not in ("http", "https"):
            raise CommandError("--url must start with http:// or https://")

        self.dry_run = options["dry_run"]
        self.token = os.environ.get(TOKEN_ENV_VAR)
        if not self.token and not self.dry_run:
            raise CommandError(
                f"Set the {TOKEN_ENV_VAR} environment variable (or use --dry-run)."
            )

        if options["live"] and options["poll_interval"] < MIN_POLL_INTERVAL:
            raise CommandError(
                f"--poll-interval must be at least {MIN_POLL_INTERVAL:g} seconds "
                "(be polite to the public API)."
            )
        if options["save_snapshots"] and not options["live"]:
            raise CommandError("--save-snapshots is only used with --live.")

        self.only = None
        if options["equipment"]:
            prefix = paris_open_data.ID_PREFIX
            self.only = {
                value if value.startswith(prefix) else prefix + value
                for value in options["equipment"]
            }

        self.tracker = EquipmentStateTracker(
            stale_after=timedelta(days=options["stale_after_days"]),
            include_stale=options["include_stale"],
        )
        self.stats = dict.fromkeys(
            [
                "records", "sent", "created", "suppressed", "recovered", "normal",
                "skipped", "errors", "would_send",
            ],
            0,
        )
        self.consecutive_failures = 0
        self.server_unreachable = False

        try:
            if options["live"]:
                self.run_live()
            else:
                self.run_replay(options["replay"])
        except KeyboardInterrupt:
            self.stdout.write("\nStopped by user (Ctrl+C).")

        s = self.stats
        if self.dry_run:
            self.stdout.write(
                f"Dry run: {s['records']} record(s) read, {s['would_send']} reading(s) would be "
                f"sent, {s['skipped']} skipped. Nothing was sent to ExpoPulse."
            )
            return
        self.stdout.write(
            f"Done: {s['records']} record(s) read, {s['sent']} sent, "
            f"{s['created']} incident(s) created, {s['suppressed']} repeat fault(s) suppressed, "
            f"{s['recovered']} recovery report(s), {s['skipped']} skipped, {s['errors']} error(s)."
        )

    # ---------------------------------------------------------------- sources

    def run_replay(self, paths):
        for path in paths:
            try:
                snapshot = paris_open_data.load_snapshot_file(path)
            except FileNotFoundError:
                raise CommandError(f"Snapshot file not found: {path}")
            except (UnicodeDecodeError, ValueError) as error:
                raise CommandError(f"Cannot read {path}: {error}")

            reference = reference_time_for(snapshot.records)
            self.print_header(snapshot, reference)
            if reference is None:
                self.stdout.write("  No dated records in this file; nothing to replay.")
                continue
            if not self.process_snapshot(snapshot, reference, "paris_open_data_replay"):
                return

    def run_live(self):
        options = self.options
        save_dir = Path(options["save_snapshots"]) if options["save_snapshots"] else None
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)

        poll = 0
        while True:
            poll += 1
            fetched_at = datetime.now(timezone.utc)
            try:
                snapshot, raw = paris_open_data.fetch_live_snapshot()
            except (URLError, OSError, ValueError, UnicodeDecodeError) as error:
                reason = getattr(error, "reason", error)
                self.stats["errors"] += 1
                self.stdout.write(f"Poll {poll}: cannot fetch the Paris feed ({reason}).")
            else:
                if save_dir:
                    name = f"paris_lifts_snapshot_{fetched_at:%Y-%m-%dT%H%M%SZ}.csv"
                    (save_dir / name).write_bytes(raw)
                    self.stdout.write(f"Poll {poll}: saved snapshot to {save_dir / name}")
                self.print_header(snapshot, fetched_at, poll=poll)
                newest = reference_time_for(snapshot.records)
                if newest is None or fetched_at - newest > FEED_STALE_WARNING:
                    self.stdout.write(
                        "  WARNING: no status in this feed changed in the last 24 hours; "
                        "the feed itself may be stale."
                    )
                if not self.process_snapshot(snapshot, fetched_at, "paris_open_data_live"):
                    return

            if options["polls"] and poll >= options["polls"]:
                return
            time.sleep(options["poll_interval"])

    def print_header(self, snapshot, reference, poll=None):
        if snapshot.mode == "replay":
            kind = "REPLAYED HISTORICAL DATA (not live equipment telemetry)"
        else:
            kind = f"LIVE DATA, poll {poll}"
        self.stdout.write(f"=== {kind} ===")
        self.stdout.write(f"Dataset  : {paris_open_data.DATASET_TITLE} [{paris_open_data.LICENCE}]")
        self.stdout.write(f"Origin   : {snapshot.origin}")
        self.stdout.write(f"SHA-256  : {snapshot.sha256}")
        label = "Snapshot time (newest status)" if snapshot.mode == "replay" else "Fetched at"
        self.stdout.write(f"{label}: {iso_utc(reference) if reference else 'unknown'}")
        target = "dry run, nothing sent" if self.dry_run else self.url
        self.stdout.write(f"Sending  : {target} (location '{self.options['location']}')")

    # -------------------------------------------------------------- detection

    def process_snapshot(self, snapshot, reference, data_source):
        """Returns False if ExpoPulse became unreachable."""
        records = timeline(snapshot.records)
        if self.only is not None:
            records = [r for r in records if r.equipment_id in self.only]
        total = len(records)
        for index, record in enumerate(records, start=1):
            self.stats["records"] += 1
            detection = self.tracker.process(
                record, reference, self.options["location"], data_source
            )
            label = self.describe(index, total, detection)

            if detection.reading is None:
                if detection.kind != Kind.NORMAL_UNCHANGED:
                    self.stats["skipped"] += 1
                self.stdout.write(f"{label} -> {KIND_LABELS[detection.kind]}: {detection.note}")
                continue

            label += f" -> {KIND_LABELS[detection.kind]} ({detection.note})"
            if self.dry_run:
                self.stats["would_send"] += 1
                self.stdout.write(f"{label} -> would send '{SEND_STATUS[detection.kind]}'")
                continue

            self.send(label, detection.reading)
            if self.server_unreachable:
                return False
            if index < total:
                time.sleep(self.options["interval"])
        return True

    def describe(self, index, total, detection):
        record = detection.record
        name = record.equipment_id or f"line {record.line_number}"
        kind = record.equipment_type or "?"
        status = record.raw_status or "no status"
        when = f" since {iso_utc(record.status_changed_at)}" if record.status_changed_at else ""
        return f"[{index}/{total}] {name} {kind} '{status}'{when}"

    # ------------------------------------------------------------------- HTTP

    def send(self, label, reading):
        try:
            status, body = send_reading(self.url, self.token, reading)
        except (URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            self.stats["errors"] += 1
            self.consecutive_failures += 1
            self.stdout.write(f"{label} -> cannot reach ExpoPulse ({reason})")
            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self.stdout.write(
                    "ExpoPulse unreachable several times in a row. "
                    "Is 'python manage.py runserver' running? Stopping."
                )
                self.server_unreachable = True
            return

        self.consecutive_failures = 0
        self.stats["sent"] += 1
        action = body.get("action")
        incident_id = body.get("incident_id")
        if status >= 400:
            self.stats["errors"] += 1
            self.stdout.write(f"{label} -> HTTP {status} ERROR: {body.get('error', 'no details')}")
        elif action == "created":
            self.stats["created"] += 1
            self.stdout.write(f"{label} -> HTTP {status} created incident #{incident_id}")
        elif action == "already_active":
            self.stats["suppressed"] += 1
            self.stdout.write(
                f"{label} -> HTTP {status} already_active (incident #{incident_id}, no new row)"
            )
        elif action == "recovered":
            self.stats["recovered"] += 1
            open_note = f"incident #{incident_id} stays open" if incident_id else "no open incident"
            self.stdout.write(f"{label} -> HTTP {status} recovered ({open_note})")
        else:
            self.stats["normal"] += 1
            self.stdout.write(f"{label} -> HTTP {status} {action}")
