# ExpoPulse — Smart Operations Center

**Expo 2030 Challenge 3.6** · **Vision Crew** · **Django prototype**

ExpoPulse brings operational incidents from simulated CCTV monitoring, external equipment-status data, and manual staff reports into one operations dashboard. It prioritizes incoming incidents, flags possible duplicates, recommends suitable response teams, and tracks work from **New → Assigned → In Progress → Resolved**.

> **Prototype disclaimer:** CCTV feeds in this repository replay prerecorded video as live HLS streams; they are not connected to cameras at Expo. The equipment module uses publicly available **Paris Open Data** elevator/escalator status records—not Expo equipment or IoT telemetry. Detector alerts require operator verification. This project is a demonstration, not a deployed safety-critical system.

## Features

| Area | Functionality |
|---|---|
| Operations dashboard | Priority and status summaries, incident queue, approximately 5-second updates |
| Incidents | Manual reporting, automatic priority scoring, possible-duplicate detection, assignment and lifecycle management |
| Live cameras | Three browser-viewable simulated HLS feeds at `/live/` with recent associated alerts |
| Crowd monitoring | YOLO-based person counting and configurable threshold/confirmation |
| Restricted areas | Person detection in a configured restricted polygon |
| Fall monitoring | YOLO pose-based possible-fall detection with temporal confirmation |
| Equipment | Public elevator/escalator operational-status feed (live polling or historical CSV replay), mapped to demonstration locations |
| Teams | Matching incident types to available response teams and tracking their assignments |
| Interface | English/Arabic toggle with RTL layout and dark/light appearance |

## Tech stack

Python · Django 6.1.2 · SQLite (local prototype) · HTML/CSS/JavaScript · Ultralytics YOLO · OpenCV · FFmpeg · HLS

## Setup

**Requirements:** Python compatible with the pinned packages in `requirements.txt`, FFmpeg available on your PATH, and Git. The CCTV models may be downloaded by Ultralytics on first use; network access can be required. Use this project for local demonstrations, not public production deployment.

```bash
git clone https://github.com/Abdullah-Albassami/expopulse.git
cd expopulse
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Open **http://127.0.0.1:8000/**.

**Windows PowerShell:** replace environment setup with:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

## Run the complete local demo

Stop any separate Django development server before using `all` mode: the runner starts its own Django process and three CCTV HLS streams. Ensure FFmpeg is installed and the three example videos are present in `footage/`.

**macOS:**

```bash
export EXPOPULSE_EQUIPMENT_API_TOKEN="local-demo-token"
./run_simulation.sh all
```

**Windows PowerShell:**

```powershell
$env:EXPOPULSE_EQUIPMENT_API_TOKEN = "local-demo-token"
.\run_simulation.ps1 all
```

Visit **Dashboard:** http://127.0.0.1:8000/ · **Live cameras:** http://127.0.0.1:8000/live/ · **Incidents:** http://127.0.0.1:8000/incidents/ · **Teams:** http://127.0.0.1:8000/teams/

The runner uses local HLS ports **8081** (crowd), **8082** (restricted areas), and **8083** (fall); Django serves the browser camera page over port **8000**. Stream videos are unannotated footage: detection events are recorded in `streams/logs/` and appear as incidents. Press **Ctrl+C** to stop the runner.

The equipment source is an external public feed and may be unavailable or change independently of this prototype. The Mac `main` runner currently polls all eligible feed devices in `all` mode; demo alert volume can be high. A proposed reduction to one sample device is pending in [PR #12](../../pull/12).

## Verify

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

The commands above are the **recommended checks**, not a claim that tests were executed for this submission. Run them before presenting.

## Project layout

```text
config/                Django project configuration
incidents/             Models, forms, services, views, management commands and tests
templates/             Dashboard, incidents, response teams and live camera pages
static/                Styles, scripts, translations and bundled browser HLS player
footage/               Prerecorded demonstration videos
configs/               Detection-area configuration
data/equipment/paris/  Equipment-status snapshot for reproducible replay
docs/                  Technical and demonstration notes
run_simulation.sh       Combined macOS demo runner
run_simulation.ps1      Combined Windows demo runner
requirements.txt       Pinned Python dependencies
```

## How monitoring works

1. **CCTV demonstration:** FFmpeg replays sample footage as HLS. OpenCV/YOLO processes frames and confirms possible crowding, restricted entry, or a fall.
2. **Equipment monitoring:** publicly published Paris equipment-status records are checked for reported faults and sent through a token-protected local API.
3. **Incident workflow:** ExpoPulse records alerts, prioritizes them, checks for possible duplicates, and supports response-team assignment and resolution.
4. **Operator interface:** the dashboard and live-camera page show current incidents and monitoring streams.

### Other documentation

- [External equipment data](docs/Equipment_External_Data.md)
- [Equipment demo](docs/Equipment_Monitoring_Demo.md)
- [Demo walkthrough](docs/demo_scenario.md)
- [Frontend technical notes](FRONTEND_README.md)

Some technical documents also preserve earlier integration and team-development notes; this README is the entry point for the **current integrated prototype**.

## Limitations and responsible use

- Prerecorded HLS is **simulated live video**, not surveillance hardware integration.
- YOLO predictions may be incorrect; crowd counts, fall alerts and restricted-area alerts need human confirmation.
- The public equipment feed reports operational status, not the root cause of a fault or visitor impact.
- Demo locations are illustrative; they are not geolocations of the Paris hardware.
- SQLite, development settings and the local API token are intended for a **local prototype only**; do not expose the development server to the public internet.
- Sample incidents may be mixed with live demonstration alerts. Check your local database before the presentation.
- Proposed priority-balancing and Arabic terminology refinements are pending in [PR #12](../../pull/12) and [PR #13](../../pull/13), respectively.

## Team

**Vision Crew** — Expo 2030 Challenge 3.6.

© 2026 ExpoPulse. Prototype for demonstration and evaluation.
