# Paris lift & escalator status snapshots

Real, publicly available equipment-status records used by
`python manage.py monitor_equipment_feed --replay ...`.

| | |
|---|---|
| Dataset | Ascenseurs / Escalators - Télé-surveillance temps réel |
| Publisher | Ville de Paris — Direction Constructions Publiques et Architecture |
| Source portal | https://opendata.paris.fr/explore/dataset/ascenseurs-escalators-tele-surveillance-temps-reel/ |
| Mirror | https://www.data.gouv.fr/datasets/ascenseurs-escalators-tele-surveillance-temps-reel |
| Upstream system | GETRALINE remote monitoring; each device pushes its status changes |
| Licence | Open Database License (ODbL) — attribute "Ville de Paris" when reusing |

## Files

| File | Downloaded | Rows | SHA-256 |
|---|---|---|---|
| `paris_lifts_snapshot_2026-10-14.csv` | 2026-10-14 (CSV export, `;` separated, UTF-8 with BOM) | 33 | `32fa7973f353ab44c00e4a27379d11ecf5f4d52f1595869d9bcf3ed2f7a92a5a` |

The file is stored **unmodified**, exactly as downloaded. Contents of the
2026-10-14 snapshot: 12 devices "En fonctionnement" (working), 13 "En panne"
(out of order), 8 "Non télé-surveillé" (not remotely monitored). The newest
status change in it is 2026-10-14T16:59:02Z.

## What the data does and does not contain

- One row per device: identifier, site, address, device kind, current status,
  and the time that status was last pushed (`Horodatage statut`).
- **No sensor measurements and no fault codes.** "En panne" says a device is
  unavailable, not why. ExpoPulse therefore reports the generic
  `OUT_OF_SERVICE` code and never invents a mechanical cause.
- A snapshot is a point in time, not a history. To replay real transitions
  (working → out of order → working), collect several snapshots with
  `monitor_equipment_feed --live --save-snapshots data/equipment/paris/` and
  replay them in order.

## Adding a new snapshot

1. Download the CSV from the portal (Export → CSV) or the data.gouv.fr link above,
   or let `--live --save-snapshots` save it for you.
2. Keep the file unchanged and name it `paris_lifts_snapshot_<date>.csv`.
3. Add a row to the table above with the download date, row count and
   `sha256sum` (PowerShell: `Get-FileHash <file>`).
