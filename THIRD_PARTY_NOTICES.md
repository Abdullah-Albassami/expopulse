# Copyright and third-party licensing

Copyright © 2026 Vision Crew contributors.

The original ExpoPulse project source code is offered under the **GNU Affero General Public License, version 3.0 (AGPL-3.0)**. See [LICENSE](LICENSE). This statement applies only to materials that Vision Crew contributors have the right to license; it does **not** relicense third-party components, videos, datasets, or model weights.

## Third-party components and data

| Component | Licensing information | Reference |
|---|---|---|
| Ultralytics YOLO software and pretrained model weights | AGPL-3.0, or a separately obtained Ultralytics Enterprise license, subject to applicable terms | https://www.ultralytics.com/license |
| Bundled hls.js player `static/vendor/hls.light.min.js` | Apache License 2.0; retain upstream notices | https://github.com/video-dev/hls.js |
| Paris Open Data equipment snapshot `data/equipment/paris/paris_lifts_snapshot_2026-10-14.csv` | Open Database License (ODbL); credit **Ville de Paris** | https://opendata.paris.fr/explore/dataset/ascenseurs-escalators-tele-surveillance-temps-reel/ |
| Demo videos under `footage/` | Separate permissions from original footage licensors apply; project AGPL does not grant redistribution rights to these videos | See upstream sources and usage terms for each file |

## Notes for reuse

- A public repository is not the same as unrestricted commercial deployment. Review Ultralytics' AGPL / Enterprise obligations before incorporating YOLO into a larger or closed-source product.
- The upstream hls.js Apache-2.0 terms and notices remain applicable; see [static/vendor/README.md](static/vendor/README.md).
- Dataset attribution is documented in [data/equipment/paris/README.md](data/equipment/paris/README.md).
- **Before publishing:** confirm the redistribution rights and attribution requirements for all recorded videos under `footage/`; if permission cannot be verified, remove the affected asset from the public distribution while retaining a download/setup instruction.

Licenses grant permissions only for work the grantor owns or is authorized to license. All contributor rights must be respected.
