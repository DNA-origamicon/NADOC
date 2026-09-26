# Computational efficiency audit — 2026-09-25

For the current **active-feature priorities**, see the [visualization follow-up](../active_visualization_20260925/README.md). The ranking below includes offline research utilities and is retained as the original computational audit.

The two implemented changes are sparse FEM stiffness assembly and generalized
normal-mode correlation-map construction. Both preserve the existing physical
model. Rankings below reflect estimated **removable cost and implementation
confidence**, not a claim that every operation was profiled or that the largest
wall-time consumer is the easiest to improve.

## Top 10 opportunities

| Rank | Operation and evidence | Estimated opportunity / next refactor | Status |
|---|---|---|---|
| 1 | FEM stiffness assembly, `backend/physics/fem_solver.py::assemble_global_stiffness`: four sparse slice updates per beam, scalar updates per spring/rigid link | Very high: collect nonzero contributions and reduce shared-node entries once. Benefits CanDo/SNUPI setup and repeated assembly. | Implemented; 32–59× assembly speedup in benchmark panel. |
| 2 | Generalized correlation maps, `fem_solver.py::compute_generalized_correlation_matrix`: Python loop over every node pair with a 6×6 determinant each | High: batch covariance blocks and determinants with bounded temporary memory. Used by `scripts/snupi_reference_compare.py`, not the interactive render loop. | Implemented; 6.6× post-NMA speedup. |
| 3 | Repeated normal-mode solves in reference analysis: `scripts/snupi_reference_compare.py` separately requests Pearson, generalized correlation, persistence length and modes | High when several observables are requested together: compute one local mode basis and pass it to the consumers. Avoid a global cache with invalidation hazards. | Source audit only; no timing claim. |
| 4 | Generalized hydrodynamic mobility, `backend/physics/snupi_hydrodynamics.py::rpy_mobility_generalized`: pairwise Python block construction, followed by dense factorization | High assembly potential, but dense factorization remains cubic. Batch pair tensors within the existing model; retain positive-definiteness/overlap checks and existing coarse model. | Source audit only; physical validation would be needed. |
| 5 | Corotational Newton solve, `backend/physics/snupi_corotational.py::element_force_tangent` and `solve_corotational`: 12 finite-difference perturbations per element and scalar sparse insertion | High but higher risk: batch sparse assembly first, then consider a validated analytic tangent. This task's linear-assembly change does not optimize this separate solver. | Source audit only. |
| 6 | Atomistic trajectory playback, `frontend/src/scene/atomistic_renderer.js::applyPositionLerp`: per-atom transforms and per-bond cylinder transforms/uploads on each frame | Medium/high at large atom counts: direct typed-array instance writes and dirty-range uploads, then evaluate GPU coordinate interpolation. Existing resident geometry and frame-offset caches must be retained. | Source audit only; needs browser frame-time profiling and picking/bond regression coverage. |
| 7 | Surface updates, `frontend/src/scene/surface_renderer.js`: repeated normal calculation and face-expanded geometry | Medium/high for large meshes: reuse topology/buffers for stable meshes and move normal calculation off the UI thread. Preserve face-level colour ownership and alpha. | Source audit only; needs browser profiling. |
| 8 | MD frame preparation, `backend/core/md_trajectory.py::_direct_heavy_pre_positions`: per-segment medians and scattered atom translations | Medium: batch lattice-shift application and improve initial group construction; existing cached row lists already eliminate repeated whole-array masks. Recorded coordinates and periodic-image semantics must stay exact. | Source audit only. |
| 9 | Fine/coarse surface voxel morphology, `backend/core/surface.py::_build_occupancy_grid` / `compute_surface_from_cloud`: full-volume grids and dilation per radius | Medium, grid-size dependent: spatially crop radius groups or benchmark exact distance-transform morphology for large kernels. Keep voxel origin, padding, and ownership unchanged. Binary transfer and vectorized atom-cloud generation already exist. | Source audit only; historical notes describing those two shipped improvements as absent are stale. |
| 10 | Protein trace rebuilds, `frontend/src/scene/protein_trace_renderer.js::rebuild`: dispose/recreate tube geometry, with six axial samples per C-alpha interval | Medium for large attachments: reuse unchanged chain geometry, separate colour/transform updates from geometry changes, and profile tessellation level. | Source audit only; needs browser evidence. |

Multicolour printable surfaces were also experimentally evaluated. Replacing
per-group full-volume scans with a single bounding-box scan was exact, but only
1.17× faster at 12 groups (0.111 → 0.095 s). A synthetic 100-group stress case was
2.33× faster (1.447 → 0.620 s), whereas the current export path uses at most four
colour groups. That candidate was removed rather than ranked above the two
stronger opportunities. No surface implementation change remains.

## Measurements

Baseline: `0dc8b857378b077a739289f413a23cfad3e234a3`.
AMD Ryzen 5 3600, Python 3.12.3; median of three calls per variant on this host.
The guarded run used the user's open test session. No production simulations
were launched. Fixture builders use isolated scratch sessions.

| Workload | Before | After | Speedup |
|---|---:|---:|---:|
| 6hb, 84 bp, 504 nodes, CanDo assembly | 0.756 s | 0.0129 s | 58.9× |
| Same, SNUPI assembly | 0.727 s | 0.0194 s | 37.5× |
| 18hb, 196 bp, 3,528 nodes, CanDo assembly | 4.979 s | 0.0939 s | 53.0× |
| Same, SNUPI assembly | 5.148 s | 0.1606 s | 32.1× |
| Generalized correlation, 504 nodes × 200 modes | 1.454 s | 0.218 s | 6.7× |
| Generalized correlation, 1,500 nodes × 200 modes | 13.699 s | 2.085 s | 6.6× |

Assembly fixtures are geometric bundles, not full routed simulation campaigns.
The matrix and force outputs were exactly equal in these A/B cases. Shared-node,
spring and crossover assembly additionally have focused superposition tests and
existing routed-design tests. Correlation timings use identical seeded synthetic
modes to isolate post-eigensolve cost; output matrices were exactly equal. They
exclude the eigensolve and are **not whole-analysis speedups or measured FPS gains**.
Timing noise, production topology and matrix conditioning can change these ratios.

Reproduction (requires a user-opened test session):

```sh
NADOC_TEST_CONFIRM=1 scripts/test_guard.sh performance-audit 1 1 -- \
  env PYTHONPATH=. uv run python scripts/benchmark_performance_audit.py \
  --baseline 0dc8b857378b077a739289f413a23cfad3e234a3
```

The harness loads the two baseline functions from Git without checking out or
modifying the worktree. Raw concise results are in `benchmark.json`.

## Implementation and limits

- Stiffness assembly collects nonzero COO entries, sums them on CSR conversion,
  drops exact zeros, and returns LIL to preserve the boundary-condition editing
  API. Constitutive matrices, element frames, crossover laws, and force values
  are unchanged. Temporary triplet capacity is linear in element/link count
  (at most 3,456 bytes per beam/link and 576 bytes per spring, before sparse
  conversion); this trades bounded linear scratch memory for much less Python
  and sparse-object overhead. Floating-point summation order can differ on
  general meshes, so equivalence tests use numerical tolerances where needed.
- Correlation determinants use chunks of at most 2,048 node pairs. Joint-matrix
  scratch space is at most 576 KiB per chunk, plus covariance/result scratch.
  The output still requires 8N² bytes. The formula, diagonal regularizer,
  determinant floors, symmetry and unit diagonal are unchanged.
- No frontend or molecular placement changes. No claim of browser interaction
  or visual frame-rate validation is made.

## Validation

- Focused numerical tests: **10 passed** in 3.68 s (assembly superposition,
  editable sparse type, empty mesh, rank-deficient/zero-displacement modes,
  chunk boundaries, symmetry, range, and failed-NMA fallback).
- Ruff checks on changed Python files: passed.
- `just test-smart` decision: **`FULL  (FULL suite)  [test-dedicated session OPEN]`**.
  **9,713 passed, 25 skipped, 13 failed** in 601.07 s. No DEFERRED groups were
  reported, and there were no unmarked per-test budget violations. The full-pass
  watermark was not advanced because the suite was not green.
- All 13 failures were rerun serially with **both original FEM functions** loaded
  in memory from the baseline revision; **all 13 reproduced** (15.99 s). Source
  files were not replaced during that check. Thus these failures are independent
  of the two refactors; they remain unresolved outside this task:
  - mrDNA synthetic round trip: mean error 0.691 nm exceeds 0.10 nm.
  - VoltronCore fine surface: area differs from its baseline by 5.35%, above 5%.
  - Mock chain completion: remains `running` when `completed` is expected.
  - PEG live worker, CPU and CUDA: bonded-neighbour separation rejected by oxDNA.
  - Seven photoproduct review tests: required archived review packet is missing.
  - CPD preview snapshot: coordinate comparison fails at the existing tolerance.
  Exact test names and baseline recheck evidence are in `validation.txt`.

The audit retained only code, numerical tests, and this small report/result set.
The benchmark used in-memory scratch documents with failure-safe disposal and
created no user workspace designs or jobs. Temporary baseline copies and logs
were removed; pytest's own temporary test outputs remain under its normal control.
