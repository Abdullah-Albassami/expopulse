# CCTV Possible-Fall Detection — Usage

`detect_falls` watches a recorded MP4 and raises a **"CCTV Possible Fall"** Medical incident when one person holds a lying posture for several processed frames. It is a prototype hint for operators: **operator verification required**. It does not diagnose a fall or a medical emergency, and it has no measured accuracy.

## Pipeline

`MP4 → yolo11n-pose (pretrained) → IoU person tracks → posture rule → candidate/confirmed/cleared per track → create_incident() → Medical team → dashboard`

Code: `incidents/cctv/fall_detection.py` (logic), `incidents/management/commands/detect_falls.py` (CLI), `incidents/tests_fall_detection.py` (offline tests).

## Posture rule

For each person, take the confident body keypoints (shoulders → ankles, confidence ≥ `--keypoint-confidence`, default 0.4):

| Result | Condition |
|---|---|
| **uncertain** | fewer than 6 confident body keypoints, or no confident shoulder/hip, or no keypoints at all |
| **lying** | principal keypoint axis ≥ `--lying-angle` (default 55°) from vertical **and** keypoint width/height ≥ 1.2 **and** box width/height ≥ 0.8 |
| **not lying** | axis ≤ 35° and keypoint width/height < 1.0 |
| **uncertain** | anything in between (oblique) |

The bounding-box aspect is a supporting cue only. It can veto "lying" but cannot cause it.

Feasibility data (yolo11n-pose, staged footage below):

| Clip | Body axis | Keypoint W/H |
|---|---|---|
| Lying after fall | 72–88° | 1.7–4.8 |
| Sitting/crouching (ADL) | ≤ 25° | ≤ 0.78 |

The simpler shoulder→hip angle was too noisy on lying people (1°–85°), so it is not used.

## Temporal logic and person association

- **Tracks:** detections are joined to the previous box with the highest IoU (≥ 0.3); otherwise a new track ID starts. The Ultralytics ByteTrack tracker was not used because it left low-confidence lying people without an ID in the test footage. Tracks unseen for `--track-expiry` video seconds (default 3) are dropped, and their IDs are never reused.
- **Candidate → confirmed:** `--confirm-frames` *lying* observations of the same track. These are processed frames (every `--sample-every`th frame), not raw frames. Uncertain observations hold the count. A not-lying observation resets it. More than `--clear-frames` uncertain observations in a row also drop the candidate.
- **Confirmed → cleared:** `--clear-frames` not-lying observations of that track, or the track being absent for longer than `--track-expiry`. A brief disappearance does not clear.
- **Time** is video time (`frame_index / FPS`), never wall-clock, so recorded runs are reproducible. A file without FPS metadata is rejected.
- **ID-switch risk:** if two people overlap, IoU association can swap their IDs. Standing up usually changes the box enough to start a new track, so the old lying track then clears by absence.

## Incident lifecycle

- One confirmation produces one alert attempt. Before creating anything, the detector looks for an **unresolved Medical incident from "CCTV Monitoring" at the same Location**. If one exists, creation is suppressed and its ID is logged. This check is in the database, so it still works after the command restarts.
- `--cooldown` is the minimum number of **video seconds** between incidents created by one run. It is held in memory and resets on restart; the database check covers restarts.
- The incident is created through `create_incident()`, so priority is calculated automatically. Severity is `HIGH` as a prototype default, not medical triage.
- If the shared duplicate service links the incident to another recent Medical incident (for example a staff report), no team is assigned. Otherwise `assign_team_to_incident()` assigns an available Medical team. If none is available, the incident stays `New`.
- Visual clearing **never** resolves the incident or releases the team; only the normal operator workflow does that. After resolution, a new confirmed episode can create a new incident.
- Suppression is per Location, so two different people falling at one location share a single incident. This is acceptable for the MVP but is not a production multi-person policy. The pre-insert check is not concurrency-safe across multiple workers.
- Database or validation errors are logged, and the alert is retried on the next processed frame instead of being dropped.

## Footage used (not committed)

**UR Fall Detection Dataset** (Kwolek & Kepski, University of Rzeszów), <http://fenix.ur.edu.pl/~mkepski/ds/uf.html>.

- **License:** CC BY-NC-SA 4.0, non-commercial academic use. Staged by consenting actors.
- **Camera:** front/side view at roughly chest height in an office room, 30 fps.
- **Format:** the `*-cam0.mp4` files place depth and RGB side by side (640×240). Only the RGB half (right 320 px) is used.

| Clip | Content | Result (n-pose, `--sample-every 3 --confirm-frames 5 --confidence 0.25`) |
|---|---|---|
| `fall-01` | walk → fall → lie on floor | ✅ confirmed at t=4.67 s, 1 incident |
| `fall-05` | fall, then partly sits up; clip ends ~1 s later | ❌ not confirmed (false negative; same with `yolo11m-pose`) |
| `adl-01` | walk → crouch/sit on floor | ✅ no incident |
| `adl-12` | two people walking / bending | ✅ no incident |

These are demonstration checks on staged clips, **not** measured real-world accuracy.

## Reproduce

```bash
source venv/bin/activate
python manage.py migrate && python manage.py seed_data
mkdir -p footage && cd footage
curl -O http://fenix.ur.edu.pl/~mkepski/ds/data/fall-01-cam0.mp4
curl -O http://fenix.ur.edu.pl/~mkepski/ds/data/adl-01-cam0.mp4
cd ..
# keep the RGB half only
python - <<'EOF'
import cv2
for name in ("fall-01", "adl-01"):
    cap = cv2.VideoCapture(f"footage/{name}-cam0.mp4")
    out = cv2.VideoWriter(f"footage/{name}-rgb.mp4", cv2.VideoWriter_fourcc(*"mp4v"), cap.get(cv2.CAP_PROP_FPS), (320, 240))
    while (ok := cap.read())[0]:
        out.write(ok[1][:, 320:])
    out.release()
EOF

python manage.py detect_falls --video footage/fall-01-rgb.mp4 --location "Zone A" \
  --sample-every 3 --confirm-frames 5 --confidence 0.25 \
  --save-annotated footage/fall-01-confirmed.jpg
```

Sample log (Zone A, no open Medical incident, Medical Team 1 available):

```
[t=4.07s] track 1: candidate lying posture (1/5).
...
[t=4.67s] track 1: Possible Fall confirmed — operator verification required.
Incident #8 created: CCTV Possible Fall - Zone A
Assigned team: Medical Team 1
End of video reached; detector exiting.
```

Running the same command again prints `Suppressed: unresolved CCTV Medical incident #8 already open at this location.` In seed data, Zone C already has an open "Medical Emergency", so a Zone C incident is linked as a possible duplicate and no team is assigned.

The short URFD clips need `--sample-every 3`. The task's default example (`--sample-every 5 --confirm-frames 5`) needs about 0.8 s of lying at 30 fps, plus detection gaps, which these clips barely provide.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--video` | required | local video file (HTTP/HLS not supported) |
| `--location` | required | exact Location name |
| `--confirm-frames` | 5 | lying observations to confirm |
| `--clear-frames` | 10 | not-lying observations to clear |
| `--sample-every` | 5 | process every Nth frame |
| `--confidence` | 0.35 | person detection confidence |
| `--cooldown` | 120 | video seconds between incidents created by one run |
| `--track-expiry` | 3 | video seconds before an unseen track is dropped |
| `--keypoint-confidence` | 0.4 | minimum keypoint confidence |
| `--lying-angle` | 55 | minimum body-axis angle for lying |
| `--model` | `yolo11n-pose.pt` | any Ultralytics *pose* model |
| `--save-annotated` | — | `.mp4`/`.avi` writes annotated video; an image path saves the first confirmed frame |

## Tests

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # No changes detected
python manage.py test incidents                     # 100 tests OK (66 existing + 34 fall detection)
```

The tests use synthetic skeletons and a mocked YOLO/VideoCapture. They make no weight downloads and read no video.

## Limitations and likely errors

- Validated only on a few staged clips from one indoor camera angle at 320×240. Staged demos **do not prove** reliability across CCTV angles, crowds, low light or occlusion.
- **False negatives:** a person lying along the camera axis (foreshortened), a body cut off at the frame edge, very short lying episodes (`fall-05`), heavy occlusion, low resolution, overhead cameras.
- **False positives:** someone deliberately lying or stretching on the floor, people bending over flat-backed with legs hidden, strong lens distortion or a tilted camera, and furniture misdetected as a person (seen once as an upright chair, which was correctly not lying).
- Image geometry cannot prove ground contact; perspective can make people look low or horizontal.
- `yolo11m-pose` gave cleaner keypoints on lying people than `yolo11n-pose`, but did not change the clip results above.
