# Desktop optimization rounds

Goal: rank the next three operations from measured cost, likely user benefit, confidence and implementation risk; implement, validate correctness and paired performance, update the evidence, then rank again. Component benchmarks do not certify end-to-end desktop latency.

## Round 1 — selected 2026-10-22

| Rank | Operation | Evidence at selection | Expected benefit and risk | Status |
|---|---|---|---|---|
| 1 | Native display geometry output construction (D08) | 189 ms median for 96 helices / 16,128 nucleotides; diagnostic profile identifies per-row output work | Reduces CPU on geometry refresh. Optimize serialization/allocation only; placement semantics and constants stay fixed. | Implemented and validated with exact paired output; independent broad-suite failures documented |
| 2 | Large atomistic renderer initialization (D30) | 40–54 ms CPU at 150k atoms | Benefits opening and switching representations. Inspect buffer/instance setup; preserve every atom, bond, colour and picking identity. | Implemented; two paired CPU runs, full frontend suite and isolated browser pixel/picking checks passed |
| 3 | Assembly connector enforcement (D22) | 12.2 ms median at 500 independent mates | Benefits constrained child movement; profile remaining repeated connector/transform work. Preserve propagation order, fixed-instance rules and exact transforms. | Float64 conversion optimization implemented; paired state checks and 109 focused tests passed; FAST suite completed with existing failures documented |

These are three distinct operation families, not three subfunctions counted as a completed round. Geometry has the largest measured cost and a narrow allocation opportunity. Renderer setup is next by current measured CPU cost. Connector enforcement has a smaller cost but an existing reproducible benchmark; it is selected ahead of unknown browser bottlenecks until phase-attributed measurements justify a new ranking. Earlier FEM/renderer speedups are already present and are not counted as new work.

### Operation 1: native geometry output

`_geometry_for_helices` now converts direction and helical-site columns to Python lists once per helix block, and computes the existing paired azimuth subtraction once per pair. It previously created NumPy row views and separate list conversions for every nucleotide. The change does not modify placement formulas, coordinates, phase constants, selection rules, emitted record ordering or authority validation.

The temporary column lists are bounded by the current helix block, not all design nucleotides. Unoccupied slots can incur temporary conversion work before the existing occupancy filter; no claim of peak-memory improvement is made.

Paired, alternating baseline/current runs, two warmups and 15 measured calls per variant, GC enabled:

| Helices × 84 bp | Baseline median | Candidate median | Speedup |
|---|---:|---:|---:|
| 6 | 5.373 ms | 4.816 ms | 1.116× |
| 24 | 27.366 ms | 23.492 ms | 1.165× |
| 96 | 187.988 ms | 175.888 ms | 1.069× |

All measured outputs match the baseline JSON bytes exactly. Nineteen additional correctness cases cover empty input, straight/bent/twisted/swept/partially occupied designs, helix filtering, compact skips, insertions/deletions, a five-prime extension, outside-helix domains and square lattice. Input design serialization is unchanged in all those cases. This is a modest CPU improvement, not a measured FPS gain. The 6-helix p95 increased from 26.164 to 29.125 ms; with 15 samples this is the maximum and does not establish a tail improvement. Larger fixture p95 improved in this run. Raw samples and hashes: [round1_geometry_emission.json](round1_geometry_emission.json).

Reproduce from the repository root:

```sh
scripts/validation_guard.sh env PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python scripts/benchmark_desktop_geometry_emission.py \
  > docs/benchmarks/desktop/round1_geometry_emission.json
```

The harness loads the original function from pinned Git revision `2f3b962966b4917d9f626e486d56680306600363` into a separate namespace; it never checks out or replaces files. Both variants share unchanged placement helpers. It checks every timed output outside the timing interval and leaves user designs/jobs untouched.

Validation: `tests/test_design_geometry_core.py`: **18 passed**; `tests/test_native_compact_geometry.py`: **12 passed**. Lint and diff whitespace checks passed.

Required `just test-smart` chose **FAST (fast suite only)**: **14,706 passed, 9 failed, 92 skipped, 4 errors**, 159.75 s. Its deferral was:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

Five failures (streptavidin replay ×2, scadnano metadata round trip, photoproduct export status, MD RMSF argument binding) and all four CPD preview setup errors reproduce with the original geometry function loaded in memory. No source files were swapped. The NAMD provenance test passes in isolation with both original and current geometry, leaving its suite/order dependency unresolved. See [baseline recheck](round1_baseline_recheck.txt) and [focused triage](round1_focused_triage.json). Do not claim the overall suite is green.

Three IPC failures were caused by the test invocation's long Archive `TMPDIR`, not geometry: native motion passes using a short alias; pytest resolves symlinks, so Alpine needs a physically short Archive path. All **12 Alpine tests pass** there, including the previously timing-out process test at 1.21 s. [Short-path evidence](round1_alpine_short_path.txt).

The guard also flagged four over-budget tests. Followed `.claude/skills/triage-slow-tests/SKILL.md`: inspected their subprocess/durable-write behavior, reran them in isolation, and corrected the socket-path setup. None required a marker/budget change on focused evidence. The other calls measured 0.26 s, 0.28 s and 2.68 s; their original broad-run delay is not reproduced. [Triage record](round1_slow_triage.json). A second `just test-fast` with physical short Archive scratch finished: **14,709 passed, 6 failed, 92 skipped, 4 errors in 131.34 s**, with **zero per-test timing violations**. The guard still flags aggregate time above 90 s for this 14,808-test inventory; no evidence warrants moving individual tests or weakening budgets. All three IPC failures disappeared. Five remaining failures and all four setup errors reproduce with the original geometry; the provenance failure remains suite/order-dependent. Full log: [corrected FAST run](round1_fast_short_path.txt). Temporary test artifacts were removed after verification; `round1_scratch.json` records the exact task-owned paths and cleanup counts.

Round 1 component implementation and paired validation are complete for all three operations. Broad-suite debt remains documented; this is not a claim that the repository suite is green.


### Operation 2: atomistic renderer initialization

The [sampled Node profile](round1_renderer_profile.json) places most self time in `_rebuild`, with smaller colour, bond-matrix and Three.js initialization costs. The implemented candidate replaces the temporary serial-to-row `Map` during bond construction with a bounded integer lookup when serials are safe integers occupying no more than 16 slots per atom. It indexes relative to the minimum serial, caps storage at 16 MiB, preserves duplicate last-row-wins behavior, and explicitly rejects nonnumeric lookup keys. Empty, noninteger, nonnumeric or extremely sparse inputs use the unchanged Map semantics. Columnar inputs with implicit row serials retain their direct indexing path. No atom/bond filtering or transform calculation changes.

The initial paired benchmark alternates old/current order, uses three warmups plus 15 samples, and compares every visible instance matrix, colour, alpha, count and buffer usage. Both object and columnar formats and ballstick/VDW/stick modes are checked. Additional serial-identity tests cover holes, duplicates, negative IDs, high offsets, nonnumeric identities, missing bond endpoints and huge sparse spans.

| Atoms | Format | Before median | After median | Speedup |
|---|---|---:|---:|---:|
| 30,000 | Object | 6.826 ms | 5.842 ms | 1.168× |
| 30,000 | Columnar | 6.419 ms | 5.305 ms | 1.210× |
| 150,000 | Object | 41.883 ms | 30.719 ms | 1.363× |
| 150,000 | Columnar | 45.120 ms | 30.531 ms | 1.478× |

This is **27–32% less CPU time** for the 150k fixture, not measured first-useful-frame latency or GPU FPS. Raw results: [round1_renderer_init.json](round1_renderer_init.json). Peak process memory was not measured; the lookup allocation cap is a code bound, not an RSS claim. Confirmation [run](round1_renderer_confirmation.json), including duplicate/missing/noninteger/string bond endpoint cases, also passed exact-buffer comparisons. Its speedups were 1.192× / 1.267× at 30k (object/columnar) and 1.207× / 1.101× at 150k. Thus observed large-fixture CPU reductions ranged from **9–32% across the two runs**; do not treat the initial 27–32% as a stable machine-independent effect.

**Frontend validation:** 730 test files passed; **8,440 tests passed, one skipped**, including five new serial-index tests. [Suite log](round1_frontend_tests.txt). **Browser validation:** one isolated Chromium check passed in 6.3 s. All 18 image comparisons (three render modes × spheres/impostors × initial/selected/coordinate-updated states) matched the pinned baseline pixel hashes exactly, with visible content and identical picked atom serial 3. This used 400 synthetic atoms/380 bonds inside the running desktop renderer, not a timed full-document user workflow or physical-GPU acceptance. [Browser evidence](round1_browser_isolated.txt).

The first attempt used the standard browser config, which starts lifespan/job services against the shared workspace. It was explicitly interrupted after background trajectory precompute was observed; that preparation reported an existing placement-source conversion error. The observed derived-cache files predate that browser attempt and were preserved; no before snapshot supports a broader claim about all job metadata. The successful retry uses the new `playwright.desktop-benchmark.config.js`, an empty Archive workspace and `--lifespan off`. [Incident record](round1_browser_startup_incident.json). Future desktop benchmarks must use this isolated setup.

Cleanup verified all test documents/stores and isolated credentials absent, no remaining process references to task scratch, and then removed both task-owned scratch trees (about 2.48 GB logical file bytes, including sparse test files) and the short-path alias. User caches were not removed. Compact results remain tracked under this report. [Artifact inventory](round1_browser_artifacts.json), [cleanup](round1_scratch.json).

Reproduction:

```sh
scripts/validation_guard.sh node frontend/scripts/benchmark-desktop-render-init.mjs
scripts/validation_guard.sh node frontend/scripts/benchmark-desktop-render-init.mjs --profile
```


Browser reproduction (from the repository root, with Archive mounted and `.development-artifacts` resolving there):

```sh
mkdir -p .development-artifacts/desktop-renderer-check/workspace .development-artifacts/desktop-renderer-check/tmp
scripts/validation_guard.sh env \
  TMPDIR="$(realpath .development-artifacts/desktop-renderer-check/tmp)" \
  NADOC_WORKSPACE="$(realpath .development-artifacts/desktop-renderer-check/workspace)" \
  frontend/node_modules/.bin/playwright test desktop_renderer_init.spec.js \
  --config=frontend/playwright.desktop-benchmark.config.js \
  --output="$(realpath .development-artifacts/desktop-renderer-check)/captures"
```

Use a fresh, empty workspace and inventory paths before running. After servers stop, inspect/retain the concise result and remove only that run's task-owned workspace, scratch and captures. The config refuses a missing/nonabsolute workspace. Do not use the standard config for this benchmark: disabling session autosave alone does not disable background job services.

### Operation 3: connector enforcement — implementation and focused validation complete

[Diagnostic profile](round1_connector_profile.json): five 500-mate postpasses spend 24.3 ms cumulative in 10,000 `Mat4x4.from_array` calls, 19.2 ms in 5,000 world-connector lookups and 13.4 ms in 15,000 `to_array` calls (instrumented totals; nested costs overlap). The next candidate is eliminating Python scalar iteration when converting float64 transform arrays to model lists, while retaining Pydantic validation, C-order flattening, scalar values and ownership. Any implementation must prove exact complete instance/base transforms and joint state against the baseline; the old aggregate checksum alone is insufficient. The float64 conversion optimization is now implemented: exact `numpy.ndarray` float64 inputs use C-order `ravel().tolist()` before the same Pydantic constructor. Other dtypes and subclasses (including masked arrays) retain the original scalar-conversion path. It changes no transform formula, traversal order, fixed-instance behavior or validation rule.

Paired runs use two warmups and 15 samples, alternating original/current classmethod descriptors outside the timer. Fixture copies, full-state serialization and comparisons are also outside the timer. Every instance field (including transform and base transform), every joint field, and visited sets match exactly after each pair. Mixed chain/star cases include rotations, fixed nodes and absent base transforms; separate cases include missing connector labels and world anchoring.

| Fixture | Before median | After median | Speedup |
|---|---:|---:|---:|
| 1 independent mate | 0.0230 ms | 0.0194 ms | 1.185× |
| 100 independent mates | 2.0205 ms | 1.7219 ms | 1.173× |
| 500 independent mates | 12.3432 ms | 10.8667 ms | 1.136× |
| Rotated chain subtree, 100 instances | 0.2269 ms | 0.1941 ms | 1.169× |
| Rotated star subtree, 100 instances | 0.2367 ms | 0.1896 ms | 1.248× |
| Chain FK control, 100 instances | 0.0568 ms | 0.0454 ms | 1.251× |
| Star FK control, 100 instances | 1.0275 ms | 0.8842 ms | 1.162× |

The 500-mate workload uses about **12% less CPU time** in this run. These are backend kernels, not desktop drag latency. [Raw samples and hashes](round1_connectors.json).

**Focused validation:** **109 passed** across matrix conversion (17), FK (13), connector core (27), assembly models (38) and core models (14). Tests preserve bit patterns, signed zero, nonfinite values, C-order flattening of strided/Fortran/reversed arrays, independent ownership, dtype/subclass fallbacks and inherited validators. [Results](round1_matrix_tests.json). Required `just test-smart` selected FAST: **14,726 passed, 6 failed, 92 skipped, 4 errors in 138.71 s**, with the same remaining failures/setup errors as the earlier corrected run. FULL remains deferred because no test-dedicated session is open. [Suite log](round1_matrix_test_smart.txt). Two trajectory-thinning tests exceeded the 5 s call budget during the broad run; the four related cases passed in isolation in 3.66 s, with the flagged calls taking 0.35 and 0.45 s. Their small fixtures do not warrant slow markers or budget changes. Aggregate suite timing debt remains. [Focused timing recheck](round1_matrix_slow_recheck.txt), [triage](round1_matrix_slow_triage.json).

```sh
scripts/validation_guard.sh env PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python scripts/benchmark_desktop_connectors.py
```

The new benchmark loads the original `Mat4x4.from_array` method from pinned Git source, patches it only in its own single-threaded process, and restores the current descriptor after each sample. No files are checked out and no user designs/jobs are opened.

## Round 2 — selected 2026-10-22

Refreshed screening after round 1 uses current working-tree code and synthetic, isolated fixtures. Selection weighs absolute CPU cost, interaction frequency potential and availability of exact-output controls; actual user-frequency telemetry is unavailable. Ranking is provisional if profiling finds no safe opportunity.

| Rank | Operation | Current screening cost | Implementation investigation |
|---|---|---:|---|
| 1 | Detailed surface generation (D34) | 2,913 ms, 6 helices × 84 bp; 1,050,316 vertices / 2,102,000 faces | Profile mesh construction, ownership and smoothing allocations; retain exact vertices, faces and ownership, with CPU path fixed. |
| 2 | Native geometry refresh (D08), remaining computation | 169 ms, 96 helices × 84 bp | Profile remaining work after round 1; optimize repeated lookup/allocation without changing placement math. Repeated coverage of D08 does not count as a new mapped family. |
| 3 | Atomistic live updates / interpolation (D32) | 12.13 / 10.03 ms, 150k atoms | Inspect repeated per-frame transform/buffer work; preserve exact buffers, atom/bond identity and visible output. |

Coarse surface generation is 63.4 ms. History replay screened at 0.01–4.29 ms and is deferred behind these three. Its screening command returned exit 1 for two threshold flags: patches-1, 0.926→0.980 ms; patches-4, 0.939→0.991 ms. Those compare the harness's historical evaluator control to current code, not a new round-2 change. Retain the flags; five batches are insufficient to establish their stability. They are timing flags, not reported correctness mismatches. Playback controls were exact for all eight measured cases. Surface controls were exact for both details. None of the control ratios constitute a new optimization claim.

[Commands, source hashes and screening output](round2_screen.json), [history details](round2_history_screen.json). Round 2 is in progress: selection is complete; operation 1 has an initial candidate below; operations 2 and 3 await implementation.

### Operation 1: detailed surfaces — initial candidate

The [three-build diagnostic profile](round2_surface_profile.json) identifies repeated normal calculations inside local refinement (681 calls, 0.673 s cumulative). Candidate validation computes face normals, then scoring immediately recomputes the same normals for the same candidate. The implementation passes the already computed array into scoring. Arithmetic, thresholds, trial order, smoothing, vertex ordering and ownership rules are unchanged.

[Seven paired samples](round2_surface_remesh.json), after one warmup per variant, alternate only the original/current `remesh_sharp_patches` function from the pinned Git baseline. This is important: the older surface-generation harness swaps surface exports but shares remeshing helpers, so it cannot independently validate this change. Every output vertex and face byte, ownership list, dtype and input design serialization matches in the new harness.

| Detail | Before median | After median | Speedup |
|---|---:|---:|---:|
| Coarse control | 62.00 ms | 59.75 ms | 1.038× |
| Detailed, local remesh enabled | 2,811.15 ms | 2,774.85 ms | 1.013× |

The detailed change is only **1.3%** in this first run. Coarse does not exercise this optimization; its larger apparent improvement demonstrates timing noise. Do not claim a stable whole-build gain from this run. Confirmation or a more targeted remeshing measurement remains necessary before accepting this candidate as a completed optimization.

Five focused remeshing tests passed in 1.36 s; [test log](round2_surface_tests.txt). Lint passed. Required `just test-smart` selected **FAST**: **14,726 passed, 6 failed, 92 skipped, 4 errors in 159.45 s**, with the same six failures and four setup errors documented in round 1. [Suite log](round2_surface_test_smart.txt). Its FULL deferral remains:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

Six per-test timing flags were inspected and rerun through focused guards. All six passed, with calls from 0.18–2.72 s. They cover small durable-write workflows and stubbed job preparation, not a heavy solver. No markers or budgets changed; aggregate suite timing debt remains. [Triage](round2_surface_slow_triage.json), [focused results](round2_slow_rechecks.json). Round 2 remains incomplete.

Targeted confirmation captured 12 intermediate meshes (1,028,448 input vertices) from the detailed build, then alternated original/current remeshing over 15 paired samples after two warmups. Median remeshing time fell **1,030.84→992.49 ms (1.039×, 3.7% less CPU)**. Every vertex/face byte and ownership list matches; inputs remain unchanged. This supports a small remeshing gain, consistent with the 36 ms whole-build difference, not a broad 3.7% desktop latency claim. [Samples and normal-call counts](round2_remesh_kernel.json). The coarse control timing variation is not attributed to this change.

### Operation 2: geometry metadata — candidate in validation

The refreshed [geometry profile](round2_geometry_profile.json) attributes 32.45 ms cumulative / 25.60 ms self to `_strand_nucleotide_info` for 96 helices. The candidate reads strand ID/type/reference status once per strand and helix/direction/overhang ID once per domain, and reuses the existing lookup key for unpaired membership. It preserves dictionary construction, traversal order, endpoint comparisons, flexible flags and placement mathematics. A new benchmark alternates only that helper, sharing round-1 emission in both variants, so round-1 gains cannot be counted twice. Exact full-output comparisons and paired results are pending in `round2_geometry_metadata.json`.


Geometry metadata focused validation: **57 passed, one skipped** across core geometry (18), compact geometry (12) and flexible segments (27). [Results](round2_geometry_tests.json). Nineteen paired edge fixtures also match full geometry JSON bytes. The [initial timing run](round2_geometry_metadata.json) performed extra reference allocations during comparisons; [confirmation](round2_geometry_metadata_confirmation.json) precomputes that reference outside the loop. Confirmation whole-geometry medians: 6 helices **4.770→4.620 ms**, 24 **22.596→21.823 ms**, 96 **161.669→163.520 ms**. The largest fixture does **not** demonstrate a whole-geometry improvement; do not count this candidate as a completed optimization yet. The metadata-only result at 96 helices is unusually large and may be influenced by cyclic-GC timing. A separately labelled GC-disabled diagnostic is queued to separate allocation work from collection scheduling; it cannot replace the GC-enabled latency evidence. Required `just test-smart` is running, with results pending in `round2_geometry_test_smart.txt`.

Operation 3 profiling is prepared in `frontend/scripts/profile-desktop-playback.mjs`: warmed 150k-atom live updates and interpolation, sampled in Node under the serialized validation guard. Profiling output is pending in `round2_playback_profile.json`; no round-2 playback implementation has been made yet.


Geometry follow-up: the [GC-disabled diagnostic](round2_geometry_metadata_gc_diagnostic.json) shows metadata 6.390→5.003 ms and whole geometry 76.637→74.872 ms at 96 helices. This supports lower helper CPU cost but **does not establish improved GC-enabled large-design latency**. The candidate remains under evaluation; small-design GC-enabled improvements are about 3%.

Required geometry `just test-smart` selected **FAST** and finished **14,697 passed, 34 failed, 92 skipped, 5 errors in 132.02 s**. FULL remains deferred under the same test-session rule quoted above. New failures include missing-route/state HTTP 404s and capture/time-limit failures; they cannot be called cleared. Representative isolated A/B checks use a pytest plugin that loads only the original metadata helper in memory, preserving source files. Plate layout, bond relaxation, capture-conflict and expiry cases passed in both variants. The native endpoint assertion also passed in both variants, but its commands **returned exit 1** because the native-placement incident latch remains open. Thus a passing assertion is not a passing placement gate. [A/B records](round2_geometry_rechecks.json), [full log](round2_geometry_test_smart.txt).

The native-placement incident is retained at `.native-placement-review/incidents/20261023T052656-fe36cbab48aa/report.html`; it records a missing `h0` helix response (HTTP 404), not a numerical displacement. Other incidents from that suite remain recorded. No incident was acknowledged, removed or bypassed; a complete review is still required by `docs/native_placement_review.md`. The single timing violator, Alpine download-queue cancellation, passed in isolation at 0.26 s; no marker/budget change was made. Do not equate these focused findings with resolution of all 34 broad-suite failures.

### Operation 3: atomistic playback — candidate in validation

[Node profile](round2_playback_profile.json): bond-matrix writing is shared by live-frame updates and interpolation and accounts for 334/1,064 and 290/858 self samples respectively. The candidate reuses the already calculated bond length for normalization and writes the existing `Matrix4.compose` arithmetic directly to the destination instance buffer, avoiding temporary matrix writes/copies. Quaternion construction, midpoint arithmetic, degenerate-bond policy and output precision remain unchanged.

The new paired harness loads both the original renderer **and its original geometry-builder dependency** from pinned Git source. This avoids silently sharing the candidate helper with the baseline. [First measurements](round2_playback_candidate.json) preserve all compared matrix/color buffers exactly. At 150k atoms, interpolation is **8.472→7.585 ms (1.117×)** and live coordinates **9.800→9.063 ms (1.081×)**. Exact-snapshot/cluster paths are controls, with no claimed improvement. The 30k snapshot control regressed 0.884→0.989 ms in this run despite not using the changed writer; retain that noise signal rather than attributing every ratio to the change.

A deterministic 1,004-case matrix test now compares against the original Three.js `bondMatrix` path with Float32 and Float64 destinations, including axial/near-antiparallel/tiny bonds, varied radius, untouched offsets and degenerate handling. Frontend tests and the running-app attempt have finished; results and the unresolved placement gate are below. Round 2 is not complete.


**Playback validation result:** 730 frontend files / **8,441 tests passed, one skipped**, including the expanded matrix oracle, in 142.90 s. The command nevertheless returned **exit 1** from the placement-review reporter because four backend incidents remain unreviewed. [Full log](round2_frontend_tests.txt). This is not a green suite verdict.

**NOT VERIFIED IN APP:** the isolated Chromium attempt was blocked by the same positioning-integrity latch when the original renderer tried to add its first molecular mesh. No pixel comparison was reached. The gate was not bypassed or pointed at a fresh ledger. [Browser log](round2_browser.txt), [artifact inventory](round2_browser_artifacts.json). Task-owned browser trace/screenshot evidence is retained on Archive under `.development-artifacts/desktop-round2/placement-gate-browser/`. After confirming no process references remained, the temporary workspace, credentials and pytest scratch were removed; [cleanup](round1_connector_scratch.json). User designs/jobs and the incident journal were preserved.

[Playback confirmation](round2_playback_confirmation.json) retains 31 raw samples per variant, helper hash and independent baseline dependency. At 150k atoms it measured **1.358× interpolation** and **1.237× live-update** speedups with exact buffers. Across the two runs this is approximately **10–26% less interpolation CPU** and **8–19% less live-update CPU**; neither is a GPU or user-visible latency result. Snapshot/cluster controls remain separate.

**Round 2 acceptance remains open.** Surface refinement has paired component evidence. Geometry metadata has a lower helper CPU cost but no demonstrated large-design GC-enabled latency gain. Playback has paired CPU evidence and passing assertions, but app verification and the overall test gates are blocked by the retained native-placement incidents. Next work must diagnose and review those incidents without weakening the gate or replacing geometry oracles, then decide whether to retain/rework the geometry candidate and complete app verification before reranking.


Placement review progress: a failed comparison-fixture setup leaked the Python document context. A forced original-fixture failure reproduces the leak, and a controlled endpoint diagnostic reproduces **all four** recorded incident assertions only when that context is leaked. The fix registers cleanup immediately after context binding. Its regression passes; comparison tests pass (31 + 13), and all five endpoint assertions pass while the command still returns exit 1 for the retained latch. [Investigation and remaining review](placement_incident_review.md). No incident has been acknowledged or bypassed; app validation remains pending.


**Placement gate review completed:** four incidents were explicitly acknowledged after reproducing every failure under leaked context, fixing cleanup, inspecting 808 shared-frame site comparisons (zero deltas), and passing 97 scope assertions. Original reports remain intact. [Completed review](placement_incident_review.md), [clear gate](round2_placement_gate_check.txt). The five endpoint tests now pass with command exit 0.

**App verification still open for a different reason:** after the gate cleared, the browser comparison reached rendering. Diagnostic output shows exact instance matrix/colour hashes in all 30 mode/state cases and matching pixels in 29. Ball-and-stick impostors at exact snapshot differ in pixel hash despite identical buffers. No pixel threshold was relaxed. [Initial post-review attempt](round2_browser_verified.txt), [labelled buffer diagnostic](round2_browser_diagnostic.txt). Original-versus-original control is running with the same camera and acceptance checks in `round2_browser_control.txt`. Do not count the playback app check as passed.


**Playback app verification completed:** the original-versus-original control passed. The final controlled comparison uses the independently loaded historical `writeBondMatrix` with shared unchanged geometry/material exports, holding module/constructor duplication constant. It passed **30 exact pixel comparisons**, exact matrix/colour hashes, visible-content checks and identical picking across three modes, sphere/impostor options and five states. [Passing app result](round2_browser_writer_control.txt), [original/original control](round2_browser_control.txt). The earlier whole-module discrepancy is retained as a harness limitation: duplicated unchanged constructors/material modules were a confound; its exact rendering mechanism is not proven. No threshold, camera, molecule or production behavior was adjusted to obtain a pass. The observation adjustment followed the improve-debug-visibility skill. [Retry inventory and cleanup](round2_browser_retry_artifacts.json).

## Round 2 closeout and next selection

All three selected implementations now have independent correctness controls and component performance evidence. Surface refinement reduced its targeted kernel by 3.7%; playback improved interpolation/live-update CPU in both runs and passed the controlled running-app check. Metadata field reuse reduces helper CPU (22% at 96 helices with GC suppressed only during timing) and improved small-design GC-enabled geometry by about 3%; it is retained as a narrow helper optimization. **It does not demonstrate a GC-enabled large-design latency improvement**, and that limit must remain in any summary. The 96-helix GC-enabled full result remains approximately flat/slightly slower in the confirmation run.

The frontend's 8,441 assertions passed; its original command exited 1 on the then-open placement latch. That latch has since received complete explicit reviews and a clear gate check; this does not rewrite the historical command result. Backend broad-suite failures and FULL deferral remain separate debt. Temporary run scratch/workspaces were removed after dependency checks; retained failed captures remain on mounted Archive.

Round 3 selection is pending fresh screening. Prefer increasing coverage before returning to the same geometry helper: surface recolour/motion (D35), solvent/protein rendering (D36), and pending overhang connection CRUD (D11) have reusable harnesses. Screen their current costs and correctness controls before ranking or claiming they are the next best three. D03 file-open-to-visible and other E2E gaps remain high-value measurement work; synthetic kernel coverage is still only 13/54 current families and 21/54 with any linked timing evidence.


## Round 3 — selected after fresh screening

[Screening commands, current source hashes and complete outputs](round3_screen.json) refresh additional operation families. Historical-control ratios in that report are **not** newly implemented gains. Connection lifecycle/refusal/cleanup checks and the frontend exact-buffer controls all passed.

| Rank | Operation | Current screened cost | Next investigation |
|---|---|---:|---|
| 1 | Atomistic selection with scalar colours/fades (D38) | 65.94 ms at 150k atoms; cluster colours/fades 42.43 ms | Profile colour/selection resolution and avoid unused lookups without changing selection precedence or colour-space conversion. |
| 2 | Surface motion updates (D35) | 21.81 ms, 160k vertices / 318,402 faces | Profile topology/normal and buffer updates; preserve exact positions, normals, colours and topology. |
| 3 | Atomistic solvent updates (D36) | 8.18 ms, 100k waters + 25k ions | Profile repeated per-water/ion buffer work; preserve dynamic counts, species colours and bond matrices. |

Pending-connection CRUD (D11) is deferred: current create/patch/delete medians are roughly 2–4 ms on the screened 6/16-cell fixtures with up to 128 retained candidates. These in-process route measurements are not network/UI latency. Protein unchanged-refresh costs are below 0.7 ms, so it ranks behind solvent updates within D36. Surface recolour without motion is about 2.55 ms at 160k vertices. Revisit ranking as new evidence arrives; no usage-frequency telemetry is available.

### Round-3 implementations in progress

**Selection colours:** [profile](round3_colour_profile.json) identifies scalar/cluster resolution and per-row alpha lookup as material costs. The candidate resolves normal colour only after determining that selection does not override it, and avoids domain/base keys when the corresponding selection collection is empty. No colour priority, alpha calculation or colour-space conversion changes. The benchmark independently loads the historical colour resolver; sharing the current dependency would invalidate the control. [Initial samples](round3_colour_candidate.json): at 150k atoms scalar selection **60.257→51.875 ms (1.162×)**; 81 focused resolver/renderer tests pass ([log](round3_colour_focused.txt)). [Confirmation](round3_colour_surface_confirmation.json): scalar selection **72.551→52.437 ms (1.384×)**, but CPK selection worsened **5.652→9.482 ms** and cluster colours **38.343→42.100 ms**. These regressions need investigation/confirmation before acceptance; do not report a universal colour-speed improvement.

**Surface motion:** added an indexed Float32/Uint16-or-Uint32 normal calculation that preserves Three.js face traversal, arithmetic order, per-add Float32 rounding, repeated-index handling and normalization. Other attribute layouts/types use the original method. Only stable buffer-update paths use it; initial construction remains the existing implementation. [Paired whole-operation result](round3_colour_surface_confirmation.json): **21.119→4.711 ms (4.483×)** at 160k vertices / 318,402 faces, with exact positions, normals, indices and colour buffers. Repeated/recolour controls remain about 2.3 ms. **41 focused tests pass** ([log](round3_surface_focused_confirmation.txt)), including byte comparison with Three.js on changing/random, repeated-index, degenerate, isolated, empty and fallback cases. The initial test failure was an oracle-version assertion: cloning a BufferAttribute resets its version, so the test now correctly checks increment from the original destination's prior version; geometry bytes already matched. [Original test log](round3_surface_focused.txt).

**Acceptance pending:** surface motion still needs running-app verification and the full frontend command; selection still has mixed performance results; solvent implementation is pending. Round 3 is not complete.


### Round-3 refinement and validation

The colour slowdown repeated on CPK selection (**8.33→9.52 ms** at 150k atoms) in [repeat evidence](round3_colour_surface_repeat.json), while scalar selection still improved (**65.28→52.23 ms**). The revised candidate preserves the original `colorForAtom` path for ordinary colour modes and uses the lazy-selection resolver only when scalar/cluster maps are present. [Revised run](round3_colour_revised.json): CPK **6.002→5.651 ms**, cluster colours **39.337→38.067 ms**, scalar selection **60.594→52.547 ms**. This corrects the observed ordinary-mode regression in that run; confirmation remains important because the original CPK measurements varied.

[Solvent profile](round3_solvent_profile.json) sampled 514 hits in bond writes and 240 in water drawing, but only 15 in ion grouping. The implemented solvent candidate therefore combines oxygen, hydrogen and bond writes into one pass over each O,H,H record, reusing coordinates and buffer references. It leaves ion bucketing, counts/capacity, species/radii, matrix writers and degenerate-bond policy unchanged. [Initial paired result](round3_solvent_candidate.json): 100k waters + 25k ions **8.093→7.781 ms (1.040×)**; the 20k case is effectively unchanged (**1.598→1.592 ms**). Sphere-mode controls are effectively unchanged. This is a modest CPU result, not an FPS claim. The first report's sample arrays were sorted by its inherited median helper; confirmation preserves sampling order.

**111 focused tests passed** across colour resolver (21), atomistic renderer (60) and solvent overlay (30): [log](round3_colour_solvent_focused.txt). The full frontend command is running in `round3_frontend_tests.txt`. The new isolated browser check compares selection colours/fades, moving surface normals and solvent counts/modes against independent original controls. It reuses transformed Three.js dependency URLs to avoid the module-duplication confound found in round 2; a blank-scene negative comparison ensures actual visible content. [Artifact plan](round3_browser_artifacts.json). Browser and solvent confirmation results remain pending.


## Round 3 closeout — 2026-10-23

All three selected candidates have exact paired output checks and passed the running-app comparison. **731 frontend files / 8,444 tests passed, one skipped**; command exit 0, 143.60 s. [Full suite](round3_frontend_tests.txt). The isolated Chromium check passed in 6.4 s with **22 exact pixel comparisons**: 12 colour/selection states, four surface states and six solvent count/mode states. Each output differs from the blank-scene negative control and has visible content. [App evidence](round3_browser.txt). This is visible-output correctness on synthetic fixtures, not physical-GPU throughput or whole-document latency.

| Selected operation | Final before/after median | Evidence and qualification |
|---|---:|---|
| Scalar-coloured selection, 150k atoms | 54.497→49.786 ms (1.095×) | Revised resolver also improved CPK selection 7.139→5.766 ms. The unchanged no-selection cluster-colour control varied 34.738→36.306 ms; do not claim all colouring improved. |
| Moving surface, 160k vertices | 20.415→4.638 ms (4.402×) | About 77% less CPU, consistent with the prior 21.119→4.711 ms run. Exact normal/position/colour/index buffers and app pixels match. |
| Atomistic solvent, 100k waters + 25k ions | 8.130→7.821 ms (1.040×) | About 3.8% less CPU, matching the earlier 8.093→7.781 ms result. At 20k waters the result is effectively flat/slightly slower (1.598→1.606 ms); sphere controls unchanged. |

[Final colour/surface samples and source hashes](round3_final_colour_surface.json), [solvent confirmation](round3_solvent_confirmation.json). Original and revised colour measurements remain retained so the rejected broad shortcut and its CPK regression are visible. The accepted lazy path is confined to scalar/cluster maps; ordinary colour resolution retains the original implementation.

Temporary workspaces, browser captures/credentials and test scratch were removed after a process-reference check. Compact logs remain in this report. [Browser cleanup](round3_browser_artifacts.json), [scratch cleanup](round3_validation_scratch.json). Original unrelated backend broad-suite failures and FULL deferral are still documented, not cleared by these frontend checks.

Round 4 will screen backend/document operations and expand remaining gaps before selecting its next three. Candidate areas are history recording/replay, durable save/recovery and library browsing. No ranking or implementation claim is made until their current costs are measured.


## Round 4 screening — document operations

[Current document component measurements](round4_document_screen.json) use disposable Archive fixtures, 24 helices and 0/100/1000 retained history entries, with seven GC-enabled samples including the first call. JSON and revision-load results are checked against the complete original model. Revision commits change the snapshot each time and retain the production flush/replace path; this is filesystem-specific timing, not UI save latency. Folder browsing tests 100/1000/10000 entries, 10% directories. All fixture directories were removed by failure-safe temporary-directory cleanup.

| Operation | Current median | Interpretation |
|---|---:|---|
| Folder picker, 10,000 entries | 24.968 ms | Clear candidate: current enumeration constructs and stats paths for every visible entry and sorts files that are never returned. |
| Portable JSON decode, 1,000 history entries | 5.869 ms | Candidate for profiling; preserve legacy migration and malformed-input behavior before choosing a parser change. |
| Portable JSON encode, 1,000 history entries | 3.428 ms | Existing native serializer; no obvious safe shortcut established. |
| Revision load, 1,000 history entries | 10.715 ms | Includes bounded decompression, checksum, validation and portable-source checks. |
| Unique revision commit | 125–348 ms across fixtures | Storage flush dominated; history size does not explain the nonmonotonic medians. |
| History recording, 24 helices / 100 entries | 0.989 ms major / 1.096 ms minor | Lower priority in this screen; not a 1,000-entry or undo/redo measurement. |

[History recording screen](round4_history_screen.json) refreshes an existing historical comparison; its ratios are **not newly implemented gains**. [Revision profile](round4_revision_profile.json) attributes 865 of 981 ms over five commits to 15 `fsync` calls (about 88%). Those flushes must remain. Compression accounts for about 54 ms and portability inspection about 14 ms. A separate level-3 compression probe halves compression CPU (10.574→4.947 ms) but grows this synthetic snapshot from 70,188 to 74,235 bytes; level 6 was not faster. No compression-policy change has been implemented or accepted.

Next ranking must distinguish avoidable CPU from required durability. Folder enumeration is the strongest supported candidate. Portable-source inspection and decode need focused profiling/contract review before finalizing the remaining two operations; avoid declaring three winners simply because three were measured. No round-4 production optimization is implemented yet. Coverage now includes fresh document I/O, folder-picker and history-recording components, while UI stalls, session-cache recovery, actual library search and end-to-end save remain gaps.

Round-4 scratch was removed after process/file/mapping reference checks. Completed round-2 failed browser captures were also pruned under the artifact policy; compact failure logs, hashes, review reports and passing-control evidence remain. Earlier statements that those raw captures are retained are historical and superseded by this cleanup. [Exact paths, bytes and verification](round4_scratch.json).

### Round 4 selection after focused CPU screening

[Paired pre-change screen](round4_cpu_screen.json) compares unchanged current functions with pinned originals, so ratios here are noise controls, not gains. Ranked by measured cost, scaling and implementation confidence:

1. **Folder enumeration (D06):** 23.93 ms / 10,000 entries. Use directory-entry metadata, skip hidden entries and files before sorting, retain symlink-following and error handling.
2. **Portable-source audit during save/load (D04):** 11.85 ms / 10,000 history entries (1.19 ms / 1,000). `command_input` eagerly evaluates its fallback `getattr` even when `op_kind` exists. Avoid that unused lookup; every source closure/integrity check still executes.
3. **Document UTF-8 byte admission (D04):** 2.37 ms / 64 MiB ASCII and 1.55 ms / 8 MiB in this run. For a built-in ASCII string, character length is exactly byte length. Return after the existing length gate; retain incremental UTF-8 checks for Unicode and subclasses. This is a small transport-kernel gain, not a whole-save gain.

The three are distinct operations, two within D04. These choices favor safe, measured CPU reductions over changing compression/storage policy or parser/migration semantics. Large synthetic history/text fixtures establish scaling, not typical user frequency. The initial document decode and compression candidates remain unchanged.

### Round 4 paired results and focused validation

Implemented all three selected CPU changes. [First run](round4_candidate.json) and [confirmation](round4_confirmation.json) independently load pinned original functions and alternate 21 before/after samples; output equality is checked before timing. Current source hashes are retained.

| Operation | Confirmation before → after | Scope |
|---|---:|---|
| Folder enumeration, 10,000 entries | 26.234 → 5.274 ms | ~80% less CPU/warm filesystem time; drive discovery held constant in both arms. |
| Source audit, 10,000 snapshot entries | 11.906 → 2.560 ms | ~78% less CPU; 1,000 entries 1.193 → 0.253 ms. No source validation omitted. |
| ASCII text admission, 64 MiB | 2.439 → 0.002 ms | Removes the encoding/slicing pass; candidate is near timer overhead, so avoid a large precise speedup claim. |
| Unicode admission control, 8 MiB UTF-8 | 2.088 → 2.088 ms | Existing bounded encoding path retained. |

**93 focused tests pass**: folder navigation 5, document transport 28, command dispatch 5, portable sources 32, revision store 23. [Command exits](round4_focused_results.json); per-file logs share the `round4_focused_` prefix. New checks cover hidden/case-tied/symlink directories, permission and missing-path statuses, UTF-8 exact limits including empty strings and surrogates/subclasses, and history command identity precedence. Existing source-integrity and revision-store tests cover source refusal, hashing, branch publication and recovery. An initial attempt passed multiple files to the single-target `test-focused` wrapper and was rejected before running tests; that log is retained in `round4_focused.txt`. The corrected per-file commands all exited 0.

Required `just test-smart` is running; round 4 acceptance remains pending its result and timing/failure triage. No frontend behavior changed in this round. No new molecular placement, topology, compression level, parser semantics or persistence flush policy was introduced.

## Round 4 closeout — 2026-10-23

All three selected implementations have repeated paired component evidence and passing focused correctness checks. Required `just test-smart` selected **FAST** and exited 1: **14,740 passed, six failed, 92 skipped, four errors**, 128.68 s pytest / 132 s wrapper. [Full log](round4_test_smart.txt). The six failures are the same named set recorded before this round: two native streptavidin lifecycle checks, NAMD old-job provenance, scadnano photoproduct metadata, photoproduct export fail-closed status, and RMSF cleanup argument mismatch. The four CPD-preview setup errors also match the earlier recorded set. No claim is made that the broad suite is green or that its historical failures have been repaired.

The selector reported verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

The [timing report](round4_slow_candidates.json) identifies one per-test violation: `test_steer_field_session_rejects_empty_waypoints`, 5.32 s. Following `.claude/skills/triage-slow-tests/SKILL.md`, inspection found mock specimen preparation and a live-session refusal check, not a production simulation. Its focused rerun passed in 2.73 s total (1.36 s call, 0.82 s setup): [triage log](round4_timing_triage.txt). This supports suite-load sensitivity; the run does not establish the exact source of contention. No budget or slow classification changed, and the aggregate overrun remains documented debt.

Round 4 therefore closes its selected implementation/paired-evidence work with **93 focused assertions plus the isolated timing check passing**, while broad-suite failures and FULL deferral remain outstanding. The changes retain every source-integrity and byte-limit gate and every persistence flush. They do not establish end-to-end save, open or UI latency gains. Round 5 should expand desktop-visible coverage—file open, feature/history panels and assembly rendering—before repeating these small document kernels. Rank the next three only after fresh measurements.

Owned round-4 implementation/test scratch was removed after checking process cwd, executable, open-file and memory-map references: 12,812 files, 2,437,180,672 bytes. [Cleanup verification](round4_implementation_scratch.json). Compact benchmark samples, source hashes and test logs remain.
