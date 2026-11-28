# Corner cold-load performance — November 27, 2026

**The requested five-second cold-generation target remains unmet.** Exact
optimizations reduce the measured full posed-plus-straight calculation from
43.94 seconds to 20.6–22.3 seconds serially; bounded parallel projection reduces
it further to **13.40 seconds**. The subsequent compiled stamping/exclusion/
bookkeeping pass measures **13.21 seconds** from the isolated staged source
(14.24 seconds including imports and setup). This small timing difference is
within plausible run-to-run variation; it is not evidence of a large additional
end-to-end speedup.
A subsequent shared-worktree run measured 15.26 s (16.31 s including setup),
underscoring that these single-run timings vary with runtime/system conditions.
These are backend measurements, not complete
browser-open times. No iteration limit, tolerance, phase constant, approved
geometry fixture, feature history, or saved design was changed.

## Reproduction and scope

```bash
just validate-safe .venv/bin/python -m scripts.benchmark_corner_load workspace/corner_test.nadoc
just validate-safe .venv/bin/python -m scripts.benchmark_corner_load workspace/corner_test.nadoc --parallel
just validate-safe .venv/bin/python -m scripts.benchmark_corner_load workspace/corner_test.nadoc --iteration-study
```

The benchmark reads an existing part, retains its complete authoring state,
generates derived display data in memory, verifies source immutability, and
writes only measurements to stdout. Each invocation is a fresh process with
empty geometry, atomistic, projection, numerical-fit, and dependency caches.
Numba's machine-code disk cache is permitted. First-ever compilation costs are
additional and are included if those binaries are absent; they are not covered
by a sub-five-second claim. Application imports are measured separately.

Measured source SHA-256:
`b792593239464371350a354b0ce79b6b4d98feafb6bbb3733e3153dfd45bb34c`.
It contains 6,276 routed nucleotides, 36 Corner seams, and 100 inserted bases.
The file-opening client waits for geometry after the initial import, while its
popup still describes reading/migration/validation. The geometry route generates
both posed and straight views.

| Stage | Original, unprofiled | Optimized, unprofiled |
| --- | ---: | ---: |
| Posed | 26.02 s | 13.07 s |
| Straight | 17.93 s | 9.21 s |
| Combined | 43.94 s | 22.28 s |

A separate paired equivalence check measured the optimized calculation at
20.59 seconds and the captured original closure/placement at 38.42 seconds.
That original-side check retained the separately verified seed batching, so it
is an equality oracle, not a second untouched performance baseline. Both complete
display outputs compared exactly. Timings are individual runs on the development
machine, not a cross-platform latency guarantee.

## Implemented optimizations

- File-load geometry now prepares posed and straight Corner projections in two
  disposable processes, each with one numerical thread. The existing display
  providers consume those exact projections. Cold display requests serialize
  their worker pairs; warm requests spawn nothing. Transport/time-budget failures
  fall back to the local provider. Partial and physical-reference paths retain
  their existing behavior.
- Vectorize clash spatial-cell calculation, preserving atom order, cell ranks,
  exclusions, exact distances and capped report order.
- Compile duplex template stamping for Corner builds while retaining each
  original matrix-vector product. Cache immutable local template arrays, rather
  than allocating one array per atom. Atom objects and full environmental
  geometry remain present; this does not substitute a sparse molecular model.
- Check one/two-bond exclusions only for spatial clash candidates using a compact
  compiled adjacency index, instead of constructing every exclusion in Python.
- Compile query-bound accumulation, candidate-list skin checks and local
  topological pair selection. Seed objectives now calculate only residuals,
  avoiding analytic-gradient arrays that the finite-difference solver discards.

- Compile closure arithmetic without fast math, preserving scalar powers,
  reduction order, rigid-coordinate transforms, and repeated-index scatter.
- Use an expanding local tree and reusable candidate lists for the environment.
  Each query can move freely. A 0.125 nm per-axis skin triggers reconstruction
  before any atom outside the list could enter the original 0.20 nm interaction
  radius. Retain full ordered environment coordinates for exact cache proofs.
- Batch seed-bridge cost evaluations through SciPy's worker-map interface.
  SciPy still owns finite-difference steps, iteration limits, evaluation counts,
  and stopping conditions. Other bridge consumers retain their existing path.
- Index seam membership once, preserving original atom/bond ordering, and build
  topological pair exclusions with Boolean adjacency arrays.

These changes preserve the same search domain and the two ordered closure passes.
They reduce work per evaluation, rather than approving different molecular poses.

## Smaller iteration budgets

The optional study evaluates numerical vectors at caps of 25, 50, and 100 for
the first seam of each insert count in each view. It always returns the ordinary
production result; no candidate is published or supplied to simulation.

At 100 iterations, the five sampled posed cases differed from the ordinary
solution by up to 0.120 nm per atom; none converged at that cap. At 25 iterations,
the maximum sampled posed displacement was 0.308 nm, and the maximum O3′–P
length difference was 0.0261 nm. These are comparison deltas, not independent
chemical-validity verdicts. Even the original 400-iteration fit reaches its cap
for several examples; the approved model is not a convergence certificate.

The optimized profile still spends substantial time constructing whole atomistic
models, performing phosphate clearance, and fitting seed bridges. Merely capping
closure iterations cannot eliminate those costs. Further work toward five seconds
needs a broader change to model construction or a separately qualified placement
model; the present measurements do not prove that the target is impossible.

## Remaining bottlenecks and hardware

The machine exposes a Ryzen 5 3600 (six cores, twelve threads, AVX2) and an
RTX 2080 SUPER with 8 GiB VRAM. The preceding serial CPU profile measured:

| Work | Profiled cumulative time, both views |
| --- | ---: |
| 144 seam closure calls | 11.23 s |
| Reciprocal phosphate clearance, including clash search | 3.95 s |
| Extra-base atom construction, including seed optimization | 3.34 s |
| Whole atomistic build, including the above | 24.97 s |

These are overlapping cumulative measurements with profiler overhead, not
additive unprofiled timings. There were 32,968 closure objective calls. Individual
seams observe previously updated atoms, so naive parallel seam fitting changes
the numerical problem. The two complete views have independent inputs.

The initial existing-preview-worker trial took 16.30 s versus 21.39 s locally,
with exact complete display equality. Avoiding preview DTO construction and
transport in the file-load worker reduced the subsequent fresh-process benchmark
to 13.40 s; its 12.85 s projection stage includes process startup and transport.
No geometry results were warmed before that measurement.
A second fresh-process paired check measured 13.48 s with the file-load worker
and 20.73 s locally, asserting exact equality of both complete outputs for
`corner_test.nadoc` and an unchanged source hash.

The follow-up implements compiled stamping, topology/exclusion indexing and
several repeated objective bookkeeping operations. Remaining candidates are
array-based atom storage (avoiding Python atom objects where only display
landmarks are required) and reducing the remaining Python/solver boundary.
Any sparse construction must retain all environmental atoms that can affect
clearance and the ordered report cap. Eliminating apparently distant atoms
without that dependency proof is not an equivalent optimization.

GPU acceleration was not implemented or benchmarked. Engineering inference:
moving each small, dependent CPU optimizer callback to CUDA is unlikely to be
the first useful target; a larger resident batch or resident solver would be
needed to amortize transfers and launches, with separate exactness validation.
NVIDIA's [CUDA best-practices guide](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html)
recommends minimizing host/device transfers and batching small transfers.
The existing CPU kernels already use compiled arithmetic without fast math.

## MagicDNA evidence

MagicDNA 2.0's **extrude** algorithm connects wedge-shaped bundles using a
vertex model calibrated against oxDNA simulations of four cross sections. The
reported effective interhelical spacing near vertices is **3.2 nm**; this is a
vertex-design calibration, not a general DNA helix diameter. The simulations
and experimental validation support its angle/edge-gradient relationship.
[Paper](https://doi.org/10.1126/sciadv.adi0697).

Supplementary Fig. S1 shows simulated vertex examples. Retrieved Data S1 contains
`adi0697_Data_S1.xlsx`, identified as staple sequences. The linked OSF root listed
gel, TEM, and AFM image folders. No reusable relaxed-joint coordinate library was
identified in those retrieved materials.
[Supplementary materials](https://www.science.org/doi/suppl/10.1126/sciadv.adi0697/suppl_file/sciadv.adi0697_sm.pdf),
[OSF](https://osf.io/n284u/), [software](https://github.com/cmhuang2011/MagicDNA).

Engineering inference: use the published vertex calibration and simulations as
reference targets for a new placement model. Applying them to NADOC would require
matching routing, cross section, linker lengths and poses, then an isolated
molecular comparison and validation. No MagicDNA spacing or placement was copied
into production, and no physical simulation was launched.

## Verification

21 focused tests passed: exact local-search cost/gradients; compiled coordinates
and objective against the independent NumPy implementation; unchanged seed
optimizer steps, counters and coordinates; frozen approved atoms; ordinary
junction/physical-reference isolation; Full/compact projection consistency; and
fit/deletion cache proofs. Ruff and whitespace checks passed. No broad suite ran.

The parallel/vectorization follow-up passed 12 focused tests, including frozen
approved atoms, native clash ordering/caps, complete worker/local equality,
warm-cache worker avoidance, transport fallback and cancellation cleanup.

The final CPU pass passed **30 focused tests** in the shared worktree and again
against an isolated archive of the staged source (without unrelated edits).
Additional checks cover exact template matrix-vector products, sparse pair
ordering including empty cases, and cost-only residuals including degenerate
arms. The staged-source benchmark used fresh geometry/fit/projection caches.
The temporary source archive and its compiler caches were removed afterward.
The final full-file comparison also matched both complete display outputs
exactly against the captured original closure/placement and original per-atom
stamping. It measured 20.10 s serially versus 40.08 s for that reference (which
retains separately verified seed batching), with the saved part hash unchanged.

Local diagnostic scripts, timing JSON, iteration results and the captured
pre-change numerical reference are in
`.development-artifacts/corner-cold-performance/`. No new `.nadoc` or `.nass`
was created. A read-only request to the running application's geometry endpoint
for the user's open `corner_test` document returned HTTP 200, 6,276 nucleotides,
and 36 straight-view helices in 24.47 s. Its server timings were 12.27 s for
posed nucleotides and 11.90 s for straight positions; live cache state was not
forced or certified cold. Complete browser-open/render latency was not measured.
After the parallel change, the same read-only endpoint check returned HTTP 200
in **14.08 s**, with all 6,276 nucleotides and 36 straight-view helices. Its paired
projection stage took 13.23 s, followed by 0.29 s posed and 0.25 s straight display
assembly. This live request likewise does not certify cold cache state.
Disposable trial programs, their compiler caches and the verbose profile tail
were removed (2,434,786 bytes); compact evidence and numerical reference source
remain. The original part's hash is unchanged.
