---
name: project_simulate_panel_overhaul
description: "Active simulation-tab optimization plan — end-to-end backend performance, visualization latency, job UX, and honest phase/progress reporting across CanDo, SNUPI, mrDNA, oxDNA/LAMMPS, and NAMD"
metadata: 
  node_type: memory
  type: project
  originSessionId: 68f44bf0-ff75-46c4-b4fc-6c7576403328
---

# Simulation tabs: end-to-end performance and UX optimization

**Rank:** P0 — active optimization loop. This file is the living plan and evidence ledger for
all user-visible work initiated from the Simulate section, not only the shared-card overhaul.

**Status (scope reset 2026-08-24):** the original structural Phases A/B are shipped; their
remaining Phase-C consolidation is UX debt inside this broader program. Performance has not yet
been audited systematically across every tab and action. Treat every unmeasured path as unknown,
not fast. The first current-loop candidate is selected only after a source + representative-data
inventory; iteration results are appended to **Current optimization iterations** below.

**Current two-hour run:** start `2026-08-24T10:43:15-06:00`; cutoff
`2026-08-24T12:43:15-06:00`. Do not start a new candidate at/after the cutoff. If an iteration is
already in flight, finish its implementation, comparison, verification, and plan update, then
stop. A cutoff does not justify skipping equivalence checks or leaving a half-applied change.

**Run closeout:** stopped at `2026-08-24T12:43:56-06:00` after the requested timer. Eight measured
iterations and two fixture audits are recorded below; no candidate was started at or after cutoff.

**Deferred backend verification closeout (`2026-08-24T13:52:59-06:00`):** the user opened the
required test-dedicated session, so the backend debt recorded throughout the eight iterations is
now paid. The first guarded slow run exposed two deterministic FEM reconstruction failures:
drawable-trajectory RMSF assertions incorrectly assumed a deletion/skip site must have a renderer
bead, and the emitted cylinder axis mixed CanDo's `0.340 nm/bp` mesh reference with NADOC's
authoritative `0.334 nm/bp` display reference. The implementation now reuses the same preallocated
NADOC-reference deformed axis points for both backbone winding and axis emission. The RMSF test now
checks exact reconstructed ensemble motion where drawable columns exist and the documented finite
modal fallback at beadless skip nodes; no phantom renderer keys were introduced. Focused FEM is
`19 passed`; the guarded slow rerun is `374 passed, 40 skipped, 1 xfailed` in `573.02 s`; FAST is
`7,211 passed, 117 skipped` in `19.82 s`. Ruff, format, and diff hygiene pass, and
`.nadoc-slow-pending` is cleared. This global closeout supersedes each historical “FULL backend
deferred” note below. The subsequent combined guarded gate is also green at `7,584 passed, 155
skipped, 1 xfailed` in `552.68 s` and refreshed the full-pass watermark; there are no other slow
test failures. The guard separately reported six passing, unmarked tests over its five-second
classification budget. They were individually added to the guarded slow registry—one 51.36 s
oxDNA→NAMD atomistic parity reconstruction, three 6.65–8.61 s dense SNUPI hydrodynamics oracles,
one 5.70 s imported-scale oxDNA serialization check, and one 5.02 s headless corner clash scan—
without removing coverage or slowing their lighter module peers. The post-triage FAST gate is
`7,205 passed, 117 skipped` in `18.59 s` with zero budget violators; slow collection retains all
`418` tests. Frontend/full-browser results remain those recorded per iteration.

**Upstream integration note:** while this work was being finalized, `origin/master` added the
newer `NADOTR1` oxDNA transport on the established `/trajectory?transport=bin` route. The final
integration keeps that nine-float backbone/`a1`/`a3` format and exact-site reconstruction for
oxDNA. The six-float `NTRJ` transport remains the shared optimized path for NAMD and LAMMPS. This
supersedes the historical oxDNA `/trajectory-bin` implementation detail recorded in ITER-1; its
measurements and phase-progress conclusions remain valid.

History (every dated block, the phase write-ups, the Chain-Simulations build-out) →
`project_simulate_panel_overhaul_archive.md`. Don't read it in a routine loop.

## Optimization contract

### Scope: every active simulation-tab surface

| Tab / execution path | Backend and data work | User-facing work to measure |
|---|---|---|
| CanDo | job creation/serialization, FEM assembly/solve, autorefine, deviations/RMSF, shape extraction | coarse/fine/autorefine launch, polling, relaxed-shape display, cylinders, metrics |
| SNUPI | shared FEM assembly plus anisotropic material path, worker/process boundary, dynamics/RMSF, shape extraction | coarse/fine launch, polling, relaxed shape, dynamics and metrics |
| mrDNA | design-to-model conversion, ARBD package/run/decode, anchors/field/surface, curvature and shape extraction | coarse/fine launch, polling, relaxed/deformed/bead views and input preview |
| oxDNA | topology/config generation, relax/live/production/autorefine, trajectory parsing/alignment, analysis and exports | launch/live controls, job tree, relaxed/RMSF/trajectory/occupancy views, metrics and export |
| LAMMPS fallback | oxDNA2 conversion/run/parse and CPU scheduling (not a selectable tab, but launched and displayed through oxDNA) | fallback choice, job state, display and comparison parity |
| NAMD | plan/wizard, atomistic build/solvation/ions, queue/execution/resume/ensemble/remote sync, health/analysis/trajectory extraction | wizard and launch, phase timeline, live health, Display-MD, visualizations, metrics and cluster state |
| Shared Simulate shell | `/simulate/jobs`, `/api/jobs/active`, normalization, polling and selection | engine switching, capability strip, master job card, Run/Stop/Resume, comparison, stale/error/cancel states |

Dormant BLADE code is out of the active sweep unless its tab is revived. Remote engine runtime is
measured separately from NADOC-controlled preparation, transfer, parsing, and display latency.

### The one-second rule

1. Measure **wall-clock latency from the user's action to the complete usable result**, with the
   same representative fixture and warm/cold state stated explicitly. Backend-only microtimings
   may locate a bottleneck but never substitute for the full-path measurement.
2. Any process whose representative p50 or a single deterministic run exceeds **1.0 s** is an
   optimization candidate. First investigate algorithmic complexity and avoided work; then
   vectorization/batched native kernels, GPU acceleration, safe parallelism, caching/incremental
   work, streaming/downsampling, or lower-copy data movement. Include startup, I/O, serialization,
   transport, JavaScript transforms, geometry rebuilds, and rendering—not just the solver.
3. Do not parallelize blindly. Account for input size, worker/process startup, memory traffic,
   GPU transfer, determinism, thread safety, concurrent simulations, and oversubscription. Prefer
   the simplest method that improves representative end-to-end time and resource efficiency.
4. If the path remains over 1.0 s after reasonable, evidenced optimization, it must show a visible
   processing indicator. The indicator must name the active phase, expose determinate progress
   for every measurable subprocess (one bar/segment/readout per phase), use indeterminate progress
   only where the engine exposes no safe denominator, and surface completion, failure, cancellation,
   and stale/no-update states. A spinner alone is not adequate for a multi-phase operation.
5. For visualization selections specifically, cover every preparatory subprocess (fetch/read,
   parse, align/reconstruct/analyze, transfer, client transform, geometry build/upload) that can
   materially contribute to the wait. Keep the previous valid scene until the new result is ready
   unless the visualization's semantics require otherwise.
6. Fast paths must preserve scientific and UX correctness. Record numerical tolerance or exact
   output identity, memory/resource deltas when material, and behavior under cancellation or a
   changing/growing trajectory.

### Mandatory candidate loop

Complete these gates in order for one candidate before moving to another:

1. **Select and bound:** name one user action, representative fixture/size, cold/warm state, and
   expected performance gain. Prefer measured >1 s paths, then missing-indicator paths, then
   likely scaling risks. Record why it outranks the queue.
2. **Read the full path:** read all code from event handler through API/router, worker/runner/core,
   file/network boundaries, response normalization, frontend transform, and final display/status.
   List every subprocess and existing timing/progress seam. Do not optimize from a partial callsite.
3. **Research:** consult primary/authoritative documentation or papers for the actual bottleneck
   (library APIs, native vectorization/GPU facilities, concurrency constraints, file formats, or
   algorithms). Record the useful method and why it fits this workload; do not cargo-cult it.
4. **Build the measurement first:** add or extend a repeatable test/benchmark that exercises the
   process in full on representative data. It must assert output equivalence/correctness and emit
   phase timings. Keep a small CI-safe regression test; put a genuinely heavy benchmark behind the
   repository's user-opened `just test-session` guard.
5. **Baseline:** run enough samples to expose noise; record command, fixture, hardware, cold/warm
   state, phase breakdown, p50 (and range/p95 when practical), peak memory/VRAM if relevant, and
   current indicator behavior.
6. **Implement one improvement:** make the smallest cohesive change that attacks the measured
   bottleneck. Avoid bundling cosmetic refactors so the comparison stays attributable.
7. **Remeasure and compare:** run the identical benchmark and correctness oracle. Record absolute
   before/after, speedup/percent change, resource change, and whether the stated expectation was met.
   Reject or revise regressions and numerically unsafe wins.
8. **Close the UX contract:** if still >1.0 s, add/verify phase status and per-subprocess progress;
   test progress ordering, terminal/error/cancel states, and exercise the feature in the running app.
9. **Reassess this plan:** append the evidence below, update the candidate queue, and explicitly
   choose to loop on the same process (remaining dominant phase) or advance. At the time cutoff,
   finish only this gate sequence and stop.

### Benchmark record template

```text
#### ITER-<N> — <user action / process> — <date>
State: selected | baseline | implemented | verified | retained-slow-with-progress | rejected
Fixture + scale:
Full code path read:
Research (primary sources):
Benchmark/test + environment:
Expected improvement:
Before (end-to-end + phases):
Change:
After (same measurement):
Correctness/equivalence:
UX for any remaining >1 s phase:
Decision + next candidate:
```

## Current optimization iterations

#### ITER-1 — oxDNA View trajectory — 2026-08-24

**State:** verified; advance to the next candidate.

**Fixture + scale:** the baseline hot phase used real job `1d509398c348` (VoltronCoreScad),
16,133 origami nucleotide keys plus a 13,944-particle captured surface, with one representative
frame repeated 50 times for five warm samples. Full-route validation used completed job
`2d8b40a0d507` (96 nt, 201 frames) through the running API and browser. The large fixture's
historical 200-frame flattening floor alone exceeded 1 s.

**Full code path read:** trajectory checkbox and status in `oxdna_jobs_panel.js` →
`oxdna_display.js` → API client/transport → `routes_oxdna.py` → composite-input discovery,
downsampling/alignment and frame flattening in `oxdna_health.py` → response decode → typed-frame
updates → trajectory player/scene. Existing cache, gzip, cancellation, surface-strand and growing-
trajectory behavior were included in the audit.

**Research:** NumPy documents that `ndarray.tolist()` converts array values to Python scalars;
orjson documents native contiguous NumPy serialization that avoids that expansion. The measured
bottleneck was broader than JSON encoding, so the retained method is a compact contiguous
little-endian float32 typed-array wire format, matching NADOC's existing binary visualization
routes, with small JSON metadata and the old JSON route as compatibility fallback.

**Benchmark/test + environment:** five same-process warm samples on the local workstation for
the representative pack/encode phase; three full HTTP requests per format on the running local
API; backend binary-vs-JSON equivalence and route tests; frontend parser, streaming client,
typed-frame update, player-phase, and panel tests; browser exercise through the running app.

**Expected improvement:** at least 4× smaller wire data and materially lower server/client
conversion work, while retaining scientific display equivalence and exposing all remaining load
phases.

**Before:** legacy 50-frame list expansion plus JSON encoding p50 `0.327034 s`,
`77,994,412 B` (samples `0.334360, 0.324400, 0.326680, 0.327760, 0.327034 s`). The full small
route returned `2,221,280 B`; warm samples were `0.2089, 0.1104, 0.1731 s`. Loading had one
aggregate status rather than durable per-phase progress rows.

**Change:** vectorized frame packing now produces one contiguous float32 array and a versioned
binary response. The client streams into a correctly sized/growing buffer, parses frames as
zero-copy `Float32Array` views, and avoids `JSON.parse` plus millions of boxed numbers. A response
header reports uncompressed length because a live proxy probe exposed compressed
`Content-Length`. The JSON endpoint remains the fallback. Backend and UI report `align`, `pack`,
`download`, `decode`, `surface-strands`, and `display` independently; the trajectory player keeps
one labelled progress bar per subprocess until completion.

**After:** binary pack p50 `0.256356 s`, `19,359,600 B` (samples
`0.257640, 0.257320, 0.256350, 0.256360, 0.254450 s`): **1.276× faster CPU phase and 75.18%
smaller** (4.03×). The full small route returned `466,188 B` (79.01% smaller) and warm samples
`0.10313, 0.10285, 0.10295 s`, about **1.67× faster** by median. Browser validation loaded all
201 frames through `/trajectory-bin`, enabled controls, and scrubbed to frame 50 without invoking
the JSON fallback.

**Correctness/equivalence:** real generated trajectory data matches the JSON representation at
`rtol=1e-6`, `atol=2e-5`, appropriate to display-only float32 positions/directions. Tests cover
the full file→align→pack→wire path, malformed/truncated payloads, zero-copy frame views, streamed
progress, compressed-length mismatch, JSON fallback, and progress phase retention. Focused tests,
the complete 5,857-test frontend suite, and the repository FAST suite pass. The FULL backend suite
remains deferred by repository policy until a user-opened test session exists.

**UX for any remaining >1 s phase:** the large 200-frame load can still exceed 1 s depending on
disk, alignment, network and GPU upload, so each named subprocess now has its own status/progress
row. The last valid scene remains visible during loading; failure/cancellation use the existing
terminal status path.

**Decision + next candidate:** the expectation was met; further packing work has diminishing
returns relative to alignment and rendering. Advance to NAMD Display-MD/trajectory loading. A live
probe also observed an unrelated 500 from one background `/api/md/jobs/.../trajectory-meta`
request, so establish whether stale-job metadata lookup is part of that path before benchmarking.

#### ITER-2 — NAMD View trajectory — 2026-08-24

**State:** verified; retained-slow-with-progress; advance to another simulation tab.

**Fixture + scale:** archived real job `c8bcf4c1406f` (`2hb_1xT`), ten physical DCD
segments and 300 raw frames sampled to 200 composite frames, 96 nucleotides. A scaling probe also
used archived job `4c0ba3a85587`, a 30 GB DCD with 40,000 raw frames.

**Full code path read:** NAMD trajectory radio, interval pricing and polling in
`md_jobs_panel.js` → shared `oxdna_display.js` controller through `md_viz_adapter.js` → client
JSON transport → `routes_md.py` job/archive resolution, segment discovery and killable analysis
subprocess → `md_analysis_runner.py` → PSF/DCD context construction, composite indices,
per-frame PBC/Kabsch/base-normal extraction and Python-list flattening in `md_trajectory.py` →
browser JSON parse, FEM updates and trajectory player. The separate WebSocket-backed live
**Display MD** path was read to distinguish it from this scrub-trajectory action; it was not
changed in this iteration.

**Research:** MDAnalysis' official DCD documentation confirms indexed/sliced reads and that DCD
is the NAMD trajectory format, while its user guide confirms that trajectory iteration advances
the Universe frame. NumPy's official array documentation confirms that `tolist()` creates nested
Python scalar lists whereas `tobytes()` emits raw C-order array bytes. Because NADOC's scientific
per-frame extraction is already array-vectorized, the suitable improvement was to retain its
float32 arrays through transport rather than parallelizing DCD reads and risking I/O contention,
stateful-Universe races, and extra per-process PSF construction.

**Benchmark/test + environment:** three matched HTTP samples per format against the running local
API, plus five same-process samples of the full synthetic 200-frame selection/extract/flatten/
encode shape (100 P keys + four termini). A CI-safe regression drives selection, extraction,
packing and wire decode; a live Playwright test opens the real design/job and records requests and
progress mutations.

**Expected improvement:** at least 4× smaller wire data and at least 5× faster Python
flatten/serialization, with lower browser allocation. Total route time was expected to improve
only where encoding/transfer was material because PSF/DCD setup and scientific extraction remain.

**Before:** real JSON payload `2,205,832 B`; samples `3.492021, 1.760410, 1.761027 s`
(warm p50 about `1.761 s`). The controlled conversion path was p50 `0.008931 s` over samples
`0.009023, 0.009029, 0.008931, 0.008540, 0.008692 s`, `1,356,482 B`. The UI exposed only one
frame counter and did not name topology initialization, transport, decode, or first-frame work.
The 30 GB scaling probe remained inside MDAnalysis DCD discovery/setup beyond 180 s and was
cancelled rather than allowed to monopolize the workstation; it establishes a separate dominant
large-file candidate without being used as a completed timing sample.

**Change:** added the shared versioned `NTRJ` float32 response for NAMD, filled one preallocated
NumPy matrix with slice assignments, and streamed/decoded it as zero-copy typed frame views using
the ITER-1 browser parser. JSON remains a fallback. Progress now distinguishes `initialize`,
`extract`, `pack`, `download`, `decode`, `surface-strands`, and `display`. A FastAPI route-schema
registration failure caught during the first reload was fixed by disabling response-model
inference for the mixed binary/not-ready endpoint and pinned through app-import/route tests.

**After:** real binary payload `465,472 B` (**78.90% smaller; 4.74×**); samples
`1.771016, 1.755785, 1.757162 s` (p50 `1.757 s`). Warm total time is essentially unchanged
(about 0.2% faster), proving the remaining `~1.76 s` is extraction/context dominated rather than
encoding dominated at this small 96-nt size. The controlled conversion p50 is `0.000605 s`
(samples `0.000661, 0.000658, 0.000604, 0.000605, 0.000605 s`), **14.8× faster**, with a
`500,644 B` payload versus `1,356,482 B` for deliberately simple synthetic values. The expected
wire and conversion improvements were exceeded; expecting a large total-route win on this fixture
would have been incorrect.

**Correctness/equivalence:** the real 200-frame binary metadata exactly equals JSON and all
coordinates match at `rtol=1e-6`, `atol=2e-5`; observed maximum absolute difference was
`4.77e-7 nm`. The focused 33 backend and 324 frontend tests pass; repository FAST is
`7202 passed, 117 skipped`; complete frontend is `5860 passed`. The live browser used
`/trajectory-bin?stride=20`, made no JSON trajectory fallback request, reached the loaded frame
status, and observed named phase rows. FULL backend remains deferred until the user opens the
repository's test-dedicated session.

**UX for any remaining >1 s phase:** retained labelled rows show topology/DCD initialization
(indeterminate until file counts are known), frame extraction/alignment (determinate by selected
frame), packing, byte download, decode, surface-strand handling and first-frame application. Rows
remain visible together until the load terminates; the existing AbortSignal and killable worker
preserve cancellation/error behavior.

**Decision + next candidate:** the transport iteration is complete. Do not keep tuning a 0.6 ms
packer while the warm route spends ~1.76 s in MDAnalysis context/extraction. Record the 30 GB DCD
offset/setup behavior as a future same-process candidate; advance now to CanDo relaxed-shape and
metrics visualization so the audit begins covering another active tab.

#### ITER-3 — CanDo predicted shape / static visualization — 2026-08-24

**State:** verified; retained-slow-with-progress; advance to the analogous SNUPI path.

**Fixture + scale:** archived completed job `080f75d47c3d` for `6hb_validated`: 14,410
nucleotides, 7,164 FEM axis nodes and 48 thermal normal-mode frames. Its job cache contained a
`684 KB` design snapshot, `5.3 MB` display payload, `516 KB` RMSF payload and `45 MB` thermal
trajectory. This is large enough to expose both browser object-allocation and WebGL scene costs.

**Full code path read:** CanDo job-row selection and all five visualization radios/status handling
in `cando_jobs_panel.js` → mode controller and thermal/flex/deviation/cylinder transforms in
`cando_display.js` → client transport → `routes_cando.py` snapshot/display/RMSF/thermal/deviation/
cylinder/shape-source routes → `cando_runner.py` cache generation and legacy cache reads, plus
`cando_deviation.py` and `cando_cylinders.py` → `design_renderer.js` external-scene lifecycle,
FEM overlay and crossover refresh → the complete `helix_renderer.js::applyFemPositions` instance
matrix, connector, slab-frame and overhang update path. `cando_metrics_card.js` was also read to
rule out eager graph fetching: selection merely enables its collapsed controls.

**Research:** [NumPy's `tobytes()` documentation](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.tobytes.html)
supports a contiguous numeric wire body instead of nested Python scalars. The official
[Three.js `InstancedMesh` documentation](https://threejs.org/docs/pages/InstancedMesh.html) says
instancing reduces draw calls, while the official
[resource-disposal guide](https://threejs.org/manual/en/how-to-dispose-of-objects.html) explains
that geometries allocate WebGL buffers and that disposal/recreation can incur a current-frame
performance penalty. Therefore the safe optimization order was: eliminate unused ensemble
frames, retain an already-instanced scene when the exact design fingerprint proves topology
identity, and column-pack the remaining representative conformation. It was not safe to reuse a
scene for an out-of-date/unknown fingerprint, nor useful to GPU-accelerate the already-cached FEM
result merely to display it.

**Benchmark/test + expectation:** the regression measures the complete real browser gesture from
the `Predicted shape` change event through final applied status, captures every named progress
mutation, and audits its requests. Direct endpoint samples separate server/cache/wire effects.
Backend packing and browser decoding have independent equivalence tests. Expected improvements
after reading the path were at least 80% less static-view wire data and at least 20% off the matched
full gesture; renderer work was expected to keep the gesture above one second, requiring retained
subprocess progress.

**Before:** every static mode downloaded/parses the entire 48-frame `44,184,003 B` ensemble even
though it displays only `representative_positions`/`representative_axis`. Direct samples were:
display `4,332,960 B` at `0.060759, 0.058992, 0.069652 s`; snapshot `8,046,798 B` at
`0.216389, 0.217884, 0.215054 s`; full thermal `44,184,003 B` at
`0.439477, 0.475391, 0.430573 s`. The exact browser gesture took `16,730 ms`, requested compressed
display/thermal/snapshot bodies of `853,092 / 20,122,567 / 1,108,748 B`, rebuilt the full scene,
and showed no subprocess indicator.

**Change (three reassessments of the same candidate):**

1. Cache and serve `thermal_representative.json`, deriving it once for legacy jobs; all modes now
   prefer it and skip the redundant display request when it already carries the predicted rows.
2. When the selected job reports `out_of_date:false`, use that fingerprint proof to retain the
   matching live instanced geometry. Unknown/stale jobs still fetch and render their own snapshot,
   preserving historical-job correctness.
3. Cache/serve versioned little-endian `CFRM` data: exact integer identity columns plus nine
   float32 visual coordinates per nucleotide and three per axis node, with one de-duplicated helix
   string table. The browser streams bytes with determinate progress, decodes the compact rows,
   and falls back to representative JSON on older/unavailable servers.

Every mode now yields so progress can paint and retains one row each for download, decode,
transform, snapshot build or exact-scene reuse, and visualization application. Flex/deviation/
cylinder-specific fetches get their own rows. A failed load retains an explicit failure row and
toast rather than silently clearing the status.

**After:** representative JSON alone was `5,063,009 B` (**88.54% smaller** than the ensemble),
with first legacy derivation `0.386679 s` and warm requests `0.062053, 0.063847 s`. `CFRM` is
`892,800 B`: **82.36% smaller than the compact endpoint and 97.98% smaller than the original
ensemble**. First derive/pack/delivery took `0.054278 s`; cached direct samples were
`0.001322, 0.000904 s`. The final matched browser gesture took `12,686 ms`, **24.2% faster** than
the `16,730 ms` baseline, meeting the stated complete-action expectation. One intermediate JSON +
snapshot pass measured `10,996 ms` and another retained-scene JSON pass `14,351 ms`, so these
headless whole-gesture numbers have real renderer/scheduling variance and should not be presented
as serialization-only precision. The final phase timeline is more diagnostic: from the first
mode phase to applied status, `4.193 s`; binary decode itself `13 ms`; transform, scene-yield and
apply each completed in the next heavily loaded headless render frame. The remaining pre-event
delay came from the large design finishing scheduled frames after job selection, not the cache
route.

**Correctness/equivalence:** all 14,410 helix/bp/copy/direction identities are exact; the observed
float32 maximum absolute error is `1.526e-5 nm`, below the `2e-5 nm` visual tolerance and WebGL's
float32 precision floor. Representative fields are exact subsets of the full cache; new jobs write
both sidecars, legacy jobs derive them; out-of-date jobs retain their snapshot route. Focused gates
pass (`3` backend and `65` frontend tests), repository FAST passes, complete frontend is
`351 files / 5,864 tests`, and the live real-fixture Playwright proof passes while observing the
binary route, no JSON/full-thermal/display/snapshot fallback, named retained phase rows, and final
thermal status. FULL backend remains deferred until the user opens a test-dedicated session.

**Decision + next candidate:** further transport work would tune a 13 ms decoder and a ~1 ms warm
route while WebGL frame/application work dominates. Keep the >1 s process visibly phased and
advance. SNUPI uses a sibling FEM UI and is the highest-value next audit: establish whether it
duplicates the old full-thermal/snapshot path or can share the proven CanDo representation without
crossing material-law/job-cache boundaries.

#### ITER-4 — SNUPI predicted shape / static visualization — 2026-08-24

**State:** verified; retained-slow-with-progress; action expectation missed, transport expectation
met; advance after reassessment.

**Fixture + scale:** archived completed static job `6f32b88f5a06` for `3x6x400_test`:
14,686 design nucleotides, 14,972 cached FEM display rows and 7,200 axis nodes. This is a distinct
SNUPI-material job/cache, not the CanDo fixture.

**Full code path read:** all SNUPI visualization modes and the trajectory player in
`snupi_display.js` → selection/retarget/status/error handling in `snupi_jobs_panel.js` → client
transport → `routes_snupi.py` snapshot/display/RMSF/trajectory/deviation/cylinders/shape-source
routes → `snupi_runner.py` cache creation, legacy cache reads, detached solve and progress. The
shared CanDo mappers plus the complete renderer instance-update path read in ITER-3 were rechecked
at the call boundary; SNUPI's material law affects the cached coordinates, not their renderer
addressing contract.

**Research:** Three.js' official
[`InstancedMesh` documentation](https://threejs.org/docs/pages/InstancedMesh.html) and
[resource lifecycle guide](https://threejs.org/manual/en/how-to-dispose-of-objects.html) support
retaining an exact already-instanced scene rather than disposing/recreating its GPU resources.
NumPy's official [`tobytes()` contract](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.tobytes.html)
supports reusing the tested static FEM column wire without coupling the SNUPI scientific solve to
CanDo. Fingerprint equality remains the safety gate; only the material-agnostic display protocol
is shared.

**Benchmark/test + expectation:** direct warm endpoint samples plus exact Playwright gestures on
the real design/job. A new live regression records request choice, status mutations and elapsed
time; unit tests pin historical snapshot behavior, current-scene reuse, all named phases and
legacy binary-sidecar derivation. Expected: remove the entire snapshot request/rebuild, reduce the
remaining display wire by at least 75%, and improve the complete gesture by at least 25%. The
wire expectation passed; the complete-action expectation did not.

**Before:** display `4,462,206 B` at `0.062837, 0.063766, 0.066724 s`; snapshot
`7,921,383 B` at `0.221663, 0.223215, 0.274477 s`; RMSF `486,963 B` at
`0.008642, 0.005342, 0.006079 s`; deviation `4,919,128 B` at
`0.357373, 0.224918, 0.352289 s`; cylinders `644,987 B` at
`0.059752, 0.192895, 0.054929 s`. Predicted shape took `12,625 ms`, fetched JSON display plus
snapshot, rebuilt the scene and exposed only the final `Showing predicted shape` text.

**Change + loop:** first, all five modes gained retained download/compute/transform/snapshot-or-
reuse/apply progress, explicit failure state, request cancellation continuity, and fingerprint-
gated live-scene reuse. Historical/unknown jobs still render their snapshot. That first pass
removed the snapshot but measured `14,695 ms`; its visible phase interval was `5.316 s`, dominated
by `3.463 s` display JSON transfer/parse. Reassessment kept the candidate: the second pass added a
SNUPI-owned `display.bin` sidecar/route using the tested `CFRM` integer-identity + float32 column
contract, streaming byte progress, a 23 ms decode, and JSON fallback. New solves write both caches;
legacy jobs derive binary once.

**After:** `922,808 B`, **79.319% smaller** than display JSON. First legacy derive/pack/delivery
was `0.055398 s`; warm direct samples `0.001382, 0.000932 s`. The progress-enabled visible phase
interval fell from `5.316 s` to `4.366 s` (**17.9% faster**). The whole gesture was `13,049 ms`,
which is **3.4% slower** than the original no-progress `12,625 ms` and misses the 25% expectation.
The apparent contradiction is measured rather than hidden: on this 14.7k structure every required
progress paint waits for an approximately `0.85 s` headless WebGL frame, offsetting the removed
network/scene work; pre-event selection/render scheduling also varies by seconds. Removing those
paints would violate this goal's UX contract. Further packing would tune a 23 ms decoder and ~1 ms
warm server route, so it is not an efficient next change.

**Correctness/equivalence + UX:** all 14,972 helix/bp/copy/direction identities are exact; observed
float32 maximum absolute error is `7.623e-6 nm`. Current jobs make no JSON display or snapshot
request; stale jobs preserve both fallbacks. Retained rows now name display download/decode,
RMSF/deviation/cylinders/trajectory fetches, transform, snapshot build or scene reuse, application,
and failures. Focused gates pass (`4` backend including shared CanDo checks; `38` frontend),
repository FAST is `7,204 passed / 117 skipped`, complete frontend is `352 files / 5,867 tests`,
and the real-fixture Playwright proof passes. FULL backend remains deferred until a user-opened
test-dedicated session exists.

**Decision + next candidate:** retain the visible phases and stop optimizing this 23 ms decoder.
Proceed to mrDNA's predicted-shape display, which still needs its own end-to-end audit; do not
assume its external simulation frame/schema or snapshot-current semantics match the FEM siblings.

#### Fixture audit — mrDNA predicted-shape display — 2026-08-24

Every archived mrDNA job, including the 14,774-nucleotide Voltron job, predates the required
`nucleotide_map.json`. The display, snapshot, and bead routes correctly reject them with HTTP 409
in 11–17 ms and instruct the user to rerun. The full frontend/controller/router/runner/decode path
was read, but this is not counted as an optimization iteration: manufacturing a tiny fixture or
bypassing the manifest guard would not measure the real process. Queue a representative completed
rerun; meanwhile advance to the next real, valid >1 s fixture.

#### ITER-5 — LAMMPS final-structure display — 2026-08-24

**State:** verified; optimized below one second at the backend, complete browser action still over
one second with per-subprocess progress; advance after reassessment.

**Fixture + full path:** completed CPU-fallback job `3bb1b170da66` on `6hbx100_noT`, 1,328
nucleotides and 101 trajectory frames. Read the complete display controller and oxDNA-panel LAMMPS
dispatch/status path, client request, `routes_lammps.py` dump-to-oxDNA cache/input resolution,
`composite_trajectory`, downsampling/alignment/flattening core, and both the full and bounded-tail
oxDNA readers through final `applyFemPositions` rendering. The final-structure route was paying for
the whole composite trajectory and then retaining only `frames[-1]`.

**Research + expectation:** Python's official
[`IOBase.seek`](https://docs.python.org/3/library/io.html#io.IOBase.seek) contract permits a negative
offset relative to end-of-stream, supporting a bounded suffix read proportional to one terminal
frame. NumPy's official [`linalg.svd`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.svd.html)
documents the SVD primitive already used by NADOC's Kabsch alignment, so the safe optimization is
to preserve that math and reduce the number of frames passed through it. Expected cold route at
least 4× faster and below 250 ms, with no complete-gesture regression; because the baseline gesture
exceeded one second, show determinate read/align, transform, and apply phases.

**Measurement + baseline:** a read-only Playwright gesture opened the real library design, selected
the unified LAMMPS row, chose Final structure, waited for the usable scene, counted requests and
timed the whole action. Baseline was `2,012 ms`, one `294,073 B` display response, and only the final
status. Direct warm route samples were `0.075192, 0.077918, 0.076882 s`; uncached sibling/full-scan
samples were `1.055633 s` and `0.524497 s`, and a new `align=false` cache key on the main fixture
was `0.426303 s`.

**Change:** `latest_aligned_trajectory_frame` reuses the production bounded-tail parser to seek and
parse only the latest complete frame, then runs the same PBC unwrap, topology plan, Kabsch SVD and
vectorized display flattening with the same loop-copy key order. The LAMMPS display route calls that
specialized core; the scrub trajectory remains unchanged. The controller/panel now retain one
labelled determinate bar each for `Read and align final frame`, `Transform final coordinates`, and
`Apply final structure` while work is active.

**After + comparison:** main aligned route samples `0.031573, 0.032075, 0.028884 s` (**2.5× warm
speedup**); main unaligned samples `0.030069, 0.029434, 0.026832 s` versus the cold-key baseline
`0.426303 s` (**14.7× by medians**). The two previously cold sibling jobs now return in
`0.053694 s` and `0.150651 s`, respectively (**19.7×** and **3.48×** against their recorded
full-scan calls); all are below 250 ms. The exact live browser gesture is `1,592 ms`, **20.9%
faster** than `2,012 ms`, despite deliberately yielding two render frames to expose client phases.
The under-250-ms and no-regression expectations pass; one sibling misses the aspirational 4× ratio
but the representative main cold-key result exceeds it substantially.

**Correctness + verification:** a parametrized regression compares every key and coordinate against
the legacy composite's final frame at `1e-12` for both `align=true` and `align=false`; both pass.
Focused frontend tests are `122 passed`. Repository FAST is `7,206 passed / 117 skipped`; complete
frontend is `352 files / 5,869 tests`. The real-fixture Playwright proof passes, observes exactly
one display request, all three progress phases, and the terminal final-structure status. FULL
backend is deferred until the user opens a test-dedicated session, per the gate output below.

**Decision + next candidate:** the backend is now tens of milliseconds and further tail/parser work
is not the dominant end-to-end cost. Retain the progress because the measured WebGL/browser action
is still 1.592 s. Advance to the cross-tab inventory with a real completed fixture; keep mrDNA at
the head of the queue once a manifest-current job exists.

#### ITER-6 — LAMMPS RMSF / mean-deviation selection — 2026-08-24

**State:** verified; cold backend below one second, complete render-bound action retained with
phase progress; two-pass loop met expectation.

**Fixture + full path:** same valid `3bb1b170da66` / `6hbx100_noT` fixture: 1,328 nucleotides,
101 frames. Read the RMSF/deviation controller and panel branches, client routes, both LAMMPS
routes, `production_rmsf` accumulation/alignment, its existing file-signature LRU wrapper,
geometry-deviation mapper boundary, and renderer updates. The route bypassed the existing cache;
the core rebuilt an identical topology/DFS unwrap plan per frame and dispatched a separate
three-vector `np.cross` per nucleotide.

**Research + expectation:** Python's official
[`lru_cache` guidance](https://docs.python.org/3/library/functools.html#functools.lru_cache) names
expensive repeated I/O/computation as the intended memoization workload and stresses bounded cache
size; NADOC already has a four-result, size/mtime-invalidated equivalent. NumPy's official
[`cross`](https://numpy.org/doc/stable/reference/generated/numpy.cross.html) supports stacked
vector inputs, matching the repository's tested batch helper. Expected at least 3× cold backend,
repeat under 100 ms, at least 25% complete-action improvement, exact output, and visible
analysis/transform/apply progress because renderer completion remains over one second.

**Baseline:** three direct RMSF calls were `2.350858, 2.491770, 2.439503 s` (`330,736 B`);
deviation was `2.434485, 2.470624, 2.430865 s` (`319,010 B`). The exact cold Playwright RMSF
gesture was `4,744 ms` and showed no intermediate status.

**Pass 1 + reassessment:** switched both routes to `production_rmsf_cached`, excluding its internal
tuple-keyed average frame from public RMSF JSON, and reused one vectorized unwrap plan per particle
key set. Cold RMSF improved only to `1.946118 s`, repeat to `0.005722 s`, and cached deviation to
`0.018301 s`; the progress-enabled full gesture regressed to `5,078 ms` because its two phase
paints exposed slow WebGL frames. The cold expectation missed, so the loop stayed on this process.

**Pass 2 + after:** replaced 134,128 scalar NumPy cross-product dispatches with one batched
`oxdna_backbone_sites` call per frame. Cold RMSF became `0.635825 s` (**3.84× faster** than the
baseline median) and repeat `0.004323 s` (**~565× faster**). The full gesture became `2,849 ms`,
**39.9% faster** than `4,744 ms`, while retaining phase paints. The live before/after JSON files
are byte-identical (`SHA-256 44f2dd4a…b667`, 330,736 bytes). All stated expectations pass.

**UX + verification:** RMSF now names `Read, align, and analyze trajectory`, transform, and apply;
mean deviation names its cached/compute phase plus transform and apply. The real Playwright proof
observes all phase rows and terminal statuses for final structure, RMSF, and deviation. Focused
checks pass (`3` backend, `124` frontend). Repository FAST is `7,208 passed / 117 skipped` and
complete frontend is `352 files / 5,871 tests`. FULL backend remains deferred until the user opens
a test-dedicated session, per the gate output.

**Decision + next candidate:** cold analysis is below one second and repeats are milliseconds;
further backend work no longer dominates the 2.849-second renderer-bound gesture. Keep its progress.
The next real uninstrumented LAMMPS visualization is the 15.7 MB trajectory player selection;
audit its JSON parse/transform/render path before returning to larger NAMD live-display debt.

#### ITER-7 — LAMMPS trajectory-player selection — 2026-08-24

**State:** verified; transport expectation met, complete action essentially renderer-bound with
progress; advance.

**Fixture + full path:** same real job, 101 simulation frames plus the design seed (102 displayed),
1,328 keys. Read the full player selection handler/status/control setup, LAMMPS controller JSON
fetch/parse/frame transform, client transport, JSON route, shared composite alignment/cache/packing,
NTRJ parser, and first-frame renderer application. Baseline direct JSON was `15,693,624 B` at
`0.636065 s` cold-cache and `0.110657, 0.111139 s` warm. Exact full Playwright selection was
`2,855 ms` with no intermediate status.

**Research + expectation:** MDN documents `Float32Array` as four-byte floats that can directly
view an `ArrayBuffer` at an offset, and [`Response.body`](https://developer.mozilla.org/en-US/docs/Web/API/Response/body)
as a readable stream suitable for determinate byte progress. Reuse the proven NTRJ schema and
streaming client rather than creating a LAMMPS-only protocol. Expected at least 75% smaller wire,
no complete-gesture regression after adding required phase paints, identity equality, float error
below `2e-5 nm`, and visible download/decode/transform/apply phases.

**Change:** added `/lammps/jobs/{id}/trajectory-bin` over the shared binary packer, uncompressed-
length header, streamed client byte progress, zero-copy shared decoder, JSON compatibility fallback,
and explicit decode/transform/apply paints. The JSON route remains unchanged.

**After + equivalence:** binary is `3,285,568 B`, **79.1% smaller**, delivered in `0.512192 s` on
first pack and `0.072439, 0.071277, 0.071361 s` warm. All 1,328 keys and 102 frames match; maximum
float32 error is `3.7662e-6 nm`. The full action is `2,817 ms`, only **1.3% faster** than `2,855 ms`:
the transport win is largely spent on the required WebGL-visible phase frames. The stated wire,
correctness, no-regression, and UX expectations pass; a large complete-action speedup was neither
observed nor claimed.

**Verification + decision:** focused backend route checks, the shared parser oracle, controller/
panel suite (`126` frontend tests), and live Playwright request/phase/terminal-status proof pass.
Repository FAST is `7,209 passed / 117 skipped`; complete frontend remains `352 files / 5,871
tests`. FULL backend remains deferred until the user opens a test-dedicated session. Further
packing would tune a ~71 ms warm route while renderer scheduling dominates. Retain progress and
advance to NAMD live Display-MD / large-DCD initialization; keep the 30 GB probe isolated and
cancellable so it cannot starve the active API.

#### ITER-8 — NAMD jobs-list / shared shell polling — 2026-08-24

**State:** verified; two-pass loop met wire and latency expectations; backend poll below one second.

**Fixture + full path:** real workspace with 67 NAMD jobs, including 13 historical RunPod jobs and
zero active RunPod jobs. Read `MdJob.list_jobs/load/to_dict`, complete `list_md_jobs` reconciliation,
RunPod liveness/repair, disk warming/progress decoration, client polling, unified-list normalization,
selection/detail WebSocket/REST refresh, timeline latest-per-segment use, metric latest-sample use,
and WC sparkline history use. Full scientific history stays in persisted `job.json` and the
single-job detail route.

**Research + expectation:** Python's official
[`dataclasses.asdict`](https://docs.python.org/3/library/dataclasses.html#dataclasses.asdict)
documentation establishes recursive nested conversion; copying and serializing every historical
sample on every poll is avoidable. Expected at least 60% smaller list wire, preserve latest state
for every segment and a useful recent sparkline, keep detail history exact, and reduce the
representative no-active-RunPod request below 100 ms without weakening active pod repair.

**Baseline:** `1,519,669 B`; direct full request samples `0.495779, 0.381937, 0.509424 s` (median
`0.495779 s`). One completed job contributed 467,488 bytes of its 1,035-sample health history.

**Pass 1 + reassessment:** compacted only the response to the latest record for every segment plus
a recent window, with explicit `health_samples_truncated/total` metadata and a UI `recent N of M`
tooltip. A 128-point window was 933 KB; 32 points was 683 KB; 16 points plus old-segment terminal
records reached ~598 KB. However, truncating after `asdict` left recursive copy cost, and request
latency remained ~0.39–0.49 s. The loop stayed on the candidate.

**Pass 2 + after:** compact request-local freshly-loaded job objects before recursive conversion,
then profiling showed all local load/reconcile/compact/dict work was only 14–15 ms. The remaining
~400 ms was an unconditional external RunPod `list_pods()` call despite no active RunPod job.
That probe is now conditional on a RunPod job being preparing/queued/running. Final samples are
`0.074782, 0.068540, 0.066481, 0.065678, 0.065284 s` (median `0.066481 s`, **7.46× / 86.6%
faster**) at ~`598,496 B` (**60.6% smaller**). The largest list history is 16 recent samples while
its detail route still returns all 1,035 samples (`471,356 B`, `0.007915 s`).
Parsing the saved real payload 200 times in the JavaScript runtime drops from `2.198 ms` median /
`2.876 ms` p95 to `0.911 ms` / `0.943 ms` (**58.6% lower median parse time**); list DOM work also
sees at most 16 recent samples per current segment instead of thousands.

**Correctness + verification:** focused tests pin recent-tail order, latest record for every older
segment, terminal-only RunPod no-probe behavior, and the existing active missing-pod repair/restart
path. No stored job is mutated. The response is now under one second, so no processing indicator is
required for this subprocess. Repository FAST is `7,211 passed / 117 skipped`; complete frontend
is `352 files / 5,871 tests`. FULL backend remains deferred until the user opens a test-dedicated
session.

**Decision + next candidate:** advance. The expensive 30 GB DCD initialization remains the highest
NAMD risk, but only run it in an isolated cancellable benchmark; otherwise audit Display-MD prewarm
on a representative smaller job first.

#### Fixture audit — NAMD Display-MD prewarm — 2026-08-24

The only small live trajectory is remote Alpine job `e6d49ff6d011` (`2hb_2-1xT`, 326 MB), but its
source `.nadoc` design is not present locally, so renderer-address equivalence cannot be validated.
The existing live Playwright proof loads a different 3x6 design and is therefore not a valid
substitute. Local completed trajectories begin around 10–20 GB and the prior 30 GB initialization
probe exceeded minutes. No new iteration was started near cutoff: obtain/rebuild the exact 2hb
design or provide an isolated cancellable large-DCD benchmark before resuming this candidate.

## Candidate queue (re-rank after every iteration)

1. **Obtain a manifest-current mrDNA predicted-shape / bead fixture.** All archived jobs return the
   intentional missing-`nucleotide_map.json` 409. Benchmark a representative rerun before deciding
   whether scene reuse, compact transport, or a different algorithm is valid.
2. **NAMD live Display MD and large-DCD initialization.** The scrub transport is complete, but
   WebSocket prewarm/display is a distinct path and the prior 30 GB probe exceeded minutes. Reproduce
   only in an isolated benchmark that reports/cancels without starving the API.
3. **Inventory and instrument remaining visualization selection latency across all five tabs.** These paths
   combine backend parsing/reconstruction with frontend geometry work and are explicitly subject
   to the per-subprocess progress rule. Start from real completed-job fixtures already in
   `workspace/`; record missing representative fixtures rather than substituting tiny mocks.
4. **NAMD preparation.** Known historical >1 s seams include solvation/package preparation;
   verify current code rather than trusting archived timings. Ensure preparation progress reaches
   the shared job UX.
5. **Remaining oxDNA RMSF/metrics, occupancy, and atomistic/surface reconstruction.** Revalidate
   cold, warm, sibling-lineage, and growing-file behavior; existing caches/vectorization are a
   baseline, not an exemption.
6. **Remaining CanDo/SNUPI FEM builds and SNUPI visualization/metrics extraction.** Separate assembly, solve,
   serialization, worker startup, deviation/RMSF, and client cylinder/geometry costs.
7. **mrDNA conversion/package/decode/display.** Separate model generation, external runtime,
   output decode, curvature, bead/deformed geometry, and input preview.
8. **Shared shell latency and polling.** Measure engine switch, `/simulate/jobs`, active-job scan,
   normalization/tree flattening, selection, status propagation, comparison, and redundant polling.
9. **Original Phase-C UX debt below.** Resolve contextual Run/Stop/Resume and duplicated status/
   progress surfaces while applying the >1 s progress contract consistently.

## Original UX baseline (still binding)

- Simulate header collapsible; per-engine header collapse removed. **[DONE]**
- Periodic MD section removed from the frontend. **[DONE]**
- Unify card styling, name, order across engines. **[DONE for naming; order = `CARD_KEYS`]**
- All job status output / loading bars / buttons into ONE global master Job status card
  reflecting the selected engine. **[PARTIAL — oxDNA, LAMMPS, NAMD feed it; mrDNA + CanDo don't]**
- Every job-initiating button flips to **Stop** while its job runs; a stopped job's button flips
  to **Resume**. Across all engines. **[oxDNA + NAMD only]**

## Where the code actually lives (probed 2026-07-28)

| Thing | Path | State |
|---|---|---|
| Run-control primitive | `frontend/src/ui/job_run_control.js` — `RUN_ACTION`:19, `runControlState`:34 | live; imported by `simulate_jobs.js:29`, `oxdna_jobs_panel.js:32`, `md_jobs_panel.js:37` (RUN_ACTION only) |
| oxDNA context button | `oxdna_jobs_panel.js` — `isRelaxRunning`:232, `_runControl`:1201, `_stopSelected`:1217, `_resumeSelected`:1224, dispatch:1237 | live |
| NAMD run control | `md_jobs_panel.js` — `mdRemoteAwaitingSubmit`, `mdJobIsRunning` / `mdJobIsStartable` / `mdJobIsResumable`, `mdRunControl` (over `runControlState`), `_paintRunControl` | **DONE 2026-08-03**: ONE control (`#md-jobs-run-btn`) for the selected job — Run / Stop / Resume — beside `＋ New job` (`#md-jobs-new-btn` → the Job Wizard) in `#md-launch-row`. `#md-jobs-job-ctl-btn` + `#md-jobs-prod-btn` deleted, with `mdSelectedJobControl` / `mdProductionAction` / `_paintJobControl`. See `project_md_job_system.md`. |
| Master jobs card | `frontend/src/ui/simulate_jobs.js` — `masterProgressPct`:103 + `_pct1`:95 (**one decimal**, so a long production leaves 0 % in minutes not hours — see [[project_md_job_system]]), `masterStepText`:213 (exported) + `_etaSuffix`:207 (**time remaining, for EVERY engine** — BLADE/SNUPI no longer append their own), `_stepTotal`:191, `formatEta`:276 (now coarsens to `2d 06h`) | live; **only importer is `main.js:207`**. Panels notify it by `window.dispatchEvent('nadoc:sim-jobs-changed')` → listener `simulate_jobs.js:691` |
| mrDNA panel | `frontend/src/ui/mrdna_jobs_panel.js` (579 ln) | **no** `job_run_control` import; `coarseBtn`/`fineBtn`/`stopBtn`:202-218, launches:345, stop:459, own bar `#mrdna-jobs-progress` painted:416 |
| CanDo panel | `frontend/src/ui/cando_jobs_panel.js` (721 ln) | same shape — buttons:268-286, launch:409, stop:649, own bar painted:603; plus `initCandoMetricsCard` (`cando_metrics_card.js:32`) wired at :323 |
| Collapsible base | `jobs_panel_base.js` — `collapsible` param:86, gate:115, force-open:140 | 6 panels pass `collapsible:false` (md:956, mrdna:256, oxdna:1064, blade:281, cando:347, snupi:322) |
| Simulate section | `#simulate-body` `index.html:3679` ← `main.js:2413` `initJobsPanelBase(… arrowStyle:'class')` | live |
| Engine selector | `engine_selector.js` — tablist:92, `.engine-selector-btn`:96, `renderStrip`:131, `stripMount`:68 · `#engine-capability-strip` `index.html:3688` ← `main.js:2292` · `engine_capabilities.js` `CARD_KEYS`:53 `CARD_LABELS`:57 | live |
| Stop relocation | `main.js:2236` `_moveStopBelowLaunch` — covers **oxdna/mrdna/cando only** (:2246-2248); NAMD deliberately excluded (morphs in place); blade/snupi use `_moveRunControls`:2229 | live |
| Anchors halo | `oxdna_anchors_setup.js` — `_dispatch`:88, single `_emit`:96 · `main.js` `_anchorsByEngine`:2108, `_refreshAnchorGlow`:2109, listener:2115, engine-switch refresh:2308 | live, **no E-field gate**. Event payload is `{engine, anchors, glow, focusKey, highlighted}`; the halo consumes `highlighted`, not `anchors` |
| ~~Chain Simulations~~ | — | **REMOVED 2026-08-04** (user decision). The whole frontend went: `chain_sim_panel.js`, `chain_sim_model.js`, `stage_planner_model.js`, `chain_sim_endpoints.js`, the `#chain-sim-*` markup, and the `getChainMode`/`enqueueChainStage` wiring in `main.js` + the NAMD/oxDNA panels. Its one reusable piece, `surfaceOpposesField`, is now `frontend/src/ui/field_anchor_rules.js` (the mrDNA M8 guard's import). **Backend left alone**: `routes_chain_sim.py`, `chain_sim_projects` on the design, and the `MdPipeline` chain executor are all still live, so saved `.nadoc` files load unchanged. Replaced by the NAMD run queue → [[project_md_job_system]]. |
| Sequence guard | `routes_md.py:1169` calls `require_sequenced_scaffold` (`backend/core/md_sequence_guard.py:70`) before job creation; backstop `md_protocols.py:1807` | live; `tests/test_md_sequence_guard.py:55` (5 tests) |
| List progress | `routes_mrdna.py:237` / `routes_cando.py:192` — `progress_fraction` (4dp) + `eta_seconds` on running jobs only | live |

Note: tests live in **`tests/`**, not `backend/tests/` (earlier notes here had the wrong path).

## Original Phase-C UX debt (audited 2026-07-28; re-probe before editing)

1. **mrDNA contextual Run/Stop/Resume — unstarted.** `mrdna_jobs_panel.js` still has
   `coarseBtn`/`fineBtn` + a separate `stopBtn` toggled by `job.status === 'running'` (:425).
   Copy the oxDNA pattern (`_runControl`/`_stopSelected`/`_resumeSelected` off `runControlState`).
   Open question kept from the original plan: with two launch buttons (coarse vs fine), decide
   which one the context verb tracks — likely Coarse as primary.
2. **CanDo contextual Run/Stop/Resume — unstarted.** Identical shape (:268-286 / :612 / :649).
   Its two launches are linear vs nonlinear corotational; same verb question.
3. **Fold `#mrdna-jobs-progress` into the master card.** `index.html:4293` is `display:none` in
   markup but `mrdna_jobs_panel.js:416-419` un-hides it and paints the bar while running — so the
   user sees two progress bars. NAMD's `#md-jobs-progress` is already **gone** (removed as
   "superseded by the master bar", recorded in [[project_md_sidebar_audit]]) — that's the model.
4. **Fold `#cando-jobs-progress`** (`index.html:4479`, painted `cando_jobs_panel.js:603-606`) —
   same as (3).
5. **Decide the fate of the bespoke status/detail blocks:** `#mrdna-jobs-status` (:4290, written
   mrdna:299), `#mrdna-jobs-detail-status` (:4444), `#cando-jobs-detail-status` (:4610), the CanDo
   metrics card, and NAMD's Health/`#md-jobs-metrics`/`#md-jobs-timeline` (:5587-5602). The spec
   says consolidate; in practice the rich per-engine detail may be worth keeping *inside* the
   master card (oxDNA already delegates its detail via `selectJob`). Pick one rule and apply it.
6. **`masterStepText` has no consumer outside its own module + test** (`simulate_jobs.js:187`).
   Either it's genuinely used internally only and the export is dead surface, or a panel was meant
   to call it. Check before item 3/4 — the step line is what the folded bars should feed.
7. **`#oxdna-jobs-progress` is still painted into a hidden element** (`index.html:3791`
   `display:none`; written `oxdna_jobs_panel.js:1508/1618`). Harmless but wasted work — delete
   the writer when touching (3)/(4).

Not blockers, but note for whoever picks this up: `manual_validation_debt.md` (repo **root**)
still lists **MV-30** (Simulate collapse + static engine headers + Periodic-MD gone), **MV-31**
(context Run/Stop/Resume on oxDNA + NAMD) and **MV-32** (chain-sim round-trip) as open PENDING
rows. They were recorded as blocked by a doc-context limit (an API-`design/load`ed design isn't
the frontend's active document, so Playwright can't drive job selection). **That limit is now
worked around** — see "Gesture-level verification" below; MV-30/31/32 are re-runnable.
MV-32 has a known duplicate-ID collision flagged at that file's L80.

## Job selection: click the selected row to DESELECT (2026-08-01)

`#simulate-jobs-list` is the ONE list the user clicks — every engine panel's own list is
`display:none` in `index.html` (the oxDNA one carries the comment saying so at :3860). Clicking a
row that is already selected now clears the selection instead of being a no-op.

**The rule: deselecting is not a job switch, so it discards nothing.** Whatever the job loaded
(trajectory frames, RMSF/deviation/strain map, the deform overlay, a live MD stream) stays on
screen and in its controller; only selecting a DIFFERENT job unloads/retargets it, exactly as
before. What clears is the row highlight, the master card, `#simulate-job-actions`, and the
engine panel's detail block.

| Where | What was added |
|---|---|
| `simulate_jobs.js` | `_deselect()` next to `_select()`; row `onClick` toggles; routes to the owning panel's `deselectJob()` (LAMMPS → `oxdnaPanel`, since it hosts the LAMMPS viz) |
| every engine panel | `_deselectJob()` + a `deselectJob` export. cando/snupi/blade deliberately skip `_retargetDisplayToSelection`; oxDNA skips `_setTrajOff`/`_clearRunCards` **and does not fire `nadoc:oxdna-job-selected`** (its listeners stop a running Live session and rebuild the export card — that's a job-switch reaction, not a deselect one) |
| cando/snupi/blade | `_syncDisplayModes` keeps the **"Off" radio enabled** whenever the display is active. Every other mode locks with no job selected; without this the lingering overlay could only be taken down by re-selecting the job |
| mrdna | the display/beads checkbox handlers no longer early-return on "no selection" for the **off** branch (same reason) |
| md | `_userDeselected` sticky flag — `_selectBestJob` runs on every poll and would re-select a beat later. `_selectDisplayJob` now prefers `_displayJobId` when nothing is selected, so deselecting can't jump the live display to another job |
| oxdna | new `_trajJobId` (who the loaded frames belong to). The "Unload trajectory?" confirm keys off it, not `_selectedId` — those differ after a deselect, and re-selecting the job whose trajectory is already up must not offer to unload it |

Pinned by: `simulate_jobs.test.js` (3), `oxdna_jobs_panel.test.js` (2 — incl. "deselect does not
unload the trajectory"), `md_jobs_panel.test.js` (2 — incl. "the poll does not re-select").

## Job NAMES: "relax N" roots, and the animation dropdown reuses them (2026-08-02)

Root rows used to be labelled `jobDisplayName(job)` = the design-file stem. One list is one
design, so **every relaxation rendered as the same string**; only the `[N]` position and the
timestamp told them apart. Roots are now **"relax 1", "relax 2", …**

- `oxdna_jobs_panel.js` — `relaxIndexMap(jobs)` (job_id → 1-based number) + `relaxRowLabel`.
  Numbering is **per design, by `created_at` ascending**, over the FULL job set: creation order
  means an existing relax keeps its number when a newer one starts, and using the full set means
  hiding a design (or archived runs) never renumbers what stays. Same rule `flattenJobTree` uses
  for the `Run N` children — so the two numbers are read the same way, and `[N]` (newest-first
  list position) legitimately differs from the relax number on the same row.
- `simulate_jobs.js` scopes the map to the oxDNA **group** (oxDNA + its LAMMPS CPU fallback) so
  "Show all job types" can't shift the numbers.
- NAMD roots deliberately keep `design_name` — a NAMD root is not always a relaxation
  (`mdHasAppendedProduction`), so "relax N" would lie there.
- `md_jobs_panel.js` gained **`mdChildLabelFor(job, index)`** — the production / replica / refit
  dispatch lifted out of `mdJobRowCtx` so other lists name NAMD children identically.
- **The animation panel's trajectory dropdown now mirrors a Simulations row.**
  `animation_panel.js` `normalizeTrajJobs` runs each engine's jobs through `flattenJobTree` +
  the label fns above and returns `{…job, id, engine, depth, listIndex, label}`; children sort
  under their parent and are prefixed `↳` (a `<select>` collapses leading whitespace). Before
  this, the dropdown was a flat list where a relaxation and all of its production runs were the
  same design stem — so **`Run 7 [A][H][E]` was unpickable in practice**, which is what the user
  reported.

Pinned by `oxdna_jobs_panel.test.js` (7 — numbering, per-design, orphans, no-renumber),
`animation_panel.normalize.test.js` (4 — naming, tree order, depth/listIndex, NAMD labels).
The per-design filtering tests there now assert `data-job-id`, not the design name.

## Gesture-level verification — the doc-context limit is solved

`frontend/playwright.livedev.config.js` + opening the design through the **welcome-screen library
row** (not `POST /design/load`) gives a spec a real active document on the user's own dev servers,
so job selection IS drivable. `frontend/e2e/job_deselect.spec.js` is the worked example: pinned
`?doc=`, read-only w.r.t. jobs, walks all five engine tabs that have jobs on this machine
(oxDNA/NAMD/CanDo/SNUPI on `3x6x400_test`, mrDNA on `6hb_2xT`; BLADE has no jobs here).

Two gotchas it cost a run each to learn:
- **Screenshot the part from OUTSIDE it.** Dollying inside the structure amplifies sub-pixel
  camera drift into a wholly different image, so byte-comparison of two "identical" frames fails
  for reasons that have nothing to do with the feature. Always take a static A==A baseline first.
- The unified list's selection is an **inline `background`** on the row (`jobs_panel_render.js`),
  not a class — assert `el.style.background !== ''`.

## Verification + debt

- Each slice gated on `just test-frontend` (vitest) + `just smoke` (23/23).
- Tests pinning the shipped parts: `job_run_control.test.js` (9), `md_jobs_panel.test.js`
  (mdRunControl Run/Stop/Resume **+ the queue matrix** — the "always ▶ Relax" matrix and `mdSelectedJobControl` were removed with the button merge),
  `field_anchor_rules.test.js` (6 — the one helper rescued from chain-sim),
  `tests/test_md_sequence_guard.py` (5). The chain-sim vitest files went with the panel;
  `tests/test_routes_chain_sim.py` (8) + `tests/test_chain_spawn_dispatch.py` (7) still pass
  against the untouched backend.
- Gesture-level verification is blocked by the doc-context limit above → the MV rows.

Related: [[project_md_job_system]] · [[project_md_engines_panel]] (install gates — prepend to
`#oxdna-jobs-body`/`#md-panel-body`) · [[project_md_panel_status]] (trajectory viewer, separate) ·
[[project_md_sidebar_audit]] (NAMD sidebar layout; owns the `#md-jobs-progress` removal) ·
[[manual_validation_debt]]. U-track lives in `SIM_COVERAGE_PLAN.md`.
