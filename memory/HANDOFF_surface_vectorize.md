# Handoff: fast HD molecular surface — visual-regression tests, then a vectorized build

You are continuing work on NADOC's molecular-surface display (oxDNA relaxation topic:
`memory/project_oxdna_relaxation.md` §27). Read that §27 first. Do TWO things, in order:
**(1) build surface visual-regression tests on real designs, (2) vectorize the all-atom
build** so the "High detail" (fine) surface is fast — validated by (1).

## Why (investigation results — do not re-derive, verify if you doubt)

The surface pipeline: `build_atomistic_model(design[, frame])` → `compute_surface`
(occupancy grid → morphological closing → marching cubes) → `smooth_mesh` →
`surface_to_json` / `pack_surface_bin`. Two surface flavours share it:
- **Coarse (default, FAST, SHIPPED):** `surface.cg_surface_mesh` rasterises ~2 CG
  spheres/nucleotide (backbone+base) — NO all-atom build. VoltronCore design ~1.4s.
- **Fine ("High detail"):** the full all-atom model. This is the slow one.

Profiled on VoltronCoreScad.nadoc (14774 nt, ~300k atoms), FINE path:
- `build_atomistic_model(fast_bridges=True)` = **~4–5.5s** ← the bottleneck. Breakdown:
  ~2s creating 300k `Atom` dataclass objects + Python loop; ~1.6s per-nucleotide frame
  math (37k tiny `numpy.cross` + `normalize_axis_tuple` calls — huge per-call overhead in
  `atomistic._atom_frame`); ~0.44s `apply_deformations_to_atoms`; ~0.28s geometry `_emit`.
- occupancy grid 0.6s · morphological closing **0.0s** · marching_cubes **0.3s** ·
  smooth 0.8s · `surface_to_json` 0.1s · `json.dumps` 1.4s.
- **The DESIGN fine surface ships an 81 MB JSON** (1.5M vertex floats + 3.05M face ints +
  1.5M colors). The browser `JSON.parse` of ~6M numbers + BufferGeometry build +
  `computeVertexNormals(1M faces)` + strand recolour BLOCKS the main thread — this is the
  bulk of the user-perceived "minutes", NOT the backend compute.

**Conclusions:** (a) GPU is a DEAD END — the GPU-amenable stages (grid/morphology/marching)
are already ~1s; the bottleneck is the Python build (not GPU-able) + the JSON payload. No
CuPy/PyTorch is installed anyway. (b) The two real fixes are the **vectorized build**
(5.5s→~0.7s) and, separately, **binary transfer for the design surface** (the sim overlay
surface already uses `pack_surface_bin`; `/design/surface` still returns the 81 MB JSON via
`routes_display_geometry.get_surface` → `surface_to_json`). Do the vectorized build here;
STRONGLY CONSIDER also doing the design-surface binary path (it's likely the single biggest
UX win and low-risk — mirror `display-surface-bin` + `scene/surface_bin.js` +
`atom_surface_display._ensureSurfaceData`). Flag it to the user early.

## Task 1 — surface visual-regression tests (do FIRST; they gate Task 2)

Goal: a fast, deterministic way to detect when a surface-code change VISUALLY changes the
mesh on REAL designs — so the Task-2 refactor can be proven to preserve appearance.

- New `tests/test_surface_visual_regression.py`. For a panel of REAL designs (use the
  headless builders in `tests/conftest.py` — `make_6hb_design`, `make_18hb_routed_design`,
  the routed 6hb in `test_atomistic_display_split.py`, and load
  `workspace/oxdna_jobs/154d3ea291b7/design.json` (VoltronCoreScad) if present, else skip):
  compute the FINE surface (`build_atomistic_model` → `compute_surface` → `smooth_mesh`) and
  assert stable, meaningful invariants that a VISUAL change would perturb:
  - symmetric surface-to-surface distance (both directions) between two meshes, via
    `scipy.spatial.cKDTree` — assert p99 < a small tolerance (e.g. 1.0 Å) and mean < ~0.3 Å
    when the mesh SHOULD be identical; expose this as a `surface_hausdorff(meshA, meshB)`
    helper the Task-2 tests reuse.
  - enclosed-volume (voxel count of the occupancy grid, or mesh volume via divergence
    theorem) and surface area — stable scalars that catch envelope drift.
  - vertex/face counts within a small band (marching cubes is deterministic for identical
    grids; counts shifting means the grid changed).
  - Mark `slow` + `atomistic` area (see conftest `_SLOW_MODULES` / `_slow_area_for`) — these
    build all-atom models. Keep each design small enough or relegate properly (the guard
    will flag >5s per-test; follow `.claude/skills/triage-slow-tests/SKILL.md`).
- Also pin the **coarse-vs-fine deviation** as a documented characterization test (currently
  ~2.8 Å mean on VoltronCore) so a future coarse-surface tweak is caught.
- These tests must be able to go RED: temporarily perturb `CG_BEAD_RADIUS_NM` or a grid
  spacing and confirm the distance/volume assertions fire, then revert.

## Task 2 — vectorize the fine-surface build

Goal: produce the all-atom (or surface-atom) POSITIONS as batched numpy, eliminating the
300k `Atom`-object creation and the per-nucleotide `numpy.cross`/`normalize` overhead.

Approach (pick the lower-risk that hits the target; the surface only needs positions +
per-atom element radius + per-atom strand_id for colouring — NOT bonds, names, seq_num):
- Preferred: a NEW `surface_atom_cloud(design[, frame]) -> (positions Nx3 float32, radii N,
  strand_ids N)` in `backend/core/` that:
  1. Computes per-nucleotide `(origin, R)` for ALL nucleotides in a BATCH — vectorise the
     `_atom_frame` basis math (cross/normalise over the whole `(N,3)` stack at once instead
     of 14774 scalar calls). Reuse the axis-derived path + the ssDNA a1/a3 rigid-frame
     override (`oxdna_health._ssdna_frame_override`) + deformation fold, matching
     `build_display_model` to tolerance (Task-1 tests enforce this).
  2. Batch-stamps template atoms: for each `(residue, direction)` template (fixed local
     coords from `_SUGAR`/`BASE_TEMPLATES`), `world = origin[:,None,:] + einsum('nij,taj->ntai'...)`
     — one big matmul, not a Python per-atom loop. Skip backbone closure + bridge minimisers
     (irrelevant to a VdW envelope; `close_backbone=False` already).
  3. Returns numpy arrays; feed them to a `compute_surface`-that-accepts-arrays (add an
     array entry point, or synthesise lightweight atoms — but avoid 300k objects).
- Wire `detail='fine'` (`oxdna_health.frame_surface_json`, `routes_display_geometry.get_surface`)
  to this fast path. Keep the exact-old path behind a flag if you can't reach tolerance.
- Target: VoltronCore fine build 4.2s → <1s; whole fine surface <3s backend.
- VALIDATE with Task-1: the vectorized surface must be within tolerance (≤~1 Å p99) of the
  current fine surface on every panel design. If it can't, the vectorization changed
  geometry — investigate rather than loosening the tolerance.

## Guardrails (from CLAUDE.md — non-negotiable)
- DNA topology/geometry is "ask first": the frame math (a1/a2/a3 basis, `_PHASE_*`
  constants) is locked — reproduce it, don't re-derive. If the vectorized frame diverges,
  STOP and ask, don't hand-tune constants.
- `just test-smart` after every backend change (cite decision + pass count; heavy atomistic
  tests DEFER — that's correct). `just test-frontend` for any JS. Exercise in the running
  app before claiming done (surface is a visual feature — `NOT VERIFIED IN APP` otherwise).
- Concurrent sessions may share the tree: never `git stash/reset/restore/checkout`; forbid
  git in any subagent prompt.
- Don't touch the STL-export route's model build (it needs exact geometry, not fast_bridges).

## Key files
- `backend/core/surface.py` — `compute_surface`, `cg_surface_mesh`, `make_cg_bead`,
  `adaptive_grid_spacing`, `smooth_mesh`, `surface_to_json`, `_build_occupancy_grid`.
- `backend/core/atomistic.py` — `build_atomistic_model` (the slow build), `_atom_frame`
  (~553), `_SUGAR`/`BASE_TEMPLATES`, `VDW_RADIUS`.
- `backend/core/oxdna_health.py` — `frame_surface_json` (detail branch), `build_display_model`,
  `_cg_beads_from_frame`, `_ssdna_frame_override`, `pack_surface_bin`.
- `backend/api/routes_display_geometry.py::get_surface` (design surface, detail param, 81MB
  JSON — binary candidate).
- `backend/api/routes_oxdna.py` — `display-surface` / `display-surface-bin`, `OxdnaSurfaceBody.detail`.
- Frontend: `scene/surface_bin.js`, `ui/oxdna_display.js` (`_relaxedSurfaceMesh`),
  `scene/atom_surface_display.js` (`_ensureSurfaceData` design fetch, `getSurfaceParams`,
  `_surfaceDetail`, `cb-surface-highdetail`).
