> **Frontend implementation notes.** Some sections document the original UI handoff and may describe historical behavior. Refer to [README.md](README.md) for the integrated prototype and current setup.

# ExpoPulse frontend

Member 3 task: the operations dashboard and user interface for ExpoPulse,
the Smart Expo Operations Center (challenge 3.6).

This document explains what was built and what was used to build it.
For how to connect it to the backend, see `INTEGRATION.md`.

## What was built

Five pages that share one layout, plus one stylesheet and one script.

| Page | File | What the operator can do |
|---|---|---|
| Dashboard | `templates/dashboard.html` | See the urgent numbers at a glance and filter the incident table by clicking |
| Incident list | `templates/incidents/incident_list.html` | Browse every incident and filter by priority, status, type, location or search text |
| Incident detail | `templates/incidents/incident_detail.html` | Read one incident in full, see the duplicate warning and follow its progress |
| Create incident | `templates/incidents/incident_form.html` | Report a new incident |
| Teams | `templates/teams/team_list.html` | See each response team, its status, location and current incident |

Shared files:

| File | Purpose |
|---|---|
| `templates/base.html` | Page shell: top bar, navigation, messages, content block |
| `static/css/styles.css` | All styling for the five pages |
| `static/js/dashboard.js` | All interface behaviour |

## Dashboard

The dashboard is built from three parts, top to bottom.

**Number tiles.** Critical, High priority, Active now and Teams free.
Critical and High priority filter the table. Active now clears the filter.
Teams free opens the Teams page.

**Two charts.**

- Open incidents by priority: four vertical bars. Clicking a bar shows only that priority.
- Where incidents stand: a ring split by status (New, Assigned, In progress, Resolved)
  with a legend. Clicking a segment or a legend row shows only that status,
  and the number in the middle of the ring changes to match.

**Incident table.** Most urgent first. The heading shows what is being
filtered and how many incidents match, and a "Show everything" link clears it.
Clicking anywhere on a row opens that incident, so there is no need to go
through the Incidents page.

Only one filter is active at a time, and the tiles, bars, ring and legend
always show the same selection.

The charts are drawn from the rows of the table, so the backend sends the
incident data once.

## Other pages

**Incident list.** Columns in this order: ID, Title, Priority, Status,
Location, Type, Source, Team, Created. The filters are a normal GET form,
so filtering happens in the backend and the page reloads. Choosing a value
in a dropdown submits the form straight away.

**Incident detail.** Uses the full width of the page. A large header card
shows the incident number, priority, status, title and location, with the
four steps (New, Assigned, In progress, Resolved) running across it. The
duplicate warning sits directly under it, then the description, then eight
fact cards (priority and score, team, severity, people affected, type,
source, created, updated). The header takes the color of the incident's
priority. The response actions retain the existing assignment and status-transition controls.

**Create incident.** Draws whatever Django form the view sends. Empty
required fields are pointed out before the form is sent. Priority is not
calculated here.

**Teams.** One card per team with a colored edge for Available, Busy or Offline.

## Design

- Dark navy blue with a gradient background and a soft blue glow at the top.
- Logo: a ring with a pulse line running through it, drawn as inline SVG in
  `base.html`, next to the ExpoPulse wordmark. No image file is needed.
- One typeface, Bricolage Grotesque, loaded from Google Fonts with a system font fallback.
- Priority colors: Critical red, High amber, Medium yellow, Low grey-blue.
  Status colors: New blue, Assigned purple, In progress teal, Resolved green.
  Every priority and status also has a text label, so nothing depends on color alone.
- The top bar stays fixed at the top of the screen while scrolling, on every page.
- All colors are defined once as variables at the top of `styles.css`.

## What was used

| | |
|---|---|
| HTML | Django templates with template inheritance |
| CSS | Plain CSS: custom properties, Grid, Flexbox, `position: sticky` |
| JavaScript | Plain JavaScript, no libraries and no build step |
| Charts | Built by hand: CSS for the bars, inline SVG for the ring |
| Logo | Inline SVG |
| Font | Bricolage Grotesque (Google Fonts) |

Not used: React, Vue, Angular, Chart.js, Bootstrap, Tailwind, jQuery.

## Responsive behaviour

Built for laptop screens first. At 900px and below the charts and detail
layout stack into one column and wide tables scroll sideways inside their
own box. At 520px and below the filters stack. No page scrolls sideways
at phone width.

## Accessibility

- Skip link to the main content.
- Visible focus outline on every control.
- Every form input has a label.
- Filter controls are real buttons and report their pressed state.
- The current page is marked in the navigation.
- Animations are turned off for people who ask their system to reduce motion.

## What the frontend does not do

Priority scoring, duplicate detection and team assignment are backend work.
The interface shows `priority_level`, `priority_score`,
`possible_duplicate_of` and `assigned_team` exactly as they are saved.
The only JavaScript logic is showing, hiding and counting rows already on the page.

## Testing

The templates were run against the project's `incidents/models.py` with
sample data in a real browser:

- All five pages open without template or JavaScript errors.
- Every dashboard filter (tiles, bars, ring, legend) shows the right rows.
- Incident list filters and search return the right rows.
- The duplicate warning appears on the detail page.
- An incident moves through New, Assigned, In progress and Resolved.
- The create form saves an incident.
- Pages were checked at laptop width and at phone width.

Historical frontend handoff note: the Django views, routes and `seed_data` are now integrated.

## Files

```text
templates/
├── base.html
├── dashboard.html
├── incidents/
│   ├── incident_list.html
│   ├── incident_detail.html
│   └── incident_form.html
└── teams/
    └── team_list.html
static/
├── css/styles.css
└── js/dashboard.js
INTEGRATION.md
FRONTEND_README.md
```

## Arabic / English, team footer and light-theme logo

- **Language switch:** the button next to *Theme* ("العربية") switches the
  interface to Arabic and right-to-left; it shows *English* to switch back.
  The choice is remembered per browser (`localStorage` key `expopulse-lang`).
- **How it works:** `static/js/i18n.js` translates the text on screen in the
  browser. Django still renders English, so the backend, forms, filters, URLs
  and tests are unchanged. Text added later by the live dashboard is
  translated as it appears.
- **What is translated:** all interface text, labels and choices, monitoring
  channels, server messages, and the demo names from `seed_data` (locations,
  teams, demo incidents). Free text typed by operators or written by the
  detectors (incident descriptions) stays as written.
- **Adding a translation:** add the exact English text and its Arabic to the
  `TEXT` table at the top of `static/js/i18n.js`. Sentences that contain
  numbers or names go in `PATTERNS`.
- **Footer:** three-column footer with platform links and Vision Crew attribution (`templates/base.html`).
- **Logo:** the pulse line is dark in the light theme so it stays visible.
- **Arabic name:** in Arabic the brand reads **نبض إكسبو** ("Pulse of Expo",
  the meaning of ExpoPulse) in the logo, the browser tab and the footer.

## Live cameras page (`/live/`)

- **Live cameras** in the navigation shows every simulated CCTV stream on one
  screen (crowd, restricted area, fall), each with a LIVE / Offline badge, a
  full-screen button and the latest alert from that camera.
- Start the streams with `run_simulation.sh all` / `run_simulation.ps1 all`
  (or a single mode such as `crowd`). The page finds them in `streams/`.
- Django serves the HLS files read-only at `/live/<camera>/<file>` from the
  same origin as the dashboard, so no extra ports or CORS settings are needed.
  Only `live.m3u8`, `liveN.ts`, `liveN.m4s` and `init.mp4` are served.
- A camera counts as offline when its playlist has not been rewritten for
  20 seconds (simulation stopped). The page retries every 5 seconds.
- Playback uses the bundled `static/vendor/hls.light.min.js` (see
  `static/vendor/README.md`). The page never creates or changes incidents.
- Code: `incidents/views_live.py`, `templates/live/cameras.html`,
  `static/js/live_cameras.js`; tests in `incidents/tests_live_cameras.py`.
