# Equipment Fault Monitoring — External Data (Paris Open Data)

ExpoPulse now detects elevator/escalator faults from **real, externally
published equipment-status records** instead of a fault sequence written into
Python. The simulator (`simulate_equipment`) is unchanged and remains the
fallback demo.

```
Paris Open Data (live API or replayed snapshot)
  -> normalize records            incidents/equipment_feed/paris_open_data.py
  -> rule-based fault detection   incidents/equipment_feed/detection.py
  -> HTTP POST JSON + token       existing /api/equipment/readings/
  -> ExpoPulse incident           existing create_incident(), priority, duplicate check
  -> Maintenance team dispatch    existing assign_team_to_incident()
  -> Operator resolution          existing manual workflow (never automatic)
```

## 1. Data source

| | |
|---|---|
| Dataset | *Ascenseurs / Escalators - Télé-surveillance temps réel* |
| Publisher | Ville de Paris (Direction Constructions Publiques et Architecture) |
| Portal | https://opendata.paris.fr/explore/dataset/ascenseurs-escalators-tele-surveillance-temps-reel/ |
| Mirror | https://www.data.gouv.fr/datasets/ascenseurs-escalators-tele-surveillance-temps-reel |
| Upstream | GETRALINE remote monitoring pushes each device's status change |
| Licence | ODbL — credit "Ville de Paris" |

**What we found when investigating it**

- The dataset is public, needs no API key, and is available as a CSV/JSON
  download and through the Opendatasoft API. The live mode uses the API's CSV
  export endpoint. It returns the same data as the downloaded file, but with
  machine field names (`statut`, `timestamp`, ...); the adapter accepts both:
  `https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/ascenseurs-escalators-tele-surveillance-temps-reel/exports/csv?delimiter=%3B`
- It contains **equipment IDs, operational states and the time of the last
  status change**: `En fonctionnement` (working), `En panne` (out of order),
  `Non télé-surveillé` (not remotely monitored).
- It does **not** contain sensor measurements, fault causes or a history of
  past states. Each download is one snapshot of the current state.

**Live vs. replayed data.** A real snapshot downloaded on 2026-10-14 is
stored unmodified in `data/equipment/paris/` (provenance and SHA-256 in that
folder's README). Replay mode labels every run
`REPLAYED HISTORICAL DATA (not live equipment telemetry)`, and every incident
it creates says *"Replayed historical Paris Open Data record"*. Live mode
labels runs `LIVE DATA` and incidents *"Paris Open Data live status feed"*.

> The live endpoint was checked on 2026-10-14 from a team laptop
> (`--live --dry-run`); its column names are covered by a test.

## 2. Normalization (Paris row → ExpoPulse reading)

| Paris column | ExpoPulse field | Rule |
|---|---|---|
| `Identifiant` (e.g. `13904_A`) | `equipment_id` | Prefixed: `PARIS-13904_A` (letters, digits, `-`, `_` only) |
| `Nom équipement` | `equipment_type` | `ESCALIER…` → `escalator`; `ASCENSEUR…`, `EPMR…` → `elevator` |
| `Statut équipement` (API export: `statut`) | state | `En fonctionnement` → operational; `En panne` → out of service; `Non télé-surveillé` → not monitored; **anything else → invalid** (not guessed) |
| `Horodatage statut` (API export: `timestamp`) | `timestamp` | Must be ISO 8601 with a timezone |
| site, address, postcode | `source_reference` | Short pointer back to the original row, stored in the incident text |
| — | `location` | The ExpoPulse location to file incidents under (`--location`, default `Main Entrance`) |
| — | `fault_code` | Always the generic `OUT_OF_SERVICE` |

`ESCALIER VOIE PUBLIQUE` is read as an escalator because the dataset only
covers lifts and escalators (*escalier mécanique*). Paris addresses are not
ExpoPulse locations, so the `--location` mapping is a demonstration choice;
the real address stays visible in the incident description.

## 3. Fault detection (rule-based)

Each equipment ID is tracked **independently** by a small state machine:

| Record | Previous state of that device | Result | Sent to ExpoPulse |
|---|---|---|---|
| working | none | Normal | `normal` |
| working | working | Normal (unchanged) | nothing |
| out of order | working | **Fault — transition detected** | `fault` → new incident |
| out of order | none | **Fault — out of order when first observed** | `fault` → new incident |
| out of order | out of order | Repeated fault | `fault` → server answers `already_active` |
| working | out of order | **Recovered** | `recovered` → incident stays open |
| not remotely monitored | — | Skipped | nothing |
| missing ID, unknown status, bad/missing timestamp, timestamp in the future | — | Skipped *invalid* | nothing |
| status not refreshed for more than 7 days | — | Skipped *stale* | nothing (`--include-stale` to act on it) |
| older than a report already processed for that device | — | Skipped *outdated* | nothing |

Why the stale rule: the feed shows the time of the last status push. A device
reported "out of order since 2024" may still be broken, or its monitoring
link may be dead; the feed cannot tell which. Those records are listed for
the operator but do not raise automatic incidents unless `--include-stale`
is given. The limit is configurable with `--stale-after-days`.

**No invented causes.** The feed only says a device is unavailable, so the
fault code is always `OUT_OF_SERVICE`, mapped to **medium** severity. The
incident text states that the cause is unknown, and the dashboard briefing
shows *"Elevator Out of Service"* with the note that the external feed
confirms neither the cause nor passenger impact.

**Why no machine learning.** The data is a two-state status signal with no
sensor values and no verified fault labels. A trained model would add
nothing that these rules do not already do, and it would be harder to
explain. ML should only be reconsidered with raw sensor data and verified
labels — for example the LBNL HVAC fault dataset
(https://faultdetection.lbl.gov/data/), which would be a **separate
HVAC module** and needs team approval first.

## 4. What stays exactly as before

- `/api/equipment/readings/`, token header, status codes and responses.
- `Incident` and `Team` models — **no migrations**.
- Priority calculation, duplicate suppression by equipment ID, Maintenance
  team assignment, incident statuses and manual resolution.
- CCTV modules and frontend.
- `simulate_equipment` — same scenario, same output, same incident text.

The endpoint gained two **optional** fields. Requests without them behave
exactly as before.

| Field | Rule |
|---|---|
| `data_source` | `simulated` (default), `paris_open_data_live` or `paris_open_data_replay`. Controls the incident description |
| `source_reference` | Optional printable text, max 200 characters, pointing back to the original record |

## 5. How to run the demo

Setup once (same as the simulator):

```bash
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

**Terminal A — Django** (PowerShell; on macOS/Linux use `export`)

```powershell
$env:EXPOPULSE_EQUIPMENT_API_TOKEN = "<your-local-token>"
python manage.py runserver
```

**Terminal B — external data**

```powershell
$env:EXPOPULSE_EQUIPMENT_API_TOKEN = "<your-local-token>"

# 1) See what would be detected, without sending anything (no token needed)
python manage.py monitor_equipment_feed --replay data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv --dry-run

# 2) Replay the real snapshot into ExpoPulse
python manage.py monitor_equipment_feed --replay data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv

# 3) Short demo with one real record
python manage.py monitor_equipment_feed --replay data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv --equipment 13904_A

# 4) Live data from the Paris API: one fetch, or every 5 minutes until Ctrl+C
python manage.py monitor_equipment_feed --live
python manage.py monitor_equipment_feed --live --polls 0 --poll-interval 300 --save-snapshots data/equipment/paris/
```

Then open <http://127.0.0.1:8000/>, open the new Maintenance incident, and
resolve it manually as the operator.

**Fallback:** `python manage.py simulate_equipment --interval 2` still runs
the synthetic scenario.

| Option | Default | Meaning |
|---|---|---|
| `--replay CSV [CSV ...]` | — | Replay snapshot files in the given order |
| `--live` | — | Fetch the current status from the Paris API |
| `--polls` | `1` | Live: number of fetches (`0` = until Ctrl+C) |
| `--poll-interval` | `300` | Live: seconds between fetches (minimum 30) |
| `--save-snapshots DIR` | off | Live: keep every download for later replay |
| `--equipment ID ...` | all | Only these Paris IDs (`13904_A` or `PARIS-13904_A`) |
| `--location` | `Main Entrance` | Existing ExpoPulse location for the incidents |
| `--stale-after-days` | `7` | Statuses older than this are skipped as stale |
| `--include-stale` | off | Act on stale statuses too |
| `--interval` | `1` | Seconds between sent readings |
| `--url` | local endpoint | ExpoPulse receiver URL |
| `--dry-run` | off | Detect and print only |

## 6. Example output (real record → ExpoPulse incident)

Recorded on a fresh database (`migrate` + `seed_data`) with the 2026-10-14
snapshot. Not-monitored rows are omitted here for length.

```
=== REPLAYED HISTORICAL DATA (not live equipment telemetry) ===
Dataset  : Ascenseurs / Escalators - Télé-surveillance temps réel (Ville de Paris) [ODbL]
Origin   : data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv
SHA-256  : 32fa7973f353ab44c00e4a27379d11ecf5f4d52f1595869d9bcf3ed2f7a92a5a
Snapshot time (newest status): 2026-10-14T16:59:02Z
Sending  : http://127.0.0.1:8000/api/equipment/readings/ (location 'Main Entrance')
[1/33] PARIS-13910 elevator 'En panne' since 2024-10-09T09:05:02Z -> SKIPPED stale: status 'En panne' not refreshed for 735 day(s) (limit 7); cannot confirm it is current
...
[8/33] PARIS-17802_B elevator 'En panne' since 2026-10-14T08:08:03Z -> FAULT (out of service when first observed) -> HTTP 201 created incident #7
[9/33] PARIS-17802_C elevator 'En fonctionnement' since 2026-10-14T08:46:02Z -> NORMAL (working) -> HTTP 200 normal
...
[14/33] PARIS-13906 escalator 'En panne' since 2026-10-14T10:32:12Z -> FAULT (out of service when first observed) -> HTTP 201 created incident #9
...
[18/33] PARIS-13904_A elevator 'En panne' since 2026-10-14T10:49:03Z -> FAULT (out of service when first observed) -> HTTP 201 created incident #10
...
Done: 33 record(s) read, 18 sent, 7 incident(s) created, 0 repeat fault(s) suppressed, 0 recovery report(s), 15 skipped, 0 error(s).
```

Running it again does not create new rows:

```
[2/2] PARIS-13904_A elevator 'En panne' since 2026-10-14T10:49:03Z -> FAULT (out of service when first observed) -> HTTP 200 already_active (incident #10, no new row)
```

Incident #10 as stored by ExpoPulse:

```
Title      : Equipment Fault [PARIS-13904_A]
Severity   : medium   Priority: 53 (high)   Type: Maintenance
Description: Replayed historical Paris Open Data record reported elevator fault
             OUT_OF_SERVICE at Main Entrance (equipment PARIS-13904_A). Source record:
             Paris equipment 13904_A (66 AVENUE D'IVRY/RUE DU DISQUE, 75013); source
             status 'En panne' since 2026-10-14T10:49:03Z. The source reports
             availability only; the cause of the outage is not known. Operator
             verification required.
Briefing   : Elevator Out of Service — Main Entrance
```

The first fault (#7) took the only available Maintenance team; the others
stay **New** until a team is free — the existing assignment behaviour.

## 7. Tests

```bash
python manage.py test incidents.tests_equipment_feed   # 24 new tests
python manage.py test incidents                        # everything: 99 tests
```

Covered: real-snapshot parsing, field-name variants, malformed rows, stale /
future / outdated / unmonitored records, transitions working → out of order →
working, independent devices, fault creation from a real record, duplicate
suppression on replay, recovery that leaves the incident and team untouched,
dry run, live fetch (mocked) and fetch failure, and validation of the two new
endpoint fields. Transition tests use small CSV fixtures in the real Paris
column layout, clearly marked as test fixtures.

## 8. Limitations

- One stored snapshot shows current states, not transitions. Real transitions
  need several snapshots (collect them with `--save-snapshots`).
- State is kept in memory per run. After a restart, a still-broken device is
  "out of order when first observed" again; the server's duplicate rule keeps
  it to one incident.
- All Paris devices are filed under one ExpoPulse location (`--location`).
- Severity for `OUT_OF_SERVICE` is a demonstration choice (medium), not an
  approved safety policy.
- The live API depends on the Paris portal being reachable and unchanged.
