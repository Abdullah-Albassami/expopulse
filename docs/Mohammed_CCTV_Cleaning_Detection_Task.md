# Mohammed — CCTV Waste-Bin Overflow Detection (Validation-First MVP)

**Project:** ExpoPulse — Expo 2030 Challenge 3.6  
**Owner:** Mohammed  
**Base and PR target:** `experiment/cctv-crowding` (never `main`)  
**Feature branch:** `feature/cctv-cleaning-detection`  
**Status:** Implementation assignment; model performance and video compatibility are **not yet verified**.

## 1. Objective

Build a reproducible prototype that observes a waste-bin area through prerecorded, fixed-camera video, flags a **possible overflowing waste bin**, confirms the visual condition across sampled frames, and creates **one Cleaning incident** through ExpoPulse's existing services. The result is an **operator-verification alert**, not a certified sanitation assessment.

The primary detection target is **visible overflowing/full bins**, not generic trash recognition, spill detection, littering behavior recognition, or a claim that any default YOLO COCO model recognizes overflowing bins.

## 2. Validate feasibility *before integrating into Django*

1. Inspect the actual repository branch, then obtain a suitable openly licensed or self-recorded/staged fixed-camera clip containing **both a clearly normal bin and a visibly overflowing bin**, preferably with transitions. Record origin, license/permission, resolution, camera angle, and duration. Do not commit the footage.
2. Evaluate a specialized pretrained waste-bin state detector, not generic `yolo11n.pt`. Candidate model: [Roboflow Universe — garbage can overflow](https://universe.roboflow.com/s-workspace-yh78p/garbage-can-overflow-repcp), which publishes classes such as `Open_full`, `Close_full`, `Open_empty`, `Close_empty` and `Trash flow`. An alternative published model is [Garbage overflowing](https://universe.roboflow.com/trash-qdazj/garbage-overflowing). **Model availability, account/API requirements, deployment costs, local-export rights and compatibility with actual footage must be checked.** Never embed or commit API keys.
3. Test inference first on still frames from the selected clip: annotated outputs must show the correct region/class/confidence for clear positive and negative cases. Map ambiguous source classes only after inspecting actual labels; do not assume `closedfull` or `Trash flow` always means overflow.
4. Run an initial temporal test on the video. Record false positives, missed detections, inference latency, and whether a camera-specific ROI is necessary. Compare several negative frames (empty/normal bins, people, bags, shadows).
5. **Go/no-go gate:** Proceed with full integration only if the detector reliably distinguishes the selected staged positive from its negative example in repeated demonstrations. If not, report evidence and blockers to the team lead rather than pretending the integration works. An OpenCV camera-specific ROI/baseline-change heuristic is an optional fallback **only with team-lead approval**; label it clearly as a controlled simulation rather than general waste detection.

Research references are candidate solutions, **not independently validated ExpoPulse performance**. TACO is useful for annotated litter, but does not by itself provide a drop-in overflowing-bin detector.

## 3. Repo setup and ownership

Use a separate clone/worktree. Before edits, inspect `incidents/models.py`, `incidents/services/{incident_service,assignment,duplicates,priority}.py`, `incidents/management/commands/detect_crowding.py`, `incidents/management/commands/seed_data.py`, current tests, and `requirements.txt`.

```bash
git clone -b experiment/cctv-crowding https://github.com/Abdullah-Albassami/expopulse.git expopulse-cleaning-lab
cd expopulse-cleaning-lab
git switch -c feature/cctv-cleaning-detection
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
```

Windows PowerShell activation: `.\venv\Scripts\Activate.ps1`. Don't rerun `seed_data` on a database containing valuable local changes. Don't alter other teammates' modules.

**Proposed new files (only after validation):**
- `incidents/management/commands/detect_bin_overflow.py` — CLI, video read, safe cleanup, logging.
- `incidents/cctv/bin_overflow.py` — model adapter, bin/ROI association and temporal alert state, mockable without cloud access.
- `incidents/tests_bin_overflow.py` — deterministic tests with mocked model outputs.
- `docs/BIN_OVERFLOW_DEMO.md` — concise setup, footage source, model choice, thresholds, demonstration evidence, and limitations.

`incidents/cctv/__init__.py` is only needed if absent. Coordinate with Ammar if both features add this package. Avoid modifying models, migrations, dashboard, URL routing, shared services, and the crowding/fall detectors. Add dependencies only if necessary and documented.

## 4. Detection and alert behavior

- Accept a local video file; HTTP/HLS stream support is optional, not a prerequisite.
- Configurable `--video`, `--location`, `--model`/provider, `--confidence`, `--sample-every`, `--confirm-frames`, `--clear-frames`, `--cooldown`, and optional `--roi` and `--save-annotated`.
- Validate CLI parameters and an exact existing `Location.name`; fail clearly for missing paths, inaccessible models, or ambiguous labels.
- Restrict analysis to a fixed bin/camera ROI when needed; document all ROI coordinates and their dependence on camera framing.
- Map explicit model classes into `normal`, `possible_overflow`, `unknown`. Uncertain or absent detections **must not automatically count as normal**.
- Require repeated qualifying observations from the **same bin/ROI** before confirming; don't add counts from unrelated bins or alternating detections.
- Use a candidate → confirmed → cleared state machine. Clear only after sustained reliable normal observations. Brief occlusions and reconnections must not create repeated alert episodes.
- Store no surveillance footage by default. Annotated frames, if saved by option, stay local/out of Git.
- Terminate local files at EOF; release OpenCV resources in a `finally` block; handle Ctrl+C gracefully. Never turn model/API failure into a positive alert.

## 5. ExpoPulse integration

Use the existing `CCTV Monitoring` source (`IncidentSource.SourceType.SENSOR`) and `Incident.IncidentType.CLEANING`. Use `create_incident(...)` and `assign_team_to_incident(incident)`; do not create model rows manually, assign scores yourself, or edit shared services.

Illustrative integration once a confirmed episode passes the active-alert check:

```python
source, _ = IncidentSource.objects.get_or_create(
    name="CCTV Monitoring",
    defaults={"source_type": IncidentSource.SourceType.SENSOR},
)
incident = create_incident(
    title=f"CCTV Possible Bin Overflow - {location.name}",
    description="Possible overflowing waste bin observed by CCTV; operator verification required.",
    incident_type=Incident.IncidentType.CLEANING,
    source=source,
    location=location,
    severity=Incident.Severity.LOW,  # demonstration default, not a validated hygiene threshold
    people_affected=0,
)
if not incident.possible_duplicate_of_id:
    assign_team_to_incident(incident)
```

**Important:** `create_incident()` links possible duplicates but **still inserts a new row**. Before creating, query for an unresolved (`New`, `Assigned`, `In Progress`) incident with the same `CCTV Monitoring` source, `CLEANING` type, location, and exact detector-specific title. Suppress repeated alerts for this camera/bin while it remains unresolved. Use a stable bin identifier in the title if monitoring multiple bins. State the limitation: without a database uniqueness constraint this is not a concurrency-proof guarantee. Do **not** treat an existing unrelated Cleaning incident (e.g. a spill) as the same bin event. When the previous incident is resolved, a fresh visually confirmed episode can create a new incident. Do not auto-resolve an incident when the bin appears emptied.

A seeded Cleaning team exists (`Cleaning Team 1`), though it may not be available. If no suitable team is available, leave the incident `New`. The existing dashboard should pick up new incident records through polling; no UI modifications needed.

## 6. Tests (no model download or external API required)

Use Django tests plus isolated state-machine tests, mocking inference and frames. Verify:

1. Normal/empty bin → no alert.
2. A single possible-overflow frame → no alert.
3. Repeated valid detection from the same ROI → one alert only.
4. Alternating bins/ROIs or intermittent unknown frames cannot falsely satisfy the confirmation count.
5. Transient occlusion does not clear or recreate an episode; sustained reliable normal frames clear it.
6. Cooldown suppresses repeated episodes within the configured interval.
7. Existing unresolved matching bin alert prevents a second database row, including restart-equivalent state.
8. Unrelated Cleaning spill incident does not suppress the bin alert.
9. Resolved matching incident permits a subsequent confirmed new episode.
10. New incident has Cleaning type, CCTV source, location and service-computed priority; assign Cleaning team when available, else leave New.
11. Invalid CLI parameters, unreadable footage, absent model credentials, and inference failures fail safely without phantom incidents.
12. Optional annotated output correctly labels candidate state and stays untracked.

Run and report actual output:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

The historical 15 passing tests are not proof that the new detector works. New tests must pass **in addition** to existing tests; no new migrations.

## 7. Manual acceptance demo

1. Start Django (`python manage.py runserver`) and open `http://127.0.0.1:8000/`.
2. Run `python manage.py detect_bin_overflow --video footage/bin_demo.mp4 --location "Food Court" --confirm-frames 3 --clear-frames 5 --sample-every 5 --confidence 0.5 --cooldown 60` (adapt options/model to actual implementation).
3. Show annotated normal and positive footage; the positive sequence creates **one** Cleaning incident via the real service.
4. Verify automatic priority and available Cleaning-team assignment (or `New` without a free team).
5. Show continuing overflow does not flood incidents; re-running while unresolved also doesn't add another.
6. Demonstrate a negative video and operator resolution, followed by a fresh confirmed event.
7. Record logs/test output, video source and permission, model ID, dependencies, qualitative failure cases, and any API requirements. No fabricated accuracy claims.

**Definition of done:** validated model and video, repeatable positive/negative demonstration, alert state control, no incident flooding, existing ExpoPulse integration, passing tests, zero migrations, readable PR evidence. If the validation gate fails, submit an evidence-based feasibility report instead of claiming full completion.

## 8. GitHub handoff

```bash
git status
git diff --check
# Stage only the new/approved files that actually exist.
git add incidents/management/commands/detect_bin_overflow.py \
  incidents/cctv/ incidents/tests_bin_overflow.py docs/BIN_OVERFLOW_DEMO.md
# Stage requirements.txt only if a dependency was genuinely added.
git diff --cached --check
git diff --cached --stat
git commit -m "Add CCTV waste-bin overflow detection prototype"
git push -u origin feature/cctv-cleaning-detection
```

Open a PR **head:** `feature/cctv-cleaning-detection` → **base:** `experiment/cctv-crowding`, not `main`. Include the feasibility evidence, model/version and licensing, footage source, screenshot/logs, test output, dependency/security notes and limitations. Do not merge your own PR or modify the shared integration branch directly. Confirm with team lead before any shared-file change.
