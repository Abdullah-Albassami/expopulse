# Restricted-area detection guide

This detector uses Ultralytics YOLO11 persons only, checks them as per-frame zone occupancy (tracking IDs optional), and checks whether the bottom center of each detected person falls inside a configured restricted polygon.

## Example config

```json
{
  "zone_id": "STAFF_ONLY_A",
  "name": "Staff-Only Corridor",
  "polygon": [[0.52, 0.26], [0.94, 0.26], [0.98, 0.96], [0.48, 0.96]]
}
```

The polygon coordinates are normalized between 0 and 1 for the original video frame. The detector converts them to pixel coordinates using the actual video dimensions. Boundary points count as inside by using `cv2.pointPolygonTest(..., measureDist=False)` with a threshold of zero.

## Run the detector

```bash
python manage.py detect_restricted_area \
  --video footage/restricted_zone_demo.mp4 \
  --location "Zone A" \
  --zone-config configs/restricted_zone.example.json \
  --confirm-frames 5 \
  --clear-frames 10 \
  --sample-every 1 \
  --confidence 0.35 \
  --cooldown 60
```

Different restricted zones at the same location are not treated as duplicates of each other; other existing Security incident duplicate warnings remain in effect. The detector creates one Security incident titled `CCTV Restricted Zone [STAFF_ONLY_A] - Zone A` when one tracked person stays inside the zone long enough. It suppresses extra incidents while the same unresolved incident remains active and respects the shared duplicate service by not assigning a team when `possible_duplicate_of` is set.

## Live simulated CCTV with HLS

The detector accepts an HTTP HLS playlist. Use three terminals from the repository root.

### Terminal 1: generate a looping HLS stream

PowerShell:

```powershell
New-Item -ItemType Directory -Force streams\hls | Out-Null
ffmpeg -re -stream_loop -1 `
  -i footage\restricted_zone_demo.mp4.mp4 `
  -an -c:v libx264 -preset ultrafast `
  -pix_fmt yuv420p `
  -f hls -hls_time 2 `
  -hls_list_size 5 `
  -hls_flags delete_segments+omit_endlist `
  streams\hls\live.m3u8
```

Keep this terminal running. The source video remains local and `streams/` is ignored by Git.

### Terminal 2: serve the HLS files

PowerShell:

```powershell
python -m http.server 8080 --directory streams\hls
```

Verify that `http://127.0.0.1:8080/live.m3u8` is reachable before starting the detector.

### Terminal 3: run the restricted-area detector

PowerShell:

```powershell
.\venv\Scripts\python.exe manage.py detect_restricted_area `
  --video "http://127.0.0.1:8080/live.m3u8" `
  --location "Zone A" `
  --zone-config "configs\restricted_zone.example.json" `
  --confirm-frames 5 `
  --clear-frames 10 `
  --sample-every 1 `
  --confidence 0.35 `
  --cooldown 60 `
  --retry-delay 5 `
  --max-retries 0
```

`--max-retries 0` means reconnect indefinitely while the HLS source is unavailable. A short stream interruption is not treated as an empty zone. Press `Ctrl+C` in the detector terminal to stop it, then stop the HTTP server and FFmpeg terminals. If the matching incident is still unresolved, replaying the stream reports `already_active` instead of creating another database row.

## Caveats

- This is a camera-plane approximation and does not prove authorization.
- Occlusion, perspective distortion, truncated persons, and missed detections can affect the decision.
- Tracking IDs are optional. The detector confirms continuous zone occupancy over sampled frames, including multiple people, and clears after consecutive sampled frames without a person in the zone. It cannot determine individual identities.
