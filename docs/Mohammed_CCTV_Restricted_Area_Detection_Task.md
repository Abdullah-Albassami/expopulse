# Mohammed — CCTV Restricted-Area Intrusion Detection

**Project:** ExpoPulse — Expo 2030 Challenge 3.6, Operations Center MVP  
**Assigned to:** Mohammed  
**Repository:** `https://github.com/Abdullah-Albassami/expopulse` (private)  
**Base and PR target:** `experiment/cctv-crowding` — **never `main`**  
**Your feature branch:** `feature/cctv-restricted-area-detection`  
**Deliverable:** A reproducible, independently tested CCTV **restricted-zone presence detector** using pretrained YOLO person detection, configurable polygon coordinates, time-based confirmation, and automatic **Security** incident creation through existing ExpoPulse services.

> **Instructions for you and your AI coding agent:** Treat this document as the implementation contract. Read the actual repository before coding. Build and run the solution in a separate checkout/feature branch. Do not change the shared experimental branch, `main`, other teammates' detectors, or shared incident services without the team leader's approval. Show the team leader a brief change plan before modifying shared interfaces.

## 1. Objective and realistic scope

Demonstrate the following end-to-end workflow:

**CCTV MP4 or simulated-live HLS → pretrained YOLO11 person detection/tracking → point-in-polygon restricted-zone check → sustained-presence confirmation → active-incident suppression → existing ExpoPulse `create_incident()` → Security team assignment → live dashboard.**

Example: A fixed CCTV camera watches a backstage service corridor. A configured polygon covers the staff-only portion of the view. If a person enters and remains within that polygon for the confirmation period, ExpoPulse creates one Security incident titled **`CCTV Restricted Zone Alert - Zone A`**. Repeated frames and intermittent tracking failures must not flood the database with alerts. An operator can verify the event and use the existing dashboard workflow.

**Precise terminology:** The camera proves only *a person was detected inside a visually configured restricted zone*. It cannot establish whether that person is authorized. Do **not** label someone a criminal, identify them, use face recognition, or claim that authorization has been checked. No new access-control API is required for this MVP. The generated incident must explicitly say **operator verification required**.

**Scope:** one camera/source and **one named polygonal restricted zone per detector process** is sufficient for MVP. Multiple zones, access credentials, multi-camera correlation, face recognition, persistent video storage, and automatic enforcement are out of scope.

## 2. Inspect the codebase before editing

Review these actual files on `experiment/cctv-crowding`:

- `incidents/models.py` — `Incident`, `IncidentSource`, `Location`, `Team`; available enums.
- `incidents/services/incident_service.py` — `create_incident(title, description, incident_type, source, location, severity, people_affected=0)`.
- `incidents/services/assignment.py` — `assign_team_to_incident(incident)`; `security` already maps to a Security team.
- `incidents/services/duplicates.py` — **a possible duplicate is marked, but its incident row is still created**.
- `incidents/management/commands/detect_crowding.py` — reference only for OpenCV, model loading, CLI, MP4/HLS and cleanup; **do not rewrite it**.
- `incidents/management/commands/seed_data.py`, `incidents/tests.py`, `requirements.txt`, `README.md`.

Verified at task creation: ExpoPulse has `Incident.IncidentType.SECURITY`, `Incident.Severity`, `Incident.Status`, `IncidentSource.SourceType.SENSOR`, `CCTV Monitoring`, and Security teams in seed data. The experiment uses YOLO11 (`yolo11n.pt`), OpenCV, Django 6.1.2, and Ultralytics. **Re-check your own branch rather than assuming it stayed unchanged.**

### Git and local setup

If you have not cloned the repo:

```bash
git clone -b experiment/cctv-crowding https://github.com/Abdullah-Albassami/expopulse.git expopulse-intrusion-lab
cd expopulse-intrusion-lab
git switch -c feature/cctv-restricted-area-detection
```

If already cloned, first inspect `git status`, `git branch --show-current`, and `git fetch origin`. Never discard uncommitted work. Create the feature branch from an up-to-date `origin/experiment/cctv-crowding` only when safe, and do not overwrite an existing branch.

macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

Windows PowerShell:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

Run `seed_data` on a **new local database** for the repeatable demo; inspect existing data first if reusing a database.

## 3. Mandatory feasibility gate — do this before Django integration

**Do not build the full detector until the detection geometry works on actual footage.**

1. Obtain **authorized, staged, or appropriately licensed** fixed-camera footage in which a visible person **enters, remains in, and exits** a predefined zone. Ideally record a short controlled demo. Obtain a negative example where a person walks *outside* the polygon. No real restricted-zone access or trespassing is required. Keep video outside Git.
2. Run a **pretrained** Ultralytics YOLO11 model (`yolo11n.pt`) on sample frames, filtering to COCO `person` class (`classes=[0]`). Test whether people are visible and detected; verify original frame dimensions. If small/distant people are missed, inspect annotated detections and adjust image size/confidence or compare `yolo11s.pt` only if necessary.
3. Draw or overlay the proposed restricted-zone polygon on an actual frame. Verify it sits in the intended location and that inside/outside test points produce the expected result.
4. Test a single person entering and exiting. Check whether person **tracking IDs** are stable. Ultralytics `model.track(frame, persist=True, classes=[0], ...)` may expose track IDs; do not assume IDs are always available. Respect the installed Ultralytics API.
5. Save **at least one annotated positive frame and one annotated negative frame**, or a short annotated demonstration video, outside the Git repository; document video source/license and the observed behavior.
6. If detection or tracking cannot be made reliable on the chosen footage, choose another *authorized* clip and report the blocker before integrating. No custom neural-network training is required or expected.

**Acceptance gate:** Show person boxes, the restricted polygon, an inside/outside decision, and at least one working entrance sequence. This is a practical demonstration, **not a validated security-grade accuracy claim**.

## 4. Polygon configuration and geometry contract

Implement a deterministic, independently testable geometry helper. Requirements:

- Use one closed **polygon with at least 3 distinct vertices**, with a nonzero area, expressed in **normalized coordinates** (`x` and `y` between 0 and 1 inclusive) so its placement adapts to the video's pixel dimensions. Convert to pixels using the real decoded frame width/height. Reject malformed, out-of-range, degenerate, and self-intersecting polygons rather than silently accepting them.
- Define polygon vertices in correct perimeter order, without needing to repeat the first vertex.
- Support a reproducible external **JSON config file**, e.g. `--zone-config configs/restricted_zone.example.json`, including `zone_id`, display name, and polygon points. Ship a safe example config without real surveillance locations. Do not introduce models or migrations for zone configuration.
- `zone_id` must be a short validated stable identifier (letters/numbers/hyphens/underscores; max 64 characters) that can be included in incident titles and is distinct from `Location.name`.
- Use the **bottom center of the person's bounding box** as the documented approximate ground-contact point, not the box center, because a person's body may overlap a restricted polygon while their feet are outside it. This is an approximate camera-plane convention, not true geospatial localization. Explain limitations for occlusion, framing, perspective, and truncated detections.
- Define whether **polygon boundary points count as inside** (recommend yes), and test the exact boundary behavior. Use `cv2.pointPolygonTest` or an equivalent deterministic method; document the choice.
- Do not require an interactive zone-drawing GUI for MVP. A saved annotated frame with the polygon and a documented JSON example is sufficient.

Example illustrative config (values **must be adapted to the actual footage**):

```json
{
  "zone_id": "STAFF_ONLY_A",
  "name": "Staff-Only Corridor",
  "polygon": [[0.52, 0.28], [0.94, 0.28], [0.98, 0.96], [0.48, 0.96]]
}
```

These points are examples only; never assume they align with an arbitrary video.

## 5. Detection and event-state lifecycle

### Person detection and tracking

- Use the installed YOLO11 model to detect **people only**; no identification, facial recognition, age/gender classification, or re-identification across cameras.
- Prefer Ultralytics tracking (`model.track(..., persist=True, ...)`) and associate qualifying observations **per track ID**. When IDs are missing or unstable, do not mix observations from unrelated people; either apply a conservative explicitly documented single-person fallback or skip confirmation for untracked observations with clear logs.
- For frame sampling, document implications for tracking IDs; persistent tracking with widely skipped frames may be less stable. Expose `--sample-every`, default 1 if using persistent tracking, and validate behavior against actual footage. Reset tracking state when opening an unrelated video/stream, not blindly across reconnects.

### State machine

Implement a small testable state machine, with named states or equivalent behavior:

`outside → candidate_inside → confirmed → clearing → outside`

- **Candidate:** A single tracked person has a qualifying bottom-center point in the configured polygon.
- **Confirmation:** That *same tracked person* remains inside across at least `--confirm-frames` processed observations. Do not combine separate people to pass the threshold. Default: 5; tune only after reviewing footage. Also describe the approximate duration at the processed frame rate.
- **Event:** On first confirmation, request an incident **at most once per active zone event**. A second person entering while the same zone incident is active must not create another incident. Log active track count if useful, but don't multiply incident records.
- **Clear:** A previously confirmed zone event clears only after **`--clear-frames` consecutive observations with no qualifying person in the zone** (default: 10). Temporary occlusion, missed detection, or ID changes must not immediately clear an active event.
- **Cooldown:** Support optional nonnegative `--cooldown` (default: 60 seconds) to avoid repeated alerts from short transitions. Use monotonic time for in-process timers. **Cooldown is not the database suppression mechanism.**
- **Source outage:** For HLS disconnection, do **not** interpret missing video as an empty zone; preserve the current alert/event state across short reconnects. Handle extended outages conservatively and document behavior.
- **Local MP4:** exit at end of file, cleanly release resources; do not reconnect indefinitely.

Do not confuse a frame's *person count* with the event's *confirmed intrusion state*. Do not fire an incident on the first detection alone.

### Database-level suppression — required

Before calling `create_incident()`, check for an **existing unresolved incident** with the same:

- `Incident.IncidentType.SECURITY`
- `source` = `CCTV Monitoring`
- `location` = configured `Location`
- exact stable title (for example `CCTV Restricted Zone [STAFF_ONLY_A] - Zone A`)

Include the validated `zone_id` to distinguish zones in the **same location**. Match on exact fields/title, not a substring or fuzzy duplicate. If such an unresolved incident exists, report `already_active` and **do not insert another row**. This persists across command restarts and looped footage. `possible_duplicate_of` alone does *not* suppress records. After resolution and a genuinely new confirmed zone-presence episode, a new incident may be created, subject to cooldown. Do **not** automatically mark an incident Resolved when the person exits; operator controls the resolution workflow.

The existing shared duplicate logic searches recent incidents of the same type/location, regardless of this detector's stable zone key. Therefore a distinct Security incident may still be flagged as a possible duplicate. **Do not alter the shared duplicate service**; document this behavior and suppress automatic team assignment for an incident flagged as a duplicate, consistent with existing code. Avoid promises of atomic concurrency safety without database uniqueness; this prototype supports one detector process per zone. Report the limitations of simultaneous processes on the same zone.

## 6. Django incident creation and team assignment

Reuse the existing services; **do not** use `Incident.objects.create()` or override priority scores.

Illustrative integration (adapt to inspected code):

```python
from incidents.models import Incident, IncidentSource
from incidents.services.incident_service import create_incident
from incidents.services.assignment import assign_team_to_incident

source, _ = IncidentSource.objects.get_or_create(
    name="CCTV Monitoring",
    defaults={"source_type": IncidentSource.SourceType.SENSOR},
)

# First check whether a matching unresolved incident already exists.
incident = create_incident(
    title=f"CCTV Restricted Zone [{zone_id}] - {location.name}",
    description=(
        f"Possible person presence detected in restricted zone '{zone_name}' "
        f"at {location.name}. Authorization is unknown; operator verification required."
    ),
    incident_type=Incident.IncidentType.SECURITY,
    source=source,
    location=location,
    severity=Incident.Severity.HIGH,
    people_affected=1,
)

if not incident.possible_duplicate_of_id:
    assign_team_to_incident(incident)
```

Severity `HIGH` is a configurable *demonstration default*, **not** an assertion that a confirmed emergency exists. Don't assert `people_affected` is the number of unauthorized people; it is a detected-person estimate. Reuse actual `Location` objects created in seed data (e.g. `Zone A`, `Main Entrance`). If no Security team is available, leave incident status `New`. Never manipulate `Team.status` directly or automatically escalate to authorities. Dashboard should already display new incidents via existing polling; **no dashboard/UI edits needed**.

## 7. Implementation ownership and file boundaries

Recommended deliverables (you may adapt naming minimally to actual branch conventions):

- `incidents/management/commands/detect_restricted_area.py` — Django CLI; argument validation, OpenCV reader, tracking, output, errors, cleanup.
- `incidents/cctv/restricted_area.py` — reusable polygon geometry, configuration validation, per-track event state machine, detector-side incident suppression helpers. If `incidents/cctv/` already exists (e.g. from Ammar), **reuse rather than overwrite** it. Keep this implementation isolated from fall detection.
- `incidents/tests_restricted_area.py` — focused unit and Django integration tests.
- `configs/restricted_zone.example.json` — safe sample config.
- `docs/RESTRICTED_AREA_DETECTION_USAGE.md` — concise operating/demo guide, evidence, caveats.

**Do not edit without team-leader approval:** `incidents/models.py`, migrations, core `incident_service.py`, `priority.py`, `duplicates.py`, `assignment.py`, `workflow.py`, dashboard templates/JS, other teammates' files, and `detect_crowding.py`. No new REST API, database table, frontend, or external service is required. Add dependencies only if truly needed and document the reason. Keep `.pt`, `.mp4`, `.m3u8`, segments, generated logs, output videos, `.env`, SQLite DB, and `venv/` out of Git.

## 8. Required CLI behavior

Recommended interface:

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

Required: `--video` local MP4; optional HTTP(S) HLS/M3U8 encouraged because ExpoPulse already has simulated live CCTV. `--location` exact existing Location name; `--zone-config` required JSON path. `--confirm-frames`, `--clear-frames`, `--sample-every` positive integers; `--confidence` within `(0,1]`; `--cooldown` nonnegative. Optional `--model` default `yolo11n.pt`, `--show` (only if GUI exists), and `--save-annotated` for evidence. `--retry-delay` and `--max-retries` are optional if HLS supported; clearly document reconnection behavior.

Helpful console logs should include: video opened; zone ID and polygon loaded; frame/track observations; candidate/confirmed/cleared events; `incident #N created` or `already_active`; team assignment or unavailability; video errors/retries. Avoid printing unbounded every-frame logs by default (optional verbose mode). Do not report an incident as created until Django successfully saves it.

All invalid arguments/configs/videos/locations must yield a helpful `CommandError`, not an opaque traceback. Handle `Ctrl+C` and clean up `VideoCapture`, writers, and OpenCV display windows if opened. If stream support is implemented, ensure the event is not spuriously cleared on reconnection.

## 9. Tests — mandatory, no model download for automated tests

Write pure deterministic geometry/state-machine tests and Django `TestCase` integration tests. Mock YOLO/OpenCV for command-level tests. The test suite must not depend on network downloads, physical cameras, or real footage.

Minimum coverage:

1. Correct normalized-polygon conversion at different resolutions; inside, outside, and on-edge points.
2. Reject invalid JSON, polygon with fewer than 3 distinct points, zero-area/self-intersecting polygons, out-of-range coordinates, invalid IDs.
3. Bottom-center feet approximation changes classification appropriately compared with bounding-box center.
4. No incident for a person strictly outside the polygon.
5. Brief entry below confirmation threshold produces no incident.
6. Sustained entry by **one tracked person** confirms once.
7. Separate track IDs cannot be merged to satisfy the same person's confirmation threshold.
8. Second person entering while zone event is active produces no additional event or incident.
9. Temporary missed detections and track-ID changes do not immediately clear/retrigger the zone event.
10. Clearing occurs only after required consecutive empty-zone observations.
11. Cooldown prevents immediate retrigger after a clear/re-entry.
12. Same unresolved matching Security incident prevents any second row, including after simulated detector restart.
13. An unrelated `Security` incident at the same location should **not** be mistaken for the same zone's active incident; a distinct zone ID must be handled independently (document effects of shared possible-duplicate linking).
14. After operator resolves old incident, a fresh confirmed episode can create a new incident.
15. Created incident uses `CCTV Monitoring`, type `SECURITY`, appropriate location/description, and the **existing** priority service.
16. Security team assigned when available and not flagged duplicate; otherwise incident stays `New`; never directly mutate team state.
17. Missing/invalid CLI options, missing location, unreadable MP4, malformed config produce clear errors and no incidents.
18. MP4 EOF, `KeyboardInterrupt`, and capture release are handled; if HLS added, reconnection must not spawn false repeat events.

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

The experimental branch previously passed **15 existing incident tests**; preserve these, add yours, and report **actual** test counts. No migrations should be generated. If tests fail, report specific failures rather than falsely stating success.

## 10. Manual demo and evidence

1. Set up fresh local Django data (`migrate`, `seed_data`) and ensure a Security team is available.
2. Use a clearly documented fixed-camera demo clip showing **outside → entry → sustained presence → exit**, ideally a consenting teammate. Save the local video in ignored `footage/`. Identify license/source if not self-recorded.
3. Configure the polygon for that exact footage and capture an annotated frame. **Do not use example coordinates unverified.**
4. Run Django (`python manage.py runserver`) in one terminal and the detector command in another.
5. Show the ExpoPulse dashboard automatically gaining exactly **one** Security incident after confirmed presence; confirm source/location, priority, title, and assignment or `New` fallback.
6. Replay/continue while the incident is **unresolved**, including restarting the detector: verify **no additional row** for the same zone incident.
7. Show a **negative case**: someone outside the polygon must not generate an incident. Show an entry too brief to pass confirmation.
8. Resolve the incident through the normal operator workflow. Demonstrate that a fresh subsequent confirmed episode can create a new incident.
9. Optional live HLS demonstration: FFmpeg loops a prerecorded video into `.m3u8`; local HTTP server serves it; the detector reads its URL. Only claim HLS support if tested.
10. Supply PR evidence: annotated positive/negative samples, concise console output, actual test results, and known limitations. Do not commit footage, portraits, secrets, weights, or generated segments.

**Note:** A staged example does not prove general detection accuracy or ability to determine authorization. This is an operator-assistance prototype.

## 11. Acceptance checklist

- [ ] Feasibility gate passed on actual authorized footage with annotated evidence.
- [ ] Reusable normalized polygon parser and deterministic point-in-polygon geometry.
- [ ] Person-only YOLO11 detection with defensible tracking/sampling handling.
- [ ] Same-person confirmation and stable zone-level event lifecycle.
- [ ] One Security incident per zone while matching incident remains unresolved, including after restart.
- [ ] Exact matching keys protect against accidentally suppressing unrelated Security incidents.
- [ ] Existing incident creation/priority/duplicate and assignment services reused without modification.
- [ ] Unavailable Security team leaves `New`; only operator resolves incidents.
- [ ] MP4 command runs, handles invalid inputs and EOF, releases resources.
- [ ] Automated unit + Django integration tests pass alongside existing tests.
- [ ] `python manage.py check` clean; `makemigrations --check --dry-run` shows no changes.
- [ ] Concise usage guide includes actual runnable commands, annotated proof, source/license, known failure modes.
- [ ] No videos, weights, database, generated streams, or secrets committed.
- [ ] PR targets `experiment/cctv-crowding`, not `main`, and is reviewed by team leader before merging.

## 12. Git commit and handoff

Inspect before staging:

```bash
git status
git branch --show-current
git diff --stat
```

Adjust listed paths to actual created files (don't stage nonexistent paths):

```bash
git add incidents/management/commands/detect_restricted_area.py incidents/cctv/restricted_area.py incidents/tests_restricted_area.py configs/restricted_zone.example.json docs/RESTRICTED_AREA_DETECTION_USAGE.md
git diff --cached --check
git diff --cached --stat
git commit -m "Add CCTV restricted-area monitoring prototype"
git push -u origin feature/cctv-restricted-area-detection
```

If a new `incidents/cctv/__init__.py` was created, stage it too. Stage `requirements.txt` only if a necessary, documented dependency was added. The existing task guide may already be in the branch; do not duplicate it. **Do not push without team-leader approval of changed shared files.**

Open a pull request **from** `feature/cctv-restricted-area-detection` **into** `experiment/cctv-crowding`. Include: summary; files changed; config/video instructions; exact commands; annotated inside/outside frames; sample incident result; automated test counts; known false-positive/false-negative limitations; any proposed shared-code changes. **Do not merge your own PR; do not push to `main`.**

## 13. Official technical references

- Ultralytics YOLO multi-object tracking: https://docs.ultralytics.com/modes/track/
- Ultralytics region counting / polygon-zone concept: https://docs.ultralytics.com/guides/region-counting/
- OpenCV pointPolygonTest API: https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html

These references demonstrate available tools, **not** completed ExpoPulse functionality. Match implementations to the installed library version and prove the behavior in the demo.

---

**Final instruction to the coding agent:** Inspect first, validate feasibility on footage second, then implement the full minimal solution, test it, document it, and submit a PR. Preserve all shared integrations. Clearly distinguish implementation evidence from assumptions. If blocked, report the precise failed step and a concrete minimal alternative rather than fabricating successful results.
