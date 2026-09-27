# Surface sharpness and strand probe audit — 2026-09-26

This follow-up adds **opt-in diagnostics only**. No surface-generation parameter,
mesh, saved design, visual golden, or rendering behavior changes. The temporary
continuous-field implementation remains the previous working-tree experiment.

## Metric

`backend/core/surface_quality.py` reports adjacent-face normal turns, edge-length
weighted 95th/99th percentiles, maxima, sharp-edge length fractions at 30/60/90°,
and sharp-edge length per surface area. It also reports boundaries, nonmanifold
edges, degenerate faces, and the coordinates/strand IDs of the strongest hotspots.

Angles are turns between face normals (0° is flat), not internal dihedral angles.
These are diagnostic thresholds, not universal physical validity criteria. Compare
matched input/probe/grid settings, retain shape/volume/detail checks, and do not
minimize sharpness by deleting genuine grooves. Counts alone are tessellation
sensitive. Separate overlapping strand shells can create visible intersection
creases without sharp adjacent triangles; this diagnostic does not test those
intersections or visibility. A sharp edge is not necessarily a distinct visible spike.

This follows the established adjacent-face angle approach described in
[CGAL feature detection](https://doc.cgal.org/5.0.4/Polygon_mesh_processing/group__PMP__detect__features__grp.html).

## Reproduction and speed

Read-only input: `workspace/mini_rect.nadoc`. CUDA initialized first; one excluded
warmup per mode/probe, then three timed runs in alternating mode order. Timings
include mesh generation, not quality analysis, transfer, or browser rendering.
Command (focused development validation, no session needed):

```bash
uv run python -m scripts.audit_surface_quality workspace/mini_rect.nadoc \
  --probe .14 --probe .24 --repeats 3 \
  --output .development-artifacts/surface-quality/mini_rect.json
```

| Probe (nm) | Mode | Warm median (s) | Length-weighted p99 normal turn | Edges >90° | Edge length >60° |
|---|---|---:|---:|---:|---:|
| 0.14 | Figure | 2.650 | 50.02° | 429 | 0.28224% |
| 0.14 | Continuous | 3.006 | 30.74° | 19 | 0.00604% |
| 0.24 | Figure | 3.669 | 42.47° | 304 | 0.10299% |
| 0.24 | Continuous | 4.106 | 26.93° | 3 | 0.00271% |

Continuous 0.14 has 17 scaffold and two staple edges >90°; its strongest turn is
106.44° at [14.647678, 0.205979, 8.631696] nm on
`scaf_XY_0_1_h_XY_0_0_55_r`. Continuous has zero boundary/nonmanifold edges or
degenerate faces in these runs. Figure 0.24 has six nonmanifold edges. The JSON
contains all measurements and hotspot locations; retain it as review evidence.

This fixture does **not** confirm faster continuous mesh generation: it takes
about 12–13% longer after warmup. The user's perceived speed difference may arise
elsewhere (first-use caches, transfer, rendering, different model); this audit
does not attribute it to a measured browser stage.

## Probe investigation

The same requested numeric probe radius is passed to every strand, independent
of scaffold/staple role. A regression checks 0, 0.14, and 0.24 nm while deliberately
forcing different strand grid spacings. The mismatch is adaptive discretization:
long scaffold bounding boxes exceed the voxel budget before short staple boxes.

| Read-only design | Scaffold grid | Staple grids |
|---|---:|---:|
| mini_rect | 0.063968 nm | 0.050000 nm |
| Roth_rect | 0.120000 nm | 0.050000–0.082078 nm |

The spherical closing stencil samples the requested probe differently on those
grids. Furthermore, continuous-field sigma is currently **0.85 voxels**, so it
also changes in physical units: 0.102 nm on a 0.12 nm scaffold grid versus 0.0425 nm
on a 0.05 nm staple grid. Independent strand cropping shifts voxel phase too.
These are real sampling differences that can explain the appearance; no exact
user-design reproduction is claimed without their design/view details.

Recommended next geometry experiment: common physical sampling and smoothing
widths, with tiled/halo processing for long scaffold shells to retain fine sampling
without a giant dense volume. Coarsening all staples to scaffold resolution would
make them consistent at the expense of fidelity, so it was not applied. Diagnose
remaining localized spikes with the metric before increasing global smoothing.

## Validation

Five focused checks pass: flat patch, known 90° fold and scale behavior, invalid
mesh edges/faces, empty mesh, and probe propagation across unequal strand grids.
Lint passes. No app changes in this diagnostic follow-up; `main.js` LOC delta 0.

`just test-smart`: **FAST**, 9,268 passed, 15 skipped, eight failures all present
in the recorded baseline, 87.74 seconds pytest / 96 seconds guard. Zero per-test
timing violations; the aggregate notice reflects suite size/overhead and does not
justify reclassifying healthy tests. Broad-suite selection reported:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

The focused quality/probe checks and benchmarks were completed without a session.
Two stale benchmark module comments requiring a session for all runs were corrected
while tracing these tools; current-development benchmark authorization follows CLAUDE.md.
