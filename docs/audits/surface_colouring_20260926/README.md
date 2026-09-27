# Active visualization opportunities 4 and 5 — 2026-09-26

Implemented the next two entries in the [active-feature ranking](../active_visualization_20260925/README.md): simulation molecular-surface updates, and atomistic colouring/selection/fades.

## Changes

- Surface simulation updates reuse compatible position, index, normal, colour and alpha buffers. Scalar/RMSF payloads still refresh baked colours. Coordinates and connectivity are compared at GPU precision, including arrays mutated in place; changed geometry recomputes normals with the same Three.js routine. Intervening ordinary animation invalidates the normal cache through attribute versions. Picking bounds are invalidated when geometry changes. Incompatible geometry is disposed, while the material survives, including physical/photo materials.
- Atomistic repaints resolve each endpoint once and reuse the result for incident bonds. Each distinct colour passes through the same Three.js sRGB conversion once per paint. Alpha uploads are marked once per mesh, retaining the minimum endpoint alpha for each bond. Caches expire after every repaint, so mutable colour/fade maps are re-read. Scalar, cluster, selection and fallback precedence are unchanged. Temporary row caches use 9 bytes/atom, or 18 bytes/atom with fades, plus the distinct-colour map.
- Mesh resolution, molecular positions, tessellation, colormaps, shader precision and topology are unchanged. The existing non-scalar interpolation normal policy is unchanged. This batch optimizes surface refresh/rebuild work, especially scalar maps; it does not accelerate backend surface generation or claim every surface animation path is faster.

## Paired CPU measurements

Baseline: `0dc8b857378b077a739289f413a23cfad3e234a3`, loaded read-only from Git. The colour and surface functions were unchanged by the preceding optimization batch. Synthetic fixtures; 10 warmups, 21 alternating paired measurements; medians exclude exact-buffer assertions. Surface motion moves the entire mesh, with changing normals. Browser coverage additionally uses binary/typed surface payloads.

| Operation | Scale | Before | After | Speedup |
|---|---|---:|---:|---:|
| CPK selection repaint | 150,000 atoms / 148,500 bonds | 55.71 ms | 11.24 ms | 4.96× |
| Cluster colours + fades | 150,000 atoms / 148,500 bonds | 318.99 ms | 158.94 ms | 2.01× |
| Scalar selection + fades | 150,000 atoms / 148,500 bonds | 405.61 ms | 202.70 ms | 2.00× |
| Repeated scalar surface | 160,000 vertices / 318,402 faces | 86.73 ms | 5.69 ms | 15.26× |
| Scalar surface recolouring | 160,000 vertices / 318,402 faces | 88.41 ms | 5.76 ms | 15.36× |
| Moving scalar surface | 160,000 vertices / 318,402 faces | 87.73 ms | 35.21 ms | 2.49× |

These are CPU operation timings, not end-to-end playback FPS. Every measured pair has exactly equal position/normal/index/colour buffers for surfaces, and matrix/colour/alpha buffers for atoms. Full results, including the smaller fixtures, are in [benchmark.json](benchmark.json).

Reproduction (large benchmarks require a user-opened test session):

```sh
NADOC_TEST_CONFIRM=1 scripts/test_guard.sh surface-colouring-benchmark 1 1 -- node frontend/scripts/benchmark-surface-colouring.mjs 0dc8b857378b077a739289f413a23cfad3e234a3
just test-frontend
cd frontend && npx playwright test --config playwright.smoke.config.js surface_colouring_performance.spec.js
```

The final surface rows were rerun with `--surface-only` after extending motion to all vertices; atom rows retain the earlier paired measurements.

## Running-app verification

The isolated Playwright check loads a real six-helix, 21-bp design and requests its
atomistic model and binary molecular surface through the app API: 5,040 atoms,
15,537 vertices, 31,118 faces. It renders original and optimized modules in the
same scene/camera. All 18 paired states have identical pixel hashes and matching
picking: six each for sphere and impostor representations (cluster colours,
selection, scalar overlay, selection clear, mutable maps, fade clear), and three
each for Phong and physical surface materials (scalar frame, colour mutation,
coordinate mutation). Both surface materials carry per-cluster fades. No browser
or shader errors. Final run: 1 passed, 57.2 s.

The first browser attempt aimed its picking ray into the bundle pore; the probe
now targets a known triangle. Another attempt was interrupted by Vite reloading
a source edit. Both failed runs cleaned up, and the final run completed without
source changes. See [browser_verification.json](browser_verification.json).

The cleanup inventory covers the exact `__e2e__surface-colouring` saved design,
session directory and hidden project store, plus the isolated-port credential
file. The test uses `afterEach` cleanup; the existing global teardown and artifact
reporter cover server credentials and Playwright output. All inventoried paths,
`frontend/test-results` and `frontend/playwright-report` were absent after every
run. See [cleanup.json](cleanup.json). Ordinary dependency caches are retained;
no simulation jobs or user designs were changed.

## Unit validation

Final `just test-frontend`: **7,066 passed, 1 skipped, 543 files**, 101.02 s.
Regressions cover in-place coordinates/connectivity, normal restoration after
ordinary animation, buffer identity, material preservation, geometry disposal,
mutable cluster maps, fade clearing, and GPU attribute lifetime when colour data
disappears. `git diff --check` passed. This batch changes frontend behavior only;
the earlier backend audit results remain in their original report.
