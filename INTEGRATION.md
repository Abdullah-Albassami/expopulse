> **Historical integration handoff.** All required Django views and routes are integrated. Do not use these instructions as a current installation checklist. See [README.md](README.md).

# ExpoPulse frontend: how to connect it

Copy `templates/` and `static/` into the Django project. The templates were tested
against the current `incidents/models.py` (Location, Team, IncidentSource, Incident)
with a real database, and every field name matches. No model changes are needed.

What is still missing in the project is the views and the URL names below
(`urls.py` currently has only `admin/`).

## 1. Settings

```python
TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]
STATICFILES_DIRS = [BASE_DIR / "static"]
```

`django.template.context_processors.request` and the messages context processor
must be on (both are on by default in a new project).

## 2. URL names the templates use

| Name | Page | Notes |
|---|---|---|
| `dashboard` | Dashboard | |
| `incident_list` | All incidents | |
| `incident_create` | Create incident form | |
| `incident_detail` | One incident | takes the incident id |
| `team_list` | Teams | |
| `incident_update_status` | optional | POST, takes the incident id. Without it the "Move to next step" button is hidden |

## 3. What each view sends

| Template | Context |
|---|---|
| `dashboard.html` | `incidents`, `critical_count`, `high_count`, `active_count`, `available_team_count` |
| `incidents/incident_list.html` | `incidents`, `incident_types` = `Incident.IncidentType.choices`, `locations` = `Location.objects.all()` |
| `incidents/incident_detail.html` | `incident` |
| `incidents/incident_form.html` | `form` = a ModelForm on Incident with `title, description, incident_type, source, location, severity, people_affected` |
| `teams/team_list.html` | `teams`, `available_team_count` |

The three counts on the dashboard are for open incidents (status is not `resolved`).

## 4. Things the views must do

- **Order**: the dashboard and the list show incidents in the order they receive them.
  Send Critical, then High, Medium, Low, newest first inside each level.
- **List filters** arrive as a GET form:
  `priority` (critical/high/medium/low), `status` (new/assigned/in_progress/resolved),
  `type` (an `incident_type` value), `location` (a Location id), `q` (title or id).
- **Teams page** reads `team.assigned_incidents` to show what a team is working on.
  `Team.objects.select_related("current_location").prefetch_related("assigned_incidents")`
  keeps it to a few queries.
- For the incident pages, `select_related("location", "source", "assigned_team", "possible_duplicate_of")`
  avoids one query per row.

## 5. What the frontend does not do

It does not calculate priority, detect duplicates or assign teams. It shows
`priority_level`, `priority_score`, `possible_duplicate_of` and `assigned_team`
exactly as the backend saved them.
