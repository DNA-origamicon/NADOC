# Cis-anti-I additive parity campaign

**Paused by user — 2026-09-25.** No new simulations, automatic retries or parameter fits until explicit resume. Latest +15 branch remains unconverged; native evidence and validation gates are preserved. See [closeout](cpd_anti_closeout_20260925.md).

**Current workflow:** [fixed validation protocol v1](cpd_validation_protocol.md) governs further work. Finish acquisition and basin closure; do not launch another parameter fit before its dataset gate passes. Historical completion notes below do not override this gate.

Started 2026-09-20 at the user's request to bring cis-anti-I to cis-syn-I's level.
User-confirmed target: additive CHARMM parity with the preliminary cis-syn v6
candidate. The existing Drude track remains separate; none of its failed gates
is superseded by this campaign. No cloud resources have been allocated.

## Next batch — 2026-09-21

User requested watcher repairs and efficient CPU utilization. The replacement
launcher (`experiments/cpd_anti_additive/launch.py`) freezes execution and watcher
scripts, pins the absolute codex executable and originating thread, and arms a
**separate systemd watcher service before starting computation**. Notifications
use inotify/pidfd, survive computation-cgroup death, preserve tokens/attempts
across retries, record queue exceptions, and deduplicate accepted terminal
notifications. They distinguish supervisor disappearance from scientific success.

Seven fast watcher tests pass. A live supervisor-SIGKILL test in
`cpd-anti-watcher-live-test-v1` survived in its external watcher and queued the
`supervisor_stopped` event, message `01a0c2c1-b941-7002-b2f4-1a8dd357f379`.
Token `97c6c81d-7002-4bdd-a01b-942bc6762215`. Actual originating-session delivery was received and acknowledged at
2026-09-21 07:10:59 UTC (01:10:59 MDT); matching `completion_wake_ack.json`
and `completion_wake_review.json` verify the complete crash → queue → session
wake chain. No duplicate job was launched.

Running/queued work:

- `nadoc-cpd-anti-endpoint2-cartesian-v1`: native unconstrained Cartesian RFO
  retry from original evaluated step 25 (lowest native maximum-force iterate
  passing all graph-distance, sugar and lesion stereochemistry screens).
  Original force 5.40e-4 au is **not converged**. Maximum trust step is 0.1,
  initial 0.05; GAU_TIGHT and the electronic method/convergence are unchanged.
  Four threads pinned to physical cores 12–15, 4 GiB Psi4 / 6 GiB service cap;
  provisional expected 4 hours, overdue 6 hours, hard resource bound 12 hours.
  Exact restart provenance: `cpd-anti-additive-next-v2/endpoint2_restart_audit.json`.
  Output: `cpd-anti-endpoint2-cartesian-v1`; watcher/status: `cpd-anti-endpoint2-service-v1`.
- `nadoc-cpd-anti-scaling-v1` and `nadoc-cpd-anti-scaling3-v1`: identical
  endpoint-1 reference gradients at 2, 3, 4 and 8 threads, 3 GiB per worker.
  Timing copies retain all QCSchema inputs/results; one validated reference
  result is checkpointed into the production Hessian rather than recomputed.
- `nadoc-cpd-anti-endpoint1-hessian-v2`: waits on benchmark exits via pidfd,
  then measures concurrent useful gradient batches at 3×4 and 4×3 (and 4×2
  only if serial scaling justifies it). Initial preference 3×4 changes only
  for >10% measured throughput improvement. Maximum four 3-GiB workers in a
  16-GiB service, initially cores 0–11; no SMT oversubscription. On endpoint-2
  exit an event releases cores 12–15 and enables four workers with the fastest
  measured 2/3/4-thread latency (requires >5% gain to change thread count).
  Completed benchmark/pilot gradient pairs are reused. All 289 immutable tasks
  are then assembled through the established frequency pipeline and independently
  audited for a harmonic minimum. Provisional expected 10 hours, overdue 15,
  resource bound 24 hours. Results: `cpd-anti-endpoint1-hessian-v2`; watcher/status:
  `cpd-anti-hessian-service-v2`. v1 was replaced **while waiting, before any
  Hessian gradient launched**, to add event-driven CPU reclamation.

The completed 3-thread benchmark exposed a terminal-status race: a normal exit
could be labeled supervisor_stopped if it fell between the status read and the
process check. The watcher now rereads the atomically written final status after
observing exit; its dedicated regression passes. The three active watcher services
were restarted with the fix, retaining tokens/receipts and leaving QM untouched.
The preserved original 3-thread receipt still shows the old event label; its actual
status and native gradient result confirm successful computation.

First timings for the identical reference gradient: 2 threads 311.8 s,
3 threads 292.2 s, 4 threads 204.2 s. These are single timings under the then-current
background workload; the useful concurrent pilots, not extrapolation alone,
select final throughput. The 8-thread probe remains part of the registered batch.

Three fast adaptive-scheduling tests pass: exactly-once task coverage, live
process-exit reclamation without timer polling, and task-failure propagation.
The conda-compatible libc pidfd call was also exercised. Native scientific
completion and actual throughput are recorded by the running jobs, not inferred
from these software checks.

The endpoint-1 optimized-audit adapter in `cpd-anti-additive-next-v2` is linked to
the actual hash-verified independent audit; it is not fabricated optimization
history or a minimum claim. Initial preparation v1 failed only on parsing the
optional mass column in intermediate Psi4 geometry tables; v2 preserves that
column's format and selected evaluated geometry correspondence explicitly.

## Status review — 2026-09-21 00:44 MDT

The v2 campaign is terminal, not running. Endpoint 1 converged and passed the
independent geometry/identity/stereochemistry audit at 00:43 MDT; its Hessian
certification remains outstanding. Endpoint 2 stopped at 23:35 MDT with Optking
“Step is far too large” / “Maximum dynamic_level reached”; no optimized target
was exported. Do not rerun endpoint 1. Recover and audit endpoint 2's trajectory
before choosing a bounded optimizer repair; endpoint 1 Hessian and additive
baseline preparation can proceed independently.

Both notification processes failed because systemd's PATH did not contain codex.
Absolute executable paths are now pinned at preparation, checked before watcher
arming, and recorded in watcher_config.json. A restricted-PATH executable check
passes; end-to-end queue delivery has not been retested. No wake delivery is
claimed. Source snapshots and terminal failures are preserved in the v2 root.

Runtime was 3 h 31 min; total CPU use 22 h 28 min (about 6.4 CPU cores on average).
The original allocation was eight threads on a 16-core / 32-thread PC, with
6.6 GiB observed service memory peak. At review, CPU was 97–99% idle and about
21 GiB RAM was available. The campaign does not fully utilize the PC.

## Executed and running

- `cpd-anti-additive-core-baseline-v1`: reconstructed the 36-atom capped anti
  core from the independently recorded bonded graph and hash-checked anti QM
  reference. Explicitly verified C5–C6/C6–C5 crosslinks, 38 bonds and all four
  lesion stereocenters. Published cis-syn types/charges are a **transfer
  hypothesis**, not anti-specific electrostatic validation. Both published
  torsion-table interpretations were retained. The `last` interpretation has
  maximum bond error 0.036573 Å and angle error 6.86516°, despite stationarity
  and positive internal curvature. It fails the unchanged 0.03 Å / 3° targets.
- `cpd-anti-additive-core-angle-v1`: bounded equilibrium-angle training diagnostic
  (±6°, 50 outer evaluations, no changes to charges, force constants or torsions).
  Errors decrease to 0.034607 Å / 3.05908°. Still fails both geometry targets;
  this is not a releasable fit. XML stays isolated; generic type changes must
  never be inserted into DNA force-field files. Joint CPD-specific bond/angle
  fitting across the core and both sugar targets is the next fitting stage.
- `cpd-anti-additive-boundary-qm-v2`: two concurrent 49-atom neutral anti
  glycosidic-fragment optimizations, retaining endpoint 1 or endpoint 2 sugar.
  Start from the independently screened repaired seeds, not the earlier
  wrong-chirality fragment calculations or an interrupted final iterate.
  Frozen-core DF-MP2/6-31G(d), Psi4 1.11, GAU_TIGHT; electronic and optimizer
  settings are unchanged from the prior plan. Four threads / 4 GiB Psi4 per
  endpoint, 14 GiB service cap, no swap, 12-hour wall-time limit. Independent
  native convergence, atom correspondence, sugar and lesion stereochemistry,
  and catastrophic-contact audits follow each successful optimization.
  Geometry optimization alone does not certify positive QM curvature.
- `cpd-anti-additive-boundary-qm-v1` failed before any QM started because the
  conda Python lacks `os.pidfd_open`. Preserved. v2 uses system Python for
  event supervision. No scientific tolerance changed.

All roots are under `.development-artifacts/` (Archive-backed), outside the
user design workspace. No registry, production geometry or supported-isomer
flag was changed.

## Fixed DNA comparison site

User selected `workspace/2hb_1xT_CPD.nadoc`, retaining the existing ordered CPD
pair for all isomer comparisons. Frozen byte-identical snapshot and atom-resolved
site manifest: `cpd-anti-additive-2hb-site-v1`.

- Endpoint 1: `__xb__:4a12dd44-bce2-46be-8296-093ce52d2ec9:0`,
  thymine on `stpl_XY_1_1`.
- Endpoint 2: `__xb__:54c5689d-127b-4693-bc11-f51121719fad:0`,
  thymine on `stpl_XY_0_1`.

Both resolve independently to crossover-extra thymines on different strands.
Measured **world-coordinate** syn crosslinks are 1.6290 and 1.5624 Å; anti
cross-pairs at this unchanged syn geometry are 2.3196 and 2.1905 Å. Stored
`design_coordinates` are before per-residue transforms and must not be measured
as world coordinates. The original design is unchanged. This freezes the site,
not an anti placement; the anti structure must be rebuilt and checked, rather
than relabeling syn coordinates or merely exchanging bonds.

## Verification

The refined core passed an independent four-center stereochemistry audit and
stationarity / step-halved MM curvature check in
`cpd-anti-additive-core-angle-verification-v1`: maximum force
3.243e-6 kcal/mol/Å; smallest internal curvature 0.6850824 and 0.6850817
kcal/mol/Å² at displacement steps 1e-4 and 5e-5 Å. This certifies only the
local MM minimum; the geometry-quality failures remain. Ruff check, Ruff
format check and Python compilation pass for the new experiment scripts.
No app behavior changed or app qualification claimed.

## Supervision and continuation

Completed calculation service: `nadoc-cpd-anti-additive-boundary-qm-v2.service`.
Failed cgroup-exit fallback (notification-path issue above): `nadoc-cpd-anti-additive-boundary-fallback-v2.service`.
The main watcher uses inotify/pidfd; the fallback survives a whole calculation
cgroup timeout/OOM and detects supervisor exit. Both target the exact originating
thread, recorded in `completion_wake.json` and `fallback_armed.json`.
Expected wall time is provisionally 6 hours, with one overdue notification at
9 hours and a 12-hour hard resource bound. These are estimates, not measured
completion guarantees. On wake, acknowledge the recorded token and inspect the
native outputs and per-endpoint audits before continuing. Queue acceptance is
not proof of delivery. Preserve incomplete and failed calculations.

## Remaining parity gates, in dependency order

1. Finish both repaired sugar targets; verify native convergence, exact graph,
   atom identity and all sugar/lesion centers. Certify QM minima with Hessians;
   reuse old core Hessian/response evidence only with matching source hashes.
2. Create anti-specific atom-role aliases and a full-term baseline, then jointly
   fit core and both boundary bonds/angles with the same geometry targets as
   syn. Preserve source force constants unless independent Hessian/PES evidence
   motivates changing them. Freeze before independent validation. Core-only
   angle fitting above cannot establish sugar transfer.
3. Audit the anti additive electrostatics against existing QM targets with the
   correct additive water conventions. Do not import Drude charges, screened
   exclusions or its correlated-water target conventions into additive CHARMM.
   Clearly label all previously exposed data as development/regression evidence.
4. Build complete product nucleotides with correct sugar-interface charges,
   connectivity and term coverage; verify native NAMD/OpenMM energy and forces,
   stationarity, step-halved MM curvature and stereochemistry. Provide concrete
   molecular review artifacts before any normal app geometry integration.
5. Stage explicit-solvent minimization/heating/equilibration followed by three
   anti/control replicas in the intended **interstrand** context. Use ordinary
   masses and ≤2 fs for additive, with box-size/image-distance checks and lesion,
   sugar, backbone and duplex-contact observables comparable to the syn work.
   The syn adjacent intrastrand duplex fixture is not an anti junction fixture.
   Use the fixed `2hb_1xT_CPD` site and explicit ordered keys above; do not infer
   anti connectivity or molecular placement from its syn patch.
6. Review bounded preliminary qualification separately from full scientific
   release. Only then package a portable anti-specific overlay and extend app
   support under the existing geometry authorization requirements.

Reproduce preparation with:

```bash
/home/jojo/miniforge3/envs/nadoc-qm/bin/python \
  experiments/cpd_anti_additive/run_boundary_qm.py \
  --prepare --root .development-artifacts/<fresh-root>
```

Launch using the recorded resource limits and `CODEX_THREAD_ID`; arm the
separate fallback service as well. Existing artifact roots must not be reused.

## Three-thread wake evidence review

Acknowledged token `8b2f07c0-3e2c-45e5-a4bd-d7730f74fe73` in the originating
session. Native task success, plan/input/result hashes and all 147 finite gradient
components verified. The four 2/3/4/8-thread reference gradients use identical
inputs; detailed numerical differences and timings are in
`cpd-anti-scaling3-service-v1/completion_wake_review.json`. The apparent supervisor
stop was the already-fixed status-read race. The existing Hessian scheduler has
advanced to its 3×4 concurrent pilot; no duplicate calculations were launched.

## Endpoint-2 six-hour overdue review

At 07:02 MDT Sep21, native Cartesian optimization reached step77 with decreasing
energy and active derivative calculations. Maximum force 0.00106 au remains
about71 times GAU_TIGHT; this is not near-converged. An independent snapshot
audit retains all sugar/lesion centers, graph-distance and contact screens.
Continue the same process for two hours, then review again; no restart or
tolerance change. The original12-hour hard limit remains. A versioned review
deadline is armed in the independent watcher, preserving all prior receipts.
Evidence: `cpd-anti-endpoint2-overdue-review-v1/`.

Concurrent throughput selected3×4:30.67 gradients/hour versus29.18 for4×3.
The Hessian has212/289 completed reference/pilot/production tasks at this review;
QM processes together consume about15 CPU cores, with15GiB RAM available.

## Endpoint-2 eight-hour overdue review

At09:04 MDT Sep21, step104 has max force2.63e-5 and RMS force9.14e-6 au.
RMS force passes, but max force and both displacement criteria still fail.
Max force improved about40-fold since the previous review. Independent
geometry/sugar/lesion checks still pass. Continue unchanged, with another
review in two hours and the original12-hour hard limit intact. Snapshot,
audit, prior acknowledgment and revised deadline evidence are preserved in
`cpd-anti-endpoint2-overdue-review-v2`. Hessian progress285/289 gradients;
assembly and minimum certification remain pending. No duplicate simulations.

## Endpoint-1 Hessian completion and numerical follow-up

At09:08 MDT Sep21, all289 native gradient tasks completed and their plan/input/
result hashes and147 finite gradient components were independently verified.
The assembled147×147 Hessian passes the registered harmonic-minimum audit:
141 internal modes, zero imaginary, lowest16.2478 cm^-1. Reference maximum
force4.12314e-6 au; matrix asymmetry2.22e-16. This qualifies the endpoint-1
QM fragment under that audit, not the additive force field or solution model.
Evidence: `cpd-anti-hessian-service-v2/completion_wake_review.json`.

Because cross-thread gradient differences reached2.75e-6 au and the lowest mode
is soft, a bounded numerical follow-up is running: `cpd-anti-endpoint1-soft-mode-v1`.
Five MP2/6-31G(d) gradient evaluations (reference and±0.04/±0.02 bohr along the
normalized Cartesian direction of the lowest projected mass-weighted mode),
with SCF E/D convergence1e-12 and response SOLVER_CONVERGENCE1e-10. Three
four-thread workers use cores0–11; endpoint2 continues on12–15. Native response
cutoffs are checked. Prospective checks: reference max force≤1.5e-5 au, positive
directional curvature at both steps, step-halving discrepancy≤10%. This is a
directional numerical check, not a second full Hessian or a new release gate.
Expected30 minutes, overdue45 minutes, hard resource bound2 hours; independent
watcher/status in `cpd-anti-soft-mode-service-v1`. No other optimization restarted.

## Endpoint-1 soft-mode completion and additive boundary baseline

The soft-mode completion wake `ed51acdc-95de-43a9-9af3-4ab8668626d6`
was acknowledged and all five native results, hashes, finite gradients and
response cutoffs checked. Reference maximum force is 3.899787e-6 au.
Directional curvatures at 0.04 and 0.02 bohr are 1.0058648656e-4 and
9.845699924e-5 Eh/bohr²: positive at both steps, with 2.1171% step-halving
discrepancy. All prospective numerical checks pass. The tighter small-step
curvature is 68.05% above the original Hessian directional value; the original
16.2478 cm^-1 should not be treated as a precision-validated frequency. A full
tighter Hessian would be needed before precise low-mode force-constant fitting.
This directional check supports endpoint-1 minimum evidence, not force-field
or solution qualification. Review and acknowledgment are preserved in
`cpd-anti-soft-mode-service-v1/`.

Ran `experiments/cpd_anti_additive/boundary_baseline.py`, producing isolated
`cpd-anti-additive-boundary-baseline-v1/`. The independently audited endpoint-1
QM geometry was compared with the unfitted published additive transfer
hypothesis on the anti graph. All 49 atoms and 52 bonds match the fragment
graph; all sugar and lesion stereo signs survive minimization. Glycosidic bond
error 0.0280723 Å passes the 0.03 Å target, but maximum boundary-angle error
6.09084° fails the 3° target. Across the whole fragment, maximum bond/angle
errors are 0.0336004 Å / 7.60860°. Keep this failed baseline as evidence for
joint anti refinement; it is not simulation-ready.

Prepared `cpd-anti-additive-types-v1/` using `prepare_anti_types.py`: isolated
anti atom-role aliases for core and endpoint-1, with no parameter fitting or
charge changes. Exported CHARMM/OpenMM energies and forces exactly match both
input systems at their recorded coordinates. Endpoint-2 will still need to be
incorporated before shared joint fitting. Use the repository `.venv` Python for
this ParmEd-dependent script; the initial `nadoc-qm` interpreter attempt failed
on import before any artifact creation. Both new scripts pass Ruff checks.

Endpoint-2 optimization and its independent watcher remain active. Next review
is 11:05:22 MDT Sep21, with the original twelve-hour hard limit unchanged.
CPU use is now limited by this remaining optimization gate; the parallel Hessian
and soft-mode tasks are finished. Do not launch duplicates or speculative full
Hessians merely to occupy idle cores. Production readiness remains false.

## Endpoint-2 ten-hour overdue review

At 11:06 MDT Sep21, native step150 has maximum/RMS forces 4.62e-6 /
1.76e-6 au: both pass GAU_TIGHT. Maximum/RMS displacements 1.36e-4 /
4.38e-5 au still fail their 6e-5 / 4e-5 limits. Energy continues decreasing;
independent evaluated-geometry screening preserves all sugar/lesion centers
and passes covalent-distance/contact checks. Continue the existing process
without a restart or tolerance change. Optimization has not converged, and
endpoint-2 minimum certification still requires a Hessian after convergence.

Snapshot, convergence rows, chemistry audit, prior receipts and review script
are retained in `cpd-anti-endpoint2-overdue-review-v3/`. The wake was
acknowledged, and the next review deadline is 12:36:48 MDT Sep21; terminal
notification remains armed. The original twelve-hour service limit (about
13:01 MDT) remains unchanged. No duplicate jobs or cloud spending. The first
review-script invocation used the repository interpreter without RDKit and
failed before creating artifacts; the recorded successful review used
`nadoc-qm` Python.

## Endpoint-2 optimization completion and Hessian launch

At 11:25 MDT Sep21, endpoint-2 completed at native step158. Maximum/RMS
forces are 4.64e-6 / 1.28e-6 au; maximum/RMS displacements are 5.98e-5 /
2.16e-5 au. All four active GAU_TIGHT criteria pass. The independent audit
passes identity, native/result/XYZ agreement, all sugar and lesion centers,
covalent distances and heavy contacts. Audit source hashes were rechecked.
The completion wake was acknowledged with prior overdue receipts preserved.
Optimization completion is not minimum certification.

Prepared 289 distributed gradient tasks in `cpd-anti-endpoint2-frequency-v2/`
and launched `nadoc-cpd-anti-endpoint2-hessian-v1`, with control/status/watcher
in `cpd-anti-endpoint2-hessian-service-v1/`. Four workers each use four threads
and 3 GiB Psi4 memory, restricted to physical cores0–15; service memory cap
18 GiB, no swap, hard limit16 hours. Endpoint-2 optimization is finished, so
its former four-core reservation is available. This extends the previously
measured four-thread worker layout without SMT oversubscription. Expected
runtime8 hours, overdue notification12 hours, terminal notification armed;
actual throughput will determine completion. Confirmed four workers running
and a live independent watcher on the original campaign thread.

The Hessian uses the same immutable v1.7.0 protocol as endpoint-1. Inspect
reference stationarity and all internal modes on completion; use a tighter
soft-direction check if needed given the endpoint-1 numerical sensitivity.
No force-constant fitting should assume precision of the lowest modes.
`cpd-anti-endpoint2-frequency-v1/` preserves an unsuccessful preparation:
the first script expected the wrong native success-marker wording. No QM
was launched by that attempt. The v2 preparation checks the actual final
geometry marker plus all four explicit convergence criteria. Production
readiness remains false; no duplicate simulations or cloud spending.

## Endpoint-2 Hessian completion and joint-refinement preparation

At 17:27 MDT Sep21, the endpoint-2 Hessian finished in 6.02 hours. All289
native task success records, input/plan/result hashes and147 finite gradient
components per task were reverified, together with the assembled Hessian and
frequency output hashes. Reference maximum gradient4.97706e-6 au. The
frequency audit passes candidate harmonic minimum:141 internal modes, zero
imaginary, lowest28.1170 cm^-1; Hessian asymmetry1.11e-16. The requested
completion acknowledgment and review are in `cpd-anti-endpoint2-hessian-service-v1`.
This is QM minimum evidence, not additive or solution qualification.

A five-gradient tighter soft-mode follow-up is running in
`cpd-anti-endpoint2-soft-mode-v1`, controlled by
`cpd-anti-endpoint2-soft-mode-service-v1`. It uses the same prospectively
specified two steps (±0.04/±0.02 bohr), electronic/response tolerances and
pass criteria as endpoint1. Three four-thread workers use cores0–11, with
14 GiB service cap, no swap, expected30 minutes, overdue45 minutes, hard
limit2 hours. Independent watcher confirmed live and armed. No duplicate
Hessian jobs. The original numerical frequency remains provisional in
precision until this check is reviewed.

Ran the endpoint2 additive transfer baseline in
`cpd-anti-additive-boundary-endpoint2-v1`: glycosidic bond error0.00527143 Å
passes; boundary angle error7.82837° fails. Whole-fragment maximum bond error
0.0323846 Å also fails. All sugar and lesion stereochemistry is preserved.
This failed baseline remains available for joint core/endpoint1/endpoint2
refinement. `boundary_baseline.py` now takes explicit --root, --endpoint and
--audit arguments and checks matching model identity and atom order.

Prepared `cpd-anti-additive-types-v2` across core and both sugar endpoints.
Role/type alias export reproduces input energies and forces exactly for all
three recorded coordinate sets. It contains no fitted parameters or changed
charges. The earlier v1 candidate remains preserved. Native MM/export checks
and Ruff passed for the edited experiment scripts. Next: review endpoint2
soft-mode evidence, then joint refinement and anti electrostatic targets;
keep all DNA/interstrand and force-field release gates separate.

## Endpoint-2 soft-mode review and additive training launch

At 17:39 MDT Sep21, endpoint2 tighter soft-mode check completed. Verified all
five input/plan/native/result hashes,49×3 finite gradients and response cutoffs
≤1e-10. Reference maximum force4.53412e-6 au. Directional curvatures at0.04 /
0.02 bohr:1.4427726317e-4 /1.4455924036e-4 Eh/bohr²; both positive,
step-halving discrepancy0.19506%, small-step stiffness5.24968% lower than the
original Hessian. All registered checks pass. Acknowledgment and native review
are preserved in `cpd-anti-endpoint2-soft-mode-service-v1`. Both sugar fragments
now have optimization, harmonic-minimum and tighter soft-direction evidence;
this does not qualify additive parameters or the interstrand DNA model.

Started local HF/6-31G(d) ESP and dipole targets for both audited fragments:
`cpd-anti-boundary-esp-v1`, controlled by `cpd-anti-boundary-esp-service-v1`.
Uses the registered deterministic four-shell grid and immutable protocol,
two four-thread workers on physical cores0–7,3 GiB per worker,10 GiB service
cap, expected30 minutes, overdue45 minutes, hard limit2 hours. These are
charge-training targets; water interaction and transfer validation remain.

Concurrently started bounded joint additive geometry training across core and
both endpoints in `cpd-anti-joint-fit-v1`, controlled by
`cpd-anti-joint-fit-service-v1`. Anti-specific aliases isolate103 shared
bond/angle equilibrium groups, with maximum shifts0.01 Å /6° and fixed
force constants, charges and torsions. The inherited syn training algorithm
now uses anti crosslink neighbors in every lesion stereochemistry check.
Acceptance remains all bond errors≤0.03 Å, all angle errors≤3°, preserved
sugar/lesion stereochemistry; fitting is training, not independent validation.
The fit uses one BLAS thread and is confined to cores8–15 (serial minimization/
response solves do not benefit from reserving eight workers). Service cap6 GiB,
expected30 minutes, overdue45 minutes, hard limit3 hours. Both independent
watchers are armed; no duplicate jobs, cloud spending or production changes.

### Immediate training results and ESP protocol correction

Both initial training services completed in about34 seconds, with terminal wakes
acknowledged and reviews recorded. The bounded joint fit preserves all sugar
and lesion centers but fails the geometry thresholds: endpoint1 max angle/bond
errors4.10848°/0.0304743 Å; endpoint2 5.35985°/0.0288891 Å; core
3.26067°/0.0298076 Å. All final MM forces are small, but this is not independent
MM minimum certification or accepted geometry. Preserve the failed candidate;
do not expand bounds just to force a pass. Charge-sensitive geometry and
parameter-group residuals need review before choosing the next fit.

ESP v1 produced finite, hash-verified1289/1287-point potential targets, but
its default helper protocol omitted the requested dipole: the default protocol
was older than v1.7.0. These ESP-only results are retained as incomplete for the
intended combined target. Corrected `boundary_esp.py` to explicitly pin v1.7.0
and require a passing ESP audit plus a finite dipole. A distinct corrected
calculation is running in `cpd-anti-boundary-esp-v2`, with independent watcher
`cpd-anti-boundary-esp-service-v2`; identical resource limits, no overlapping
original calculations. The prior claim that v1 generated dipoles was incorrect.
Next review should verify v2 native outputs and dipoles, then assess charge
transfer and joint-fit residuals. No production gates advanced.

## Joint-fit v1 completion wake: optimizer-budget diagnosis

Reviewed and acknowledged token8bb46122-5efd-4b2f-9c24-90599d0646c1.
Reverified the joint-fit source hashes and native optimizer/report evidence.
The command returned zero, but optimizer_success is false: the maximum40
function evaluations were exhausted. There are38/103 normalized shifts
within1% of a bound. All geometry acceptance failures reported above remain.
The largest errors are opposite-signed C1'-N1-C6 angles in the two sugar
endpoints (−4.10848° /+5.35985°); this suggests a shared-parameter compromise,
not a reason to alter anti chemistry or automatically split types.

Launched one warm-start continuation with the same targets, regularization,
103 parameter groups,0.01 Å/6° limits, unchanged charges/constants/torsions,
and unchanged acceptance criteria: `cpd-anti-joint-fit-v2`, controlled by
`cpd-anti-joint-fit-service-v2`. Maximum200 evaluations, expected10 minutes,
overdue15 minutes, hard limit1 hour,6 GiB cap, single BLAS thread on cores8–15.
This tests whether the evaluation budget was limiting; it does not expand
scientific bounds. Previous failures remain intact. Watcher confirmed live
and armed; corrected ESP v2 was still running at launch. Native completion
of either service requires reviewing scientific results separately.

### Same-turn continuation result

The short continuation completed before handoff; its terminal watcher delivered
and exited normally. Optimizer now satisfies ftol, but geometry still fails:
endpoint1 4.10479°/0.0304360 Å, endpoint2 5.36614°/0.0288887 Å, core
3.26118°/0.0298012 Å. Stereo retained. More evaluation budget did not fix the
shared-model mismatch; do not repeatedly restart this objective.

Corrected ESP v2 also finished. Both native output/potential hashes and target
audits were verified:1289/1287 ESP points, with dipole magnitudes2.72032 /
1.38613 e·bohr. Both required dipole vectors are present and finite. Completion
receipts and reviews for both v2 services are recorded. No jobs remain running
in these two services. Next useful work is assessing transferred charges against
these targets and water interactions, and investigating the conflicting shared
angle residuals before any new parameter fit. Qualification remains incomplete.

## ESP v1 late wake, transferred-charge diagnostic and water calibration

Acknowledged late token424a2ab5-dae1-41f5-a70e-73ed2c8fb339; reverified both
v1 native output and potential hashes. V1 is valid ESP-only evidence, incomplete
for the requested dipole target and superseded by verified v2. No rerun.

Computed `cpd-anti-charge-transfer-diagnostic-v1` at the actual audited QM
geometries with unchanged additive charges and the v2 potential grids.
Endpoint1/2 ESP RMS errors0.0108337/0.0103720 au, relative RMS errors51.925% /
57.350%; gas-phase HF versus MM dipole-vector errors0.87971/1.50292 D and
angular deviations6.8297°/17.8050°. These are unscaled diagnostic comparisons,
not retrospectively selected acceptance thresholds, charge fitting, or an
independent validation set. Both fragment charge sums remain neutral.

Prepared and launched `cpd-anti-water-calibration-v1`, controlled by
`cpd-anti-water-calibration-service-v1`: identical-geometry DF/DIRECT
HF/6-31G(d) interaction pairs at three sites per endpoint (1:O2,2:O4 and
attached endpoint H3 on N3), twelve native jobs total. TIP3P target-probe
separation1.9 Å; chose the least crowded of0/120/240° azimuths and verified
all non-target intermolecular separations≥1.1 covalent-radius sums. This is
a deterministic clash screen, not optimum water orientation or a complete
interaction curve. Explicit v1.7.0 protocol uses neutral interaction scaling1.16
and distance offset−0.2 Å; the DF/DIRECT tolerance remains0.02 kcal/mol.
Each endpoint has its own three-site calibration audit.

Four four-thread workers on physical cores0–15,3 GiB each,18 GiB service cap,
no swap; expected1 hour, overdue90 minutes, hard limit4 hours. Independent
watcher handles terminal events. Generate production distance curves only
after this calibration is reviewed. Joint geometry failures remain preserved;
no new charge candidate or production flag has been accepted. Ruff and native
preparation checks passed for both new experimental scripts.

## Corrected ESP v2 late wake and screened distance-grid preparation

Acknowledged token4752ce62-ddfc-4b87-a4a4-49d35d592a27 and reverified both
v1.7.0 ESP/dipole jobs, source XYZ/parent/input/grid hashes, native output and
potential hashes, and complete dipole vectors. Both are training targets, not
charge validation. No duplicate calculations were launched.

While the twelve-job DF/DIRECT calibration remains active, prepared
`cpd-anti-water-curve-plans-v1`: six sites on each endpoint (O2,O4,N3–H3 on
both bases), each with seven target-probe distances1.5–2.7 Å in0.2 Å steps.
All twelve site grids pass the registered non-target distance screen at every
point, using the least crowded of0/120/240° water azimuths. All candidate
orientation screen values are retained, not only the chosen orientation.
This yields84 prospective interaction points, not executed jobs. Orientation
and distance minima still require scientific review; a curve minimum at an
edge requires extension, not an accepted fitted target.

Execution remains gated on each endpoint's passed three-site DF/DIRECT audit.
The future generator must explicitly pass protocol v1.7.0 to
`generate_water_interaction_job`; do not rely on older helper defaults. Scripts
and preparation passed Ruff/native checks. No release or minimum gate changed.

## Joint-fit v2 late wake and independent MM numerical checks

Acknowledged token085c693f-26d1-480e-a569-9190edd883e4. Reverified all fit-input
and warm-start hashes. Native optimizer ftol termination is genuine, while all
three geometric training cases still fail their existing acceptance criteria.
No duplicate fit or relaxed criterion was introduced.

Ran `verify_joint_candidate.py`, retaining results in
`cpd-anti-joint-fit-verification-v1`. Independent force evaluation and projected
MM Hessians at1e-4 and5e-5 Å steps show stationary positive-curvature minima
for core and both sugar fragments. Maximum forces≤6.59e-6 kcal/mol/Å;
smallest internal curvatures at the halved step are0.5679702,0.3929877,
0.1155391 kcal/mol/Å² respectively, all with zero negative internal modes.
Reloading the exported CHARMM parameters reproduces candidate XML energies
within4.08e-10 kcal/mol and forces within6.03e-9 kcal/mol/Å. These checks
support numerical stability/export correctness only; the geometry and charge
mismatches remain. They do not qualify a force field or DNA simulation.

Water calibration was still running at this review. Its existing watcher
remains responsible for the next computational gate; the84 screened water
curve points remain unlaunched pending calibration. All failed candidates and
native outputs are retained; no cloud spending.

## Water calibration completion and production distance curves

Acknowledged token9bc6f626-f3b3-4ac2-b90d-6d2a20391946. Reverified all12
native calibration jobs and their model/water/parent/input hashes, and reran
the calibration audit independently from native outputs. Both endpoint audits
pass: maximum DF/DIRECT interaction errors0.00387297 and0.00448968 kcal/mol
versus0.02 tolerance, covering three distinct sites per endpoint. These
validate the sampled SCF approximation, not charges or a molecular minimum.
Independent reviews reside in `cpd-anti-water-calibration-service-v1`.

Launched the screened distance curves in `cpd-anti-water-curves-v2`, controlled
by `cpd-anti-water-curves-service-v1`. There are84 points over12 sites; six
identical calibration DF geometries are reused through their original immutable
job directories after model/protocol/coordinate matching, leaving78 new jobs.
All new jobs explicitly use protocol v1.7.0. Four four-thread workers on
physical cores0–15,3 GiB per worker,18 GiB service cap, no swap; expected1 hour,
overdue90 minutes, hard limit4 hours. Terminal watcher and progress.json track
completion. Each seven-point curve will be audited separately; an unbracketed
minimum remains incomplete and requires extension before charge fitting.
No charge fit, additive release or DNA validation is implied by job completion.

Preserved `cpd-anti-water-curves-v1` preparation failure: a NumPy boolean reuse
flag could not serialize into the plan. No QM jobs were launched from v1.
The corrected v2 casts that flag to a native bool and passed native preparation
and Ruff checks. No duplicate computations or cloud spending.

## Water-curve completion and initial bounded charge candidates

Acknowledged tokenc6266ae5-9ab1-47e4-b3e9-5fe9a23af119. All84 native
output/input/model/water/parent provenance chains verify, including six reused
calibration points. All12 seven-point curves have bracketed minima and pass
the curve audit. This is complete charge-target evidence, not charge acceptance
or molecular minimum certification.

`cpd-anti-water-transfer-diagnostic-v1` evaluates unchanged published-transfer
charges and CHARMM TIP3P (including hydrogen LJ) on these curves, with no
relevant pair-specific NBFIX terms. QM interaction energies use1.16 scaling;
QM minima use the registered−0.2 Å distance offset. Local three-point parabolas
interpolate both minima. N3–H3 contacts overbind by3.37–4.27 kcal/mol; carbonyl
errors range−2.10 to+0.76 kcal/mol. All MM minima are bracketed. This explains
why the transferred charge hypothesis needs refinement independent of the
remaining bonded-geometry compromise.

Ran `cpd-anti-charge-candidates-v1`: three prospectively recorded L2 restraint
strengths (1,10,100) with per-atom charge shifts bounded±0.15e. The28 stable
base atoms have shared charges across the two fragments; sugar/caps and all LJ
and bonded parameters remain fixed. Constraints preserve neutral totals and
equal methyl-H shifts within each base. Objective combines ESP and three
near-minimum water points per site, evaluating MM water at the−0.2 Å shifted
separations. All inputs are explicitly development data. No independent holdout
or final charge acceptance is claimed; dipoles are diagnostics outside the fit
objective. No charge candidate was exported into PSF or production.

All three numerical optimizations converge. The least restrained candidate
has ESP relative RMS errors38.77%/43.41% (baseline51.93%/57.35%), dipole-vector
errors0.316/0.921 D, and maximum water-minimum energy errors1.328/1.443 kcal/mol.
The more restrained candidates improve less. These residuals remain material;
do not label the candidate accepted because the optimizer converged. Next:
independent charge/geometry transfer checks and parameterization tradeoff review
before selecting charges and revisiting bonded fitting. Prior failed geometry
and original charge baselines remain intact. Native calculations and experiment
Ruff checks completed; no duplicate jobs or cloud spending.

## Overall-status and progress-visualizer refresh

Regenerated Help → CPD progress from current retained evidence. Replaced stale
anti “stopped/deferred” studies with audited QM minimum coordinates and checks;
added three separate additive training structures with per-atom/bond angle and
length failures, stereochemistry, MM-curvature/export checks, charge-target
progress and pending interstrand validation. Anti gallery campaign checks and
overall summary now agree with this document. Gallery illustrative coordinates,
normal application geometry and registry qualification remain unchanged.

At refresh, no CPD calculation services were running: reference targets are
complete, while parameter selection/refinement and independent transfer/DNA
validation remain. Cis-syn retains preliminary v6 integration and its existing
finite DNA stability evidence, with the unresolved lesion-site conformational
finding separate from release qualification. Anti is not yet at that level.

Verification: all6590 frontend tests (458 files) passed; all3 CPD Chromium
browser tests passed after updating the obsolete starting-structure assertion.
The new browser check explicitly inspects anti QM and failed additive studies.
Evidence references resolve; Ruff and diff-whitespace checks pass. Verified
Playwright reports/screenshots and test workspace artifacts cleaned after run.
Refresh review saved in `cpd-progress-refresh-v1/review.json`.

## Next geometry/charge set: controlled coupling and retrospective transfer

User authorized another set for failed geometry and charge candidates. Prepared
`cpd-anti-coupled-round-v1` and launched independent watched service
`cpd-anti-coupled-round-service-v1`. Five tasks: three joint geometry fits using
existing charge strengths1/10/100 and two charge fits each trained on one sugar
endpoint and evaluated on both. The latter are retrospective transfer checks,
not blind validation, since both fragments already informed development.

Charge-assignment preparation verifies exact candidate charges in each endpoint,
neutral totals in all three compounds, unchanged sugar/cap charges and graph,
and successful standalone CHARMM system creation. Core receives the same stable
base-atom shifts, retaining neutral methyl caps. Charge-dependent nonbonded
exceptions are regenerated from each new PSF. Isolated artifacts only; no normal
app/production PSF is changed.

All three geometry fits retain the original±0.01 Å/±6° parameter bounds,
fixed force constants/LJ/torsions, and≤0.03 Å/≤3° geometry criteria. They start
from the previous joint equilibrium-parameter shifts and receive200 evaluations;
no repeat of the unchanged baseline. Endpoint transfer repeats the same three
charge restraints and±0.15e bounds, with the opposite endpoint excluded from
the fitting objective. Record both improvements and regressions; no charge
candidate is selected merely because it gives a better training score.

Three concurrent tasks, one BLAS/OpenMP thread each, on physical cores0–15;
these small MM-response problems do not benefit from16-thread BLAS. Service
memory cap12 GiB, no swap, expected20 minutes, overdue30 minutes, hard limit2h.
Completion watcher targets the existing campaign session. Preparation and Ruff
checks passed; preserve any failed tasks. No cloud spending.

## Coupled-round completion: charges do not resolve the geometry compromise

Acknowledged tokenda9fa588-cfbb-4530-ba40-bdd8736e7a70. Verified all five
assessment hashes and fit-source hashes against the registered plans. Every
optimizer converged, but all three charge-dependent geometry fits still fail:
endpoint1 angles4.05–4.10° and bonds0.03051–0.03067 Å; endpoint2 angles
5.37–5.42°; core angles3.24–3.26°. All stereocenters survive. These new
candidates have no independent MM Hessian certification yet; optimizer success
is not minimum certification or geometry acceptance. No charge set is accepted.

Retrospective leave-one-endpoint-out fits worsen on the excluded fragment.
For restraint1, train endpoint1→evaluate endpoint2: ESP relative RMS46.9%,
dipole-vector error1.374 D, max water-energy error1.890 kcal/mol. Reverse:
41.6%,0.455 D,1.739 kcal/mol. Both fragments are previously seen development
data; these results are sensitivity/transfer diagnostics, not blind validation.
The existing joint charge candidate remains exploratory.

Started the next isolated diagnostic: `cpd-anti-ordered-types-v1` retains the
ordered endpoint number in each atom-role alias, rather than tying same-named
atoms across the stereochemically distinct anti endpoints. Terms for each
ordered endpoint remain shared between core and sugar models. All three
pre-fit energies and forces exactly reproduce the original additive baseline,
so aliasing alone changes no physics. Charges, LJ and force constants are fixed.

`cpd-anti-ordered-fit-v1`, controlled by `cpd-anti-ordered-fit-service-v1`, fits
this alternative grouping with the original±6°/±0.01 Å limits and≤3°/≤0.03 Å
criteria,200 evaluations, starting from zero shifts (old alias names cannot
safely transfer previous parameter shifts). This tests the cross-endpoint
sharing assumption; extra parameters do not by themselves establish physical
validity. Single BLAS thread on cores8–15,6 GiB cap, expected10 minutes,
overdue15 minutes, hard limit1h, independent watcher. No cloud spending.
Progress snapshot now records coupled-round failures and this pending diagnostic.

## Ordered-endpoint geometry success and charge-coupled verification

Acknowledged token83c1c68f-0437-4ff4-9f36-01706daad72e and verified native
fit/source evidence. The ordered-endpoint hypothesis passes all three original
geometry criteria, with maximum angle/bond errors: core2.34462°/0.0267218 Å,
endpoint1 2.61156°/0.0261182 Å, endpoint2 2.89065°/0.0288070 Å. All stereo
signs remain correct. These are fitted training results, not new independent
reference data. Independent two-step MM curvature, stationarity and CHARMM
export checks also pass (`cpd-anti-ordered-verification-v1`).

Then ran `cpd-anti-ordered-coupled-v1` (service `cpd-anti-ordered-coupled-service-v1`):
three pre-existing charge hypotheses with ordered-endpoint typing, same bounds,
and the ordered baseline's fitted parameter shifts as initialization. No
retrospective charge-fit jobs were duplicated. All three optimizers converged,
and all nine compound/charge combinations pass geometry and stereo checks.
Maximum angle error across them2.89040°; maximum bond error0.0288074 Å.
The least restrained charge candidate gives core2.22659°, endpoint1 2.52372°,
endpoint2 2.88964°, with all bonds within0.0288049 Å. No charge selection or
release is implied by these geometry results.

Independent verification for all nine systems is retained in
`cpd-anti-ordered-coupled-verification-{1,10,100}-v1`: every system is stationary,
has positive projected internal curvature at both finite-difference steps,
and reproduces its CHARMM export to the declared numerical tolerance. The
coupled service finished during this review; its wake was acknowledged and
scientific results recorded. No jobs remain active in these services.

Progress visualizer now retains the historical failed shared-role candidates,
adds the three successful ordered-endpoint baseline training structures, and
reports successful charge-coupled geometry separately from unresolved charge
accuracy/transfer and interstrand DNA validation. Numerical minimum evidence
is not electrostatic qualification. Next work should obtain independent
conformational/energetic validation of the enlarged parameter grouping and
resolve charge/water residuals before DNA qualification. No cloud spending.

## Ordered-coupled late wake and fresh conformational probes

Acknowledged token477a9c9e-9cf7-488b-b6e7-afc96751e610 and rechecked the three
fit assessments plus all nine independent MM-verification source hashes.
Geometry, stereochemistry, stationary internal curvature and CHARMM exports
remain passed within their documented isolated training scope. No repeated fits.

Prepared and launched `cpd-anti-glycosidic-probes-v1`, controlled by
`cpd-anti-glycosidic-probes-service-v1`. Four new MP2/6-31G(d) gradient/energy
calculations rotate the17 sugar atoms rigidly by±15° about N1–C1' for each
endpoint. Core/caps stay fixed. All graph-bond lengths remain unchanged within
1e-8 Å, all degree-four tetrahedral signs are preserved, and every nonbonded
heavy-atom separation exceeds one covalent-radius sum. Reference energies and
coordinates reuse the verified tighter soft-mode reference jobs, avoiding two
duplicate calculations. Electronic E/D1e-12 and response1e-10 match those
references. The original preparation snapshot is retained; a closure-binding
lint fix in the comparison code is separately hashed in the plan's runner record.

On completion compare relative energies and dE/dtheta at exactly the same
coordinates against the baseline ordered model and all three charge-coupled
models, without refitting. These are fresh fixed-geometry response diagnostics,
not relaxed torsion profiles, new minima, solution validation or predetermined
release gates. Four four-thread workers use physical cores0–15,3 GiB each,
18 GiB service cap, expected30 minutes, overdue45 minutes, hard limit2 hours.
External watcher is armed; progress visualizer includes the pending probes.
No cloud spending or production changes.

## Fresh ±15° probes reveal off-minimum nonbonded mismatch

Acknowledged token52bd636c-5f82-4785-a7b1-1856c26a6ba4. Reverified all four
native result/input/plan/output hashes,147 finite gradient components per job,
response tolerances, both reused reference results and all compared MM systems.
No fixed-geometry probe is called a minimum. Endpoint1−15°: QM relative energy
1.4068 kcal/mol versus MM8.71–8.90; endpoint2+15°: QM3.9683 versus
MM12.73–13.02. Other directions agree more closely. Charge changes do not
resolve the large asymmetric errors. These probes remain unre-fitted evidence.

Force-group decomposition (`cpd-anti-glycosidic-decomposition-v1`) finds bond,
angle and Urey–Bradley changes numerically zero under the rigid rotation;
periodic torsion changes are small. Exact pair decomposition
(`cpd-anti-glycosidic-pairs-v1`) reproduces OpenMM nonbonded deltas within1e-5
kcal/mol: the high-penalty directions contribute LJ+9.0468/+15.4799 kcal/mol
and Coulomb−0.3779/−1.4153 respectively. Leading contacts involve sugar O5'
and the opposite base methyl hydrogens/carbon. This is a capped-fragment,
rigid-rotation diagnostic; do not soften LJ or fit compensating torsions solely
to these points, nor assume the same contact behavior in a full DNA boundary.

Launched four smaller±7.5° probes in `cpd-anti-glycosidic-half-probes-v2`,
controlled by `cpd-anti-glycosidic-half-probes-service-v2`. Same reference reuse,
method/tolerances, graph/stereo/contact screens, candidate comparison and
resources as±15°. This checks whether mismatch extends close to the minimum.
The first half-step preparation failed because its label formatter expected an
integer angle; the accompanying service failed for missing plan before any QM
ran. Both v1 failures are preserved. Corrected v2 prepared successfully and
runs with an independent watcher; no duplicates or cloud spending. Progress
visualizer reports the energetic mismatch and pending smaller probes.

### Late failed-v1 notification review

Acknowledged tokenc1d6f8ac-c4fa-447d-ab33-4200e8b0c905. Confirmed the preserved
v1 failure is the missing-plan consequence of integer angle-label formatting;
there are no v1 native outputs or QM result files. Rechecked all four corrected
v2 input hashes and native-output presence. Its supervisor and watcher are
live; continue that run unchanged. No duplicate jobs or new scientific verdict.

## Half-angle probe completion and constrained-relaxation next set

Acknowledged token6343a3c4-ba2c-490a-8281-89796ae6e5e7. Verified four native
input/plan/output/result chains, finite gradients and response cutoffs, reused
references and compared MM-system hashes. At endpoint1−7.5°, QM relative
energy0.4437 kcal/mol versus MM2.6386–2.7313; at endpoint2+7.5°, QM0.8413
versus MM2.0887–2.2262. Angular energy derivatives also disagree. Thus the
asymmetric mismatch persists near the QM minimum, not only at±15°. These
are fixed-geometry response probes, not unconstrained minima or fitted targets.

Prepared four constrained relaxed±15° points in `cpd-anti-relaxed-glycosidic-v1`,
controlled by `cpd-anti-relaxed-glycosidic-service-v1`. Reuse previously screened
±15° seeds, explicit C2–N1–C1'–O4' dihedral and hash-pinned model graph. The
registered v1.7.0 generator verifies that N1–C1' is a real acyclic single bond
and that each starting torsion agrees with its target. It freezes that dihedral
and relaxes other coordinates with MP2/6-31G(d), frozen core, GAU_TIGHT and
the generator's existing default optimizer/electronic convergence policy.
Unlike the tighter fixed probes, these use the unmodified registered torsion
input; review numerical tolerances before any fine energy comparison.

Four four-thread jobs, physical cores0–15,3 GiB per job,18 GiB service cap,
no swap, expected6 hours, overdue9 hours, hard limit12 hours. Jobs fail
individually without discarding other results; native outputs are retained.
Completion includes a constraint/tetrahedral/covalent-distance screen, followed
by independent review. Constrained convergence is not unconstrained harmonic
minimum certification, and these four points are not a full torsion profile.
No force-field parameters were changed. The next comparison requires matched
constrained MM relaxation and checks for contact/cap artifacts, rather than
fitting compensating charges or torsions to rigid-probe errors. Visualizer
reports both probe mismatches and the pending relaxed points. No cloud spending.

## Constrained-relaxation overdue review — 2026-09-22

Acknowledged overdue token a182d768-6742-491f-83d6-f6919348775a at
15:27 UTC. All four native runs remain active, with no completed optimizer
or final geometry audit. Latest completed iterations at review: endpoint1−15
41, endpoint1+15 31, endpoint2−15 41, endpoint2+15 43. Endpoint1−15 meets
force thresholds but not displacement thresholds; endpoint2−15 still has
large forces. Native output hashes and convergence rows are retained in
`cpd-anti-relaxed-glycosidic-service-v1/overdue_review_20260922.json`.
Continue these workers under the existing 12-hour hard limit, without
restarting or launching duplicates. The watcher delivered overdue successfully
and remains waiting for completion/failure. CPU use averaged about 3.3 cores
over nine hours; cgroup I/O pressure was substantial, with no OOM kills or CPU
quota throttling. Do not infer a CPU benefit from adding more concurrent jobs.
Progress JSON was regenerated successfully (14 evidence structures). No new
minimum certification, parameter acceptance, or DNA-validation readiness.

## Hard-timeout reconciliation — 2026-09-22 12:45 MDT

Systemd stopped the constrained-relaxation service at12:25:09 MDT after its
12-hour cap (Result=timeout). Endpoint1−15 completed at12:12 after46 steps;
its native success marker, output/optimized-coordinate hashes and passing
constraint/stereochemistry/covalent screen were verified. Endpoint1+15,
endpoint2+15 and endpoint2−15 were interrupted after last complete iterations
40,46 and48 respectively; none is accepted as converged. All native files
remain intact. No unconstrained harmonic minimum is certified by this batch.

The killed supervisor left stale running status. Preserved that status and
systemd journal, then reconciled status.json to failed with per-point outcomes.
The watcher remained alive with its pidfd already consumed and only inotify
open, consistent with observing exit while /proc identity still existed and
then waiting indefinitely. Watcher now retains the authoritative process_exit
event rather than discarding it; a regression covers lingering /proc identity.
Updating status wakes the existing watcher. No duplicate QM jobs were started.
Next scientific work remains matched constrained MM relaxation and reviewed
continuations for the three incomplete points, with reduced disk contention.

## Reviewed continuations — 2026-09-22

Acknowledged supervisor_stopped token a182d768-6742-491f-83d6-f6919348775a,
preserving the previous overdue acknowledgement. Prepared three coordinate
continuations in `cpd-anti-relaxed-glycosidic-v2`, controlled by
`cpd-anti-relaxed-glycosidic-service-v2`. Each latest native evaluation geometry
passes original-atom-order, graph bond-distance, tetrahedral-sign and fixed-angle
checks. Sources are hash-pinned; these are fresh optimizer histories, not binary
restarts. The successful endpoint1−15 point is reused, never recomputed.

Keep registered MP2/6-31G(d), frozen-core, GAU_TIGHT/default electronic policy.
Use two concurrent four-thread workers with6GiB each and local scratch under
`/home/jojo/.cache/nadoc-qm/cpd-anti-relaxed-continuation-v2`, rather than four
workers contending on the archive disk. Local disk initially has34GiB free;
each task refuses to start below15GiB free. Prior scratch was about4.3GiB per
unfinished job. Service cap20GiB, no swap,24h hard limit,6h expected/9h overdue.
Scratch is retained on failure; old raw evidence is untouched. Corrected watcher
retains pidfd exit evidence. Native launch/status and independent watcher checked.
No cloud use or parameter promotion; matched constrained MM comparison remains
pending after the required QM geometries.

## Continuation failure review and tighter follow-up — 2026-09-22

Acknowledged v2 failed token7ba6f8e7-4090-4bac-bcc1-f11283bcf656. All three
native runs failed at50 optimizer iterations, not missing input or disk space.
Verified native output hashes against run manifests. The wrapper attempted a
geometry audit after failed native execution and obscured the cause with absent
optimized.xyz; it now reports native failure and its manifest before auditing.
Endpoint2+15 meets force criteria but misses maximum displacement; the other
two retain larger residual forces. Local scratch reduced50-step runs to about
1h53–2h15; no new constrained convergence or minimum certification.

Prepared fresh screened last-evaluation-coordinate continuations. v3 used an
invalid CPHF_CONVERGENCE option and failed immediately before QM; preserved.
Corrected v4 uses installed-Psi4-verified CPHF_R_CONVERGENCE=1e-10,
SCF E/D=1e-12, GEOM_MAXITER=150. The GAU_TIGHT geometry criteria, MP2 method,
basis, frozen core, fixed torsion and chemistry remain unchanged. This is an
explicit campaign override recorded with hashes in each new job manifest,
not the unmodified registered protocol. v4 has two4-thread6GiB workers,
local versioned scratch,20GiB service cap/no swap,24h hard cap,8h expected
and12h overdue. v2 and v3 raw failures remain intact; v1 successful point reused.
The independent watcher is armed. Progress snapshot reflects the new attempt.

## Post-reboot recovery — 2026-09-23

System journal records v4 stopped during host shutdown Sep22 at19:08:06 MDT;
current boot began19:08:24. No QM workers or watcher survived. Preserved stale
running status and journal; reconciled v4 as interrupted, not completed.
Endpoint1+15 last completed step47 still had substantial force residual;
endpoint2−15 step46 remained unconverged. Endpoint2+15 never started.

Prepared v5 from the latest printed evaluation geometries of the two interrupted
points, retaining the queued point's original v2 native seed. All three pass
atom-order, covalent-distance, tetrahedral-sign and fixed-angle screens. This is
a fresh optimizer history; no false binary-checkpoint restart claim. Successful
v1 endpoint1−15 is still reused. Retain v4 method/SCF/optimizer settings and
resource limits: two4-thread6GiB workers, local scratch,20GiB service cap,
24h hard runtime,8h expected/12h overdue. New independent watcher pins the
installed26.917.62051 Codex executable; original thread retained. v5 native
start and armed watcher verified. Progress snapshot updated.

Numerical caveat discovered during recovery: despite the global
CPHF_R_CONVERGENCE=1e-10 setting, v4 native CGR output converged near1e-6.
Do not claim a verified1e-10 MP2 response solve from that option alone.
Native response tolerance must be resolved before fine energy/gradient
comparisons; resumption does not promote these geometries or certify minima.

## Adaptive optimization update — 2026-09-23

Literature review and implemented policy are in `docs/cpd_optimization_strategy.md`.
Added experiment-only per-evaluation stall/excursion/nonfinite/budget detection,
evaluated-geometry/gradient checkpoints, and bounded native adaptive trust/backsteps.
Five unit tests and a real Psi4 smoke optimization passed. Retrospective v5 replay
flags failures at16/36steps; these are diagnostic heuristics, not proof or minimum
certification. Stopped remaining v5 after repeated excursions and preserved its
outputs/status. v6 is a single endpoint2+15 pilot from screened near-converged v2,
with other points held. Uses actual SOLVER_CONVERGENCE control; native verification
required. Independent watcher pins current executable; progress snapshot updated.
No cloud use or geometry/parameter promotion. Recovery ladder beyond bounded
native backtracking remains a reviewed next step, not an automatic retry loop.

## v6 reviewed, v7 bounded pilot — 2026-09-23

Acknowledged tokendc8cdb0a-8dcc-4105-8090-780ec52e25e2. v6 native output hash
verified; diagnostic guard stopped at14 evaluations for sustained excursion.
Response residuals now reach<1e-10, but trust/backtracking controls had silently
used defaults due to option aliases. Corrected and added effective-option checks
before the first gradient. Six unit tests and a constrained native smoke passed,
including the trust cap and fixed angle. Prepared/started v7 from the same
screened near-converged v2 seed with immutable guard snapshot and same resource
bounds. No other point launched, no cloud spend, no minimum certification.
See `docs/cpd_optimization_strategy.md` for evidence and limitations.

## v7 bounded failure; gradient-consistency diagnostic — 2026-09-23

Acknowledged failed token9e488ffc-677b-452f-8f1b-cdec1fe272b5. Verified native
output hash, intended option values, trust cap<=0.1 and response residuals<1e-10.
V7 exhausted its permitted backsteps/dynamic level after25minutes, with9 post-step
records plus the final evaluated checkpoint saved before the failing step.
This bounded failure is not convergence; the lowest-force/lowest-energy point
remains the first evaluation. No further optimization extension launched.

Prepared `cpd-anti-gradient-consistency-v1`, controlled by its corresponding
service-v1. Five fixed-geometry MP2 gradients: repeat first v7 checkpoint and
central±0.002/±0.001bohr displacements along the first optimizer displacement,
projected tangent to the frozen torsion at the reference. Coordinates are
straight-line finite differences, not exactly constrained optimized points.
All prepared points preserve tetrahedral signs, covalent lengths within1% of
reference and target dihedral within0.01degree. Native electronic settings match
v7, including verified SOLVER_CONVERGENCE. Two4-thread6GiB workers, local scratch,
20GiB cap/no swap,2h hard runtime,30min expected. Assessment reports repeat-gradient
and energy differences, analytic versus finite-difference directional derivative,
and two-step directional curvature; no automatic stationarity/minimum acceptance.
This checks local energy-gradient consistency before any alternative optimizer.

## Gradient-consistency assessment recovery — 2026-09-23

Acknowledged failed token7126d759-1f27-4ba3-9e49-0d866d8546c2. All five native
jobs returned0 with finite results; failure was postprocessing broadcasting a
49x3 array against the saved147-vector. Corrected assessment-only entry point
reshapes explicitly and reuses all native results, checking input/output hashes.
Original failed service status is retained with recovery annotation. A synthetic
quadratic regression verifies flattened-reference handling, reused reference,
configurable steps, derivative and curvature (1test passed).

Recovered repeat-gradient max difference2.51094e-7 au, energy difference−5.23e-12Eh.
Analytic directional derivative−8.15816e-7Eh/bohr; finite differences at0.002/0.001
bohr are−3.33955e-6/+1.06247e-5. Gradient-difference directional curvatures
0.00145445/0.00153225Eh/bohr². Small-step energy derivatives are inconsistent;
this is not a demonstrated gradient bug or certified stationarity.

Launched four larger-step probes±0.02/±0.01bohr in gradient-consistency-v2,
reusing v1 reference (no duplicate reference QM). Same screened direction,
electronic method/tolerances and resource bounds. All seeds preserve stereo,
bond distances and near-target angle checks. This tests whether small energy
differences/noise dominate; larger-step anharmonicity remains a possible limitation.
No optimizer extension or minimum certification. Independent watcher armed.

## Larger-step consistency results and alternative optimizer — 2026-09-23

Acknowledged complete token59397f44-7c0f-4b46-9869-b0b2f472f2bc. Four native
jobs returned0; verified input/output hashes and response residuals<=1e-10,
plus the reused reference hash. At0.02/0.01bohr, finite-difference energy slopes
are−8.03391e-7/−3.21916e-7Eh/bohr versus analytic−8.15816e-7. Directional
gradient curvatures0.00146240/0.00146274Eh/bohr² agree to0.023%. Improved but
step-sensitive energy slopes suggest numerical-resolution sensitivity; not proof
of complete gradient consistency, constrained positive Hessian, or minimum.

Installed geomeTRIC1.1.1 with no dependency changes under isolated artifacts
`cpd-geometric-runtime-v1`; package Python sources hash-pinned in pilot plan.
Primary implementation/constraint documentation reviewed. Prepared one
`cpd-anti-geometric-pilot-v1` using the same49-atom endpoint2+15 seed, chemical
graph and QM method/tolerances; reused the verified reference gradient. TRIC,
exact-constraint enforcement enabled, trust0.02Å max0.05Å, GAU_TIGHT,
40-evaluation budget (including reused evaluation), single4-thread6GiB worker,
local scratch,12GiB service cap,4h hard runtime. geomeTRIC displacement/force
metrics differ from OptKing's internal-coordinate metrics; do not equate named
threshold sets numerically. Every requested geometry is screened for graph,
stereo and frozen dihedral; every computed gradient is saved with native hashes.
No full Hessian or harmonic certification is implied by eventual convergence.

Constrained HF/STO-3G peroxide integration smoke converged in9 evaluations with
zero reported torsion error and passing bond screen. First smoke stopped on
provenance check because setup kept writing the reference log after hashing;
preserved it, fixed the test setup and reran in a new root. Production reference
comes from a separate completed immutable job. Alternative pilot and independent
watcher launched, no duplicate OptKing retry or cloud spending.

## Alternative optimizer pilot completion — 2026-09-23

Acknowledged complete token96ce3510-ef32-400f-bc9a-6eaa389f9fc7. geomeTRIC
endpoint2+15 converged in1474seconds,10 evaluations (9new,1reused). Verified
all result/native/geometry hashes, response residuals<=1e-10, optimizer log,
and final coordinates against the last evaluated gradient. Frozen torsion
error6.6e-11degrees; stereo and covalent screen pass. Independent Cartesian
projection onto the frozen-dihedral tangent gives maximum atom force norm
4.10155e-6 and RMS1.28646e-6 au, below the selected thresholds; numerical
constraint Jacobian step-halving difference1.84e-10relative. Trust contracted
near the numerical floor, and tiny energy increases persisted, so do not treat
convergence as a full resolution of energy noise or Hessian/minimum certification.
Evidence: `cpd-anti-geometric-pilot-v1/independent_review.json`.

Launched the remaining endpoint1+15 and endpoint2−15 in
`cpd-anti-geometric-pair-v1`, under one20GiB bounded service. Seeds reuse the
screened v4 preparation (last evaluated v2 coordinates), avoiding the worse
late OptKing iterates. Graph, atom order, stereo, bond and frozen-angle seed
checks pass. Same geomeTRIC/TRIC, MP2/basis/tolerances, exact-constraint handling
and40-evaluation per-point budget. Two separate4-thread6GiB workers, local
scratch,4h hard runtime; retain independent outcomes and completion watcher.
Completed endpoint1−15 and endpoint2+15 are not recomputed. No cloud spending,
no harmonic-minimum claim or parameter/DNA gate promotion.

## GeomeTRIC pair partial completion — 2026-09-23

Acknowledged failed token79b690a4-de4c-4885-af5c-549566fc8c7b. Failure is partial:
endpoint2−15 converged in19evaluations; endpoint1+15 exhausted40evaluations.
Verified59 native gradient/geometry/result chains and response residuals<=1e-10.
Independent frozen-dihedral-tangent projection confirms endpoint2−15 max atom
norm8.01392e-6/RMS3.00744e-6au; final geometry matches evaluated gradient and
passes stereo/bond/frozen-angle checks. This is constrained stationarity, not a
certified Hessian minimum. Three of four constrained points now converged.

Endpoint1+15 remains unconverged (independent projected max6.02769e-5,
RMS2.28322e-5au). Unlike prior runaway/stalled OptKing attempts, recent native
steps show decreasing energy with predicted/actual quality near1.3–1.6, supporting
a bounded continuation. v2 replays the40 saved gradients only at matching
coordinates (max difference<1e-10bohr), rebuilding optimizer history without
claiming a binary restart; any unmatched coordinate requires new native QM.
At most40 new gradients and80 total evaluations, same tolerances/constraints,
one4-thread6GiB worker,12GiB cap and4h hard runtime. Prior attempts immutable.
Replay integration smoke reconstructed the constrained peroxide run with all9
saved evaluations and zero new QM. Independent completion watcher armed.

## Fourth constrained point complete; matched MM campaign — 2026-09-23

Acknowledged complete token8f3455b6-b640-418a-ad64-60d335ebbb3d. Endpoint1+15
converged after56 total evaluations:40reused and16new gradients. Verified all
result/native/coordinate hashes, new response residuals<=1e-10, and final
coordinate agreement with its evaluated gradient. Independent tangent-projected
maximum atom norm4.05579e-6/RMS1.67332e-6au passes; geometry screen and frozen
angle pass. All four±15° constrained QM points have optimizer convergence,
not unconstrained or constrained-Hessian minimum certification.

Prepared/launched `cpd-anti-matched-mm-v1` under its service-v1:24 local MM
relaxations = four unchanged candidate systems × two endpoints × three target
angles (reference and±15°). Same target torsions and screened QM starting
coordinates. geomeTRIC/TRIC handles exact constraints, OpenMM Reference supplies
energies/analytic gradients. Per-system finite-difference component checks validate
unit conversion; each trial screens stereo/bonds/angle. MM convergence uses
stricter projected force thresholds (max5e-7/RMS2e-7au) and200-evaluation budget.
Hash-pinned MM systems; no parameter fitting or promotion. Assessment will compare
relaxed MM relative energies with existing QM differences, keeping failed cases.
Endpoint1−15 QM retains older default electronic tolerances, so this is exploratory
matching rather than fine-precision numerical equivalence. No cloud use.

## Matched MM completion and reference-basin check — 2026-09-23

Acknowledged complete token5f5caeba-4c6c-433d-a2ee-7a93202099d6. All24 matched
MM cases converged. Independent review reconstructs each hashed OpenMM system,
verifies native convergence, final atom order/geometry, recomputes energy and
projects the final gradient against the dihedral constraint; all satisfy selected
max5e-7/RMS2e-7au thresholds within output precision. This remains constrained
stationarity, not positive-Hessian or global-minimum certification.

Relaxation removes most large rigid-probe penalties but leaves energetic errors.
Endpoint2+15 QM relative+0.41968kcal/mol versus MM−1.3320 to−1.5463 across the
four candidates (error−1.7517 to−1.9659). Other errors range+0.4001–0.8832.
QM endpoint1−15 is−0.12730 relative to its original reference. These sign/ranking
changes motivate checking reference-basin dependence before compensating fits.

Launched16 MM reference-torsion multistarts: four candidates × two endpoints ×
two neighboring optimized MM geometries, rigidly back-rotated about the same
N1–C1' axis using the existing17 sugar-atom mapping. Seed checks compare stereo
against actual neighbor coordinates, verify atom order and target angle/bonds.
Then relax at the exact reference torsion with unchanged MM systems. Compare
energies with the original MM reference relaxation; preserve all failures and
avoid claiming global minima. Native results and independent watcher remain
under `cpd-anti-mm-reference-multistart-v1`/service-v1. No charges, force-field
parameters or normal-app geometry changed; no cloud spending.

## MM reference-basin result and QM check — 2026-09-23

Acknowledged complete tokenf9b03eb6-f83a-46df-81c0-fdb3fbcbd13b. All16 MM
reference multistarts converged. Independent OpenMM energy/constraint-projected
force, atom order, stereo, bond and native-convergence checks pass. Energy changes
relative to original MM references are at most9.45e-9kcal/mol in magnitude.
These tested starts do not explain the1.75–1.97kcal/mol endpoint2+15 mismatch;
this is not a proof of a unique or global MM minimum. Parameters remain unchanged.

Prepared/launched two QM reference-torsion checks in
`cpd-anti-qm-reference-multistart-v1`: endpoint1 from its−15° optimized neighbor,
endpoint2 from its+15° optimized neighbor, back-rotated using the established
17-atom sugar group and N1–C1' axis. Seed stereo checked against both actual
neighbor and original reference, plus exact reference torsion and graph distances.
Reference source hashes retained. Same bounded geomeTRIC/TRIC plus tight MP2
settings,40evaluations each, two4-thread6GiB workers,20GiB cap,4h hard runtime.
This probes QM reference-basin dependence, especially the negative endpoint1−15
relative energy, before fitting torsion corrections. No duplicate completed
reference run, harmonic certification, release gate or cloud spending.


## QM reference budget review and bounded continuation — 2026-09-24

Acknowledged failed token5ef0442b-c1ee-4538-bc51-57d53fe11d13. Both v1 checks
exhausted their40-evaluation budgets, without electronic calculation failures.
Independent review verified all80 result/native/coordinate hash chains, geometry
screens and MP2 response residuals<=1e-10. Last energies remain above original
references by0.0024035 and0.0097199kcal/mol for endpoints1 and2. Recent steps
continue descending; these results establish neither convergence nor a lower basin.
Original failures and native outputs remain preserved.

Launched `cpd-anti-qm-reference-multistart-v2` with two4-thread6GiB workers,
20GiB service cap and4h hard runtime. Each reconstructs optimizer history from
40 hash-verified saved gradients and permits at most40 new evaluations (80 total).
Same physics, convergence thresholds, constraints and trust limits. Explicit unique
local scratch paths avoid collisions between identically named child tasks across
versions. Completion watcher armed; progress visualizer updated. No parameter
promotion, minimum certification or cloud spending.


## QM reference checks complete; relaxed midpoint profile — 2026-09-24

Acknowledged complete tokena3b37222-9efb-49d0-bd56-9334771d1c0f.
Both reference-torsion checks converged: endpoint1 used63 evaluations (40 replay,
23 new); endpoint2 used55 (40 replay,15 new). Independent review checked every
result/native/coordinate hash, response residual<=1e-10, final coordinate agreement,
stereo/bond/constraint screen and native convergence. Projected maximum atom
 gradients are4.7272e-6 and9.4308e-6au; RMS1.3005e-6 and2.5012e-6au.
Energy differences from original references are+0.00000723 and−0.00001524kcal/mol.
These starts do not explain the MM energetic mismatch. This is constrained
stationarity; neither global basin uniqueness nor positive-Hessian certification.
Original failed budget-limited attempts remain preserved.

Launched `cpd-anti-relaxed-half-v1` / `cpd-anti-relaxed-half-service-v1`:
four ±7.5° points seeded by rigid rotation of the established17-atom sugar group
from the converged reference checks. Seed bond distances and stereochemistry
checked against actual reference coordinates. Same tight MP2/6-31G(d), TRIC,
constraints/trust limits;60-evaluation cap each, two4-thread6GiB workers,
20GiB service cap,8h runtime limit. Four tasks run two at a time. The added
midpoints will resolve profile shape before torsion fitting; parameters unchanged.
Independent completion watcher armed; progress view updated. No cloud spending.


## Midpoint partial completion and continuation — 2026-09-24

Acknowledged failed token5d4b46d3-e19d-43ce-9ba4-0df0310a15c4. Three of four
QM points converged: endpoint1+7.5 (54 evaluations), endpoint2−7.5 (50),
endpoint2+7.5 (53). Independent native/hash/response/geometry and projected-gradient
review passes, saved in `cpd-anti-relaxed-half-v1/independent_review.json`.
Maximum projected atom gradients are7.4933e-6,3.8061e-6,2.8561e-6au respectively.
Endpoint1−7.5 exhausted60 evaluations. Last projected RMS5.1608e-6/max1.2863e-5au
passes force thresholds but maximum displacement7.397e-5Å fails GAU_TIGHT;
recent force improvement supports bounded continuation, not a convergence claim.
All217 evaluated QM points passed native response and geometry checks.

Launched `cpd-anti-relaxed-half-v2`/service-v2 for only endpoint1−7.5:
replay60 saved gradients, at most40 new, unchanged thresholds and physics,
one4-thread6GiB worker,12GiB service cap,4h hard limit. Prior failures preserved.
Also running12 matched MM relaxations for the three verified midpoint QM points
and four unchanged candidate systems under `cpd-anti-matched-half-mm-v1`.
Reference MM energies reused from the prior verified campaign; no duplicate QM
or parameter promotion. These checks do not certify positive Hessian curvature.

All12 matched midpoint MM relaxations converged and passed independent native,
energy, projected-gradient, atom order and geometry checks. Errors across four
candidates: endpoint1+7.5 [0.32634, 0.36449] kcal/mol. Full per-case errors saved in matched-half-mm-v1/assessment.json.
No fitting performed pending the fourth midpoint. Continuation verified60 replayed
evaluations and new native work, with independent watcher active.


## Complete midpoint profile and outer validation — 2026-09-24

Acknowledged complete tokenc5212850-ab97-402c-b06f-3a3b3cb8fa09. Endpoint1−7.5
converged after66 evaluations:60 replayed plus6 new. Independent native, hash,
response, final geometry and projected-gradient checks pass (maximum1.1061e-5,
RMS4.5559e-6au). All four midpoint points now have constrained optimizer
convergence; no Hessian certification. Original failed run remains preserved.

Completed four additional MM cases in `cpd-anti-matched-half-mm-v2`, with independent
energy/gradient/geometry checks passing. All16 midpoint MM cases are verified.
`cpd-anti-local-profile-diagnostic-v1` combines these with the existing ±15 profile.
For each unchanged candidate/endpoint, an exploratory correction
 a*(cos(delta)-1)+b*sin(delta) trained only on ±15 predicts held-out ±7.5 residuals
within0.089kcal/mol. This is a local energy diagnostic, not accepted force-field
parameters: it creates nonzero reference torque and unconstrained global periodic
ranges32.7–37.2kcal/mol. Coupled equilibrium geometry and wider angular coverage
are not validated. No charge or torsion parameters promoted.

Launched `cpd-anti-relaxed-outer-v1`/service-v1 with four ±30° points, seeded from
completed ±15° QM neighbors by another15° rotation of the established sugar group.
Actual target offsets, unchanged bond lengths and stereo against each actual
neighbor checked. Same tight MP2 and bounded TRIC settings,60 evaluations each,
two4-thread6GiB workers,20GiB service cap,8h runtime limit. This tests extrapolation
before coupled torsion fitting. Watcher armed, progress view updated; no cloud use.

Demo pause/resume: outer-profile service and watcher frozen at user request;
resumed2026-09-24T20:02UTC with original QM processes intact. Runtime and watcher
deadlines extended by10591 seconds of pause; no duplicate QM jobs launched.
Exact timestamps and service state retained in service-v1/demo_pause.json.


## Outer-angle QM complete — 2026-09-25

Acknowledged complete token866daf66-18b1-4b7f-8c4e-c6179d56e743. All four
±30° points converged (endpoint1−/+54/58 evaluations; endpoint2−/+58/52).
Independent review verifies all222 native/result/coordinate hash chains,
response residuals<=1e-10, geometry constraints/stereo/bonds, final coordinate
agreement and native convergence. Projected maximum gradients6.131e-6,
7.008e-6,4.241e-6,4.470e-6au respectively. Constrained stationarity only;
no Hessian or global minimum certification.

Running16 matched MM relaxations against four unchanged systems under
`cpd-anti-matched-outer-mm-v1`. Previously fitted local ±15° residual correction
is frozen for evaluation on ±30° points; no outer data refit. Independent
force-group decomposition will describe relaxed energy contributions without
claiming causal attribution. Original failures and all parameter candidates retained.


All16 outer MM relaxations converged and passed independent energy, projected
force and geometry checks. `cpd-anti-outer-profile-review-v1` evaluates the frozen
local correction without refitting: residual ranges(kcal/mol), endpoint1+30
−1.384 to−1.339; endpoint1−30 −0.477 to−0.451; endpoint2+30 +0.795 to+0.830;
endpoint2−30 +0.031 to+0.055. Thus the midpoint diagnostic does not establish
outer-angle accuracy. Force-group differences sum to independently recalculated
relative MM energy; decomposition retained as descriptive evidence only.

Launched16 outer MM multistarts in `cpd-anti-outer-mm-multistart-v1`/service-v1,
using each candidate's optimized ±15 MM neighbor rotated to the exact ±30 target.
Seeds screened against both actual neighbor and existing QM stereo. Compare with
original outer MM relaxations before broader torsion fitting; all parameters fixed.
Single-thread local MM,4GiB cap,1h limit, independent watcher. No cloud use.


## Outer MM basin agreement and broader torsion screening — 2026-09-25

Acknowledged complete token56673b9b-d749-4302-bd73-3edd156918f1. All16 outer
MM multistarts converged and independently passed energy/gradient/geometry checks.
Largest absolute energy difference from original outer relaxations2.6293e-8kcal/mol.
These tested starts do not explain profile mismatch; no global minimum claim.

`cpd-anti-broad-torsion-diagnostic-v1` compares n=1,2 Fourier residual models,
free torque versus analytically zero reference torque, trained on ±15/±30 with
±7.5 held out. Predeclared ridge sweep0.0001/0.01/0.1 and coefficient bounds±10
(kcal/mol; transformed sin1 can reach20 in zero-torque family). No fit accepted by
held-out tuning. Endpoint2 zero-torque fits have substantially larger residuals.

Ran `cpd-anti-torsion-geometry-v1`/service-v1: all four candidates, two endpoints,
two torque families at fixed ridge0.01. Isolated OpenMM CustomTorsionForce overlays;
angle convention checked against actual geometry and force finite differences.
Unconstrained L-BFGS geometry screening from original MM minima, no CHARMM export.
All16 attained maximum force<0.001kcal/mol/Å and stereo/bond checks pass. Endpoint2
moves about19–20° for free-torque fits and47–50° for zero-reference-torque fits.
Endpoint1 moves about5–8°. The zero-torque condition refers to the QM reference
angle, not necessarily the original MM minimum. These shifts require further
coupled validation; energy-fit improvement is not geometry acceptance. No Hessian
certification, charge acceptance, full DNA test or parameter promotion. Watcher
and visualizer updated; originals and all trial failures retained. No cloud use.


## Independent torsion geometry audit and remote wells — 2026-09-25

Acknowledged complete tokendd065509-d313-4255-a7a9-877c2102c87b. Independent
reconstruction of all16 serialized trial systems confirms max force<0.001
kcal/mol/Å. Internal MM Hessians at1e-4 and5e-5Å displacements are positive
for all16 after removal of six rigid modes. This supports local MM minima only,
not QM certification, global minima, transferability or release acceptance.
Training geometry comparison: endpoint1 maximum angle errors2.72–2.93°;
endpoint2 free-torque3.61–3.62° and zero-torque5.97–6.08°. Endpoint2 maximum
bond errors0.0301–0.0386Å. Thus the endpoint2 trials degrade prior geometry gates.
Evidence saved in torsion-geometry-v1/independent_review.json; failures preserved.

Crucial scope correction: original baseline endpoint2 MM torsion177.9226°
versus QM reference84.4659° (difference93.4567°). The earlier training bond/angle
success did not imply torsion or full conformational agreement. Endpoint1 original
MM/reference difference−3.5476°. Local residual fits around the QM reference
cannot establish behavior at the distant endpoint2 MM well. Zero-reference-torque
is defined at the QM angle, not the original MM minimum.

Launched `cpd-anti-remote-wells-v1`/service-v1: two constrained endpoint2 QM
relaxations seeded from baseline MM minimum and baseline zero-torque trial minimum,
at each actual glycosidic angle (about178° and131° respectively). Both seed graphs,
bonds and stereo screened against QM reference. Tight MP2/6-31G(d),60 evaluations
per point, two4-thread6GiB workers,20GiB service cap,6h runtime limit. These compare
remote conformations before further fitting; no unconstrained QM minimum claim.
No parameter or normal-app geometry promotion. Watcher and progress view updated;
no cloud spending.


## Remote-well budget review and continuation — 2026-09-25

Acknowledged failed tokend1b0ddfa-708b-4734-a722-fd268b7dade9. Both remote
points exhausted60 gradient evaluations; no native electronic failure. Independent
review of all120 result/native/coordinate chains and geometry screens passed,
including tight response residuals. Last projected max/RMS atom gradients:
baseline-well3.938e-6/1.424e-6au; zero-torque-well9.237e-6/3.561e-6au.
Forces pass GAU_TIGHT, but displacement convergence has not been attained.
Baseline-well recent energy changes are noise-scale with alternating trust updates;
zero-torque-well has recently improving forces. No optimizer convergence claimed.

Current energies relative to the original endpoint2 reference are−7.08002 and
−0.76032kcal/mol respectively. These establish lower-energy evaluated
conformations, not unconstrained or constrained-Hessian certified minima. In
particular, the original QM reference must not be assumed to be the global well
when fitting away the remote MM preference. Further fitting remains deferred.

Launched `cpd-anti-remote-wells-v2`/service-v2:60 hash-verified cached gradients
replayed per point, at most20 new evaluations each (80 total), same thresholds,
constraints and electronic settings. Two4-thread6GiB workers,20GiB cap,3h hard
runtime. Old failures immutable; watcher armed and visualizer updated. No cloud
spending or parameter promotion.


## Remote constrained convergence; restraint release — 2026-09-25

Acknowledged complete token4adeddb3-9153-43ea-8f0e-7c5a31b93015. Both remote
points converged: baseline-well61 evaluations (60 replay+1 new), zero-torque-well62
(60 replay+2 new). Independent native/hash/geometry/response review passes;
projected maximum atom gradients5.970e-6 and6.418e-6au. Relative energies remain
about−7.08002 and−0.76032kcal/mol versus original endpoint2 reference. These are
constrained stationary conformations, not certified unconstrained minima.

Added explicit opt-in `freeze_torsion=false` to isolated geomeTRIC worker; default
constrained behavior unchanged. Bond/stereo screens retained; angle drift permitted
only for the unconstrained mode. Review uses full gradients in this mode. Native
peroxide HF smoke first exposed geomeTRIC1.1.1 conmethod1 incompatibility without
constraints (zero QM evaluations, failure preserved); corrected free-run plans omit
constraint-specific conmethod/enforce options. Smoke v2 converged11 evaluations,
full maximum atom gradient1.528e-7au and35° torsion drift, confirming actual release.

Launched `cpd-anti-remote-unconstrained-v1`/service-v1 from the two verified remote
geometries. Each reuses its last hash-verified gradient, then permits60 new
calculations. Same tight MP2/6-31G(d), two4-thread6GiB workers,20GiB service cap,
6h hard runtime. Hessian work waits for full-gradient unconstrained convergence.
No parameter promotion, cloud spending or global-minimum claim. Watcher armed,
progress view updated; original failures preserved.


## Remote unconstrained convergence and Hessian — 2026-09-25

Acknowledged complete token80bb0bc3-265a-4800-9734-3729450bdf45. Both remote
starts converged unconstrained:30 and39 evaluations, each including one reused
gradient. Independent native/hash/response/geometry/final-coordinate checks pass;
full (not constraint-projected) maximum atom gradients4.195e-6 and4.561e-6au,
RMS9.364e-7 and1.430e-6au. Existing review field names retain 'projected' but
freeze_torsion=false explicitly selects the full gradient in the implementation.
Aligned all-atom RMS difference0.0003544Å, energy difference3.95e-6kcal/mol,
final glycosidic angles−168.4701/−168.4775°. Both are about7.58404kcal/mol below
the original endpoint2 reference. This demonstrates lower unconstrained stationary
conformations; a global minimum is not established.

Prepared one Hessian at baseline-well-derived stationary geometry to avoid duplicate
calculation for indistinguishable conformations. `cpd-anti-remote-frequency-v1`
has289 independent gradient tasks (reference plus288 displacements). Same existing
frequency protocol1.7.0 and MP2/6-31G(d), with its default electronic convergence
settings (not the extra-tight optimizer settings). Tight soft-mode follow-up is
required for ambiguous curvature, as in earlier certification campaigns. No
Hessian/minimum pass asserted before native assembly and audit.

Launched `cpd-anti-remote-hessian-service-v1`: established four4-thread3GiB worker
layout on CPUs0–15,18GiB service cap,16h runtime limit, resumable per-task outputs.
Independent watcher active, progress view updated. Charges/torsions remain
unaccepted pending reference-state reassessment; no cloud spending.


## Remote Hessian harmonic audit and soft-mode follow-up — 2026-09-25

Acknowledged complete tokenbbe934f0-ad3b-483e-a644-01dc1a04964e. Hessian batch
finished289 tasks in5.84h. Independent review rechecked every task's input/result/
run-record hash, plan identity, native success and finite147-component gradient;
assembled Hessian, native output and run manifest hashes verified. Frequency audit
passes candidate harmonic minimum:141 projected positive modes, zero imaginary,
lowest14.9846cm−1. This supports a local harmonic QM minimum at MP2/6-31G(d),
not a global minimum, accepted CHARMM parameters, or DNA validation.

Launched `cpd-anti-remote-soft-mode-v1`/service-v1 using established soft-mode
protocol: tight reference plus ±0.04 and±0.02bohr along the lowest projected
mass-weighted mode transformed to a normalized Cartesian direction. SCF E/D1e-12,
response solver1e-10. Tests force at reference, positive gradient-difference
curvature and<=10% step-halving disagreement. Three4-thread3GiB workers,
14GiB service cap,2h hard limit. Exact lowest-mode stiffness remains provisional
until this independent directional check, which does not replace a full Hessian.
Watcher active; visualizer updated. No cloud spending or parameter promotion.


## Remote soft-mode consistency failure — 2026-09-25

Acknowledged failed tokenbaccc3f0-2f39-4578-b1ad-0ff629f4f97c. All five native
calculations completed and independently verified input/plan/native/result hashes,
finite gradients and actual final response residuals<=1e-10. Reference maximum
component force2.558e-6au passes. Directional curvatures are positive:
1.1323492e-4 at0.04bohr and9.9591082e-5 at0.02bohr (Eh/bohr²). Step-halving
relative difference0.120491 fails the unchanged0.10 criterion. Original Hessian
curvature4.6632687e-5 is substantially smaller. Harmonic positive-mode evidence
remains, but the numerical soft-mode validation failed; precise stiffness and
robust minimum qualification remain unresolved. No negative curvature observed.

Launched `cpd-anti-remote-soft-resolution-v1`/service-v1: five new tight gradients,
±0.01/±0.08bohr along the same saved direction plus repeat reference. Prior five
results are hash-referenced, not rerun or overwritten. Four-scale trend and repeat
noise diagnostic only; no automatic acceptance by selecting a favorable pair.
Same tight settings, three4-thread3GiB workers,14GiB cap,2h runtime. Original
failures preserved. Watcher and visualizer updated; no cloud or parameter promotion.


## Four-scale soft-mode evidence and conformer electrostatics — 2026-09-25

Acknowledged complete token1cc40ead-26e1-48aa-94d8-49fc1faaa7d2. Independently
verified all10 old/new native result/input/plan hashes and response residuals;
recomputed the four directional curvatures. At0.01/0.02/0.04/0.08bohr:
9.9851203e-5,9.9591082e-5,1.1323492e-4,1.1418131e-4Eh/bohr², all positive.
Smallest pair agrees0.2605%; largest pair0.8288%; middle pair still fails12.0491%.
Reference repeat projected-gradient difference9.284e-9au (maximum Cartesian
component difference1.569e-7au), energy difference−2.956e-12Eh. Reference repeat
noise does not establish error bounds at displaced geometries. Two different
curvature plateaus and default-Hessian stiffness discrepancy remain unexplained.
The original failed10% gate is not relabeled passed. Combined with the positive
full harmonic spectrum and unconstrained stationarity, this strengthens local
minimum evidence; precise soft stiffness and full tight-Hessian qualification
remain provisional. No global minimum or force-field acceptance claim.

Launched `cpd-anti-remote-esp-v1`/service-v1 to add HF/6-31G(d) ESP and dipole
targets at the lower-energy endpoint2 conformation using existing ESP generator
and audit. Original reference-conformer targets retained; not replacing history or
accepting charges. One4-thread3GiB native job,6GiB service cap,2h runtime limit.
Source harmonic audit and unresolved soft-mode review retained in plan. Watcher
and visualizer updated; no cloud spending or parameter promotion.


## Remote electrostatics and three-conformer charge trial — 2026-09-25

Acknowledged complete tokena68013cf-cd17-41a6-bf99-107de46bb204. Verified native
successful run, job/source/output hashes,1274 finite ESP values with matching grid,
and audited dipole vector. Initial audit re-invocation correctly refused to overwrite
existing esp_audit.json; existing evidence was preserved and independently checked.
Frozen baseline and charge1/10/100 predictions have remote ESP relative errors
0.6248/0.4595/0.5418/0.6090 and dipole vector errors1.739/1.204/1.227/1.614D.
This prospective comparison is saved before refitting in remote-esp-v1 review.

Ran `cpd-anti-multiconformer-charge-v1`: adds remote ESP as a third equally weighted
conformer block to existing two ESP and original water-target blocks. Same28 shared
base variables,±0.15e bounds, neutral summed shift, equal methyl-H shifts,
regularization1/10/100; caps/sugar/LJ/bonded terms fixed. All optimizers converged
and charge constraints pass. New target is now training, not held-out validation.
Lowest-regularization remote relative ESP error0.4216 and dipole error0.8775D;
remaining two candidates0.5237/1.0276D and0.6041/1.5555D. Original water maximum
energy errors for lowest regularization are1.14 and1.53kcal/mol by endpoint.
Substantial residuals remain; no candidate selected, exported or promoted.

Launched `cpd-anti-remote-water-calibration-v1`/service-v1: three representative
screened contacts at the new conformer, each evaluated with DF and DIRECT HF using
identical coordinates. Established>=1.1 non-target covalent-radius-ratio screen;
production curves await calibration. Four4-thread3GiB workers,18GiB cap,2h runtime.
Original conformer datasets/candidates retained. Soft-mode numerical limitations
remain explicit; watcher and visualizer updated, no cloud spending.


## Remote water calibration passed; distance curves — 2026-09-25

Acknowledged complete token83ac0f2a-c454-4812-8043-d608a689e65c. Independent
review verified all six DF/DIRECT job/source/water/native hashes, successful
execution and recomputed calibration audit from native data. Three matched sites
pass: errors0.003688,0.004324,0.001783kcal/mol, maximum below0.02kcal/mol limit.
This validates the sampled DF approximation, not force-field charges.

Screened six donor/acceptor site orientations for the lower-energy endpoint2
conformer, distances1.5–2.7Å in0.2Å increments. All six pass non-target separation
>=1.1 covalent-radius sums; least crowded of registered0/120/240° azimuths used.
Prepared42 distance points, with three exact geometry/protocol matches reused
from calibration. Launched39 new native DF HF interaction calculations under
`cpd-anti-remote-water-curves-v1`/service-v1. Four4-thread3GiB workers,18GiB cap,
3h hard limit. Native curve audits follow, then evaluate frozen original and
three-conformer charge candidates before any new fit. Fixed orientation is not
orientation optimization. Original data and soft-mode limitations retained;
watcher and visualizer updated, no parameter promotion or cloud spending.


## Remote water curves: partial scientific pass — 2026-09-25

Acknowledged complete tokenc1c33644-61d0-4e17-8a47-ea974d60ce77. Independently
verified42 job/native/source/water/output hash chains and successful execution;
recomputed six curve audits without overwriting originals. Five bracket minima.
1-O4 fails: all sampled interactions repulsive through2.7Å (+5.543kcal/mol at
outer edge), minimum at grid boundary. Service completion was process completion,
not all_curves_passed. Future remote curve runner now returns failure when audits
fail, while retaining assessments and individual successful results.

Frozen baseline/original charge1 and new three-conformer charge1 give worst
usable-site minimum energy errors3.663/1.461/1.417kcal/mol respectively, with
existing1.16 energy scaling and−0.2Å target-distance offset. All seven frozen
candidate predictions retained in remote-water-transfer-v1/frozen_candidates.json.
Unbracketed1-O4 excluded explicitly; no refit or parameter acceptance performed.

Extension v1 setup requested2.9–4.5Å but generator rejected distances above4.0Å.
Six valid2.9–3.9Å job inputs existed; no native outputs or complete plan existed.
An inadvertently invoked v1 service failed on missing plan, with no native work.
Failure retained in extension-v1/preparation_failure.json. Corrected v2 reuses
those six valid inputs, seven original native outputs and unchanged orientation,
within supported range. Launched extension-service-v2: four4-thread3GiB workers,
18GiB cap,2h limit. Re-audit13-point curve after completion; if still unbracketed,
do not infer a minimum. Watcher/visualizer updated; no cloud spending.

Acknowledged delayed extension-v1 failure wake2355b2bc-9b11-4109-b414-bdeeb45d78b7.
Native launch never occurred in v1 (missing plan). Corrected v2 remains active,
with six new jobs and seven reused points; native outputs progressing and watcher
active. No additional jobs launched in response to the stale notification.


## Extended contact specificity and updated charge trials — 2026-09-25

Acknowledged complete tokenbaca7b30-9e69-4d7b-ba85-40fb349cd06f. All13 points
(seven reused, six new) independently verified by native/hash/source checks;
recomputed series audit now brackets the1-O4 minimum at sampled3.7Å, scaled
interaction−3.4958kcal/mol. However nearest water H1/model contact is sugar2:O5′
at2.5188Å, whereas nominal1:O4 is3.7Å away. Thus this is a mixed-contact minimum,
not a clean nominal O4 target. Preserve it as diagnostic and exclude it from
direct site fitting; contact_review.json records distances. Original failure retained.

Ran `cpd-anti-multiconformer-water-charge-v1`: original three-conformer ESP and
water targets plus five usable remote water curves;1-O4 excluded explicitly.
Same28 charge variables, neutrality/methyl constraints,±0.15e bounds and
regularization1/10/100. Lowest-regularization remote ESP relative error0.4293,
dipole error0.8263D, worst remote water minimum energy error1.2145kcal/mol.
Original endpoint water maxima1.2769/1.5529kcal/mol. These are now training
metrics; preceding frozen transfer measurements preserved. No candidate accepted.

Ran12 isolated charge-only geometry screens in `cpd-anti-charge-conformer-geometry-v1`
/service-v1: three strengths × two endpoints × two starting conformations.
Charges and corresponding nonzero pair exceptions updated consistently; fixed
LJ/bonded terms. Endpoint1 uses original QM/MM starts; endpoint2 original/remote
QM starts. All report stationarity and stereo/bond screen pass. Endpoint2 ends
at different torsions by start (~171° versus179–180°); independent geometry,
force and Hessian validation remains required. No optimizer success is treated
as minimum certification. Serialized trial systems stay isolated; watcher and
visualizer updated, no cloud spending or parameter promotion.


## Independent charge geometry audit and bonded refinement — 2026-09-25

Acknowledged complete tokencb2589ca-dd43-43cd-9c08-238ed5b71f39. Reconstructed
all12 serialized systems; verified final hashes, energy/forces, unchanged bonded
and LJ terms, and consistent charge-product exception rescaling. Internal MM
Hessians at1e-4/5e-5Å both positive for all12, with maximum force<0.001kcal/mol/Å.
Local MM minima supported, not global minima or force-field acceptance. Endpoint1
two starts converge to same minima; endpoint2 remote-derived minima lie1.35–1.57
kcal/mol below original-start minima. Maximum target angle errors endpoint1
2.55–2.60°, endpoint2 original4.36–4.37°, remote5.05–5.24°. Charges alone do not
retain desired geometry quality. Native failure history remains preserved.

Prepared/launched `cpd-anti-remote-coupled-v1`/service-v1. Three multiconformer
charge strengths frozen while jointly refining original core/endpoint1 and the
lower-energy endpoint2 QM geometry. Endpoint2 starts from that actual remote
geometry; original reference retained as separate validation data, not erased.
Existing ordered CPD type aliases, absolute±6° angle/±0.01Å bond-equilibrium
bounds relative to original typed parameters, fixed torsions/LJ,100 optimizer
function evaluations per candidate. Target provenance and unresolved soft-mode
stiffness caveat recorded. Original geometric-fit engine reused through hash-pinned
reference adapter; all reported endpoint2 boundary target angles now correspond
to new geometry. Three single-BLAS-thread fits,10GiB cap,4h limit. Subsequent
independent curvature/export/multiconformer checks required; no release or cloud.

Coupled service-v1 failed before starting any fit because the QM interpreter lacks
ParmEd. Preserved log; relaunched the same prepared inputs via service-v2 with
the repository virtual environment used successfully for preparation and original
MM fitting. No simulation duplication or input regeneration.

Acknowledged delayed service-v1 failure wake7a684d2f-a450-4327-8402-f01723176f09.
Confirmed missing ParmEd import before fit execution. Corrected service-v2 remains
active; strengths10/100 have final training reports and strength1 is still working.
These reports are not independent curvature/export validation. No duplicate fits
launched in response to this stale notification.


## Lower-reference fits verified; retained-profile transfer — 2026-09-25

Acknowledged complete tokenfa448364-5a85-44e4-b1f9-1aa24501ebe1. All three
bounded geometry fits completed. Verified source hashes, optimizer success,
±6°/±0.01Å parameter bounds and reported training geometry/stereo gates.
Maximum endpoint angle errors2.7263/2.7153/2.7022° for strengths1/10/100;
maximum endpoint bond errors<=0.0261Å. Independent reconstruction of all nine
core/fragment systems confirms stationarity, positive projected MM Hessians at
two step sizes, and numerical equivalence with CHARMM PSF/parameter export.
Reports remote-coupled-verify-{1,10,100}-v1 retained; no full force-field acceptance.

Launched `cpd-anti-remote-profile-mm-v1`/service-v1:45 constrained relaxations,
three fixed candidates ×15 existing QM points. Points include both original
references,±7.5/±15/±30 for both endpoints, and new lower-energy endpoint2 minimum.
Old-reference profiles are retained rather than hidden by target replacement.
Same strict MM stationarity/geometry screens and200-evaluation budget per case.
Single-thread native MM,4GiB cap,2h hard runtime. This is retrospective transfer,
not unseen experimental validation; endpoint1−15 retains older electronic settings.
Independent audit follows completion. Watcher/progress view updated; no parameter
promotion or cloud spending.


## Refined profiles: stationarity passes, energy transfer fails — 2026-09-25

Acknowledged complete token7e7f991a-17a9-4900-9e48-03a8d2ac7b24. All45
constrained MM cases independently pass native convergence, system/source hashes,
atom order/geometry, re-evaluated energies and projected force thresholds. This is
constrained stationarity, not Hessian certification of every profile point.

Relative to the respective original-reference constrained relaxations, remote
endpoint2 MM energies are−17.475/−16.987/−16.637kcal/mol for strengths1/10/100,
versus QM−7.584: errors−9.891/−9.403/−9.053kcal/mol. Endpoint2−30 errors are
−9.351/−6.461/−6.625kcal/mol, much larger than prior local-profile results.
Thus training geometry/export success does not establish energetic transfer.
A conformational-basin switch is a hypothesis requiring explicit multistarts;
these relative energies must not silently be treated as global minimum differences.
No candidate accepted and no compensating fit launched from these data.

Launched `cpd-anti-refined-basin-check-v1`/service-v1:18 cases = three refined
candidates × two target angles(original endpoint2 reference and−30) × three MM
neighbor starts. Neighbors are prior constrained minima at−30/+30/remote for
reference target, and−15/reference/remote for−30 target. Existing17-atom sugar
rotation, target/bond/stereo checks against actual neighbors and QM signs; no
parameter edits. Compare to original45-case energies. Single-thread local MM,
4GiB cap,2h limit. Failure evidence retained, watcher/progress view updated; no cloud.


## Refined MM basin dependence confirmed — 2026-09-25

All18 follow-up cases completed and independently passed native convergence,
source/system hashes, atom order/stereo/geometry, energy reconstruction and
projected stationarity. No Hessian certification of these constrained points.
Remote-seeded reference-angle energies are lower than original starts by
4.84849/4.81028/4.90808 kcal/mol for strengths1/10/100. At -30, remote-seeded
energies match strength1 but lower strengths10/100 by2.96882/2.90732 kcal/mol.
Other starts retain higher stationary basins. Thus basin dependence is confirmed;
initial -9.05 to -9.89 relative-energy errors include reference-basin bias and
must not be interpreted as comparisons between global minima. These new references
alone do not eliminate the remote relative-energy discrepancy. Preserve all starts.

Launched `cpd-anti-refined-profile-basin-v1`/service-v1:36 unchanged-parameter
MM cases, three strengths × six remaining endpoint2 targets × two seeds from
lower reference/-30 basins. Exact target rotation, stereo/bond checks against
both neighbor and QM reference, hash-pinned sources. This will characterize the
lowest observed MM profile before deciding whether further QM basin matching or
parameter fitting is justified. Single-thread native MM,4GiB cap,2h hard limit,
20min watcher estimate; no duplicate jobs, cloud spending, or candidate promotion.

Acknowledged delayed basin-check completion wake a9a85420-9305-4639-b214-d7c64192b8b9. Rechecked native outputs and independent stationarity audit:18/18 pass, no minimum certification. Follow-up profile multistarts already active (5/36 completed at review); separate watcher active. No duplicate jobs launched.


## Lowest observed MM profiles; QM basin matching — 2026-09-25

Acknowledged completion token c886fe91-0bf3-4256-b94e-6bc60e65a2ef. All36
remaining-angle MM multistarts pass independent native/hash/geometry/energy/
projected-stationarity audit. These constrained stationary points are not
Hessian-certified. Retained every original and alternate-start result.
`cpd-anti-refined-profile-basin-v1/profile_envelope.json` compares lowest observed
MM energies over original45 plus18+36 multistarts with existing QM points.
After using lower reference basins, remote endpoint2 errors are -5.0424/-4.5926/
-4.1446 kcal/mol (strengths1/10/100), versus initial -9.89/-9.40/-9.05.
At -30 errors remain -4.503/-4.619/-4.624. At +15 errors are +2.356/+2.374/
+2.394. No accepted energy transfer; lowest observed is not a global minimum.

Launched `cpd-anti-refined-basin-qm-v1`/service-v1: constrained MP2/6-31G(d)
DF frozen-core tight electronic settings and geomeTRIC TRIC/GAU_TIGHT, two
starts at original reference and -30 angles using strength1 remote-seeded lower
MM basins. Strength1 chosen for largest remote energy discrepancy, not assumed
representative of all candidate basins. Same atom map/stereo/bond/target screens,
60 evaluations per point,4 threads and6GiB per worker; two concurrent workers,
20GiB service cap,8h hard limit,4h watcher review estimate. No parameter changes.
These decisive QM checks test whether the old QM profile missed corresponding
lower conformers before fitting further. Separate watcher armed; no cloud.


## QM basin checks: one converged, one budget-limited — 2026-09-25

Acknowledged failed wake78ce4402-586c-4d4f-95c6-b4e2b58dfc4f. Service-v1
finished after3.24h; failure is reference-point60-evaluation guard, not SCF failure.
Independent audit verifies all114 native MP2 gradient/source/geometry records.
-30 converged at54 evaluations; projected max/RMS7.485e-6/2.167e-6au,
energy-1364.5176844454218Eh,8.87179kcal/mol below previous same-angle QM.
Thus previous QM scan missed a lower constrained stationary conformer. No
Hessian certification or proof of global minimum. Original evidence retained.
Reference latest energy-1364.5119583781861Eh is3.50790kcal/mol below old
reference but NOT converged: independent projected max/RMS3.775e-5/1.128e-5au.
Recent native gradient/displacement decrease supports a bounded continuation.

Launched service-v2/root`cpd-anti-refined-basin-qm-v2` for reference only:
60 hash-verified cached gradients replayed to reconstruct optimizer history,
80 total/20 new evaluations maximum, unchanged convergence/settings,4 threads,
6GiB worker/10GiB service cap,3h hard limit,70min watcher review estimate.
The successful -30 calculation is referenced and not duplicated. Further
relative-energy fitting waits for reference convergence; no cloud/promotion.


## Lower-basin QM reference converged — 2026-09-25

Acknowledged complete wakee185c845-c91c-46d2-8c40-cc853e5b34de. Independent
native/hash/stereo/geometry/gradient audit passes:67 evaluations,60 reused/7 new,
energy-1364.5119583961437Eh, projected max/RMS1.47248e-5/4.35294e-6au.
Native GAU_TIGHT convergence and independent thresholds pass; no Hessian or
unconstrained/global-minimum certification. Reference is3.507914kcal/mol below
old same-angle QM. Combined with converged -30, QM relative energy is-3.593150
kcal/mol; lowest observed MM errors now+0.86090/+0.74441/+0.73977 for strengths
1/10/100. Remote QM is-4.076126 relative to updated reference, leaving MM errors
-8.55019/-8.10079/-7.65294. Earlier comparisons used an obsolete QM reference;
all historical results retained. Exact full-conformer correspondence and global
minima remain unproven. No candidate accepted or parameter refit yet.

Launched `cpd-anti-lower-basin-profile-v1`/service-v1: two constrained QM points
at -15/+15 from the newly converged QM reference, screened17-atom sugar rotations
against seed and original QM stereo/bond/target geometry. Same tight MP2 settings,
TRIC/GAU_TIGHT,60-evaluation budgets, two4-thread/6GiB workers,20GiB service cap,
8h hard limit and4h watcher review estimate. This extends the newly discovered
lower-basin profile before further torsion fitting. No cloud or product promotion.


## Fixed validation contract established — 2026-09-25

User requested literature research and codification to replace repeated ad hoc fits.
See docs/cpd_validation_protocol.md for primary sources, exact limits, membership,
exposure rules and review workflow. Machine manifest contains94 records:63 required
for reference acquisition,28 prospective holdouts,3 export checks. These are records,
not94 new jobs. Current scans continue; no new full-grid or DNA jobs launched.

Native optimization is not basin closure. Use multiseed bidirectional propagation,
fixed matched reference identity and full conformer descriptors. Old inspected data
are exposed regression/development, never relabeled blind. New fit entry guards
block without a hash-verified acquisition lock; candidate registration blocks further
fitting to protect holdouts. Missing/changed evidence and unmatched basins fail closed.
Current contract intake is0/63 adapted reviews, not a claim that prior QM evidence
is worthless or failed. Required closure/curvature gaps remain real. Final dataset
is not certified merely by publishing its membership. Failure archives preserved.

Verification:26 scoped validation/watcher tests passed, including missing evidence,
NaN/Infinity, altered hashes, reflection/basin mismatch, inconsistent energy zeros,
RMSE failure, holdout coverage, and preventing fit-service creation without a lock.
Current native acquisition and watcher remain active. No broad backend or frontend
behavior change; exported progress data refreshed. Native-audit adapters and full
wavefront scheduling remain acquisition work, explicitly not claimed complete.


## Lower-basin profile: +15 stalls; diagnose before extending — 2026-09-25

Acknowledged failed wake4dcbd02c-9d80-418d-b2e7-31561fe54fff. Independent
native/hash/geometry/response audit covers49+60 evaluations. -15 converged with
projected max/RMS1.27418e-5/3.36044e-6au, energy-1364.5159999680018Eh.
No Hessian or basin closure certification. +15 stopped on60-evaluation guard:
projected max/RMS2.28489e-4/8.08984e-5au, ~15x maximum-force tolerance.
Final native gradient plateau near2.4e-4 despite small energy decreases; do not
justify another budget extension solely by energy descent. All outputs retained.

Launched `cpd-anti-lower-profile-gradient-v1`/service-v1, five single-point
MP2 energy/gradient checks at stalled geometry: repeat reference and +/-0.005,
+/-0.0025bohr along normalized downhill projected Cartesian gradient. This is
a straight-line directional derivative test, not constrained curvature/minimum
certification. Hash/geometry/stereo screens and tight native response retained.
Two4-thread/6GiB workers,20GiB service cap,2h hard limit,20min watcher estimate.
Review both symmetric energy slopes against analytic slope, repeat-gradient noise
and step dependence before choosing optimizer continuation/repair. Local diagnostic
criteria recorded in plan; no acceptance limits changed. Fitting remains blocked
under fixed validation v1; no blind data acquired or cloud spending.


## Stalled +15 diagnostic: slopes agree, repeatability narrowly fails — 2026-09-25

Acknowledged complete wake7f58eb71-5488-43e9-aa91-a44e7aa8e672. Independently
verified five native results, hashes, screened coordinates, finite gradients and
response residuals<=1e-10. Analytic tangent slope-5.663524e-4Eh/bohr agrees with
symmetric energy slopes to0.1479%/0.7517%. Reference gradient component difference
1.083921e-6au exceeds preregistered1e-6 limit: overall diagnostic criteria FAIL,
not silently relaxed. Reference energy difference4.775e-12Eh. This supports a
real downhill gradient at the stalled point; it does not certify stationarity,
curvature, basin closure or accurate soft-mode stiffness.

Launched `cpd-anti-lower-profile-restart-v1`/service-v1: one bounded method test
from same last geometry with fresh initial TRIC Hessian (not replaying stale Hessian
updates), one cached diagnostic reference gradient and at most20 new evaluations.
Original60-evaluation failure plus repeatability failure are linked in plan. This
uses the one continuation allowed by validation v1; no further automatic extensions.
Tight QM and GAU_TIGHT criteria unchanged.4 threads/6GiB worker,10GiB cap,3h hard
limit,70min watcher estimate. Fitting remains blocked; no holdout or cloud work.


## Fresh-Hessian continuation exhausted; method review required — 2026-09-25

Acknowledged failed wake3d922444-a0da-44b2-92a3-27223ccf690b. Native geomeTRIC
maxiter20 failure;21 evaluations=1cached+20new. Independent audit verifies all
native/hash/stereo/response records but NOT convergence. Final projected max/RMS
2.74580e-4/9.14524e-5au versus starting max2.28489e-4. Trust shrank to~4e-6Å;
steps often~1e-7Å with noisy energy changes and persistent gradient. Final energy
is higher than restart seed. No further automatic continuation: the one20-new
allowance is exhausted. Original60 plus20 optimizer evaluations remain unresolved.

Read-only `coordinate_review.py/json` reconstructs initial/final TRIC Jacobians:
rank147/147, condition~91.6, exact expected bond-distance primitives, gradient
reconstruction residual<2.4e-16au initially. This does not implicate graph mismatch
or a missing Cartesian subspace at those two geometries; it does not prove the
internal step/constraint enforcement is correct. No new QM was launched. Store
`method_review.json`: next work is cached-iteration constraint/trust-step and
energy-noise review before selecting a changed method. Prior repeatability failure
remains failed. +15 is unresolved coverage, not an exclusion or certified minimum.
Fixed dataset fitting gate remains closed; no holdout, cloud or candidate promotion.

User-requested closeout complete: pause receipt and launch guard active; legacy
CPD automatic triggers disabled with prior states recorded. Deleted4.81GB of
regenerable integral scratch, preserved all31,188 existing evidence files and
retained three wavefunction snapshots with hashes. See closeout/cleanup manifest.
37 scoped Python tests and3 browser checks pass; browser artifact cleanup verified.
