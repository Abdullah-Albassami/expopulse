# Ammar — CCTV Possible-Fall Detection

**Project:** ExpoPulse — Expo 2030 Challenge 3.6 (Operations Center)  
**Owner:** Ammar  
**Repository:** `Abdullah-Albassami/expopulse` (private)  
**Base / PR target:** `experiment/cctv-crowding` (**never `main`**)  
**Your feature branch:** `feature/cctv-fall-detection`  
**Deliverable:** A reproducible, independently tested **possible-fall or sustained lying-posture detector** that creates an operator-reviewable **Medical** incident through ExpoPulse's existing services.

> Give this entire guide to your coding agent. It must inspect the actual branch before editing. Do not claim that the model diagnoses a fall or a medical emergency.

## 1. Target outcome and boundaries

`Authorized MP4 CCTV footage → pretrained YOLO11 pose → person association → posture and temporal checks → confirmed possible-fall event → existing incident service → Medical team assignment → live dashboard`

Use **pretrained `yolo11n-pose.pt`** as the starting point, **OpenCV**, and the repository's existing Ultralytics installation. Pose estimation provides person keypoints, **not a built-in fall classifier**; write a small, explicit rule-based detector over time. A recorded demonstration MP4 is sufficient; HTTP(S) stream support is optional. No training, proprietary services, new Django models, migrations, hardware integrations, or new dashboard UI are required.

**Language for alerts:** “Possible Fall” or “Possible Person Lying on Ground — Operator Verification Required.” Do not report a confirmed medical emergency or claim medically validated sensitivity/accuracy.

## 2. Stage 0 — feasibility check BEFORE full implementation (mandatory)

1. Find **authorized, staged/synthetic, or suitably licensed** footage with at least one clearly visible staged fall or persistent lying posture **and** a negative clip showing ordinary walking, sitting, or crouching. Record source/license or consent and camera angle. Do not commit videos or identifiable personal footage.
2. Install dependencies and run `yolo11n-pose.pt` on representative frames. Inspect visualized bounding boxes, skeletons, keypoint confidence, resolution, and any tracking IDs. Save a local annotated sample frame for the PR evidence (without committing private footage).
3. Document whether hips, shoulders, knees, and ankles are reliably present in this footage and whether the apparent horizontal/low posture differs from normal actions. A side view that clearly shows body orientation is often easier for an MVP than an overhead view, but validate it rather than assuming.
4. Implement a *small offline feasibility check* before Django integration. Confirm that one sustained positive sequence can trigger a candidate and at least one negative sequence does not. These are demonstration checks, **not measured real-world accuracy**.
5. If pose evidence is insufficient, **stop and report** the exact limitation, output screenshots/logs, and recommend a different clip, camera angle, or model size. Do not fabricate a successful result or silently switch to a bounding-box-only “fall detector.”

**Gate:** Proceed to full integration only when model output and available footage support a defensible possible-fall heuristic. The first PR may report a clearly identified blocker if this gate fails.

## 3. Inspect the actual repository and prepare a safe branch

Read before coding:

- `incidents/models.py` — model fields, choices, and statuses.
- `incidents/services/incident_service.py` — `create_incident(...)` performs validation, priority setting, duplicate *linking*, and save.
- `incidents/services/assignment.py` — `assign_team_to_incident(incident)` routes Medical incidents.
- `incidents/services/duplicates.py` — a possible duplicate **still creates a row**; it does not provide event suppression.
- `incidents/management/commands/detect_crowding.py` — CLI, video handling, and incident-integration example; **do not modify it**.
- `incidents/management/commands/seed_data.py`, `incidents/tests.py`, `requirements.txt`, and `README.md`.

Use a separate checkout:

```bash
git clone -b experiment/cctv-crowding https://github.com/Abdullah-Albassami/expopulse.git expopulse-fall-lab
cd expopulse-fall-lab
git switch -c feature/cctv-fall-detection
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

Windows PowerShell, after `cd` and branch creation:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

If already cloned: first inspect `git status` and existing branches. Do not discard uncommitted work, overwrite shared branches, force-push, or merge into `main`. For an AI agent, ensure the private repository has been explicitly authorized or provide a local clone. Propose the minimal changes after inspecting current code.

## 4. Implementation contract

### Files owned by this feature

- `incidents/management/commands/detect_falls.py` — CLI, pose inference/video processing, resources and output.
- `incidents/cctv/__init__.py` and `incidents/cctv/fall_detection.py` — reusable pose interpretation, per-person event state, temporal logic. Additional small dedicated files only if needed.
- `incidents/tests_fall_detection.py` — deterministic tests, **no weight downloads**.
- `docs/FALL_DETECTION_USAGE.md` — short reproducible instructions, video/source, settings, sample evidence, limitations.

Avoid touching `incidents/models.py`, migrations, URLs, templates, shared priority/duplicate/assignment/workflow services, or `detect_crowding.py`. Update `requirements.txt` only for an essential missing dependency.

### Evidence and person association

- Derive plausible body orientation and position using confident pose keypoints (especially shoulder/hip/leg geometry) and, if useful, bounding-box aspect ratio **as a supporting cue only**.
- Define documented, adjustable thresholds after inspecting video; don't imply ground contact from image coordinates alone. Perspective and camera angle can make standing people appear low or horizontal.
- Tie consecutive observations to the **same person**, using Ultralytics tracking IDs where reliable or a documented association method. Reset or isolate tracks when IDs disappear; do not accumulate evidence across different people. Document the risk of ID switches.
- Ignore or classify as **uncertain** low-confidence/occluded poses rather than assuming a fall. Avoid triggering on momentary crouching, sitting, a single horizontal-looking frame, or an incomplete skeleton.
- Use `candidate → confirmed → cleared` state per tracked person, with configurable confirmation and clearance periods. A brief disappearance must **not** immediately clear an event; define expiry for tracks missing for a sustained duration.
- Show logs for candidates, confirmations, suppression, clearing, and keypoint/track uncertainty. Optional annotated output is strongly recommended.

**Temporal semantics:** `--confirm-frames` means qualifying **processed** observations for the same person, not every raw video frame. `--sample-every` sets frame stride. For a local MP4, time-based durations must be derived from video timestamps/FPS or an explicitly documented alternative; do **not** equate playback wall-clock time with recorded time. State how `--cooldown` is measured. Keep recorded-video behavior reproducible.

### Required CLI

```bash
python manage.py detect_falls \
  --video footage/fall_demo.mp4 \
  --location "Zone C" \
  --confirm-frames 5 \
  --sample-every 5 \
  --confidence 0.35 \
  --cooldown 120
```

Validate inputs (`confirm-frames` and `sample-every` >= 1, `0 < confidence <= 1`, nonnegative cooldown, valid Location). Support informative errors for unreadable MP4, absent keypoints, model failure, and invalid options; clean up `VideoCapture` and any windows on normal exit or `Ctrl+C`. MP4 processing **stops at EOF**. Optional flags: `--model`, `--clear-frames`, `--save-annotated`, and HLS input only if proven reliable. Avoid requiring a webcam or access to real CCTV.

## 5. ExpoPulse incident and alert lifecycle

Use **only existing** integration services:

```python
from incidents.models import Incident, IncidentSource
from incidents.services.incident_service import create_incident
from incidents.services.assignment import assign_team_to_incident

source, _ = IncidentSource.objects.get_or_create(
    name="CCTV Monitoring",
    defaults={"source_type": IncidentSource.SourceType.SENSOR},
)

incident = create_incident(
    title=f"CCTV Possible Fall - {location.name}",
    description=(
        "Possible fall or sustained lying posture detected from CCTV pose evidence. "
        "Operator verification required."
    ),
    incident_type=Incident.IncidentType.MEDICAL,
    source=source,
    location=location,
    severity=Incident.Severity.HIGH,
    people_affected=1,
)

if not incident.possible_duplicate_of_id:
    assign_team_to_incident(incident)
```

This is **illustrative integration**, not a complete detector. Never set the priority score directly. `HIGH` is a prototype severity default, **not medical triage**. If no eligible Medical team is available, leave the incident `New`; do not modify team statuses directly. Log any API/database error; do not silently discard confirmed events.

**Critical duplicate rule:** Before calling `create_incident()`, search for a matching **unresolved** Medical incident from **CCTV Monitoring** at the **same Location**. If one exists, suppress creation and log the existing incident ID. This check must work after restarting the command; in-memory cooldown alone is insufficient. The existing duplicate service only *links* duplicates after creating them. Document that location-level suppression may combine independent people/events, which is acceptable for the MVP but not a production multi-person policy.

A cleared visual event does **not** automatically resolve the operator's incident or release its team. Only the normal operator workflow resolves it. Once the earlier incident has been resolved, a genuinely new confirmed episode may create a new incident (subject to local cooldown). Do not confuse a single tracked person's episode with a persistent database incident; avoid re-alerting while either remains active.

For this single-process local demo, the pre-insert query is sufficient to demonstrate suppression, **not a concurrency-safe uniqueness guarantee**. Do not claim atomic protection for multiple simultaneous workers.

## 6. Automated tests (mandatory)

Use Django tests and mocks/fake pose observations. Tests must run offline without downloading YOLO weights or reading real video. Cover at minimum:

1. Normal upright walking → no event.
2. Single brief horizontal posture → no confirmation.
3. Sustained qualifying pose for **one track** → one confirmation.
4. Alternating poses from **different tracks** cannot combine into one confirmation.
5. Missing/low-confidence keypoints and transient occlusion handled without a false repeat.
6. Sitting/crouching negative sequence does not trigger in the selected fixture.
7. Confirmed state clears only after the configured recovery/absence interval.
8. Cooldown suppresses eligible repeats; document video-time versus wall-time semantics.
9. Missing/reassigned track ID does not silently transfer another person's confirmation state.
10. New confirmed event creates one Medical incident with correct source/location and automatic priority.
11. Matching unresolved Medical CCTV incident blocks a second row, including after simulated detector restart.
12. Resolved prior incident plus a **new** qualifying episode can create another.
13. Eligible Medical team is assigned if incident isn't flagged as duplicate; otherwise remains `New` if none available.
14. Invalid CLI parameters, unknown Location, and missing/unreadable MP4 report useful errors and clean up resources.
15. Positive/negative deterministic fixtures exercise the candidate/confirmed/cleared logic.

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

The previous experimental branch had **15 existing incident tests**. Do not weaken them. Report the actual final passing count; zero migrations expected. If the new test module isn't discovered by `test incidents`, fix discovery rather than claiming tests ran.

## 7. Manual demo and acceptance criteria

In `docs/FALL_DETECTION_USAGE.md`, state model, thresholds, tested camera angle, license/consent for the positive and negative clips, commands, sample logs, and limitations. Verify:

- [ ] Pose model produces interpretable keypoints on actual positive footage; early feasibility gate passed.
- [ ] Sustained possible-fall/lying posture generates a **Medical** incident requiring operator verification.
- [ ] Normal walking, sitting, or brief crouching clip produces no false incident in the chosen test.
- [ ] Incident is visible in ExpoPulse dashboard; assigned to Medical team when one is available.
- [ ] No repeat incident appears during the active visual episode or while a matching unresolved DB incident exists, even after command restart.
- [ ] Resolved incident allows a new genuine episode; visual clearance does not auto-resolve tickets.
- [ ] Tests and Django checks pass; no migrations and no changes to shared services.
- [ ] No MP4s, `.pt` files, secrets, databases, virtual environments, HLS artifacts or sensitive frames are committed.
- [ ] Provide an annotated still/log evidence where licensing/privacy allows, plus limitations and probable false-positive/negative cases.

Explain that staged demonstrations **do not prove detection reliability on all CCTV angles, crowds, low light, or occlusions**.

## 8. Commit, PR, and handoff

Review files and stage **only those actually changed**:

```bash
git status
git add incidents/management/commands/detect_falls.py incidents/cctv/ incidents/tests_fall_detection.py docs/FALL_DETECTION_USAGE.md
git diff --cached --check
git diff --cached --stat
git commit -m "Add CCTV possible-fall detection prototype"
git push -u origin feature/cctv-fall-detection
```

Stage `requirements.txt` separately only if a necessary dependency was added. Open a PR with **head** `feature/cctv-fall-detection` and **base** `experiment/cctv-crowding` (**not `main`**). Do not merge your own PR. Include changed-file list, model and footage source/license, thresholds and interpretation, annotated evidence or logs, commands to reproduce, exact test output, limitations, and unresolved integration concerns. If feasibility gate fails, report the blocker and evidence before proceeding; do not claim the feature is complete.
