---
name: project_clash_detector
description: "Clash visualizer: red posed-backbone clashes, cyan nucleotide-ring piercing markers, separate legend counts; read-only display diagnostics."
metadata: 
  node_type: memory
  type: project
  originSessionId: bdb975a0-1d00-4602-8b89-8cd73cd1a73c
---

# Design-layer steric-clash detector (shipped 2026-07-08)

## November 2 performance follow-up (ISSUE-166)

`ring_piercing_scan.py` precomputes centroid-fan triangles and tests candidates in
bounded NumPy batches. Ring/bond order, shared-atom exclusions, search radius and
intersection tolerances remain unchanged; scalar-oracle and saved-report equality
checks qualify the optimization. Terminal-linker scan: **31.76 → 0.43 s**; entire
check **32.25 → 0.86 s** (warm read-only benchmark). A 208,000-atom platform still
takes **4.40 s**, including atom preparation; live-app latency can be higher.

The legend shows a spinner and measured bond-check percentage after **one second**.
Preparation stays at 0%; scan batches publish completed/total heavy-atom bonds.
`clash_progress.py` keeps bounded ephemeral records per document; the API client's
poller pins that document and releases/cancels obsolete work. Completion, failure,
toggle-off, geometry refresh and disposal remove the indicator. No simulation or
geometry repair runs. Evidence: `.development-artifacts/piercing-performance-20261102/`.

## November 2, 2026 — ring piercings in the clash visualizer

The **clash** view tool requests `/design/clashes?include_piercings=true`.
Existing backbone clash criteria remain unchanged. The additional `piercing`
report uses the existing `ring_piercing.model_piercings` criteria on the **same
model as the atomistic display**, including saved references, flexible display
frames and imported PDB atoms. `routes_display_geometry._display_atomistic_model`
is shared by both reads. This is design geometry, not a live simulation-frame audit.

`backend/core/piercing_display.py` packages exact bond/ring atom identities and
deduplicated involved nucleotides. Extension `ext_k`, crossover `extra_base_k` and
loop `copy_k` survive; export chain labels are not used in the overlay. At most
200 hits are returned; a further hit makes `truncated=true` and the legend reads
`200+ piercings`, never an exact all-clear/count claim.

Red glow = backbone clash; cyan wireframe diamond = base involved in a ring
piercing. Both can appear on one base. The legend shows separate counts and
definitions. One piercing can mark several bases. Native base selection retains
the usual Properties-card labels. `piercing_markers.js` owns its instanced layer;
the design renderer refreshes it with live base positions and clears it on rebuild.
Extension/loop entries resolve by canonical base key, crossover inserts by their
simulation index; coarse views use the measured native position if a bead is absent.

The overlay shows pending/failure states, discards older async responses and
repaints after display-only rebuilds. Shared views retain the colors/shapes and
both counts; old presentations without piercing counts remain readable.
This changes diagnostics only. ISSUE-163's production conversion and ISSUE-164's
long-extension molecular geometry remain deferred; no atom placement is repaired.

Latest qualification: 55 focused backend / 27 frontend; full frontend 9,545
passed / one skipped; SMART FAST 19,964 passed / 19 skipped (FULL deferred); isolated
smoke 23 passed. Actual app: S37 ›3/›2 one piercing and zero clashes in Full and
atomistic; corner six clashes / one piercing with both marker types visible.
Off clears both. Screenshots inspected then pruned; isolated workspaces removed.
Evidence: `.development-artifacts/clash-piercing-20261102/`.

The no-simulation counterpart to the MD-time NAMD declash
(`backend/core/md_protocols.py`): detects backbone collisions on a **posed**
Design with zero export/simulation. Built as a clean pure core so later
validators (e.g. a headless corner primitive) import it directly.

## Core rule — straight-vs-posed (the calibration KEYSTONE)
`backend/core/clash.py :: clash_report(design, *, threshold_nm=0.65, designed_margin_nm=2.0) -> ClashReport`

Beads are placed POSED via canonical native `design_geometry._geometry_for_design`
(cluster folds + bend/twist and authored nucleotide poses applied). A posed pair is a clash iff:
- posed distance **< threshold_nm (0.65)**  AND
- straight distance **> designed_margin_nm (2.0)** — where "straight" = the same
  design with `deformations` + `cluster_transforms` stripped (mirrors
  `get_geometry`'s straight-embed strip; keeps loop/skips/extensions so the bead
  SETS match by (helix_id, bp_index, direction, copy_k) key).

**Why this and not topological neighbor-enumeration:** designed proximity — WC
partners, covalent strand neighbors, crossover/forced-ligation partners, AND
tight lattice packing of neighbor helices — is ALL close (≤~0.5 nm) in the
straight geometry, so it's excluded automatically. A *fold* collision is ~20 nm
apart straight and only collides when posed. One criterion, no lattice-adjacency
heuristic. (User chose this over enumeration, 2026-07-08.)

**Do NOT** compare posed against raw `nucleotide_positions(h)` — that skips
`effective_helix_for_geometry` (loop/skips/extensions) so the two bead sets
diverge and clean designs over-flag. Strip via `design.model_copy(update=...)`
and route both through the canonical native geometry authority.

Calibration (`tests/test_clash.py`, fixture `tests/fixtures/corner_miter_test.nadoc`):
clean 6hb/18hb/26hb_platform_v3 → **0**; corner_miter_test → A↔B seam
pairs (cols 0–5 ↔ 9–14). The test independently enumerates native-coordinate
distances; the November 2 app check measured six pairs. Do not restore the obsolete
15-pair count from the former construction-point geometry.

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
  active CSS + `#clash-legend` (separate clash/piercing counts; green border only when both are clean). Wired in
  `view_tool_buttons.js` (`toggleClashes`/`getClashesOn` deps) + one factory init
  in `main.js` (`clashOverlay`). `client.js :: getClashes()`.
- Tests: `clash_overlay.test.js`, `piercing_markers.test.js`, shared-view roundtrip,
  backend `test_clash.py` and `test_piercing_display.py`. Native placement supersedes
  the historical 15-clash corner count; the calibration test independently enumerates
  the current native bead pairs without changing either distance threshold.

Related: [[project_cando_fem]], feedback [[feedback_display_toggle_visual_verify]].
