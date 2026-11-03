---
name: project_simulate_panel_overhaul
description: "Active simulation-tab optimization plan — end-to-end backend performance, visualization latency, job UX, and honest phase/progress reporting across CanDo, SNUPI, mrDNA, oxDNA/LAMMPS, and NAMD"
metadata: 
  node_type: memory
  type: project
  originSessionId: 68f44bf0-ff75-46c4-b4fc-6c7576403328
---

# Simulation tabs: end-to-end performance and UX optimization — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

The August two-hour optimization run is closed. Its timing and test results remain dated evidence. Continue only a user-selected bounded task; preserve the one-second rule, candidate equivalence loop, honest progress, and representative app validation. The current optimization contract and candidate queue are indexed below.

November 2, 2026: unused simulation viewers must remain inert during edits and
feature-log seeks. CanDo/SNUPI cleanup restores shared render state only after
that controller has acquired the scene (including a pending compact load).
MD and oxDNA edit-driven freshness checks require known jobs for the current
part; the unified list retains a successfully loaded empty result across edits.
Panel opens, document switches and job actions still discover jobs. Empty MD
lists arm neither prewarm nor remote polling timers; discovering a real job
restarts the applicable work. A pending discovery still invalidates its freshness
on edits, and remote polling rechecks for new active jobs before shutting down
after its final refresh. Regression coverage lives in
`simulation_jobs_idle.test.js`, `simulate_jobs.test.js`, the CanDo/SNUPI display
tests and `feature_seek_representation.spec.js` (real UI, rendered-image equality
after heavy reconstruction finishes, and no job/result requests during empty
part edits/scrubs).

<a id="simulation-tabs-end-to-end-performance-and-ux-optimization"></a>
- [Simulation tabs: end-to-end performance and UX optimization](details/project_simulate_panel_overhaul/01-simulation-tabs-end-to-end-performance-and-ux-optimization.md#simulation-tabs-end-to-end-performance-and-ux-optimization)

<a id="cando-thermal-progress-2026-09-27"></a>
- [CanDo thermal progress (2026-09-27)](details/project_simulate_panel_overhaul/01-simulation-tabs-end-to-end-performance-and-ux-optimization.md#cando-thermal-progress-2026-09-27)

<a id="assembly-fem-execution-2026-09-27"></a>
- [Assembly FEM execution (2026-09-27)](details/project_simulate_panel_overhaul/01-simulation-tabs-end-to-end-performance-and-ux-optimization.md#assembly-fem-execution-2026-09-27)

<a id="assembly-browsing-correction-2026-09-27"></a>
- [Assembly browsing correction (2026-09-27)](details/project_simulate_panel_overhaul/01-simulation-tabs-end-to-end-performance-and-ux-optimization.md#assembly-browsing-correction-2026-09-27)

<a id="optimization-contract"></a>
- [Optimization contract](details/project_simulate_panel_overhaul/01-simulation-tabs-end-to-end-performance-and-ux-optimization.md#optimization-contract)

<a id="scope-every-active-simulation-tab-surface"></a>
- [Scope: every active simulation-tab surface](details/project_simulate_panel_overhaul/01-simulation-tabs-end-to-end-performance-and-ux-optimization.md#scope-every-active-simulation-tab-surface)

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

<a id="benchmark-record-template"></a>
- [Benchmark record template](details/project_simulate_panel_overhaul/02-benchmark-record-template.md#benchmark-record-template)

<a id="current-optimization-iterations"></a>
- [Current optimization iterations](details/project_simulate_panel_overhaul/02-benchmark-record-template.md#current-optimization-iterations)

<a id="iter-1--oxdna-view-trajectory--2026-08-24"></a>
- [ITER-1 — oxDNA View trajectory — 2026-08-24](details/project_simulate_panel_overhaul/02-benchmark-record-template.md#iter-1--oxdna-view-trajectory--2026-08-24)

<a id="iter-2--namd-view-trajectory--2026-08-24"></a>
- [ITER-2 — NAMD View trajectory — 2026-08-24](details/project_simulate_panel_overhaul/02-benchmark-record-template.md#iter-2--namd-view-trajectory--2026-08-24)

- [ITER-2 — NAMD View trajectory — 2026-08-24 — continued detail](details/project_simulate_panel_overhaul/03-iter-2--namd-view-trajectory--2026-08-24.md)

<a id="iter-3--cando-predicted-shape--static-visualization--2026-08-24"></a>
- [ITER-3 — CanDo predicted shape / static visualization — 2026-08-24](details/project_simulate_panel_overhaul/03-iter-2--namd-view-trajectory--2026-08-24.md#iter-3--cando-predicted-shape--static-visualization--2026-08-24)

- [ITER-3 — CanDo predicted shape / static visualization — 2026-08-24 — continued detail](details/project_simulate_panel_overhaul/03-iter-2--namd-view-trajectory--2026-08-24.md)

<a id="iter-4--snupi-predicted-shape--static-visualization--2026-08-24"></a>
- [ITER-4 — SNUPI predicted shape / static visualization — 2026-08-24](details/project_simulate_panel_overhaul/04-iter-4--snupi-predicted-shape--static-visualization--2026-08-24.md#iter-4--snupi-predicted-shape--static-visualization--2026-08-24)

- [ITER-4 — SNUPI predicted shape / static visualization — 2026-08-24 — continued detail](details/project_simulate_panel_overhaul/04-iter-4--snupi-predicted-shape--static-visualization--2026-08-24.md)

<a id="fixture-audit--mrdna-predicted-shape-display--2026-08-24"></a>
- [Fixture audit — mrDNA predicted-shape display — 2026-08-24](details/project_simulate_panel_overhaul/04-iter-4--snupi-predicted-shape--static-visualization--2026-08-24.md#fixture-audit--mrdna-predicted-shape-display--2026-08-24)

<a id="iter-5--lammps-final-structure-display--2026-08-24"></a>
- [ITER-5 — LAMMPS final-structure display — 2026-08-24](details/project_simulate_panel_overhaul/04-iter-4--snupi-predicted-shape--static-visualization--2026-08-24.md#iter-5--lammps-final-structure-display--2026-08-24)

<a id="iter-6--lammps-rmsf--mean-deviation-selection--2026-08-24"></a>
- [ITER-6 — LAMMPS RMSF / mean-deviation selection — 2026-08-24](details/project_simulate_panel_overhaul/05-iter-6--lammps-rmsf--mean-deviation-selection--2026-08-24.md#iter-6--lammps-rmsf--mean-deviation-selection--2026-08-24)

<a id="iter-7--lammps-trajectory-player-selection--2026-08-24"></a>
- [ITER-7 — LAMMPS trajectory-player selection — 2026-08-24](details/project_simulate_panel_overhaul/05-iter-6--lammps-rmsf--mean-deviation-selection--2026-08-24.md#iter-7--lammps-trajectory-player-selection--2026-08-24)

<a id="iter-8--namd-jobs-list--shared-shell-polling--2026-08-24"></a>
- [ITER-8 — NAMD jobs-list / shared shell polling — 2026-08-24](details/project_simulate_panel_overhaul/05-iter-6--lammps-rmsf--mean-deviation-selection--2026-08-24.md#iter-8--namd-jobs-list--shared-shell-polling--2026-08-24)

<a id="fixture-audit--namd-display-md-prewarm--2026-08-24"></a>
- [Fixture audit — NAMD Display-MD prewarm — 2026-08-24](details/project_simulate_panel_overhaul/05-iter-6--lammps-rmsf--mean-deviation-selection--2026-08-24.md#fixture-audit--namd-display-md-prewarm--2026-08-24)

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

<a id="where-the-code-actually-lives-probed-2026-07-28"></a>
- [Where the code actually lives (probed 2026-07-28)](details/project_simulate_panel_overhaul/06-where-the-code-actually-lives-probed-2026-07-28.md#where-the-code-actually-lives-probed-2026-07-28)

<a id="original-phase-c-ux-debt-audited-2026-07-28-re-probe-before-editing"></a>
- [Original Phase-C UX debt (audited 2026-07-28; re-probe before editing)](details/project_simulate_panel_overhaul/06-where-the-code-actually-lives-probed-2026-07-28.md#original-phase-c-ux-debt-audited-2026-07-28-re-probe-before-editing)

<a id="job-selection-click-the-selected-row-to-deselect-2026-08-01"></a>
- [Job selection: click the selected row to DESELECT (2026-08-01)](details/project_simulate_panel_overhaul/06-where-the-code-actually-lives-probed-2026-07-28.md#job-selection-click-the-selected-row-to-deselect-2026-08-01)

<a id="job-names-relax-n-roots-and-the-animation-dropdown-reuses-them-2026-08-02"></a>
- [Job NAMES: "relax N" roots, and the animation dropdown reuses them (2026-08-02)](details/project_simulate_panel_overhaul/06-where-the-code-actually-lives-probed-2026-07-28.md#job-names-relax-n-roots-and-the-animation-dropdown-reuses-them-2026-08-02)

<a id="gesture-level-verification--the-doc-context-limit-is-solved"></a>
- [Gesture-level verification — the doc-context limit is solved](details/project_simulate_panel_overhaul/06-where-the-code-actually-lives-probed-2026-07-28.md#gesture-level-verification--the-doc-context-limit-is-solved)

<a id="verification--debt"></a>
- [Verification + debt](details/project_simulate_panel_overhaul/06-where-the-code-actually-lives-probed-2026-07-28.md#verification--debt)
