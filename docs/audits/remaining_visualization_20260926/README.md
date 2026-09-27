# Remaining active visualization opportunities — 2026-09-26

Completes active ranking #8 (solvent, ions, periodic images) and #10 (protein
attachments). All ten active opportunities have now been investigated and their
worthwhile changes implemented. Earlier batches and their evidence are linked
from [the active ranking](../active_visualization_20260925/README.md).

## Changes and measured scope

- Solvent spheres, water hydrogens, ions and O–H bonds write directly into existing
  instance buffers using the exact shared matrix math. Degenerate-bond behavior,
  capacities, colors, radii, impostors and particle counts are preserved.
- Subsequent solvent GPU uploads cover active matrices only: at steady capacity
  this avoids the 25% allocation headroom (20% fewer uploaded bytes). After a
  100→40 molecule count decrease with capacity 125, the upload is 68% smaller.
  Initial GPU allocation still includes the full capacity.
- Periodic-image buffers only upload changed position/color channels, comparing
  Float32 values to avoid repeated uploads caused by rounding. The existing
  six images, 12,000-point preview cap and sampling are unchanged. Static views
  now require zero subsequent position/color uploads.
- Protein trace refreshes retain unchanged tessellated meshes and GPU buffers.
  Primitive snapshots detect coordinate/name/chain/attachment changes, including
  in-place edits; fresh atom metadata replaces old picking/centroid references.
  Selection and saved simulation transforms retain their previous semantics.
  The shared factory serves both individual-part and assembly views.
- Box and ovoid representations retain their original rebuild path. Measurement
  showed that snapshotting their full atom payload could cost more than rebuilding
  their simple geometry. Actual trace deformations also rebuild as before.

Paired Node measurements against commit `0dc8b857`, alternating execution order,
with warmup and exact matrix/position/normal/UV/index comparisons:

| Operation | Before | After | Speedup |
|---|---:|---:|---:|
| 20k water + 5k ions, spheres | 0.55 ms | 0.36 ms | 1.51× |
| 100k water + 25k ions, spheres | 1.71 ms | 1.45 ms | 1.18× |
| 20k water + 5k ions, ball-and-stick | 8.72 ms | 3.19 ms | 2.73× |
| 100k water + 25k ions, ball-and-stick | 39.99 ms | 19.54 ms | 2.05× |
| Unchanged 300-CA protein trace refresh | 10.77 ms | 0.118 ms | 91.5× |
| Unchanged 3,000-CA protein trace refresh | 102.61 ms | 0.903 ms | 113.7× |

These synthetic fixtures isolate CPU preparation, not whole-app FPS or simulation
runtime. Protein timings apply to unchanged geometry refreshes, not first build
or deforming trajectories. Raw results: [benchmark.txt](benchmark.txt).
Reproduce in an active test session:
`NADOC_TEST_CONFIRM=1 scripts/test_guard.sh remaining-benchmark 1 1 -- node frontend/scripts/benchmark-solvent-proteins.mjs`.

No additional GPU compute shader is introduced: the gain here comes from reusing
GPU geometry and avoiding redundant transfers, while retaining the existing
sphere impostor path. CUDA surface acceleration remains enabled and warmed at
backend startup, with CPU fallback when unavailable.

## Verification

See [validation.txt](validation.txt). The app exercise compares baseline/current
pixel hashes for solvent sphere and atomistic modes (sphere meshes and impostors),
shrinking hydration shells, and protein trace/ovoid/box modes with refreshed
metadata, selection and coordinate edits. Picking and exact centroids are also
compared. Periodic-image static, moved and recolored frames also match exactly.
Unit checks cover update ranges, unchanged periodic channels, metadata
refresh, in-place geometry invalidation and transform reset semantics.

Browser artifact inventory: `workspace/__e2e__*.nadoc`/`.nass`, associated hidden
project histories, scratch `playwright_tests/__e2e__*`, and isolated port-5174
bridge credentials are covered by global teardown. The custom spec additionally
owns `__e2e__solvent-protein` session/project/document paths and removes them in
`afterEach` even on assertion failure. Session autosave is disabled. Reports are
removed by the cleanup reporter. Paths are checked before and after execution.

`main.js` LOC Δ0. Unrelated photoproduct edits and analysis/experiment artifacts
are excluded from the audit commit.
