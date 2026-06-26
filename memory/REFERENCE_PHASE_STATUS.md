---
name: REFERENCE_PHASE_STATUS
description: All shipped NADOC phases with test counts, key implementations, and bug fixes
type: project
---

## Foundation Phases (test counts)
- Phase 0: ✅ 29/29 — foundation models
- Phase 1: ✅ 35/35 — geometry visualization
- Phase 2: ✅ 99/99 — bundle creator (caDNAno-style)
- Phase 3: ✅ 111/111 — slice plane 3D editor
- Phase 4: ✅ 164/164 — staple strand editor
- Phase 5: ✅ 192/192 — XPBD physics layer

## Scaffold Routing (2026-03-15)
- `auto_scaffold(mode="seam_line", nick_offset=7, min_end_margin=9)` — seam_line and end_to_end modes
- Path: greedy nearest-neighbor (XY distance); even-N constraint
- Nick: NOT `make_nick` — domain start/end bp adjustment
- Hotkeys [1]–[7] in Routing menu
- 24 routing tests + 21 backbone geometry tests

## 2D Unfold View (2026-03-14, merged master)
- `unfold_view.js`, `cross_section_minimap.js` — 86 pass, 1 skip

## Phase 6 — Bend/Twist Geometric Deformation (2026-03-14, merged master)
- `deformation_editor.js`, `deformation.py`, `DeformationOp` model
- See `REFERENCE_DEFORMATION_THEORY.md` for DTP-6 decisions

## Phase 7 — Loop/Skip Topology (2026-03-23)
- Loop/skip base mods; gap-aware per-helix placement; deformation bp-index bugs fixed

## Phase AA — Atomistic 3D View (2026-03-24, merged master)
- All-atom template, PDB/PSF export for NAMD, WebSocket streaming, Representation submenu
- Merged master 2026-03-25

## NAMD Complete Package Export (2026-03-25, merged master)
- "Export NAMD Package (.zip)" → one-click simulation bundle
- ZIP: PDB, PSF, namd.conf, forcefield/, scripts/, launch.sh
- GBIS implicit solvent; 2000-step min + 50000-step NVT at 310K

## XPBD Fast Physics (2026-03-24, merged master)
- Numba-accelerated XPBD solver; loop/skip mechanics; displayState.js fast overlay

## Phase S — Sequences, View Enhancements, Export (2026-03-16, merged master)
- `sequences.py`, M13mp18 scaffold; sequence overlay; loop/skip insert; sequence CSV export

## Phase SQ — Square Lattice (2026-03-19, merged master)
- 33.75°/bp twist; 4 neighbors; 23 tests
- See `REFERENCE_SQUARE_LATTICE.md`

## Phase CN — caDNAno v2 Import/Export (2026-03-22, merged master)
- `cadnano.py`; HC row step 3.375nm; stap-only fix; 23 tests

## Phase UX-1/2/3 (2026-03-24/25, merged master)
- UX-1: Overhang 3D fixes, glow, undoable group ops, lasso fix
- UX-2: Selection Filter rework; toolFilters/selectableTypes split; arc/end/loop lasso
- UX-3: Draggable end arrows; `resize_strand_ends`; inline overhangs; `_reconcile_inline_overhangs`

## FEM Structural Analysis (2026-03-27, merged master)
- Euler-Bernoulli FEM; RMSF heatmap via eigsh; WebSocket `/ws/fem`; equilibrium overlay deferred
- 275-line validation test suite
- See `REFERENCE_FEM.md`

## Cluster Rigid Transforms (2026-03-27, merged master)
- `ClusterRigidTransform` model; translate/rotate gizmo; sidebar panel; live transform fields
- `store.translateRotateActive`, `store.activeClusterId`

## Surface Representations (2026-03-28, merged master)
- VdW and SES surfaces; marching cubes; strand coloring; opacity slider
- `_resetForNewDesign` hardened; undo-across-sessions bug fixed

## scaffold-sequence-overhaul (2026-03-28, merged master)
- p7560 + p8064 scaffolds added; picker modal; SQ periodic skips; overhang sidebar permanent

## Strand Terminal Extensions + Fluorescence/FRET (2026-03-29, merged master)
- `StrandExtension` model; fluorophore beads; Fluorescence view; FRET Checker
- Förster radii: Cy3→Cy5=5.4nm, FAM→TAMRA=4.6nm, ATTO488→ATTO550=6.3nm

## refactor/phase6-feature-log (2026-03-30, merged master)
- **Phase 6 UI + Phase 7 frontend overhaul**: left sidebar (280px, collapse pill), feature log timeline with draggable playhead, checkpoint dividers, seek/truncate-on-insert, `_animateToConfig` geometry-stale fix
- **TD-1**: `auto_scaffold` 691 → 144 lines; three extracted helpers returning `list[list[Domain]]`
- **TD-4**: `backend/core/bp_indexing.py` — `get_helix_geo_bp_start`, `get_helix_bp_count`, `stored_to_global_bp`, `global_to_stored_bp`
- 429/429 tests pass

## scadnano Import (2026-04-02, merged master)
- `POST /design/import/scadnano` — square + honeycomb grids; loopouts → extra bases; extensions → StrandExtension; PhotoproductJunction for CPD round-trip
- Pre-pass: helix axis trimmed to actual strand bp ranges; empty helices skipped with warning
- Blunt end fixes: cadnano 2D ring Z = (bpStart+physicsBp)×RISE; physics posMap uses global bp_index; helix label extracts trailing int from h.id
- Expanded-spacing (Q key) arc fix: `_extArcOff` parentHelixResolver path for __ext_* endpoints
- Spreadsheet: staple sort by color + length
- 448 tests passing (11 new in test_scadnano.py)

## In Progress / Planned
- **FEM equilibrium overlay**: deferred, needs torsional pre-stress
- **Deferred UI refinements**: minor UI polish items noted by user, not yet enumerated
- **Phase 8** (Parts Library + Assembly CAD): branch `phase-8-assembly`, prior implementation reverted, awaiting re-scoping
- **Phase 9** (Checker Integrations): planned
