# CCTV Possible-Fall Detection — Usage

`detect_falls` watches a recorded MP4 **or a simulated live HLS/M3U8 stream**. When a person falls and stays lying down, it raises a **"CCTV Possible Fall"** Medical incident.

This is a prototype hint for operators. Every alert says **Possible Fall Detected — operator verification required**. It does not diagnose a fall or a medical emergency, and it has no measured real-world accuracy.

```
MP4 / HLS → OpenCV → yolo11n-pose → IoU person tracks → posture rule
        → transition check → candidate/confirmed/cleared per person
        → create_incident() → Medical team → dashboard
```

| File | Purpose |
|---|---|
| `incidents/cctv/fall_detection.py` | Posture rule, tracking, transition evidence, stream clock, incident notifier |
| `incidents/management/commands/detect_falls.py` | CLI, video/stream loop, reconnection, logs |
| `incidents/tests_fall_detection.py` | Offline tests (synthetic poses, mocked YOLO/OpenCV) |

No models, migrations, templates or shared services were changed.

---

## 1. Setup

### macOS

```bash
cd expopulse
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py seed_data
brew install ffmpeg            # only needed for simulated live CCTV
```

### Windows (PowerShell)

```powershell
cd expopulse
py -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate; python manage.py seed_data
winget install Gyan.FFmpeg     # then open a new terminal so ffmpeg is on PATH
```

`yolo11n-pose.pt` downloads automatically on the first run. Pass `--model path/to/yolo11n-pose.pt` to use a local copy.

### Test footage (not committed)

The tests here use the **UR Fall Detection Dataset** (Kwolek & Kepski), <http://fenix.ur.edu.pl/~mkepski/ds/uf.html>.

- **License:** CC BY-NC-SA 4.0, non-commercial academic use. Staged by actors.
- **Contents:** 30 falls and 40 daily-activity (ADL) clips, plus per-frame labels (`urfall-cam0-falls.csv`).
- **Format:** each `*-cam0.mp4` holds depth and RGB side by side. Keep only the RGB half (right 320 px).

macOS:

```bash
mkdir -p footage && cd footage
for n in fall-01 adl-01 adl-36; do curl -O http://fenix.ur.edu.pl/~mkepski/ds/data/$n-cam0.mp4; done
cd ..
python - <<'EOF'
import cv2
for name in ("fall-01", "adl-01", "adl-36"):
    cap = cv2.VideoCapture(f"footage/{name}-cam0.mp4")
    out = cv2.VideoWriter(f"footage/{name}-rgb.mp4", cv2.VideoWriter_fourcc(*"mp4v"), cap.get(cv2.CAP_PROP_FPS), (320, 240))
    while (ok := cap.read())[0]:
        out.write(ok[1][:, 320:])
    out.release()
EOF
```

Windows: download the same files with `curl.exe -O <url>` (or a browser) into `footage\`, then run the same Python snippet saved as a `.py` file.

`fall-01` is a walk followed by a fall. `adl-01` is a crouch. `adl-36` is someone sitting down and then lying on a bed on purpose.

---

## 2. Recorded video (MP4)

```bash
python manage.py detect_falls --video footage/fall-01-rgb.mp4 --location "Zone A" \
  --sample-every 3 --confirm-frames 5 --confidence 0.25 \
  --save-annotated footage/fall-01-annotated.mp4
```

Recorded video uses **video time** (`frame / FPS`), so runs are reproducible. The command exits at the end of the file. On Windows, put the command on one line or use a backtick (`` ` ``) at the end of each line instead of `\`.

---

## 3. Simulated live CCTV (FFmpeg → HLS → detector)

Run each step in its own terminal from the repository root. Activate the venv in the Django terminals.

**Terminal 1: dashboard**

```bash
python manage.py runserver          # http://127.0.0.1:8000/
```

**Terminal 2: FFmpeg turns the MP4 into a looping live stream**

macOS:

```bash
mkdir -p streams/hls
ffmpeg -re -stream_loop -1 -i footage/fall-01-rgb.mp4 \
  -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -f hls -hls_time 2 -hls_list_size 5 -hls_flags delete_segments+omit_endlist \
  streams/hls/live.m3u8
```

Windows:

```powershell
New-Item -ItemType Directory -Force streams\hls | Out-Null
ffmpeg -re -stream_loop -1 -i footage\fall-01-rgb.mp4 `
  -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p `
  -f hls -hls_time 2 -hls_list_size 5 -hls_flags delete_segments+omit_endlist `
  streams\hls\live.m3u8
```

**Terminal 3: serve the stream**

```bash
python3 -m http.server 8080 --directory streams/hls      # Windows: py -m http.server 8080 --directory streams\hls
```

Wait until <http://127.0.0.1:8080/live.m3u8> opens; Safari, VLC or `ffplay` can play it.

**Terminal 4: detector (runs until Ctrl+C)**

```bash
python manage.py detect_falls --video http://127.0.0.1:8080/live.m3u8 --location "Zone A" \
  --sample-every 3 --confirm-frames 5 --confidence 0.25 --retry-delay 5 --max-retries 0
```

### Expected output (real run, shortened)

```text
Loading YOLO11 pose model (yolo11n-pose.pt)...
CCTV Fall Detection started
Location: Zone A
Connecting to HLS stream...
Video source connected.
Time base: stream timestamps.
[t=0.02s] Person track 1 detected.
[t=0.02s] Track 1: upright posture.
[t=4.02s] Track 1: possible lying posture (1/5, rapid descent 0.9s).
...
[t=4.52s] Track 1: Possible Fall Detected — operator verification required.
Medical incident #8 created: CCTV Possible Fall - Zone A
Assigned team: Medical Team 1.
[t=8.22s] Track 1: person no longer visible; visual event cleared. Any open incident stays open for the operator.
[t=9.92s] Track 3: Possible Fall Detected — operator verification required.
Cooldown active; incident creation suppressed.
```

After restarting the detector while incident #8 is still open:

```text
Repeated event detected.
Existing unresolved fall incident #8.
Duplicate suppressed.
```

After stopping the HTTP server (Terminal 3) for 10 s and starting it again:

```text
Stream interrupted; tracking state reset.
Reconnecting. Retry 1 in 3 seconds.
Stream unavailable. Retry 2 in 3 seconds.
Video source connected.
```

Streaming `adl-36` (deliberately lying on a bed):

```text
[t=7.81s] Track 1: possible lying posture (1/5, slow descent 1.4s).
```

No alert follows, because the lie-down was slow and the person didn't keep lying for 60 s.

### Live acceptance results (performed, `--sample-every 3 --confirm-frames 5 --confidence 0.25`)

| Test | Stream | Result |
|---|---|---|
| Positive | looped `fall-01` | ✅ Fall confirmed 0.5 s after the first lying frame. **One** Medical incident, Medical Team 1 assigned, priority set automatically. The description includes "Rapid standing-to-lying transition observed (0.9 s)". |
| Duplicate | same stream, later loops and a detector restart | ✅ Every repeat suppressed: cooldown within a run, the open incident across restarts. |
| Recovery | person leaves the frame at the loop end | ✅ Visual event cleared. The incident stayed **Assigned** and the team **Busy** until the operator resolved it. |
| Reliability | HTTP server stopped for 10 s, then restarted | ✅ Tracking reset, reconnected after 2 retries, no incident from stale state. |
| Negative | looped `adl-01` (crouch) | ✅ No candidate, no incident. |
| Negative | looped `adl-36` (lying on a bed) | ✅ Slow descent (1.4 s), held, no incident. |

### How live streams are timed

HLS frames arrive in **bursts**. In a probe, OpenCV read about 8 s of backlog in 0.02 s, then waited 8 s for the next segment. Arrival time, whether wall clock or monotonic, therefore says nothing about how fast something happened in the scene. With the monotonic clock, a 4 s deliberate lie-down measured as a 0.6 s "rapid descent".

Live streams use `StreamClock` instead:

- It follows the stream's **presentation timestamps** (`CAP_PROP_POS_MSEC`) while they are present and moving forward.
- It falls back to `time.monotonic()` when a stream has no timestamps; the log shows `Time base: monotonic clock`.
- It re-anchors if timestamps jump backwards.
- It never runs backwards, and it continues across reconnects. An outage counts at least its real duration, so `--cooldown` stays meaningful.
- FPS metadata is not required for streams.

**On disconnect:** all per-person evidence (tracks, candidate counts, transition history) is **dropped**, because frames on either side of a gap may show different people. A fall that is still visible after reconnecting is confirmed again from fresh frames, and the open incident blocks a second row. `--max-retries 0` retries forever. Retry counts reset after every successfully read frame.

---

## 4. How a possible fall is decided

### Posture (per person, per processed frame)

Only confident body keypoints are used: shoulders to ankles, confidence ≥ `--keypoint-confidence` (default 0.4).

| Result | Condition |
|---|---|
| uncertain | fewer than 6 confident body keypoints, no confident shoulder/hip, or no keypoints |
| **lying** | principal keypoint axis ≥ `--lying-angle` (55°) from vertical, **and** keypoint width/height ≥ 1.2, **and** box width/height ≥ 0.8 |
| not lying | axis ≤ 35° and keypoint width/height < 1.0 |
| uncertain | anything in between |

The box shape is only a supporting veto and can never cause "lying" on its own.

### Temporal logic

- **Association:** greedy IoU (≥ 0.3) with the previous box. ByteTrack left lying people without IDs on this footage. Tracks unseen for `--track-expiry` seconds (default 3) are dropped, and IDs are never reused.
- **Confirmation:** `--confirm-frames` lying observations of the same person, counted in processed frames (every `--sample-every`-th frame).
  - Uncertain observations hold the count.
  - A not-lying observation resets it.
  - More than `--clear-frames` uncertain observations in a row drop the candidate.
- **Clearing:** `--clear-frames` not-lying observations (the person got up), or the person being absent for longer than `--track-expiry`. Short gaps don't clear.

### Transition evidence: "a lying person is not necessarily a fallen person"

When a candidate starts, the detector measures the **descent time**: seconds since a person at that spot was last at full standing height.

- A box at least 1.5× as tall as it is wide counts as standing.
- It is measured across track IDs, because the ID often changes during a fall.
- Only the last `lookback` (6 s) of detections nearby are used.

| Transition | Meaning | Effect |
|---|---|---|
| **rapid** (≤ `--rapid-descent`, 1.1 s) | fall-like | alert at normal confirmation |
| **unobserved** | nobody was seen standing there (person first seen already lying) | alert at normal confirmation |
| **slow** (> 1.1 s) | lay down via sitting or kneeling | alert only if lying continues for `--slow-lying-hold` (60 s) |

A transition is **not mandatory**. A person the camera only sees after they fell is still alerted. Someone who lay down on purpose but stays down for over a minute is also alerted, because they may still need help. `--slow-lying-hold 0` turns the hold off.

The evidence is added to the incident **description**; the title is unchanged.

Measured descent times (all 70 clips, 30 fps, `--sample-every 3`):

| Group | Descent time |
|---|---|
| Detected falls | 0.2–0.9 s |
| Deliberate lie-downs (bed, sofa, floor) | 1.3–4.8 s |

---

## 5. Incident lifecycle

- **Title:** `CCTV Possible Fall - <Location>`, the format the dashboard already shows. This stable title identifies fall incidents.
- **Same-fall suppression:** before creating an incident, the detector looks for an **unresolved incident with that title, type Medical, source "CCTV Monitoring", at the same Location**. If one exists, it logs "Duplicate suppressed". The check is in the database, so it survives restarts.
- **Unrelated incidents:** other Medical incidents at that Location, whether staff reports or other CCTV detectors, are **not** treated as the same fall. The fall incident is still created. The shared duplicate service may still link it as a *possible duplicate*; that warning is preserved, and team auto-assignment is then skipped as before.
- **Cooldown:** `--cooldown` (default 120 s) is the minimum time between incidents created by one run. It uses video time for files and the stream clock for HLS, is held in memory, and resets on restart.
- **Creation and assignment:**
  - Incidents are created with `create_incident()`, so priority is automatic.
  - Severity is `HIGH` as a prototype default, not medical triage.
  - `assign_team_to_incident()` assigns an available **Medical** team. Other team types are never touched. If no Medical team is free, the incident stays `New`.
- **Resolution:** visual clearing (the person stands up or leaves) **never** resolves the incident or releases the team. Only the operator workflow (`New → Assigned → In Progress → Resolved`) does that. After resolution, a new confirmed fall can create a new incident, subject to the cooldown.
- **Errors:** database and validation errors are logged, and the alert is retried on the next processed frame.

**Accepted MVP limitation:** suppression is per Location. Two different people falling at one Location while the first incident is open share that incident, and people cannot be told apart across detector restarts. The pre-insert check is not concurrency-safe across several detector processes.

---

## 6. Offline evaluation on the full UR Fall dataset

**Method:**

- yolo11n-pose was run once on the RGB half of all 70 clips.
- The cached poses were replayed through the same `fall_detection` code the command uses, with video time.
- Ground-truth fall onset came from `urfall-cam0-falls.csv`.
- ADL activities were labelled by inspecting each clip.

**Settings:** `--sample-every 3 --confirm-frames 5`, default thresholds.

| Footage | Clips | Alerts | Notes |
|---|---|---|---|
| Walk → fall → lying | 30 | **15 detected** | latency from fall onset: median 1.27 s (1.00–1.97 s) |
| … with ≥ 1 s of lying before the clip ends | 14 | 10 | |
| … clip ends < 1 s after landing | 16 | 5 | too short to count as *sustained* lying |
| Walking + crouching | 9 | 0 | |
| Bending to pick something up | 6 | 0 | |
| Sitting on a chair or sofa | 8 | 0 | |
| Sit → lie on bed or sofa (deliberate) | 8 | 0 | 3 alerted before the transition check was added |
| Go down to the floor, lie or crawl, some stand up again (deliberate) | 9 | 0 | 6 alerted before the transition check was added |

Other settings (falls detected / ADL false alerts):

| Setting | Falls | ADL false alerts |
|---|---|---|
| `--sample-every 5 --confirm-frames 5` (CLI defaults) | 10/30 | 0/40 |
| `--sample-every 5 --confirm-frames 3` | 16/30 | 0/40 |
| `--sample-every 3 --confirm-frames 5 --slow-lying-hold 0` | 15/30 | 9/40 |

**Missed falls:**

- 10 of the 15 misses end less than 0.75 s after the person lands.
- The others: a body lying straight toward the camera (foreshortened, so it looks upright), a body cut off at the frame edge, or a person not detected at 320×240.
- Standing up after lying: in `adl-35` the person gets up, and the visual event clears (seen with the hold disabled).
- Temporary occlusion and missing keypoints: these hold the evidence without counting it (see tests and the "uncertain" log lines).

**Caveats:**

- The transition threshold (1.1 s) was chosen on these same clips.
- There is only one dataset, with 2–3 rooms, one camera height, and staged actors.
- These are **demonstration results, not accuracy figures**. Don't quote them as sensitivity or specificity.

---

## 7. Options

| Flag | Default | Meaning |
|---|---|---|
| `--video` | required | local video file, or HTTP(S) HLS playlist URL |
| `--location` | required | exact Location name |
| `--confirm-frames` | 5 | lying observations to confirm |
| `--clear-frames` | 10 | not-lying observations to clear |
| `--sample-every` | 5 | process every Nth frame; 3 is recommended for 30 fps demos |
| `--confidence` | 0.35 | person detection confidence; 0.25 works better on 320×240 footage |
| `--cooldown` | 120 | seconds between incidents created by one run |
| `--track-expiry` | 3 | seconds before an unseen person's track is dropped |
| `--keypoint-confidence` | 0.4 | minimum keypoint confidence |
| `--lying-angle` | 55 | minimum body-axis angle for lying |
| `--rapid-descent` | 1.1 | max standing-to-lying seconds that count as rapid |
| `--slow-lying-hold` | 60 | seconds a slow lie-down must continue before an alert (0 = off) |
| `--model` | `yolo11n-pose.pt` | any Ultralytics *pose* model |
| `--save-annotated` | — | `.mp4`/`.avi` writes annotated video; an image path saves the first confirmed frame |
| `--retry-delay` | 5 | seconds between HLS reconnect attempts |
| `--max-retries` | 0 | consecutive HLS reconnect failures before giving up (0 = never) |

## 8. Tests

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # No changes detected
python manage.py test incidents                     # 127 tests OK (66 existing + 61 fall detection)
```

The tests cover:

- **Video input:** local MP4, HLS connection, stream timestamps vs. monotonic fallback, disconnection/reconnection, unavailable stream, tracking reset after interruption, cleanup after Ctrl+C.
- **Detection:** fall confirmation, normal activity, missing keypoints, transition evidence (rapid / slow / unobserved / hold).
- **Incidents:** same-fall suppression (including restart), unrelated Medical incidents, operator-controlled resolution, Medical-only team assignment.

No weights are downloaded and no video is read.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `Location 'Zone A' not found` | Run `python manage.py seed_data`. |
| `Stream unavailable. Retry …` forever | Check that FFmpeg and `http.server` are running and that <http://127.0.0.1:8080/live.m3u8> opens. Start the detector a few seconds after FFmpeg. |
| `ffmpeg: command not found` | macOS: `brew install ffmpeg`. Windows: `winget install Gyan.FFmpeg`, then open a new terminal. |
| `Duplicate suppressed` on the first fall | An unresolved `CCTV Possible Fall - <Location>` incident already exists. Resolve it in the dashboard or use another Location. |
| Incident created but no team assigned | No Medical team is Available, or the incident was linked as a possible duplicate of another recent Medical incident (seed data has one in **Zone C**, so demo in **Zone A**). |
| No detection on your own clip | Use a side or front view at roughly chest height, with the whole body visible and lying for at least 1–2 s. Try `--sample-every 3 --confidence 0.25`, or `--model yolo11m-pose.pt`. |
| `Time base: monotonic clock` | The stream has no timestamps. Detection still works, but descent timing is less reliable because of bursty delivery. |
| Port 8080 already in use | Stop the old server, or use another port in both the server and `--video` URL. |

## 10. Limitations

- Validated only on staged indoor clips at 320×240 from one dataset. This does **not** prove reliability for other CCTV angles, overhead cameras, crowds, low light, or occlusion.
- **Likely false negatives:**
  - a body lying straight toward or away from the camera;
  - a body partly outside the frame;
  - very short recordings;
  - a slow collapse (sliding down a wall, kneeling first), which is held for 60 s like a deliberate lie-down.
- **Likely false positives:**
  - a fast deliberate drop to the floor (exercise, play);
  - furniture or objects misdetected as a lying person;
  - a strongly tilted camera.
- Image geometry cannot prove ground contact.
- **Descent timing:**
  - Another standing person near the fall spot can make a slow lie-down look rapid, which leads to a normal alert.
  - In crowds, overlapping people can swap IoU tracks.
- Location-level suppression and the non-atomic duplicate check are described in section 5.
- The dataset license is non-commercial.
