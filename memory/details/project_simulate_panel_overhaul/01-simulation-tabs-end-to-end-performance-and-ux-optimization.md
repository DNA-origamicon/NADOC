# Simulation tabs: end-to-end performance and UX optimization — supporting detail

[Topic head](../../project_simulate_panel_overhaul.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

## CanDo thermal progress (2026-09-27)

Thermal predictions report each of 48 reconstructed/saved frames, reference setup,
fluctuation statistics and representative reconstruction. The unified progress bar
uses these backend labels; thermal work has a larger phase weight and the obsolete
size-only ETA is suppressed when measured phase progress exists. Cancellation is
checked at these boundaries, and terminal status overrides stale progress files.
Numeric ensemble storage and job-local reference reuse cut measured BigO frame
reconstruction from ~51 s to ~9.5 s, preserving coordinates within 1e-12 nm.
See [audit](../../../docs/audits/cando_thermal_optimization_20260927.md) for scope and tests.

## Assembly FEM execution (2026-09-27)

CanDo/SNUPI creation now requests `simulation_only=true` from assembly flattening:
the canonical Design is loaded for engine input, but no full Design/geometry payload
is synchronized into the browser. Compact/full preparation cache keys are distinct.
Job result/lifecycle reads use their immutable snapshot; assembly displays never reuse
the live part renderer based on the projection fingerprint. Complete creation handlers
run in the API worker pool (including counts, fingerprints, revisions and hydro preflight).
CanDo CPU contention and both panels' preparation-error cleanup are fixed.
FEM polling now shares the revision fingerprint cache with oxDNA/MD; no-RMSF node
counts come from the actual FEM axis, excluding unpaired terminal nucleotides.
See [execution audit](../../../docs/audits/assembly_fem_execution_20260927.md) for full BigO
native timing, browser validation and explicit expensive-mode coverage limits.

## Assembly browsing correction (2026-09-27)

Opening Simulations no longer materializes the assembly for availability, policy,
job lists, status, stop/cancel or archives. `api/simulation_context.js` separates
passive requests from explicit design consumers by method and route; preparation
failure aborts the dependent request. Recommendation GET carries no body (Chromium
rejected the old `null` body). Assembly policy counts each source once off the event
loop; unified jobs use `flat_<assembly id>` without loading a Design. NAMD's source
path now follows the assembly host like the other engines. Prepared input and job
lifecycle parity retain the shared engine implementations. Source-count estimates
are advisory; prepared topology remains authoritative. Validation and scope:
[assembly Simulations audit](../../../docs/audits/assembly_simulations_20260927.md).

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
