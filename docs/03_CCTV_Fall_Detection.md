# ExpoPulse — CCTV Fall Detection: Start & Test

**Verified against:** `test/fall-detection-integration` · `incidents/management/commands/detect_falls.py`  
**Incident category:** Medical · **Source:** CCTV Monitoring · **Module:** CCTV Fall Detection.

This module uses **YOLO11 pose estimation and temporal posture/transition logic** to flag **possible falls for operator verification**. It is not a validated medical detector. See `docs/FALL_DETECTION_USAGE.md` for the teammate's full evaluation and limitations.

## Prerequisites

```bash
source venv/bin/activate
python manage.py check
ls -lh footage/fall-01-rgb.mp4
```

The dataset footage is **not checked into the repository**. Use an RGB-only prepared clip `footage/fall-01-rgb.mp4` (UR Fall Detection dataset) supplied by the teammate or prepare it from the original `fall-01-cam0.mp4`. The original camera MP4 contains depth+RGB side-by-side and **must be cropped to the RGB right half** before inference. If you already prepared `fall-01-rgb.mp4`, skip cropping.

### Optional: prepare RGB footage if only the original is available

```bash
python - <<'PY'
import cv2
from pathlib import Path
src = Path('footage/fall-01-cam0.mp4')
assert src.is_file(), f'Missing {src}'
cap = cv2.VideoCapture(str(src))
fps = cap.get(cv2.CAP_PROP_FPS)
assert cap.isOpened() and fps > 0, 'Could not read original MP4'
out = cv2.VideoWriter('footage/fall-01-rgb.mp4', cv2.VideoWriter_fourcc(*'mp4v'), fps, (320, 240))
assert out.isOpened(), 'Could not create RGB MP4'
while True:
    ok, frame = cap.read()
    if not ok:
        break
    assert frame.shape[1] >= 640, 'Expected depth+RGB side-by-side video'
    out.write(frame[:, 320:640])
cap.release()
out.release()
print('Created footage/fall-01-rgb.mp4')
PY
```

## Option A — Local MP4 test (simplest)

```bash
python manage.py detect_falls \
  --video footage/fall-01-rgb.mp4 \
  --location "Zone A" \
  --sample-every 3 --confirm-frames 5 --confidence 0.25 \
  --save-annotated footage/fall-01-confirmed.jpg
```

Database incident creation works without the Django HTTP server; start Django separately to view the incident. The annotated confirmation JPEG is created only if a confirmation occurs.

## Option B — Live HLS simulation (four terminals)

### Terminal 1 — Django dashboard

```bash
source venv/bin/activate
python manage.py runserver
```

### Terminal 2 — Loop the RGB fall clip as HLS

```bash
mkdir -p streams/fall
ffmpeg -re -stream_loop -1 -i footage/fall-01-rgb.mp4 \
  -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -f hls -hls_time 2 -hls_list_size 5 \
  -hls_flags delete_segments+omit_endlist streams/fall/live.m3u8
```

### Terminal 3 — Host the playlist

```bash
python -m http.server 8080 --directory streams/fall
```

### Terminal 4 — Run the fall detector

```bash
source venv/bin/activate
python manage.py detect_falls \
  --video http://127.0.0.1:8080/live.m3u8 \
  --location "Zone A" \
  --sample-every 3 --confirm-frames 5 --confidence 0.25 \
  --retry-delay 5 --max-retries 0
```

Start FFmpeg and HTTP hosting **before** the detector. The first YOLO execution might fetch `yolo11n-pose.pt` if not already cached.

## What to check

1. Console: `Loading YOLO11 pose model...`, `Video source connected.`, `Possible Fall Detected — operator verification required.`
2. Django creates `CCTV Possible Fall - Zone A` as **Medical** and assigns an available Medical team if eligible.
3. Open <http://127.0.0.1:8000/> and check the monitoring channel and incident details.
4. With the fall incident still unresolved, replay the clip. Verify `Duplicate suppressed.` (or `Cooldown active; incident creation suppressed.` within the same session); don't expect another incident.
5. Visual event clearing **must not** automatically resolve the Medical incident or release its team.
6. Test a negative clip such as `adl-01-rgb.mp4` (normal activity) by substituting the file/stream; it should not raise a fall incident for that footage.

## Troubleshooting

- `Video file not found`: the sample footage is not included in Git; request the prepared RGB MP4 or acquire it from UR Fall Detection dataset.
- Detector runs but no incident: verify RGB-only clip, appropriate camera view, and at least five qualifying **sampled** lying frames. The documented benchmark misses some actual falls; lack of alert isn't always a configuration error.
- `Duplicate suppressed.` immediately: an unresolved `CCTV Possible Fall - Zone A` incident already exists. Use another valid Location for a fresh test or resolve the original through normal operator workflow.
- `Stream unavailable`: verify playlist via `curl -I http://127.0.0.1:8080/live.m3u8` and ensure HLS segments exist.
- Time base fallback: stream timestamps might be unavailable; HLS bursts can then distort temporal transition estimates.
- If `--save-annotated` is used, check the resulting image rather than expecting a new file on negative footage.

## Shutdown / tests

Ctrl+C detector, FFmpeg, HTTP server, and Django. `python manage.py test incidents.tests_fall_detection` tests fall module; `python manage.py test incidents` runs full regression. The user previously ran **136 passing tests** on the combined branch; this does not replace testing your video/stream.
