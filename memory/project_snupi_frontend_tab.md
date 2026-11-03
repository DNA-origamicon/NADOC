---
name: snupi-frontend-tab
description: Build prompt + architecture map for the frontend SNUPI structure-prediction engine tab (P5 of the SNUPI mimic). Backend ready via predict_shape(material="snupi").
metadata:
  node_type: memory
  type: project
---

# SNUPI frontend engine tab — fresh-session build brief (P5)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## Result visualization guards (2026-09-28)

Large static jobs now use the shared compact FEM renderer and guarded metrics
factory through SNUPI adapters. Deviation/cylinder preparation runs off the API
event loop. All dynamics playback uses indexed, bounded single-frame requests and
zoom-adaptive points with GPU-buffer reuse, cancellation and backpressure; it no
longer loads the full trajectory into the browser. Engine changes release active
views and pending loads so hidden playback cannot continue. Coordinates remain unchanged;
trajectory points omit orientations/slabs. See [audit](../docs/audits/snupi_visualization_guards_20260928.md)
for scale-fixture provenance, validation and manual visual-quality debt.

<a id="-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-path"></a>
- [✅ SHIPPED 2026-07-11 — first-class SNUPI engine tab (separate-tab path)](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-path)

<a id="-2026-07-13--solve-now-runs-in-a-detached-subprocess-survives-uvicorn---reload"></a>
- [⚙ 2026-07-13 — solve now runs in a DETACHED subprocess (survives `uvicorn --reload`)](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#-2026-07-13--solve-now-runs-in-a-detached-subprocess-survives-uvicorn---reload)

<a id="anchors--e-fields--surfaces--the-investigation-deliverable"></a>
- [Anchors + E-fields + surfaces — the investigation deliverable](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#anchors--e-fields--surfaces--the-investigation-deliverable)

<a id="the-prompt-paste-into-the-fresh-session"></a>
- [THE PROMPT (paste into the fresh session)](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#the-prompt-paste-into-the-fresh-session)

<a id="architecture-map-grounded-from-a-read-only-sweep-2026-07-11"></a>
- [Architecture map (grounded, from a read-only sweep 2026-07-11)](details/project_snupi_frontend_tab/02-architecture-map-grounded-from-a-read-only-sweep-2026-07-11.md#architecture-map-grounded-from-a-read-only-sweep-2026-07-11)

## Notes
- Module-first: new logic in `snupi_*` modules; `main.js` gets imports + init + thin wiring only.
- `predict_shape` returns DISPLAY-ONLY positions/RMSF (Physical layer) — never write topology.
- Related heads: [[snupi-mimic]] (backend/verdict), simulate_panel_overhaul, cando_fem, md_viz_tools,
  md_engines_panel, mrdna_panel (clean clone precedent).
