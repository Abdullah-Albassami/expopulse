# ExpoPulse — CCTV Crowd Detection: Start & Test

**Verified against:** `test/fall-detection-integration` · `incidents/management/commands/detect_crowding.py`  
**Incident category:** Crowding · **Source:** CCTV Monitoring · **Typical response:** available relevant team.

## Prerequisites (from the `expopulse-cctv-lab` project root)

```bash
source venv/bin/activate
python manage.py check
python manage.py showmigrations incidents
ls -lh footage/indoor_mall_cctv.mp4
```

If the footage file is absent, supply an MP4 containing visible crowds and replace the filename below. Use an existing database with seeded Locations/Teams; **do not run `seed_data` merely to start a detector**, since reseeding can modify demonstration records. For initial setup only, follow the project's seed instructions.

## Option A — Fastest local MP4 test (no Django server needed for database writes)

```bash
python manage.py detect_crowding \
  --video footage/indoor_mall_cctv.mp4 \
  --location "Gate 1" \
  --threshold 5 --frames 3 --sample-every 5
```

The detector writes incidents through Django's ORM. Open the dashboard separately (see below). A video containing too few visible people will not trigger a crowding incident.

## Option B — Simulated live CCTV via local HLS

Open **four terminals** in the project root. Start in this order:

### Terminal 1 — Django dashboard

```bash
source venv/bin/activate
python manage.py runserver
```

### Terminal 2 — FFmpeg creates a looping CCTV stream

```bash
mkdir -p streams/crowd
ffmpeg -re -stream_loop -1 -i footage/indoor_mall_cctv.mp4 \
  -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -f hls -hls_time 2 -hls_list_size 5 \
  -hls_flags delete_segments+omit_endlist streams/crowd/live.m3u8
```

### Terminal 3 — Host HLS over HTTP

```bash
python -m http.server 8080 --directory streams/crowd
```

Check the playlist in a separate terminal with `curl -I http://127.0.0.1:8080/live.m3u8`. Wait for FFmpeg to generate files.

### Terminal 4 — Start crowd detector

```bash
source venv/bin/activate
python manage.py detect_crowding \
  --video http://127.0.0.1:8080/live.m3u8 \
  --location "Gate 1" \
  --threshold 5 --frames 3 --sample-every 5 \
  --retry-delay 5 --max-retries 0
```

**Never start a second module on port 8080 simultaneously without assigning a different port.**

## Expected console and dashboard checks

- `Loading YOLO11n model...`, `Video source connected.`, `Frame ...: N people detected`.
- After **three consecutive sampled frames** with at least **five people**, a log such as `CROWDING DETECTED: 5 people at Gate 1` appears.
- A `CCTV Crowding Alert - Gate 1` incident is created (or flagged as a possible duplicate by shared incident logic).
- Dashboard: <http://127.0.0.1:8000/>; incident category **Crowding**, monitoring module **CCTV Crowd Detection**, check priority/team assignment and operator workflow.
- When the people count stays below threshold for three sampled frames, the episode clears. The **incident does not automatically resolve**.

### Important duplicate behavior

The crowd detector uses an in-process episode/cooldown mechanism and the shared incident duplicate service; it does **not guarantee zero new rows** across every restart. Check actual incident IDs rather than assuming perfect database-level suppression.

## Troubleshooting

- `Location ... not found`: use an existing Location name or initialize the database once.
- `Cannot open local video`: confirm MP4 path; run `ls -lh`.
- `Stream unavailable`: check FFmpeg and HTTP server; try `curl -I .../live.m3u8`.
- No alert: use footage with >=5 detected people in three consecutive **processed** frames, or lower `--threshold` temporarily to test wiring.
- No team assigned: the matching team may be Busy or the incident may be a possible duplicate.
- YOLO may download `yolo11n.pt` on first use; an Internet connection may be required once.

## Shutdown

Press **Ctrl+C** in detector, FFmpeg, HTTP server, and Django terminals. Do not resolve or delete incidents automatically for cleanup. Use `python manage.py test incidents` for regression tests.
