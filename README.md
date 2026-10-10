# ExpoPulse — Smart Operations Center

ExpoPulse is a Django-based operations center developed for the **Expo 2030 Challenge 3.6**. It centralizes operational incidents, automatically calculates priorities, detects potential duplicates, assigns response teams, and tracks incidents through resolution.

This experimental branch introduces **AI-powered CCTV monitoring**, using YOLO and OpenCV to detect crowding from recorded footage or simulated live HLS streams.

> **Branch:** `experiment/cctv-crowding`  
> **Official branch:** `main`  
> **Repository:** [Abdullah-Albassami/expopulse](https://github.com/Abdullah-Albassami/expopulse)

## Features

- Unified operations dashboard with automatic updates approximately every 5 seconds.
- Incident creation, prioritization, and possible-duplicate detection.
- Automatic or operator-confirmed assignment of suitable response teams.
- Incident lifecycle: **New → Assigned → In Progress → Resolved**.
- CCTV crowd monitoring using YOLO11 and OpenCV.
- MP4 and simulated live HLS/M3U8 video processing.
- Basic HLS stream reconnection.

## Technology Stack

Python · Django 6.1.2 · SQLite · HTML/CSS/JavaScript · YOLO11 · OpenCV · FFmpeg

## Installation

Clone the experimental branch:

```bash
git clone -b experiment/cctv-crowding https://github.com/Abdullah-Albassami/expopulse.git
cd expopulse
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Initialize the database and start Django:

```bash
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Open **http://127.0.0.1:8000/**.

## CCTV Monitoring

The crowding detector is available at:

`incidents/management/commands/detect_crowding.py`

Place authorized footage in the local `footage/` directory.

### Local MP4

```bash
python manage.py detect_crowding \
  --video footage/indoor_crowd.mp4 \
  --location "Transport Hub" \
  --threshold 5 \
  --frames 3
```

### Simulated Live HLS Stream

Requires FFmpeg.

**Terminal 1 — Generate the stream**

```bash
mkdir -p streams/hls

ffmpeg -re -stream_loop -1 \
  -i footage/indoor_crowd.mp4 \
  -an -c:v libx264 -preset ultrafast \
  -pix_fmt yuv420p \
  -f hls -hls_time 2 \
  -hls_list_size 5 \
  -hls_flags delete_segments+omit_endlist \
  streams/hls/live.m3u8
```

**Terminal 2 — Serve the stream**

```bash
python3 -m http.server 8080 --directory streams/hls
```

**Terminal 3 — Start the detector**

```bash
python manage.py detect_crowding \
  --video "http://127.0.0.1:8080/live.m3u8" \
  --location "Transport Hub" \
  --threshold 5 \
  --frames 3
```

Run Django separately to view the live dashboard. Activate the virtual environment in terminals running Django commands.

The HLS stream is generated from looping prerecorded footage, not a physical live CCTV camera.

## Validation

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

**Latest baseline validation:** 15 tests passed, no system issues, and no pending migrations.

## Team Development

Additional CCTV incident detectors are being developed independently.

All development instructions, task requirements, integration rules, and pull-request procedures are documented in:

- [CCTV Team Integration](docs/CCTV_TEAM_INTEGRATION.md)
- [Ammar — Fall Detection](docs/Ammar_CCTV_Fall_Detection_Task.md)
- [Nasser — Obstruction Detection](docs/Nasser_CCTV_Obstruction_Detection_Task.md)
- [Mohammed — Cleaning Detection](docs/Mohammed_CCTV_Cleaning_Detection_Task.md)

## Current Limitations

- Crowd detection is based on YOLO person counts, not validated crowd density.
- Small or overlapping people may be missed.
- Repeated crowding episodes can generate multiple incident records.
- HLS reconnection is basic and has not been fully automated-tested.
- Additional incident detectors are under development.
- CCTV-generated alerts require operator verification.

**Status:** Experimental MVP. Keep changes isolated from the official `main` branch until reviewed.