# Uniform continuous-surface sampling and sharp-edge attribution

## Implemented

The temporary continuous-field option now uses a **shared world-aligned 0.05 nm
lattice** for all scaffold/staple shells and simulation frames, with Gaussian sigma
fixed at **0.0425 nm**. Strand size no longer changes either parameter. Probe
closing and four Taubin iterations remain; the existing Figure quality option is
unchanged as the comparison baseline. No molecular coordinates/topology changed.
`main.js` LOC delta: 0.

`surface_tiled.py` owns extraction. Tiles contain disjoint marching-cubes cells
with overlapping dependency halos (two probe radii plus full filter support), and
shared grid-edge identities weld boundary vertices. Aspect-aware blocks fill a
fixed voxel budget to avoid repeatedly processing halos on thin strands. At 0.14
and 0.24 nm probes, working grids are limited to 1,601,613 and 1,953,125 samples
respectively. Final mesh memory still scales with surface area; fine sampling can
cost more than the previous coarsened scaffold representation.

An independent dense CPU oracle checks zero/0.14/0.24 nm probes at three tile
budgets, both-direction nearest-vertex agreement below 5e-6 nm, matching triangle
counts, and zero boundary/nonmanifold edges or degenerate faces. Integer-grid
translation, ownership, physical filter width, and native/simulation routing are
also covered. The implementation does not replace geometry with coarser samples
when a large bounding box exceeds the working-grid budget.

## Results on mini_rect

Read-only input `workspace/mini_rect.nadoc`. Same requested probe and four mesh
smoothing iterations. “Before” means the initial adaptive-grid continuous mode;
“after” includes uniform spacing AND common lattice phase.

| Probe | >60° edges before → after | >90° edges before → after |
|---|---:|---:|
| 0.14 nm | 162 → 19 | 19 → 2 |
| 0.24 nm | 58 → 158 | 3 → 24 |

All strands report 0.05 nm grid and 0.0425 nm sigma at both probes. Both outputs
have zero mesh boundary and nonmanifold edges. Sampling consistency is achieved,
but sharpness is **not monotonically improved at every probe**. The previous
coarsened scaffold also had a wider physical filter; making resolution/phase/
filter width consistent changes its narrow-contact geometry.

Raw fixed-grid meshes contain 2,549,176 triangles at 0.14 nm and 2,469,528 at
0.24 nm. These are display-surface edge diagnostics, not a count of distinct
visible spikes. Counts and angles remain tessellation-sensitive; compare matched
settings, edge-length fractions, shape/detail, and validity as well.

## Causes, measured at and above 60°

The analysis follows the SAME edges through smoothing, preserving triangle
connectivity, and samples the local scalar field and nearby named atoms.

| Probe | Raw >60° / >90° | Four iterations >60° / >90° | Final >60° already sharp in raw | Crossed 60° during smoothing |
|---|---:|---:|---:|---:|
| 0.14 nm | 110 / 8 | 19 / 2 | 15 | 4 |
| 0.24 nm | 464 / 132 | 158 / 24 | 99 | 59 |

1. **Narrow contacts introduced by probe closing.** The inspected hotspots lie
   between nearby helical domains belonging to the same staple, near phosphate
   oxygens and neighboring sugar atoms. They are not at the connecting crossover:
   the 19 hotspots at 0.14 nm are 2.49–2.68 nm from its nearest C3′–C5′ segment;
   the strongest 24 inspected at 0.24 nm are 3.62–5.63 nm away. The probe-closing
   operation creates thin surface connections in these gaps. At the strongest
   0.14 nm example the field value at the hotspot changes from 0.0776 without
   closing to 0.4827 with it (isosurface level 0.5); at the strongest 0.24 nm
   example it changes from 0.00027 to 0.4921. This is localized to one strand's
   field, not an intersection between two separately rendered strand meshes.
2. **Extraction under-resolves some of these narrow connections.** In one local
   patch the raw maximum normal turn is 111.1°. Re-extracting the same field at
   half spacing with linear interpolation gives 127.1°; cubic interpolation gives
   81.0°. More triangles alone do not remove the underlying pinched field. The
   strongest 0.24 nm patch remains severe even with cubic reconstruction (161.5°
   → 145.7°). These interpolation changes are diagnostic experiments only.
3. **Mesh smoothing can create/amplify local creases.** A tracked edge changes
   from 32.7° to 83.1° after four iterations, with vertex displacement up to
   0.0222 nm. The uniform neighbor-averaging Taubin pass moves irregularly spaced
   mesh vertices without constraining them to the 0.5 field surface. At 0.24 nm,
   eight iterations reduce >60° edges to 114 but increase >90° edges to 28 (from
   24 at four iterations). This reproduces why a blanket iteration increase is
   not a reliable remedy.

The next candidate is field-aware local remeshing/projection plus controlled
regularization of thin closing-induced connections, evaluated against shape and
pore/detail preservation. No additional global smoothing or atom displacement was
applied. Adjacent-face analysis alone cannot exclude other visual causes on other
designs (e.g. intersections of independently generated shells).

## Evidence and reproduction

- `.development-artifacts/surface-quality/consistent-sampling.json`: both probes,
  per-strand parameters, metrics, warm measurements. Timing in that first report
  predates the final aspect-aware tile scheduling optimization; it is not a final
  performance claim.
- `.development-artifacts/surface-quality/consistent-stages.json`: 0.14 nm stage
  metrics and all 19 hotspot attributions.
- `.development-artifacts/surface-quality/probe024/consistent-stages.json`: all
  158 >60° transitions; detailed field/atom attribution bounded to 24 hotspots.
- `preexisting.png` and `smoothing_induced.png` in each stage report's directory:
  same-edge before/after geometry. The patches are cropped for inspection;
  open crop outlines are not holes in the full mesh.

```bash
uv run python -m scripts.diagnose_surface_sharpness workspace/mini_rect.nadoc \
  --probe .14 --output .development-artifacts/surface-quality/consistent-stages.json
uv run python -m scripts.diagnose_surface_sharpness workspace/mini_rect.nadoc \
  --probe .24 --output .development-artifacts/surface-quality/probe024/consistent-stages.json
```

Focused backend checks: 24 passed. Lint and diff whitespace checks passed.

Final app checks: 24 Playwright tests passed (smoke, assembly teardown, and
continuous/figure comparison). Figure quality restored byte-for-byte and
pixel-for-pixel after switching back; no page/shader errors. Inspected the saved
continuous screenshot. Comparison screenshots are intentionally retained in
`.development-artifacts/surface-consistent-comparison/`. Test document/session,
revision store, reports, and temporary viewer credentials were verified absent
after teardown.

`just test-smart` selected FAST: 9,273 passed, 15 skipped, 8 failed in 87.21 s.
The eight failure IDs match previously recorded photoproduct-review/CPD-preview
failures in `surface_generation_20260926/startup_default_validation.txt`.
No slow-test budget violators. The runner deferred the broader FULL suite under
the session policy; that broad verification remains outstanding. Targeted surface
tests and the directly related diagnostic runs were completed without a session.
