---
name: project_clash_detector
description: "Design-layer steric-clash detector — pure clash_report core + GET /design/clashes + \"clash\" view-tool overlay. Straight-vs-posed exclusion."
metadata: 
  node_type: memory
  type: project
  originSessionId: bdb975a0-1d00-4602-8b89-8cd73cd1a73c
---

# Design-layer steric-clash detector (shipped 2026-07-08)

The no-simulation counterpart to the MD-time NAMD declash
(`backend/core/md_protocols.py`): detects backbone collisions on a **posed**
Design with zero export/simulation. Built as a clean pure core so later
validators (e.g. a headless corner primitive) import it directly.

## Core rule — straight-vs-posed (the calibration KEYSTONE)
`backend/core/clash.py :: clash_report(design, *, threshold_nm=0.65, designed_margin_nm=2.0) -> ClashReport`

Beads are placed POSED via `deformation.deformed_nucleotide_positions(helix, design)`
(cluster folds + bend/twist applied). A posed pair is a clash iff:
- posed distance **< threshold_nm (0.65)**  AND
- straight distance **> designed_margin_nm (2.0)** — where "straight" = the same
  design with `deformations` + `cluster_transforms` stripped (mirrors
  `get_geometry`'s straight-embed strip; keeps loop/skips/extensions so the bead
  SETS match by (helix_id, bp_index, direction) key).

**Why this and not topological neighbor-enumeration:** designed proximity — WC
partners, covalent strand neighbors, crossover/forced-ligation partners, AND
tight lattice packing of neighbor helices — is ALL close (≤~0.5 nm) in the
straight geometry, so it's excluded automatically. A *fold* collision is ~20 nm
apart straight and only collides when posed. One criterion, no lattice-adjacency
heuristic. (User chose this over enumeration, 2026-07-08.)

**Do NOT** compare posed against raw `nucleotide_positions(h)` — that skips
`effective_helix_for_geometry` (loop/skips/extensions) so the two bead sets
diverge and clean designs over-flag. Strip via `design.model_copy(update=...)`
and route both through `deformed_nucleotide_positions`.

Calibration pins (`tests/test_clash.py`, fixture `tests/fixtures/corner_miter_test.nadoc`):
clean 6hb/18hb/26hb_platform_v3 → **0**; corner_miter_test → **15** A↔B seam
pairs (cols 0–5 ↔ 9–14), min ~0.28 nm.

## Endpoint
`GET /design/clashes` in `backend/api/routes_display_geometry.py` (query
`threshold_nm`, `designed_margin_nm`). Read-only; `report.to_dict()` →
`{clashes:[{a,b,distance_nm}], count, threshold_nm, designed_margin_nm}`, each
side `{helix_id, bp_index, direction, position:[x,y,z]}`, nearest-first.

## Frontend (module-first)
- `frontend/src/scene/clash_overlay.js` — `initClashOverlay({store,designRenderer,api})`
  → `{toggle, refresh, clear, isOn}`. Pure `clashEntriesFor(clashes, backboneEntries)`
  maps pair sides → backbone entries. Re-fetches on `currentGeometry` change while on.
- Red glow layer `_clashGlowLayer` (`0xff2b2b`, name `'clashGlow'`) in
  `design_renderer.js` — mirrors the undefined/anchor glows; `setClashHighlight` /
  `clearClashHighlight` / `clashGlowCount`.
- `"clash"` vt-btn in `index.html` (after overhangNames, before expanded) + red
  active CSS + `#clash-legend` count badge (green when 0). Wired in
  `view_tool_buttons.js` (`toggleClashes`/`getClashesOn` deps) + one factory init
  in `main.js` (`clashOverlay`). `client.js :: getClashes()`.
- Tests: `clash_overlay.test.js` (11), backend `test_clash.py` (6). Live-verified
  in app on corner_miter (15 clashes glowing red at the fold seam; off clears).

Related: [[project_cando_fem]], feedback [[feedback_display_toggle_visual_verify]].
