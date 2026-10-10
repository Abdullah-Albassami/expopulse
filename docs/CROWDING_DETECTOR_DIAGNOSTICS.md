# CCTV crowding reliability — prototype evaluation

## What changed

- Configurable YOLO weights (`--model`) and inference size (`--imgsz`).
- Episode hysteresis: trigger after `--frames` consecutive observations >= `--threshold`; clear only after observations <= `--clear-threshold` persist for `--clear-seconds`. Counts between thresholds retain the active episode.
- Stream interruption stops clearance timing. Neither reconnect nor elapsed cooldown alone creates another incident.
- Before creating a CCTV Crowding incident, the detector looks for an unresolved incident with the same source and location. Existing incidents remain unchanged and get no duplicate team assignment.
- Visual clearance does **not** resolve the Django incident.

## Local usage

Use the existing FFmpeg/HLS demo from the project guide, then:

```bash
python manage.py detect_crowding --video 'http://127.0.0.1:8080/live.m3u8' \
  --location 'Transport Hub' --threshold 5 --frames 3 \
  --clear-threshold 3 --clear-seconds 10 --cooldown 60 \
  --model yolo11n.pt --imgsz 640
```

These parameters are **demo starting values, not validated real-world crowd-safety thresholds**. A new event within cooldown is suppressed until another properly cleared-and-retriggered episode; an unresolved database incident independently suppresses insertion.

## Tests (not executed from this GitHub-only environment)

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

Test video decoding on MP4 and HLS, with reconnection, on the developer Mac. Compare time-matched annotated frames for each source before drawing conclusions about HLS quality or model accuracy.

## Accuracy study still required

1. Collect several representative, authorized frames and annotate bounding boxes with `results[0].plot()`. Save diagnostic images locally, outside Git.
2. Record source resolution/FPS, actual inference `imgsz`, per-frame predicted counts, manually reviewed missed detections and false positives.
3. Evaluate `yolo11n.pt` and `yolo11s.pt` on **the same frames** and settings, recording CPU inference latency and counts. Larger model or higher detection count does not itself establish greater accuracy.
4. If major undercount persists, document that box counts are not reliable venue occupancy estimates and evaluate crowd-density approaches separately.

## Known limits

- The current schema has no camera identifier: cameras sharing one location and source share suppression scope.
- The database guard locks the Location row, which can serialize cooperating detector processes on databases with row locking, such as PostgreSQL. SQLite does not have equivalent row-level locking, so concurrent detector processes can race; this is **not an exactly-once guarantee**.
- Only operator workflow should resolve an incident or release a team.
- Blocking OpenCV stream reads may not respond promptly to Ctrl+C; no hard read timeout is implemented.
- A stream stall that returns no failure but eventually resumes is not explicitly detected. Clearance timing assumes the submitted observations are timely.
- Uncommitted local footage is required to diagnose undercount; no measurable accuracy improvement has been verified.
