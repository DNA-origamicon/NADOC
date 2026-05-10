# Archive — XPBD physics + FEM solver (derelict, 2026-05-10)

These two features were prototyped, partially implemented, and never reached "as-intended" working state. Archived here to preserve the implementations as a reference; **not** part of the live codebase.

## What was here

### Backend physics (`backend/physics/`)
- `fem_solver.py` (505 LOC) — finite-element static-equilibrium + RMSF solver. Beam-FEM model with rotational + translational DOFs per node. Pure-math helpers (`_beam_stiffness_local`, `_transform_to_global`) had decent tests; integration orchestrators (`build_fem_mesh`, `assemble_global_stiffness`, `solve_equilibrium`, `compute_rmsf`, `deformed_positions`) had recent test backfills (Pass 9-C + Pass 10-E) but the underlying physics never produced reliable results — calibration of beam-element stiffness against B-DNA was not converged, and the RMSF outputs did not match published references.
- `xpbd.py` (634 LOC) — XPBD (Extended Position-Based Dynamics) solver for live constraint relaxation. Slow and non-converging on representative designs.
- `xpbd_fast.py` (799 LOC) — accelerated XPBD variant. Faster but had `Crossover` model divergence (read removed `xover.strand_a_id` / `domain_a_index` attributes; never updated to current `half_a` / `half_b` model). See REFACTOR_AUDIT.md Findings #32, #33 + precondition #25.

### Tests (`tests/`)
- `test_xpbd.py` (404 LOC)
- `test_xpbd_fast.py` (483 LOC)
- `test_fem_solver_math.py` (328 LOC) — Pass 9-C pure-math floor (helpers fully covered)
- `test_fem_solver_integration.py` (532 LOC) — Pass 10-E orchestrator backfill (87% file coverage; many tests required `_patch_crossover_bases` workaround for the model divergence)
- `test_fem_validation.py` (274 LOC)

### Frontend (`frontend/src/physics/`)
- `displayState.js` (269 LOC) — fast-mode helix-segment particle overlay (XPBD live viewer)
- `fem_client.js` (67 LOC) — FEM WebSocket client
- `physics_client.js` (215 LOC) — XPBD WebSocket client

(`mrdna_relax_client.js` is NOT here — mrdna is a working external tool, kept live.)

## What was deleted (not archived; recoverable from git history before commit pruning Pass 10/11)

- `backend/api/ws.py` routes: `/ws/physics`, `/ws/physics/fast`, `/ws/fem`
- `backend/api/ws.py` imports of the archived modules
- `tests/test_ws_helpers.py` — 7 of 14 tests (physics + fem WebSocket tests; md-run tests preserved)
- `frontend/index.html` — `<div id="physics-section">` and `<div id="fem-section">` panels
- `frontend/src/main.js` — physics/FEM client init + key handlers + status wiring
- `frontend/src/state/store.js` — `physicsMode`, `physicsPositions`, `femMode`, `femPositions`, `femRmsf`, `femStatus`, `femStats` state slices
- `frontend/src/scene/helix_renderer.js` — `applyPhysicsPositions` method + scratch vectors
- `frontend/src/scene/design_renderer.js` — `physicsPositions` store reactor

## Why archived rather than deleted

Both implementations represent design effort and contain readable algorithmic structure that may inform future physics work (e.g. a from-scratch FEM rewrite once beam parameters are recalibrated, or a different relaxation approach). Keeping the source visible makes intent recoverable without spelunking commits. Tests document the intended behaviors that were never reliably achieved.

## Re-activation note (if this gets revived)

If a future pass intends to revive xpbd or FEM:

1. Don't directly restore from this archive — the model-divergence bugs remain (`xover.strand_a_id` / `xover.domain_a_index` reads in xpbd_fast.py were never updated; the `Crossover` model now exposes `half_a` / `half_b` only — see REFACTOR_AUDIT.md precondition #25).
2. The FEM beam parameters were never calibrated against B-DNA stiffness measurements; revival should start from a beam-parameter calibration pass against published references.
3. The XPBD constraint set assumed an older `Design` shape; check `Design` model + `Crossover` model evolution since `a6df304` (cadnano overhaul) before relying on any constraint construction.
4. The `_patch_crossover_bases` test workaround in the archived `test_fem_solver_integration.py` is a `__dict__.setdefault("crossover_bases", [])` monkey-patch — production code reading `crossover_bases` was already removed by the MD-pipeline refactor, so the workaround is no-op overhead today.

## Audit links

- REFACTOR_AUDIT.md Findings #16, #28, #32, #33 — coverage backfills + apparent-bug flags
- REFACTOR_AUDIT.md precondition #25 — model-divergence escalation (now obsolete; archived modules removed)
- `memory/REFERENCE_FEM.md` — historical FEM theory notes
