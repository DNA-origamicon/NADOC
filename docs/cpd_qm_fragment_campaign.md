# TT-CPD local fragment QM campaign

## Decision

The routine TT-CPD parameterization target is no longer a separately optimized,
charged 63-atom d(TpT) model for every ordered isomer. The submitted Alpine
full-boundary job is intentionally unchanged and may finish as useful independent
validation. New local work follows the model-compound hierarchy used by additive
CHARMM development:

1. retain the complete, covalently connected TT-CPD core in a neutral 36-atom
   N1-methyl model;
2. retain one complete deoxyribose at a time in a neutral 49-atom endpoint-boundary
   model, with the other N1 methyl-capped and the open backbone oxygen hydroxyl-capped;
3. transfer unmodified sugar-phosphate chemistry from CHARMM36; and
4. validate the assembled patch in full d(TpT), short DNA, and NAMD rather than fitting
   the entire DNA environment quantum mechanically.

This partition and its release limits are machine-readable in
`backend/data/forcefield/photoproduct_qm_fragment_policy_v1.json`. It is based on the
[CGenFF model-compound protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/),
the [CHARMM modified-ribonucleotide workflow](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/),
the [CGenFF 5.0 four-membered-ring training/validation split](https://pmc.ncbi.nlm.nih.gov/articles/PMC11938330/),
the [N-methyl CPD electrostatic model of Masson et al.](https://doi.org/10.1021/ja076081h),
and CPD [QM/MM work that restricts the QM region to the reactive bases](https://doi.org/10.1021/jacs.6b06701).

## Reviewed readiness (2026-09-08, workstation local date)

The hierarchy is defensible for **candidate parameter development**, conditional on
measured transfer. The model-compound strategy and separate validation sets are supported
by the CGenFF papers cited above; they do not establish that these particular six fragments
cover all eight ordered CPDs. The Masson and photodimerization papers are mechanistic
precedents, not validation of this ground-state additive force field.

The audit found and repaired two operational problems:

- cis-anti-II and trans-anti-I had interrupted `output.dat` files despite the original
  inventory saying `prepared_not_run`; neither had a completion receipt. Their old
  manifests also referenced temporary source directories.
- Stage A was absent from the fragment launcher. Three fresh core jobs now live under
  `core-cases/`, registered in `review_preparation.json`. Archived starting XYZ and model
  hashes match the original jobs. Source locations and the job-generation protocol were
  updated: protocol 1.7.0, 300 optimizer iterations, 4 GiB/four threads. These are clean
  starts from the original candidates, not restarts from interrupted coordinates.

Original campaign manifests, interrupted outputs, and boundary inputs remain preserved.
All 53 campaign-level hash records matched. Direct Psi4 1.11 molecule/basis construction
verified nine selected jobs: three neutral singlet 36-atom/332-function cores and six
neutral singlet 49-atom/449-function boundaries. This check performed no SCF or optimization.
The verification receipt is `preparation_verification_2026-09-09.json` (UTC date) in the
campaign directory. At review, the workstation had about 22 GiB available RAM and
4.9 TiB free on Archive. No new QM calculation was started.

Remaining scientific gates are substantive:

- An optimized identity/chirality audit **does not prove a minimum**. Require a matching
  frequency audit with the complete 3N−6 spectrum and no material imaginary modes before
  using a stationary point as an equilibrium fitting reference. Reuse existing frequency
  evidence only when the geometry, model, method, basis, and hashes match.
- Audit the retained sugar's stereocenters, puckering, cap contacts, glycosidic geometry,
  and full product graph after optimization. The existing product chirality audit alone
  does not validate every sugar coordinate or exclude a cap-driven gas-phase conformer.
- Geometry alone cannot identify force constants, torsion barriers, or charges. Required
  Hessian/response targets belong before the final primary fit; water/dipole/ESP evidence
  and consistent cap-to-sugar charge constraints must be accounted for explicitly.
- Freeze primary parameters, fitting choices, atom/type mapping, CHARMM36 version, and
  transfer metrics before evaluating C. A refit informed by C consumes that holdout;
  establish a new independent check before claiming transfer.
- C checks only one alternate syn orientation and one trans-anti endpoint. Passing them
  does not validate untested trans-syn products or both endpoints of every ordered isomer.
- Full-boundary QM is optional additional evidence. Assembled d(TpT), short explicit-solvent
  DNA, topology/placement, and real-engine validation remain required for the intended
  release scope. Do not equate optional Alpine evidence with optional DNA-context validation.

## Prepared inputs

### Live checkpoint: 2026-09-09

The completion triggers fired and progression worked through both geometry sets:

| Event (MDT) | Evidence |
|---|---|
| Sep 8, 23:43:19 | Last A optimization completed; stage-finished review event recorded. |
| Sep 8, 23:45:40 | Favorable A assessment automatically launched B's cis-syn endpoint-1 benchmark. |
| Sep 9, 08:45:02 | Last B optimization completed. All seven A/B cases passed candidate-continuity QC. |
| Sep 9, 08:45:39 | Controller entered `hold_for_response_and_fit_scope`. |
| Sep 9, 08:50:39 | Reassessment monitor recorded the scope-hold alert. |
| Sep 9, 09:22 | Following the A/B exit review, the first scoped D frequency benchmark launched. |

Observed A times were 0.58–0.71 h/job; B times were 1.66–2.76 h/job. Peak child RSS
was about 3.75 GiB for A and 10.63–10.65 GiB for B (systemd peak includes additional
process/cgroup memory). Product and tetrahedral stereochemistry passed the existing
audits, and the short-cap-contact screen had no flags. The four retained C1'–N1 distances
were 1.439, 1.468, 1.485 and 1.480 Å. Endocyclic sugar torsions are recorded as diagnostics
in `review_inputs/ab-exit-review-2026-09-09.json`; they are not a DNA-context validation.
The largest syn bond changes were relaxation of initially short C5–C6 distances
(endpoint 2: 1.291 Å to about 1.55 Å), with retained chirality.

`frequency_scope_v1.json` now scopes seven minimum-confirmation/Hessian jobs, each
hash-linked to its exact passed parent optimization. `review_extensions.json` registers
the complete cohort; the standing continuation authorization pins the scope and order.
The first job is `frequency-syn-primary-endpoint-1`. Jobs request **12 threads/12 GiB**, run
one at a time with a 16 GiB process-group cap, and have a provisional **24 h per-job review
budget**. A complete 3N−6 spectrum, no imaginary modes, and a hash-valid, finite, symmetric
Cartesian Hessian are required before continuing. The first frequency is the timing and
memory benchmark; no automatic relaxation of frequency-audit criteria is permitted.

The controller now continues through this D cohort if assessments remain favorable.
Afterward it holds for the primary charge/response fit and transfer specification. The
five reused core geometries require their own matching-frequency evidence inventory;
this seven-job cohort does not claim all-eight equilibrium coverage. C remains held out.

The timers execute local scripts and request desktop notifications; they cannot open a
new conversational/AI planning session. Consequently an unscoped scientific step needs
an active assessment such as this one. `review/latest.md` now includes the continuation
status and its reason, in addition to the per-job scientific evidence states.

The prepared campaign and execution evidence are stored at:

`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1`

Its `campaign_manifest.json` contains hashes, source evidence, resource estimates, and
the exact status of every case. Each new endpoint model has 49 atoms, charge zero, 449
6-31G(d) orbital basis functions, a complete ordered product graph, and a passed starting
chirality audit. Psi4 inputs request 12 GiB and six threads so one job can run locally
without consuming all workstation memory. No `output.dat` or run manifest was created
during preparation.

## Work breakdown and estimates

Estimates are elapsed time for sequential local execution. Geometry-optimization time
is sensitive to optimizer steps, so the first job in each size class is also a benchmark.

| Batch | Need | Prepared work | Estimated local wall time |
|---|---|---:|---:|
| A: missing core optimizations | Complete distinct ring stationary points required regardless of parameter sharing | cis-anti-II, trans-anti-I, trans-anti-II; repaired 36-atom inputs under `core-cases/` | 3–9 h total; rebenchmark |
| B: primary glycosidic boundaries | Cover both ordered C1'-N1/sugar interfaces in the syn and anti families | cis-syn endpoints 1/2 and cis-anti-I endpoints 1/2; four 49-atom inputs | 24–72 h total |
| C: held-out transfer checks | Test family sharing before more QM is authorized | cis-syn-II endpoint 2 and trans-anti-I endpoint 1; two 49-atom inputs | 12–36 h total |
| D: dependent frequencies/scans | Confirm minima, fit force response and selected acyclic glycosidic torsions | Generate after corresponding optimization/identity audits; required primary response precedes C evaluation | 40–140 h placeholder; scope at checkpoint |
| E: full d(TpT) | Independent boundary validation, not routine per-isomer fitting | Leave current Alpine submission alone; do not start a duplicate locally | Alpine-dependent |

Batch D is deliberately not instantiated from the unoptimized starting structures.
Frequency and relaxed-torsion inputs must hash-link to passed optimized geometries; making
them now would create scientifically misleading targets.

## Recommended order

1. Run the three missing 36-atom core optimizations. Start with `tt-cpd-cis-anti-ii`; it is a
   low-memory, short benchmark and is required no matter how the boundary parameters are
   shared.
2. Run `syn-primary-endpoint-1` as the 49-atom local benchmark.
3. If its memory and timing match the estimate, finish the other three primary boundary
   jobs.
4. Generate the mandatory minimum-confirmation frequencies and identified primary
   response/charge targets (stage D work can precede C). Scope and benchmark numerical
   MP2 Hessians before scheduling the full set; do not treat 40–140 h as a commitment.
5. Fit and freeze provisional syn/anti blocks and the transfer scoring specification,
   then evaluate the two held-out fragments. Add scans only for identified response gaps.
6. Expand to another 63-atom full-boundary QM calculation only if a registered transfer
   metric fails. Otherwise use the Alpine result, if it finishes, as the independent
   full-boundary check.

The first three steps provide starting evidence for a cis-syn candidate, not a complete
parameter fit. NAMD production remains fail closed until charge, bonded, topology,
placement, and real-engine audits all pass.

## Execution interface

Listing the prepared fragment cases does not launch anything:

```bash
/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1/run_selected.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1 \
  --list
```

After a case is explicitly selected, its eventual execution command is:

```bash
/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1/run_selected.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1 \
  --run CASE_ID
```

The runner has no default execution path, uses NADOC's provenance-recording QM runner,
refuses to overwrite prior results, and places Psi4 scratch data under the Archive-backed
campaign directory.

## Authorized execution and parallelism (2026-09-08)

The user authorized starting the first set and continuing after each set while assessment
remains favorable, then requested use of spare CPU/RAM. Stage A started with cis-anti-II
at 23:00 MDT; trans-anti-I and trans-anti-II started at approximately 23:06 MDT after
the first job's observed peak was about 4.5 GiB and available memory remained about
20 GiB. The workstation has 16 physical cores/32 hardware threads and about 30 GiB RAM.

Three independent A optimizations now run concurrently, each requesting four threads and
4 GiB from Psi4. The original benchmark service has an 8 GiB systemd limit; the two later
core services have 6 GiB limits each. Combined systemd limits are 20 GiB. Each calculation
has its own scratch directory and unchanged hashed scientific input. Boundary jobs remain
serial at six threads/12 GiB until the 49-atom benchmark and memory measurements justify
revising concurrency. Requested Psi4 memory is not a process RSS limit.

`nadoc-local-qm-continue.timer` evaluates progress every five minutes. The controller
launches at most one eligible case per tick, permits up to three independent cores,
requires all A assessments before B, and assesses each B job before the next. It invokes
the existing product-identity audit plus a conservative whole-fragment continuity screen:
source SDF/element order, all bond-length changes (review above 25%), every tetrahedral
center (same sign and at least 20% of source volume), nonbonded overlap (below 0.9 times
the sum of covalent radii), and short cap-H to N/O contacts (review below 2.2 Å). It also
requires successful run/output provenance, completion within the registered time budget,
and measured peak child RSS within requested memory +2 GiB. These thresholds are
conservative **triggers for closer review**, not validated transfer or release bounds.
Passing them permits more isolated evidence generation only. Sugar pucker, torsional
coupling, cap artifacts and all equilibrium/transfer validation remain later review work.

`continuation_authorization.json` records the user's standing instruction and pins
`continuation_policy.json`. `review/continuation.json` shows the current launch/hold
decision; `review_inputs/automatic-*.json` stores case and stage assessments. The read-only
reassessment monitor also emits a notification request when continuation enters a hold.
Failed/interrupted jobs are never overwritten or restarted automatically. An unfavorable
assessment stops further launches but does not kill other independent running jobs.

The initial automatic queue covered A and B. The Sep 9 checkpoint above extends it to
the assessed seven-job frequency cohort. It cannot declare a favorable assessment of
an unspecified target set. The user's authorization continues to apply to later work
once its scientific prerequisites are established.
C remains held out until the primary fit and transfer scoring specification are frozen.
No duplicate local E job or force-field release is authorized by the controller.

Inspect with `systemctl --user status nadoc-local-qm-continue.timer` and
`systemctl --user list-units 'nadoc-local-qm-case*'`. Disabling the continuation timer
stops new automatic launches while existing jobs continue.

## Reassessment triggers and stage exit reviews

`nadoc-local-qm-reassess.timer` runs every five minutes and catches up after the workstation
returns. The selected-case runner also requests a reassessment on exit. Reports are local:
`review/latest.md`, `review/latest.json`, and immutable, content-deduplicated requests in
`review/events/`. New events request a desktop notification when a desktop notification
service is available. No email, chat message, AI session, next QM job, fit, or release is
started by this monitor. Reports survive logout/reboot; execution requires the user systemd
manager to be running and Archive mounted.
The workstation already has user lingering enabled (`Linger=yes`), so its user manager
can run this timer while logged out. The timer was enabled and its first service run
returned `Result=success`, `ExecMainStatus=0` on 2026-09-08.

| Trigger | Required reassessment before dependent work |
|---|---|
| First core result (`tt-cpd-cis-anti-ii`) | Execution success, graph/chirality, optimizer behavior, elapsed time and memory; revise A estimates. Failed or interrupted runs remain evidence, never overwritten. |
| First 49-atom result (`syn-primary-endpoint-1`) | Same checks plus retained-sugar stereochemistry/pucker, cap contacts and glycosidic geometry; revise B/C estimates before the other primaries. |
| Every job result or changed audit | Validate input/run/output hashes; run the relevant domain audit; separate execution, product identity, and harmonic-minimum verdicts. |
| Half of per-job wall budget; full budget exceeded | Inspect convergence trend and measured resource use. A: 1.5/3 h; B/C: 9/18 h. Rebudget explicitly; these are review signals, not kill deadlines. |
| No output 15 min after launch; output unchanged for 2 h; launcher lost without receipt | Diagnose startup, SCF/optimizer progress, interrupted run or resource failure. Preserve evidence and prepare a separate retry if justified. |
| Invalid provenance; execution/chirality/frequency failure | Stop dependent use, diagnose the cause, and record recovery. No automatic threshold relaxation or restart. |
| Available RAM <4 GiB or Archive free <50 GiB | Reassess local resource contention and scratch use. Launcher requires requested memory +4 GiB available; explicitly authorized core concurrency is capped at three, with boundary jobs serial. |
| A execution finished, including failed outcomes | Confirm all three core outcomes and reuse evidence for the other five; schedule frequency confirmation for fitting references; decide readiness for B. |
| B execution finished | Compare both endpoints within/between families, identify response/charge gaps, register required D work, and define the primary fit and transfer metrics. |
| Primary-fit freeze receipt arrives/changes | Confirm parameters and metrics were frozen before C scoring; record hashes of parameters, training evidence and scoring code. |
| C execution finished; transfer report arrives/changes | Score the frozen fit, inspect endpoint-specific residuals and coverage; keep, split, or reject family sharing. A failed holdout used for refitting becomes training evidence. |
| D registered cohort finished | Check complete mode tables/Hessian provenance and identifiability; inspect imaginary modes and cap motion; assess scan continuity, hysteresis and stereochemistry. Refit only against the declared training set. |
| E collection receipt arrives/changes; registered collected cohort finished | Check actual completion and identity/frequency evidence, projected boundary forces and assembled-context transfer. An incomplete/failed collection is an immediate review event, not a passed full-boundary check. |

For quantitative transfer decisions, freeze a `review_inputs/transfer-metric-spec.json`
before C evaluation. It must name observables, atom subsets, alignment/projection, units,
aggregation, reference hashes, numerical acceptance bounds, and missing-data behavior.
At minimum cover each endpoint's C1'–N1 distance/angles, glycosidic torsion and sugar pucker,
core geometry, projected gradient/Hessian residuals and identifiability, charge constraints,
held-out water interactions, and assembled d(TpT) boundary forces. Missing bounds or missing
required evidence mean **not assessed**, never pass. Existing full-d(TpT) policy values
are not automatically validated for neutral capped fragments. The B exit review must
register fragment-specific bounds before scoring the holdouts; no scientifically justified
universal bounds currently exist in this campaign.

Save review receipts as JSON under `review_inputs/` (e.g. `primary-fit-freeze.json`,
`transfer-report.json`, `stage-D-review.json`, `stage-E-review.json`). Any added/changed
receipt triggers review; a receipt's claimed `status` does not grant acceptance.
Record the reviewer, decision (`continue`, `hold`, `revise`, or `stop`), reasons, exact
evidence hashes, permitted next work and remaining blockers. Geometry changes still use
the repository's concrete visual-review procedure.

D's seven frequency jobs are now registered; later D targets and collected E jobs need
their own scoped registration. Register the **complete planned cohort** when its jobs
exist in `review_extensions.json`; do not register only completed jobs or replace the
existing cohort when adding new entries.
The file has this shape (repeat `jobs` entries for every planned job):

```json
{
  "schema": "nadoc.local-qm-review-extensions.v1",
  "jobs": [{
    "id": "unique-frequency-case-id", "stage": "D",
    "job_dir": "/absolute/path/to/generated/job",
    "job_manifest": {"path": "/absolute/path/to/generated/job/job_manifest.json", "sha256": "actual-sha256"},
    "wall_hours": 24
  }]
}
```

Use stage `E` for collected full-boundary jobs; its local Alpine `collection_report.json`
files are watched automatically even before job registration. Until registered, stages stay
pending and cannot pass by having zero jobs. A stage-finished event reports execution
completion only; every stage still needs the scientific exit review above. The monitor
does not query SLURM, so remote changes become visible when the existing collector writes
local evidence.

Inspect monitoring with `systemctl --user status nadoc-local-qm-reassess.timer` and
`journalctl --user -u nadoc-local-qm-reassess.service`. Force a read-only reassessment with:

```bash
.venv/bin/python scripts/local_qm_fragment_campaign/reassess.py
```

Recreate the preparation on a newly built campaign with the QM environment's Python:
`scripts/local_qm_fragment_campaign/prepare_review.py --campaign-root CAMPAIGN_ROOT`.
It refuses to overwrite an existing preparation. The archived launch helper lists all
nine selected A/B/C cases plus registered extensions; it never runs an unspecified case.

## Alpine continuation handoff (2026-09-10)

Local QM execution is held under `local_execution_hold.json`; the continuation timer is
disabled. The interrupted `frequency-anti-primary-endpoint-1` attempt is preserved with a
hash-pinned stop receipt after 269 of 289 gradient evaluations. It produced neither a
completion receipt nor a Hessian and is not restartable, so Alpine receives a clean job
from the immutable optimized geometry and protocol.

The relocatable continuation is stored at:

```text
/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-local-fragment-continuation-v1
```

Its ready Slurm array contains the six unfinished frequency/Hessian jobs. Each requests
32 CPUs, 56 GiB Slurm memory, 48 GiB Psi4 memory, and 23.5 h; the submission cap is three
concurrent array tasks. The passed local syn endpoint-1 frequency remains the seventh
cohort member. The archive has a complete SHA-256 inventory and materialized source
geometry/parent-audit copies, so collection and frequency audit do not depend on the
original absolute paths.

`bundle/offload_plan.json` defines the remaining transitions. Collection fires the D1
trigger only when all seven frequency jobs pass complete 3N-6 mode and Cartesian-Hessian
audits. D2 then reconciles reused-core frequencies; D3 requires a hash-pinned charge,
nonbonded, and torsion-target scope; D4 freezes the primary fit and transfer metrics.
The two C inputs are transported under `bundle/sealed-heldout/HOLD.json` and remain
unsubmittable until the D4 freeze receipt. E reuses the existing Alpine boundary recovery
job rather than duplicating it. Any missing or failed assessment holds dependent stages.

Submission and collection use:

```bash
scripts/alpine_qm_local_fragment_campaign/submit_frequency_from_local.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-local-fragment-continuation-v1
scripts/alpine_qm_local_fragment_campaign/watch_and_collect_frequency.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-local-fragment-continuation-v1
```

Submission starts the collection watcher as a transient user service. Both require the
authenticated OpenSSH control socket used by the existing Alpine campaign scripts. A
failed socket preflight changes no remote state. The handoff evaluator is read-only:

```bash
.venv/bin/python scripts/alpine_qm_local_fragment_campaign/evaluate_handoff.py \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-local-fragment-continuation-v1
```

The D1 array was submitted on 2026-09-10 as Slurm job **32360291**, array
`0-5%3`. Slurm confirmed `ArrayTaskThrottle=3`, 32 CPUs per task, and a 23:30:00
walltime. Its initial state was `PENDING (Priority)`; the `sbatch --test-only`
scheduler estimate placed its first allocation at 2026-09-12 07:59 MDT. This is an
estimate, not a reservation. The transient user service
`nadoc-alpine-local-fragment-frequency-watch.service` is active and checks the array
each minute. When no Slurm records remain, it synchronizes the remote result tree,
runs the six-case import/frequency audit, writes `gates/frequency_cohort.json`, and
evaluates the next handoff stage. Missing, ambiguous, failed, or hash-mismatched
results produce a hold trigger.

At the same checkpoint, existing boundary-recovery array 32312446 still had two
running tasks: task 0 was scheduled through 04:42 MDT and task 1 through 04:57 MDT
on Sep 10. Task 2 had already failed with exit code 1. Stage E therefore remains an
independent, incomplete validation input pending collection and recovery review.

Wave 1 of D1 completed later on Sep 10: anti endpoint 1, anti endpoint 2, and syn
endpoint 2 passed 141/141-mode, zero-imaginary-mode, and Cartesian-Hessian audits.
The remaining three D1 tasks are `32360291_3` through `_5`; after a stale array
throttle was released, they became ordinarily eligible and pending on priority.

The D2 inventory found four matching passed reused-core frequency audits and one
missing case, the 36-atom `tt-cpd-cis-syn-ii` core. That missing job was generated
from its hash-matching passed optimized-model audit under protocol v1.7.0 and
submitted independently as Slurm job **32368077**, task 0. Its collector watcher is
`nadoc-alpine-local-fragment-frequency-watch-32368077.service`. This lets the only
known D2 calculation accrue queue priority while D1 finishes. D2 still cannot pass
until both D1 and the five-core reconciliation pass.

The 2026-09-10 17:37 MDT reassessment remains favorable. D1 is 4/7 passed, with
array tasks 3–5 pending for priority; D2 is 4/5 prevalidated, with job 32368077
pending for priority. Both completion watchers are active. Alpine reports no estimated
start for either pending allocation. No additional QM submission is justified yet:
the known D1 and D2 work is already queued, D3 lacks a hash-pinned target/scan scope,
D4 and held-out C remain gated, and boundary stage E remains incomplete at 0/3 passed
compute products. The signed-off machine-readable decision is
`reassessment_2026-09-10T173737-0600.json` in the Alpine continuation evidence root.

Alpine accounting on 2026-09-12 confirmed that all seven submitted tasks completed
normally with exit code `0:0`; no task was cancelled, preempted, or interrupted. The
remaining three D1 cases passed with zero imaginary modes and valid Cartesian Hessians,
so `gates/frequency_cohort.json` passed D1. The independently queued cis-syn-II reused
core also passed with 102/102 modes, zero imaginary modes, and a valid Hessian. A
hash-pinned reconciliation of that result with the four retained matching core audits
passed D2 in `gates/reused_core_frequency_inventory.json`. The handoff now reports
`ready_D3`. Further submission remains held until the charge, nonbonded, and justified
torsion target scope is hash-pinned.

## Verification of this review

Targeted monitor tests exercise input/source corruption, interrupted execution, stage
failure, benchmark/stage events, deduplication, deferred-stage registration, and the
distinction between identity and harmonic-minimum evidence. Shell syntax, Ruff, systemd
unit verification, live service execution, and the nine-case listing passed.

The required `just test-smart` selected **FAST**: **8,108 passed, 109 skipped, 11 failed**.
Failures are in assembly flattening/CanDo tests outside the changed campaign code;
representative reruns fail because workspace fixtures `BigO.nadoc` and `smallO-poly.nass`
are absent. No application or scientific production validation is claimed.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
