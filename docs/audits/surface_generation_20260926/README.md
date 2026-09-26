# Surface generation audit — 2026-09-26

Scope: the user's standard and “slow but beautiful” surfaces, including their shared
simulation/export engine. No surface parameters, grids, atom placement, topology,
triangulation, smoothing, or scientific goldens changed.

## Surface definitions and fidelity

| Path | Current definition | Compute worth retaining |
|---|---|---|
| Standard design / coarse simulation | Two 0.50 nm CG spheres per nucleotide; fused envelope; 0.20 nm target grid, adaptive coarsening; 0.28 nm probe; 15 Taubin iterations | Fast overall envelope and grooves at CG resolution. More triangles or more smoothing cannot recover omitted atomic detail. |
| Beautiful design (`chimerax`) | Atomistic VdW radii; independent strand shells; 0.05 nm target grid; 0.14 nm probe; 4 Taubin iterations | Atomic detail, smaller probe and strand separation in the mesh. Fine sampling resolves detail that smoothing cannot invent. |
| Beautiful simulation (`chimerax`) | Same target atomic radii/grid/probe/smoothing, but **one fused shell** | Existing distinction found during audit; preserved rather than changing simulation geometry implicitly. |
| Fine fallback / proteins / flexible atoms / exports | Existing all-atom or CG route as selected by callers | Preserve full model fallback for structures the vectorized cloud cannot represent. |

Both presets use discrete sphere occupancy, morphological closing, and marching cubes.
They approximate molecular surfaces; neither is an analytical Connolly calculation.
Independent strand shells can overlap and do not establish physical solvent accessibility.
Grid caps can coarsen the beautiful preset to 0.12 nm. The global split-grid budget is a
heuristic, with a 2-million-voxel per-strand floor; it is not a hard total-work ceiling.
At fixed bounds, reducing spacing from 0.20 to 0.05 nm increases voxel count 64-fold;
per-strand cropping partly offsets this. Fine grids and true atom radii are worthwhile
for groove/atomic detail. Additional smoothing or subdivisions cannot recover details
omitted by a CG envelope. For quantitative surface-area comparisons, grid convergence
and solvent-accessibility semantics need separate checks: this implementation does not
perform an explicit exterior-solvent flood fill. GPU lighting/anti-aliasing can improve
presentation without changing the mesh, but does not improve the underlying surface.

## What other applications do

| Application | Fast attractive surfaces | Higher fidelity / cost |
|---|---|---|
| VMD | QuickSurf generates Gaussian-density isosurfaces, with GPU acceleration and adjustable resolution. | Grid spacing, atomic radius scaling, density threshold and Gaussian cutoff control different approximation errors. A Gaussian envelope is a different surface definition from SES. [Official QuickSurf manual](https://www.ks.uiuc.edu/Research/vmd/current/ug/node73.html). |
| Mol* | Its GPU Gaussian path computes density and marching cubes into reusable vertex/normal textures, keeping geometry on the GPU. Hardware and texture-memory checks select CPU fallback. | The source deliberately avoids its GPU path above 1 Å grid resolution, where CPU performance is comparable and very coarse GPU results can show artifacts. [Gaussian surface implementation](https://github.com/molstar/molstar/blob/master/src/mol-repr/structure/visual/gaussian-surface-mesh.ts). |
| Mol* / NGL lineage | Spatial neighbor lookup avoids testing every atom against every surface sample. | Molecular-surface code projects spheres and samples probe torii; resolution and probe-position count control cost. This is separate from Gaussian density. [Molecular-surface implementation](https://github.com/molstar/molstar/blob/master/src/mol-math/geometry/molecular-surface.ts). |
| ChimeraX | Supports a separate Gaussian surface option and reuses existing surfaces when updating parameters. | Its SES command defaults to 1.4 Å probe and 0.5 Å grid, with per-chain construction and CPU thread scheduling. These defaults inspire NADOC's preset; they do not make our discretization equivalent. [Official command implementation](https://github.com/RBVI/ChimeraX/blob/develop/src/bundles/surface/src/surfacecmds.py). |

Sources inspected 2026-09-26. Performance statements about other applications are
architectural guidance, not speedup estimates for NADOC.

## Changes

1. Stamp the **same discrete spherical stencil** into occupied regions using bounded
   NumPy scatter batches, replacing one full-volume binary dilation per element/radius.
   Duplicate seeds are collapsed. Border seeds are clipped in three dimensions to avoid
   flat-index wrapping. Scatter index batches are limited to 8 MiB.
2. Group atoms by strand once, preserving first appearance and original within-strand
   order. This avoids a full object-array comparison for every strand and preserves
   KD-tree tie ownership.
3. Round cloud radii once; resolve nucleotide identity once per atom instead of once
   per surface vertex.

These benefit design, simulation and export callers of the shared surface functions.
4. CUDA count convolutions perform the same binary closing, with CPU fallback
   for small workloads, missing CUDA/PyTorch, insufficient free memory, or CUDA errors.
   GPU calls are serialized within the backend; no global precision/allocator settings change.

Marching cubes, smoothing, ownership queries and binary transport retain their existing
algorithms. The API's binary route still constructs intermediate Python lists before
packing; that is a remaining allocation opportunity, especially for million-vertex meshes.
The frontend already caches unchanged design surfaces and supports scalar-only refreshes.
Remaining candidates are direct array-to-binary packing (avoid list round-trips),
profile-guided KD-tree worker counts for small strand queries, and bounded parallel
strand construction. The latter needs aggregate memory control before adoption: a
per-strand voxel budget does not bound concurrent allocations. Marching cubes and
smoothing remain substantial work after occupancy/closing accelerate. Live trajectory
surfaces also need cancellation/coalescing at the generation-request layer before
making stronger interactive-frame-rate claims.

## GPU assessment

A complete GPU density → isosurface → rendering pipeline, as in Mol*, offers the most
promising architectural route for interactive Gaussian previews. Moving just one CPU
stage to CUDA adds transfers and still leaves CPU marching cubes, smoothing, ownership,
and serialization. Gaussian replacement would change the requested surface definition.
CuPy is absent; Torch CUDA is installed locally but is not a core project dependency;
Numba's CUDA availability check is false in the ordinary application environment.
CUDA is now enabled by default and warmed during backend lifespan startup.
NumPy/SciPy remains the fallback when CUDA-enabled PyTorch is unavailable.

An isolated 96×96×192-voxel closing probe on this RTX 2080 SUPER produced exact output:
CPU 126 ms; warm CUDA 25–29 ms; cold CUDA including import/context initialization 2.95 s.
The exact closing accelerator is **enabled by default** at the user’s request.
Startup warms import, CUDA context and a synthetic convolution before accepting
requests. Start normally:

```sh
just dev
```

Verification uses an isolated backend; no package installation was needed.
Missing/incompatible PyTorch or insufficient GPU memory retains CPU behavior. The
accelerator skips grids below 256,000 voxels and stencils outside 33–512 occupied
entries. It uses zero-padded float32 count convolutions and half-integer thresholds;
Boolean inputs and stencil values preserve the same discrete operations. GPU memory
preflight requires estimated free space of 32 bytes/voxel plus 256 MiB of workspace
headroom; allocation failures still fall back to CPU.
There is no Gaussian substitution, mesh decimation, or grid coarsening. Cold-start
cost is now paid during backend startup. `NADOC_SURFACE_GPU=0` explicitly selects
CPU execution for diagnostics and paired benchmarks.
Complete real-design CPU/CUDA comparisons are in `benchmark_cuda.txt`:

| Beautiful surface | Optimized CPU | CUDA | Additional speedup |
|---|---:|---:|---:|
| 6hb, 84 bp | 4.520 s | 2.573 s | 1.76× |
| VoltronCore | 39.682 s | 24.110 s | 1.65× |

Three alternating paired runs; all mesh arrays and identity lists compare exactly.
The first 6hb CUDA build took 4.249 s including initialization; subsequent builds
were 2.499–2.573 s. All VoltronCore CUDA samples used the warmed process, with 202
strands accelerated and three using CPU closing. Relative to the original implementation,
these warm GPU-assisted times are approximately 8.7× and 7.2× faster respectively.
The CPU/CUDA table is a separate benchmark run from the original/optimized CPU table.

## Reproduction and validation

Baseline: `0dc8b857378b077a739289f413a23cfad3e234a3:backend/core/surface.py`, loaded
into an independent in-memory module. Alternating paired runs compare every vertex,
face, strand ID and nucleotide ID exactly, including post-smoothing coordinates.
`benchmark_surface_generation.py` reports generation only, excluding network/render time.
Use an active user-opened test session:

```sh
NADOC_TEST_CONFIRM=1 scripts/test_guard.sh surface-benchmark 1 1 -- env PYTHONPATH=. uv run python scripts/benchmark_surface_generation.py --baseline 0dc8b857378b077a739289f413a23cfad3e234a3 --voltron
```

| Design / mode | Original CPU | Optimized CPU | Speedup |
|---|---:|---:|---:|
| 6hb, 84 bp — standard | 0.175 s | 0.140 s | 1.25× |
| VoltronCore — standard | 1.896 s | 1.623 s | 1.17× |
| 6hb, 84 bp — beautiful | 22.479 s | 4.518 s | 4.98× |
| VoltronCore — beautiful | 174.578 s | 40.358 s | 4.33× |

Three alternating paired samples per entry. Standard timings use the final owner-key
optimization (`benchmark_final_coarse.txt`); earlier occupancy-only measurements are
retained in `benchmark.txt`. Beautiful uses the cloud ownership path, unaffected by
the later object-key change. VoltronCore beautiful retains all 7,643,030 vertices and
15,292,948 faces, exactly. Timings exclude rendering/packing/network overhead.

Focused CPU tests: 38 passed, 8 slow cases deselected (full suite follows).
Acceleration + lattice parity tests: 24 passed, including real CUDA empty/full/random
grids, clipped boundaries, four probe footprints, and simulated unavailable-memory /
CUDA-error fallback. Results and suite/app evidence are recorded alongside this report.
No golden regeneration.

## Running-app verification and scope

`surface_generation_performance.spec.js` passed on the isolated app with
`NADOC_SURFACE_GPU=1` (44.6 s including server setup). Standard → beautiful → standard
returned exactly the original binary payloads (736,655 / 10,878,386 / 736,655 bytes),
including geometry, colours, and identity tables. The actual scene contained the
expected triangle counts, WebGL output was visible/coloured, no page/shader errors
were seen, the probe control followed the preset, and the restored standard image
had the same pixel hash. `app_validation.txt` records the pixel census.

Owned `__e2e__` design/session/project paths, the isolated viewer credential file and
Playwright output directories were verified absent after teardown. No generated
benchmark design was written into the user workspace. Benchmark and research evidence
is retained only in this audit directory. Frontend production code is unchanged in
this batch; `main.js` LOC Δ: **0**. `just lint` passed. `just lint-memory`: zero errors,
59 length/index warnings. Full backend suite: **9,743 passed, 25 skipped, 13 baseline failures**, in 624.78 s.
The failing IDs exactly match the prior audit, including the existing VoltronCore
fine-area golden (19045.7 vs 18077.7). No groups deferred. All 24 newly added tests
passed. Evidence is recorded in `validation.txt`; baseline failure details are in
[the earlier validation](../performance_20260925/validation.txt).

## CUDA startup follow-up

Five fresh Python processes on this RTX 2080 SUPER / PyTorch 2.6.0+cu124:
startup overhead above a warmed closing operation was **1.72–3.34 s**, median
**1.82 s**. Median components: Torch import 1.35 s, CUDA availability check
0.089 s, context initialization 0.249 s, first closing 0.164 s (warmed closing
0.028 s). Total first use was 1.75–3.37 s, median 1.84 s. Component medians
need not sum to the median total. Each run used a fresh process; OS/driver
caches were not flushed, and this does not measure a cold machine boot.

These measurements preceded the startup-policy change: the same initialization
is now performed during backend startup, before serving requests. The explicit
CPU override avoids Torch/CUDA initialization. Raw timings
and reproducible probe source: `cuda_startup.txt`, `cuda_startup_probe.py.txt`.

## Default-on startup validation

CUDA is enabled without an environment flag, and FastAPI awaits the synthetic
CUDA warm-up before serving requests. Lifecycle tests verify that ordering and
CPU fallback/override behavior. Focused tests: 10 passed. Running app with the
flag **unset**: 1 passed (41.9 s), both preset transitions, identical binary
payloads and rendered pixels. Cleanup verified. `just test-smart` selected FULL:
**9,747 passed, 25 skipped, the same 13 baseline failures**, 611.50 s; no groups
deferred. `just lint` passed. See `startup_default_validation.txt` and
`startup_default_app.txt`. The CPU comparison script explicitly selects CPU so
future baseline benchmarks remain comparable after the default changes.
