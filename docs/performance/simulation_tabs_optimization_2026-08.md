# Simulation-tab performance and progress overhaul (August 2026)

This note summarizes the shipped optimization pass across the active simulation tabs. The living
measurement ledger, fixture details, research links, and remaining candidate queue are in
[`memory/project_simulate_panel_overhaul.md`](../../memory/project_simulate_panel_overhaul.md).

## User-visible contract

- Measure the complete action from visualization selection to a usable scene, not only the solver
  or HTTP handler.
- Investigate algorithmic reduction, vectorization, compact native-array transport, caching,
  parallelism, or GPU execution whenever representative work exceeds one second.
- Keep the previous valid scene visible while a replacement loads.
- If an action remains over one second, retain a labelled progress row for every material phase:
  read/initialize, align or analyze, pack, download, decode, transform, scene build/reuse, and apply.
- Preserve cancellation, failure, stale-job, historical-snapshot, and compatibility-fallback paths.

## Transport formats

Two versioned little-endian binary formats remove nested JSON number/object expansion while keeping
identity fields exact:

- `NADOTR1` carries oxDNA trajectory frames on the established trajectory route. Its nine-float
  records preserve backbone, `a1`, and `a3` vectors so the browser can reconstruct exact live slab
  axes and sites.
- `NTRJ` carries LAMMPS and NAMD trajectory frames as contiguous six-float `float32` records plus
  compact key metadata. Browser frames are zero-copy `Float32Array` views over the response buffer.
- `CFRM` carries one CanDo/SNUPI representative conformation. Integer helix/base-pair/copy/direction
  columns remain exact; positions, slab-frame vectors, and FEM axis coordinates use `float32`, which
  matches WebGL storage precision.

Both protocols retain JSON fallback for old caches or servers. Streaming clients report determinate
byte progress using the uncompressed response length, avoiding incorrect compressed
`Content-Length` denominators.

## Measured results

| Action and representative fixture | Result |
|---|---|
| oxDNA trajectory, 16,133 keys × 50 frames | 75.18% smaller pack output; packing 1.276× faster. A real 201-frame route was 79.01% smaller and about 1.67× faster by warm median. |
| NAMD trajectory, 96 nt × 200 frames | 78.90% smaller wire; conversion 14.8× faster. The 1.76 s route remains extraction/context dominated and therefore keeps phase progress. |
| CanDo predicted shape, 14,410 nt + 7,164 axis nodes | `CFRM` is 97.98% smaller than the original 48-frame ensemble. The complete gesture improved from 16.730 s to 12.686 s (24.2%). |
| SNUPI predicted shape, 14,972 rows + 7,200 axis nodes | 79.32% smaller display wire. Visible loading improved 17.9%; the render-bound full gesture remains about 13 s and keeps detailed progress. |
| LAMMPS final structure, 1,328 nt × 101 frames | Bounded tail parsing replaced a full-trajectory scan. Representative cold-key backend latency improved 14.7×; the browser gesture improved 20.9%. |
| LAMMPS RMSF/deviation, same fixture | Cached analysis plus batched backbone-site cross products reduced cold RMSF from a 2.440 s median to 0.636 s (3.84×); repeats are about 4 ms. |
| LAMMPS trajectory selection, 1,328 keys × 102 displayed frames | `NTRJ` is 79.1% smaller. The renderer-bound gesture remains about 2.8 s and exposes download/decode/transform/apply phases. |
| NAMD shared jobs poll, 67 jobs | Compact history and conditional RunPod probing reduced the response 60.6% and latency from a 0.496 s median to 0.066 s (7.46×). Full history remains available from job detail. |

Display-only float32 conversions were checked at `rtol=1e-6`, `atol=2e-5 nm`; integer/string
addresses remain exact. Scientific topology and saved simulation history are unchanged.

## FEM full-suite corrections

The first guarded slow-suite run exposed two latent CanDo reconstruction issues:

1. Cylinder-axis output mixed CanDo's `0.340 nm/bp` mesh reference with NADOC's authoritative
   `0.334 nm/bp` display reference. Backbone winding and axis emission now reuse the same
   preallocated NADOC-reference deformed axis points.
2. The RMSF regression assumed every deletion/skip FEM node had a drawable nucleotide. Drawable
   sites are checked against reconstructed ensemble motion; beadless mechanical nodes retain their
   finite modal RMSF without inventing renderer keys.

The combined backend gate passes with `7,584 passed, 155 skipped, 1 xfailed`. Six passing tests
found above the five-second fast-loop budget were moved individually into the guarded slow registry;
the post-triage fast suite is `7,205 passed, 117 skipped` in 18.59 s with no budget violators.

## Remaining work

- Obtain a manifest-current mrDNA job before optimizing its predicted-shape and bead displays.
- Benchmark NAMD Display-MD and large-DCD initialization in an isolated, cancellable process.
- Continue the one-second audit across remaining metrics, occupancy, atomistic/surface, preparation,
  and shared-shell actions.
- Consolidate the remaining mrDNA/CanDo run controls and duplicate status bars into the shared job
  shell without removing engine-specific scientific detail.
