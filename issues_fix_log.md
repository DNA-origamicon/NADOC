# Issues fix log

## ISSUE-269 — Autoscaffold replay changes joined-cluster identities and tether order (2026-11-27)

[x] Joined-cluster crossovers use the recorded Autoscaffold routing namespace.
Replay preserves the recorded flexible-connection order and anchor selections.
Eight focused tests passed and two optional local-design tests were skipped.
Four rebuilt wheel layouts independently replayed after reopening.
## 2026-11-25 — EM smooth playback and calculated-field crossfades

- [x] EM uses 500 ms smooth segments and joins both fields to molecular endpoint
  preparation. Cache misses hold a saved endpoint; pause/scrub restores its solve.
- [x] Unequal adaptive clouds crossfade by opacity without per-subframe geometry
  uploads, numerical field invention, or changes to archive/molecular histories.
- [x] Protect active/pending fields, including background reads promoted to demand.
- [x] 246 focused frontend tests and the real-EM application flow pass. Gold and
  EM remain rendered; dense DNA is consistently hidden in the software-WebGL
  test. Full-scene hardware appearance is tracked in MV-EM-SMOOTH.
- [x] Main.js task delta: zero. Original source hash unchanged.
- Smoke: 26 passed, two skipped, one assembly setup timeout at its part-save
  request (scene_harness.js:355). No EM failure; test artifacts cleaned.

## 2026-11-24 — ISSUE-267: Complete EM scope and sustained playback buffering

- [x] Stable selected-frame count; missing pages collected into optical inputs.
- [x] Playback no longer cancels every unfinished field request.
- [x] Direct NumPy serialization and bounded compact field storage measured.
- [x] 194 frontend tests, six API tests, and the real-EM app flow pass.
- [x] Source design hash unchanged; main.js task delta zero.

## 2026-11-24 — ISSUE-266: Foreground trajectory download ownership

- [x] Animation cache pruning preserves active visualization page reads; explicit
  cancellation still stops them. Foreground leases end when reads settle.
- [x] Six download tests and 166 shared visualization-controller tests pass.
- [x] The isolated browser loads the Plasmonic test trajectory across the
  representation transition, calculates both EM frames, changes persistent dot
  size and disables the overlay without console errors. Original source hash
  remains unchanged. Dense DNA is hidden only in the software-WebGL trajectory
  check; gold positions and EM rendering remain live. The separate standalone
  EM browser check exercises the DNA and gold scene together.

## 2026-11-24 — ISSUE-265: EM default-shell rejection detail

- [x] Preserve API error details and report actual gap/shell dimensions.
- [x] Offer explicit bare-mode recovery without changing model assumptions silently.
- [x] Eight frontend and ten backend tests pass; isolated app check covers untouched
  defaults, rejection, recovery and coated solve. Design hash unchanged and
  temporary artifacts removed. `main.js` task LOC delta: zero.
## 2026-11-23 — ISSUE-264: Profile and reduce Corner calculation overhead

- [x] Profile native recording and both molecular projections separately.
  Recording/routing is subsecond; closure, seed fitting and cache charging dominate.
- [x] Accelerate seed costs with the original scalar types, cross products without
  fastmath, immutable closure offsets and scalar memory accounting. Preserve the
  native solver, two-pass order, exact cache keys and memory bounds.
- [x] Paired cold backend previews improve by 21–24%; changed-direction previews
  improve by 11–19%. Add a bounded native construction benchmark with no saved parts.
- [x] Exact cost/seed-solver comparisons and all four approved geometry cases pass;
  physical override isolation and unchanged unrelated junction atoms pass too.
- [x] 36 focused backend checks pass, including cache ownership/charges,
  worker cancellation, exact native projection equivalence, source isolation,
  prepared Apply and independent native recipe replay. Backend/test and benchmark
  lint pass. `main.js` LOC delta: 0.
- [x] 6HB and square live workflows pass preview, Apply, undo/redo and history
  edit; both axis displays were inspected. The combined square case exhausted
  its 240 s total budget; a focused isolated rerun passes in 3.9 min with no
  code or timing-limit change. Cleanup verified after both runs. App-run cold
  previews remain about 16–19 s; do not claim the backend gain as a browser gain.
- [ ] The 1–2 second Full-preview target is still unmet; approved seam fitting
  remains the major cost. No production physical simulation was run.

## 2026-11-23 — ISSUE-268 / ISSUE-269 / ISSUE-270: Reuse Corner preview and clip axes

- [x] Commit the exact recorded/replayed candidate and its Full/undeformed
  projections using a bounded, source-owned, single-use preview token.
- [x] Preserve source/session/revision/policy and parameter checks, native undo,
  edit recovery, save/reopen and independent replay. No molecular refit on Apply.
- [x] Prepare independent projections concurrently; test exact serial-provider
  equivalence and cancellation cleanup for both numerical workers.
- [x] Reuse the feature-editor save hold to avoid autosave invalidation during
  preview; verify drain, cancel, document reset and real saved-file workflows.
- [x] Draw curved axes within a single occupied domain too. Unit regressions and
  6HB / flat square app checks pass; both applied views were inspected.
- [x] Nine focused backend and 59 frontend tests pass; lint passes. Apply starts
  responding in 0.38–0.82 s, with complete scene refresh in 4.3–5.1 s in software
  rendering. Initial Full preview remains about 16–22 s (ISSUE-264 stays open).
- [x] Smoke: 26 passed, 2 skipped; the known assembly-exit fixture timeout at
  `scene_harness.js:434` remains (ISSUE-266, previously reproduced upstream).
  Test parts, sessions, reports, bridge keys and the two verified legacy-fixture
  cache snapshots were removed; the isolated workspace ends with zero snapshots.

## 2026-11-23 — ISSUE-266 / ISSUE-267: Smoke baseline and fixture-cache accounting

- [ ] Assembly-exit fixture setup hits 60 seconds with and without Corner;
  reproduced on untouched `afbc311c`. Full smoke: 26 passed, 2 skipped, 1 failed.
- [x] Verified and removed only the isolated run's two legacy-fixture revision
  snapshots; all test artifacts are gone and the main workspace is unchanged.
- [ ] Add failure-safe ownership tracking for read-only smoke fixture caches;
  do not weaken the existing prefix-only teardown guard.

## 2026-11-23 — ISSUE-265: Keep extension display out of Corner atom inputs

- [x] Reproduced recursive atom construction using native Corner → extension.
- [x] Request only duplex endpoint geometry inside the Corner atom builder;
  retain upstream measured extension slabs on the outer Full projection.
- [x] Integrated regression, finite extension slabs and independent reopened
  recipe replay pass; the ordinary extension-slab regression also passes.

## 2026-11-23 — ISSUE-261 / ISSUE-264: Approved Corner provider and responsive progress

- [x] Integrate the demonstrated two-pass molecular provider only for recorded
  Corner inserts, after wedge deformation. Full representation uses its atoms.
- [x] Preserve frozen coordinates, ordinary inserts and physical overrides;
  test numerical-cache transport and disposable-worker cancellation.
- [x] Stream actual fit progress without buffering and preserve immediate
  cylinder previews. Verify native save/reopen and independent command replay.
- [ ] Full preview still exceeds the requested 1–2 seconds. Production physical
  simulations remain unvalidated; software checks are not stability evidence.

## 2026-11-23 — ISSUE-263: Whole-preview Corner edit progress

- [x] Reproduced premature completion; progress now includes source proof,
  edited seams, later-feature replay/validation and Full projection.
- [x] Two history/stream tests and the square-lattice app workflow pass. The
  app checks monotonic completion and remaining-time estimates, plus actual
  numeric arrows and history controls. No persisted test artifacts remain.

## 2026-11-23 — ISSUE-262: Preserve Corner numeric increments

- [x] Reproduced off-grid position snapping on both HC and square lattices.
- [x] Native spinners now add 7/8 bp (or matching nm) and 15° from typed values.
- [x] 13 focused frontend tests and the 6HB app workflow pass, including actual
  arrow keys and history operations. Preview ready in 1.945 s, painted in 2.301 s.
  Inspected preview; test part/revisions, browser captures, reports and bridge
  credentials cleaned. No molecular placement changes.

## 2026-11-23 — ISSUE-260: Corner source ownership at overlapping miter tips

- [x] Reproduced ambiguous endpoint ownership using native Extrude → Auto
  Scaffold → Make Cluster → Corner; added a regression for the exact failure.
- [x] Preserve original endpoint ownership; v3 marks new tip sequence N and
  leaves v1/v2 replay unchanged. Keep authored plane nicks unjoined.
- [x] Focused backend/frontend checks and nicked/sequence-assigned routed 6HB
  app checks pass. Routed preview ready in 1.687 s, painted in 2.040 s.
- [x] This topology fix initially left molecular placement unchanged. The
  candidate was subsequently approved and promoted under ISSUE-261.

## ISSUE-264 — Large-scene backbone rendering and native metadata assignment (2026-11-24)

[x] Desktop enables fast CG backbone spheres independently of atomistic flags;
photo mode substitutes ordinary spheres and restores original interactive meshes.
A bundled C++ integer domain-assignment kernel retains the existing NumPy fallback
and all molecular placement authorities. Matched-camera ttest medians: Full wide
30.2→59.9 fps, close 29.9→59.9; 68.4% fewer triangles. One candidate trial remained
near 31 fps and is retained. Warm compact preparation 27.35→21.10ms with identical
packet bytes. Opening stayed ~0.55s; no opening or selection speedup claimed.
Part click selection, assembly editing/save/reopen, photo/cancel and installed
normal lifecycle passed. 35 backend, 141 frontend, four host tests. Source files
unchanged, simulations not run. Details: `docs/desktop_large_scene.md`.
`main.js` task delta: 0 lines.

## ISSUE-263 — Applications-menu launch aborted by Ubuntu sandbox policy (2026-11-24)

[x] Initial installed tests inherited VS Code's AppArmor profile. GNOME's
unconfined launch denied Chromium user-namespace capabilities, then aborted at
the unconfigured SUID helper before NADOC logs existed. Installer now prepares
an exact-executable userns profile and authenticated setup script. Applied the
workstation profile through pkexec; kept the Chromium sandbox and global
namespace restriction enabled. Verified `gtk-launch nadoc` from the unconfined
user service manager, new backend ready and visible welcome window captured.
Five focused desktop tests and task lint pass. `main.js` delta: 0.

## 2026-11-24 — ISSUE-262: Linux desktop milestones 1–3

[x] Built and locally installed the Electron/Python application; added isolated
HC24/30-mer acceptance and first-display instrumentation. Removed fixed success
wait and assembly source round trip; corrected initial elongated-scene framing
and implemented cooperative cancellation. Same-runtime median opening fell 65%
(1.791s to 0.624s). Native window captures establish visible output; actual
orbit/Full/select/hide/undo/recolor/save/reopen/cancel and clean backend exit pass.
88 frontend, 13 backend/audit and 3 host unit tests pass. Saved structure process
independently replayed. No simulation or full-suite claim; Linux only.

## 2026-11-23 — ISSUE-261: Preserve external storage with tracked Shared Designs

[x] Integrated `52a1b317`, preserving local policy edits and backing up the
previous empty nested repository metadata. Added shared storage-root selection
and strictly scoped linked-folder support. Pointer relocated byte-for-byte;
Archive jobs and local designs remain in place. Thirty-nine focused tests and
the read-only live Library browser check passed; no browser artifacts persisted.

## 2026-11-23 — ISSUE-260: Constrain the scaffold sequence target selector

[x] Scoped shared-control CSS fixes intrinsic-width overflow from imported
scaffold IDs. Verified old-layout negative control, desktop/narrow containment
and real M13 assignment in the isolated app. Sixteen frontend and two backend
tests pass; Pointer's assigned M13mp18 offset 0 independently matches all 161
published 2017 staple cores. Saved/reopened process replay passes.

## ISSUE-259 — NAMD runner scheduling fixture intermittently sees a busy lease (2026-11-22)

[ ] Occupancy archive FAST validation failed in
`test_analysis_contention_waits_cancellably_before_launch[False]` before its task
started: `analysis_activity_lease()` raised `WorkloadBusy`. All 20 runner tests
passed in an isolated retry (4.42 s). The fixture already sets a temporary memory
budget directory; background activity sharing process state is a hypothesis, not
an established cause. No runner or scheduling code changed for occupancy archival.
Evidence: `.development-artifacts/occupancy-archive-backend.log` and
`occupancy-archive-runner-retry.log`. Investigate worker/background lease isolation.




## ISSUE-258 — NAMD row selection waits for full job-list refresh (2026-11-22)

[x] Selecting Gerling R1 Alpine could leave a second spinning circle indefinitely.
The unified list had saved job metadata, but the NAMD panel awaited its separate
all-job status/provenance refresh before selecting a missing panel record. A stalled
`GET /md/jobs` reproduced the unselected row with `data-selection-pending` intact.
Pass the visible list snapshot to the panel, seed only missing NAMD records, and
preserve already-refreshed panel records. Include parents so production settings
remain available. Live status, artifact checks and launch validation still use their
ordinary paths; selection does not wait for them. No backend or simulation changes.
Regression covers an unresolved list request, parent settings, duplicate records,
and engine isolation. Evidence: `.development-artifacts/gerling_job_selection_20261122/`.
Validation: stalled-request live browser check passed; 404 focused tests passed.
Full frontend: 10,712 passed, 1 skipped; one outdated call assertion corrected
and verified by the focused rerun. Lint passed. Smoke: 22 passed, 2 skipped,
2 existing Create/Close Session failures. Temporary sessions/screenshots cleaned;
Gerling source checksum unchanged. Feature `main.js` LOC Δ: 0.


## ISSUE-234 — VR build test captures background trajectory subprocess (2026-11-20)

[ ] Intake during hybrid sampling validation. FAST: 21,002 passed, 90 skipped,
one VR assertion failure from a third, background trajectory-precompute call.
Isolated VR test passed; no fix claimed. Raw logs were pruned in the requested
2026-11-21 cleanup; summary retained in `docs/oxdna_hybrid_benchmark.md`.
See ledger for the open isolation investigation.

## 2026-11-21 — ISSUE-257: Close Move/Rotate after attachment Apply

- [x] Gold/quantum-dot and protein Apply now use shared session confirmation;
  successful and no-op commits detach and close, errors remain open for retry.
- [x] 134 focused panel/tool/gizmo tests and lint pass.
- [x] Gold in-app regression passes: exact translation, one new history entry,
  closed popup/gizmo, and no extra entry after an unchanged Apply. Test fixture,
  revision store and browser artifacts removed by teardown.


## 2026-11-21 — ISSUE-256: Move/Rotate Clear selection

- [x] Clear now releases the cluster tool target and pending preview, then leaves
  the popup waiting for another selection. The existing cancel path restores display.
- [x] Focused tool, panel and subscription tests: 124 passed.
- [x] App regression passed: `frontend/e2e/move_clear_selection.spec.js` loads the existing
  JJ_Hinge file and checks clear/reselection plus unchanged saved design content
  (excluding the normal Open file-identity signoff metadata).


## 2026-11-20 — ISSUE-253/254: RunPod cold imports and large-result collection

- [x] Extend dependency preflight to 180 s and native-result packaging to 900 s,
  preserving dependency failures, immutable provenance, staging, compression and
  the paid-pod budget/watchdog. Actual failures: `53d8d2b83be8` before solving,
  `f404d25df60e` after a successful 693.43 s CUDA solve during packaging.
- [x] Correct obsolete RunPod help text: managed default SNUPI setup is automatic,
  and linear/Stokes dynamics can use CUDA. Unsupported models retain CPU.
- [x] 19 focused solver-cluster tests pass after both fixes; the existing 25 focused
  frontend checks passed for provider cards, engine activity and stage timelines.
- [x] All three managed RunPod jobs completed, all native outputs passed numerical
  checks and all nine result-view checks passed. Completed spinner/Stop clear;
  provider inventory confirms no pods remain. Total compute $2.629 including
  failed attempts; browser artifacts removed, managed scientific results retained.
- [x] Fresh FAST: 21,247 passed, 19 skipped, one known ISSUE-235 failure.
  No individual >5 s; aggregate 506.31 s pytest / 551 s wrapper, no guard changes.
  FULL remains deferred. Benchmark results and final campaign checks are recorded
  in `memory/project_snupi_dynamics.md`. Main.js LOC delta: 0.


## 2026-11-19 — ISSUE-251: CUDA SNUPI integration and cached output

- [x] Installed optional float64 device-resident linear/Stokes GJF, sampled
  translation transfers, bounded RMSF and cached reconstruction with native normals.
  Unsupported models retain CPU; actual backend/RNG metadata survives collection.
  Managed RunPod bootstrap installs CUDA Torch; the subsequent remote campaign
  verifies actual CUDA execution and managed result collection.
- [x] Same-host full benchmarks, 60,000 steps, 1,200 samples, 40 output frames:
  2-mer 469.294→60.827 s (7.72×), 10-mer 2537.728→280.310 s (9.05×).
  Integration improves 14.96× / 20.58×; reconstruction/analysis 4.57× / 4.59×.
  Single paired observations on Ryzen 5 3600 / RTX 2080 SUPER; no provisioning or
  transfer time. Same 6/8 GiB guards; baseline 10-mer briefly hit the soft limit
  (0.264 s observed pressure stall), no OOM. Source/input hashes verified.
- [x] Full matched-noise 2-mer RMSF max difference 1.999e-15 nm; coupled oscillator
  covariance error 1.01%. Independent production RNG streams differ; no claim of
  physical equilibration. All benchmark trajectories/RMSF finite, no retries,
  large temporary outputs removed. Evidence and methodology in
  `.development-artifacts/snupi-gpu-implementation-20261119/` and project memory.
- [x] 90 focused tests, lint and diff check pass. Main.js LOC delta: 0.
  `test-smart` decision FAST: 21,240 passed, 6 failed, 19 skipped. Five failures
  pass in isolation (ISSUE-252); known ISSUE-235 remains. Aggregate budget overrun
  triaged with no individual >5 s test; no thresholds weakened.

DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.

## 2026-11-19 — ISSUE-252: FAST isolation debt (open)

- [ ] Resolve ambient-memory and background-process interference in the mrDNA
  field/surface and VR tour tests. Five broad-run failures pass in isolation;
  no guards, thresholds or production behavior were weakened. Dossier/evidence
  recorded while validating SNUPI acceleration. Known ISSUE-235 remains separate.

## 2026-11-19 — ISSUE-250: shaded SNUPI results

Completed-job selection now defaults to saved coarse FEM axes/joints, rendered
as opaque lit tubes with RMSF colors. Other modes use shaded nucleotide beads,
with scalar colors for flexibility/deviation and helix colors for shape/trajectory.
Missing scalars are gray. Tiled, zoom-adaptive bead detail retains all saved
coordinates and reuses frame buffers; coarse segments are never subsampled.
Explicit Off remains respected. No molecular state or CanDo rendering changes.
All five modes reviewed against actual completed 2-mer/10-mer jobs; trajectory
scrubbing and display teardown passed. Focused tests: 16 passed. Full frontend:
10,786 passed, 1 skipped, one cached pre-edit module failure resolved in the fresh
focused rerun. Smoke: 27 passed, 2 skipped. Main.js delta: +1 wiring line.
Evidence: `.development-artifacts/snupi-rendering-20261119/`.

## 2026-11-18 — ISSUE-234 / ISSUE-236: install bounded timestep and reconstruct BigO

Stopped RunPod before case `bebad41f65e7`; exact pod `84j90s4fjgre6t`
termination acknowledged and provider inventory empty. Installed conservative
fixed-work timestep sizing, downward two-significant-digit rounding and vectorized
electrostatic stiffness/CSR setup. GPU integration remains a prototype.

Legacy BigO cannot directly pass native replay, and modern automatic routing
changes its 126-bp repeat to 147 bp. Added `scripts/rebuild_legacy_part.py` to
reconstruct the known scaffold with real Helix Extend, Resize Ends, Nick and
Place Crossovers operations, then execute its downstream recorded commands.
The saved `BigO-rebuilt.nadoc` independently replays 70 commands and matches all
molecular topology, sequences, junctions, periodic identity and geometry (1e-12
absolute float tolerance). The original source is unchanged; the `.rebuild.json`
receipt retains its original log and checksum. Two-monomer assembly publication
and reopened audit verify two commands, two instances, one joint and all upstream
construction. Visual app load passed. Real job `fe44cad5dfec` launched on RunPod,
coarse Langevin with 60000 steps, dt=0.13 ps, 14112 nodes, no retry. Completed
in 470.78 s solver time; setup ~5 s, timestep selection within one log second.
All 40 trajectory frames, display coordinates and RMSF are finite; results
downloaded and exact pod terminated (provider inventory empty). Cost $0.09683.
Frontend actual job row, RunPod choice, integration stage and measured 81.7%
progress verified. Browser screenshots/profiles and 2.8 GB test scratch removed.

Validation: installed timestep checks 34 passed; reconstruction checks 2 passed;
lint and diff check passed. `test-smart` decision FAST: 21199 passed, 2 failed,
19 skipped, 499.44 s pytest / 542 s guard wall time. Known ISSUE-235 duplex failure
persists; seamless native-proof synchronous timeout passes in isolation (1 test).
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Slow-test triage: no per-test violators; aggregate cost spread over 21220 tests,
not evidence for arbitrarily relegating the slowest tests. No thresholds changed
and no redundant broad rerun. Main.js LOC delta: 0.


## 2026-11-18 — SNUPI candidate validation and slow-test triage

Candidate numerical checks: 34 pass; BigO operator equivalence and full-assembly
50-step/GPU probes pass. Lint passes. Repository FAST: 21,167 pass, one unrelated
duplex-link failure (ISSUE-235), 19 skipped; FULL deferred without a test session.
Joined-path generation/edit/two cold replays cost 5.32 s in the sweep and 6.04 s
including setup alone. Registered that proof in `_SLOW_TESTS` / headless, keeping
its existing area routing; slow collection confirms coverage. No budget raised.
The unrelated deterministic failure remains; no subsequent green broad sweep or
aggregate-budget recovery is claimed. Temporary owned pytest roots and probe logs
were removed after checking for process references; candidate source/results remain.


## 2026-11-18 — ISSUE-234: isolated SNUPI setup optimization candidate

Preserved live RunPod baseline as requested. Implemented and benchmarked candidate
modules outside API-watched paths: conservative fixed-work mass-scaled frequency
bound, downward timestep rounding, vectorized electrostatic COO batches, CSR-only
dynamics accumulation. BigO-poly reaches integration in ~47 s; 50 steps finish
with finite outputs and no retry. BigO part operator relative error ~6.4e-21,
identical masses. GPU plain-GJF pilot shows ~5.9× warm speedup with identical noise.
These are short numerical/performance checks, not physical convergence evidence.
Candidate patch, numerical tests, benchmark scripts and compact JSON results:
`.development-artifacts/snupi-timestep-20261118/`. Production backend unchanged;
patch intentionally unapplied to preserve the ongoing before case. Main.js LOC
delta: 0. Full repository validation status is recorded in `checks.json`.


## 2026-11-18 — ISSUE-233: solver activity and selected RunPod resources

Added SNUPI to the shared NAMD-style tab spinner and tested preparation, running
and terminal states for SNUPI/CanDo/mrDNA. SNUPI/mrDNA selection now updates the
Clusters provider, restores saved settings and shows the selected pod, GPU,
requested RAM/CPU, quote and budget. Repeated polls preserve user edits.
Validation: 989 frontend files, 10,743 tests passed / one skipped; 28 existing
smoke checks and the corrected focused sidebar check passed; lint and diff check
passed. Browser fixture corrections use the app's existing panel instances.
Evidence: `.development-artifacts/solver-sidebar-activity-20261118/checks.json`.
Main.js LOC delta: 0. Browser scratch roots and temporary validation logs removed.


## 2026-11-18 — ISSUE-232: separate SNUPI dynamics stages in the timeline

The engine panel and unified job poll now share a phase-derived stage renderer.
Mesh/stiffness preparation, stable timestep calculation, optional hydrodynamic
friction, integration, analysis/save and remote preparation/download have separate
rows. Dynamics steps belong to integration. Unknown/stale/terminal states are
explicit, and no setup percentage or stage duration is invented. Existing worker
telemetry supports the ongoing BigO-poly job without restarting its controller.
NADOC theme colors and locale-formatted step counts are used throughout.

Evidence: `.development-artifacts/snupi-stage-timeline-20261118/checks.json`.
Main.js LOC delta: 0; no backend or simulation changes.
Validation: 15 focused checks; full frontend 10,737 passed / one skipped;
28 browser smoke checks, including the timeline transitions, passed. Lint passed.
Temporary browser output and validation logs removed; cleanup verified.

## 2026-11-18 — ISSUE-231: isolate imported simulation route workspace aliases

Test startup isolation now redirects imported API workspace aliases as well as
assembly/main globals. This prevents test-process reconciliation from marking a
live RunPod controller interrupted. BigO-poly's live owner and remote process were
verified, then its false failure label was repaired without renting another pod.
A regression covers activity collection, SNUPI listing and alias restoration.

## 2026-11-18 — ISSUE-230: actual SNUPI dynamics progress on RunPod

Remote controllers now retrieve bounded worker progress separately from job
metadata. The job API and shared progress bar show completed/planned dynamics
steps, remaining steps and a rate measured during integration. Setup is
indeterminate with named phases; retry counters reset, stale receipts are labelled
and stale ETA is suppressed. Static load steps and weighted setup fractions no
longer determine a dynamics percentage. No physics/timestep changes.

Replacement BigO-poly job `bebad41f65e7` confirms live receipt transport and
assembly-list association. Original job `4c9ec02f01e5` was stopped for deployment
and its pod removed; old spend $0.531981 plus new cap $4.46 stays below $5.
A completed Langevin trajectory is not yet confirmed. Main.js LOC delta: 0.
Evidence: `.development-artifacts/snupi-runpod-progress-20261118/checks.json`.

Validation: 11 progress backend, 33 remote lifecycle/bundle and four isolation
checks passed. Full frontend: 10,731 passed / one skipped; browser smoke: 28
passed. Backend FAST: 21,166 passed / 19 skipped, with existing ISSUE-221 gesture
failure. FULL deferred by the session guard. Aggregate timing flag only (596 s;
maximum individual test 4.78 s); no budgets/classifications changed. Lint passed.
Temporary validation files and processes cleaned up; real managed job retained.

## 2026-11-18 — ISSUE-229: hide idle SNUPI Stop

Stop now appears only for queued/preparing/running jobs. It continues targeting the
active job when an older completed result is selected. The HTML starts hidden;
the panel synchronizes row visibility and button enablement together.

Validation: four factory tests; full frontend 10,726 passed / one skipped; 26
other smoke checks and the corrected Stop app check passed. Initial app fixture
failures omitted the document association and left the welcome/relocated-controls
host hidden; focused retry passes. Scratch cleanup verified; lint passed.
Main.js LOC delta: 0. Evidence: `.development-artifacts/snupi-stop-langevin-20261118/checks.json`.

A genuine BigO-poly Coarse + Langevin job was submitted through the standard
assembly projection/create API as `4c9ec02f01e5` (RunPod, 75 GiB/eight CPUs,
RTX 4090 host, $0.89/hour, $5 cap). The assembly-scoped list returns it with
`dynamics=true`, `nonlinear=false`. At handoff it remains running in setup;
completed trajectory/results are NOT confirmed. The source assembly is unchanged.
The managed job, pod and budget watchdog remain active intentionally.

## 2026-11-18 — ISSUE-227: SNUPI RunPod deployment repair

The default RunPod interpreter path was never provisioned. SNUPI now installs
and reuses a pinned Python 3.12 CPU-worker environment on the network volume,
under the existing budget and independent watchdog. Custom interpreters and
mrDNA/ARBD remain user-managed. Live retries also exposed archive extraction
trying to restore local ownership and missing scaffold sequence files; extraction
now retains remote ownership and packaging includes core sequence/runtime data.
The packaged-worker import test runs without access to the original checkout.
New attempts clear stale errors before provisioning.

Validation: five environment tests, 17 cluster/archive tests, and 16 pod lifecycle
tests passed; lint and diff checks passed. Backend FAST: 21,153 passed / 19 skipped,
two unrelated failures (baseline ISSUE-221 and intermittent trajectory queue
ISSUE-228; the latter passed its isolated rerun). FULL deferred. Timing triage
found no per-test violations (maximum 4.70 s); the aggregate guard took 526 s.
No budgets or test classifications changed. main.js LOC delta 0. Live job `b958e97feeae` completed BigO-poly coarse + RMSF in 1129.96 s:
424,144 finite positions, 211,680 FEM nodes, RMSF 1.660–7.558 nm. Results downloaded
and served through the display/RMSF APIs. Original assembly/snapshot unchanged.
Provider confirmed all retry pods absent; combined recorded compute cost $1.025.
Temporary test outputs were removed. Evidence:
`.development-artifacts/snupi-runpod-environment-20261118/checks.json`.

## 2026-11-18 — ISSUE-228: trajectory queue validation intake

Recorded an empty scheduling queue failure during the broad sweep. The isolated
rerun passed; no queue or scientific behavior change is claimed here.

## 2026-11-18 — Solver resource comparison list and ISSUE-226

SNUPI and mrDNA now offer scrollable, keyboard-selectable Alpine/RunPod resource
rows with availability, estimated wait and estimated completion. Refresh uses
the current allocation; unavailable or undersized resources remain visible with
an explanation. Existing RAM/VRAM admission and final RunPod stock/price checks
remain enforced for parts and assemblies. Timing uses the existing solver
reference heuristic and general Alpine queue forecasts; unknown startup/wait
stays explicit, with no claim of calibrated per-GPU performance.

Fixed ISSUE-226: themed buttons no longer override the wizard's hidden state.
The standard extra-wide modal fits all columns; temporary before/after captures
were inspected. main.js LOC delta 0.

Validation: 10 focused backend tests passed; full frontend 987 files,
10,725 passed / one skipped. Six app checks passed, including both solvers,
both providers and part/assembly submission. Backend FAST: 21,148 passed,
19 skipped, two failures (baseline ISSUE-221 and intermittent ISSUE-225, whose
isolated rerun passed). FULL deferred. No per-test timing violations; aggregate
budget exceeded without changing classifications or budgets. Compact evidence:
`.development-artifacts/solver-resource-list-20261118/checks.json`.
Smoke: 26 passed, including console-error and teardown gates. Temporary browser
workspaces, fixtures and credentials were removed and absence verified.

## 2026-11-18 — ISSUE-225: native-proof timeout intake

The resource-list backend sweep hit a synchronous verification HTTP 408 in the
auto-break upstream-length test. Isolated rerun passed; recorded as intermittent
proof-validation debt. No deadline, history proof, or molecular change.

## 2026-11-18 — ISSUE-224: solver allocation availability and wizard styling

SNUPI job `3869962f92e9` failed before pod creation because the chosen A100 PCIe
was unavailable at the volume's EU-RO-1 location with 75 GiB RAM/8 CPUs, despite
global stock. Corrected the REST datacenter-field parser and added volume/host
scoped availability checks before review and rental, including clear supply-race
errors and no automatic retries. Standard NADOC input/select/button primitives
replace the wizard's unstyled fields/actions; number fields use the data font.
The confirmation uses the exact reviewed allocation.

Validation: 19 focused backend and 20 focused frontend tests passed. Full frontend:
986 files, 10,720 passed, 1 skipped. App: all 3 checks passed, covering rendered
colors/fonts/buttons and both solvers/providers on parts/assemblies. Backend FAST:
21,146 passed, 19 skipped, existing ISSUE-221 failure; FULL deferred. Timing
triage found zero per-test violations (maximum 4.31 s); aggregate guard time
537 s. No test budgets/classifications changed. Lint passed; main.js LOC delta 0.
Smoke: 26 passed. Temporary test workspaces, captures, logs and bridge credentials
removed; compact results retained. No paid retry. Evidence:
`.development-artifacts/solver-capacity-style-20261118/checks.json`.

## 2026-11-18 — ISSUE-223: mrDNA Fine export-limit intake

The optimized BigO pilot got past fine bead construction but hit the external PDB writer's residue-number assertion. Recorded the partial-output evidence and kept it separate from hardware limits. No fix claimed; remaining benchmark cases continue.

## 2026-11-17 — ISSUE-222: capture-limit validation intake

Broad memory-regression sweep hit a repair-draft capture limit during fixture setup; isolated reproduction passed. No fix or guard change. Evidence is retained in `solver-memory-round2-20261117`.

## 2026-11-17 — ISSUE-221: intake only, baseline gesture failure

Solver memory validation found the native duplex-link auxiliary-pose assertion failure. Focused reproduction also fails with the original solver modules. Recorded as unrelated baseline debt; no fix claimed. Evidence: `.development-artifacts/solver-memory-20261117/verification-review.json` and its linked baseline logs.

## ISSUE-249 — VMMC wizard rejects empty submodel selection (2026-11-18)

Validation: 6 focused backend; FAST 21,015 passed (90 skipped), FULL deferred by session policy; 10,698 frontend passed (1 skipped). Smoke 23 passed, 2 skipped; existing Honeycomb request timeout passed isolated retry. Native job and copy each completed eight stages with explicit empty-box payload. All test jobs/captures removed. Evidence: `.development-artifacts/vmmc-wizard-422.json`.

[x] The normal production launcher includes `submodel: {box: null}` for a full-system
job. VMMC incorrectly rejected the wrapper's presence as an active submodel, returning
422 before job allocation. Accept the explicit null box while continuing to reject an
actual region. Regression covers both cases with the real RunRequest schema, and the
native browser/API workflow now includes the launcher's explicit empty-box payload.

Optimistic `creating-*` rows now select the submodel draft and skip export trajectory
metadata until the real job exists, avoiding the secondary 404 requests. Feature
`main.js` LOC Δ: 0. Native browser create/edit/run/copy/results validation passed
with the corrected payload; both jobs completed all eight stages and were removed.


## ISSUE-248 — Umbrella results entry points (2026-11-18)

Validation: dedicated browser gesture/export test and visual review passed; 10,696 frontend tests passed (1 skipped). Smoke: 23 passed, 2 skipped, unrelated Honeycomb creation request timeout; exact isolated retry passed. Screenshots/traces removed; compact receipt `.development-artifacts/umbrella-results-ui.json`.

[x] VMMC job right-click menu and Graphs and Metrics now expose “Show umbrella
results”. Both open one shared dialog with saved melting curves, uncertainty/
sampling diagnostics and CSV/JSON exports. Pending analyses show the existing
pending-results message; ordinary MD jobs do not show this action. UI-only change;
no simulations or molecular documents authored. Feature `main.js` LOC Δ: 0.


## ISSUE-247 — CPU VMMC equilibrium duplex workflow (2026-11-18)

Final checks: 9 focused backend, 10,696 frontend (1 skipped), 24 smoke (2 skipped); lint/diff clean. Edited salt 0.35 M and a fresh-seed copy each completed all eight native CPU stages. All validation jobs/captures removed. FAST: 21,009 passed; four energy compatibility failures fixed/retested, existing aptamer-history HTTP 413 remains. FULL deferred by session policy. Feature `main.js` LOC Δ: 0.

[x] Add a wizard mode mutually exclusive with thermal ramps, with salt/concentration,
fixed tuning/equilibration/production budgets and independently seeded CPU replicas.
Persist stage progress and frozen bias weights, replay interrupted stages, and recover
analysis after restart. Native histogram reweighting and finite-size correction produce
melting curves, replica diagnostics and CSV/JSON exports in settings/metrics. Undamaged
complementary free-solution DNA duplexes only; unsupported CPD/hybrid/force systems
fail preflight. Sparse sampling reports inconclusive rather than a reliable Tm.

Validation: real browser create → API queued edit → native CPU execution of eight stages
→ recorded results → CSV download passed on the existing duplex; all native stages done,
no page errors. Short sampling was correctly inconclusive. Desktop/narrow pixel review
fixed salt alignment and stage-table spacing. Disposable simulation child removed through
API; authored source unchanged. Compact evidence: `.development-artifacts/vmmc-development/validation.json`.


## ISSUE-246 — Native melt threshold with durable stage pruning (2026-11-18)

Added default-on Stop series after melting and editable Unpaired bases (%)
controls for creation/queued editing, plus recorded settings and skipped-stage
reasons. Count unique DNA bases without native hydrogen bonds, including initially
single-stranded bases and non-designed/intrastrand pairing. Observe at trajectory
cadence; any sampled crossing ends the series only after the current full dwell.

Native HBList output uses the active CPU/CUDA interaction and consecutive output
numbering. Parse complete frames incrementally; malformed/missing samples cannot
trigger. Preserve attempt offsets, exclude discarded retry samples, and persist
threshold/step/fraction with skipped stages. Recovered boundaries reapply pruning
idempotently. Copies clear evidence; old saved protocols remain opt-out.

Validation includes native analysis of bound and melted duplex checkpoints,
runner tests for both toggle states, persistence/reload, copy/retry handling and
wizard create/edit/view checks. Detailed final validation/cleanup receipt:
.development-artifacts/melt-stop-20261118.json. main.js feature LOC delta: 0.
No user jobs or authored molecular documents were modified.

## ISSUE-245 — DNA concentration controls and simulation volume (2026-11-18)

Added µM total DNA strands controls for relaxation, production, thermal ramps and
queued edits. Exported DNA strand counts determine cubic box volume; proteins and
PEG do not count. Coordinates remain unchanged. Validate source fit before
creating continuation jobs or applying queued edits; preserve parent inputs.
Persist resolved concentration/count/box metadata through copies and ramps, with
readable saved settings. Blank keeps automatic/inherited boxes. Corrected recorded
label capitalization so µM remains µM. Documented total-strand versus per-species
conventions and the limits of interpreting heating ramps as equilibrium melting.

Validation: backend fast suite 21,002 passed / 90 skipped; frontend 10,691 passed /
one skipped. Browser workflow covers create, ramp, edit and recorded settings,
including narrow layout. Full backend suite remains deferred by test-session
policy. Final smoke/cleanup details in
.development-artifacts/oxdna-concentration-20261118.json. No user jobs or molecular
documents changed; main.js LOC delta for this feature: 0.

## ISSUE-244 — Exclusive native representation after oxDNA Off (2026-11-18)

Restores native scene ownership before restoring the native atomistic/surface
representation, so the final representation decision hides CG as appropriate.
Suspending a display uses the same order and restores representation visibility
even if a pending heavy frame never landed, preserving held trajectory caches.
Regression reproduced eight heavy-mode failures before the fix; all ten cases
now pass (Off/suspend × Full, VDW, ball-and-stick, stick, surface). No topology,
geometry parameters, user jobs or saved structures were changed. main.js delta 0.
Validation: 226 focused display/representation tests and 10,687 frontend tests
passed (1 skipped). Real-app browser path selected a mocked job on an existing
read-only design, enabled VDW and oxDNA display, then clicked Off: atomistic mode
and atom count remained intact, and the CG root was hidden. Visually inspected
the resulting native-only atoms. Browser regression passed; lint/diff and
artifact/session/credential cleanup verified. FULL remains deferred.

## ISSUE-243 — Temperature/salt controls and wizard layout (2026-11-17)

Added shared salt controls beside temperature for relaxation, ordinary production
and queued continuation edits (including field/surface deposition). Thermal salt
sits in the temperature schedule grid. Preserved inheritance/explicit overrides;
relaxation-wide salt edits also update previous per-stage overrides. Conditions
now lead the settings page; engine installation/build details are collapsible.
Moved the ramp toggle ahead of runtime fields, styled native dropdowns, corrected
the Celsius badge grid, and kept wide stage tables locally scrollable. Recorded
nonthermal settings render nested options as labeled values and stage conditions
as a table, keeping full JSON in its dedicated tab. No structures or user jobs
were modified. main.js task LOC delta: 0.
Validation: 10,677 frontend tests passed (1 skipped); focused condition edits
and shared target checks passed; 4 browser workflows plus focused final review
reruns passed. Inspected desktop relaxation/production/target/View/Edit and a
720px thermal layout. Retook transitional screenshots after animations settled;
also corrected shared target copy incorrectly naming NAMD in the oxDNA wizard.
Lint/diff and browser artifact/session/credential cleanup checks passed. Reusable
review: frontend/e2e/oxdna_wizard_review.spec.js. FULL remains deferred.

## ISSUE-242 — Thermal salt defaults to the continuation source (2026-11-17)

Removed salt from the thermal physics preset in both frontend and backend.
Continuation parameters now include salt from the actual saved source stage,
falling back to job metadata when the stage has no recorded MD specification.
The new thermal salt field applies to every plateau and remains synchronized
with the editable parameter table. Source changes update inherited values;
explicit user edits win, and clearing the field restores inheritance. Existing
jobs were not modified. main.js task LOC delta: 0.
Validation: 20,990 FAST backend tests and 10,673 frontend tests passed; two
browser workflows verified source switching, explicit salt edits and clearing to
restore inheritance. Focused checks: 25 backend / 31 UI passed. Cleanup, lint and
diff checks passed. Aggregate FAST time 191s exceeded 90s; timing triage found no
individual violators (slowest 2.02s), so budgets/classifications remain unchanged.
FULL deferred in .nadoc-slow-pending.

## ISSUE-241 — Branch thermal production from stopped runs (2026-11-17)

The list/detail API now exposes can_seed_production based on terminal status,
writer inactivity and a nonempty saved last_conf. Both production creation and
the wizard use this eligibility; stopped choices explicitly say last saved frame.
Live read-only verification confirmed duplex Run 1 and Tm Run are eligible. No
user job was created, resumed, modified or restarted. main.js task LOC delta: 0.
Validation: 20,988 FAST backend tests / 90 skipped; 10,673 frontend tests /
1 skipped; 2 browser workflows passed. Focused tests confirm copied seed bytes
match the saved parent configuration and active/missing-checkpoint sources are
rejected. Cleanup and lint/diff checks passed. Aggregate FAST time 196s triggered
the 90s warning; triage found no per-test violators (slowest 3.56s), so no tests
were reclassified and no budget changed. FULL deferred in .nadoc-slow-pending.

## ISSUE-240 — Formatted thermal View/Edit Settings (2026-11-17)

Single-job detail now includes persisted stage specifications. Opening settings
fetches that detail; thermal View Settings opens directly on readable schedule,
physics cards, and temperature rows. Queued/copy edits expose schedule and shared
physics controls, with JSON collapsed under Advanced configuration. Saved physics
is preserved in explicit overrides so editing an old job cannot silently adopt
new defaults. Missing legacy parameters are labeled unavailable. No active job
or molecular document was modified. main.js task LOC delta: 0.
Validation: 20,985 FAST backend tests and 10,672 frontend tests passed;
focused recorded-spec API regression and browser View/Edit workflow passed.
Visually inspected desktop read-only and narrower edit dialogs; fixed the native
select styling. Browser artifacts/session/credentials cleanup verified. Lint and
diff checks passed. FULL deferred in .nadoc-slow-pending.

## ISSUE-239 — False full-stage progress with dense energy output (2026-11-17)

The progress denominator now honors print_energy_every_override, matching native
input generation. Both live endpoints also size the current attempt against its
remaining budget before adding banked work. The duplex's 25°C stage was still
running normally at about 175M / 2B steps; corrected live API returned 8.83%, not
100%. During automatic API reload the existing worker/native PIDs and start
times remained unchanged, directly confirming server-restart survival. No job
was stopped, skipped, resized or otherwise modified.

Validation: 39 focused progress/thermal/runtime tests and 7 legacy progress tests
passed. FAST: 20,984 passed / 90 skipped, one known VR subprocess-mock isolation
failure caused by a delayed trajectory-precompute launch; isolated rerun passed.
Lint/diff checks passed. FULL remains deferred in .nadoc-slow-pending. main.js
task LOC delta 0. Receipt: `.development-artifacts/oxdna-ramp-progress-restart-20261117.json`.

## ISSUE-238 — Selected temperature progress (2026-11-17)

The unified Jobs bar/status now follows a selected thermal child: temperature,
status, percentage, completed/scheduled steps and remaining steps all use that
plateau. Parent selection retains whole-series progress. A pure projection uses
matching live stage fractions (already including banked work), otherwise reverses
the existing stage-count overall fraction; it never mutates job/control identity.
Completed/pending/failed/stopped/skipped rows retain their own state, and the
whole-series ETA is omitted from the child view.

Validation: 120 focused tests; frontend 10,669 passed / one skipped; browser
verified running 50% (500k/1M), done 100%, pending 0%, and parent 1.5M/3M.
The added clicks initially disrupted the later playback test's selection setup;
restoring its child selection made the full workflow pass. Lint/diff checks and
artifact cleanup passed. No native job changed; main.js task LOC delta 0.
Receipt: `.development-artifacts/oxdna-stage-progress-20261117.json`.

## ISSUE-237 — Literature-informed thermal sampling (2026-11-17)

New thermal jobs default to fixed 2-billion-step plateaus, dt 0.005, Brownian
thermostat with 100-step updates, diffusion 2.5, and 0.1 M monovalent salt.
The duration is a fixed adaptation of Soto et al. (2025), not an assertion that
every system converges in that time. Physics edits in the wizard apply uniformly
across plateaus; explicit overrides win. API/validation accept up to 10B steps.
New ramps use the pinned upstream sequence-dependent DNA2 parameter file;
legacy stage specs still default to average strengths. The chosen file is frozen
with new jobs and rendered correctly for local and remote inputs. Saved jobs
are not restarted. Documentation includes the GCGTTGCG/CGCAACGC control, 0.3 M
reference salt, and the important 6 mM vs default-box concentration difference.
No molecular structure or production simulation was created by this change.

Validation: FAST 20,983 passed / 90 skipped; frontend 10,665 passed / one skipped;
focused backend 36 passed / one deselected and frontend 30 passed; two browser
workflows passed, including uniform 0.3 M salt edit and native-settings preview.
Lint and diff checks passed, no per-test timing violators, cleanup verified.
FULL remains deferred in .nadoc-slow-pending. main.js task LOC delta 0.
Receipt: `.development-artifacts/oxdna-literature-defaults-20261117.json`.

## 2026-11-17 — ISSUE-220: expose placement Apply rejection details

Corrected error reporting, not yet the user's unreproduced rejection. Apply now
receives the request-local HTTP or adoption failure instead of a generic null
receipt; pending poses remain intact. Existing ordinary group callers retain
their null-return contract. In-app JJ requests 55/65/90° projected to
19.772/19.820/19.868° and committed all queued poses exactly, with one feature per
Apply. Seeking an earlier history stage reproduced a genuine refusal: the toast
now names the latest-history requirement and all pending poses survive.

Validation: 982 frontend files, 10,699 passed / 1 skipped; isolated app regression
passed; lint passed; memory hygiene 0 errors / 18 warnings. No source design saved
or altered. Receipt: `.development-artifacts/tether-apply-validation.json`.
Original user-specific trigger remains open pending its detailed rejection.


## 2026-11-17 — ISSUE-219: reliable tether discovery and bounded live preview

Coalesced concurrent selection attachments, rejected superseded gate replies, and refreshed pivot options when asynchronous discovery finishes. The exact M-before-selection path passes with a delayed API reply. Coupled previews now publish one display transaction; contact math reuses scratch storage, a refitted bounds hierarchy finds candidate pairs, and follower membership is captured once per gesture. Interactive solves retain unfinished work under a 60 ms budget, discard it on reversal, and publish only contact/tether-valid poses. Discrete numeric edits retain their complete iteration budget.

GPU app verification on JJ_Hinge (RTX 2080 SUPER, Full representation): 60 updates at the recorded relaxed pose measured median/p95/max **116.4/163.2/168.2 ms**; 60 at the current saved pose measured **145.4/166.3/171.8 ms**. Timings include `gl.finish()` after each frame, after shader warm-up. All-part contact and tether checks, follower yielding, fixed largest cluster, rendered anchor positions and Cancel restoration passed. The original file was not saved or rewritten. Discrete +5-degree numeric input remains slower (565.5 ms including gesture setup); the <200 ms acceptance target is repeated drag updates. Software rasterizers failed the full-frame target and are not counted as GPU evidence.

Reproduce using the isolated smoke workspace runner with `NADOC_TETHER_CONFIG=playwright.tether.config.js`; WSL GPU configuration used `GALLIUM_DRIVER=d3d12`. The browser config retains cleanup and isolated ports. `main.js` shrank by 28 lines. Validation: 982 frontend files, 10,696 passed / 1 skipped; smoke 24 passed / 2 skipped; code lint passed; memory hygiene 0 errors / 18 warnings. Results and source hash: `.development-artifacts/tether-preview-validation.json`. Subjective pointer feel remains MV-70.

## 2026-11-17 — ISSUE-218: compliant flexible neighbors during Move/Rotate

Coupled the whole eligible flexible component for tethered previews, pinning its largest cluster and allowing smaller neighbors to translate and rotate under tether/contact constraints. Collisions remain optional; tether compliance remains active with detection off. All-part static barriers still participate. Bounded incremental requests prevent blocked steps accumulating into a jump through an obstacle. Existing preview transactions carry all follower poses through Apply/Cancel/Undo. Corrected the checkbox/label row layout. `main.js` LOC delta 0; subjective pointer feel remains MV-70.

## 2026-11-17 — ISSUE-217: numeric tether motion and collision barriers

[x] Numeric fields now share tether projection and movable-link solving with
pointer dragging. Added a default-on Move/Rotate collision toggle, all-part
paired-duplex obstacles (including loose/unowned bundles), joint clamping of
active/linker poses, bounded motion sampling and monotonic overlap escape.
Final poses continue through the existing atomic recorded Apply transaction.
No `main.js` changes (LOC delta 0). Pointer feel remains MV-70.


## ISSUE-216 — Await smoke fixture creation and display refresh (2026-11-17)

Smoke setup treated welcome dismissal / a fixed 500 ms delay as creation
completion and fired an unacknowledged broadcast before waiting for rendered
beads. Await the actual File > New response and browser document adoption, then
explicitly await design/geometry refresh after fixture authoring. Square creation
awaits its POST, matching the existing Honeycomb test. Production behavior and
test timeouts are unchanged. Final isolated one-worker rerun: all 3 affected
smoke cases pass (assembly-exit, Square-create, close-session); see ISSUE-215.


## ISSUE-215 — History cancels previews and respects partial cluster ownership (2026-11-17)

JJ_Hinge's saved F19 source has identity cluster transforms and no nucleotide
poses, deformation or atomistic override. The observed jumble is disposable
render/geometry-cache state, absent from its feature history. Two bugs combined:
Undo/Redo did not cancel the local Move/Rotate preview, and cluster-only history
deltas transformed entire helices for domain/base-selected clusters, then wrote
those wrong visual positions into the derived nucleotide cache. Initial app
regression after cancellation alone still measured a 16.8195 nm discrepancy.

All part/assembly Undo/Redo API entry points now await preview cancellation and
restoration before sending a history request. Partial/base-selected and shared
helix ownership uses native geometry regeneration instead of whole-helix deltas;
segmented axes and all nucleotide placements are resolved together. Disjoint
whole-helix history retains its fast path. No authored topology, constants or
transform semantics changed. `main.js` LOC delta: 0.

Repair now explicitly distinguishes recipe verification from viewport state.
Refresh displayed geometry cancels the draft, rebuilds from published geometry
and reports corrected cached nucleotide coordinates without adding a feature or
changing authored data. Recipe success no longer implies a viewport check.

Focused frontend: 105 tests passed. Actual JJ app test passes: nonzero preview,
menu Undo, nonzero preview, keyboard Redo, then preview + repair display refresh.
All rendered backbone coordinates agree with fresh native regeneration within
0.001 nm; feature counts 19 -> 20 (Relax) -> 19 -> 20 -> 20 (display recovery).
Post-Undo and post-recovery screenshots inspected. Original SHA256 unchanged;
no legacy derivative saved. Temporary captures, workspace hosts and browser
reports cleaned. Receipt: `.development-artifacts/undo-preview-verification.json`.
Broad frontend: 974 files pass, 10,666 tests passed / 1 skipped (512.68 s).
Lint and diff whitespace checks pass. Initial broad smoke: 22 passed / 2 skipped,
2 fixture timing failures (ISSUE-216); real-design console and close-session gates
passed. After explicit fixture synchronization, shared-workspace reruns reached
save/read calls but hit existing 60 s limits. Final affected smoke run uses one
worker and an isolated temporary workspace: assembly exit 15.5 s, Square creation
7.6 s, close-session 34.9 s; all 3 pass with unchanged timeouts. No broad rerun
was needed after these test-only fixture changes. Temporary workspace, reports,
credentials and test project stores were removed and cleanup verified.


## ISSUE-214 — Hard contact constraints and flat duplex ends (2026-11-17)

JJ_Hinge with all 12 marked tethers failed the v1 soft-contact solve. Rounded
capsule ends also invented three initial clashes across genuine axial gaps
between short hinge duplexes. The new flat-ended cylinder bounds preserve radial
clearance and add exact axial support-plane separation, with 0.167 nm terminal
padding. Cross-product closest-point math avoids nearly parallel cancellation.

The v2 solve repairs initial overlap, then uses SLSQP contact inequalities while
minimizing tether overstretch. No changes to 1.18 nm contours, cluster ownership,
topology, pinning or atomic acceptance. Actual native geometry remains the final
acceptance authority; absolute transforms replay through the existing command.

Actual app: F19 -> F20, 12/12 lengths <= 1.18 nm, zero overstretch, contact
penetration 1.86e-13 nm (zero overlaps), largest cluster fixed. Four Full views
inspected and full geometry refresh matches rendered coordinates exactly.
Geometry Cluster 2's Constrained (tethers) option appears and selects successfully.
Source hash unchanged; temporary captures, host/project/session/credential/report
artifacts cleaned. No new legacy structure published. Focused checks: 10 network
and 8 contact tests pass, including guarded save/reopen/replay and atomic failure.
The local full-model regression is explicitly slow (12.62 s).
main.js LOC delta: 0. Evidence:
`.development-artifacts/jj-twelve-app-verification.json`.

Validation: FAST **21,067 passed / 19 skipped**, 494.70 s pytest / 498 s guard
wall time; lint passes. Aggregate timing warning only: zero per-test violators,
slowest 4.56 s. Reviewed the timing report, shared isolation fixtures and the
leading oxDNA/build/immutable-apply modules: varied orchestration, geometry and
replay work; no identified shared accidental wait warrants unrelated changes.
No tests were relegated merely for ranking slowest. The measured 12.62 s full-JJ
regression is registered in `_SLOW_TESTS` with headless area/source routing;
collection confirms it remains available as slow+headless. Small network/contact
fixtures remain fast. No timing budgets changed; no redundant broad rerun.

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.


## ISSUE-213 — Staged duplex contacts in flexible-network Relax (2026-11-17)

The user authorized the successful staged-contact method after comparing joint
penalties, constrained fitting and expand/reclose variants. Relax all and Relax
connected flexible network now solve tether and inter-body duplex-capsule
constraints jointly, keeping the largest participating body fixed per component.
Five contact weights (0.1, 0.3, 1, 3, 10) repair initially overlapping poses;
already-slack tethers do not bypass contact checking. The contact math and
ownership-aware native-axis extraction live in `flexible_contacts.py`.

Both contour excess and capsule penetration must be <= 0.001 nm. Actual native
posed geometry is independently remeasured inside the atomic recorded mutation;
bad clearance or movement of fixed-body capsules rejects without changing
history, revision or undo. Feature metadata records initial/final contacts,
scope/limitations, model radius and stage settings. Absolute-pose replay remains
unchanged, preserving old features and deterministic independent replay.

Read-only production solve on saved JJ_Hinge: 28 initial overlaps become zero,
all 11 tethers close (maximum excess 0.000187992 nm; capsule penetration
0.000001347 nm), Geometry Cluster 1 stays fixed, 91.99 seconds. Source SHA256
unchanged. No legacy derivative is authored or published. Focused network tests:
9 passed / 1 historical-source skip, including guard publication/reopen/replay,
undo/redo, slack-but-overlapping repair, infeasibility, and atomic rejection of
falsely optimistic clearance reports.

Coverage is participating clusters' paired duplex axes only. ssDNA/overhangs,
nonparticipating obstacles, intra-body clashes and continuous collision-free
trajectories remain follow-on work. `main.js` LOC delta: 0.

Validation: `just test-smart` selected FAST, 20,986 passed / 20 skipped. Its
timing guard flagged the pre-existing mock-job extension-display integration
test at 5.64 s; required slow-test triage identified bundle construction/export,
stage subprocesses and display parsing. Focused rerun passed (3.41 s call).
Registered that test in `_SLOW_TESTS` with the existing oxDNA area routing;
verified slow collection retains it. No budget/guard changes. The remaining
tests in the measured broad run were <= 4.84 s; broad timing was not rerun
solely for this classification change.

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

Two dedicated browser cases pass (ordinary and deleted-slot flexible regions),
checking solver/contact diagnostics, fixed poses, flexible rendering and undo.
Inspected the ordinary relaxed Full view. Temporary captures, both __e2e__ host
files, their project stores, bridge credentials and session/output paths verified
absent after teardown. Lint and diff whitespace checks pass.

## ISSUE-212 — Joint flexible-network solve with a fixed largest cluster (2026-11-17)

The old pairwise Relax all leaves three JJ_Hinge tethers at 7.785, 5.892 and
6.940 nm against 1.18 nm contours; successive pair solves undo previous closure.
The shared backend kinematic solve now minimises all positive contour violations
jointly, fixing the largest participating rigid cluster in each connected
component and giving other bodies translation/rotation freedom. Exact-base and
domain membership participate in the size calculation. Slack remains free.

The existing Relax API accepts scope requests, independently checks final posed
anchor distances and the fixed reference, and commits only converged, current-
revision results. App and headless authoring share this path. The feature stores
explicit absolute poses, solver settings, fixed IDs and actual final per-tether
measurements. Its new proof contract replays poses without rerunning optimisation.
Pose-only recording preserves topology and avoids pending-ligation retries.

Validation: 48 focused backend tests pass, including recorded import/mark/relax,
guarded publication, saved/reopened independent replay, undo/redo, rollback,
rotation composition and the optional read-only JJ_Hinge numeric regression.
That regression closes all 11 tethers to within 0.001 nm with Geometry Cluster 1
fixed. The legacy source has no recipe root and was not modified or republished.
Three browser checks pass: ordinary and deleted-slot two-base relaxation plus
read-only JJ_Hinge rendering. Screenshots inspected and removed; test workspace
files and dedicated bridge credentials verified absent after teardown.

Frontend: 10,560 passed / one skipped across 959 files; final focused controller
and client checks: 18 passed. Lint and diff whitespace checks pass.
Smoke: 23 passed / two skipped / existing ISSUE-180 Square New Part request
assertion fails (`lattice_type` undefined). No New Part changes.

`just test-smart`: FAST, 20,978 passed / 19 skipped. Aggregate timing warning
(510 seconds pytest wall time, no individual budget violators); required triage
found broad suite volume and existing mock lifecycle/replay work, with no reason
to reclassify tests or alter guards. Deferred output:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

`main.js` LOC Δ: 0.

## ISSUE-211 — Fixed-duration thermal ramps (2026-11-17)

Reduced the default from 50M to 10M steps per temperature. The wizard exposes
one duration and an exact total; adaptive controls and duplicate production
steps are removed. Every stage uses the chosen fixed count. Legacy gate fields
cannot enable adaptive execution; budget-extension requests reject without
mutation. Energy histories and descriptive statistics remain available, without
automatic exponential fits or stability verdicts. Numerical health checks remain.
Existing workers and saved durations were not restarted or resized.

Validation: FAST 20,982 passed / 90 skipped; frontend 10,662 passed / one skipped;
focused backend 22 passed / one deselected, skip 11 passed, monitor 4 passed,
frontend 29 passed. Both browser workflows passed; desktop, 760px and 480px
screenshots visually reviewed with aligned, unclipped thermal controls. Ruff and
diff checks passed. FULL deferred in .nadoc-slow-pending. main.js task LOC delta 0.
Receipt: `.development-artifacts/oxdna-fixed-thermal-20261117.json`.

## ISSUE-210 — Manual thermal-stage advance (2026-11-17)

Parent and all temperature child context menus now expose Skip to next stage.
The expected active-stage name guards stale clicks; the final temperature is
ineligible. A detached controller terminates the current owner, acquires the
idle lease, validates/recovers its checkpoint, preserves samples/prior verdicts,
marks the stage skipped and starts the next temperature. Fresh generation
publication prevents the new worker inheriting the old Stop mailbox. Natural
completion, concurrent execution, duplicate commands and later Stop requests
are handled without skipping an unintended temperature. Diagnostic failure does
not prevent a manual advance; a valid starting configuration is still required.
Restart reconciliation and progress account for skipped stages without treating
them as equilibration passes. Failed handoffs surface in the command and job error.

Validation: 11 focused skip tests, 14 shared runtime tests, 126 focused frontend
tests; browser parent/child menus and final-stage disabling passed with mocked
jobs. FAST 20,980 passed / 90 skipped; frontend 10,661 passed / 1 skipped. FULL
remains deferred. Cleanup verified. No real user stage skipped. main.js task
LOC delta 0. Receipt: `.development-artifacts/oxdna-thermal-skip-20261117.json`.


## ISSUE-209 — Energy metrics and thermal plot annotations (2026-11-17)

Added an independent, read-only oxDNA potential-energy Generate/Display/Export
path. It reads production/field energy histories during active jobs without
trajectory geometry, retaining resumed samples and ignoring unfinished output
lines. Plots and PNGs annotate executed thermostat setpoints at stage boundaries;
CSV carries native time, potential energy per particle, temperature, stage and
job identity. Job/scope caches prevent another selection's graph from appearing.
Nearby energy-axis ticks now retain enough decimal places to remain distinct.

Validation: live job 67bdaecee7f3 generated/displayed/exported 958 samples at 25°C;
13-temperature layout independently reviewed with a plotting fixture (the older
completed ramp was no longer in the library). Four energy-series and ten existing
energy-fit tests passed; focused graph/card tests 32 passed; frontend suite 10,657
passed, one skipped. Backend FAST 20,970 passed / 90 skipped, with one unrelated
repair-draft capture-time-limit setup error; exact isolated rerun passed. FULL
remains deferred. Main.js task LOC delta 0. No simulation launched or changed.
Evidence: `.development-artifacts/oxdna-energy-metrics-20261117.json`.


## ISSUE-208 — Full-history exponential energy diagnosis (2026-11-17)

Gate v3 fits all distinct energy times at the current temperature to
E_inf + A exp(-t/tau), including resumed segments reconstructed from attempt
receipts. Acceptance bounds remaining relaxation with correlation-adjusted local
parameter uncertainty and checks fit identifiability, residual structure and
independent information. Flat histories are explicitly constant-model diagnoses.
Pairing remains a separate optional window check; fixed dwell remains nonblocking.

Every raw native energy row remains stored; display-ready JSON includes potential,
kinetic and total energy, segment identities/times, source hashes, fitted values
and diagnostics. Periodic check files retain earlier fits. The thermal-metrics
API serves these alongside untouched historical decisions. Idle-job backfill was
verified on 13 completed temperatures; the 67-segment audit retained 4,355 raw
rows and fitted 4,289 distinct times. The shorter completed curves do not establish
a reliable plateau under the new diagnosis; no physical rerun was performed.

Validation: 10 fit + 24 ramp focused passed; frontend 10,655 passed / 1 skipped;
browser 1 passed, cleanup verified. Backend FAST: 20,966 passed / 90 skipped, one
VR test isolation failure (a late trajectory-precompute launch intercepted by its
subprocess mock); that exact test passed alone. Broad FULL remains deferred.
No per-test timing violators. Main.js task LOC delta: 0. Evidence and plots:
`.development-artifacts/thermal-exponential-fit-20261117/`.

## ISSUE-207 — Fixed-dwell stability reporting and real CPD ramp (2026-11-17)

Fixed dwell now evaluates stability and records `gate_enabled: false` plus an
honest `stability_status`; an unsettled observable no longer masquerades as a
stability pass. Completion remains independent of that diagnostic. Regression
checks cover a fully melted state, failed stability with successful fixed dwell,
and event-driven terminal/stall notifications. No main.js task changes.

Real job 60694a597e17 completed all 13 CUDA plateaus, 25–85°C, 5M steps each,
65M total, at 02:58:57 America/Denver on November 17. Zero native failures or
numerical retries; finite energies and all checkpoints/target inputs verified.
Trajectory API exposes 6,500 frames and 13 markers. Only 60°C passed its energy
stability diagnostic; 12 plateaus remain unconverged by that criterion. Endpoint
pair retention was 83% at 85°C, so the expected 40–60°C bulk melt was not observed.
The earlier adaptive run remains stopped with its evidence intact (25°C passed
at 67M, 30°C at 3M before the user selected fixed dwell).

Validation: FAST 20,957 passed / 90 skipped; 23 thermal + 4 monitor focused passed.
Aggregate 185.90s, zero per-test timing violators; broad FULL suite remains deferred.
Receipt and per-stage CSV: `.development-artifacts/cpd-melt-ramp-20261117/fixed-dwell/`.

## ISSUE-206 — CUDA CPD interaction and managed GPU thermal ramps (2026-11-16)

Added checked-build CUDA DNA2 kernels with permanent CPD forces/body torques,
reacted-pair exclusions and preserved backbone FENE. Frozen CUDA hashes accompany
the original model; CPU parents can create GPU continuations. Removed forced-CPU
job/edit rules, exposed production backend, and recorded idle-job backend changes.
Build, audit, benchmark and full-ramp scripts are reusable. Main.js task delta: 0.
Validation: `.development-artifacts/cpd-cuda-force-audit.json`,
`cpd-cuda-ramp-validation.json`, `cpd-cuda-benchmark.json` and final receipt.
The 96-nt user checkpoint measured 2.90× CPU throughput with managed edge lists.
Stopped ramp 175f1c31fdd9 now uses CUDA for remaining MD; its 17M-step checkpoint,
stage statuses and gate configuration are preserved. It remains stopped.


## ISSUE-205 — Accumulate thermal evidence and resume exhausted sampling (2026-11-16)

Gate v2 grows three trailing windows deterministically with completed blocks,
bounded at 1,000 samples/window, retaining the original tolerances and ESS floor.
Pass streaks cannot mix gate versions. Explicit start-request budget extensions
preserve failed verdicts and all outputs, advance the step target by one block,
and resume the same temperature. Tests cover correlated stationary evidence,
continued drift rejection, preserved outputs and saved/reloaded resume metadata.
Main.js task LOC delta: 0. Receipt: `.development-artifacts/thermal-gate-repair.json`.



## ISSUE-204 — Preserve ramp submission and select temperature trajectories (2026-11-16)

Forwarded the wizard's thermal settings through the production submit handler.
Temperature children now select actual managed stages, with matching timeline
markers and streamed frame ranges. Parent selection loads the full ramp. The
browser regression exercises wizard submission rather than only fabricated list
entries; focused backend tests include resumed segments and exclude ancestors.
Task changes to main.js: 0 lines. Validation receipt:
`.development-artifacts/thermal-selection-validation.json`.


## ISSUE-203 — Visually verify and format the thermal wizard (2026-11-16)

Replaced raw inputs and inherited tall rows with themed controls, adjacent
checkbox labels and grouped responsive fields. Inspected rendered desktop,
narrow and small-window views; input alignment and bounds are checked in the
existing browser workflow. Main.js LOC delta: 0. Review receipt:
`.development-artifacts/thermal-ramp-layout-review.json`.


## ISSUE-180 — Await the Square-lattice creation request (2026-11-16)

Replaced a fixed sleep with Playwright's matching-request promise. The original
smoke run had 23 passed, 2 skipped and this race failure. The next run passed
Square creation but hit the known Close Session busy-overlay wait. That test now
awaits fixture sequence completion before asserting the geometry busy modal,
which is intentionally suppressed during sequence writes. Final full smoke: 24
passed, two skipped; cleanup verified. No app behavior changed.


## ISSUE-202 — Skip background work for deleted jobs (2026-11-16)

MD and oxDNA background analysis now stop when their queued job has been deleted.
This resolves the cleanup race observed during the four-isomer CPD browser check;
existing malformed job manifests still raise errors. No simulation physics changed.


## ISSUE-201 follow-up — Preserve colors and follow displayed atoms (2026-11-14)

Push integration: merged incoming exact-base cluster selection fixes without
dropping atomistic connection/copy handling or either presentation regression.
Renumbered these atomistic records to ISSUE-200/201 because incoming history
already uses ISSUE-197–199. Merged frontend validation: 965 files, 10,622 passed,
1 skipped; atomistic browser regression passed (32.5 s).

The first fix was incomplete: native selection explicitly painted atoms white,
and a separate `Presenter selection` point cloud still drew green discs at coarse
positions. Checking only `selectionGlow` and white instance colors missed both.

Non-surface atomistic selection now uses a color-preserving silhouette outline
of actual sphere/cylinder instances. Cached membership is rebound on rebuilds;
current instance/world matrices, clipping and visibility are used when drawing.
Annotation and atomistic outline providers coexist. Cluster/group bounds retain
actual atom/bond instances without applying the coarse surface tint. Existing
coarse glow follows whole-design visibility even after MD hides its source root.
The presentation cloud is a non-painting local ping/export target, updated from
live selected atom/bond instances; prepared-viewer halos remain supported.

App verification: opened existing 2hb_2xT, selected P3 Alpine (da4af0483372),
Display MD, Ball-and-stick, S1. Inspected pixels: red strand surfaces retained,
green outlines track atom/bond contours, no coarse discs. Confirmed 693 selected
instances, zero instance-color changes, hidden coarse glow, non-painting presenter
cloud. Switching to native positions rebinds the selection to 699 instances.
No molecular structure or simulation run was authored/modified.

Additional app verification used the existing P3 trajectory, sampled every 1000
frames (25 displayed frames): stepping frame 1 → 2 moved S1's atom/bond outline
with the displayed coordinates. Stick used only `atomBonds`; VDW only
`atomSpheres`. Native/MD/trajectory view switches preserved selection. The final
outline also checks scene depth so hidden atoms cannot outline through the
foreground. Temporary screenshot captures were inspected and removed.

Validation so far: `just test-frontend` — 962 files, 10,602 passed, 1 skipped
(190.22 s). Final focused presentation/silhouette/tint/highlight tests — 51 passed.
Targeted browser regression passed (33.3 s), including all three non-surface
representations, click targets, preserved colors and no painted presenter points.
Build passed (6.32 s). Smoke: 22 passed, 2 skipped, two failures — the existing
Square-lattice assertion (ISSUE-180), plus Close Session's progress-modal timing.
The latter passed in isolation (40.0 s); no smoke assertions were weakened.

Final review also added an atomistic mesh-rebuild notification for cluster/group
bounds, including equal-count MD/native replacements, without broadcasting every
coordinate-only frame. Group bounds also refresh on each display frame, with callback cleanup on
renderer disposal. Final full frontend run: 962 files, 10,604 passed, 1 skipped
(185.98 s). Final focused checks, including the display-frame integration added
after that run: 68 passed. Final browser regression: 1 passed (32.3 s). Final
build passed (6.17 s); `just lint` and `git diff --check` passed. `main.js` has zero net line growth (thin wiring only).
Cleanup verified: no __e2e__ parts/project manifests, Playwright output directories,
or temporary review captures remain. Removed the owned diagnostic script and
failed-capture metadata (3,538 bytes); screenshots were removed by their browser
workflow's finally block. Existing user structures/jobs and unrelated worktree
changes were preserved.

Observation limits/retries: the attached viewer was hidden, so review used a
separate browser at 1500×1000. Initial UI locators encountered hidden duplicate
job rows and a status label appended to Display MD; the real controls were then
used. The last VDW occlusion review showed the rendered atom scene correctly,
though the MD status indicator remained “warming…”; no new latest-frame arrival
is claimed from that last capture. Earlier Display MD and explicit trajectory
frame-stepping checks establish coordinate tracking. No refresh was forced past
the disabled remote-job control.

## ISSUE-201 — Highlight the active representation (2026-11-14)

Initial attempt (superseded by the follow-up below): the coarse-glow compositor resolves every pool against current source visibility
and representation on every composition. It no longer restores raw Full entries
when another selection pool refreshes. Atomistic selection uses native atom and
bond colors, not generic bead-radius halos. Cluster/group bounds exclude hidden
instances and Stick's private sphere proxies. Coarse connection highlights remain
available in Full/Beads/Cylinders, but not in their atomistic replacements.

Native highlights cover strands, domains, bases, ends, overhangs, extensions,
clusters/groups, bonds and crossovers. Explicit connection records select actual
covalent bonds; VDW selects their physical endpoint atoms. Insert copies and
extra crossover bases are matched by canonical identity. Coordinates are unchanged.

The app regression checks real clicks, strand/domain/base/end highlight colors,
zero coarse selection glow in all three atomistic representations, and restored
Full glow on switching back. Inspected Stick output shows the selected nucleotide
on its white bond cylinders. Unit regressions cover all native filter mappings,
connection endpoint identity, hidden/mixed representations, and manager-level
recomposition. Validation: 961 frontend files / 10,596 tests passed (one skipped), browser
regression passed, build/lint/diff checks passed. Smoke recorded 22 passed,
two skipped, the known ISSUE-180 Square-lattice assertion and an assembly-fixture
load timeout. The isolated assembly retry passed (15 s) without changing its
thresholds. Test parts, recent project snapshots, browser outputs and isolated
bridge credentials were removed. Logs: `.development-artifacts/atomistic-highlight-*`.
`main.js` LOC delta: 0.


## ISSUE-200 — Pick displayed atomistic balls and sticks (2026-11-14)

Extracted `atomistic_renderer/picking.js`: VDW tests spheres, Ball & Stick tests
spheres and cylinders, Stick tests cylinders only. Bond hits retain nucleotide
identity through the nearest endpoint in the live cylinder frame. Visibility,
instance alpha, clipping and moved-instance bounds participate in picking.
Global and regional design selection reuse this implementation; the separate
shared-assembly bounding-box picker remains unchanged. No molecular edits.

Validation: 957 frontend files / 10,548 tests passed (one skipped); build, lint
and diff checks passed. Smoke: 23 passed, two skipped, one known ISSUE-180
Square-lattice request assertion failure. The browser click regression passes
for VDW, Ball & Stick and Stick (23.6 s). Earlier browser failures were test
state carry-over: clicking the same selected base toggled it off; the final
fixture clears canonical selection between modes. Inspected ball/stick screenshots
confirmed the rendered target. Temporary screenshots and workspace test artifacts
were removed; no recent picking-test project snapshots remain. `main.js` LOC delta: 0.


## ISSUE-198 — Flexible flags survive Relax all geometry refresh (2026-11-14)

The live JJ_Hinge design retained 22 marks and 11 two-base connections after
Relax all. The compact partial-helix response omitted `is_flexible_segment`,
causing rigid meshes to recreate those bases. Shared compaction now emits sparse
`flex` booleans; the shared frontend codec restores them. Marked designs bypass
the native compact shortcut so its binary feed also retains complete metadata.
No molecular geometry or solver change; no user document mutation.

Validation: both Full-mode browser relax-all cases pass (ordinary two-base and
deleted-slot anchor), asserting two arc beads, two geometry flags and zero marked
bases in rigid meshes. The initial browser attempt failed on missing dev facade
access before relaxation; exposing the existing gizmo and using getDesignRenderer
corrected the harness. All 37 focused backend tests pass; frontend suite passes
10,507 tests, one skipped, across 950 files. Build and lint pass. Smoke has
23 passes, two skips and the existing assembly fixture-load timeout at
scene_harness.js:88, before assembly exit. Test workspace artifacts, bridge
credentials and managed reports were verified absent after teardown.

`just test-smart`: FAST; 20,950 passed / 19 skipped. Aggregate timing warning
(538 seconds, zero individual violations); mandatory triage found broad suite
volume and existing mocked-job work, not a new per-test offender. No timing
limits or slow classifications changed. Its deferred report is:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

Evidence: `.development-artifacts/flex-relax-{smart,frontend,app-final,focused-final,smoke,build,lint}.log`.
`main.js` LOC delta for this fix: 0.

## ISSUE-197 — Exact cluster membership for both highlight layers (2026-11-14)

The solid green tint was correct; the separate Presenter selection halo resolved
base clusters as whole helices. `annotation_targets` now shares the canonical
cluster membership predicate used by mesh tint. Linear and indexed resolution
retain loop-copy identity, mixed-domain ownership and claimed-base exclusions.
Before-fix regressions fail on excess halo points; corrected regressions check
actual point positions and tint after sidebar selection. No user design edits. All nine saved
JJ_Hinge clusters pass exact tint and halo membership, including all six 24-base
clusters and deselection; before/after PNGs were inspected. Both rectangle/Ctrl-click
browser workflows pass. Full frontend run: 10,503 passed, one skipped, three failures
from an incomplete submodel fixture; adding its required helix/strand records fixes
those cases, and the final 84-test focused run passes. Production code was unchanged
between that full run and the fixture recheck. Build and lint pass. Smoke:
22 passed, two skipped; existing assembly fixture-load timeout and Square New Part
request-capture failure recur. Test workspace files, revision stores, bridge
credentials and managed reports were cleaned. `main.js` LOC delta: 0.

## ISSUE-195 — Preserve annotation text box precision (2026-11-14)

- `annotation_font_fit.js` retains fractional measured width/height and explicitly
  fixes the inner box dimensions before absolute positioning. This prevents a
  second shrink-to-fit pass from wrapping “Anchors” at the unchanged 13 px font.
- Reproduced two text line rectangles before the fix; one afterward. Regression
  covers fractional fonts, viewport resize, explicit newlines and narrow boxes;
  existing browser resize/rotation workflow also passes. No molecular data edits.
- Validation summary: `.development-artifacts/annotation-text-fit/validation.json`.

## ISSUE-194 — Routed scaffold ends inherit an earlier deformation (2026-11-14)

New Autoscaffold commands record terminal deformation inheritance. Added scaffold
runs inherit their existing root's selected membership, per helix/direction;
original ranges and Bend parameters remain on the original feature row. Cached
history restores the later routing-owned scopes; native replay derives the same
ranges. Legacy commands keep their recorded behavior. No helix-phase constants,
deformation formulas or routing topology algorithms changed.

The initial corrected guide contained 61 images, including eight complementary views at F3,
F4, F5 and after returning to F5. Actual image review rejected an initially
clipped capture; the accepted recipe fits after each orbit. End-region views
expose both terminal loops. The saved/reopened example passes independent
publication audit without using recovery snapshots. Desktop checks verify
Autostaple (allowing its expected scaffold sequence assignment), scrub,
suppression, Undo, loadouts, two cadnano end resizes and reopen. All 2,057 tested
consecutive scaffold-base pairs stay within 0.621 nm after routing and scrubbing.
The maintenance procedure now explicitly evaluates whether the guide's views can
expose bugs, requires inspection of the images, and records findings/limitations.

Reopening a Save As copy also requires its filename-to-name edit to be recorded.
Library open now records the native `document-metadata` rename and omits no-op
renames; its regression verifies independent replay and repeated-open idempotence.

Validation: six focused inheritance/history regressions and 24 guide-tool tests
passed; the complete
browser capture passed in 6.7 minutes. HTML matches the capture and Feature
History reports CURRENT with no problems. `just test-smart` decision FAST:
20,944 passed, 19 skipped in 574.86 seconds.

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

Timing triage followed `.claude/skills/triage-slow-tests/SKILL.md`: five existing
mock-binary integration tests ran real subprocess lifecycles over the 5-second
budget. Registered individually in `_SLOW_TESTS`, all with area `oxdna`:

- Detached worker ownership after launcher exit: 6.41 s, subprocess imports and
  intentional 0.5-second delays in each mock stage.
- Deflecting-field validation: 5.51 s, relaxation plus field subprocess stages.
- Wrong-target inter-helix measurement: 5.31 s, relaxation/production plus
  trajectory parsing and measurement.
- Field-ready specimen: 5.23 s, construction, relaxation and field-stage checks.
- Append production: 5.18 s, initial relaxation followed by a production stage.

Collection confirms all five remain in slow coverage (46 selected in the two
modules, 298 deselected). The full fast suite was not repeated after this
classification-only change; no budgets or guards were weakened. Both browser
scratch roots were verified absent after cleanup, including the rejected capture.


November 14 designer-guide revision: removed the advanced repair proposal,
its input-selection setup and follow-up Undo capture. The guide now has 56
images. Move uses the shared NADOC select primitive and fits within its modal;
step 37 was visually reviewed with measured text/background contrast 16.02:1.
Frontend: 10,491 passed, 1 skipped. The isolated commit-source browser capture
passed in 6.7 minutes, including saved/reopened independent audit and all scaffold
preservation checks. HTML and guide freshness checks passed. The six routing
regressions, 24 guide-tool tests and the library-open provenance test also passed
against the isolated commit sources. Browser scratch
`/tmp/__e2e__guide-fa7brspb` was verified absent after cleanup.


The first push encountered concurrent master updates. Merged in an isolated
worktree, retaining both issue-log entries and both slow-test lists. Recapture
against the merged code passed in 6.8 minutes with independent saved/reopened
replay, scaffold preservation and 16.02:1 dropdown contrast. Browser scratch
`/tmp/__e2e__guide-kyfz3guz` was verified absent. The full frontend count above is
from before this merge; the merged code receives the full guide workflow and
focused Feature Log checks rather than an unrelated full-suite repeat.

## ISSUE-193 — Exact atom sources for MD zoom insets (2026-11-14)

- [x] `md_inset_source.js` owns a representation-independent MD source. Only
  requested residue snapshots are retained (at most five frames); the existing
  lightweight model/frame endpoints supply original atom identities and bonds.
  Flex previews reuse their supplied atom means/topology. Playback interpolation
  operates on atom coordinates. Changed frames/ranges invalidate pending paints.
- [x] Inset atom layers use the exact source's topology and positions, wait visibly
  while data is pending, and restore native topology on exit. Display MD publishes
  selected atoms from its atomistic stream as well as its Full inset stream.
- Real P1 frames 21547–21549 (zero-based): raw versus aligned within-residue
  distance error < 9.75e-8 nm; the float32 flex mean matches the independent mean
  exactly. In-browser Full/ballstick agreement: 265/265 atoms, zero flex error,
  < 9.89e-7 nm relative-coordinate error for frames/interpolation. Real renderers,
  read-only existing source, replayed coordinate transport. Inset image inspected.
  `main.js` LOC Δ: 0. Validation logs use `.development-artifacts/inset-*`.
- Final validation: frontend 10,491 passed / 1 skipped; 235 focused checks and
  5 source/cancellation checks passed; both P1 browser checks passed. Display MD
  has zero rendered-coordinate error for all 265 atoms and 293 bonds. General
  smoke: 21 passed, 2 skipped, 3 failures in the recorded New Part / assembly
  fixture areas (ISSUE-179/180). No newly persisted browser/test artifacts.

## ISSUE-180 — Smoke follow-up during flex settings (2026-11-13)

- [ ] Square creation request assertion remains unresolved; Honeycomb creation
  request capture also timed out in this run. No New Part implementation changes.
  Dedicated flex preview/settings app checks: 2 passed. Evidence:
  `.development-artifacts/flex-settings-smoke.log` and `flex-settings-app-final.log`.

## ISSUE-199 — Periodic preview buffer ownership and Bend command admission (2026-11-13)

Shared assembly rendering intentionally migrates source matrices/colors into GPU
textures. The periodic continuation preview still reread those retired buffers
on traversal. Preserve its already computed transforms for shared sources;
geometry changes rebuild the shared source. The regression reproduces the null
color failure and checks retained transforms. Frontend suite: 10,457 passed,
1 skipped. No molecular placement changes; `main.js` LOC delta 0.

Bend prefix admission omitted the supported native `route-for-polymerization`
command. Added it to ordinary unestimated routing commands without changing
resource bounds. Focused tests cover both a small and guide-sized 6HB through
prepare/evaluate/native append and independent history replay (2 passed).
Guide-sized coverage also checks the explicit manual bend's six-repeat closure.
The asynchronous closure readout and automatic angle accuracy remain open.


The publication guard then caught an unrecorded filename-to-name stamp on library
open after Save As. Record that existing user-facing metadata edit through
`document-metadata`; preserve the original input and omit no-op renames. The
regression failed before the fix and passed afterward (1 passed). No audit
exemptions were added.


## ISSUE-192 — Nonblocking sequence-work spinner and scoped geometry (2026-11-12)

Subsecond follow-up: removed the redundant FastAPI response traversal, hash only
history bodies actually transmitted, reuse exact serialized recovery entries,
and avoid visibility notifications when the hidden sets have not changed.
Same-length sequence-only changes now reuse geometry after proving every other
model field equal. Targeted staple assignment derives only requested strands;
a bounded immutable scaffold lookup is keyed by complete sequence, traversal,
loop/skip and reference precedence inputs, with fresh mutable results for callers.
No history bodies, validation checks, or completion paints were removed.

The target is **not yet met for resizing**: the latest browser samples are
**1448.3, 1357.0, 1441.0 ms** for growth/shrinks and **981.2 ms** for a same-length
substitution. Backend profiling fell from 602.7 to 366.0 ms, but native rendering
under concurrent NAMD load (GPU observed at 99%) still adds roughly 360 ms for
completion paint; deferred scene consolidation also overlaps subsequent edits.
The camera is explicitly framed outside timing in this follow-up, so comparisons
to earlier unframed samples are diagnostic, not a controlled A/B claim.
Final repeat: **1107.3, 1165.2, 1648.1, 1150.2 ms**. Even the same-length
981 ms result was not repeatable; no subsecond acceptance claim. Inspected both
the live spinner/editable draft screenshot and the framed completed scene.
Validation: FAST **20,844 passed, 90 skipped**; frontend **10,455 passed,
1 skipped**; final browser **1 passed** with source-file hash unchanged; lint
and whitespace checks passed. Browser teardown removed its output and scratch
artifacts. `main.js` LOC delta remains 0. Removed completed test
scratch after process-reference checks: 2,775,022,674 logical bytes.
Evidence: `.development-artifacts/sequence-subsecond-20261112/`. Failed fixture
setup tests and all slower browser samples are retained in the logs.


- [x] Track sequence writes, queued replacements, geometry application/final paint,
  generated-sequence checks, and live-check debounce/request lifetimes with a shared
  nonmodal spinning indicator. Keep sequence controls editable; suppress duplicate
  request popups for the owned work.
- [x] Serialize authoring writes and coalesce only unsent drafts; discard queued
  work after document reset. Preserve active drafts and Set buttons in main/2D
  spreadsheets and the Overhangs panel. Domain Designer retains its existing
  in-place annotation updates. Explicit sequence writes can pass passive reads.
- [x] Embed scoped geometry in the sequence response instead of rebuilding the old
  scene, fetching full geometry, and rebuilding again. Same-length edits refresh
  affected sequence-dependent strands. Posed/complex designs retain full fallback.

Validation: FAST backend **20,842 passed, 90 skipped**; frontend **10,452 passed,
1 skipped**; focused backend **12 passed**; final browser **1 passed**; lint and
whitespace checks passed. The browser uses real spreadsheet Enter/blur gestures,
proves the middle unsent draft is not written, preserves a further unfinished
seven-base draft through both responses, and checks spinner completion. Inspected
its actual rendered wheel and editable QD_OH1 cell. The read-only source hash matched
before/after the browser run (the user's current file has a seven-base QD_OH1).

Natural completion samples with the spreadsheet open: **1661.2, 1591.7, 1595.4,
1845.8 ms** (growth/shrinks/same-length substitution, including final paint).
Earlier full-geometry traces were 3545–5198 ms; these are diagnostic comparisons,
not a controlled same-state A/B guarantee under active NAMD. No checks were removed.
The first two browser attempts exposed welcome-screen spreadsheet hiding in the
API-load test setup; corrected observation setup, retained failure/interruption logs.
Early frontend failures included stale modules during edits and fake-clock tests
not advancing paint; the final clean run passed. Remaining visual-surface review:
MV-67. Broad smoke refused by active-NAMD guard; no override used.

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

Removed completed pytest artifacts after process-reference checks (5,550,331,213
logical bytes); Playwright's standard teardown/report cleanup removed browser
artifacts. Evidence: `.development-artifacts/overhang-sequence-feedback-20261112/`.
`main.js` LOC delta: 0.

## ISSUE-191 — Subsecond visible QD_OH1 undo (2026-11-12)

Redo follow-up: retained only the preceding history request's original entries
within the same document scope/design, so redo can acknowledge an edit body
removed from the current history by undo. Current same-ID bodies take precedence;
retained entries never enter the authored document. Added isolation, bounded
retention and exact recovery-body tests. Initial redo was 990.4/1062.0/986.8 ms.
After the fix: **687.5/905.4/899.1 ms**, then **927.8/892.2/918.6 ms** in the
visual-review run. Both runs include a Redo-menu sample; all six are <1,000 ms
through two animation frames. Root/free end 1223/1214; source hash unchanged.
Framed and inspected the actual redo rendering, with review hold outside timing.
Frontend **10,446 passed, 1 skipped**; focused cache **6 passed**; lint passed.
Evidence: `.development-artifacts/qd-redo-performance-20261112/` and reusable
`frontend/e2e/qd_overhang_undo_latency.spec.js` (undo/redo parameterized).


- [x] Remove the previous-design deep copy, acknowledge identical recovery bodies
  by content, and scope geometry to the changed domain's helix. Feature records
  retain exact authored content; cache tokens live outside the records.
- [x] Remove redundant display work, allow one undo/redo past a passive read,
  and defer complete local recovery serialization until after the restored frame.
- [x] Check same-ID body replacement/clearing, request-cache races, previous-state
  immutability, partial/full geometry equivalence, and overlay visibility.

Final native-GL browser measurements on the real read-only VoltronCoreArmV2 file:
**653.9 ms, 861.9 ms, 987.6 ms** through two animation frames after restoration;
the last sample uses the Undo menu. All three pass the strict <1,000 ms assertion.
The restored root/free end are 1223/1209. Inspected the framed rendered screenshot;
source SHA-256 unchanged. Earlier runs exceeded a second, including a 1,096 ms
sample after the interactive-lane fix under active NAMD load; these results are
retained, so this is measured attainment, not a worst-case latency guarantee.
Browser artifacts cleaned by the standard reporter. Completed broad-test temporary
files removed after process-reference checks (5,550,048,281 logical bytes).
Evidence: `.development-artifacts/qd-undo-performance-20261112/`.
Validation: FAST backend **20,840 passed, 90 skipped**, with one verification
HTTP 408 (0.5-second deadline under active NAMD); that exact test **passed in
isolation**. Final history-body checks **5 passed**. Frontend **10,444 passed,
1 skipped**; focused browser **1 passed**, lint and whitespace checks passed.
Broad smoke refused by the active-NAMD guard; no override. Full backend deferred:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

`main.js` LOC delta: 0.

## ISSUE-190 — Preserve overhang roots and refresh undo connections (2026-11-12)

- [x] Scope sequence resizing to the selected overhang's terminal domain; retain
  shared helix occupancy and dedicated-root position/orientation.
- [x] Include strand junctions in connection invalidation, so undo/redo rebuilds
  arcs immediately even when crossover IDs and counts remain unchanged.

Validation: FAST backend **20,835 passed** (90 skipped); frontend **10,435 passed**
(1 skipped); lint passed. App exercise remains MV-66 (active-NAMD smoke guard).
Full suite deferred without a test session. Saved/reopened native history audits pass.
Disposable pytest output removed after process-reference checks (5,550,079,208
logical bytes); compact logs/diagnosis retained under `.development-artifacts/qd-oh1-resize-20261112/`.

## ISSUE-189 — Late Slurm stderr inventory (2026-11-12)

- [x] Recheck mismatching downloaded files against fresh remote sizes; preserve
  rejection when remote verification fails. Repaired Gerling's saved download
  state through normal worker retry, preserving its continuation checkpoint.

## ISSUE-188 — Exact zoom-volume base selections (2026-11-12)

- [x] Resolve extension, loop-copy, crossover-insert and separately rendered
  linker/flexible bases; keep native insert display poses and exact connectors.
- [x] Preserve extension and loop identity through atomistic JSON serialization.
- [x] Add selection, display, persistence and transport regression coverage.
- Validation: 10,396 frontend tests passed (one skipped); two final browser
  checks passed, including independent replay/guarded publication and assembly
  exit. Lint passed. Initial smoke: 23 passed, two skipped, one fixture timeout
  subsequently passing in isolation.
- Backend selector: FAST; 20,852 passed, 19 skipped, one history-verification
  deadline failure that passed in isolation (0.11 s call). Aggregate guard:
  496 s against 90 s, zero per-test violators; no limits or markers changed.
  FULL remains deferred in `.nadoc-slow-pending`. Evidence:
  `.development-artifacts/zoom-volume-bases/validation.json`. Test artifacts cleaned.



## ISSUE-187 — Live trajectory readiness and compiled-video indicators (2026-11-12)

- [x] Preserve preparation-event identity through preview and compilation, retain
  valid progress across row rebuilds, and report actual progressive frame availability.
- [x] Add independent per-keyframe compiled-video badges and a duration-aligned rail,
  with stale detection after source or timeline edits and recognition on library Load.

## ISSUE-186 — Placement review released after schema and test-isolation repairs (2026-11-11)

- [x] Repaired display-field ownership, strict empty-state admission, archive copy
  schemas and NAMD display-only identity exclusions. Added preservation and aliasing
  regressions; no molecular geometry or numerical constants changed.
- [x] Scoped cancellation injection and isolated NAMD mocks; completed eight explicit
  incident reviews, preserving original evidence. Placement gate reports clear.
- [x] 380 focused checks, 78 metadata checks and two browser workflows passed.
- One experimental CPD preview-contract failure remains for dedicated review; see
  ISSUE-186 in the ledger. The broad FULL suite remains deferred by the session gate.

## ISSUE-185 — Compile selector and library modal (2026-11-11)

- [x] Styled the native Video size select and options to match the dark sidebar.
- Root cause: the new select had no component styling and inherited browser defaults.
- [x] Library dialog lives in the document body, outside sidebar mirror cloning;
  download progress explicitly respects hidden state.
- [x] Browser checks verify styles, server-to-device download, local reopen, and
  playback without networking. No molecular documents were authored for these checks.


## ISSUE-184 — Presentation export readiness belongs to its document (2026-11-11)

- [x] Added a failing regression for a view-volume host receiving another
  document's presentation event; it previously vetoed frame readiness.
- [x] Ignore that event before rendering or registering pending work. Preserve
  rejection if the owning document changes during an actual pending frame.
- [x] Full-app compiled presentation now exports, then plays/backtracks/replays
  from a downloaded HTML file with browser networking disabled and no HTTP requests.


## ISSUE-183 — Transfer inputs and compact Alpine submission review (2026-11-11)

- [x] User requested standard upload/download fields and a submission popup focused
  on ETA, cost and speed, with collapsed settings and tooltip explanations.
- [x] Reproduced unstyled numeric transfer controls with a failing regression.
  Shared input/button factories now supply the appearance; step 0.1 aligns with min 0.1.
- [x] Alpine review exposes only three estimate rows by default. Settings retains
  editable resource values and partition re-sizing; explanatory metadata and passing
  clearance diagnostics live in the question-mark tooltip. Required clearance decisions
  and submission errors remain visible. Numeric shortcut blocking now recognizes this dialog.
- Root cause: raw transfer inputs bypassed shared styling; the review printed all
  fourteen estimate/resource rows and explanatory notes at the same visual priority.
- App verified: real wizard transfer controls; real review component with representative
  estimates, expanded settings and cancel only. No job submission. Evidence:
  `.development-artifacts/submit-review-20261111/`.
- [x] 10,308 frontend tests passed / 1 skipped; 36 focused tests passed; live UI check passed; 25 smoke checks passed; lint and diff checks passed.
  Source unchanged and scratch cleanup verified. `main.js` LOC delta: 0.

## Full regression follow-up (2026-11-11)

- Synced upstream after committing the existing work. Full `just test` at
  `12958aee`: 21,492 passed, 8 failed, 26 skipped in 2,510.59 seconds.
- Corrected four stale test contracts: detached oxDNA workers no longer share
  the parent test's mocks/thread registry; empty zoom metadata is excluded from
  the v1 preservation digest; the rebuilt BigO fixture has 24,696 paired FEM
  sites rather than the former snapshot's 21,168; the high-resolution 6HB
  surface correctly exceeds the unchanged 128 MiB response budget.
- Marked the mixed-module CPD display parameter scientific, as required by the
  existing opt-in policy. Its underlying display-contract failure is not fixed
  or claimed as validated; ordinary runs now deselect it.
- Still failing: mrDNA zero-step mean error 0.691 nm (limit 0.10 nm), corner
  fold 13 clashes (limit 11), and rod generation rejected for DNA/gold overlap.
  Corner and rod reproduce independently. The mrDNA decoder defect is already
  documented in `memory/project_mrdna_bead_model.md`; its candidate remains
  unapproved. No geometry constants, placement, topology, or thresholds changed.
- Root cause: test expectations lagged current worker, preservation, fixture,
  and resource contracts. The chain failure is not a supervisor timing race:
  its in-process mocks never reached the detached worker.
- Final focused coverage: 50 passed; 1 CPD parameter deselected. Ruff and
  whitespace checks passed. Remaining owned pytest scratch was removed after
  checking live process references; compact logs and summary were retained.
- Evidence: `.development-artifacts/full-test-20261111/`. The full-suite gate
  remains red; focused validation does not clear the full-suite watermark.

## ISSUE-182 — Numeric shortcut scope and interrupted temperature edits (2026-11-10)

- [x] User requested number shortcuts disabled in popups and editable fields, and
  editable NAMD relaxation temperature with the Aksimentiev default.
- [x] Reproduced missing registry-level popup/focus guards and a pending protocol
  response replacing a focused temperature input (five failing regressions).
- [x] Numeric shortcuts now respect open dialogs and focused form/contenteditable
  controls. Temperature input stays attached across plan refreshes, preserving drafts.
- The stable live wizard already accepted typed temperatures; the failing hypothesis
  that relaxation never supports temperature was rejected. Aksimentiev tutorial
  step3 equilibration files specify 300 K for thermostat and barostat; keep that default.
- Evidence: `.development-artifacts/wizard-keyboard-20261110/`.
- [x] 10,272 frontend tests passed / 1 skipped; 115 focused checks passed; live typing/popup checks passed; 25 smoke checks passed; lint and diff checks passed.
  Source unchanged; browser and smoke scratch cleanup verified. `main.js` LOC delta: 0.

## ISSUE-181 — Wizard numeric defaults and literature integrator (2026-11-10)

User authorized standard numeric fields, visible defaults and direct app checks.
The app audit found default values present but inconsistent input styling, invalid
oxDNA step/min grids, placeholder-only stage editors, and a literature integrator
incorrectly pinned to 4 fs/HMR. Standard controls and valid increments fix presentation;
prefilled editors preserve no-op blur behavior; preset-aware integrator resolution
fixes the selected protocol without changing explicit choices or saved jobs.

Root cause: global fast-mode pinning ran before preset resolution, so an automatic
value became an explicit override. The failing unit regression and app preset audit
capture that distinction. The initial missing-server-default hypothesis was not
supported for the literature numeric inputs: the values existed in the plan.
Frontend: 10,267 passed / 1 skipped; final focused: 260 passed; direct app audit: passed; smoke: 25 passed; lint and diff checks passed.
Source unchanged and isolated browser/smoke artifacts removed and verified.
Evidence: `.development-artifacts/wizard-numbers-20261110/`; main.js LOC delta: 0.

## ISSUE-179 — Zoom-list validation follow-up (2026-11-10, unresolved)

Smoke: 21 passed, two skipped; assembly setup timed out waiting for scaffold
meshes, and Close Session failed waiting for its progress indicator before close.
Neither case creates zoom entries. No root cause or fix is claimed; no timeout
or guard changed. Details: `.development-artifacts/zoom-volume-entries/validation.json`.
After pull `84227195`, the same two smoke failures repeated (21 passed / two skipped);
zoom browser and frontend checks passed. Evidence: `.development-artifacts/zoom-volume-pull/validation.json`.

## ISSUE-180 — Square-lattice smoke failure intake (2026-11-10)

Unresolved. Full smoke: 22 passed / 2 skipped / 1 failed; focused retry also
failed (`capturedBody?.lattice_type` undefined). Root cause not established.
Inset zoom app regression and frontend suite pass; no New Part code changed.

## ISSUE-177 — Complete junction sequence display and default picking (2026-11-04)

Root cause: separate consumers treated domain sequences and backbone meshes as
complete inventories, omitted forced ligations, and used independent display
offset arithmetic. Shared topology ownership now supplies copyable sequence runs
and synthetic-base pick entries. The pure projection also preserves loop/skip
offsets and the renderer's 5′→3′ insert indexing.

The broad frontend run passed 10,049 tests and exposed one missing `scrollIntoView`
mock in the new test; corrected focused coverage passes all 73 checks. Browser
fixture corrections account for occlusion, selection-dependent display radii,
Escape preserving selection, and the sidebar's existing expanded state. Production
selection rules and assertions were retained. The overhang gate now uses recorded
authoring instead of an unavailable workstation-specific file. The old lasso tests
now use the existing unmodified-drag gesture; the base lasso uses a side view to
avoid an axial view's overlapping glow spheres. Native ligation's merged-domain
case has separate sequence and ownership regressions. Final checks and
cleanup: [audit](docs/audits/extra_base_ui_20261104.json). `main.js` LOC delta: 0.

## ISSUE-176 — Preserve helix properties during recorded axis edits (2026-11-04)

Root cause: public helix updates and their proof builder reconstructed a new Helix
instead of changing the four supplied fields, silently resetting routing metadata.
Version2 copies the existing helix and changes only those fields; saved version1
rows still replay identically. Public authoring and independent replay share the
builder. Thirty-five native routing/history tests pass. D003's source explicitly
requires 3 nm pitch; the standard 2.25 nm grid produced a poor panel fit.
No phase/rise constants or optimizer formulas changed. `main.js` LOC delta: 0.

## ISSUE-175 — Normalize replay state without recopying recovery caches (2026-11-04)

Root cause: each command normalized the entire Design, including accumulated
snapshot-bearing history that was immediately replaced with the existing prefix.
The 1,592-command D003 build and original publication check reproduced the cost.
Exclude only that redundant history serialization; preserve all command execution,
model normalization, physical comparisons and refusal checks. The cache-independence
regression and all 20 publication-guard tests pass. `main.js` LOC delta: 0.

## ISSUE-174 — Guard shared origami reconstruction (2026-11-04)

D003 follow-up: the apparent 210/166 mismatch was a missed separate 44-strand
edge table. Exact sequence anchors recover M13 offset1515 and every bound domain;
40 recorded bridge inserts retain all226 remaining bases, including ATTTTT.
The source's 3 nm helix spacing is explicit beyond the image/table profile.
Two independent builds have identical molecular authoring fields and fitted poses.
Ordinary loading plus full replay verifies1,692 commands, and the native topology
export preserves14,281 nucleotides and reciprocal bonds. Shared Designs contains
only the generated part; source/recipe/reports moved outside the workspace.
The converged four-panel fit remains approximate (max junction excess6.71 nm);
no simulation-readiness claim. Final qualification: 95 focused checks and four
isolated timeout/timing diagnostics pass. FAST: 20,601 passed / 19 skipped /
seven failed; one assertion corrected, one isolated timeout passes, five known
filesystem/CPD failures remain. FULL deferred. All 32 preview hashes verified;
15 disposable files (119,763,751 bytes) removed. The compact report is
`experiments/origami_publication_catalog/recovery/d003_20261104.json`.
Earlier infrastructure-only evidence follows.


Root cause: the early reconstruction scripts treated importer output plus prose
sidecars as provenance and wrote structures outside the new native feature-log
boundary. Reuse recorded editor commands and group poses; block source snapshots,
unknown authoring adapters, unresolved selections and required unsupported fits.
All-nucleotide rigidity/clearance checks are retained as independent evidence,
not molecular authoring operations. No topology/polarity guesses or phase changes.
The feature-history fix does not establish D003 sequence-to-route equivalence.
`main.js` LOC delta: 0. Final focused validation: 11 shared-workflow tests and
10 import/relaxation tests pass. Real first-five source extraction produces
portable, hash-verified blocked runs with no native parts; D003 records 210
traced staple starts versus 166 extracted staple rows. Broad FAST and timing
triage evidence are retained in `.development-artifacts/shared-origami-validation.json`.

## ISSUE-173 intake — shared workspace validation (2026-11-04)

[ ] Recorded six broad FAST failures and four timing overruns separately from
the Git design-folder change. Four failures trace to unhandled unavailable WSL
drive enumeration; CPD display-contract and preview timeout causes need separate
diagnosis. No unrelated production changes, test reclassification, or budget
changes made. Five focused workspace checks and lint pass; live Library endpoint
shows `Shared Designs` without `.git`. `main.js` LOC delta: 0.

Tracks the "fix next issue" loop (backlog + protocol in `issues_ledger.md`). One row per phase shipped,
one commit per phase. Mirrors `main_js_extraction_log.md` for the carve-up.

**Why this exists:** to keep bug-fixing on the same disciplined rails as the carve-up — repro-first,
test-pinned, routed through extracted modules (NOT back into main.js), gated by vitest + smoke + app
exercise — and to measure whether the loop is actually tight (wall-clock, edits-to-green, did a phase
regress anything).

## ISSUE-165 — Clash and piercing visualization (2026-11-02)

The clash view now combines the existing posed-backbone clash report with the
existing ring-piercing detector on the atomistic display model. Red halos and cyan
wireframe diamonds remain distinguishable when both findings affect one base;
the legend labels and counts them separately. Extension/insert/loop identities
are retained, limited reports are labeled, and shared views preserve the legend.
Pending/failure states replace the old false zero on a null response, and older
async results cannot repaint newer geometry. No molecular geometry or detector
criteria changed. `main.js` LOC delta: 0 (two existing comment lines updated).

Focused checks: 55 frontend and five backend passes. Live app: terminal-linker
zero clashes / one piercing at S37's `Extension - 0[-5›3]` and ›2; corner six
clashes / one piercing. Full off/on and atomistic screenshots visually inspected;
representation return, off clearing and zero browser errors verified. Exact
read-only source copies and disposable app services were cleaned up. Evidence:
`.development-artifacts/clash-piercing-20261102/`.

Required qualification: SMART **FAST 19,954 passed / 19 skipped** (432.80 s),
FULL deferred by the existing session gate; full frontend **9,538 passed / one
skipped** across 801 files (369.40 s); isolated **smoke 23 passed** (2.5 min).
Lint/memory hygiene pass. Aggregate FAST warning reviewed with the slow-test skill:
zero per-test violators, maximum 3.88 s; no guards or test classifications changed.
The handoff retains the selector's verbatim deferral and cleanup evidence.

## ISSUE-162 — Full extension attachment order (2026-11-02)

User-specified correction: S37 position 1 joins `Extension - 0[-5›1]`, not ›16.
The renderer treated extension-local indices as helix bp indices, so parent
FORWARD/REVERSE direction reversed two of the four end/orientation combinations.
Sort extension beads by their 5′/3′ terminal domain before the ordinary helix sort;
this fixes both internal arrows and the attachment arc without moving coordinates.
Actual renderer regression: 2 failed / 6 passed before, 8 passed after; existing loop and
continuation cases make 58 focused frontend passes. Isolated app: all 12 roots join
›1, S37's Properties labels are verified, and the connections survive Full→Beads→Full.
Complete frontend qualification: 800 files, 9,527 passed / 1 skipped (384.68 s). No backend geometry/topology or molecular
candidate changed. The initial test harness lacked explicit slabless fields and
used a nonexistent controller disposer; these fixture errors were corrected before
recording the two genuine ordering failures.

Agent publication also rejects private diagnostic and assembly operations in a
part, even if their independent replay succeeds (18 focused checks pass). This
closes the review-authoring route into ISSUE-163. The user explicitly chose to
track the production conversion change as follow-on work; the shared materializer
is unchanged and ISSUE-163 is deferred. ISSUE-164 records
long-extension molecular geometry as separate work after the feature-log/dependency
overhaul. No approval for the existing isolated linker candidate is inferred.

## FH-27 — private comparison renderer retention (2026-10-28)

Root cause: live DNA templates were uploaded into each private WebGL renderer;
shared geometry/attribute disposal references retained its closed GPU context
and canvas. Comparison-only deep buffer copies preserve exact vertex/index data
and placement, and their existing owner disposes them without touching live templates.
Red browser repro:12 detached comparison canvases after12 closes; corrected:0.
The weak-reference instrumentation hypothesis was rejected by an in-memory heap
retaining path from the live scene through a shared attribute and WebGL buffer.
21 focused checks,12-cycle app repro and visual review pass; full frontend9480 pass/1 skip.
Normal app review/Apply/undo/reopen passes: comparison1106–1154 ms, Apply295 ms.
See [aggregate evidence](docs/audits/feature_history_20261014/implementation.md#aggregate-integration-qualification--october-28-2026).

## ISSUE-126 — collision-free native results and publication (2026-10-26)

Native construction and replay now reject duplicate slot occupancy before
acceptance; ordinary edits and undo/redo require entirely collision-free results.
User decision: partial repair of an invalid source is refused; complete atomic
repair is allowed. Diagnostics retain all claimants and cold-proof attribution.
No molecular placement, polarity, sequence, phase constant or golden changed.
See the [connection plan](docs/audits/feature_history_20261014/ordinary_connection_completion_plan.md)
and [current handoff](docs/audits/feature_history_20261014/session_handoff.md)
for validation, baseline failures and deferred broad coverage. No app claim.

## ISSUE-99 / FH-18 — cluster lifecycle qualification (2026-10-27)

Make Cluster v3 preserves existing placement and records separate creation intent.
Sidebar/context edits, finite dissolution, component repair, reference diagnostics,
undo/reopen and cold replay are qualified; missing recovery refuses atomically.
Failed style/name edits restore display, and style close no longer double-commits.
Nine cluster app scenarios, 23 smoke cases and 9463 frontend tests pass; focused
backend coverage and the persistent broad baseline are recorded in the
[current handoff](docs/audits/feature_history_20261014/session_handoff.md).
Native geometry formulas/constants/goldens and unrelated production gates are unchanged.

## ISSUE-97 / ISSUE-143 — ordinary connection closure (2026-10-28)

Unequal direct Duplex binding now transports endpoint registers after native bind
and inverse operations; the isolated A/B comparison preserved every molecular
coordinate and paired offset. Same-length sequence assignment leaves shared helix
extent and neighboring domains intact. Atomic Connect/Add version, explicit
Reapply and native history/removal gates are qualified in the running app.
Focused backend 560 pass; frontend 93 pass; ordinary family/profile, undo/reopen,
source-reset and downstream-refusal coverage is linked from the
[connection plan](docs/audits/feature_history_20261014/ordinary_connection_completion_plan.md#ordinary-connection-qualification--october-28-2026).
Broad regression results remain separate in the current handoff.

## Validation intake — 2026-11-02 / follow-up 2026-11-03

- ISSUE-109 resolved after explicit user-authorized review: only allocate a DS
  connector after its native bridge boundary arrives. Reusable zero-scale meshes
  remain supported for actual collapsed native endpoints during playback.
- Root cause: playback mesh reuse broadened allocation to missing native records;
  test and picking registration still relied on absence. Initial hypothesis that
  this was only an assertion mismatch was incomplete: placeholders were pick candidates.
- Original failing oracle retained. 53 frontend and 90 native placement tests passed;
  explicit review acknowledged incident `20261103T064355-2dbec3347e96` and gate is clear.
- Post-acknowledgement: 53 focused frontend tests, 23 smoke tests and both YggDNAsil browser tests pass; live backend reports review_required=false with zero incidents. Test artifacts cleaned up.
- ISSUE-110 trajectory buffer failure remains unrelated and open. `main.js` LOC delta: 0.

## Baselines (at loop start, 2026-06-05)

- `frontend/src/main.js` LOC: 9600
- vitest spec count: 725 (66 files) — NOTE: actual count at first run was **906 (75 files)**; the 725
  baseline was stale at ledger creation. Use 906 as the real pre-ISSUE-3 baseline.
- Open issues: 4 (ISSUE-1 context menus, ISSUE-2 cross-tab sync, ISSUE-3 ctrl-click, ISSUE-4 drill)
- Backend test count: ~1786 (frontend-only fixes don't touch it)

## Metrics per phase

| # | Date | Issue / phase | What changed (module) | Repro pinned by | Wall-clock | main.js LOC Δ | tests added | edits-to-green | app-validated | regression caught |
|---|------|---------------|------------------------|-----------------|-----------|---------------|-------------|----------------|---------------|-------------------|
| 49 | 2026-10-17 | ISSUE-145; S17 end-menu repair | Real sidebar markup, existing Properties reveal, explicit selector resolution | S16 two real-gesture failures; real-HTML and scope regression tests | Browser final28.1s | 0 | Five unit cases; retained two browser cases | Both browser cases pass after numeric display-format assertion correction; full frontend result in evidence | **Yes**, isolated tiny native Bend; S18 production smoke 23/23 passed | Mock DOM concealed absent sidebar; hardcoded null discarded explicit selection. [Evidence](docs/audits/feature_history_20261014/bend_end_menu_repair_20261017.md) |
| 48 | 2026-10-16 | ISSUE-135; FH-23 checkpoint 9, investigation only | Native ordering and terminal-tail characterization; production unchanged | Actual empty-root native recipes, independent rigid oracle, exact identities/bonds/unselected controls | 5 cases2.59s;4 cases2.66s;101 existing cases3.34s | 0 | Nine characterization cases | 110 focused passes; [U26 evidence](docs/audits/feature_history_20261014/validation_member_motion_order.json); issue remains open | **No** — isolated scalar evidence only, no approved molecular artifact | Atomistic terminal-key fallback also moves tail atoms, while Full synthetic tail IDs miss that pose; ordinary owners/final passes also fail chronological motion examples |
| 47 | 2026-10-16 | ISSUE-130/134; FH-23 checkpoint 8 | Versioned extension-only v2, owned five-URL CRUD and shared 2D/3D controls | Native placement preservation, full recipe regeneration, exact source/session/policy, no-op and stale/failed UI guards | Backend matrix8.07s + focused3.00s; frontend327.34s + fixture1.25s | 0 | Closed contract/HTTP/permit/host cases and real client/dialog/menu tests | 346 distinct backend;9,208 distinct frontend/one existing skip after targeted mock fix; [U25 evidence](docs/audits/feature_history_20261014/validation_organized_extensions.json) | **No** — Archive unavailable; MV-48/MV-52/FH-27 remain | Legacy global reconciliation could rewrite placements; unchecked null replies lost edits/selection; omitted session scalar and no-op receipt confused ownership/success |
| 46 | 2026-10-16 | ISSUE-133; FH-23 checkpoint 6 | Numerical lease host, cancellable owned progress and status recovery; shared one-undo publication | Stale sequence, busy result retirement, timer failures, unknown Status and local timing regressions | Backend315 checks18.46s; native2 checks8.40/189.24s; frontend327.96s | 0 | Finite host lifecycle, real native host chains and frontend polling/dialog cases | 317 distinct backend; frontend9151 passes/one skip; [U23 evidence](docs/audits/feature_history_20261014/validation_transform_numerical_lifecycle.json) | **No** — Archive unavailable; MV-52/FH-27 remain | Phase transitions confused completed computation with editable ownership, transport refusal with publication outcome, and response processing with fresh lease time |
| 45 | 2026-10-16 | ISSUE-132; FH-23 checkpoint 5 | Shared supervisor retains admission through actual buffer cleanup; private numerical transform worker pair remains unwired | Repeated dead-child close/unlink failures, actual shared-memory cleanup, exact native source/draft binding and numerical replay | Shared442 checks20.27s; native4 checks200.23s; targeted final diagnostics191 checks7.23s | 0 | Two new worker/native dossiers; obsolete three-retry expectation replaced | 446 distinct focused passes; red failures and overlaps in [U22 evidence](docs/audits/feature_history_20261014/validation_transform_numerical_workers.json) | **No** — Archive unavailable; live numerical lifecycle/FH-27 remain open | Process death mistaken for resource release; source graph aliases could expand before output admission; both guarded |
| 44 | 2026-10-16 | ISSUE-109; FH-18 checkpoint 9 | Exact native Direction admission in bounded repair capture; named preview/repair integration remains gated | Native scoped-definition capture and arbitrary string-enum refusal; actual named repair jobs | Backend matrices 14.03/9.56 s plus corrected oracle 2.74 s; frontend 319.13 s | 0 | 124 cases across six new backend dossiers; native-wire and UI regressions | 967 distinct focused backend; full frontend 8,601 passes/one existing skip; [checkpoint record](docs/audits/feature_history_20261014/validation_named_deformation_lifecycle.json) | **No** — MV-48/FH-27; tiny timing probes do not qualify rollout | Exact-string copier omitted native enum; repaired publication facade rejected its valid permit; stale comparison oracle and missing editor guide wiring corrected |
| 43 | 2026-10-16 | ISSUE-99 continuation; FH-18 checkpoint 3 | Shared detached group admission, recorded component/pivot paths, stale pivot UI guards and scalar-work preflight | Native replay/undo/reload/seek, typed limits, source/session/policy races, preserved document fields and unfinished moves | Backend 10.61 s; frontend 316.97 s | 0 | 72 backend and 18 frontend cases | 389 focused backend; 8,564 frontend passed/one skip; [red/review evidence](docs/audits/feature_history_20261014/validation_group_auxiliary_recording.json) | **No** — MV-48/FH-27; no latency/broad-backend claim | Unlogged pivot, incomplete component rows, unowned publication, read-time inference and scalar geometry expansion; task growth flagged at 18/38 with fixed migration plan |
| 42 | 2026-10-16 | ISSUE-99 continuation; FH-18 checkpoint 1 | Shared owned group recorder, typed dependencies, ordinary client sync and candidate geometry response | Actual omitted/false flags, atomic refusal, undo/reload/cold proof, reversed replies, rootless response inference | Backend 13.51 s + 3.56 s; frontend 325.58 s | 0 | Three backend dossiers and 21 frontend cases; stale style/preview tests updated | 292 distinct backend; 8,517 frontend passed/one skip; red/review history in evidence | **No** — MV-48; no latency/broad-backend claim | Unlogged membership/style, unowned publication, standalone geometry race avoided, response inference republished a different candidate |
| 41 | 2026-10-16 | ISSUE-106 explicit live-part repair | Closed grouping upgrade, shared draft planner/capture, isolated evaluator and existing repair panel | Exact old-row/rebase receipts; native move/bend/twist rebuild; Apply/undo/redo/cold proof; cancellation and same-revision session ABA | Backend 30.84 s; full frontend 355.98 s | 0 | Five backend dossiers; 23 frontend cases; stale private oracle updated | 631 backend and 8,464 frontend passes/one skip; red/review failures retained | **No** — MV-48; invalid-file recovery and latency open | Typed overlay replacement missing; locked source discovery serialized cluster inputs; omitted action archive catalog; stale group labels |
| 40 | 2026-10-16 | ISSUE-106 prevention; explicit structural status | Grouping v2, bounded frame-reference check, final candidate/deletion guards and audited numerical schema transition | Legacy exact replay, new save/reload/cold proof, generated joins, empty selection, stale deletion, current/old/unknown pins in real workers | Focused 51.22 s; native compatibility 49.09 s | 0 | Seven focused dossiers; stale membership-index assumptions updated | 563 distinct backend passes; red/integration evidence retained | **No** — MV-48; repair and latency open | Namespaced UUID seed, generated first-group assumption, empty-group all-helices expansion, post-publication validation and source races |
| 39 | 2026-10-16 | ISSUE-105 authored group retargeting; gated ISSUE-100 editor | Native prefix selection helper, closed control validation, actual editor/popup adapter and private viewport | Group/plane reversals, exact unchanged inputs, failed Apply/status recovery, native display, owned guide cleanup and cold save/reload | Backend 14.87 s; full frontend 320.32 s | 0 | 18 retarget cases; complete checkpoint evidence linked below | 373 backend; full frontend 8,441 passed/one skip; review failures retained | **No** — MV-48, both rollout gates closed | ISSUE-106 source save defect reproduced; shared Sprite geometry preserved; pending callbacks and input reversals fixed |
| 38 | 2026-10-16 | ISSUE-104 — readable typed refusals | Two direct string checks in existing API error formatter | Actual native-reference shape plus precedence/fallback controls | Red 1.65 s; full frontend 345.21 s | 0 | 9 cases (22 total) | Red 6 failed/16 passed; full frontend 8,300 passed/1 skipped | **No** — MV-48 | Typed `detail`/`message` was serialized as raw JSON |
| 37 | 2026-10-16 | ISSUE-103 — automatic crossover ownership | Private full capture and guarded existing recorder adapter | Detached native input, real intervening nick, policy ABA, HC/SQ replay and rollback | Red 3.41 s; green 10.43 s | 0 | 12 cases | 117 related passes/1 existing skip; 72 overlap ISSUE-102 run | **No** — MV-48 | Prebuilt candidate discarded newer work; expensive native work stays outside lock, extra copy cost unqualified |
| 36 | 2026-10-16 | ISSUE-102 — atomic nick/resize references | Shared strict builders/reference guards in routing recorder | Failed later selection, exact stacks/markers and multi-helix partial response | Red 3.80 s; green 7.09 s | 0 | 17 cases (31 routing total) | 174 related passes | **No** — MV-48 | Live nick skipped invalid selections; resize lacked terminal guard; response scope read stale source |
| 35 | 2026-10-15 | ISSUE-101 — forced-ligation source ownership | New `part_routing_recording.py`, thin ordinary route | Deterministic intervening nick, lock ownership and protected-loadout refusal | Red 3.26 s; combined continuation run 5.23 s | 0 | 14 focused cases | Red 3 failed/11 passed; all 107 related cases green within combined run | **No** — MV-48; no broad/performance qualification | Prebuilt candidate discarded a later edit; shared native math and existing recording postprocessing retained |
| 34 | 2026-10-15 | ISSUE-99 — ordinary grouping inputs; G1 partial | New `part_group_recording.py`, thin cluster route, headless compatibility documentation | Default/false/true logging, group+move, routing chronology, independent replay, source/failure/lock guards | Focused 101 cases in 5.57 s; group rerun 16 in 2.88 s | 0 | New group dossier; obsolete unlogged expectations updated | 102 unique focused passes; overlapping runs retain 108/16 warnings respectively | **No** — MV-48; no broad/performance qualification | ISSUE-100 preview/Apply/Cancel defects separately reproduced; ten green deformation cases include characterization, not a fix |
| 33 | 2026-10-15 | ISSUE-84 — repair proposal roundtrip budget | Canonical persisted-form admission in `part_repair_draft.py` | Three red maximum-node/byte save/reload cases, plus one control | P5 continuation | 0 | 4 boundary cases | 69 focused schema/API/persistence cases pass | backend only | Raw sparse input fit while serialized optional defaults exceeded the same limit |
| 32 | 2026-10-14 | ISSUE-82 — producer/consumer regeneration, PARTIAL | Root-based recipe edit module, refreshed snapshots/diffs, revision/source guard | Native bundle→joint edit/delete and failure regressions | P3 continuation | 0 | 31 focused native/regeneration cases | compatibility regressions corrected; audit records checks | backend only | rootless recovery, sweep version parsing and persisted detachment |
| 31 | 2026-10-14 | ISSUE-81 — long pose history overhead | Type-gated Join/Pattern scans; skip no-op cluster copy | Existing 1,000-pose A/B gates and independent replay oracle | P2 prerequisite audit | 0 | existing behavioral suites retained | all 14 A/B gates pass | backend only | yes — missing-attribute lookups dominated nominally linear scans |
| 30 | 2026-10-13 | ISSUE-80 — assembly loading / Full GPU limits, PARTIAL | Compact/NDGB transport, readiness/source reuse, prepared CG primitives, semantic/lazy UI work and ordered saves | Exact seven-source parity, final 8,075 frontend/23 smoke, real-frame release benchmarks, frozen source/cleanup proof | completed implementation; limits retained | −2; thin wiring only | focused batches overlap; audit records counts | final frontend/smoke pass; backend retains identical baseline 22/4 failures, zero individual timing violations | Benchy 29.669 s import/33 ms Full; hinge 6.119 s/485 ms Full; load/GPU targets unmet | unique-source CPU, repeated-instance GPU, background readiness and screenshot timing are measured separately |
| 29 | 2026-10-11 | ISSUE-68 — shared headless/UI simulation ownership | `simulation_runtime.py` and seven native engine adapters | Separate-process native CanDo + HTTP poll/stop/resume/death; detached-worker and generation races | one headless parity follow-up | 0 | 25 lifecycle regressions | final 26 focused runtime/planning checks passed | native API and actual CanDo/SNUPI launches; readiness browser exercise also passed | yes — read-only legacy completed NAMD planning initially created a lock file; fixed and pinned |
| 28 | 2026-10-08 | ISSUE-66 — obsolete loop/skip marks survived recomputation | `crud.py` clears active marks inside the revision-checked commit; new sweep strain synthesis uses stored spline intent | HC/SQ API tests seed obsolete end marks, recompute twice, undo/redo and revert | one sweep follow-up | 0 | 14 backend + 1 browser for sweep support and regression | focused suites green; browser reload fixture corrected to use complete export | yes — real Add Loops/Skips menu, undo/redo, full export/reload, screenshot inspected | yes — clearing only the calculation copy left old marks in the committed design |
| 27 | 2026-10-08 | ISSUE-65 — native cluster history ownership | Optional creation snapshot and extracted replay helper; restore original v2 snapshot cluster baseline | Cluster replay regressions and all 98 saved-design history boundaries | focused generator refactor | 0 | 2 backend | boundary audit caught both ownership loss and missing original group | covered by generator app exercise | root cause: creation entries stored membership without parent/duplex ownership; restoring only generated groups also lost original snapshot membership |
| 26 | 2026-10-07 | ISSUE-61 — pending-review regression failed on WSL and opened a durable incident | One test in `test_native_placement_vr_failure.py` stubs `_native_platform_reason`; runtime checks and placement code unchanged | Existing pending-review regression failed before / passed after; 18 VR-failure assertions and four platform cases passed | short focused follow-up | 0 | 0; existing regression corrected | first focused assertion run passed; retained gate required separate review | n/a, test-only; explicit review audit clear after recorded acknowledgement | yes — platform rejection occurred before the review check; original report and review retained |
| 25 | 2026-08-10 | Alpine completion feedback — verified multi-GB downloads looked frozen/failed during synchronous health and metrics extraction | `md_executor.py`: persist `download_status.state=processing` around final bookkeeping, then restore `verified`; `routes_md.py`: offline verification preserves the active phase; `simulate_jobs.js`: explicit processing message, striped 100% bar and locked **Processing…** action | Backend reconciliation test reloads the persisted job from inside final bookkeeping; frontend unified-card test asserts message + disabled action | ~1 short session after live diagnosis | **0** | 1 backend + 1 frontend | one Python local-import scoping failure caught by focused test, fixed by using the existing module import | live root cause observed on Alpine job `029a76c6a59f`; UI behavior test-pinned | yes — byte verification completed correctly, but the old synthetic `running`/retry message remained throughout a CPU-bound DCD pass and made successful work look stalled |
| 23 | 2026-08-09 | P1 Alpine lifecycle hardening — truthful minimisation progress; safe resumable result download; offline verification; completed partial-production accounting; unified job-directory moves | `md_executor.py` + `cluster_ssh.py`: node metrics, measured minimisation rate, per-job async+filesystem transfer locks, exact persisted inventories, offline verification and `.part` promotion, filesystem errors no longer expire SSH; `routes_md.py`: verified download lifecycle, local/remote size authority, actual completed steps/ns from XST; `simulate_jobs.js` + `md_jobs_panel.js`: transfer status/bytes, minimisation counter+ETA, SLURM allocation time, actual production ns and green completion check; shared archive UI renamed to directory moves | Backend executor/SSH/offline-verification/size/progress suites; frontend unified-card/timeline suites; live Playwright against real P1 `24hb_0xT` card | ~1 long live-debug session | **0** | 20+ focused cases added/strengthened | duplicate SFTP append → offline-verifier rename race → filesystem-error session expiry, each reproduced and closed | **yes** — real Alpine SLURM 30958617: 104.7 GB inventory downloaded and verified; card shows 65.97 ns actually complete + green ✓ | **yes — multiple coupled races:** automatic+manual fetches could append the same `.part`; then the first offline verifier could steal an exact-size active `.part`; generic SFTP error handling expired a healthy Duo session for local ENOENT |
| 24 | 2026-08-09 | Direct triage — unsequenced NAMD Create looked inert; bead↔slab connector colors diverged from sidebar and flex-map colors | `routes_md.py`/`md_job.py`/`md_sequence_guard.py`: Create records an awaiting-sequence draft, Run rejects incomplete scaffold or staple sequence, sequence-change prepares in place before execution so exact PSF atom count feeds projections; `md_jobs_panel.js`: explicit create/run notices and automatic deferred preparation; `helix_renderer.js`: connector color follows the slab through shared recolor, scalar-map apply/clear, and geometry refresh | Backend create→Run rejection + post-assignment in-place/autostart assertions; frontend run-control case; renderer cross-path parity assertions; focused visualization suites | ~1 session | **0** | 2 backend behavior cases + 4 frontend parity/control cases | clean | user confirmed original diagnosis; final live gesture still recommended | yes — geometry refresh explicitly reset connectors to `defaultColor`, and scalar dirty propagation omitted the connector mesh |
| 22 | 2026-08-09 | Direct triage — welcome library took ~4.22 s before showing files in a 75 GB workspace | `routes_assembly_workspace.py`: pruned metadata walk, once-per-process background identity audit with atomic writes, split `/library/disk-usage`; `ui/library_panel.js`: immediate localStorage paint, quiet generation-guarded refresh, asynchronous size merge; `api/client.js`: enrichment endpoint | Backend identity/disk/pruning tests + new `library_panel.test.js` cache/merge cases; benchmark on the real workspace | ~1 session | **0** | 3 backend cases changed/added + 4 frontend | one background-write race caught and fixed with atomic replacement | benchmark: metadata path ~22 ms; full frontend suite green | yes — moving identity migration off-response made direct writes observable concurrently; atomic `os.replace` closed that race |
| 21 | 2026-08-08 | ISSUE-22 audit + identity hardening — roll/return API-green; fixed missing Return action and cross-file history aliasing | `ui/toast.js` replaces reused actions; new `core/design_identity.py` gives moves stable identity and copies/Save-As fresh UUIDs; workspace routes sign/migrate old files + remap all job provenance; cross-design roll uses the snapshot's own log | Red Vitest action repro; lifecycle oracle; 10 new identity core/API cases including legacy duplicate split, move/copy/Save-As, job remap, and cross-design log isolation | ~2 sessions | **0** | 11 new + 2 strengthened | focused suites green | **USER TODO** — live roll/follow/return plus one Save-As/move/copy pass | yes — the ledger missed an existing lifecycle oracle; audit also found `Design.id` existed but simulation ownership remained path-centric |
| 20 | 2026-07-24 | ISSUE-16 — nondeterministic CanDo/SNUPI RMSF (recognized as already fixed during the 2026-08-08 ledger audit) | `backend/physics/fem_solver.py`: all relevant `eigsh()` calls pass deterministic `v0=_eigsh_v0(...)`; introduced by `b02e954` | Existing salt-invariance and RMSF tests; audit reran `test_g12_salt_ignored_by_cando` + `test_rmsf_is_finite_nonnegative_and_per_node` | historical / incidental | 0 | 0 | 2 focused tests passed 2026-08-08 | n/a (numerical backend) | n/a |
| 19 | 2026-07-13 | ISSUE-9 (single phase) — autoscaffold not idempotent: every re-route ratcheted the helices further out and stacked crossovers, persisted to `.nadoc`. **Not teeth-specific** (the dossier implied it was): a plain 4HB bundle went `168→189→199→210` bp and `6→9→12` xovers over 3 routes, on BOTH routers | new `backend/core/scaffold_reset.py` (`reset_scaffold_to_structure` + `structural_intervals` + `is_route_crossover`); wired into `seamed_router.auto_scaffold_seamed` / `auto_scaffold_matched` and `seamless_router.auto_scaffold_seamless` (new `reset=` kwarg; `section_router` passes `reset=False` — it calls the seamless router on a seed it is mid-way through building, after the top-level reset already ran). **The routing algorithm is untouched — only its INPUT is normalised.** Oracle (user's rule, then verified): autoscaffold never touches STAPLES, so a helix's true extent is its staple span; in the real teeth/dumbbell fixtures the staple intervals *are* the scaffold sections, gaps and all | `tests/test_scaffold_idempotence.py` ×12 — **8 verified can-go-red** against the pre-fix source (temporary env kill-switch on the reset, then removed): plain-bundle idempotence (seamed + seamless), teeth + dumbbell idempotence, helices-don't-grow, crossovers-don't-accumulate, `reset(route(fresh)) == fresh`, forced-ligation bail-out. The other 4 are guards (no-op on fresh, staples untouched, single-strand, don't-grow-a-short-scaffold) | ~1 session | **0** (backend-only) | 12 new | clean (routers 76/76; `just test-smart` = **FULL**, 4901 passed — 1 unrelated flake, `test_snupi_element::test_g12_salt_ignored_by_cando`, green alone + whole file 28/28, no import path from SNUPI to the routers); ruff clean on all touched files | **USER TODO — eyeball owed.** Backend-only + fully unit-pinned, but this rewrites helix geometry on a real design; run Auto-scaffold twice on a teeth design and confirm the faces do not move | **yes — a second, independent bug**: the seamed router stamps 3 `process_id`s (`auto_scaffold_seamed:seam`, bare `create_near_ends`, `create_far_ends`) but `_clear_auto_scaffold_route_for_seamed` matched only the `auto_scaffold_` prefix → the end-turn crossovers survived every "clear", so that helper (used by `auto_scaffold_matched`) had never worked |
| 18 | 2026-07-13 | ISSUE-14 (single phase) — `assembly_exit_cleanup` red-gating `just smoke`. **The recorded diagnosis was wrong**: there was no console error and no app bug. The spec died in the shared e2e harness during *setup*, so the assertion it was blamed for never ran | `frontend/e2e/helpers/scene_harness.js` (`loadScaffoldedPart`, shared by **9 specs**): (a) `waitForTimeout(500)` raced File→New's backend POST — the welcome screen hides when the *page* has a design, but on a cold backend the POST lands later, so `page.request` got **404 "No active design."** → replaced with `expect.poll` on `GET /design`==200; (b) removed the dead `POST /design/auto-scaffold` (**405** since `e9d6750`, 2026-06-08 consolidated it into `-seamed`/`-seamless`) and promoted its `scaffold-domain-paint` fallback — the path that was actually running — to primary. Plus `scripts/sim_guard.py` + `justfile` (smoke refuses under a live sim) | the spec itself IS the repro: red → green. Root cause pinned by an instrumented probe spec printing each API call's status (`helix-at-cell` 404 → 201 once the design landed; `auto-scaffold` 405) — guessing from the spec name would have sent the fix into the teardown code, which was never broken | ~½ session | **0** (no product code touched) | 0 new (the 9 existing specs sharing the harness are the pin) | clean (`assembly_exit_cleanup` green standalone + in-suite; backend 4720 passed; ruff clean on new file — repo-wide lint debt pre-existing) | n/a (test-harness + gate only; no user-facing surface) | **yes — a second bug**: with the harness fixed, heavy specs still timed out under a live NAMD job (~5.5/12 cores, load ~10) and the failure *moved between specs* run-to-run. Now guarded, fails loud, `NADOC_IGNORE_SIM_GUARD=1` to override |
| 15 | 2026-07-08 | ISSUE-15 (single phase) — a SLURM-COMPLETED remote MD job whose checkpoint restart set (`.coor/.vel/.xsc`) failed to download was falsely marked `completed` (left the poll set → files never re-fetched → downstream chain-seed 400s) | `backend/core/md_executor.py` (new `_completion_checkpoint_present` predicate + `_MAX_FETCH_ATTEMPTS=3`; `reconcile_remote_job` keeps a missing-checkpoint completion **re-pollable** — `status=running` — for bounded retries, then `failed`/`fetch_incomplete`), `backend/core/md_job.py` (+`fetch_attempts` counter + load default) | `tests/test_md_executor.py::test_reconcile_completed_missing_checkpoint_{stays_repollable,fails_after_retries}` — both **can-go-red** vs old source (stash-rerun verified); 2 under-specified existing completed-path tests made realistic (staged restart files) | ~½ session | **0** (backend-only) | 2 new + 2 fixtures | clean (file 49/49 green; ruff clean on touched files — repo-wide lint debt pre-existing, untouched) | n/a (remote-SLURM path; a dropped Alpine fetch isn't reproducible offline — standing eyeball folds into cluster-submission live-validation) | n/a |
| 1 | 2026-06-05 | ISSUE-3 (single phase) — Ctrl+click multi-select feedback + toggle semantics | `scene/assembly_lasso.js` (new pure `toggleInstanceSelection`), `scene/assembly_multi_box.js` (white-for-1 / purple-for-2+, relaxed ≥2 gate), main.js `onClick` re-wired to the helper | vitest (`toggleInstanceSelection` ×6, `assembly_multi_box` color cases) + e2e `assembly_select.spec.js` ISSUE-3b (real raycast, discriminating) | ~1 session | **+1** (dev-only `getMultiSelectedInstanceIds` oracle; onClick body net 0) | 6 unit + 1 e2e (+2 updated multi-box tests, +1 e2e helper) | clean (vitest 906 green first pass; e2e 3a/3c reframed once after discovering empty-centers fixture + gizmo occlusion) | yes — real `Belt_test1.nass` on shared renderer: white box (1 part) → purple (2 parts), `getInstanceCenters`=62 | n/a (no prior phase) |
| 2 | 2026-06-05 | ISSUE-2 (Phase 1 repro+ask + propagation fix) — different-doc same-file tabs didn't cross-sync | `app/lifecycle.js` (new `registerSiblingSave(path, sameDoc)` — doc-scoped echo guard), main.js `file-saved` handler re-wired to it | vitest `app/lifecycle.test.js` ×3 (same-doc suppresses; **different-doc reloads = repro**; 5 s clear) + USER TODO two-real-tab app check | ~1 session | **−4** (9-line inline echo block → 1 call) | 3 unit | clean (vitest 909 green first pass; smoke 23/23) | **USER TODO** — two-real-tab gesture (BroadcastChannel can't cross Playwright contexts; see difficulties) | n/a |
| 3 | 2026-06-05 | ISSUE-2 sub-phase C — sync console logging silent by default | `ui/sync_badge.js` (`syncLog` console mirror gated on new `debugLogging` flag; show/hide/toggle/close drive the flag in lockstep with panel `.visible`) | vitest `ui/sync_badge.test.js` ×5 (silent default = repro; records row while silent; mirrors when panel shown; silent on hide; silent on close button) + 3 existing console-assertions updated to open panel first | ~1 session (cheap) | **0** (fix entirely in extracted module; no main.js touch) | 5 unit (net +5: 909→914) | clean (vitest 914 green first pass; smoke 23/23) | yes — live `Belt`-less boot: `__nadocSyncDebug.forceResync()` emitted 0 `[SYNC]` lines with panel closed, 2 with `.show()` open | n/a |
| 5 | 2026-06-05 | ISSUE-1 Phase 1 — context-menu inventory + target spec (NO code; survey + AskUserQuestion) | none (doc-only): `issues_ledger.md` ISSUE-1 dossier (inventory table of 18 builders + banked spec + refined phase plan) | inventory table IS the repro (survey bug, not a single gesture) — no automated test this phase | ~½ session (cheap) | **0** (no code) | 0 | n/a | n/a (no code to validate) | n/a |
| 4 | 2026-06-05 | ISSUE-2 sub-phase B — "saved" badge co-editing (stale-sibling) indicator; closes ISSUE-2 | `ui/sync_badge.js` (compose base status + sibling count via `_render`; new `setSiblingCoediting` + pure `countCoeditingSiblings`), `index.html` (`.sync-dot.coedit` blue), main.js (doc-presence carries `workspacePath`+`docId`; `_refreshCoediting`; `doc-goodbye` emit/handler; `_setWorkspacePath` re-announces) | vitest `ui/sync_badge.test.js` ×13 (7 badge-render incl. green-only annotation/plural/revert = the fix; 6 detector incl. same-docId-excluded) | ~1 session | **+22** (thin wiring across existing doc-presence / beforeunload / setter blocks — not a new cohesive block; cohesive logic lives in `sync_badge.js`) | 13 unit (net +13: 914→927) | clean (vitest 927 green first pass; smoke 23/23) | **USER TODO** — two-real-tab gesture (BroadcastChannel can't cross Playwright contexts; same constraint as row 2) | n/a |
| 6 | 2026-06-05 | ISSUE-1 Phase 2a-binding — overhang-binding menu migrated onto the shared `createContextMenu` primitive (pure consolidation, no behavior change) | new `ui/overhang_binding_menu.js` (factory `initOverhangBindingMenu`), `ui/primitives/context_menu.js` (+reusable `danger` item flag), `styles/components.css` (+`.context-menu__item--danger`), main.js (inline `_showBindingCtx`/`_hideBindingCtx` block → 1 factory-init line) | vitest `ui/overhang_binding_menu.test.js` ×9 (renders header+Bind+Delete via `.context-menu` markup, Unbind-when-bound, danger class, unknown-id→nothing, Bind/Delete api-wiring, confirm-gated delete, hide/no-stack, auto-dismiss-on-click) | ~½ session (cheap) | **−81** (83-line inline block → 1 factory-init line; +1 import) | 9 unit (net +9: 927→936) | clean (vitest 936 green first pass; smoke 23/23) | **USER TODO** (boot/wiring exercised by smoke console-error gate; live right-click-on-binding-line not drivable — no fixture has non-empty `overhang_bindings`) | n/a |
| 8 | 2026-06-05 | ISSUE-4 Phase 1 — drill-selection current-state map + target interaction spec (NO code; survey + AskUserQuestion) | none (doc-only): `issues_ledger.md` ISSUE-4 dossier (3-mechanism current-state map + friction catalogue + banked target spec A–G + target state-machine diagram). Verified by code read that the drill is **design-editor only** (`assembly_pointer.js`/`assembly_lasso.js` have zero drill) | narrated USER TODO walkthrough = the repro (survey UX issue, not a single gesture) — no automated test this phase | ~½ session (cheap) | **0** (no code) | 0 | n/a | n/a (no code to validate) | n/a |
| 10 | 2026-06-16 | ISSUE-10 (single phase) — dead MD-load REST routes deleted | `backend/api/routes_md.py` (removed `md_resolve_config` + `md_load` handlers + their `MdResolveConfigRequest`/`MdLoadRequest` models; kept live `/md/browse`) | whole-repo `grep -rn` proved zero frontend/test caller; live load path is the `/ws/md-run` WebSocket (`ws.py`) → both REST twins unreachable | ~½ session (cheap; rode on the #42 carve-up) | **0** (backend-only) | 0 (deletion of dead code — `just test` 2130 passed / 0 failed unchanged is the pin) | clean (ruff clean; 2130/55 unchanged) | n/a (dead code — nothing invokes them, so no gesture to validate) | n/a |
| 7 | 2026-06-05 | ISSUE-1 Phase 2a-orientation — overhang-orientation menu migrated onto the shared `createContextMenu` primitive (pure consolidation, no behavior change) | new `ui/overhang_orientation_menu.js` (factory `initOverhangOrientationMenu`), `ui/primitives/context_menu.js` (+reusable `{ type:'custom', el }` HTMLElement passthrough — for the rep hover-flyout the flat-item model can't express), main.js (inline `_showOverhangOrientMenu`/`_dismissOvhgMenu`/`_ovhgCtxMenu` block → 1 factory-init line, `_orientPanel` passed via lazy getter) | vitest `ui/overhang_orientation_menu.test.js` ×12 (item set + ordering, single-vs-multi gating of Set Label/Generate, Clear-All danger class, Edit/Reset/Generate/Open-Manager/Clear api-wiring, Set-Label prompt + cancel, hide/no-stack) + `ui/primitives/context_menu.test.js` ×4 (custom-item append, no-el tolerance, no-dismiss-on-inside-click, dismiss-on-outside-click) | ~½ session (cheap) | **−83** (92-line inline block → 9-line factory-init; +1 import) | 16 unit (net +16: 941→957) | clean (vitest 957 green first pass; smoke 23/23) | **USER TODO** (boot/wiring exercised by smoke console-error gate; live right-click-on-rendered-overhang WebGL raycast gesture not drivable here) | n/a |
| 11 | 2026-06-05 | ISSUE-4 Phase 3-xover — crossover arcs hoverable (red preview) + clickable (select crossover, green) in drill-v2; the thin inter-helix arc was never in the bead/cone pick set | `scene/selection_level.js` (`hoverPreviewTarget` +'arc' kind); `scene/selection_manager.js` (`_findStrandArcAt` proximity over the selected strand's arcs; `_updateHoverPreview` arc fallback; `_v2HandleArc`+`_selectCrossoverV2` strand-first→crossover w/ toggle; plain-click routes arc→`_v2HandleArc` when drillV2; `_arcHitPx` 12→18) — **follow-up: arc hover preview is a red glow TUBE along the polyline (`design_renderer.setPreviewArc`/`clearPreviewArc`, TubeGeometry r=0.3nm), not a midpoint sphere (user request)** | vitest `selection_level.test.js` arc cases (hoverPreviewTarget gate: same-strand arc→target, off-strand→null) + bead/cone drill e2e unregressed | ~1 session | **0** (no main.js touch) | 1 unit (net +1: 987→988) | clean (vitest 988 first pass; smoke 23/23; drill e2e 2/2) | **partial — USER TODO**: arc hover-red + click-green needs a multi-helix design (harness fixture is single-helix → no crossovers; thin-line gesture + Tier-3 colour not automatable) | n/a |
| 10 | 2026-06-05 | ISSUE-4 Phase 3-preview — red hover-preview glow on the would-be-selected leaf (replacing Phase 2's un-eyeballed scale-pop; "breadcrumb" was a naming mismatch, user wanted this glow) | NEW pure `hoverPreviewTarget` in `scene/selection_level.js` (gate: default+strand+same-strand → bead/cone target); `scene/glow_layer.js` (+`name` tag + `count()`); `scene/design_renderer.js` (red `_previewGlowLayer` + `setPreviewGlow`/`clearPreviewGlow`, cleared on rebuild + refreshed); `scene/selection_manager.js` (`_updateHoverPreview`/`_clearHoverPreview` scale-pop → red glow; `_restoreStrand` clears it) | vitest `selection_level.test.js` ×7 (`hoverPreviewTarget` gating) + e2e `drill_v2_select.spec.js` new test (real raycast: select strand → hover → named `previewGlow` layer count 0 → >0, discriminates glow from the old scale-pop) | ~1 session | **0** (no main.js touch; e2e reaches the count via `__nadocTest.scene` traverse for the named mesh) | 7 unit + 1 e2e (net +7: 980→987) | clean (vitest 987 green first pass; smoke 23/23; both drill e2e green) | **partial — behavioral pin app-verified by e2e** (real scaffolded part, hover pops preview glow); the RED-over-GREEN *colour* is a Tier-3 golden-image check → **USER TODO** below | n/a |
| 17 | 2026-06-06 | ISSUE-4 legacy-deletion — physically deleted the auto-drill ladder / manual filter pins / Tab drill-lock + the `NADOC_DRILL_V2` flag plumbing; selection-level is now the ONLY model, no opt-out (user chose "drop the opt-out entirely", gated on a confirmed multi-helix v2 eyeball — both AskUserQuestion'd) | `scene/selection_level.js` (removed `isDrillV2`; `lassoCaptureType`/`hoverPreviewTarget` v2-only), `scene/selection_manager.js` (3853→3477; removed `_autoDrill*`/`_drillLock`/`_drillSeq`/`_drillLevel`/`_drillAnchor`/`_currentDrillType`/`_handleCtrlTypeLockClick` + `setDrillLock`/`getDrillLock`/`resetDrill`/`isDrillV2` exports + the `_drillV2` gates; KEPT `_drillClusterId` — shared with v2 cluster menu), `ui/selection_filter.js` (133→? removed `_manualFilters`/`isManualSelect`/`reflectLockOnButtons`/`resetToAutoBaseline`; visibility gates now plain-toggle), `ui/keyboard_shortcuts.js` (removed `_TAB_LOCKS`/legacy Tab+Escape branches + 3 deps), `main.js` (−5 wiring), `index.html` (−`.sf-pinned` CSS) | vitest (legacy-path tests deleted WITH the code: 4 legacy lasso + 3 isDrillV2 + 1 hover-flag in `selection_level.test.js`, ~10 legacy factory in `selection_filter.test.js`, 2 legacy Tab + 1 Escape sub-case in `keyboard_shortcuts.test.js`) + drill-v2 + bead_select e2e regression (no behavior change) | ~1 session | **−5** | net −16 (1000→984; legacy tests removed) | clean (vitest 984 first pass; smoke 23/23; drill-v2 3/3 + bead_select 2/2) | yes — drill-v2 e2e re-run WITHOUT the now-defunct `?drillv2=1` param (v2 is default), all green; user pre-confirmed the multi-helix v2 eyeball | n/a (pure cleanup; ~715 net lines removed) |
| 16 | 2026-06-06 | ISSUE-4 (C follow-up) — drill-v2 engaged level PERSISTS across an empty-space/toggle-off click (the lit filter button stayed lit until Tab/re-click) | `scene/selection_manager.js` (`_clearAll` emits the persisted `_selLevel` in v2, not `null`; `_selLevel` was never reset there); `main.js` (+2 dev-only `__nadocTest.getSelectionLevel` oracle) | e2e `drill_v2_select.spec.js` (engage cluster → empty-canvas click → level + lit `clust` button persist; the button `.active` assertion is the discriminator) | ~¼ session | **+2** (dev-only test oracle in main.js; fix itself in the module) | +1 e2e | clean (vitest 1000; smoke 23/23; drill-v2 e2e 3/3) | yes — e2e real empty-space click on a scaffolded part | n/a |
| 15 | 2026-06-06 | ISSUE-4 Phase 3-filterrow (C) — drill-v2 is now the DEFAULT; filter-row gutted to one rule (no button = drill ladder, button = fixed level); `strand` is a distinct fixed level; Tab cycle cluster→strand→domain→end→xover→none; red `sf-pinned` box removed from v2 row. Legacy 87 sites kept (dead) — physical deletion deferred (user choice) | `scene/selection_level.js` (LEVELS +strand, TAB_CYCLE rewrite, BTN_LEVEL/LEVEL_BTN remap, `isDrillV2` default ON, `lassoCaptureType` strand→strands); `scene/selection_manager.js` (`_v2Handle{Bead,Cone,Arc}` strand branches); `ui/selection_filter.js` (v2 paint drops sf-pinned, default=no button); `ui/keyboard_shortcuts.js` (Tab toast for none) | vitest: `selection_level.test.js` (LEVELS/TAB/flag/lasso-strand rewrites), `selection_filter.test.js` (v2 paint no-sf-pinned + strand-level + legacy tests pinned `drillV2:false`), `keyboard_shortcuts.test.js` (v2 cycle + legacy `drillV2:false`) | ~1 session (cont.) | **0** | net +2 unit (998→1000) | clean (vitest 1000; smoke 23/23 now boots v2 by default; drill-v2 + bead_select e2e green) | **partial** — flag-flip + boot/render/teardown e2e-validated; the NEW behaviors (strand level, Tab cycle, no-red-box) multi-helix eyeball = USER TODO | n/a |
| 14 | 2026-06-06 | ISSUE-4 (B) — unify crossover SELECTION highlight to a green glow tube (was endpoint spheres, now a tube along the arc like the red preview tube) | `scene/design_renderer.js` (new `setSelectionArc`/`clearSelectionArc` green TubeGeometry; hidden on rebuild; removed dead `getCrossoverGlowEntries`); `scene/selection_manager.js` (`_selectCrossoverV2` + legacy arc path draw the tube; `_restoreStrand` clears it) | not unit-pinnable (Tier-3 rendering; single-helix e2e fixture has no crossovers) — smoke + drill-v2 e2e regression | ~⅓ session | **0** | 0 (rendering) | clean (vitest 998; smoke 23/23; drill-v2 e2e 2/2) | **USER TODO** — green tube over a real crossover needs a multi-helix design (same constraint as Phase 3-xover red tube) | n/a |
| 13 | 2026-06-06 | ISSUE-4 (A) — drill-v2 default 2nd-click on a bead KEEPS the leaf selected (was toggle-clear) | `scene/selection_manager.js` (`_v2HandleBead` default branch: removed the same-leaf clear + dead `_sameBead`) | e2e `drill_v2_select.spec.js` (3rd click now asserts the nucleotide STAYS selected; was "clears") | ~¼ session | **0** | 0 unit (e2e assertion flipped) | clean (drill-v2 e2e 2/2) | yes — e2e real-raycast on a scaffolded part | n/a |
| 12 | 2026-06-06 | ISSUE-4 Phase 3-filter-audit (lasso) — drill-v2 lasso respects the engaged `_selLevel` (Tab→ends, lasso grabbed clusters; now captures the level's element). Per-mechanism keep/clean/delete ask resolved; flip-flag + delete-legacy #4/#5/#6 DEFERRED pending v2 eyeball (user choice) | new pure `lassoCaptureType({drillV2,selLevel,drillType,selectableTypes})` in `scene/selection_level.js` (v2: level is the single truth, end→termini only, overhangs/loops/skips not capturable; legacy branch byte-for-byte); `scene/selection_manager.js` `_finalizeLasso` derives all 9 capture flags from it | vitest `selection_level.test.js` ×11 (5 legacy + 6 v2; the 5 v2 cases FAILED against the level-blind kernel = the repro) | ~1 session | **0** (fix entirely in extracted modules; no main.js touch) | 11 unit (net +11: 988→998 incl. drift; lasso file +5 over prior) | clean (vitest 998 green; smoke 23/23; drill-v2 e2e 2/2 unregressed) | **partial — UNIT-pinned**; the multi-element lasso gesture isn't drivable on the single-helix harness fixture (banked gotcha), so kernel is unit-pinned + app-eyeball is a USER TODO in the handoff | n/a |
| 9 | 2026-06-05 | ISSUE-4 Phase 2 (full) — unified `selectionLevel` state machine (default strand→leaf click, filter-row level selector, Tab cycle, Esc→default, hover preview, rep caveat) behind the `NADOC_DRILL_V2` flag | NEW pure `scene/selection_level.js` (model + flag); `scene/selection_manager.js` (`_v2HandleBead`/`_v2HandleCone` gate ahead of legacy `_autoDrill*`, reusable `_select*V2` primitives, hover preview on pointermove, `setSelectionLevel`/`getSelectionLevel`/`isDrillV2` API); `ui/selection_filter.js` (level buttons → `setSelectionLevel`; `reflectDrillLevel` v2 paint); `ui/keyboard_shortcuts.js` (Tab→`nextTabLevel`, Esc→default) | vitest: `selection_level.test.js` ×14 + `selection_filter.test.js` ×6 + `keyboard_shortcuts.test.js` ×4 + e2e `drill_v2_select.spec.js` (real-raycast strand→nucleotide→clear, discriminating vs legacy) | ~1 session (user opted "Full Phase 2 now" over a cheap slice) | **0** (legacy paths untouched; v2 added flag-gated; main.js not edited) | 24 unit + 1 e2e (net +24: 957→980 full suite count incl. drift) | clean (vitest 980 green first pass; smoke 23/23; e2e v2 green) | **yes** — `e2e/drill_v2_select.spec.js` boots `?drillv2=1` on a real scaffolded part, real-raycast 1st→strand / 2nd→nucleotide / 3rd→clear. Hover-preview pop + filter-row paint NOT eyeballed (cosmetic; carry to Phase 3) | n/a |

| 18 | 2026-06-06 | ISSUE-5 (single phase) — selecting an imported protein threw in the properties panel; **pushed in from the carve-up loop** (found while extracting `scene/protein_subsystem.js` #85, fixed same session) | `ui/properties_panel.js` (new `_renderProtein` — asset name/source, free/overhang/assembly anchor, atom/residue/chain counts, conj atom, handle, hidden flag; + `protein` dispatch branch; graceful fallback when attachment absent) | vitest `ui/properties_panel.test.js` ×5 (first test for the file; no-throw regression + free/overhang anchors + missing-attachment fallback + hidden flag) + live select-protein exercise | ~¼ session (cheap; adjacent to #85) | **0** (fix entirely in the extracted panel module; no main.js touch) | 5 unit (1037→1042) | clean (vitest 1042 green first pass; smoke 23/23) | yes — live `import mini_protein.pdb → select → panel renders __e2e__mini`, zero console errors | n/a — pre-existing (byte-identical on master), surfaced by the #85 live exercise. Overhang/assembly anchor branches unit-only → `MV-15` validation debt |

| 19 | 2026-06-08 | ISSUE-6 (single phase) — `test_teeth_closing_zig` hash-seed-flaky (≈30% pass); **backend**, the standing `KNOWN_FLAKES` entry. Misdiagnosed in the ledger as a cross-test state leak | `backend/core/seamed_router.py` (`_hamiltonian_path`: `(len(adj[n]), n)` lexicographic tiebreaker on BOTH the starter sort + neighbor key — was degree-only → hash-order-dependent path); `tests/test_seamless_router.py` (`test_teeth_closing_zig` re-pinned to the closing-zig crossover event + `bridge_xovers==6`, dropping the brittle `len(scaf_strands)==4`) | **pytest** — `PYTHONHASHSEED` sweep (13 seeds) is the repro: pre-fix nondeterministic, post-fix 100% green; full `just test` 2× green | ~½ session | **n/a** (backend; no main.js) | 0 added (1 rewritten) | clean (full suite 1753 passed / 0 failed, was 1752/1; 13-seed sweep green ×2) | n/a (backend test fix; no app surface) — confirmed the closing-zig event fires in BOTH the 4- and 5-piece orderings, so the count was never measuring the intent | n/a |
| 20 | 2026-06-08 | ISSUE-7 (single phase) — negative-bp scaffold segments undeletable in the 2D editor ("nothing happens" on Delete). **Direct triage**; multi-factor (parse + visibility) | NEW `cadnano-editor/element_keys.js` (single source of truth: 5 builders + 5 negative-safe `-?\d+` parsers); `cadnano-editor/main.js` (5 broken `\d+` parse sites in the delete path + extra-bases menu → module parsers; xover-key build → `xoverKey`); `cadnano-editor/pathview.js` (builders aliased to module, 2 parse sites → module; **+`_fitToContent` panX offset** so negative-bp cells aren't drawn off the left edge) | vitest `cadnano-editor/element_keys.test.js` ×19 (exact teeth stub keys + build↔parse round-trips for negative/zero-crossing/positive; old `\d+` proven red via standalone Node eval) + throwaway gesture e2e (real select→Delete on teeth removes the stub; removed after verify) | ~1 session | **0** (the 3D `main.js` is untouched; the cadnano-editor `main.js` is a separate file, net −1) | 19 unit (1133 total) | clean (vitest 1133 green; smoke 23/23; real-gesture e2e green) | yes — temp e2e drove the REAL select-tool→Delete path on `teeth.nadoc`: stub deleted (factor 1) + bp −17 on-screen after fit (factor 2) | **n/a — caught the incomplete first pass myself**: the `_fitToContent` visibility fix shipped first did NOT fix Delete (parse was the real defeater); user reopened with "still can't delete," which surfaced factor 1. See root-cause log |

**Column notes:**
- **Repro pinned by** — the failing-then-passing test that defines "fixed": `vitest` / `e2e (scene_harness)` /
  `USER TODO` (un-automatable, user-confirmed — log it explicitly, like the carve-up's accepted caveats).
- **main.js LOC Δ** — should be **≤ 0**. A positive delta means the fix grew the closure; justify it
  (rare: a one-line wiring tweak) or refactor. Prefer routing the fix through an extracted module.
- **app-validated** — minutes of manual app exercise, or "USER TODO" if handed to the user.

## Root-cause log (DoD field — fill one row per fixed bug)

Every fix records **why the bug existed** and, if you chased a wrong fix first, **the failed hypothesis**.
This is a DoD line in `issues_ledger.md`, not optional — it's the cheapest defense against shallow fixes
(which show up later as reopens) and it feeds `memory/LESSONS.md` *systematically* instead of ad hoc.
Use one 5-Whys chain, but distrust a single causal thread — three-layer/topology bugs are usually
multi-factor (CLAUDE.md's own warning). If the bug is a *class*, add a `LESSONS.md` entry and link it here.

| Issue | Root cause (5-Whys, one line) | Failed hypothesis (the "obvious fix" that was wrong, if any) | → LESSONS.md |
|-------|-------------------------------|-------------------------------------------------------------|--------------|
| ISSUE-177 | Domain text / backbone mesh inventories omit junction-owned residues → forced-ligation sequences, default picks and live references diverged → share exact path ownership and retain simulation-index keys. | Projected bead centers can be occluded; the browser fixture now verifies the exposed rendered target before clicking. | [F8](memory/LESSONS_archive.md#f8) |
| ISSUE-162 | Full treated anchor-outward extension indices as helix-axis bp indices → helix polarity selected the wrong chemical traversal → the host attached to the far tip. Use extension terminal-domain ordering for both cones and attachment arcs. | No alternative molecular-placement fix was tried; initial fixture identity/disposal errors were corrected before the genuine red regression. | `helix_renderer.extensions.test.js`; all12 roots checked in the isolated app |
| ISSUE-160 | Generic allocation and a self-referencing recursive closure retained copied graphs until collection; repeated header factory introspection then consumed the remaining capture deadline. Empty destinations, exact fixed-shape copying, acyclic recursion and equivalent fresh header defaults remove that work without changing authority or budgets. | General leaf seeding and prefilled dictionaries added overhead. Crossover profiling and a failing weak-reference lifetime regression identified the narrower fixes. | `test_part_model_copy.py`, capture admission/copy regressions; qualification in feature-history handoff |
| ISSUE-159 | Rebuild starts at the recipe root → host save identity was absent; asynchronous autosave also replaced the captured frontend object → valid private jobs became stale or saved under a new path. Preserve host identity and coordinate saves with revision-bound asset publication. | Ignoring object identity alone did not prevent in-flight save acknowledgements or preserve the publication's original path. Both boundaries needed correction. | `asset_operation_requests.test.js`, `asset_save_coordination.test.js`, `test_part_asset_routes.py` and the asset browser flow |
| ISSUE-133 | Long computation introduced new phase boundaries → callbacks, busy admission and post-publication timer errors could retire the wrong state; Status transport failure was treated as direct Apply refusal. Bind sequence/deadline, preserve authoritative receipts and require validated terminal outcome before retry. | Global timer-count failures were JSDOM focus-selection one-shots, not leaked progress intervals; flush only zero-delay callbacks and still require no retained timers. | [C14](memory/LESSONS_archive.md#c14); backend lifecycle and controller regressions |
| ISSUE-132 | Supervisor stopped retrying cleanup after three failures once the process died → shared buffers could remain named/mapped → releasing admission permitted repeated leaking allocations. Hold admission through successful close/unlink, reporting stopping meanwhile. | Child liveness alone cannot establish resource release. Updated the old regression that explicitly blessed the premature three-retry return. | `tests/test_part_verification_jobs.py`, `tests/test_part_verification_worker.py` |
| ISSUE-109 | Repair capture cloned typed overlay fields but its scalar whitelist omitted native Direction → valid frozen ranges reached the generic rejection branch; exact enum admission retains native types and existing accounting | Converting every Enum to a string would silently expand accepted types and lose the typed capture contract; unrelated string enums remain refused | `tests/test_part_deformation_repair.py` |
| ISSUE-99 continuation | PATCH overloaded pose preview and ordinary authoring; desktop membership/style omitted commit, bypassing history and response revision/persistence gates. One owned transaction and shared full response adoption now cover authored edits. | A separate geometry GET is insufficient for exact pairing: it lacks revision identity (ISSUE-107). Owned responses must also disable legacy normalization that can silently rewrite the accepted candidate. | `docs/audits/feature_history_20261014/validation_group_edit_recording.json` |
| ISSUE-104 | Error renderer recognized only `msg` while typed command diagnostics use `detail` → useful explanations became JSON; direct string precedence now covers the shared contracts | No recursive traversal or new truncation policy needed | `frontend/src/api/error_detail.test.js` |
| ISSUE-103 | Native work ran on a live alias before recorder ownership → candidate could overwrite an intervening edit; isolate then compare exact source/session/revision/policy before recording | Holding the full fixed-point calculation under the global lock would risk responsiveness; the extra detached copy instead remains an explicit measurement debt | `docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md` |
| ISSUE-102 | Live routes reused tolerant builders without replay reference guards and read response scope before ownership → successful-looking partial/no-op edits; one owned strict transaction restores agreement | Preserve tolerant legacy builder and empty-batch contract rather than changing compatibility replay incidentally | `docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md` |
| ISSUE-99 | Group creation made recording optional → desktop/headless callers omitted `log` → membership existed without producer inputs → later native move/replay could not reconstruct the group; one lock-owned builder/publication now records every new group | Mandatory logging alone is insufficient if creation selects source outside its transaction or reacquires the non-reentrant lock through `state.set_design`; reuse the existing lock-owned publisher | `docs/audits/feature_history_20261014/implementation.md` |
| ISSUE-80 (partial) | Cold display repeated work across native record expansion, JSON/gzip, hidden source readers, readiness assessment, primitive construction and eager maps → caches/scheduling were scoped to individual consumers instead of one versioned source lifecycle → first Full and representation saves still blocked after selection was fixed | A sub-millisecond CPU representation update was insufficient evidence: retained Full buffers do not prove Full drawing, backend save/readiness can still delay the gesture, and the initial runner omitted curved-cylinder slots; preserve the invalid run and require actual frame/triangle proof | `docs/audits/assembly_loading_performance_20261013.md` |
| ISSUE-68 | Process-local thread maps were treated as global ownership → UI polling orphaned live headless runners; child PIDs also missed preparation/inter-stage work, and stale status writes could overwrite a restart → shared kernel lease, workspace scope and generation checks now cover those boundaries | A private workspace hid the original polling symptom; it was not the lifecycle fix | `memory/project_simulation_runtime.md` |
| ISSUE-66 | Recomputed marks were merged into the original design → its obsolete marks had never been cleared → clearing happened only on the temporary calculation copy; commit now replaces active marks atomically and rejects stale revisions | None; integration assertions exposed the calculation/commit mismatch | — |
| ISSUE-61 | Gate test depended on the host platform → WSL returned plain-string 503 before the intended review check → structured-detail assertion failed → marked parent failure correctly latched the durable journal; isolate only the test's platform prerequisite and explicitly review the retained incident | Temporary incident-store leakage was considered, but source inspection showed intentional recording of the outer test failure in the runner's durable ledger | n/a; bounded test precondition fix, no placement change |
| Alpine post-download feedback | Reconciliation saved `verified` and then synchronously scanned a 19.7 GB DCD before saving terminal job state → the UI continued showing the prior synthetic `running`/retry error for minutes → users had no evidence that local CPU-bound bookkeeping was active | Treating byte verification as the terminal UX state; the download was complete, but the job was not yet usable as fully finalized | `memory/project_alpine_cluster_submission.md` |
| NAMD sequence gate | Sequence validation lived at Create → planning was rejected before a job record existed and the wizard's async boundary hid the reason → moving only the check would still leave a stale/poly-T package → unsequenced jobs now defer atomization, Run owns the hard refusal, and sequence-change prepares from the live topology before atom-count consumers or dynamics | Treating the missing notification as only a toast bug; the lifecycle boundary was wrong and a toast alone would still forbid creation or preserve stale atom counts | — |
| Slab connector color parity | Connector geometry had its own instanced color buffer → recolor paths updated beads/slabs/cones but not that buffer → geometry refresh then explicitly wrote `slab.defaultColor` → sidebar/scalar colors could never remain matched through a moving display | Updating only the flex-map loop; sidebar coloring and later geometry refresh would still diverge | — |
| Welcome library performance | The UI cleared rows until one endpoint returned → that endpoint combined presentation metadata with migration and accounting → every refresh parsed all 193 designs (~89 MB) and recursively visited a 75 GB workspace → work grew with design and simulation history even though neither was required to name files | Simulation-size accounting looked like the likely dominant cost; measurement showed it was ~71 ms cold while identity parsing alone cost ~3.26 s | `docs/welcome_library_performance.md` |
| ISSUE-3 | multi-box BoxHelper gated at ≥2 selections by design → single Ctrl-select had no visual; toggle re-clicked the active pick into a phantom size-1 set | — (root cause found on first read) | — |
| ISSUE-2 | `file-saved` cross-tab echo guard added the path to `selfSavedPaths` with NO doc check → a different-doc sibling's genuine save read as a self-echo, reload dropped | the `_RELOAD_SUPPRESS_MS` suppression window (it only arms on *same-doc* design-changed; the failing tabs never exchanged that) | difficulties ledger (doc-id/broadcast/SSE interplay) |
| ISSUE-5 | `properties_panel._render` had no `protein` branch → a `{type:'protein'}` selection fell through to `_renderNucleotide`, which reads nucleotide-shaped fields | — (pre-existing; surfaced by the #85 live exercise) | carve-up difficulties ledger (#85) |
| ISSUE-6 | test asserted an absolute scaffold-strand count → count varied run-to-run → seamless router's Hamiltonian path varied → shared `_hamiltonian_path` sorted helices by degree only with no tiebreaker → equal-degree helices came out in `set`-iteration (hash-seed) order. (Two-layer: the nondeterminism bug AND a test pinning a non-invariant intermediate count.) | (a) ledger's "cross-test global-state leak → add a reset fixture" — wrong, it fails in a single fresh process; (b) the FIXME's "just add the tiebreaker" — made it deterministic but locked onto 5 strands, exposing that the count was never the right assertion | LESSONS — hash-seed set-iteration nondeterminism class |
| ISSUE-7 | Delete on a negative-bp segment no-ops → `onDeleteElements` collected no domain selector → its key parsers used `(\d+)` → `\d+` can't match the leading `-` of a negative bp → the key built as `line:…_-17_-6_…` parsed to `null`. (Multi-factor: ALSO `_fitToContent` drew the negative cells off-screen — real but not the no-op cause.) | the `_fitToContent` off-screen visibility bug — fixed first, looked plausible ("can't click what's off-screen"), but the user reopened "still can't delete": the real defeater was the parse, not the view (the dead `erase`-tool red herring also pointed at the wrong gesture initially) | LESSONS F5 — bp is signed; never `(\d+)` |
| ISSUE-22 | Multi-factor: (1) Return affordance retained an older persistent-toast action; (2) cross-design roll spliced the active file's Feature Log because ownership was inferred from current request state while persisted `Design.id` was ignored; (3) Save As/copies duplicated UUIDs while jobs were path-keyed | “Design lacks identity” was false—`Design.id` already existed; the defect was failure to enforce professional copy/move semantics and carry the correct history | — |

## Reopen tracking (the headline effectiveness metric)

A reopened "fixed" bug is the direct signal that step-1 (repro-first) or the root-cause depth above was
insufficient. Track it: when a closed issue comes back, add a line here and bump the counter.

- Fully-closed issues to date: **8** (ISSUE-2/3/4/5/6/7/10/15; ISSUE-1 is multi-phase, still partial → not counted yet)
  _(Corrected 2026-07-13: this said **6** and omitted ISSUE-10 (closed 2026-06-16) and ISSUE-15 (closed 2026-07-08), both of which have fix-log rows. The loop was under-reporting its own effectiveness.)_
- Reopened: **1** (ISSUE-7, within the same session — the `_fitToContent` visibility fix shipped first didn't address the actual no-op; caught + corrected before closing, not a cross-session reopen)
- **Reopen rate: 1 / 8 = 12.5%** _(target < ~10%; the ISSUE-7 reopen is the lesson — a plausible single-factor fix (visibility) was shipped before reproducing the EXACT gesture (select→Delete, not the dead erase tool). Reproduce the real gesture end-to-end before claiming a fix on a "nothing happens" bug.)_

_Reopen log (id · what came back · why the first fix was incomplete):_
- **ISSUE-7 · "still can't delete after reloading" · the first fix (`_fitToContent` panX offset, making the off-screen negative-bp cells visible) was a real but SECONDARY factor.** The primary defeater was `onDeleteElements`'s `(\d+)` key parsers dropping negative-bp keys → Delete silently collected nothing. Root cause of the incomplete first pass: fixed a plausible factor (off-screen) without reproducing the user's EXACT gesture end-to-end — and chased the `erase` tool (dead UI) instead of the real select→Delete path. The reopen forced the faithful repro that found the parse bug.

## Difficulties ledger

_Append a dated entry whenever a phase hits a dead-end, a surprising root cause, a flaky repro, or a
"the obvious fix was wrong" moment. Future sessions read this to avoid re-paying the cost. Empty at
creation._

**ISSUE-3 (2026-06-05) — empty-centers fixture + gizmo occlusion blocked two of three e2e repros.**
The inline `loadAssemblyWithParts` fixture has an empty renderer bounding box, so `getInstanceCenters()`
returns `[]` and `instanceUnionBox` returns null → the multi-select box NEVER materializes in that e2e at
any selection count. So the box's white/purple rendering can't be asserted in e2e — it's pinned by the
vitest unit test (mocked centers) instead. Separately, the move/rotate gizmo auto-arms on plain-click and
occludes the second rod in the tight fixture, so "plain-click A then Ctrl+click B → both" can't be driven
either (pinned by `toggleInstanceSelection` unit test). Net: only the "Ctrl+click the active part toggles
it off cleanly" case is both e2e-drivable AND discriminating (pre-fix left a phantom size-1 multi-set).
Lesson: for assembly visual/center-dependent behavior, app-verify on a REAL `.nass` via
`__NADOC_DBG__.{store,assemblyRenderer}` + `importAssembly` (centers ARE populated there — 62 for
Belt_test1); the inline e2e fixture is only good for pick/selection-STATE wiring.

**ISSUE-2 (2026-06-05) — the obvious repro (2-context Playwright) cannot reproduce the bug; root cause was a doc-id split, not the suppression-window the dossier suspected.**
The ledger's hypothesis pointed at `_RELOAD_SUPPRESS_MS = 10000` (the `markSameDocActivity` window). That
was wrong: that window is only armed by a *same-doc* `design-changed`, which the two failing tabs (different
sticky doc ids) never exchange. The real defeater was the `file-saved` cross-tab echo guard in `main.js`
adding the path to `selfSavedPaths` with NO doc check — so a different-doc sibling's genuine save was
treated as a self-echo and its SSE `file-changed` reload was dropped. Also: the handoff's suggested
acceptance test (two `browser.newContext()` on the same `?doc`) can't reproduce it — `BroadcastChannel`
does not cross Playwright contexts, so tab B never gets the `file-saved` echo and the reload fires even on
the buggy code. The bug needs two REAL same-browser tabs (shared BroadcastChannel) with DIFFERENT doc ids.
Pinned the logic with `registerSiblingSave` unit tests instead; app-verification is a two-real-tab USER TODO.
Lesson: trace the doc-id/broadcast/SSE interplay before trusting a suppression-window hypothesis, and check
whether your repro harness even shares the channel the bug rides.

**ISSUE-1 Phase 2a (2026-06-05) — the handoff's "2a = 3 menus in one phase" was wrong; the 3 design-editor menus differ a LOT in migration cost.** Verified before implementing: (1) **overhang-binding** is a clean dynamic builder → trivial `createContextMenu` migration (the only gap was no `danger` styling on the primitive — added a reusable flag). (2) **overhang-orientation** embeds a hover-flyout SUBMENU (`createRepresentationMenuItem`, shared with `selection_manager.js`) that `createContextMenu` cannot express → needs a primitive extension (a `{ type:'custom', el }` item type) FIRST. (3) **blunt-end** is not a builder at all — a static `#blunt-end-ctx-menu` HTML element with 3 heavy pre-wired handlers; converting it moves real launch logic. Lesson: for the menu-migration phases, scope ONE menu per session and read its structure before committing — "they're all just context menus" hides a 10× cost spread. The `danger` flag is now shipped and reusable for every remaining migration's destructive items.

**ISSUE-4 Phase 2 (2026-06-05) — a flag-gated ADDITIVE rewrite, not an in-place one, kept a risky interactive change at zero regression risk.** The spec wanted to MERGE three live mechanisms (auto-drill ladder / manual pins / Tab-lock) into one `selectionLevel`. Doing that in-place would have rewritten the hottest selection paths with no safe fallback. Instead: keep every legacy branch byte-for-byte and add v2 handlers that gate AHEAD of them on `_drillV2` (read once from `NADOC_DRILL_V2`). main.js LOC Δ = 0 because the flag is read inside each module (`drillV2 = isDrillV2()` opt with a default), so NO new wiring args were needed — the existing `onDrillLevel`/`isManualSelect`/`setDrillLock` injection already covered it. Surprise that made it cheap: the legacy `_drillLock` already implemented "fixed level on every click," and the legacy MANUAL default path already did "strand→leaf," so v2's primitives are near-mirrors of existing branch bodies — the only genuinely new behavior was the hover preview. Lesson: for a risky interactive state-machine rewrite, prefer an additive flag-gated parallel path read inside the owning modules (keeps main.js untouched + the off-path provably intact via smoke) over an in-place merge; and re-read the legacy code first — the "three mechanisms" often already contain the pieces the new model needs.

**ISSUE-4 Phase 3-preview (2026-06-05) — "breadcrumb" meant the wrong thing; asking the FORM before building caught it.** The handoff (and decision E) called Phase 3's headline item a "breadcrumb UI" — a persistent TEXT level-trail (`Strand ▸ End`). I started toward exactly that (read the filter row, planned a `ui/selection_breadcrumb.js` text widget). The protocol-2 "ask the FORM before implementing" question surfaced that the user had a completely different mental model: by "breadcrumb / the next thing that would be selected" they meant the **hover-preview highlight** — would-be leaf glows RED, selected leaf glows GREEN. Phase 2 had shipped that affordance as a scale-pop and explicitly never eyeballed it; the user's "fix" was to make it a red glow. Net: the whole text-widget build was the wrong feature. Lesson: when a handoff hands you a NAMED UI artifact ("breadcrumb", "badge", "panel"), still ask the user what it should *look/behave* like before coding — a named noun can carry a different referent between sessions, and one AskUserQuestion is far cheaper than building the wrong widget. Also: the additive green+red glow blend means a red preview over a green-glowing strand washes toward yellow at the bead centre — mitigated with a larger red halo (4.2 vs 2.8) but flagged as a Tier-3 eyeball check, not asserted.

**ISSUE-4 Phase 3-xover (2026-06-05) — "crossover" in the 3D view is three different rendered things; the user's "crossover arc" is the one NOT in any raycast set.** Asking the element-identity question (per the CLAUDE.md crossover-caution rule) paid off immediately. Code facts that settled it: in `helix_renderer.js`, a cross-helix step renders its cone at **radius 0** (`r = isCrossHelix ? 0 : CONE_RADIUS`) — the visible "cones" are only WITHIN-helix direction markers, NOT crossovers. The actual crossover is a thin **arc** rendered by `unfold_view.js` (`getArcEntries()`, exposing `crossover_id`/`getMidWorld()`/`getPositions()`/`setColor()`). Arcs are pick-by-PROXIMITY (`_findArcAt`, screen-space `_arcHitPx`), not raycast — so the bead/cone hover/click never touched them. The legacy click DID handle arcs but only selected the proper crossover object (green `getCrossoverGlowEntries`) behind the `crossoverArcs` filter (off in v2); the v2 plain-click fell through to a strand/`'cone'`-pseudo select with no glow. Fix routed a v2 arc branch (`_v2HandleArc`/`_selectCrossoverV2`) into the no-bead-no-cone fallback. Perf note: hover reuses the already-computed `_strandArcEntries` (selected strand only) instead of the global `_findArcAt`, so a pointermove doesn't project every arc in a dense design. Lesson: for anything "crossover", enumerate the rendered elements (cone vs arc vs extra-base beads) and which are raycast vs proximity BEFORE coding — the user's word maps to a specific one, and the hidden-cone detail is non-obvious.

**ISSUE-4 Phase 3-filter-audit (2026-06-06) — the lasso fix was clean, but the chosen "flip ON + delete legacy" scope collided with an un-verified feature; re-surfacing the gap before acting was correct.** The per-mechanism keep/clean/delete ask resolved fast (#8 lasso KEEP-but-FIX; #7 KEEP; #9 DEFER; #4/#5/#6 DELETE). The user's first scope answer was the most aggressive: lasso fix + flip the `NADOC_DRILL_V2` default ON + delete the 3 legacy mechanisms in one phase. Reading the deletion surface BEFORE coding (the discipline that keeps paying off) found two facts the scope answer couldn't have weighed: (a) it's **87 entangled reference sites** across the 3 hottest selection modules — a live-path rewrite, not dead-code removal; (b) **drill-v2 has never been human-eyeballed on a multi-helix design** (explicit open carry item) and the Tier-3 WebGL visual check (red/green preview colour, filter-row paint) is deliberately NOT automatable here. So "make the un-eyeballed path the default AND delete its fallback in one go, with no app gate I can satisfy" is exactly the handoff's named risk. Re-asking with that info → the user chose "eyeball v2 first, then flip+delete." Net: shipped the actual reported bug (lasso) clean + gated; deferred the risky half behind a USER TODO. Lesson: when a phase's scope includes flipping a flag DEFAULT + deleting the fallback, check whether the now-default path was ever visually verified — a scope decision made before that's known is under-informed, and re-surfacing it (cheap) beats shipping an un-eyeballed default (expensive). Also: the single-helix `loadScaffoldedPart` harness fixture genuinely can't drive a multi-element lasso (no clusters/crossovers), so the lasso fix is unit-pinned via the pure `lassoCaptureType` kernel — the recommended route, not a shortcut.

**ISSUE-4 v2-eyeball feedback batch (2026-06-06) — flipping a default-flag breaks every test that assumed the old default; pin the legacy-path tests with the explicit opt-out, don't delete them.** After the user eyeballed v2 and approved, decision C flipped `isDrillV2()` to default ON. That instantly broke 18 unit tests across `selection_level`/`selection_filter`/`keyboard_shortcuts` — but in TWO different ways worth distinguishing: (a) tests pinning the v2 MODEL constants (LEVELS/TAB_CYCLE/flag default) needed their expectations rewritten to the new model; (b) tests exercising the LEGACY path (manual pins, drill-lock Tab) broke only because the factory now defaults `drillV2=isDrillV2()=true` — they were testing dead-by-default-but-still-present code. The right fix for (b) is to construct the factory with `drillV2: false` explicitly (NOT to delete the tests), so the legacy path stays covered until its physical deletion. When that deletion lands, those `drillV2:false` tests delete alongside the code. Also: the flag flip means smoke + ALL design-view e2e now boot v2 by default — verified bead_select (Alt-pick, drill-independent) + drill_v2 still green, and confirmed no e2e asserted legacy auto-drill click behavior (only drill_v2 exercises the design plain-click ladder). Lesson: a default-flag flip is a test-wide event — sort the breakage into "model expectation changed" (rewrite) vs "legacy path now needs the opt-out" (pin with the flag), and grep the e2e/smoke boot paths for anything that silently relied on the old default. Separately, this whole batch validated the iterate-on-feedback loop: shipping the small clear items (A 2nd-click-keep, B green tube) as their own commits while confirming the model-changing one (C) with a 2-question AskUserQuestion kept each commit bisectable and avoided re-gutting on a misread (the `strand`-distinct-from-`default` level was the subtle bit the ask pinned down).

**ISSUE-4 legacy-deletion (2026-06-06) — the handoff's "delete `_drillClusterId`" was WRONG; it's shared state v2 relies on. Read the deletion surface, don't trust the symbol list.** The handoff listed `_drillClusterId` among the legacy vars to delete (`_drillAnchor`/`_drillLevel`/`_drillSeq`/`_drillClusterId`). Reading the code first (the discipline that keeps paying off) showed `_drillClusterId` is set by `_highlightCluster` — which the v2 cluster select (`_selectClusterV2`) calls — and read by the cluster right-click menu + the post-rebuild cluster-highlight subscriber. Deleting it would have broken the v2 cluster menu. KEPT it; only `_resetDrill`'s reset of it moved inline into `_clearAll` (`_drillClusterId = null`). Lesson: a deletion handoff's symbol list is a LEAD, not a fact (same map-trust rule as the carve-up) — a "legacy" var can be load-bearing for the surviving path. Two other subtleties the read caught: (a) the v2 visibility-gate path (scaf/stap/loop/skip/ovhangs clicks) was tangled into the deleted `_manualFilters`/`resetToAutoBaseline` machinery, so the clean replacement made them PURE plain-toggles (computeFilterToggle + a `V2_LEVEL_KEYS`-gated subscriber) — a deliberate, user-approved behavior refinement (the old reset-to-baseline-on-unpin was a legacy side effect), NOT a pure no-op; (b) `_handleCtrlTypeLockClick` was already dead in v2 (`_currentDrillType()` returns null when `_drillSeq` is empty, which it always is in v2), so removing it + leaving Ctrl+click-no-drag a no-op preserved behavior. Default-flag-DELETION (not just flip) is a test-wide event: the `drillV2:false`-pinned legacy tests delete WITH the code (as the v2-eyeball entry predicted), and the v2 tests that passed extra `drillV2:true`/`drillType` keys keep passing (extra keys ignored) — but clean them up so the next reader isn't misled.

**ISSUE-7 (2026-06-08) — a "nothing happens" bug is multi-factor; the plausible first fix was the wrong layer, and the symptom pointed at a DEAD tool.** Three traps cost a reopen: (1) **The `erase` tool is a red herring.** The pathview has a full `erase`-tool delete path (`onEraseDomain`), but it has NO toolbar button and NO keybinding (the R-cycle is select→pencil→nick→paint; N/P only) — it's unreachable dead UI. The real delete gesture is **select-tool → Delete key → `onDeleteElements`**. The first investigation traced + even e2e-tested the erase path (which "worked" in isolation), proving nothing about the user's actual gesture. (2) **The first fix addressed a real but secondary factor.** The negative-bp stubs WERE drawn off the left edge by `_fitToContent` (a genuine bug, numerically confirmed: bp −17 at screen-x −37); fixing it was correct but didn't make Delete work, because the actual no-op was the parse. Shipping it before reproducing the EXACT gesture end-to-end caused the "still can't delete" reopen. (3) **The real bug was a `(\d+)` regex that silently rejects negative bp** — see LESSONS F5. Lesson: for a "nothing happens / silently no-ops" report, (a) find the EXACT code path the user's gesture takes (which tool/key actually fires — don't assume the obvious-looking one is wired), (b) reproduce it end-to-end FAILING before fixing, and (c) treat a plausible single-factor fix with suspicion until the real gesture is reproduced — `CLAUDE.md`'s "three-layer/topology bugs are usually multi-factor" applies to UI-state bugs too. The clean win: extracting all build+parse of the element keys into one round-trip-tested module (`element_keys.js`) means the negative case is now pinned and the format can't drift from its parser.

**Loop conventions banked at creation (2026-06-05):**
- **Repro before fix, ask before implement.** The two non-negotiables. A bug without a reproducing test
  is not ready to fix; a UX bug without the user's chosen target behavior is not ready to implement.
- **`rg`, not `grep`, on main.js** — grep's binary heuristic trips on some byte in the file and silently
  returns zero matches (carried over from the carve-up loop, where it cost ~5 tool calls).
- **`just lint` is Python-only** (`ruff check backend/ tests/`), currently ~38 pre-existing errors unrelated
  to frontend; a frontend-only fix has lint delta 0 by construction. No eslint config exists for the frontend.
- **`just smoke` is two gates** (console-error render + teardown) — run it for any DOM/scene/store fix.
- **Don't grow main.js** — see the prime-directive section in `issues_ledger.md`. If the buggy code is
  still inline, extract-then-fix (carve-up) or minimal-patch-then-log-as-extraction-target.

ISSUE-24 (2026-09-04): [x] Released animation job rows from the performance idle gate,
with a bounded fallback for background requests. Pending-list and timing regressions
pass; the ordered preparation/readiness follow-up passes 196 focused tests and two
isolated browser checks. Full validation details: docs/animation_trajectory_loading_audit.md.

ISSUE-25 (2026-09-11): [x] PEG inputs use sidebar tokens; 2 Playwright tests
cover contrast, real input, API review and wizard request propagation. Root cause:
PEG fields lacked the explicit styles present on adjacent surface fields; numeric
steps also disagreed with the existing density default and fractional charge API.
Initial fixture attempt bypassed normal file-open lifecycle and left Simulations
disabled; corrected with an isolated scratch file and teardown. Follow-ups and
validation limitations are recorded in docs/peg_coating_setup.md.

ISSUE-26 (2026-09-11): [x] PEG Live frontend/backend path implemented. Root causes:
explicit 409 rejection, PEG built without Python bindings, Live topology rewritten
from DNA alone, and trailing PEG particles incompatible with stock Live readout.
Bindings are isolated per process; topology and CM frames are preserved. Browser
fixture initially targeted the hidden legacy job list; corrected to use the visible
unified list. Real stepping is pending a user-opened test session; see docs/peg_live.md.


ISSUE-27 (2026-09-13): [x] First-save NAMD form reset reproduced in the requested
blank-file workflow and fixed in `md_jobs_panel.js`; no `main.js` change. Browser
coverage verifies first save plus actual draft persistence. The charged-wall
preparation audit separately exposed a rebuilt descriptor dropping charge and
temperature; the API handoff now applies those fields after the final rebuild,
with a regression at the molecular-builder boundary. Broader smoke remains red
on an unrelated mrDNA job-save HTTP 500 race; see `docs/namd_charged_surface.md`.

2026-09-14: [x] ISSUE-28/29/30: managed CUDA electrode library/restart initialization,
false native-process adoption and cadence-dependent screening metrics corrected.
Real Start-API pilot completed at 4 fs; longer runs remain visible under the source
nadoc. Regression and scientific-analysis tests cover the corrected contracts.
See docs/namd_electrode_gpu.md and workspace/electrode_gpu_screening_4fs_20260914/.

2026-09-20: [x] ISSUE-31: guarded the optional test bridge's secure-context UUID
requirement so it cannot prevent ordinary HTTP LAN viewing. Added unit coverage
and a real non-secure-origin Playwright project, including completed manual
performance capture. Both production browser projects pass; 6,692 frontend tests
pass. Cached host assets require restarting the test host and replacing its link.

## 2026-09-21 — ISSUE-32, ensemble submission context lifetime

Fixed as part of the Alpine periodic-image clearance gate. Root cause: closing the review cleared its shared context before the asynchronous ensemble submit branch read the partition. Capture the reviewed partition before teardown. The regression exercises the ensemble API call after disposal, including the new explicit clearance override. No alternate hypothesis pursued; `main.js` LOC delta 0.

<!-- ISSUE-31/32 below were independently assigned on the CPD branch; historical IDs retained. -->

2026-09-20: [x] ISSUE-31/32: preliminary cis-syn strand-builder integration removes
reactant planar C5 impropers and rejects bypasses of product coordinate placement.
Native builder duplex passes 1,000 minimization and 1,000 2-fs dynamics steps.
See docs/cpd_strand_builder.md. No main.js changes from this task (LOC delta 0).

2026-09-22: ISSUE-33 null tool draft guard implemented. Physical run exposed stopped polling, not an Undo mutation failure. Main.js LOC delta0 for this fix; regression sends null then valid draft through actual application handler. See .development-artifacts/vr-workflows/fit-undo-physical (failure preserved); validation follows in fit artifacts.

2026-09-22: [x] ISSUE-34: atomic private VR session publication and non-destructive status reads. Root cause: reader treated partial JSON as stale and unlinked a pathname concurrently being written. Deterministic publication/racing-reader regressions pass; physical commit/Undo passes after correction. ISSUE-33 also exercised by subsequent physical polling. Evidence fit-undo-atomic; previous failed attempts preserved.

2026-09-22: ISSUE-35: bounded read-only scene refresh retry after autosave revision advance. Mutation remains exactly once, stale snapshot remains rejected. First physical6HB failure preserved under sixhb-physical. Frontend main.js LOC delta0.

2026-09-22: [x] ISSUE-36: save acknowledgement carries atomic revision metadata, accepted only against the browser's matching preceding revision. Maintains lightweight response and no autosave-loop design replacement. Physical desktop6HB→VR6cells in same rotated frame→Undo→cadnano edit/save/reload passed; commit20.1s and Undo12.4s scene refresh remain performance debt. Main.js LOC delta0.

2026-09-22: [x] ISSUE-39: visible Tools→Extrude now supports empty-part configuration
and opens the paint tablet through shared initialization with radial activation.
Physical steady_fast VR-first menu/paint/wheel/Confirm/Undo/cadnano/save-reload passes.
Native36tests and26focused tooling tests pass. Existing framing helper now accepts
a visible-UI callback; regression rejects hidden semantic activation in that path.
Evidence: .development-artifacts/vr-workflows/menu-activation-validation.md.

2026-09-22: [x] ISSUE-40: settings pixel review found blank minus glyph despite valid
layout/interaction checks. Added horizontal stroke and nonblank/distinct-from-plus
regression. Root cause: font's fallback erased an unsupported character; geometry
checks do not observe label meaning. No failed alternative fix; discovered during
larger target work. Native36tests pass; settings-sign-steady full VR-first roundtrip passes56.3s;
submitted-eye image confirms minus signs on length/direction/size controls. Frontend main.js LOC delta0.

2026-09-23: ISSUE-41 opened by actual image review after a green combined workflow:
native whole-design review occupies82x64pixels and is largely end-on, while the
presence-only threshold passes. No framing fix yet; recorded as unresolved rather
than declaring visible debugging complete. Desktop geometry/edit/save-reload remains
validated. Native camera/bounds root cause needs measurement; no geometry change.

2026-09-23: [x] ISSUE-41 opt-in review now uses ordinary rotation/scale, both-eye
coverage/cluster/RGB checks and actual desktop pixel comparison. Original weak
view retained. A subsequent0%desktop match failure is retained separately; headed
demo explicitly reveals only its PID-verified native viewer, keeping thresholds.
Physical through-lens comfort and authoring-trace delivery remain open.

2026-09-27: [x] ISSUE-42 — assembly Simulations tab opening no longer flattens for
passive API reads; recommendation uses a valid GET and lightweight assembly facts.
Unified jobs resolve assembly identity without a loaded projection; NAMD source-path
wiring matches other engines. Tests and limits: docs/audits/assembly_simulations_20260927.md.

2026-09-27: ISSUE-43 — CanDo/SNUPI assembly execution uses a compact backend projection
and snapshot-based visualization. Root cause: a part-centric preparation/display
optimization assumed a live flattened part renderer; uncached full-topology fingerprints
on every FEM poll then competed with the solver. Reused the existing revision cache and
moved preparation/results off the event loop. Native BigO runs disproved the initial
missing/disconnected-mesh hypothesis (one connected 211,680-node mesh). A no-RMSF summary
also mistook unpaired terminal geometry for FEM nodes; corrected from axis records.
Evidence and gates: `docs/audits/assembly_fem_execution_20260927.md`. main.js delta 0.

2026-09-27: ISSUE-44 — Thermal reconstruction reused the expensive full display
pipeline for 48 frames while retaining only XYZ. Cache immutable per-job reference
geometry, batch bead reconstruction, preallocate numeric frames and stream JSON.
BigO two-frame comparison: 5.1–5.5× reconstruction speedup, <1e-12 nm coordinate
difference; full-job NMA speedup is not claimed. Progress and cancellation now
advance at each frame and persistence boundary. See the thermal optimization audit.

- 2026-09-27 · ISSUE-45 · Large completed CanDo results use bounded point/line
  rendering, compact transport, indexed cylinder joints, native-source visibility
  guards and cancellation-safe switching; metric graphs reuse compact scalars.
  [Audit](docs/audits/cando_visualization_guards_20260927.md). main.js Δ +3.

- 2026-09-27 · ISSUE-46 · Verify cached simulation fingerprint ownership with a
  weak reference; a recycled object ID cannot reuse a closed design's fingerprint.
  Deterministic regression reproduced the failure before the fix; 18 focused tests pass.

- 2026-09-28 · ISSUE-47 · SNUPI shares guarded large FEM views/metrics; bounded,
  indexed trajectory playback preserves scrubbing with cancellation/backpressure
  and GPU-buffer reuse. [Audit](docs/audits/snupi_visualization_guards_20260928.md).
  main.js Δ +1.

- 2026-09-29 · ISSUE-48 · Browser representation publication shares the complete
  identifier contract; native partial installs honor pre-axis availability.
  Desktop cylinder builder supplies native radius/topology/palettes. Sidebar
  hit-testing also supplies unpressed pointer rays. main.js Δ +1 (error logging).
  Root cause: duplicated allowlists diverged, while synthetic axes satisfied an
  incorrect presence check. Initial suspicion of unfinished Surface generation
  was disproved by completed export and a visible desktop Surface paired with
  repeated Full acknowledgements. [Audit](docs/audits/vr_representation_parity_20260929.md).

- 2026-09-29 · ISSUE-49 · Native atomistic bonds now share Full's lit cylinder
  renderer. Sidebar navigation follows the logical row list across viewport edges
  and uses shared easing/clipping; descendants indent by ancestry. A real GL
  removed-occluder control distinguishes cast shadows from diffuse shading.
  main.js Δ 0 for this change. [Audit](docs/audits/vr_shadow_scroll_20260929.md).

- 2026-09-29 · ISSUE-50 · Diagnosis only; OPEN. Real browser/ScryWrite loads
  measured 226/393/806 ms synchronous style application and a separate 112 ms
  Surface gap at 49.198%. Root cause of final stalls: geometry preparation and
  GL staging run on the XR thread before the existing frame timer starts.
  GPU priority alone cannot fix this path; the earlier gap remains unattributed.
  Added local phase/log diagnostics; no scheduling fix, main.js Δ 0.
  Three functional tours and native build passed; frame-comfort acceptance fails.
  [Research and evidence](docs/audits/vr_loading_stalls_20260929.md).

- 2026-09-29 · ISSUE-50 · Static CPU geometry/index preparation now runs on the
  parser worker; separate GL buffers upload in 1 ms / 256 KiB slices and activate
  after a zero-timeout fence poll. CPU/GPU caches have inactive budgets, with CPU
  retirement off the XR thread. Finer tracing isolated the earlier gap to avatar
  publication (335 ms); a coalescing writer removes that disk wait from XR.
  Object-ID table growth and redundant static shadow draws were additional costs,
  addressed with bucketed IDs and shared shadow reuse. Clustered slow frames
  select a lightweight loading scene. Native traces and SteamVR compositor timing
  now gate the registered loading-performance tour. Retained failed trials caught
  startup availability, memory pressure and frame-observation transport problems;
  none are erased or relabeled as passes. main.js Δ 0.
  [Implementation and measured limits](docs/audits/vr_loading_frame_delivery_20260929.md).

### ISSUE-51 — post-load motion regression investigation (2026-09-29, unresolved)

Reverted speculative shadow/lighting changes and the loading patch's shadow cache
following the user's confirmation that the earlier renderer performed well.
Kept staged loading/async publication; isolated legacy/staged upload comparison
has identical pixels and comparable GPU timing. Stick motion passes the final
initial profile; Ball & Stick still fails. Do not describe this as a completed
performance fix. [Evidence and testing limits](docs/audits/vr_motion_regression_20260929.md).

2026-09-30 — ISSUE-52: animation sharing exposed a pre-existing NaN in
`_refreshSlabConnectors` when decomposing a zero-scale slab matrix. Pinned with a
failing renderer test, then kept collapsed connectors finite and hidden. Visible
molecular coordinates and topology are unchanged. Shared-animation browser
coverage exercises the construction-stage transition that exposed the defect.


- 2026-10-04 — ISSUE-54 [x]: pattern API wrappers propagate rejected requests;
  panels retain their preview and show the error. Regression coverage:
  `frontend/src/api/pattern_requests.test.js`, `linear_pattern_panel.test.js`.
  No additional main.js logic (linear-tool feature wiring is +2 LOC).
2026-10-05 — ISSUE-59 / ISSUE-60: OPEN intake from the Benchy native-tool
benchmark. All-helix cluster creation left a saved lattice frame referring to a
removed default cluster; fresh-cell extrusion left 714 of 1,157 helices outside
the placement cluster, so its Move affected only the initial 443. Product code
was not changed. The benchmark workaround preserves the placement cluster and
patches its membership through the native cluster API. Corrected native reload
and occupied-domain validation match all 11,984 reference cell-slabs, with zero
missing/extra/off-grid intervals. [Observed state and retained failing file](.development-artifacts/benchy_20261005/cluster_bug_evidence.json).
Regression tests and product fixes remain pending; `main.js` delta 0.

2026-10-05 — ISSUE-55: fixed native print/atomistic export failing at strand
702. Shared unbounded alphabetic chain labels preserve A…ZZ exactly and agree
with PDB cycling plus NAMD package/playback maps. All 24 focused chain tests
pass, including a real 3,062-strand build and legacy semantic component IDs;
existing NAMD segment-order, streptavidin preparation, and large-design PDB
connectivity regressions pass. Native 3,062-strand Benchy STL export completes
in 32.3 s with the initial surface settings. Identity
bookkeeping only; molecular geometry is unchanged. `main.js` delta 0.
Final native Benchy export (0.30 nm grid, 0.90 nm probe, 60 mm target) is one
watertight connected surface: 1,446,424 triangles and zero boundary, nonmanifold,
degenerate, or inconsistent-winding elements. Final `just test-smart` decision
FAST: 9,605 passed, 93 skipped, one unrelated existing loop/skip bit-identity
failure (1.11e-16), reproduced independently against unchanged geometry code.
Full-suite debt remains deferred; exact output is retained in
`.development-artifacts/benchy_20261005/test_smart_final.log`.

2026-10-05 — ISSUE-56: Extrude dismissal now follows acceptance of the Confirm
intent, retaining the asynchronous submission until matching feedback arrives.
Retry republishes a consumed validation plan, and Undo uses its saved feature
instead of the user's later selection. Shared layout auditing now checks text
against neighboring text/features and reserved columns; the prior bounds-only
checks missed real overlaps. Transparent MSAA text was attenuated twice, while a
width-capped cache retained the old height and filtered wide-panel text excessively.
Corrected alpha handling and cache aspect restore lettering; first allocation also
preserves the caller's framebuffer. Failed observation hypotheses (window-size
clamp, framebuffer binding and whole-panel pixel counts masking faint letters)
are retained in the [audit](docs/audits/vr_menu_formatting_20261005.md).
425 rendered states and 12,001 layout cases pass; full frontend suite 7,375 passed,
1 skipped. `main.js` delta 0. Reopen count: 0.

2026-10-05 — ISSUE-57 intake (OPEN): right-wheel testing exposed a stale Nick
pixel projection (+Y versus the renderer's -Z), now corrected with a pure test.
The broader scissors/glow visual workflow still fails; no rendering fix is
claimed. Target selection, wrist/contact adjustments, mirror size and grip zoom
were insufficient; those experimental probe changes were removed. Evidence and
unchanged pixel thresholds are recorded in ISSUE-57 and
`.development-artifacts/vr-edit-wheel-20261005/`. Wheel behavior is validated by
its own four-profile stereo tour and separate document-history workflow.

2026-10-05 — ISSUE-58 intake (OPEN): the Ligate browser tour reaches the new
right-wheel mode and rejects the invalid release, then its stretched-preview
pixel gate fails (3/7 left, 2/7 right/mirror). Production preview code and the 0.7
coverage threshold are unchanged. Evidence is retained under
`.development-artifacts/vr-edit-wheel-20261005/ligate/`; commit/save was not reached.

2026-10-08 — ISSUE-66 fixed during sweep loop/skip support. Root cause: marks were
cleared on the calculation copy but merged onto the uncleared committed design.
The commit now clears active bundle marks before replacement and rejects stale
revisions. Repro/regression: HC/SQ seed an illegal old end mark, realize, repeat,
undo/redo and revert; reference/overhang/linker preservation stays covered by the
existing suite. 14 focused sweep-realization tests + 75 existing loop/skip tests
pass. No discarded hypothesis; no production molecular-placement changes.
`main.js` delta 0. Reopen count: 0.
App validation: Add Loops/Skips menu, undo/redo, complete `.nadoc` export/reload
passed (1 browser test); screenshot inspected and test workspace artifacts removed.
`just test-smart` selected FAST: 10129 passed, 19 skipped, 21 failed, 4 errors;
failure signatures exactly match the preceding sweep-wizard run. Timing guard
reports 20 unrelated existing tests over 5 s, none from the new sweep suite.
Full suite deferred by the session gate. Lint retains the existing unused `Path`
import in `tests/test_cpd_cube_validation_v6.py`; `git diff --check` passes.

2026-10-07 — ISSUE-59: fixed SNUPI coordinate-field parsing after the platform
comparison exposed 1,194 silently omitted nodes. Adjacent signed 8-character
coordinate fields now use a fixed-width fallback; legacy whitespace input is
preserved. Added a regression using actual platform output. No molecular
coordinates or topology are changed.

2026-10-08 — ISSUE-67: construction animations now traverse intermediate states
and render their historical DNA/particle topology. Explicit WebCodecs timestamps
replace wall-clock WebM capture in both exporters. Root cause: endpoint-only
planning and live-topology/live-recorder assumptions were insufficient for a
historical build movie. The closer Voltron check additionally exposed ordinary
snapshot replay retaining future nanoparticles; a failing browser assertion and
backward/forward backend regression pinned that defect before the replay fix.
No molecular-placement formula or golden changed. `main.js` delta +2 wiring lines.
Reopen count: 0. Validation evidence: `.development-artifacts/build-animation/`.

2026-10-08 — ISSUE-67 follow-up: sweep construction animation reveals origin to
path end in Full/Cylinders/atomistic/surface displays; reverse playback retracts
from the end. Empty initial surface preparation is handled explicitly. Headed
preview and decoded video verified; source geometry/topology stays unchanged.

2026-10-11 — ISSUE-69 intake: isolated untouched HEAD reproduces the Extrude
menu-spacing failure seen while validating VR Join. No fix attempted; root cause
remains the mismatch between Extrude bounds and the existing rail oracle.
Baseline proof is retained in `.development-artifacts/vr-join-20261011/`; exact
generated baseline sources/binary were removed after verification.

2026-10-11 — ISSUE-70 intake: the headless braced-corner investigation reproduced
Free Join selecting extra adjacent side attachments whose connector-only cycle
cannot be nicked without breaking requested joins. Native realization correctly
rejects the set; precursor matching lacks that feasibility constraint. Same-pose
diagnostic subsets and a narrower-reach public Join succeed. No product fix or
scientific rule change attempted. Evidence and reproducible authored fixtures:
`.development-artifacts/braced-corner-20261011/`. `main.js` delta 0.

2026-10-11 — ISSUE-71 intake: strict native export/import validation of the braced
corner preserves topology and rigid poses but changes flexible-connector anchor
orientation and bead positions (maximum observed 1.97979197 nm across two
processes; eight connector nucleotides, zero nonconnector nucleotides). Direct model
serialization had passed; exercising the real import path exposed the defect.
Before/imported models and per-nucleotide evidence are retained under the same
artifact root. No geometry repair attempted; native persistence remains an
explicit failed gate for promoting this prototype to a reusable primitive.

2026-10-12 — ISSUE-72 fixed: range configuration now publishes atomically after
clearing old playback state. The new acknowledgement can no longer carry the
previous range. Fifteen focused trajectory/bridge tests pass, including a new
notification regression; native/live range-wheel evidence is retained under
`.development-artifacts/vr-range-wheels-20261012/`. `main.js` delta 0.

2026-10-12 — ISSUE-73 fixed: removed adjacent-sidebar closure during simulation
snapshot adoption and separated representation changes from simulation teardown.
Shared physical-coordinate representations preserve scalar colors; exact sampled
source IDs drive MD/oxDNA atoms. FEM/CG atomistic requests are serialized and stale
responses are discarded. Compact sources retain nucleotide identities and publish
their current frame on representation changes. An initial live failure exposed a
missing switcher helper export; the export and regression were added. Another
capture attempt was invalidated by a development reload while source was edited;
subsequent live validation freezes the source. Evidence and limits are retained in
`docs/audits/vr_simulation_representations_20261012.md`. `main.js` delta −12.

ISSUE-74 (2026-10-12): simulation trajectory popup controls now precede disabled
background rows in hit testing. All ten numeric keys have real-ray regression
coverage. The initial live loop check exposed this while seeking the selected
range end; its failed evidence is retained under `vr-trajectory-loop-20261012/initial`.

2026-10-13 — ISSUE-79 fixed: selecting an assembly part no longer seeds an
animation or PATCHes its source. Shared versioned Design reads, stable selection
rows, queued source-aware renderer refreshes and direct color-buffer repainting
remove redundant work. Backend indexed-sweep axis sampling is batched with exact
coordinate parity; compact geometry and unrelated cache entries are retained.
A review caught a stale authoring callback during forced refresh; a loading guard
and three regressions close that race. `main.js` delta 0 (two wiring substitutions).

Full Benchy app validation retained 462,002 nucleotides and 91.75 million triangles:
selection 64–449 ms, color change 290 ms versus 10.39 s, 32 fps during idle, no
basic-action/idle rebuild or busy overlay. Cold opening and explicit representation
builds remain slow; their measured limits are recorded rather than hidden.
Frontend: 7,917 passed, 1 skipped, followed by 33 affected tests passing after the
refresh guard. Focused backend: 48 passed. `test-smart` FAST: 10,542 passed,
22 failed, 21 skipped, 4 collection errors; missing prerequisites and four
HEAD-reproduced failures are documented, with the deferred FULL notice, in
`docs/audits/benchy_full_performance_20261013.md`. Reopen count: 0.
App smoke: 23 passed; native placement gate clear; changed-file Ruff clean,
repository lint delta zero. Original Benchy hashes and test cleanup verified.

2026-10-13 — ISSUE-80 **PARTIAL: implementation and validation complete; cold-load/GPU targets unmet**.
Lossless native compact/NDGB transport, versioned source/readiness reuse, exact
hull-work reuse, prepared CG primitives/lazy indexes, ordered optimistic saves,
inactive UI gates and lazy connectors remove repeated work. Base authoring stays
separate from overridden display Designs. Source failure/retry and accepted API
snapshot provenance are regression-pinned; independent reviews are clean.

Final release Benchy (seven sources, 462,002 nucleotides): 34.203 s navigation /
29.669 s import→paint, 33.0 ms first Full, 93.8 ms Beads, 76.4 ms Cylinders,
35.4 ms restored Full. All seven close, 91,752,688 triangles/35 calls, steady Full
21.075/21.597 FPS; Cylinders 59.460. Final hinge500 (one repeated source):
10.481 s navigation / 6.119 s import→paint, 485.2 ms first Full, 1,058.8 ms Beads,
689 ms Cylinders, 205.8 ms restored Full. All 500 close, unchanged camera/LOD,
1,517,472,000 triangles/five calls, Full 2.363/1.855 FPS; Cylinders 59.210.
Both have no errors, Design PATCHes or context loss; only Benchy startup geometry
has a busy overlay. Hashes and cleanup pass. These are single document/browser/
source-cold runs, with actual option click→rendered frame excluding menu travel;
they are not compositor/input-to-photon or repeated-median measurements.

The release hinge first-Full screenshot shows Cylinders selectors despite Full
store/renderer evidence. This cause was not reproduced: the separate controls
run checks all 500 row selectors after every phase with zero mismatches and a
Full screenshot. Its 5.964 s import / 233.8 ms Full remains diagnostic; primary
release values above are retained. One hinge readiness GET is pending at close;
backend cancellation is absent. The intermediate readiness profile is still
39.604 s after map/flatten reuse, before lifetime cleanup. No claim that cold
readiness, GPU scale, or screenshot presentation is solved is made.

Final frontend: 8,075 passed, one skipped across 697 files / 314.18 s.
Post-fix smoke: 23 passed / 2.6 minutes. Final FAST: 10,603 passed, 22 failed,
21 skipped, four collection errors / 191.09 s pytest / 203 s guard. Failure/error
IDs are identical to baseline; zero individual timing violators remain, but the
203 s aggregate exceeds 90 s. FULL deferred notice is retained verbatim in
`docs/audits/assembly_loading_performance_20261013.md`; budgets/markers unchanged.
Scoped Ruff passes 23 changed backend/test files. Native gate and diff clean;
`main.js` net −2. Aggregate lint retains two pre-existing unused imports; memory
lint retains four unchanged-file errors/60 warnings. Focused counts, overlap,
exact transport/hull parity and commands are in the audit.

Final cleanup preserves exact 205 project-store paths, five document IDs and
nine original source hashes; all test prefixes and bridge credentials are empty.
All 109 frozen app/test hashes match, with no added/removed scoped files. Final
measurements, controls diagnostic and smoke are complete; earlier runs remain
checkpoints. Reopen count: 0. PARTIAL reflects remaining performance limits and
the unresolved screenshot observation, not unfinished acceptance work.


2026-10-13 — ISSUE-76 fixed for normal-launch integration. Root cause: the optimized
viewer and final recorder were validated through a private diagnostic launch, while
the ordinary backend still selected the pre-work executable without the capture
binding. The new torso recording therefore exercised the old path. The failed
assumption was that a private runtime success implied ordinary user launch was
deployed; exact executable/capture provenance now prevents that confusion.

Owner-controlled configuration selects the versioned Archive build and capture
layer. Normal launch creates inspect/journal resources, uses markers only while
journaling, preserves physical haptics/Desktop/touch input, reports fresh recorder
readiness, and requires valid diagnostics before claiming completion. No scientific
geometry or current document content changed; Join regression evidence is retained.
A normal-menu recording and final physical-inspect recording each saved 179 final
images, zero drops, with full pixel and durable direct-I/O audits. Final calibrated
decoding joins all 716 eye images to strict CRC/full-session/eye/frame identities:
179 unique consecutive IDs per eye per clip, no repeats/gaps/regressions, both eyes
matching. Wide ROI and first tight-ROI failures remain preserved. The bounded
component filter skips only already subminimum components before the same 64-cap;
all other thresholds are unchanged. Menu frame 0 alone calibrated the tighter ROIs;
178 later menu frames and all 179 physical-inspect frames were held out.

Final viewer 378253/start 96081361 uses native v2 hash 1e830a7f...; original Stick/Flex
source placement restored within 2.4e-7 m, grouped/opaque defaults active, one-shot
restore setting removed. Both controllers were untracked. Browser reattachment is
now independently verified: same PID/session and exact presentation, actual feed
sequence advances, unchanged geometry payload/scientific export, and Help's Exit VR
toggle enabled. The stale restore dialog was cancelled without reimporting content.
NADOC is now foreground; desktop 3D during VR retains its original true setting.
Earlier capture cadence does not certify this combined foreground workload.
SteamVR process and four saved global VR config hashes are unchanged.

101 focused backend checks, four readiness cases, five native v2 checks and 175
tracking/decoder checks plus 24 subtests passed. Initial FAST: 10,830 passed, 14 failed, 8 errors, 92 skipped, 2,500 warnings.
Three Unix-socket failures pass with short Archive paths. Final FAST: 10,832 passed,
11 failed, 8 errors, 92 skipped, 2,500 warnings; pytest 134.82 seconds, guard 137 seconds,
five timing overruns. psfgen and CPD failures remain recorded. Focused success does
not clear broad/full-suite debt. Reopen count: 0.
ISSUE-76 closes the deployment gap only; worn-headset doubling remains MV-44.
Evidence and rollback:
[normal-launch integration](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/launch-handoff.json),
[recording review](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/index.html),
[calibrated identity proof](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/postfix-summary.json),
[test triage](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/test-smart-triage/triage-report.txt),
[rollback](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/rollback-plan.txt),
[browser reattachment](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/browser-reconnect/verification.json).

2026-10-13 — ISSUE-77 investigation checkpoint, OPEN. The user reports that
doubling is substantially reduced, with remaining menu/hover-associated lag.
Request 962531370889719 retains all 179 final presentations with zero capture
drops. The complete bounded-follow decode joins all 358 eye images: 144 distinct
submitted images and 35 reused-image pairs per eye, no unknowns/gaps/regressions.
The original fixed-ROI 313/358 joins and 22-pair lower bound are retained. The
retrospective follow trial changed no CRC, contrast or bit/geometry thresholds;
it does not constitute a separately acquired validation clip.

The longest measured input/actions stage is 1.61 ms versus 20.88 ms inside
xrEndFrame. All 242 journal rows have head/hand tracking flags 15, which excludes
no unflagged jitter. Both menus are logically open with varying visible coverage.
This evidence locates host waiting without proving its cause; older journals
have no per-frame hover/haptic timings. Native inspection identified synchronous
event-triggered haptic calls, hover-sensitive texture caching, backdrop copies and
frosted shading as measurable pathways. No behavior/performance fix was applied.

The new bounded capture-only diagnostics and summarize-interactions reader expose
actual API dispatch/results, hover changes, texture/cache work and per-eye menu/
backdrop host spans. Missing legacy fields, truncation, overflow and clock errors
remain explicit. Haptic dispatch does not independently establish actuator motion;
host GL time is not GPU time, and draw counts are not on-screen coverage.

Six native checks passed, including actual GL hover/cache changes and OpenXR
dispatch/result spies; 45 reader tests and 69 marker tests passed. Normal launch
deployed native SHA256 65bcd41e1de02d1d6271c19a1aa7d04683087358eb0dd78a17d4eb282cb8a4d3
as physical-inspect viewer 545874 with the existing compositor. The real browser
reattached; scientific data and restored placement are preserved. Closed-menu
recording 963838453284914 saved 179 frames, with 288 diagnostic journal rows,
zero UI clock calls/errors/overflow. The first check mistakenly required positive
UI clocks; that failed assertion is retained, then corrected without recapture or
native change. This is a zero-activity integration check, not live physical hover
validation. The reload closed the menus and did not restore their previous positions.
Reopen/place them for a new worn-controller reproduction; ISSUE-77 and MV-44 remain
open. Existing broad-test failures and timing-guard debt are not cleared.

Evidence: [native audit](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-audit.json),
[complete identity proof](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json),
[native freeze](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-freeze.json),
[closed-menu live check](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/verification.json),
[retained initial verification failure](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/initial-verification-failure.json).

### ISSUE-78 — VR Join duplicate preview lifecycle (2026-10-13)

Fixed in `vr_join.js`; no `main.js` growth. Root cause: duplicate preview event →
unconditional checking publication → unchanged transform deduplicated → no new
validation → Apply stayed disabled. The earlier browser dispatch test omitted
this native event order; physical playback exposed it. Added a failing regression
then reused the valid result for an identical current pose. Full frontend suite:
7,906 passed, one skipped. Broader validation and frame-rate limits are retained
in `.development-artifacts/vr-join-20261013/verification-summary.json`.

### ISSUE-97 — Exact grouped Ball+Stick rendering (2026-10-15, physical validation pending)

Root-cause chain supported by measurements: dense exported atom meshes → costly
small hardware instances despite exact indexing → GPU frame cost around 13 ms →
application images reused at approximately 45/90 Hz → speed-dependent temporal
landmark splitting in the user's recording. Grouping eight indexed instances
cuts the measured live GPU cost to approximately 8.5 ms and raises mean app cadence
to 87.343 Hz; occasional missed refreshes and physical confirmation remain open.

Failed hypothesis: plain vertex indexing alone did not materially improve live
cadence. Offline blend/culling/normal simplifications did not give a useful isolated
gain; only exact grouping was promoted. A diagnostic wrapper also disconnected
the browser, causing competing desktop rendering and inflated timing. That sample
is retained separately; configuring the actual ELF and reattaching the same viewer
restored the valid measurement condition. No SteamVR setting was changed.

Implementation is in `view_indexed_mesh.hpp` and View Tools stream/render wiring,
with bounded derived storage and fallback. Eight native tests passed without skips:
34 grouped exact color/depth/stencil/ID comparisons, 12 fallback comparisons and
75765 ordered vertex records; ordinary indexing and previous shader/group tests
also pass. Fifty tour checks passed. Live scene and browser were verified, and the
user was asked for the fresh two-second torso capture. GPU OOM cleanup is statically
reviewed, not a forced live-driver failure test. `main.js` LOC delta: **0**.

Evidence: [.development-artifacts/vr-temporal-fix-20261015/index.html](.development-artifacts/vr-temporal-fix-20261015/index.html).


2026-10-14 — ISSUE-81 root cause: variant-blind `getattr` in two full-history scans repeatedly invoked Pydantic missing-field handling; the cluster-restoration helper additionally copied an unchanged object. No speculative algorithm replacement was attempted. The pre-existing benchmark first required a response-contract adapter repair; its frozen reconstruction functions remain unchanged. The unchanged timing gate and all 14 full-output comparisons pass after type discrimination. Evidence is in the feature-history audit directory.


2026-10-15 — ISSUE-82: broad regression exposed five refinement failures because an extracted helper still read/changed the active session; scaffold selection now sequences its input design only. Native lifecycle tests exposed missing linker-patch/loop-clear log variants and framed-copy frame references; those are recorded/preserved. Generated recovery exposed an earlier absolute membership setter overwriting a newer extrusion snapshot; payload-aware membership restoration fixes both recovery modes. A small CPD conversion took ~70 s; its method is explicitly unverified and blocked before the solver on proof paths, rather than weakening deadlines or claiming snapshot replay is proof. See feature-history implementation audit for remaining scope and measured validation.

2026-10-15 — ISSUE-83: extracted `part_replacement_transaction.publish_replacement`
under the existing state lock. Failed prepared-model commits now restore the exact
source object, bounded stacks, revision and request context, including cancellation
after revision publication. A ready repair remains available for a successful retry.
Eight transaction and fifteen repair-job tests pass. One undo copy remains; no
geometry computation or additional proof was added to ordinary publication.

2026-10-15 — ISSUE-84: raw-envelope budget checks omitted optional fields that
Pydantic adds on serialization. A load-admitted draft therefore could not
survive the unchanged snapshot/load validator. Admission now also checks the
canonical stored form; no size limit or snapshot validator was weakened. The
repro preceded the fix (three red / one control), then all 35 schema, 18 API
and 16 persistence cases passed. Retained-draft performance is measured in a
separate rerun; the aborted benchmark is preserved rather than called a pass.

2026-10-15 — ISSUE-85: bind every publishing evaluation to the actual host
session captured alongside source/revision. A new session cannot reuse the old
handle even if its public revision and source object match. Trusted guards use
a noncreating session lookup so stale publication cannot reopen a closed tab.
All 21 session cases and the affected ordinary lifecycle files pass. This closes
the evaluation lifetime gap; it is not the broader strict automation policy.

2026-10-15 — ISSUE-86: the actual JavaScript action/JSON transport collapsed
authored integer-valued floats, contradicting the planner's exact old-value
comparison. The two HTTP regressions failed before the fix (2.71 seconds,
HTTP 409 for diameter and pose). A bounded canonical JSON encoding now travels
with the displayed old value and restores it before action construction; it
persists through draft reloads. This encoding grants no authority: unchanged
strict conflict/identity checks and native regeneration still decide acceptance.
Malformed, duplicate-key, nonfinite, over-depth, boolean/number and aggregate
budget cases are covered. All 280 focused codec/transport and related repair
regressions pass; full desktop integration remains separately tracked in ISSUE-87.

2026-10-15 — ISSUE-87: desktop repair integration assumed the commit API returned
a full model, but the actual contract returns only a publication receipt. Retain
that receipt separately from display refresh and bind all refresh reads to the
original document/revision/session before syncing geometry. First full Vitest
also exposed a null prior-summary dereference in the new metadata adapter (six
failures; 8,155 passed and one skipped). Corrections and focused regressions are
in progress; no green integration result is claimed yet.

2026-10-15 — ISSUE-88: replaced lossy document-cache filename sanitization with
exact bounded identity admission. Unsupported IDs cannot alias valid files or
address the cache root/parent; strict HTTP refuses them before body acquisition.
Autosave reports unsupported IDs and continues valid documents. Baseline29failed/
9passed; final122 focused cases pass. Existing files and pruning are unchanged.

2026-10-15 — ISSUE-89 identified an admission/execution mismatch: dependency and
scoped replay exclude inert generator annotations, but ordinary strict native
builders still receive them. The isolated valid-gold cold-proof dossier failed
five cases with 11 controls passing in 3.68 seconds, including a real spawned
worker. The shared execution boundary now excludes only `_generator` after the
existing scope handoff, retaining recorded metadata and all input/identity
guards. Corrective validation passed all 16 annotation cases and 377 related
invalid-input, draft, source, scope and native-particle regressions (393 total).

2026-10-15 — ISSUE-87 fixed: committed and uncertain publication survive failed
display/transport, exact original-document revision/session checks guard refresh,
and default-document null maps only to the explicit server `__default__` sentinel.
Final86 focused tests and full8,181 passed/one skipped (708 files,309.16s).
No app/smoke/headset validation; MV-45 remains pending because Archive is absent.

2026-10-15 — ISSUE-91 API correction: physical input freshness is now explicit
in oxDNA/NAMD list/detail responses. A matching legacy partial fingerprint stays
unknown; known comparable differences are stale. No extra model/file work or job
mutation. 59 focused cases pass; obsolete legacy MD fixture repaired with paired
legacy/native assertions. Shared frontend labels subsequently passed 39 focused
and 8,192 full cases with one skipped (`6abb5dde`; API `764b413b`). Full receipts,
projection qualification and MV-46 app validation remain open; no app check is claimed.

2026-10-15 — ISSUE-90 pending NP deletion: the original global applied-version
sync erased an unrelated legacy direct-binding marker. The parent recorded the
49-case pending-native dossier red (31 failed/18 passed, 3.29 seconds), including
the actual deletion defect. Pending deletion now removes only its selected
version in native and compatibility paths. Native metadata inputs, owner checks,
atomic recording, nested ownership budgets and context/failure regressions passed
the parent's final 66-case run (4.20 seconds). Editing regressions passed 95 cases
(3.58 seconds), including seven identity-policy cases: 161 distinct green cases.
Thirty-repeat measurement passed all ten cells/five native cold proofs, with
cleanup; latency remains unqualified (native request/lock/light maxima
88.57/82.35/86.30 ms). Initial larger-fixture cold capture refusal remains in the
evidence. No app validation is claimed. Applied geometry is unchanged.

2026-10-15 — ISSUE-92 tests-first application ownership correction: root recorded
eight failures in 2.85 seconds across stale active constraints, unrelated legacy
binding preservation, surface-carrier identity and bound-handle selection. The
root cause is duplicated lifecycle state maintained separately from native
relocation: the geometry/domain moved, while the surface carrier and inactive
constraint fields did not; a global version-only sync also overwrote unrelated
owners. The narrow correction updates only affected ownership, clears inactive
constraints and explicitly excludes bound handles from free selection. Existing
register/relocation/restoration formulas and numerical pins are unchanged. Root
validation passed 181 distinct cases, after strengthening one stale status-only
assertion to the existing complete typed 422 diagnostic. No new native applied
contract or app check is claimed. No alternative geometry fix was attempted.

2026-10-15 — ISSUE-93 private DNA comparison cleanup: a shared-template disposal
regression exposed Three BufferGeometry's aliased userData on a geometry clone.
Detaching the private clone's metadata preserves the shared native template.
Added concurrent ordinary-scene identity/matrix/metadata survival assertions;
migrated obsolete constructor regex checks into actual buffer behavior. The
corrected 11-file run passed 195 cases in 3.97 seconds; real Python→Node packets
also passed. Full frontend passed 8,291 cases (one skipped) in 314.43 seconds; resource and
app qualification remain pending.

2026-10-15 — ISSUE-94 strict cold DNA decoding: the actual-byte benchmark found
that nested Design validation leaves Helix's forward-reference serializer deferred
until direct construction. A fresh-process minimal diagnostic reproduced the
MockValSer failure and confirmed schema initialization resolves it. The strict
boundary now resolves the existing schema once; pinned model/engine files remain
unchanged. Independent cold serialization, spawned DNA proof and controlled decode
cancellation pass within 115 distinct focused cases (one incomplete expected
proof fixture corrected). Actual HTTP measurements remain pending.

2026-10-15 — ISSUE-95 oxDNA copy input preservation: add the existing packaged
sequence-parameter filename to Copy Job's file set. Tests verify exact independent
bytes, stage rendering and honest legacy absence alongside the existing seed,
protocol and lineage contract. Initial present-file test failed as expected; both
copy cases plus 42 related physics/freshness cases now pass. Complete physical
input receipts and immutable preparation remain separate work.

2026-10-15 — ISSUE-99 focused grouping fix: ordinary and headless group creation
now always publishes one versioned `cluster_create` entry through the shared
pure builder and existing lock-owned replacement transaction. `log=False` is
accepted but cannot suppress recording. Historical cursor/sub-cursor input
refuses explicitly before allocation rather than silently truncating history.
Source, validation, undo, revision and failure checks stay inside one owning
lock; no nested `state.set_design`, full history proof or topology reconciliation
is added. Missing legacy roots remain unverified. The first green focused run passed
101 cases with 108 warnings in 5.57 s; the group file then passed 16 cases with
16 warnings in 2.88 s after adding the nicks→group→nick ordering regression.
There are 102 unique passes across these overlapping runs, not 117. Two old
tests requesting unlogged grouping were updated, retaining an explicit removed
receipt negative. `main.js` delta is 0. No app, broad-suite or latency
qualification; MV-48 remains open.

The same checkpoint reproduces ISSUE-100 rather than fixing it: ten bend/twist
tests include direct-edit controls and explicit assertions that the current
preview sequence removes the committed overlay before Apply, and that Cancel's
seek changes undo/redo. Apply refuses the resulting source correctly. The next
G1 increment must isolate preview state; do not weaken source proof to accept
the polluted document or preserve these characterization expectations as the
desired user contract.

2026-10-15 — ISSUE-101 forced-ligation recording: move source selection, endpoint
label/response scope and native building into one lock-owned minor transaction.
The shared builder preserves geometry and the recorder still snapshots,
reconciles and retries once. The red dossier reproduced three defects; all 107
related cases, including 14 new cases, now pass. The combined run's two preview-fixture
failures and corrected rerun remain in the
[continuation evidence](docs/audits/feature_history_20261014/validation_geometry_integrity_continuation.json).
No app, broad-suite or performance claim; MV-48 remains pending, `main.js` delta
is zero, and nick/resize/auto-crossover follow-ups remain open.

2026-10-16 — ISSUE-105 intake (open): historical bend/twist group controls do
not reliably update affected-helix membership. The private preview retains
native behavior and advertises group retargeting as unavailable. G2 must use
the existing prefix plane/scope resolvers and align preview, publication and
cold replay; this checkpoint does not change molecular calculations.

2026-10-16 — ISSUE-105 backend correction and gated history editor: actual group
selection changes now use existing selectors against the owned prefix. Unchanged
groups preserve historical explicit membership, and old commands replay unchanged.
The complete private control validator, plane editor, popup and viewport connect
through the real feature editor behind a default-false gate. Failures preserve
inputs, reversed inputs overwrite prior drafts, and explicit status/refresh
actions avoid a second publication. Native source tests exposed ISSUE-106's
pre-existing invalid all-members grouping; it remains separately open for a
compatibility-aware correction. See [checkpoint evidence](docs/audits/feature_history_20261014/validation_deformation_history_editor.json).
Both rollout gates remain closed and MV-48 remains open; no desktop or latency
result is claimed.

2026-10-16 — ISSUE-108 intake (open): native crossover growth reconstructs
`Helix` with an incomplete field list; batch growth can use original opposite
endpoints outside the final domain's range. Native controls reproduce the lost
metadata. U9's private organization adapter refuses the affected case before
native work; algorithms and legacy behavior are unchanged. This is containment,
not a fix or new milestone. The 752 focused U9 passes and remaining acceptance
are recorded in [U9 evidence](docs/audits/feature_history_20261014/validation_group_geometry_lineage.json).


2026-10-16 — ISSUE-110 Move Apply acknowledgement: extracted explicit-placement
commit retains refused/newer input and returns accepted legacy partial results.
Organized parts use one native batch publication with one undo/revision and
matching geometry, avoiding a second client transform. Current failures retain
the editor; reset retires old pending state. Actual factory/API/tool/native tests
and observed failures are retained in [U12 evidence](docs/audits/feature_history_20261014/validation_group_placement_ui.json).
The early InvalidURL factory mock failure is not a claimed behavior reproduction.
Public gates remain false; desktop/latency and earlier move editing stay open.


2026-10-16 — ISSUE-111 visibility queue review correction: bind rollback to each
save's dispatch revision and isolate pending counts/hydration by reset generation.
Regression cases cover successful earlier save followed by latest rejection and
same-ID reload while a prior save is held. No persisted schema or topology change.
See U12 evidence; this correction predates release and adds no milestone credit.

2026-10-16 — ISSUE-112 deformation opening lifecycle: reset during held Prepare
now retires the local opening immediately. The observed-open transition excludes
the controller's initial invalidation, and the generation rejects late old
responses/finalizers after a new tool opens. Meaningful failing regression and
passing focused correction are in [U13 evidence](docs/audits/feature_history_20261014/validation_deformation_creation.json).
This changes no geometry formula and earns no separate milestone credit.


2026-10-16 — U14 visibility integration: ISSUE-113 removes per-strand geometry
rescans by using the existing effective mask; ISSUE-114 applies endpoint masks to
cached saved Join lines without rebuilding them; ISSUE-115 settles visibility
before explicit Save/export and guards document ownership through asynchronous
reads/writes. The unused duplicate client exporter is pruned. ISSUE-111 reopened
once: two refused queued writes restored an unacknowledged intermediate state;
rollback now uses the last accepted checkpoint. Earlier one-success tests did not
cover this failure combination. Tests-first failures and final evidence are in
[U14 evidence](docs/audits/feature_history_20261014/validation_group_visibility.json).
No additional milestone credit or desktop qualification is claimed.


2026-10-16 — ISSUE-116 schema compatibility correction before U14: default model
serialization would add an empty presentation list to old sealed bytes. Preserve
the old canonical encoding with explicit empty-only field omission and the old
strict empty-state digest after validating the new field. Three observed red
canonical/stored/spawned recovery cases guard the fix; no relaxed decoder or
rewritten source evidence is used. This was discovered by tracing the actual
recovery equality check, beyond ordinary .nadoc roundtrip tests.


2026-10-16 — U16 / ISSUE-119: output-identity preservation also retained a derived
continuation source receipt after source input changes. Bind the edited receipt
to the proved prefix after identity preservation; never infer it from the latest
displayed geometry. Shared owned publication and typed reference failure keep
rejected edits atomic. The seven-family editor is one FH-21 milestone, not extra
credit for this fix or the shared-host extraction.

2026-10-16 — U17 / ISSUE-120–122: the gated Sweep history editor now distinguishes
native input replay from legacy snapshot rebasing. It identifies typed downstream
nick dependencies and preserves rejected drafts. Shared Apply rechecks its final
deadline after preservation. Private picker ownership blocks hidden legacy
authoring and prevents old cleanup from hiding a newer view; preparation can be
cancelled before the panel opens. Existing molecular algorithms and legacy
recovery contracts are retained. These corrections earn only the fixed FH-22
milestone when its full software acceptance passes; desktop remains FH-27/MV-51.

2026-10-16 — U18 / ISSUE-123–124: share strict placement/nucleotide/reset history
binding, correct the consumer-reference identity role and stale reset receipt,
and preserve exact typed failure attribution with atomic publication. Native
replay reuses its occupancy predicate without an added successful-target scan.
The standard regression command exposed an import-time randomized Sweep test ID;
replace it with a deterministic value. Archive-backed collection and FULL debt
remain explicit. FH-23 stays open; these fixes add no completed milestone.


2026-10-16 — U27 / ISSUE-136–137: Fine Routing entry adapters computed before
source ownership or twice, and native input errors escaped precise row attribution.
Use the existing locked recorder once and attach diagnostics at the actual
executing command. Keep native mathematical behavior, source-bound edit publication,
no-op handling and undo/redo intact. This is within FH-24, with desktop/performance
qualification still assigned to FH-27; no additional milestone is counted.


2026-10-16 — U27 / ISSUE-138: source-bound geometry alone did not guarantee correct
browser recovery. Stable feature IDs survive upstream edits, so a partial reply
must not backfill regenerated suffix bodies from the old client cache. Eight red
HTTP cases cover the existing routing/extrusion/pattern response families; use
full regenerated history for owned edits, preserving ordinary append slimming.


### U28 — ISSUE-139 combined Connect source alias

- [x] Observed real blank-version naming mutate source records through Pydantic
  deep-copy update values. Detach the supplied version records before naming.
- Native complete-output parity covers all eight finite types; source isolation,
  default naming and real publication failure retain canonical/held-source state.
  Focused regression:111 passed,14 warnings,5.96s. No molecular or public gate change.


### U31 — ISSUE-140 direct replacement owner cleanup

- [x] Reproduced retained Duplex records across eight native replacement cases.
- Root cause: replacement teardown accounted for bindings but not the later
  unequal-length Duplex relocation owner; sequence edits also preceded restore.
  Share complete restoration cleanup, preserving the existing native helpers.
- Expanded regression20 cases; six-file regression157passed/25warnings/7.89s.
  Initial fixture used non-existent direct type strings; corrected before the
  bug reproduction. No alternate molecular hypothesis or new algorithm proposed.
  Direct replay remains incomplete; desktop/visual validation remains deferred.


### U35 — ISSUE-141 observed, not closed

Native upstream length editing exposes a literal conditional binding reference
in a downstream replacement contract. Failure is correctly attributed and the
source is preserved; an explicit isolated recipe correction verifies in a child
process. Root cause is freezing conditional child ownership rather than selecting
a stable logical creator. Onshape query/repair research informs the next contract
review; no automatic retargeting or saved-contract reinterpretation implemented.
This remains within existing FH-25/FH-26 exits, with no milestone credit.

### U36 — ISSUE-141 prevention in new versioned recipes

Direct v2/linker v4 use stable creator selectors with strict current-prefix
ownership validation. Legacy literal recipe repair and public rollout remain
open; no automatic reinterpretation of saved inputs. See the ordinary connection
completion plan for evidence and remaining exits.

### U37 — applied metadata recording; ISSUE-142 identified

Version2 metadata commands record applied create/patch/delete and exact pair flag
changes without touching materialized geometry. The current UI's non-atomic
Unapply/delete sequence and omitted Duplex teardown are tracked as ISSUE-142,
not claimed fixed by metadata support. Existing FH-25 scope and rollout gates
remain unchanged.

### U38 — ISSUE-142 atomic disconnection implemented privately

New exact-pair command/HTTP transaction and shared UI controller restore native
owners, clear pair flags and optionally delete the chosen saved version in one
undo. No admitted failure retries through legacy writes. Existing Apply retains
its broader endpoint-conflict semantics. Public correction awaits MV-54 and
coordinated gate rollout; the unused local conflict-teardown helper is removed.

### ISSUE-146 — Part recipe repair launcher restored

[x] Moved the existing launcher out of the configuration-only toolbar. Two real
Sweep/Extrude source-reference repair workflows pass through undo/redo and reopen;
no new repair panel or transaction owner.

### ISSUE-147 — Repeated reference repair preserves replay accounting

[x] Selection and repair tracking callbacks now run for every planned row even
when a prefix was previously cached. Repeated-proposal regression passes.

### ISSUE-148 — Atomic linked-member pose transport

[x] Complete Move/Rotate stages every owner pose before carrying existing member
poses. Common-end movement passes; differential-end movement still refuses
without source mutation. Native4, compound31 and constraint16 regressions pass.

### ISSUE-149 — Complete pose refresh on undo/redo/seek

[x] Changed residue poses now use the existing full native display response,
refreshing site frames and inserted-base geometry rather than applying a cluster
or compact-position delta. Host6/render-diff22 and actual browser1 pass.

### ISSUE-150–153 — Fine Routing desktop completion (2026-10-25)

[x] Source-bound routing feedback now marks the failing child and blocked suffix,
then clears on retry/Cancel/reset. The ordinary18HB uses established CAD source
capture capacity and bounded record/domain versus expanded-JSON accounting.
Seamless fallback traversal is deterministic across Python hash seeds. Nested
forms use a responsive grid so every control stays within the dialog.
Native focused283 +large2 pass; final all22-form lifecycle/layout and visual23pass,
with32 distinct app cases across applicable runs. Broader regression results live
in the [tool plan](docs/audits/feature_history_20261014/fine_routing_history_editor_plan.md).
No native builder, phase constant, geometry lock or golden changed; `main.js` delta0.

### ISSUE-154–156 — Complete organized-placement movement (2026-10-25)

[x] One complete owner command carries saved member poses once, publishes them
with the placement poses and records complete recovery for history seeking.
Menu/shortcut activation retains multiple selected placements. HTTP undo/redo/reopen
uses the existing reviewed lifecycle names. Native rigid-coordinate, atomic
refusal, cold-replay and HTTP regression checks pass. Full evidence and rollout
limits remain in the Move/Rotate plan; the production gates remain off.

- 2026-10-25 — ISSUE-157 [x]: ordinary multi-cluster Apply uses one complete-pose publication. Backend8pass, focused frontend79pass, real posed-insert app1pass. Final qualification is tracked in the Move/Rotate plan. `main.js` delta0.
- 2026-10-26 — ISSUE-158 [x]: cluster undo/redo on posed designs returns full native geometry even with unchanged pose records. Recovery precedes topology-patch selection. Regressions23+9pass; final creation/undo/reopen app5pass. Evidence in the Move/Rotate plan.
- 2026-11-01 — ISSUE-159 [x]: native asset publication preserves the existing save identity and coordinates asynchronous saves; focused frontend19pass and ordinary biotin/generated save-reopen flows pass. Final aggregate checks are recorded in the feature-history handoff. `main.js` delta0.
- 2026-11-01 — ISSUE-160 [x]: unchanged-budget generated capture and complete scalar-atom undo copies;145focused checks plus18 final model-copy checks pass after the red lifetime regression. Final maximum HTTP qualification:29/30 captures,30/30 publications, one safe clock refusal; generated app edit/reopen/cold proof passes. Failed profiles remain retained; full evidence is in the feature-history handoff. `main.js` delta0.

- 2026-11-01 — ISSUE-161 [x]: diagnostic history restores recorded molecular references and source placement owners; changed references force a full render refresh. Safeguard/recovery regressions15pass; six real parts pass88 history positions and the adverse Current→Candidate atom-view transition. No molecular placement or detector changes. `main.js` delta0. Evidence: `.development-artifacts/fh27-process-repair-20261101/`.

- 2026-11-02 — ISSUE-166 [x]: precomputed ring triangles and bounded vectorized tests reduce the terminal-linker scan from 31.76 s to 0.43 s with identical reports. Checks over 1 s show a spinner and measured bond percentage; stale work cancels and clears progress. Focused 55 backend / 27 frontend pass; SMART FAST 19,964 passed / 19 skipped (FULL deferred), frontend 9,545 passed / one skipped, isolated smoke 23 passed. Actual app progress/cancellation and screenshots verified; owned workspaces and screenshots removed. `main.js` delta0. Evidence: `.development-artifacts/piercing-performance-20261102/`.

- 2026-11-03 — ISSUE-167 [x]: cadnano crossover indicators resolve neighbors by lattice frame and local cell, avoiding Sweep/source aliasing. Frontend 9,601 passed / one skipped; four actual staple/Shift-scaffold clicks across original/swept frames passed, including feature recording, unchanged coverage, undo/redo/reload; smoke 23 passed; lint passed. User visual review pending under MV-55. Autoscaffold changes deferred as requested. `main.js` delta 0.

- 2026-11-03 — ISSUE-168 [x]: attached Sweep segments share source helix rows and labels in cadnano. Native segment/frame identities and feature history remain intact; bp picking and row operations resolve the appropriate members. Focused 12 passed; four real editor cases passed (row alignment, crossovers, coverage/history, undo/redo/reload, nicks and gutter reordering); frontend 9,609 passed / one skipped; smoke 23 passed; lint passed. `test.nadoc` is unchanged and resolves to ten rows. User review: MV-56. Autoscaffold deferred. `main.js` delta 0.

- 2026-11-03 — ISSUE-169 [x]: end-turn selection checks final normalized crossover sites against both staple spans and tries outward alternatives; matched far ends retain a common translation. `test.nadoc` routes one scaffold with the failing −2 turn replaced by −12. FAST 19,994 passed / 19 skipped (FULL deferred), focused clearance 10 and continuation 25 passed, browser routing/undo/redo/reload and visual checks passed, lint passed. Test artifacts removed; no user structure saved.

## ISSUE-170 — Joint crossover drag snapping (2026-11-03)

Selected crossovers are validated as one proposed endpoint edit, so adjoining
crossovers no longer block one another at their old positions. Every selected
arc and attached domain is previewed at the common snapped displacement; release
uses the existing atomic `crossover-move-batch` operation. No crossover tables,
molecular placement rules, or backend authoring commands changed. `main.js` LOC
delta: 0 (both composition roots).

Frontend: 9,613 passed / one skipped across 808 files. Fresh public-command
fixture: batch move, zero occupancy conflicts, guarded publication, reopen and
independent replay passed. Existing fixture republication exposed ISSUE-171's
pre-existing loadout replay mismatch and was refused without writing a file.

Final qualification: three browser canvas regressions passed (each internal
pair separately and both pairs together), with all preview arcs checked and
screenshots inspected. `just smoke`: 23 passed; `just lint`: passed. Cleanup
verified no test workspace files, test project stores, or isolated bridge key
remained; 9,439,400 bytes of preview/Vite scratch removed. Compact evidence:
`.development-artifacts/crossover-group-drag-20261103/validation.json`.

2026-10-20 — ISSUE-98 VR numpad hit planes: an oblique ray aimed at the
rendered 0.070 panel-local button face failed the production hit assertion before
the fix, then passed with explicit surface depth. Generic numeric controls also
now precede their disabled background rows. No ray thresholds or target sizes
changed. Existing simulation tour checks Cancel without seeking and Apply popup
closure. The user's active viewer is preserved; live four-profile and through-lens
verification are deferred to MV-48. Frontend main.js delta for this fix: 0.

ISSUE-98 validation: rebuilt deployed viewer; native simulation-panel,
simulation-trajectory and sidebar-unit CTests all pass (3/3). Placement audit,
task Python Ruff and whitespace checks pass. Additional menu-spacing target
cannot compile: its existing fixture still assigns removed `jobScroll` and
`viewScroll` fields (line 146); no production workaround was added. The first
CTest invocation through the variadic just wrapper lost shell regex quoting;
using the same validation guard directly ran the unchanged selection successfully.
Tour catalog focused validation: 50 passed. No backend/frontend runtime behavior
changed in this popup fix; frontend main.js task delta remains zero.

2026-10-21 — ISSUE-99: bounded immutable VR vertex-template cache and direct current-instance packing remove repeated mesh allocation; settled native style acknowledgements no longer rebuild the desktop display and pause trajectories. Added byte-parity/cache-invalidation and repeated-style regression tests. App validation covers all four CPD isomers and two 24HB jobs; quantitative results and limitations are in `docs/audits/cpd_vr_hitches_20261021.json`. Main.js task LOC delta: 0. Through-lens review remains MV-49.

2026-10-21 — ISSUE-100: overhang-orientation test cleanup now closes menus after deferred listener binding rather than only removing their DOM. Repairs a full-suite teardown exception discovered during ISSUE-99 validation; no application runtime change or main.js growth.

2026-10-21 — ISSUE-101: negotiated absolute transform streaming retains native mesh resources and reuses fenced instance buffers. Exact CPU/GPU/pixel parity regressions and resident CPD/24HB app measurements are recorded in `docs/audits/vr_transform_stream_20261021.json`. Full snapshots remain the compatibility/structural-change path. Main.js task delta: zero. Physical review: MV-50.

2026-10-21 — ISSUE-102: replace tiny per-vector transform reads with bounded 48 KiB blocks. Exact scalar-oracle, malformed-packet and production GL byte/pixel checks pass. Native preparation improves on 24HB but median playback cadence does not; retain as CPU headroom and prioritize broader rendering/publication work over more decoder tuning. Evidence: `docs/audits/vr_final_pass_20261021.json`. Main.js task delta: zero.


2026-10-21 — ISSUE-103 investigation: added bounded GPU group-size sweeps and
post-timing snapshot exports. Fixed diagnostic replay to apply backend camera
rotation and include current dense sphere meshes in probes. App captures, exact
pixel group checks, offscreen negative control and 50 tour tests pass. No measured
case justifies changing production defaults; analytic sphere rendering remains
the substantial next task. Main.js task delta: zero.


2026-10-21 — ISSUE-104: Smooth prepares each pair before a slower, delivery-aware
presentation clock, retaining seven intermediate fractions and exact endpoints.
Eligible sphere/bond groups halve vertex records without geometry/shader changes;
final same-scene repeats improve GPU time by 2.5–4.7% with exact color/depth/ID
parity. Sphere-only packing, smaller indices and reordered triangles did not
establish a consistent gain. Full frontend and smoke pass; production GL tests
cover packed/full buffers, transform reuse and shadow transitions. App measurements
and cleanup are in `docs/audits/vr_gpu_iterations_20261021.json`. Physical review:
MV-51. Main.js task delta: zero.

2026-10-21 — ISSUE-104 publication follow-up: GC callbacks and event-loop sampling
tie a 148 ms pre-handler delay to a 149.6 ms generation-2 collection. A dedicated
server startup factory collects import temporaries and freezes the permanent
startup graph once; later cycles stay collectible. Controlled 60-second upload
maxima improve 160.8→31.8 ms raw and 58.8→26.7 ms Smooth. All four isomers pass
24 atomistic windows; remaining browser request/encoding outliers are separately
recorded. A startup race now waits for the actual SteamVR server pipe. Existing
sessions were not restarted; the factory activates on the next normal start.
100 focused checks and 16 targeted rechecks pass. FAST suite retains documented
chemistry/provenance debt; no guards or fidelity were weakened. Evidence and
cleanup: `docs/audits/vr_publication_20261021.json`. Main.js task delta: zero.


## ISSUE-172 — Preserve native history across master relaxation (2026-11-03)

Root cause: independently developed import paths diverged—native preparation
returned before the new option, while the new manual action assumed snapshot-only
history. Unioning the text conflicts preserved both implementations but did not
compose their recording contracts. Two imported-option regressions exposed the
missing path before the fix; no geometry-algorithm hypothesis was pursued.

The integration adapter composes existing recorded group operations and verifies
replay before publication; manual use retains one undo step and checks source
currency. The old import-menu tests now accept the added options step, retaining
all downstream omission/save assertions. Integration correction `main.js` LOC
delta: 0. Backend FAST: 20,507 passed / 100 skipped; frontend: 863 files,
10,041 passed / one skipped; four browser checks pass. Full-suite debt remains
explicitly deferred. Final smoke and cleanup results live in the
[merge audit](docs/audits/feature_history_merge_20261103.md).

## ISSUE-178 — Frame-aware crossover lookup for swept parts (2026-11-04)

The source bundle and continuation reused lattice cells, and a global cell map
silently retained only the last helix. Candidates now resolve within each frame,
including multiple segments with bp coverage. Both routing commands record the
new lookup semantics; historical commands explicitly retain legacy semantics on
replay. The new recorded regression failed before the fix and passes afterward,
including publication-guard verification of the saved/reopened process. The user's
`test.nadoc` remains unchanged; its separate loadout-history audit failure prevents
agent publication of a derivative. `main.js` LOC delta: 0.

Validation: 18 focused tests pass, including repair of an already legacy-routed
part by a new recorded operation. The guarded four-command review reproducing
`test.nadoc`'s bundle/sweep parameters has 59 source-bundle and 193 sweep staple
crossovers; independent saved-file replay and a browser render check pass. Visual
review inspected the screenshot; all 9,234,271 bytes of isolated review data were
removed. Cylinder graph screening was recomputed; all records remain identical,
with only the changed crossover source checksum updated. Lint passes.

`test-smart` decision FAST: 20,620 passed, 8 failed, 19 skipped. Three change-related
failures were corrected and rerun successfully. Remaining failures concern the
CPD comparison packet and four unavailable-`/mnt/f` filesystem checks. FULL remains
DEFERRED in `.nadoc-slow-pending`. The aggregate runtime gate fired at 485 seconds;
triage found zero per-test budget violators, so no unrelated tests were reclassified
and no limits changed. Compact evidence: `.development-artifacts/autostaple-frames-20261104/validation.json`.


## ISSUE-179 — Smoke setup timeouts found during presentation work (2026-11-10)

Open: assembly scaffold-mesh readiness (20 seconds) and an invisible New Part
name input (30 seconds) failed in the required smoke run. 21 tests passed and
two were skipped. Both failures precede presentation entry. Root cause is not
established; no speculative product fix or timeout increase was made. The local
presentation controller has independent unit and browser coverage. Compact
results: `.development-artifacts/animation-presentation/validation.json`.

Animation sidebar follow-up: smoke 22 passed, two skipped, one failure at the
same assembly scaffold-mesh setup; New Part creation passed this time. The full
sidebar workflow and presentation browser checks passed. Backend FAST initially
reported 20,637 passed and 41 failed: 40 archive-schema failures were corrected
by explicitly retaining the new view metadata, with 137 affected tests passing
on retry; the documented CPD display-contract failure remains. Frontend: 887
files, 10,173 tests passed, one skipped; final focused rerun 37 passed. An actual
browser failure exposed a deferred pose update rebuilding the annotation picker
when disabled controls lost focus; open multiselects now defer that rebuild.
Compact evidence and cleanup audit:
`.development-artifacts/animation-sidebar/validation.json`.

Sidebar polish validation: standard buttons, NAMD-style annotation selection,
font selectors and viewport deselection passed both live browser workflows.
The new reselection regression exposed the debounced saved-document snapshot as
the wrong source for live annotations; display-only subsets now project from the
working controller. Final affected tests: 11 passed. The frontend sweep had
10,174 passed, that one subsequently fixed regression, and one skipped. Backend
FAST: 20,677 passed, the existing CPD display failure, 19 skipped. Runtime triage
found no per-test violators (532-second aggregate run); no limits or test
classifications changed. Smoke: 22 passed, two skipped, the known assembly setup
timeout. Cleanup verified. Evidence:
`.development-artifacts/animation-sidebar-polish/validation.json`.

### ISSUE-179 — Live oxDNA jitter (2026-11-09)

Root cause: an independently updated burst count was used as frame identity,
while the published coordinate snapshot lagged behind it; deduplication could
consume an ID before its positions existed. The earlier assumption that spline
lookahead alone would absorb arrival jitter was insufficient. Added atomic frame
publication, a four-frame jitter reserve, bounded queue, cadence filtering and
start-to-start polling. Reduced curve-allocation and per-subframe display setup
work. Timings are available in the Live popup. Native visual confirmation remains
MV-59; software validation details are retained under
`.development-artifacts/live-jitter-validation.json`.


## Zoom volume persistence and animation output (2026-11-10)

Root causes: `zoomStep` existed only inside each camera controller; documents stored
no inset definitions; animation encoders copied only the main render target; inset
DOM lived outside the fullscreen subtree. Added display-only part/assembly metadata,
serialized writes and stale-response protection, saved-lens restoration, scene-scoped
export compositing/readiness, and viewport-owned overlays. Browser checks also found
that disabling zoom during builds dropped rapid clicks; lens adjustments now remain
available while meshes build. No molecular authoring or main.js logic was added.
Validation: `.development-artifacts/zoom-volume-persistence/validation.json`.

Persistence/export validation completed: 10,290 frontend tests passed / one skipped;
85 focused backend checks and both browser workflows passed. Smoke: 22 passed,
two skipped, existing assembly scaffold-mesh setup timeout. The earlier Close Session
and Square-lattice checks passed this run. FULL backend sweep deferred; cleanup verified.

## Inset title typography (2026-11-12)

Zoom-volume names now appear centered in the top border bar without the visible
movement hint. Inset options share annotation font families and size presets;
settings persist independently per inset. Header height, loading overlays, bottom
positioning and photo/video compositing follow the selected size. Existing files
retain 12 px defaults. Validation: 10,397 frontend tests passed, 27 focused tests,
lint and browser typography/export/save-reopen passed. Smoke had 23 passed/2 skipped
and an assembly fixture timeout that passed serially. The browser fixture now waits
for serialized metadata writes before saving its audited structure. Evidence:
`.development-artifacts/inset-titles/validation.json`; visual follow-up MV-63.

## Visualization card collapse and View Actions alignment (2026-11-12)

Representations, Coloring and View Actions now use native keyboard-accessible
collapse buttons with remembered per-card state and shared sidebar-copy updates.
View Actions uses consistent compact buttons, neutral and selected colors, aligned
borders and single-line labels, including section-plane controls. Removed the old
Reset Camera margins that broke grid alignment. Browser validation caught and
resolved chevrons entering accessible names and Reset Camera wrapping at the
standard width. Validation: 10,398 frontend tests passed, 18 focused tests, app
exercise and lint passed. Smoke: 23 passed/2 skipped; assembly fixture setup timed
out and passed its isolated retry. Evidence: `.development-artifacts/visualization-cards/validation.json`.
Main.js LOC delta: 0; visual follow-up MV-64.

## ISSUE-196 — Shared part-editor display geometry ownership (2026-11-14)

Crossover lines previously kept independent native endpoints and simulation
buffer writes. A visibility refresh could overwrite the frame; callers also had
to remember separate insert, extension, and flexible-link refresh methods.

The part editor now owns a stable molecular scene root and an exact-key display
frame. Observed geometry mutations publish ordered producer/consumer updates;
simulation frames, animation batches, residue previews, copy identities, extension
sites, inserted bases and flexible/linker positions use that owner. Removed the
arc-specific simulation, cluster, deformation and spacing update APIs. Whole-model
visibility inherits through the root; representation gates remain per layer.
Assembly instancing and physical atomistic/surface pipelines remain separate hosts.

Validation: 956 frontend files, 10,542 tests passed / one skipped; lint passed;
memory hygiene has zero errors (16 existing warnings). Real renderer tests cover
amplification, partial-frame replacement, exact copies/extensions, inserted-base
previews/reset, unfold, transforms, visibility and display rebuilds.
Read-only browser checks passed for 6hb_test and VoltronCoreArmV2 with saved oxDNA
job 34992198f43a. Voltron: 3,050 endpoint comparisons, max error 0.0000153 nm;
deliberately displacing the line buffer failed the audit by 5 nm. Real line pixels
were verified with the helix meshes temporarily hidden to remove occlusion.
Both original design hashes were unchanged. Main.js is eight lines smaller.
Compact validation/cleanup results: .development-artifacts/display-geometry-refactor/validation.json.
Smoke: 23 passed / two skipped; existing ISSUE-180 Square New Part request
assertion failed (missing captured lattice_type). Boot, real-design render,
assembly exit and Close Session passed. Temporary images/traces/logs were
removed after review; no new files remain in the inventoried workspace test,
project or session roots. Unrelated worktree changes were preserved.

### ISSUE-265 — D014 scaffold strokes excluded from staple matching (2026-11-26)

Added observed lane/color-phase classification and conservative connected pixel
tracing. Anchor screening accepts classified staple domains only and has no raw
stroke fallback. The three visually identified scaffold false positives are now
covered by source-image regression tests. Blue staples, alternate scaffold colors,
ambiguous crossings, gaps and occlusion are covered separately. Full strand-end,
polarity and native routing recovery remain unresolved and are reported as such.

### ISSUE-266 — Target the cluster row selection area in pattern checks (2026-11-27)

Changed the two pattern browser checks to click the left selection area instead
of the row centre, where the colour control can intercept the event. Failure
inspection showed an empty selection and an armed tool, not a geometry failure.
The viewport selection path remains independently exercised by the circular-axis
check. Product selection behavior is unchanged.

ISSUE-266 verification: circular confirmation and the complete linear grid/history/
undo/save/reload browser flows pass with explicit row selection. The linear fixture
waits for prior autosave (separate ISSUE-267) and reloads from its configured
`NADOC_WORKSPACE`, allowing failure-safe isolated storage and cleanup.
