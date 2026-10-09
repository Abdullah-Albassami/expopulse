# ExpoPulse — Experimental Branch Updates

**Branch:** `experiment/cctv-crowding`  
**Purpose:** Integrate the ExpoPulse MVP and test automated CCTV crowding alerts without modifying `main`.

## Integrated MVP

- Added Nasser's Django templates, CSS, JavaScript, and five pages: dashboard, incident list, incident detail, create incident, and teams.
- Connected Django views, URL routes, and an incident creation form.
- Integrated Ammar's automatic priority scoring, 15-minute duplicate detection, and incident status validation.
- Integrated Mohammed's team suggestion/assignment, team availability handling, and demo-data command.
- Added dashboard metrics, incident search/filters, priority/status charts, and duplicate warnings.
- Completed the manual workflow: **New → Assigned → In Progress → Resolved**, with team released on resolution.

## CCTV Crowding Prototype

- Added `detect_crowding` management command using **OpenCV + YOLO**.
- Processes recorded MP4 footage, detects/counts people, and triggers alerts when a configurable threshold is met over consecutive sampled frames.
- Creates `Crowding` incidents through the existing Django service, automatically calculating priority and checking possible duplicates.
- Attempts automatic Security team assignment for non-duplicate alerts; duplicate alerts do not receive a second assignment.
- Added configurable detection threshold, sampling, confidence, and cooldown settings.

## Live Dashboard Enhancements

- Added `/dashboard/data/` JSON endpoint and **5-second polling** (no WebSockets).
- Dashboard updates incident rows, summary counters, and charts without manual refresh.
- Preserves the selected dashboard filter and displays a new-incident notification.

## Verification Completed

- `python manage.py check` — passed.
- `python manage.py makemigrations --check --dry-run` — no changes detected.
- `python manage.py test incidents` — **15/15 existing tests passed**.
- Seeded demo records and recalculated priorities.
- Manually verified incident creation, assignment, resolution, and team release.
- Confirmed CCTV-generated incidents **#8 and #9**: #9 referenced #8 as a possible duplicate; #8 was assigned Security Team 1.
- Confirmed an incident appeared on the dashboard automatically via polling.

## Limitations / Next Steps

- **HLS/M3U8 live-stream simulation with FFmpeg** is planned, not yet verified.
- Current crowding trigger is a person-count heuristic, **not calibrated crowd-density or safety detection**.
- Existing 15 automated tests do not yet cover the CCTV detector, dashboard polling, or complete integration.
- This is an experimental demo branch, **not the official `main` submission**. Use the branch README for macOS/Windows setup and safe collaboration.
