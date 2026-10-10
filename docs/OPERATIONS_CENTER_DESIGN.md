# ExpoPulse Operations Center — Operator Workflow and Design Rationale

## Scope and references

ExpoPulse is a **demonstration operations center**, not a certified emergency dispatch system.
The design is informed by:
- FEMA NIMS EOC Toolkit: https://preptoolkit.fema.gov/web/nims-toolkit/eoc
- FEMA EOC functions and information sharing: https://training.fema.gov/programs/nims-ics-position-specific/eoctraining.aspx
- USFA/NIMS resource management: https://www.usfa.fema.gov/a-z/nims/managing-resources.html

Relevant principles: shared operating picture, timely incident triage, clear provenance, resource availability, coordination, and response status.

## End-to-end workflow

1. Automated CCTV or equipment monitoring **detects a candidate event**; an operator can also submit a manual report.
2. Backend creates an incident, calculates priority and checks possible duplicates.
3. Appropriate team is assigned when the monitoring adapter supports it and an eligible available team exists. Otherwise the operator handles assignment on the incident detail page.
4. Operator validates the alert, moves Assigned -> In Progress -> Resolved, and releases the team only upon manual resolution.
5. Dashboard polls and updates incident counts/status. Detector clear/recovery **does not imply operator resolution**.

## Monitoring taxonomy

| Monitoring channel | General incident type | Team class |
|---|---|---|
| CCTV Crowd Detection | Crowding | Security |
| CCTV Fall Detection | Medical | Medical |
| Elevator & Escalator Fault Monitoring | Maintenance | Maintenance |
| CCTV Restricted-Area Detection | Security | Security |

The monitoring channel is derived for presentation from source and current title conventions. No migration or changes to established detector identifiers. The fall-detector module must be integrated and tested separately; the label alone does **not** implement fall recognition.

## Operator interface

- Dashboard: open severity, backlog, status, response capacity; live polling and incident queue
- Incident list: filters and search
- Incident detail: evidence in description, origin, urgency, assigned team, workflow transitions, duplicate warning
- Manual incident report: explicit manual provenance, backend priority/duplicate calculation
- Teams: base location distinct from incident response destination, team-type responsibilities shown

## Operational limitations and next-stage enhancements

This is intentionally an MVP, **not** an incident-command compliant system. It does not yet offer:
- Signed-in operator identities, role-based approval and immutable audit trail
- Multisite geographic dispatch, road travel times or GPS-based "nearest team"
- Durable equipment telemetry history, CCTV evidence storage, acknowledgement timers or shift handover logs
- Multi-process-safe atomic resource allocation / uniqueness guarantees
- AI detector confidence/evidence verification before a safety-critical dispatch
- Sensor health indicators and automatic escalation for stalled incidents

These features should be prioritized if deployed beyond a controlled capstone demonstration.

## Validation

```bash
python -m pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test incidents
```

Test the form manually, confirm team base/destination display, and leave the existing live detector scenarios unchanged.
