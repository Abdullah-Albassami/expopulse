# Nasser — Live IoT Equipment Fault Monitoring

**Project:** ExpoPulse (Expo 2030 Challenge 3.6)
**Assigned to:** Nasser
**Base / PR target:** `experiment/cctv-crowding` (never `main`)
**Your feature branch:** `feature/equipment-fault-monitoring`
**Deliverable:** A working, **simulated LIVE IoT telemetry pipeline over HTTP using JSON**, generating verified-by-software *potential* Maintenance incidents for elevators and escalators.

> **Paste this entire document into your coding agent.** Implement the required feature, tests, and documentation in the actual repository. Do not substitute a static JSON-file reader, a manually triggered incident, or a UI-only mockup. Do not build CCTV escalator-motion analysis: that is **out of scope**.

## 1. Outcome / live demo

Build this functioning workflow:

`Python IoT simulator → HTTP POST JSON → Django equipment monitoring endpoint → fault-state/deduplication logic → existing create_incident() → existing Maintenance team assignment → existing live ExpoPulse dashboard`

For example, the simulator emits **normal readings every few seconds**, then injects a simulated elevator `DOOR_STUCK` fault, then repeated readings of the same fault, then recovery. It also simulates an escalator `EMERGENCY_STOP`. The *first* fault should create exactly one Maintenance incident per equipment fault episode; repeated packets must **not** create additional incidents. The dashboard should show the result (with Django running). When a Maintenance team is free, it should be assigned through ExpoPulse's existing service. All values and fault thresholds are **synthetic demonstration data**, not actual manufacturer telemetry or approved safety thresholds.

## 2. Repository synchronization — do this first

Repository: `https://github.com/Abdullah-Albassami/expopulse` (private; confirm your account has access). If your coding agent has a GitHub connector, connect/authorize this repository and read the branch contents. Otherwise work from a local clone; **prefer reading local checked-out files** if already cloned. Do not guess existing interfaces or overwrite teammates' work.

```bash
git clone -b experiment/cctv-crowding https://github.com/Abdullah-Albassami/expopulse.git
cd expopulse
git switch -c feature/equipment-fault-monitoring
```

If already cloned and clean: `git fetch origin && git switch experiment/cctv-crowding && git pull --ff-only && git switch -c feature/equipment-fault-monitoring`. If local changes exist, coordinate/stash safely; never discard them or force push.

Create/activate a virtual environment (macOS: `python3 -m venv venv && source venv/bin/activate`; Windows PowerShell: `py -m venv venv; .\venv\Scripts\Activate.ps1`), then `python -m pip install -r requirements.txt`, `python manage.py migrate`, and `python manage.py seed_data` **once** on a fresh local database.

**Read before editing:** `incidents/models.py`, `incidents/services/{incident_service,assignment,duplicates,priority}.py`, `incidents/urls.py`, `config/urls.py`, `incidents/management/commands/seed_data.py`, `incidents/tests.py`, `README.md`, and `docs/CCTV_TEAM_INTEGRATION.md` if present. Adjust integrations to the actual branch. Ask your agent to inspect code and propose a minimal integration plan before changing shared files.

## 3. Scope and data contract (required)

Implement an **HTTP JSON telemetry receiver** in Django and a **separate Python simulator** that sends new readings in real time (e.g., one every 2 seconds). This must be a real request/response exchange over localhost HTTP, not loading a prerecorded JSON file. The simulator can use standard-library `urllib.request` (or existing `requests`) and run on macOS or Windows. No proprietary hardware, paid API, MQTT broker, or external network service is required.

Use an explicit route such as `POST /api/equipment/readings/` registered through the project's URL structure. Example payload (one JSON object per POST):

```json
{
  "equipment_id": "ELEV-A1",
  "equipment_type": "elevator",
  "location": "Main Entrance",
  "status": "normal",
  "fault_code": null,
  "motor_temperature": 42.5,
  "timestamp": "2026-10-10T10:00:00Z"
}
```

A *fault* packet can be:

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

**Required fields:** `equipment_id` (nonblank ID, max 64 chars, safe characters e.g. letters/digits/hyphens/underscores); `equipment_type` exactly `elevator` or `escalator`; `location` must match an existing `Location`; `status` exactly `normal`, `fault`, or `recovered`; `fault_code` nonblank only when `status=fault` (otherwise `null`); ISO 8601 timezone-aware `timestamp`. Optional `motor_temperature` is a finite numeric demo reading; **do not infer a fault solely from arbitrary temperature thresholds**. Reject unknown/invalid input fields or document an explicit allowlist; reject invalid JSON, wrong content type, oversized body, and unsupported HTTP methods. Return meaningful JSON responses and suitable status codes (`201` for newly created incident, `200` for accepted no-op/repeat, `400`/`404` for invalid input/location, `401`/`403` for unauthorized requests). Include stable response fields such as `accepted`, `equipment_id`, `action` (`normal`, `created`, `already_active`, `recovered`), and `incident_id` where applicable.

**Security baseline:** This is a *local demonstration* endpoint. Require a shared API token read from environment variable `EXPOPULSE_EQUIPMENT_API_TOKEN` and supplied in `X-Equipment-Token` header; never commit the token. If using `csrf_exempt` for this machine-to-machine endpoint, explain that API-token authentication substitutes for browser CSRF protection in this prototype. Avoid opening the development endpoint to the public internet; avoid printing the token in logs or README examples. Test missing/incorrect token. Do not log personal or sensitive data.

## 4. Fault lifecycle and duplicate prevention (required)

The central rule: **one active fault per equipment ID = at most one unresolved ExpoPulse incident.** Do not rely solely on `possible_duplicate_of`: the shared `create_incident()` *creates a row even for duplicates*.

- `normal`: record/log normal state; no incident.
- First `fault` for an equipment ID: create one incident (subject to existing active-incident check), assign Maintenance team if appropriate.
- Repeated `fault` packets from the **same equipment ID**: respond `already_active`, do not create an incident or reassign a team. Different fault codes while already active should be logged, not spawn new rows for MVP.
- `recovered`: log recovery and reset simulator/monitoring state; **do not automatically resolve an existing incident or release a team**—that is the operator's responsibility.
- Subsequent `fault` while an **unresolved incident** still exists for this equipment ID: suppress creation even after simulator restart or recovered packet.
- After the old incident is resolved and a fresh fault arrives, a **new incident may be created**. Do not reopen resolved incidents.
- Separate equipment IDs, even at the same location, must be processed independently.

Persistence: Avoid database schema changes. Before creation, search for an **unresolved** Equipment Monitoring Maintenance incident with an **unambiguous stable equipment identifier**. Use a documented exact-match naming convention (e.g., `Equipment Fault [ELEV-A1]`) with a validated ID so `ELEV-A1` cannot collide with `ELEV-A10`; alternatively introduce a dedicated small helper keyed by ID without migrations. Clearly document that this is a prototype, not industrial telemetry event sourcing. Ensure duplicate prevention is safe for parallel requests: prefer an application-level serial processing approach for the local demo, or explain and test concurrency limits; don't claim an atomic uniqueness guarantee without a database constraint.

The existing shared duplicate detector may flag two **different** devices in the same location/type as possible duplicates. **Do not change the shared service.** Treat those as distinct equipment events in your module; document when the existing duplicate flag affects assignment. Avoid assigning two teams to a flagged duplicate unless the team lead approves a rule change.

## 5. Existing ExpoPulse integration (required)

Use the current model choices and **existing services**, not raw `Incident.objects.create()` or hardcoded scores:

```python
from incidents.models import Incident, IncidentSource, Location
from incidents.services.incident_service import create_incident
from incidents.services.assignment import assign_team_to_incident

source, _ = IncidentSource.objects.get_or_create(
    name="Equipment Monitoring",
    defaults={"source_type": IncidentSource.SourceType.SENSOR},
)
incident = create_incident(
    title="Equipment Fault [ESC-001]",
    description=("Simulated escalator fault EMERGENCY_STOP at Main Entrance; "
                 "operator verification required."),
    incident_type=Incident.IncidentType.MAINTENANCE,
    source=source,
    location=location,  # existing Location object
    severity=Incident.Severity.HIGH,
    people_affected=0,
)
if not incident.possible_duplicate_of_id:
    assign_team_to_incident(incident)
```

The above is an **interface illustration**, not a complete view. Use a small documented synthetic severity map: `EMERGENCY_STOP` = critical, `DOOR_STUCK` / `MOTOR_FAULT` = high, unknown fault = medium. Never claim the error code indicates a real manufacturer's diagnosed failure. `MAINTENANCE` already maps to Maintenance response teams; seed data includes `Maintenance Team 1`. If none is available, incident remains New. Existing dashboard polling should display incidents automatically; **do not edit the dashboard/UI unless genuinely necessary and approved**.

## 6. Simulator behavior (required)

Create a command such as `python manage.py simulate_equipment --url http://127.0.0.1:8000/api/equipment/readings/ --interval 2` that uses HTTP POST JSON to Django. It must **generate and transmit** a deterministic demonstration sequence at runtime, including:

1. Elevator normal readings → `DOOR_STUCK` fault → several repeated fault readings → recovered.
2. Escalator normal readings → `EMERGENCY_STOP` fault → repeated fault readings → recovered.
3. Two distinct devices sending faults (to prove independent equipment IDs).
4. Optional `--loop` continuous simulation that does **not** flood the incident table; support `Ctrl+C` cleanly.

Read API token from the same environment variable. Offer flags for `--interval` (nonnegative), `--url` (default localhost) and optional `--loop`. Print concise status, HTTP responses, and incident ID on creation, but never print secret tokens. Handle server unavailable/HTTP errors gracefully without a traceback storm. Keep code portable between macOS and Windows. **No static JSONL file as the main input/source**; small sample JSON fixtures are acceptable *for tests only*.

## 7. File ownership and integration boundaries

Recommended new files (adapt minimally to existing structure):

- `incidents/services/equipment_monitoring.py` — validation / incident mapping / active-incident suppression.
- `incidents/views_equipment.py` — authenticated JSON API view.
- `incidents/management/commands/simulate_equipment.py` — live IoT simulator.
- `incidents/tests_equipment.py` — focused automated tests.
- `docs/Nasser_Equipment_Fault_Detection_Task.md` — this assignment.
- `docs/Equipment_Monitoring_Demo.md` — concise setup, two-terminal instructions, example outputs, limitations.

Minimal URL addition in `incidents/urls.py` (or existing routed module) is permitted. Avoid changing `incidents/models.py`, migrations, dashboard templates/JS, priority, duplicates, workflow, or assignment services. Coordinate with team leader before any shared-interface change. Add dependencies only if essential; prefer Python standard library + installed Django. No generated files, virtual environment, `.env` secrets, database, or videos in Git.

## 8. Required tests — implement automated tests, not only manual screenshots

Use Django `TestCase`, `Client`, `unittest.mock`, and controlled time/data as appropriate. Cover at minimum:

1. Valid normal packet: accepted, no incident.
2. First fault packet: creates exactly one Maintenance incident with correct source, location, type, and synthetic severity.
3. Repeated identical fault: no second incident.
4. Another fault code while already active: no second incident.
5. Recovery: no new incident, doesn't mark previous one Resolved or release its team.
6. Restart-equivalent repeated fault / same equipment unresolved: still no extra incident.
7. Previously resolved incident followed by a new fault: creates a new incident.
8. Different equipment IDs at same location: distinct fault incidents (subject to existing possible-duplicate flag, but not suppressed as the same equipment).
9. Available Maintenance team is assigned when incident is not flagged as duplicate; no team available leaves incident New.
10. Bad JSON, missing/invalid fields, bad timestamp, unknown location, wrong method/content type, oversized payload return useful errors without incident creation.
11. Missing/invalid API token is rejected; correct token accepted.
12. Simulator sends actual HTTP JSON messages and handles connection errors (mock `urllib`/requests where appropriate).

Run and report:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

The existing repository previously passed 15 tests. **Your additions must pass without breaking them**. `makemigrations` should report no changes.

## 9. Manual acceptance demo

1. In **Terminal A**, with venv and token environment variable set, run `python manage.py runserver`.
2. In **Terminal B**, same venv and token setting, run your `simulate_equipment` command at 2-second intervals.
3. Open `http://127.0.0.1:8000/`: see new Maintenance incident(s) appear via existing dashboard polling (~5 seconds).
4. Verify incident type, source `Equipment Monitoring`, priority, location, and Maintenance assignment when a team is available.
5. Confirm repeated fault readings do **not** create new rows; recovery doesn't auto-resolve incidents; restarting simulator while incident is unresolved also doesn't create another.
6. Resolve an incident through the normal operator workflow, then simulate a **new** fault and verify a new incident can be created.
7. Save a short log/screenshot for PR evidence. State explicitly that readings are simulated.

**Definition of done:** Actual timed HTTP POST traffic, correct state transitions and suppression, valid API security baseline, working ExpoPulse integration, tested error handling, zero migrations, passing automated tests, and repeatable demo. If any part fails, report it rather than claiming completion.

## 10. Commit, push, pull request

```bash
git status
git add incidents/services/equipment_monitoring.py incidents/views_equipment.py \
  incidents/management/commands/simulate_equipment.py incidents/tests_equipment.py \
  incidents/urls.py docs/Equipment_Monitoring_Demo.md
# Stage the task guide too only if you created/updated it locally.
git diff --cached --check
git diff --cached --stat
git commit -m "Add simulated live IoT equipment fault monitoring"
git push -u origin feature/equipment-fault-monitoring
```

Adjust `git add` paths to the files actually created. Open a PR **from** `feature/equipment-fault-monitoring` **into** `experiment/cctv-crowding` (**not** `main`). PR description must include files changed, how to run Django and simulator, sample API payload, screenshots/logs, test results, security/limitations, and any integration concerns. Do not merge your own PR or force-push shared branches. If your AI agent can access GitHub, it may inspect code and draft the PR, but push/PR actions require your authorization and must target the specified branches.

### Explicit non-goals

No real elevator API integration, no hardware sensors, no MQTT, no CCTV escalator detector, no machine-learning model training, no custom frontend dashboard, no new database models, and no automatic incident resolution upon equipment recovery. Focus on a robust **live simulated telemetry → HTTP JSON → Maintenance incident** MVP.
