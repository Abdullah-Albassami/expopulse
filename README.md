# ExpoPulse — Experimental CCTV Crowding Branch

> **Branch:** `experiment/cctv-crowding`  
> **Official branch:** `main`  
> **Repository:** [Abdullah-Albassami/expopulse](https://github.com/Abdullah-Albassami/expopulse)  
> **Status:** Experimental prototype — **do not merge into `main` without review**.

This branch is a collaborative sandbox for the **ExpoPulse** smart operations center (Expo 2030, Challenge 3.6). It integrates the Django MVP with **simulated CCTV crowd detection** and **automatic dashboard updates**. It is not the official submission branch and is not suitable for real-world safety decisions.

## What works

- Django operations dashboard, incident list/detail/create pages, and response-teams page.
- Automatic priority scoring and possible-duplicate detection (same incident type and location, unresolved, within 15 minutes).
- Manual workflow: operator confirms a suggested team, then moves the incident **New → Assigned → In Progress → Resolved**; resolution releases the team.
- CCTV experiment: OpenCV + YOLO processes an MP4, counts detected people, and creates a **Crowding** incident when the configured threshold persists across sampled frames.
- For **non-duplicate CCTV alerts**, the detector attempts **automatic assignment** of an available Security team. Possible duplicates are flagged and are not assigned a second team by the detector.
- Dashboard polls `/dashboard/data/` approximately every **5 seconds**, updating counts, charts, and rows without a manual refresh, with a new-incident notification. Other pages may still require refreshing.
- Repeatable `seed_data` command for sample locations, sources, teams, and incidents.

**Already manually verified in the development environment:** Django system and migration checks, 15 original incident-service tests, manual incident assignment/resolution/team release, CCTV-created incidents with correct priority and duplicate linking, and dashboard auto-update notification. **Not yet verified across teammate machines:** platform-specific setup, automated tests for the detector/polling integration, and HLS/M3U8 playback.

Crowding is currently a **visible-person-count heuristic**, not a validated measurement of occupancy, density, or safety risk. Low thresholds such as `--threshold 2` are **for testing only**.

## 1. Safest setup: a separate clone

Use a different directory from your normal ExpoPulse checkout. You need Git, Python, and access to this **private** GitHub repository. SSH cloning requires a configured GitHub SSH key.

### macOS — Terminal

```bash
git clone --branch experiment/cctv-crowding git@github.com:Abdullah-Albassami/expopulse.git expopulse-cctv-lab
cd expopulse-cctv-lab
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test incidents
python manage.py seed_data
python manage.py runserver
```

### Windows — PowerShell

```powershell
git clone --branch experiment/cctv-crowding git@github.com:Abdullah-Albassami/expopulse.git expopulse-cctv-lab
cd expopulse-cctv-lab
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test incidents
python manage.py seed_data
python manage.py runserver
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` **in that terminal session only**, then activate again. Alternatively use Command Prompt: `venv\Scripts\activate.bat`.

Open **http://127.0.0.1:8000/**. Leave the server running; stop it with **Ctrl+C**. On some macOS installations, use `python3` in place of `python` if needed.

**Notes:** `migrate` creates your own local SQLite database. `seed_data` creates or updates demonstration records, so avoid rerunning it midway through a scenario. Django's built-in server is for development only.

## 2. Already have a clone?

To inspect or switch safely:

```bash
git status
git fetch origin experiment/cctv-crowding
git switch --track origin/experiment/cctv-crowding
```

The `git switch --track` command is for when the local branch does **not** exist. If it already exists:

```bash
git switch experiment/cctv-crowding
git pull --ff-only
```

**Save or stash local changes before switching.** Do not run `git pull origin experiment/cctv-crowding` while on `main`; that could bring experiment changes into `main`. A separate clone is the safest option for active teammates.

## 3. Manual ExpoPulse smoke test

1. Open **Dashboard**, **Incidents**, **Create incident**, and **Teams**.
2. Create a Crowding incident at a seeded location using a reasonable severity and person count.
3. Check its automatically calculated priority and any duplicate warning.
4. If a matching team is available, click **Confirm team assignment**.
5. Click **Start incident response** and then **Mark as resolved**.
6. Check that the team returns to **Available**.

Previously seeded or unresolved incidents can influence duplicate detection and team availability. Use a new local SQLite database for a repeatable clean demo if needed; **never delete or reset shared data**.

## 4. Simulated CCTV experiment (MP4)

The detector lives at `incidents/management/commands/detect_crowding.py`. Check that this file was included in the branch you fetched. Use a video you have permission to process; **do not commit videos or footage containing identifiable visitors**.

If the committed `requirements.txt` does not yet include both computer-vision libraries, install them inside your active virtual environment:

```bash
python -m pip install ultralytics opencv-python
```

Create a local `footage/` folder and add your own MP4, such as `footage/indoor_mall_cctv.mp4`. Start Django in one terminal. In a **second terminal**, enter the project folder, activate its virtual environment, and run:

```bash
python manage.py detect_crowding --video footage/indoor_mall_cctv.mp4 --location "Gate 1" --threshold 2 --frames 2
```

`--threshold 2` is a **low test threshold**, used only to prove the pipeline. The detector samples video frames, counts YOLO person detections, and triggers after the specified number of consecutive **sampled** frames meets the threshold. On the first run, YOLO may download its pretrained model weights.

**Expected behavior if the footage triggers:** A new `Crowding` incident appears in Django, receives a calculated priority, and is checked for duplicates. The detector assigns an available Security team only if it does not flag the new incident as a duplicate. The **dashboard should update within roughly five seconds while its tab is visible**. If no incident appears, inspect the detector output and adjust the threshold for testing.

The detector currently processes a video source until it ends (or a stream disconnects); it is not a permanently managed monitoring service. **HLS/M3U8 is the next experiment**: the `--video` argument can take a URL if OpenCV's video backend can decode the stream, but a live HLS server is **not bundled or verified yet**.

## 5. Collaboration and Git safety

- **Never push experimental work to `main` or merge this branch into `main` without team review.**
- Create a personal branch from `experiment/cctv-crowding` for changes:

```bash
git switch experiment/cctv-crowding
git pull --ff-only
git switch -c experiment/cctv-yourname
```

- Verify changes, commit, and push your personal branch:

```bash
git status
git add .
git diff --cached --stat
git commit -m "Describe experimental change"
git push -u origin experiment/cctv-yourname
```

- Share a link or open a PR **targeting `experiment/cctv-crowding`**, not `main`.
- Coordinate modifications to models, migrations, priority scoring, status handling, and team availability.
- Do not force-push the shared experimental branch.
- Keep `venv/`, `db.sqlite3`, `footage/`, `*.pt`, `.env`, and other generated or sensitive files ignored; check `git status` before committing.

## 6. Core service entry points

| Service | Purpose |
|---|---|
| `incidents.services.incident_service.create_incident()` | Validates and creates incidents with priority and duplicate checks |
| `incidents.services.assignment.find_suitable_team()` | Recommends a matching available team |
| `incidents.services.assignment.assign_team_to_incident()` | Assigns team and marks it busy |
| `incidents.services.workflow.update_incident_status()` | Validates normal status transitions |
| `incidents.services.assignment.release_team_from_incident()` | Resolves incident and makes assigned team available |
| `python manage.py seed_data` | Populates local demo data |
| `python manage.py detect_crowding` | Runs experimental video detection |

Use the shared services instead of recreating priority or assignment logic in frontend JavaScript or computer-vision code.

## 7. Useful commands

| Task | Command |
|---|---|
| Active branch | `git branch --show-current` |
| Working-tree changes | `git status` |
| Update experimental branch | `git pull --ff-only` (while on that branch) |
| Django checks | `python manage.py check` |
| Migration check | `python manage.py makemigrations --check --dry-run` |
| Existing automated tests | `python manage.py test incidents` |
| Apply migrations | `python manage.py migrate` |
| Add demo data | `python manage.py seed_data` |
| Start dashboard | `python manage.py runserver` |

---

**Goal:** Demonstrate an indoor CCTV crowding signal becoming an ExpoPulse incident, automatically scored, checked for duplicates, assigned to the appropriate team when suitable, and displayed on a live-updating operations dashboard — without changing the official MVP branch.
