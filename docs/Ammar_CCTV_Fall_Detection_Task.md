# Ammar — CCTV Possible-Fall Detection

**Project:** ExpoPulse (Django operations center, Expo 2030 Challenge 3.6)
**Owner:** Ammar
**Base branch:** `experiment/cctv-crowding`
**Your branch:** `feature/cctv-fall-detection`
**PR target:** `experiment/cctv-crowding` (**NOT** `main`)
**Deliverable:** A working, independently testable **possible-fall detector** that creates a *Medical* incident through existing ExpoPulse services when a sustained, credible fall/lying-person event is detected.

> **Read this document as the complete implementation assignment.** You may use an AI coding agent. Give it this file and access to the repository. The agent must inspect the checked-out source before coding; this document describes the integration contract, not an excuse to assume the code is unchanged.

## 1. Mission and scope

Build a **prototype CCTV detector for a *possible* person fall or person remaining on the ground**. Use authorized, prerecorded video for demonstration; an MP4 is sufficient. An HTTP(S) video stream is optional if it works with OpenCV. A detected posture **must not be presented as a medically confirmed emergency**. The dashboard should show an automatically created Medical incident, suitable for review by an operator.

**Required:** pose-based evidence across time; person-level tracking or temporal association; filtering of momentary crouching/sitting; event confirmation; duplicate/active-alert suppression; integration into existing incident creation and Medical team assignment; deterministic tests; CLI usage documentation.
**Not required:** new Django models, frontend changes, a training pipeline, real surveillance hardware, medical diagnosis, or production-grade fall detection.

## 2. Source of truth: inspect the repository first

Repository: `https://github.com/Abdullah-Albassami/expopulse` (private; request access from the team lead if necessary).

Inspect **before editing**:

- `incidents/models.py` — `Incident`, `IncidentSource`, `Location`, `Team` and choice constants.
- `incidents/services/incident_service.py` — **`create_incident(...)`**, which validates, scores, checks duplicates, and saves incidents.
- `incidents/services/assignment.py` — **`assign_team_to_incident(incident)`** and Medical-team routing.
- `incidents/services/duplicates.py` — existing possible-duplicate semantics.
- `incidents/management/commands/detect_crowding.py` — reference for CLI, YOLO/OpenCV, source setup, and cleanup; **do not rewrite it**.
- `incidents/tests.py`, `requirements.txt`, `README.md` — tests, dependency conventions, and setup.

Current model types already include `Incident.IncidentType.MEDICAL`, `Incident.Severity`, and `Incident.Status`; team assignment maps `medical` incidents to `Team.TeamType.MEDICAL`. The existing source `CCTV Monitoring` uses `IncidentSource.SourceType.SENSOR`.

## 3. Setup and Git workflow

Use a **separate working directory** from the team's main checkout. Clone with GitHub HTTPS or SSH. Example:

```bash
git clone -b experiment/cctv-crowding https://github.com/Abdullah-Albassami/expopulse.git expopulse-fall-lab
cd expopulse-fall-lab
git pull --ff-only
git switch -c feature/cctv-fall-detection

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

For **Windows PowerShell**, substitute:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

If you use an AI coding agent (including one with a **GitHub connector**), give it the repository, **your feature branch**, and this full task. Grant access to this repository if your agent requires authorization. The agent should read the real files and work only on your branch; **do not let it write to `main` or the shared experimental branch**. If it cannot access GitHub directly, work from your local clone and push through Git.

## 4. Required implementation

### A. New command and separation of concerns

Create:

- `incidents/management/commands/detect_falls.py` — CLI and video-processing loop.
- `incidents/cctv/fall_detection.py` (and `incidents/cctv/__init__.py`) — reusable, **pure or easily mockable temporal fall-event logic**. You may split tracking and geometry into small modules if justified.
- `incidents/tests_fall_detection.py` — new automated tests (or a test package if consistent with repository conventions).
- `docs/FALL_DETECTION_USAGE.md` — brief setup, usage, evidence, limitations, troubleshooting.

Do not change existing incident models, migrations, URLs, templates, priority-scoring code, duplicate service, team-assignment service, or crowding detector without obtaining approval. Avoid introducing unnecessary dependencies. Use already available `ultralytics`, `opencv-python`, and `numpy` where possible.

### B. Model and event detection

Use a pretrained **YOLO pose model** (suggested starting point: `yolo11n-pose.pt`). Download pretrained weights at runtime via the existing Ultralytics mechanism; keep `*.pt` ignored. Do **not** treat a standard person-detection bounding box by itself as proof of a fall.

Implement a documented, adjustable **candidate fall heuristic**, combining several visual cues, for example:

1. Person's torso or body orientation becomes unusually horizontal **or** keypoint geometry indicates a lying posture.
2. Low body position / posture relative to the scene is consistent with being on the ground.
3. The evidence persists across multiple sampled frames or a configurable time interval.
4. A detected person's pose can be associated across frames (Ultralytics tracking IDs when available, or a simple documented bounding-box association). Avoid mixing observations from different individuals.

Use keypoint confidence thresholds and explicitly handle missing/occluded keypoints. Implement a *candidate → confirmed → cleared* state lifecycle, with a configurable clear duration/hysteresis so temporary keypoint loss does not repeatedly trigger alerts. Prefer an initial **possible-fall/lying-person** classification rather than claiming to distinguish all real falls. If the available video cannot establish that someone fell, title the event accordingly.

You may choose concrete angle/aspect-ratio thresholds after inspecting the model output and test footage. **Document and expose important thresholds**; never hard-code claims of medically validated accuracy.

### C. Command interface

Support these arguments at minimum:

```text
python manage.py detect_falls \
  --video footage/fall_demo.mp4 \
  --location "Zone C" \
  --confirm-frames 5 \
  --sample-every 5 \
  --confidence 0.35 \
  --cooldown 120
```

- `--video`: required local video path; URL support is optional.
- `--location`: existing `Location.name`; helpful error for an unknown/ambiguous location.
- `--confirm-frames`: consecutive qualifying sampled observations for **the same person**.
- `--sample-every`: stride for image processing.
- `--confidence`: detection confidence; validate `(0, 1]`.
- `--cooldown`: non-negative time between eligible alert episodes.
- Optional `--model`, `--clear-frames`, `--show`/`--save-annotated` if useful. A *saved annotated example* is highly recommended for review.

Validate all parameters. Handle missing/unreadable video gracefully, release `VideoCapture` on success/failure, and terminate cleanly on `Ctrl+C`. For local MP4, stop at end-of-file instead of reconnecting endlessly. Never create an incident for a single fleeting false positive.

### D. Django incident integration — use existing services

When one **confirmed** possible-fall event occurs, create an incident using the existing service:

```python
from incidents.models import Incident, IncidentSource, Location
from incidents.services.incident_service import create_incident
from incidents.services.assignment import assign_team_to_incident

source, _ = IncidentSource.objects.get_or_create(
    name="CCTV Monitoring",
    defaults={"source_type": IncidentSource.SourceType.SENSOR},
)

incident = create_incident(
    title=f"CCTV Possible Fall - {location.name}",
    description=(
        "Possible person fall or prolonged lying posture detected by CCTV. "
        "Requires immediate operator verification."
    ),
    incident_type=Incident.IncidentType.MEDICAL,
    source=source,
    location=location,
    severity=Incident.Severity.HIGH,
    people_affected=1,
)
```

The existing service computes priority and performs standard duplicate linking. **Do not calculate or overwrite priority fields yourself.** Severity `HIGH` is a prototype default, not a medical triage decision.

**Prevent incident flooding:** Before generating a new CCTV Medical incident for a matching location/event, check for an **unresolved incident with the same CCTV source, incident type, and location**. If one exists, log that the event is already active rather than inserting another record. Implement this logic in a small helper local to your detector; don't alter the shared duplicate service. Document the limitation that this coarse key can combine unrelated falls in the same location. This policy is for the prototype only, not a final multi-person tracking design.

If a new incident is created, call `assign_team_to_incident(incident)` **only if it is not flagged as a possible duplicate**. If no Medical team is available, leave the incident `New` and log it. Never modify a team status manually. Do not silently discard a high-severity event on an exception; print a useful error.

### E. Demo and operator verification

Use a **consented, synthetic, staged, or suitably licensed** fall/lying-person clip, with no need to commit the footage. In `docs/FALL_DETECTION_USAGE.md`, provide a reproducible demo:

1. Setup and command to start Django.
2. Command to start your detector with the demo video.
3. Expected terminal output (person candidate, confirmed event, incident created or suppressed).
4. Dashboard check for a **Medical** incident at the chosen location.
5. Expected assignment to an available Medical team, or the `New` fallback.
6. A negative demonstration (walking, sitting, or normal motion produces no incident).

Keep `footage/`, downloaded model weights, HLS output, `.env`, `db.sqlite3`, and `venv/` out of Git. If you need to share footage, link to the public source with its license and retrieval instructions; do not assume videos are in the repository.

## 5. Automated testing — mandatory

Tests must run without downloading model weights or processing actual footage. **Mock the pose model and video capture** or test the reusable state machine directly.

Minimum assertions:

1. A normal upright walking sequence produces **no** event.
2. An isolated horizontal/low pose produces **no** event before the confirmation threshold.
3. A sustained candidate for the **same tracked person** produces **one** confirmed event.
4. Different tracked people cannot accidentally satisfy one person's confirmation threshold.
5. Brief missing keypoints/occlusion do not create repeated alerts.
6. A confirmed event clears only after the required recovery observations.
7. Cooldown prevents repeat alerts during the protected period.
8. An unresolved, matching CCTV Medical incident blocks creation of a second incident.
9. A new qualifying event creates `Incident.IncidentType.MEDICAL`, retains automatic priority and matches `CCTV Monitoring` source.
10. Appropriate Medical team assignment occurs only when an eligible team is available; no team means a `New` incident.
11. Invalid CLI options and unreadable local paths fail with helpful errors.

Do not weaken or change existing tests just to obtain green output. Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

All original incident tests plus the new tests should pass; there should be **no migrations**. Document any new dependency and update `requirements.txt` only when strictly required, with a justification in the PR.

## 6. Acceptance criteria — definition of done

- [ ] `python manage.py detect_falls --help` shows documented options.
- [ ] Demonstration clip is processed without crashes; logs are readable.
- [ ] Confirmed sustained *possible-fall* episode creates exactly one **Medical** incident when no matching active incident exists.
- [ ] Normal walking/brief crouching does not create a Medical incident in the chosen negative clip.
- [ ] Existing priority and duplicate services remain unchanged and are exercised through `create_incident()`.
- [ ] Medical team assigned when eligible; otherwise incident remains `New`.
- [ ] Correct alert suppression, event-clearance handling, and resource cleanup.
- [ ] Automated tests cover both temporal detection and database integration.
- [ ] Original 15 tests still pass; `manage.py check` clean; no migrations.
- [ ] No footage, private data, `.pt` weights, databases, or venv files in Git.
- [ ] Brief usage document states limitations and how to reproduce a demo.
- [ ] PR opened against `experiment/cctv-crowding` with logs, tests, demo evidence, and list of files changed.

## 7. Push and handoff

After checking `git status` and validating staged paths:

```bash
git add incidents/management/commands/detect_falls.py \
  incidents/cctv/ \
  incidents/tests_fall_detection.py \
  docs/FALL_DETECTION_USAGE.md
# Only stage requirements.txt if you intentionally added a necessary dependency.
git diff --cached --check
git diff --cached --stat
git commit -m "Add CCTV possible-fall detection prototype"
git push -u origin feature/cctv-fall-detection
```

Create a GitHub pull request with **base `experiment/cctv-crowding`** and **head `feature/cctv-fall-detection`**. Share the PR URL with the team lead; **do not merge your own PR**. Include: approach, thresholds, tested video (source/license), sample terminal output, a screenshot or annotated demonstration, test summary, known false positives/false negatives, and any performance constraints.

**If blocked:** First inspect the implementation and report the exact missing file/interface or error to the team lead. Do not invent shared APIs or modify core services as a workaround. Keep the module independent so the lead can integrate it with the other CCTV detectors.
