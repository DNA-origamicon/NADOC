# Active atomistic and simulation visualization — 2026-09-25

This replaces the earlier ranking by computational improvability with a ranking
for active viewing features. Offline SNUPI validation and optional research
solvers are excluded. The first implementation batch covers interpolation,
live MD instance updates, and backend periodic-image preparation.

## Active-feature priorities

| Rank | User-facing feature | Work to reduce latency without reducing fidelity | This batch |
|---|---|---|---|
| 1 | Atomistic trajectory/animation interpolation (previous #6) | Calculate each atom once; reuse its position for incident bonds; write existing instance buffers without object allocation. Retain rigid cluster transforms and bond cutoffs. | Implemented |
| 2 | MD trajectory and live-view frame preparation (previous #8) | Batch per-strand periodic-image selection and atom translation. Preserve recorded intra-residue coordinates, median decisions and alignment inputs. | Implemented |
| 3 | Live MD atomistic frame updates | Remove per-atom matrix clones and per-bond vector/matrix allocation while retaining topology validation, colours, alpha and mesh identity. | Implemented |
| 4 | Animated/simulation molecular surfaces | Profile and reuse geometry/normal buffers where topology is stable; preserve vertex positions, face colours and lighting. | Implemented in [batch 2](../surface_colouring_20260926/README.md): scalar surface buffer/normal reuse |
| 5 | Atomistic simulation colouring, selection and fades | Audit duplicate repaint requests and update only changed identity/style data; preserve full selection and scalar-colour semantics. Existing identical-colour suppression must be retained. | Implemented in [batch 2](../surface_colouring_20260926/README.md): per-paint endpoint/colour caches and batched alpha writes |
| 6 | Trajectory loading, scrubbing and prefetch | Discard superseded queued scrubs; consume compact recorded frames directly; retain exact preparation/playback requests. | Implemented in [batch 3](../loading_open_20260926/README.md) |
| 7 | First-open atomistic simulation display | Construct instance matrices without per-atom/per-bond Matrix4 allocation; retain existing zero-copy binary topology decoding. | Implemented in [batch 3](../loading_open_20260926/README.md) |
| 8 | Solvent, ion and periodic-box visualization | Profile overlay preparation and frame uploads on large MD jobs; reuse coordinate/identity buffers without subsampling visible particles. | Completed in [final batch](../remaining_visualization_20260926/README.md): direct solvent matrices and reduced GPU uploads |
| 9 | Native and simulated molecular-surface generation | Reduce repeated full-volume voxel work; retain grid spacing, probe radius, envelope and per-vertex ownership. | Implemented in [surface generation audit](../surface_generation_20260926/README.md): exact vectorized sphere stamping and stable strand grouping |
| 10 | Protein attachments in simulation/assembly views | Reuse unchanged trace/ovoid geometry and separate transforms from rebuilds. Preserve trace tessellation and all picking metadata. | Completed in [final batch](../remaining_visualization_20260926/README.md): unchanged trace geometry reuse; box/ovoid caching rejected after measurement |

These priorities represent active paths and remaining investigations, not ten
measured bottlenecks. The implemented work neither changes simulation physics nor
reconstructs recorded atom positions from coarse-grained coordinates.

## Implementation

- `atomistic_renderer.js`: interpolation uses a reusable row-indexed Float64
  workspace (24 bytes/atom), retaining JS-number precision until the existing
  Float32 GPU upload. Each atom's position is evaluated once instead of again
  at each incident bond. The workspace is discarded on topology rebuild/disposal;
  hidden atomistic representations skip the coordinate work.
- `geometry_builder.js`: additional direct-buffer sphere/bond writers retain
  the original Three.js quaternion/composition math and existing clone-returning
  helpers for callers that retain matrices. The interpolation and live-update
  callers keep their respective stretched/degenerate-bond policies.
- `md_trajectory.py`: immutable topology layouts cache phosphate row batches
  grouped by strand length. `median(axis=1)` evaluates the same per-strand
  coordinate differences without padding or changed NaN/tie rules. A contiguous
  gather applies the same lattice translation to every heavy atom of the strand.
  Both current layout producers and older layouts without cached rows work.
- Exact-snapshot playback already had a direct-buffer path; it was retained.

## Paired measurements

Host: Ryzen 5 3600; baseline `0dc8b857378b077a739289f413a23cfad3e234a3`.
Synthetic scale fixtures isolate the changed operations. Render benchmarks
alternate A/B order for 31 measurements after 15 warmups, and compare all instance
matrices and colours exactly after every timed frame. Timings exclude those
comparisons. Backend medians use 15 alternating paired measurements and check
coordinate equality for every result, including the first cache-building call.

| Operation | Scale | Before | After | Speedup |
|---|---|---:|---:|---:|
| Atomistic interpolation | 30,000 atoms / 29,700 bonds | 12.64 ms | 2.90 ms | 4.36× |
| Atomistic interpolation | 150,000 atoms / 148,500 bonds | 45.05 ms | 14.96 ms | 3.01× |
| Cluster interpolation | 150,000 atoms / 148,500 bonds | 36.72 ms | 7.74 ms | 4.74× |
| Live MD coordinates | 150,000 atoms / 148,500 bonds | 41.81 ms | 22.59 ms | 1.85× |
| MD periodic-image placement | 211,280 atoms / 300 strands | 24.77 ms | 9.52 ms | 2.60× |
| MD periodic-image placement | 611,680 atoms / 1,000 strands | 78.51 ms | 31.10 ms | 2.52× |

The unchanged exact-snapshot control measured 11.30 → 11.82 ms at 150k atoms
(0.96×); no snapshot improvement is claimed. Backend cold calls including batch
cache construction were 11.58 and 36.00 ms. These are CPU update/preparation
measurements, **not end-to-end playback FPS or GPU render times**. Cluster
fixtures include bonds hidden by the existing length cutoff; compare that row
only against its matching baseline. No additional atoms, bonds, trajectory frames or surface
triangles were culled to obtain the reported improvements.

Raw data: `renderer_benchmark.json`, `md_benchmark.json`.

Reproduce within a user-opened test session:

```sh
NADOC_TEST_CONFIRM=1 scripts/test_guard.sh active-md-benchmark 1 1 -- \
  env PYTHONPATH=. uv run python scripts/benchmark_md_frame_placement.py \
  --baseline 0dc8b857378b077a739289f413a23cfad3e234a3
NADOC_TEST_CONFIRM=1 scripts/test_guard.sh active-render-benchmark 1 1 -- \
  node frontend/scripts/benchmark-atomistic-playback.mjs \
  0dc8b857378b077a739289f413a23cfad3e234a3
```

## Validation and artifact ownership

- Focused backend tests: 16 passed, covering periodic/nonperiodic axes, odd/even
  strand lengths, missing phosphate references, sparse/reordered phosphate rows,
  cached and legacy layouts, repeated frames, unchanged input arrays, existing
  atom identity tests and MD trajectory fast-frame tests.
- Final full frontend unit suite: **7,059 passed, 1 skipped** across 543 test files
  in 87.06 s, including direct-matrix equivalence, rigid cluster interpolation,
  sparse serials, weld-overlay behaviour and hidden-representation regression checks.
- Isolated Chromium app check: 1 passed in 20.1 s. Real 6hb model, 5,040 atoms,
  five instance meshes. Interpolation, snapshot and live-update images all had
  pixel hash **3154978965**, with **35,430 visible pixels**. Picking selected serial
  0 in both comparisons; instance buffers, colours and alpha were preserved.
- `just test-smart --base HEAD` selected **`FULL  (FULL suite)  [test-dedicated session OPEN]`**
  because of the existing unrelated photoproduct test edits. Result: **9,719 passed,
  25 skipped, 13 failed** in 594.27 s. Failure IDs exactly match the earlier full
  run's 13 failures, already reproduced with baseline code; none are new. No
  DEFERRED groups or unmarked test-budget violations were reported. See
  `validation.txt` and the [earlier baseline investigation](../performance_20260925/README.md).
- Browser artifact cleanup was verified: no matching document session, project
  store, saved design, Playwright test-results or report directory remained.
- Browser check uses a real 6hb×21 bp model generated in an in-memory scratch
  session. The app imports it into `__e2e__active-atomistic-playback`; frame
  movement is a synthetic rigid translation, not a production simulation.
- Before Playwright: verified no pre-existing matching workspace artifact. The
  smoke config disables session caching and runs isolated servers. The spec's
  `afterEach` closes the page, deletes the in-memory document and removes only
  its exact session/project/design paths, including on failure. Standard
  Playwright output/report cleanup remains enabled. No user design is saved.

Temporary benchmark/test logs were removed after retaining the concise numerical
results and validation summaries here. The browser fixture and benchmarks create
no production jobs; the full backend suite uses its normal test temporary paths.
