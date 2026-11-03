# ITER-6 — LAMMPS RMSF / mean-deviation selection — 2026-08-24 — supporting detail

[Topic head](../../project_simulate_panel_overhaul.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
