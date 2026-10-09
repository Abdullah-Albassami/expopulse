# ExpoPulse Demo Scenario

1. Run `python manage.py migrate` on a fresh database.
2. Run `python manage.py seed_data`.
3. Open the dashboard and show `Medical Emergency` in Zone C.
4. Assign the suggested `Medical Team 1`; its status becomes Busy.
5. Move the incident through Assigned and In Progress, then resolve it.
6. Show that Medical Team 1 is Available again.
7. Show `Heavy Crowd at Gate 4` and `Visitor Congestion at Gate 4`.
8. Point out that the second incident is linked as a possible duplicate.
9. Assign `Security Team 1`, move the incident to In Progress, and resolve it.

Expected highlights: same-location team selection, team availability changes, and duplicate-ready demo data.
