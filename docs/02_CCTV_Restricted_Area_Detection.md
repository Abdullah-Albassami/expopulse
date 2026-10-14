# ExpoPulse — CCTV Restricted-Area Detection: Start & Test

**Verified against:** `test/fall-detection-integration` · `incidents/management/commands/detect_restricted_area.py`  
**Incident category:** Security · **Source:** CCTV Monitoring · **Module:** CCTV Restricted-Area Detection.

## Prerequisites and camera-specific zone

From the `expopulse-cctv-lab` project root:

```bash
source venv/bin/activate
python manage.py check
ls -lh footage/restricted_area_demo.mp4
```

**The demo filename above is a placeholder**: use your real MP4 file showing someone entering a restricted area, and update the commands below. Ideally the video starts empty, then a person enters the polygon. The module needs a **JSON polygon fitted to that particular camera angle**; don't assume a sample polygon matches your footage.

Create a demo zone configuration (edit coordinates for your footage):

```bash
mkdir -p configs
cat > configs/restricted_zone_a.json <<'JSON'
{
  "zone_id": "STAFF_ONLY_A",
  "name": "Staff-Only Area A",
  "polygon": [[0.55, 0.35], [0.95, 0.35], [0.95, 0.95], [0.55, 0.95]]
}
JSON
```

The coordinates are **normalized fractions** of frame width/height (0–1). This example defines a rectangle in the lower-right region. The incident is based on the **bottom center of a detected person's box**, so ensure that their feet enter this zone. Use a camera-specific configuration for meaningful results.

## Option A — Local video test

```bash
python manage.py detect_restricted_area \
  --video footage/restricted_area_demo.mp4 \
  --location "Zone A" \
  --zone-config configs/restricted_zone_a.json \
  --confirm-frames 5 --clear-frames 10 \
  --sample-every 1 --confidence 0.35
```

`--show` optionally opens an OpenCV window to inspect the video (not required for incident creation). The detector creates database incidents without an HTTP Django server; run Django separately to view the dashboard.

## Option B — Simulated live HLS (four terminals)

### Terminal 1 — Django

```bash
source venv/bin/activate
python manage.py runserver
```

### Terminal 2 — FFmpeg (replace the MP4 filename)

```bash
mkdir -p streams/restricted
ffmpeg -re -stream_loop -1 -i footage/restricted_area_demo.mp4 \
  -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -f hls -hls_time 2 -hls_list_size 5 \
  -hls_flags delete_segments+omit_endlist streams/restricted/live.m3u8
```

### Terminal 3 — HTTP server

```bash
python -m http.server 8080 --directory streams/restricted
```

### Terminal 4 — Restricted-area detector

```bash
source venv/bin/activate
python manage.py detect_restricted_area \
  --video http://127.0.0.1:8080/live.m3u8 \
  --location "Zone A" \
  --zone-config configs/restricted_zone_a.json \
  --confirm-frames 5 --clear-frames 10 \
  --sample-every 1 --confidence 0.35 \
  --retry-delay 5 --max-retries 0
```

Only one HLS server can use port 8080 at a time. For parallel CCTV demos, use unique ports/playlists and pass each URL to the appropriate detector.

## Expected outcome / verification

- `Restricted-area detector started ...`, `Video source connected.`
- `Candidate person inside restricted zone.` followed by `Restricted-zone occupancy confirmed.` after enough consecutive sampled frames.
- One Security incident titled similarly to `CCTV Restricted Zone [STAFF_ONLY_A] - Zone A`.
- An available Security team may be assigned; verify in <http://127.0.0.1:8000/>.
- Repeated presence of the same unresolved zone incident should show `already_active: incident #...`, not create a second one from this detector.
- Leaving the zone may clear the **visual event**, but it does not resolve the incident or free the team.

## Troubleshooting

- `Invalid zone config`: verify valid JSON, unique polygon vertices, non-self-intersecting polygon, and 0–1 coordinates.
- Person visible, no alert: check whether bottom-center position actually falls inside the polygon; try a wider polygon **only for diagnosis**.
- URL fails: start FFmpeg first, then the HTTP server; check `curl -I http://127.0.0.1:8080/live.m3u8`.
- No incident: verify person is visible within the region for `--confirm-frames` sampled observations; inspect confidence.
- No team assigned: matching team may be unavailable or shared duplicate detection may have linked a separate Security incident.

## Shutdown and regression

Ctrl+C detector → FFmpeg → HTTP server → Django. Run `python manage.py test incidents` for regression checks. **Avoid running `seed_data` over an active demo database.**
