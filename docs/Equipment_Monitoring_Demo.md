# Equipment Fault Monitoring — Demo Guide

Simulated **live IoT telemetry over HTTP JSON** for elevators and escalators.

> **All readings are simulated.** Equipment IDs, fault codes, temperatures and
> severities are synthetic demonstration data. They are not manufacturer
> telemetry, diagnosed failures, or approved safety thresholds.

## How it works

```
simulate_equipment (Python)  --HTTP POST JSON-->  /api/equipment/readings/
        -> validation + token check
        -> one-active-fault-per-equipment rule
        -> existing create_incident()
        -> existing Maintenance team assignment
        -> existing ExpoPulse dashboard (polling)
```

| File | Role |
|---|---|
| `incidents/services/equipment_monitoring.py` | Validation, fault lifecycle, duplicate suppression |
| `incidents/views_equipment.py` | Authenticated JSON endpoint |
| `incidents/management/commands/simulate_equipment.py` | Live simulator |
| `incidents/tests_equipment.py` | Automated tests |
| `incidents/urls.py` | One added route |

No models, migrations, templates, or shared services were changed.

## Setup (once)

```bash
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data      # only on a fresh database
```

`seed_data` provides the `Main Entrance` location and `Maintenance Team 1`
used by the demo.

## Run the demo (two terminals)

Both terminals need the virtual environment active and the **same** token in
`EXPOPULSE_EQUIPMENT_API_TOKEN`. Choose any local value; never commit it.

**Terminal A — Django**

```powershell
# Windows PowerShell
$env:EXPOPULSE_EQUIPMENT_API_TOKEN = "<your-local-token>"
python manage.py runserver
```

```bash
# macOS / Linux
export EXPOPULSE_EQUIPMENT_API_TOKEN="<your-local-token>"
python manage.py runserver
```

**Terminal B — simulator**

```powershell
$env:EXPOPULSE_EQUIPMENT_API_TOKEN = "<your-local-token>"
python manage.py simulate_equipment --interval 2
```

Then open <http://127.0.0.1:8000/> and watch the Maintenance incidents appear.

### Simulator options

| Option | Default | Meaning |
|---|---|---|
| `--url` | `http://127.0.0.1:8000/api/equipment/readings/` | Receiver URL |
| `--interval` | `2` | Seconds between readings (zero or more) |
| `--location` | `Main Entrance` | Existing ExpoPulse location name |
| `--loop` | off | Repeat the scenario until `Ctrl+C` |

The scenario is generated at runtime (nothing is read from a file):

1. `ELEV-A1` elevator: normal → `DOOR_STUCK` → repeated fault → recovered
2. `ESC-001` escalator: normal → `EMERGENCY_STOP` → repeated fault → recovered
3. `ELEV-A2` elevator: normal → `MOTOR_FAULT` → repeated fault → recovered

### Example output

Recorded on a local run where `ELEV-A1` already had an open incident (#7):

```
Simulated equipment telemetry -> http://127.0.0.1:8000/api/equipment/readings/ (interval 2s, synthetic data)
[1/17] ELEV-A1 normal -> HTTP 200 normal
[3/17] ELEV-A1 fault DOOR_STUCK -> HTTP 200 already_active (incident #7, no new row)
[7/17] ELEV-A1 recovered -> HTTP 200 recovered
[10/17] ESC-001 fault EMERGENCY_STOP -> HTTP 201 created incident #8
[11/17] ESC-001 fault EMERGENCY_STOP -> HTTP 200 already_active (incident #8, no new row)
[15/17] ELEV-A2 fault MOTOR_FAULT -> HTTP 201 created incident #9
[16/17] ELEV-A2 fault MOTOR_FAULT -> HTTP 200 already_active (incident #9, no new row)
Done: 17 sent, 2 incident(s) created, 7 repeat fault(s) suppressed, 0 error(s).
```

## API

`POST /api/equipment/readings/` — one JSON object per request.

Headers: `Content-Type: application/json`, `X-Equipment-Token: <token>`

```json
{
  "equipment_id": "ESC-001",
  "equipment_type": "escalator",
  "location": "Main Entrance",
  "status": "fault",
  "fault_code": "EMERGENCY_STOP",
  "motor_temperature": 91.2,
  "timestamp": "2026-10-10T10:00:10Z"
}
```

| Field | Rule |
|---|---|
| `equipment_id` | Required. 1–64 characters: letters, digits, `-`, `_` |
| `equipment_type` | Required. `elevator` or `escalator` |
| `location` | Required. Name of an existing `Location` |
| `status` | Required. `normal`, `fault`, or `recovered` |
| `fault_code` | Required when `status` is `fault`; otherwise `null` or omitted |
| `timestamp` | Required. ISO 8601 with a timezone |
| `motor_temperature` | Optional finite number. Never used to infer a fault |

Any other field is rejected.

Response:

```json
{"accepted": true, "equipment_id": "ESC-001", "action": "created", "incident_id": 8}
```

| HTTP | `action` / meaning |
|---|---|
| 201 | `created` — a new incident was created |
| 200 | `normal`, `already_active`, or `recovered` — accepted, nothing created |
| 400 | Invalid JSON or invalid/missing/unknown field |
| 401 | Missing or wrong `X-Equipment-Token` |
| 404 | Unknown location |
| 405 | Method other than POST |
| 413 | Body larger than 4096 bytes |
| 415 | Content type is not `application/json` |
| 503 | Server has no `EXPOPULSE_EQUIPMENT_API_TOKEN` configured |

Errors return `{"accepted": false, "error": "..."}`.

## Fault lifecycle

**One active fault per equipment ID = at most one unresolved incident.**

| Reading | Result |
|---|---|
| `normal` | Logged; no incident |
| First `fault` | One Maintenance incident; a team is assigned if available |
| Repeated `fault` (same or different code) | `already_active`; no new row, no reassignment |
| `recovered` | Logged only. The incident is **not** resolved and the team is **not** released — that stays with the operator |
| `fault` after recovery, incident still unresolved | Still suppressed (also after a simulator restart) |
| `fault` after the operator resolved the incident | A **new** incident is created |

Each incident is linked to its device by an exact title, `Equipment Fault [<equipment_id>]`,
with source `Equipment Monitoring` and type Maintenance. Exact matching plus the
restricted ID characters means `ELEV-A1` cannot collide with `ELEV-A10`.

Synthetic severity map: `EMERGENCY_STOP` → critical; `DOOR_STUCK`, `MOTOR_FAULT`
→ high; any other code → medium.

## Security baseline

- Shared token from the `EXPOPULSE_EQUIPMENT_API_TOKEN` environment variable,
  compared in constant time; never logged, printed, or returned.
- The view is `csrf_exempt` because it is a machine-to-machine endpoint with no
  browser session; in this prototype the API token replaces CSRF protection.
- Local demonstration only. Do not expose the development server to the internet.

## Limitations and integration notes

- **Prototype, not industrial telemetry.** Normal and recovered readings are
  only logged; there is no reading history or event sourcing.
- **Concurrency.** "Check for an open incident, then create" is guarded by an
  in-process lock. That is sufficient for the single-process `runserver` demo.
  It is **not** an atomic uniqueness guarantee: with several server processes
  two simultaneous first faults could both create a row, because there is no
  database constraint (schema changes were out of scope).
- **Shared duplicate detector.** `find_possible_duplicate` flags any unresolved
  incident of the same type at the same location within 15 minutes. Two
  *different* devices faulting at one location are therefore both created, but
  the second is flagged `possible_duplicate_of` the first and does **not** get a
  team automatically. An operator can assign one manually. The shared service
  was not changed; changing this rule needs team-lead approval.
- A renamed incident title or a changed source would break the link between an
  incident and its device.
- If no Maintenance team is available the incident stays **New**.

## Tests

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

Result on this branch: `Ran 55 tests ... OK` (15 existing + 40 new),
`No changes detected`.
