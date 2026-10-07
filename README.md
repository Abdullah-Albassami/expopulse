# ExpoPulse

ExpoPulse is a smart operations center prototype for Expo 2030. The system is designed to centralize operational incidents and alerts, prioritize them, detect possible duplicates, assign suitable response teams, and track incidents until resolution.

The project is being built as an MVP for **Challenge 3.6 — Expo Operations, Safety, and Security**.

---

## Current Repository Status

The shared Django project foundation has already been created and pushed to `main`.

The repository currently includes:

- Django project configuration
- `incidents` Django app
- Shared database models
- Initial migration for the `incidents` app
- `requirements.txt`
- `.gitignore`

### Core Models Added

The following shared models are already defined in:

```text
incidents/models.py
```

#### `Location`

Stores Expo locations and their importance level.

Main fields:

```text
name
zone
importance_level
```

#### `Team`

Stores response teams.

Main fields:

```text
name
team_type
status
current_location
```

Supported team types include:

```text
Security
Medical
Maintenance
IT
Cleaning
Visitor Services
```

Supported team statuses:

```text
Available
Busy
Offline
```

#### `IncidentSource`

Stores where an incident or alert came from.

Main fields:

```text
name
source_type
```

Examples:

```text
Staff
System
Sensor
Visitor Service
Security
Maintenance
```

#### `Incident`

Main incident record used across the MVP.

Main fields:

```text
title
description
incident_type
source
location
severity
people_affected
priority_score
priority_level
status
assigned_team
possible_duplicate_of
created_at
updated_at
```

Supported incident statuses:

```text
New
Assigned
In Progress
Resolved
```

---

## Initial Setup for Team Members

Each team member should clone the shared repository and work from the latest `main` branch.

### 1. Clone the Repository

```bash
git clone git@github.com:Abdullah-Albassami/expopulse.git
cd expopulse
```

### 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply Database Migrations

```bash
python manage.py migrate
```

### 5. Verify the Project

```bash
python manage.py check
```

Expected result:

```text
System check identified no issues (0 silenced).
```

---

## Branch Assignment

Each member must work on their own feature branch.

Do not develop directly on `main`.

### Ammar — Incident Logic

```bash
git checkout -b feature/incident-logic
```

Main responsibilities:

```text
Priority scoring
Duplicate incident detection
Incident status workflow
```

### Nasser — Dashboard UI

```bash
git checkout -b feature/dashboard-ui
```

Main responsibilities:

```text
Operations dashboard
Incident pages
Team pages
HTML/CSS/JavaScript
Django templates
```

### Mohammed — Team Assignment and Demo Data

```bash
git checkout -b feature/team-assignment-demo-data
```

Main responsibilities:

```text
Team assignment logic
Team availability handling
Seed/mock data
Testing and demo scenarios
```

---

## Team Leader Responsibilities

The team leader is responsible for:

```text
Maintaining the shared project structure
Managing the main branch
Reviewing changes before merging
Resolving integration issues
Coordinating shared model changes
Ensuring the MVP works end-to-end
```

Any change to shared Django models should be discussed with the team leader before implementation.

---

## Git Workflow

Before starting work:

```bash
git checkout main
git pull origin main
```

Then switch to your feature branch.

Example:

```bash
git checkout feature/incident-logic
```

If the branch does not exist locally yet:

```bash
git checkout -b feature/incident-logic
```

---

## Making Changes

After completing a meaningful piece of work:

```bash
git status
git add .
git commit -m "Describe the completed feature"
```

Example commit messages:

```text
Add incident priority scoring logic
Add duplicate incident detection
Add operations dashboard
Add team assignment service
Add ExpoPulse seed data
```

Push your branch:

```bash
git push -u origin YOUR_BRANCH_NAME
```

---

## Important Collaboration Rules

- Do not push feature work directly to `main`.
- Do not change shared model fields without discussing it with the team leader.
- Do not rewrite another member's assigned feature unless coordinated first.
- Keep commits focused and descriptive.
- Pull the latest `main` before starting major new work.
- Run project checks before handing off your branch.

Recommended checks:

```bash
python manage.py check
python manage.py test
```

If your work changes models, migrations must also be handled carefully and coordinated with the team leader.

---

## MVP Workflow

The agreed ExpoPulse MVP workflow is:

```text
Incident enters system
        ↓
Incident data is validated
        ↓
Priority score is calculated
        ↓
Possible duplicate is checked
        ↓
Incident appears on operations dashboard
        ↓
Suitable response team is assigned
        ↓
New → Assigned → In Progress → Resolved
```

---

## MVP Scope

The first working version should include:

```text
Incident creation
Automatic priority scoring
Duplicate incident detection
Operations dashboard
Team assignment
Incident status tracking
Seed/demo data
```

---

## Out of Scope for the Initial MVP

Do not spend time on these unless the core MVP is already complete:

```text
Machine-learning crowd prediction
Real Expo APIs
Real CCTV integration
IoT integrations
GPS tracking
Complex maps
Redis
Celery
Microservices
WebSockets
Mobile application
```

These can be presented later as future enhancements.

---

## Project Goal

The final MVP should demonstrate this clearly:

```text
An operational alert enters ExpoPulse
        ↓
The system identifies how urgent it is
        ↓
Possible duplicate reports are detected
        ↓
The incident appears clearly on the dashboard
        ↓
The appropriate response team is assigned
        ↓
The incident is tracked until it is resolved
```

The priority is to keep the system:

```text
Simple
Clear
Reliable
Easy to demonstrate
Technically complete enough for the hackathon MVP
```
