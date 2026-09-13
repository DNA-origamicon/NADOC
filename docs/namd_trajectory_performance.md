# NAMD trajectory performance — 2026-09-09

The 15-minute optimization pass addresses cached atomistic playback and the cost
of preparing its coordinates. It preserves the simulation's recorded heavy atoms,
sparse serial identities, periodic imaging, and alignment.

## Changes

- Fine scrubbing reuses exact frames already prepared for playback. Switching
  coarse/fine retains that cache. Uncached fine requests share the existing
  request queue, avoiding competing analysis workers. Off-grid frames remain
  transient to respect the existing memory budget.
- Coordinate-only extraction selects cached phosphate indices, reads the DNA
  prefix of supported DCD files, and returns NumPy arrays directly. It scatters
  coordinates into the existing serial-indexed payload without creating tens of
  thousands of Python atom dictionaries per frame. Unsupported prefix layouts
  retain the full-reader fallback; solvent requests still advance the Universe.
- Exact snapshots update existing atom/bond instance buffers using cached serial
  offsets. Selection, sparse serials, bond cutoffs, and cluster interpolation keep
  their existing behavior. Zero-length bonds are hidden instead of retaining a
  stale transform.
- NAMD trajectory topology opts into the existing sphere impostor shader, which
  draws each sphere using two triangles with corrected depth. The flag travels
  with the display payload; restoring design topology restores its ordinary
  geometry. The explicit `?impostors=0` override remains available.

## Measurements

Read-only local P1 job `a5e2cf157a76`, 32,748 DNA heavy atoms, 2,977,603 total
simulation atoms. Ten frames sampled across the complete trajectory:

| Work | Median |
| --- | ---: |
| Full DCD read and atom-record extraction | 152.5 ms |
| DNA-prefix coordinate extraction | 7.4 ms |
| Serial scatter, rounding, and conversion to payload list | 3.0 ms |

Maximum coordinate difference between full-reader atom records and the optimized
arrays was **0 nm** across those ten frames. Initial context setup remained
**28–32 seconds**. These timings exclude HTTP/JSON serialization and browser work.

Synthetic 144,000-atom renderer benchmark, median of 20 exact snapshots, with
sparse serials and 143,999 candidate bonds:

| CPU instance-buffer update | Before | After |
| --- | ---: | ---: |
| VDW | 9.0 ms | 1.0 ms |
| Ball-and-stick | 43.0 ms | 13.8 ms |

A standalone Chromium WebGL check rendered the real P1 heavy-atom coordinates
at 640×640. Atom geometry fell from **4,584,720 to 65,496 triangles**. Both paths
rendered; the compact path produced nonempty pixels, no JavaScript/shader errors,
and WebGL error code zero. This checks the real renderer with real coordinates,
not the entire application or a sustained GPU frame-rate guarantee.

## Validation and remaining costs

Focused backend tests cover periodic/nonperiodic DCDs, multiple segments, random
seeks, sparse serials, and the full-reader fallback. Renderer/controller tests cover
cached fine scrubbing, topology replacement, sphere geometry restoration, and
snapshot equivalence with the existing interpolation path. Existing trajectory,
solvent, preparation, and NAMD panel tests also pass.

Reproduce the backend benchmark from the repository root:

```sh
.venv/bin/python scripts/benchmark_namd_trajectory.py workspace/md_jobs/a5e2cf157a76
```

The setup cost is still paid by each analysis subprocess/batch. Surface generation,
uncached ion/graphene companion windows, HTTP transfer, and full-scene rendering
can still delay an unprepared frame. This pass establishes millisecond DNA
extraction and cached atom-buffer updates; it does not establish millisecond
latency for every representation, companion configuration, and machine.

## Follow-up: complete ion/box playback cache

P1's ion freeze was a separate scheduling bug: DNA advanced at 8 fps, while the
companion controller requested only a 32-frame neighborhood. Its next prefetch
started around frame 17, but every request paid topology setup again. DNA never
waited for that request, leaving old ions and box coordinates visible.

The companion controller now loads one preview frame, measures its full size
(including graphene), and prepares **all** loaded trajectory frames in batches
of at most 128 MiB. Its status reports completed frames out of the full count.
Play joins that background work before starting. A missing-frame seek holds the
scene and frame counter until its companions are ready, and rapid seeks discard
superseded results. Failed/incomplete batches prevent playback and allow retry;
settings/job changes discard stale responses. Full-cache memory checks use the
existing solvent budget and request a larger frame interval if needed.

Real P1 validation: all **280 frames**, **6,799 ions**, **44,664 graphene atoms**,
and box coordinates extracted successfully into **172,957,992 bytes** in **28.2 s**.
An isolated browser HTTP fixture served these real frames to the actual companion
controls, trajectory player, ion/graphene renderer, and box renderer. Requests were
**1, 212, and 67 frames**. The UI reached **280/280 ready**, and all 280 frame seeks
then used the cache, including frames 17, 32, 100, and 279. Companion buffer updates
averaged **0.69 ms/frame**; this excludes full-scene rasterization. No JavaScript
errors occurred in the completed check. No jobs or saved designs were changed.

Regression tests exercise full preparation beyond frame 17, the actual NAMD Play
button's wait, synchronized DNA/ion advancement, cancelled and superseded seeks,
partial-response failure/retry, disabled views, and graphene memory accounting.
The MDAnalysis `DCDReader` deprecation message concerns a future change to timestep
copying; it is not a read failure and appeared during the successful extraction.
