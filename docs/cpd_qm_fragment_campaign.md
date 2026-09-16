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

## Primary syn/anti fitting submission (2026-09-13)

The D3 scope is now hash-pinned at
`alpine-qm-primary-syn-anti-fit-v1` in the photoproduct evidence archive. The primary
cis-syn candidate retains its completed charge fit and quantitatively selected coupled
response fit; its charges are re-evaluated against the newly collected 996-point ESP.
The primary cis-anti-I charges are fitted independently against its HF/6-31G(d) dipole,
1023-point ESP, and six conventional water curves. Endpoint-1 water sites train the
fit, while endpoint-2 sites remain held out.

The anti bonded fit uses its passed minimum Hessian and four completed fixed-geometry
response Hessians. The minimum plus conformers 001 and 004 form the training set;
conformers 002 and 003 remain validation data. The complete four-carbon ring block is
fit as a coupled response with periodicities 1 through 4, fixed QM improper reference
angles, and no Urey-Bradley terms. Cyclic ring bonds are not treated as independent
torsion scans.

Alpine job **32491760** builds a separate OpenMM/RDKit/SciPy fitting environment without
changing the pinned QM environment. Dependent job **32492585** performs the anti charge
fit and constructs the bonded basis. Array **32492672[0-4]** computes the minimum and
four conformer responses in parallel. Job **32492676** assembles the disjoint campaign,
applies the preregistered bounded ridge policy, selects a quantitative candidate, writes
the CHARMM algebraic transform, and reassesses both primary families. The local watcher
only synchronizes results and writes a gate-neutral trigger. A favorable result advances
to D4 CHARMM mapping and primary-fit freeze; it does not make either product simulation
ready.

## Primary syn/anti fitting reassessment (2026-09-14)

The Alpine chain did not wait on ordinary queue priority. Environment job **32491760**
timed out after 1:00:20 while installing and verifying its packages, leaving prepare job
**32492585** in `DependencyNeverSatisfied` and the response and finalize jobs pending on
dependencies that could never pass. After a bounded local fallback was established, the
three dependent Alpine jobs were cancelled to prevent duplicate execution.

The local fallback completed charge/bonded-basis preparation and all five OpenMM response
sets. Its first finalize attempt exposed an avoidable allocation in the identifiability
diagnostic: a full left singular-vector matrix was requested for the 17,982 by 120 tall
design even though only the complete 120 by 120 right basis is used. The diagnostic now
requests a full SVD only for wide matrices, preserving exact parameter-space null vectors
without allocating the unused tall left basis. The focused identifiability tests pass
**5/5**. A subsequent preflight also corrected the campaign runner to use the existing
fixed-QM-improper v3 response-fit policy, which includes the bond basis present in this
campaign.

The corrected run completed the full-rank response campaign (**rank 120, nullity 0**) and
evaluated all seven preregistered ridge candidates. The reassessment is unfavorable: zero
of seven candidates passes the physical CHARMM transform screen. Candidates with ridge
values through 0.01 produce an invalid equilibrium for
`angles:CG3C41-NN2B-CN1T`; ridge 1.0 fails at
`angles:CG3C41-CG3C41-NN2B`; ridge 100.0 fails at
`bonds:CG331-NN2B`. Automatic continuation therefore stopped. The existing full-rank QM
responses can be reused, but the bond/angle equilibrium treatment must be revised and
preregistered before candidate selection, CHARMM mapping, MM-minimum validation, psfgen,
or staged NAMD smoke testing.

The machine-readable assessment is
`alpine-qm-primary-syn-anti-fit-v1/local-run-v1/bundle/results/stage_assessment.json`, and
the fail-closed completion trigger is
`alpine-qm-primary-syn-anti-fit-v1/local-run-v1/gates/primary_syn_anti_fit.json` in the
photoproduct evidence archive. Both remain gate-neutral and explicitly report
`simulation_ready: false`.

## Physical-equilibrium refit and NAMD smoke preflight (2026-09-15)

The failed v3 transform was followed by a separately registered v4 response-fit policy.
It retains the same training and held-out partitions, ridge grid, fixed stereochemical
impropers, and prohibition on Urey-Bradley terms, while constraining the coupled harmonic
coefficients to positive curvature and physical bond/angle equilibrium intervals during
the fit. The implementation uses linear inequalities with SLSQP and keeps held-out data
outside the optimization. The selected ridge-0.01 candidate was full rank and had the
best held-out normalized score among the seven registered candidates. The local service
peaked at 166 MiB under its 1 GiB memory cap.

Because several fitted angle equilibria were close to the allowed limits, continuation
required a geometry refinement and an independent numerical audit before CHARMM mapping.
The refinement converged to a local minimum with 0.05935 angstrom heavy-atom RMSD from
the QM geometry, positive projected curvature, zero negative projected modes, and all
four expected stereochemical signs. A wrapper filename mismatch stopped after writing
that result; the failed attempt is preserved under
`geometry-refinement-v1/attempts/attempt-001-wrapper-report-name-mismatch`. Recovery reused
the hash-identical refinement output and ran the independent audit without repeating the
optimization.

The independent audit passed stored-minimum reproduction, finite-difference Hessian
symmetry, actual-minimum curvature, heavy-atom RMSD, and stereochemistry. It failed its
unchanged maximum-force limit: 1.09362e-5 kcal mol-1 angstrom-1 against a required maximum
of 1.0e-5. The fail-closed geometry trigger therefore stopped continuation before a
CHARMM transform was generated.

The D4 smoke preflight also found an independent downstream blocker in the selected anti
nonbonded fit. Its held-out endpoint-2 O4 water energy error is 0.55791 kcal/mol, above the
candidate-assembly policy maximum of 0.50000 kcal/mol. Earlier joint and multi-orientation
anti candidates do not supply an accepted substitute; their reserved validation sets also
failed. The screened anti chain-B boundary and real `psfgen`/NAMD executables are present,
but no workbook, CHARMM candidate, PSF, or NAMD trajectory was generated while these two
gates remain closed.

The combined assessment is
`alpine-qm-primary-syn-anti-fit-v1/local-run-v1/namd-smoke-preflight-v1/stage_assessment.json`;
its completion trigger is `gates/namd_smoke_preflight.json` in the same directory. Both
report `blocked_before_candidate_assembly`, `automatic_continuation: stopped`, and
`simulation_ready: false`. Recovery requires a passing independent geometry audit without
relaxing its registered limits and an independently validated anti nonbonded candidate
within the registered held-out water bounds.

## Failed-gate troubleshooting and independent-water recovery (2026-09-15)

The D4a troubleshooting stage kept every previous acceptance limit. The geometry audit
failure was numerical termination noise: the original strict OpenMM minimization stopped
at 1.09362e-5 kcal mol-1 angstrom-1 maximum atom force, only above the 1.0e-5 limit. A
versioned audit adds one finite-difference-Hessian Newton correction restricted to all 102
positive vibrational directions and capped at 1e-4 angstrom per atom. The actual correction
was 9.47e-7 angstrom, after which the maximum force was 1.36e-10 kcal mol-1 angstrom-1.
Stored-minimum reproduction, Hessian symmetry, positive curvature, 0.05935 angstrom
heavy-atom RMSD, and all four stereochemical signs also passed. This resolves the bonded
geometry gate and produced a hash-linked CHARMM bonded transform candidate.

Removing only the contradicted cross-endpoint charge equalities did not resolve the
nonbonded gate. The endpoint-1-trained ordered candidate overbound the held-out endpoint-2
H3 water probe by 1.454 kcal/mol; its alternate-plane independent energy RMSE was
1.055 kcal/mol. Total charge, neutral methyl caps, within-endpoint equivalent hydrogens,
the fixed pinned Lennard-Jones library, training/held-out site identities, and all limits
were unchanged. The D4a trigger therefore remains fail-closed for candidate assembly.

A subsequent capacity-only comparison fit all 12 conventional and alternate-plane water
curves and cannot serve as validation. Fixed Lennard-Jones values failed the maximum
distance target at 0.1424 angstrom. Shared and O2/O4 role-distinct carbonyl oxygen values
also failed at 0.1164 and 0.1073 angstrom. The only model form within all smoke-capacity
targets used ordered endpoint- and role-distinct O2/O4 Lennard-Jones values: 0.1630 kcal/mol
energy RMSE, 0.2767 kcal/mol maximum energy error, 0.05263 angstrom distance RMSE,
0.099999996 angstrom maximum distance error, and 0.1513 e maximum charge change. Its full
charge and Lennard-Jones vector is frozen in
`gate-troubleshooting-v1/model-form-diagnostic-v1/selected_capacity_candidate.json` for
independent validation only.

The required independent evidence is a third, azimuth-120 water orientation. A one-product
Alpine bundle containing 54 counterpoise-corrected HF/6-31G(d) points was built at
`alpine-qm-water-validation-campaign-v3-cis-anti-i-azimuth120`. Its non-target clash ratio
is 1.7649, its archive checksum passes, and the submission helper now derives and overrides
the Slurm array range from `cases.tsv`, allowing this one-case campaign to submit as task
0 only. Alpine job `32590755` was submitted as array `0-0`. Upload verification initially
paused during extraction in Alpine scratch, then recovered without a duplicate submission.
The resource-capped user service `nadoc-alpine-cpd-water-v3-watch.service` monitors that
job, collects its results, and runs the frozen-candidate evaluator. A failure stops, while
a pass authorizes implementation of the custom Lennard-Jones CHARMM assembly stage. Neither
the capacity fit nor the new evidence generation makes the product simulation ready.

## Alpine water result and NAMD integration completion (2026-09-15)

Alpine job **32590755** completed normally in 19 minutes 47 seconds with exit code 0, and
the completion watcher collected and evaluated it. The independent azimuth-120 gate
failed under its unchanged limits: energy RMSE was 0.41249 kcal/mol (limit 0.2), maximum
energy error was 0.69876 kcal/mol (limit 0.5), distance RMSE was 0.06171 angstrom (pass),
and maximum distance error was 0.11153 angstrom (limit 0.1). The endpoint-2 H3 donor was
the worst energy case. Automatic scientific continuation stopped as designed.

A leave-one-orientation-out diagnostic then fitted each registered atom-centered additive
model on two water orientations and predicted the third. Ordered carbonyl-O LJ, ordered
H3/O2/O4 LJ, and ordered N3/H3/O2/O4 LJ variants all failed every held-out orientation.
Their all-orientation fits approached some aggregate targets, but those same orientations
were used in fitting and therefore provide no independent validation. This supports the
existing model-form diagnosis: fixed atom-centered additive charges do not reproduce the
carbonyl/donor anisotropy across arbitrary water azimuths. The registered acceptance
limits were not relaxed.

To finish the requested engine implementation without converting that failed scientific
gate into a pass, policy v4 introduces an explicit integration-only candidate. It records
the failing nonbonded checks, emits distinct fitted O2/O4 LJ types, keeps
`simulation_ready: false`, and prohibits force-field release, production use, or
scientific interpretation. Its first real NAMD parameter load found that distinct LJ atom
types also hide the source ON1 bonded parameters. The preserved failed attempt stopped on
the missing `CA1O2 CN1T NN2B` angle. The exporter now copies hash-pinned bonded identity
records for each integration-only LJ type into the self-contained candidate parameter
file; the focused candidate assembly and engine tests pass 33/33.

The corrected `tt-cpd-cis-anti-i-integration-v2` candidate passes the complete local NAMD
implementation path:

| Gate | Result |
|---|---|
| Real psfgen product/reactant construction and static topology audit | Pass; 63 atoms, charge conserved at -1 e, and exactly the two ordered CPD crosslinks were added. |
| Vacuum NAMD | Pass; warning-classified load, 2,000 minimization steps, and 1,000 ordinary-mass steps at 2 fs. All 100 frames retained chirality; minimum nonbonded covalent-radius ratio was 1.675. |
| Explicit solution NAMD | Pass; 1,084 TIP3P waters, 4 Na+, 3 Cl-, neutral total charge, 1,000 minimization steps, 1,000 heating steps at 1 fs, and 5,000 production-smoke steps at 2 fs. All 50 frames retained chirality; minimum ratio was 1.613. |

The machine-readable assessment is
`gate-troubleshooting-v1/namd-integration-v2/stage_assessment.json`; its trigger is
`gates/namd_integration_smoke.json`. The NAMD implementation stage is complete, while the
scientific campaign remains held. Reassessment requires a preregistered anisotropic or
polarizable nonbonded model, a fresh independent water-orientation set that passes the
unchanged bounds, full d(TpT)/duplex validation for that accepted model, and independent
reproducibility and release review.

## Nonbonded model-form reassessment (2026-09-15)

A second preregistered leave-one-orientation-out diagnostic tested whether a minimal,
charge-conserving static anisotropy extension could recover the failed transferability.
The four fixed-geometry families were an axial carbonyl site, paired in-plane carbonyl
sites, paired in-plane carbonyl sites plus axial donor sites, and paired out-of-plane
carbonyl sites plus axial donor sites. Virtual sites carried no Lennard-Jones term. Their
charges, the constrained atomic charges, and the same ordered N3/H3/O2/O4 Lennard-Jones
terms were bounded and regularized; the original folds and acceptance limits were left
unchanged.

All four families failed all three held-out orientations. The variants with donor sites
reduced some distance errors, but held-out energy RMSE remained 0.35--0.43 kcal/mol. The
largest errors continued to change with orientation: canonical held-out data failed at
the endpoint-2 O2 acceptor, the alternate plane failed at endpoint-2 O4, and azimuth +120
failed at endpoint-2 H3. Optimized carbonyl virtual charges often collapsed toward zero.
This result closes further tuning of the fixed additive model; it does not close the
possibility of a polarizable model.

The official CHARMM Drude nucleic-acid release was then hash-pinned and inspected. Its
thymine model uses asymmetric carbonyl lone-pair charges together with atomic
polarizabilities, atom-specific Thole screening, and anisotropic carbonyl Drude springs.
That is materially different from a fixed equal-site charge split. The published Drude
nucleobase procedure fits charges, polarizabilities, and Thole factors to perturbed
B3LYP/aug-cc-pVDZ ESP maps on MP2/6-31G(d) geometries and scales the fitted gas-phase
polarizabilities by 0.85. The current CPD evidence has the geometry, zero-field ESP,
dipole, and water curves, but no perturbed ESP set or polarizability tensor. Those are now
the required next QM targets.

An engine-only probe established the implementation boundary. psfgen 2.0 built two
standard MTHY residues with 64 total particles, including 20 Drude particles, eight lone
pairs, and four anisotropy entries. The installed NAMD 3.0.2 CUDA binary rejected
NBTHOLE, while the local NAMD Git-2025-12-04 build loaded the same PSF and returned a
finite zero-step energy. The full 2018 nucleic-acid topology also exposed an unsupported
`DELETE ANISOTROPY` patch statement in psfgen. Thus the newer NAMD build can execute a
Drude model compound, but the complete DNA structure-builder path still needs either a
validated preprocessing correction or a CHARMM-GUI/CHARMM-generated PSF.

The first P1 response pilot is Alpine job **32603453**. It requests a
B3LYP/aug-cc-pVDZ molecular polarizability tensor and dipole at the audited
MP2/6-31G(d) N-methyl CPD geometry using 32 CPUs and 70 GB on `acpu`. Submission and
resource checks passed; the job entered `PENDING (Priority)`. Its completion audit
requires normal Psi4 termination, nine finite tensor components, tensor symmetry within
1e-6 atomic units, and three finite dipole components. The enabled
`nadoc-cpd-drude-response-watch.timer` polls every five minutes, collects terminal output,
and writes an immutable completion trigger. A pass authorizes preparation of the
fit/held-out +0.5 e perturbed-ESP campaign only and has no registry effect.

The next campaign has four reassessment triggers: finish and audit fit/held-out perturbed
ESP and polarizability QM targets; require a fitted Drude electrostatic model to predict
the held-out perturbations; require unchanged three-orientation water cross-validation
plus a new frozen fourth orientation; then require a full Drude d(TpT), SWM4-NDP solution,
and duplex-context validation at no more than 1 fs. Additive-to-Drude parameter transfer
does not satisfy any of these triggers. The hash-pinned result, engine evidence, missing
targets, and trigger definitions are recorded in
`docs/audits/cpd_nonbonded_model_form_20260915.json`.

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

## Literature and conventional-practice reassessment (2026-09-15)

A focused review of modified-nucleotide guides, force-field reviews, and CPD-specific
simulation precedents changes the scope of the nonbonded conclusion. The completed QM
evidence is not a failed QM campaign. It demonstrates that the registered fixed-charge
anti model does not predict unseen water azimuths within the NADOC limits. Leave-one-
azimuth-out prediction is a useful model-form stress test, but it is not a universal
CHARMM additive release gate in the established workflows; those workflows fit selected
water poses and then validate the assembled nucleotide in condensed phase and against
experiment.

The campaign will therefore be reassessed as two deliverables. The canonical cis-syn-I
path should compare the existing NADOC fit with a fully audited reconstruction of the
published Ma/van der Vaart CHARMM-compatible CPD tables, then advance to d(TpT) and duplex
validation under a new versioned policy. The water-orientation limitation remains visible
and cannot be relabeled as a pass. Ordered anti and other design stereoisomers remain a
separate research path; Drude response work is justified there when orientation-dependent
electrostatics are part of the intended observable, but those products no longer block
the canonical cis-syn-I release path by default.

The full evidence review and recommended gates are in
`docs/cpd_parameterization_literature_reassessment.md`.

### Polarizability-pilot numerical recovery

Alpine job **32603453** completed the B3LYP/aug-cc-pVDZ property calculation normally in
about five minutes, returning all nine finite polarizability components. The Slurm job
was nevertheless marked failed by its post-calculation audit. Two numerical plumbing
issues were preserved rather than treated as scientific failures: the dipole parser
looked for scalar variable lines even though Psi4 printed the three components in its
multipole table, and the default CPHF solver tolerance of 1e-6 produced maximum tensor
asymmetry of 8.86e-6 atomic units against the preregistered 1e-6 audit limit.

Recovery job **32603776** repeats the same property calculation, geometry, method, basis,
threads, and memory with an attempted CPHF convergence override of 1e-10 and the parser
corrected to read Psi4's multipole table. Its archive is
`alpine-qm-cpd-drude-response-v2`; hashes were verified after upload. The five-minute
completion watcher was moved to the recovery archive. A pass completes the P1 target
only. Consistent with the literature reassessment, it does not automatically launch the
perturbed-ESP campaign or make the anti product a prerequisite for cis-syn-I release.

Job **32603776** ran for 2 minutes 53 seconds and Psi4 exited normally. The corrected
parser recovered all three finite dipole components, and all nine polarizability
components were finite. The tensor was positive definite after symmetrization, and the
largest component difference from job 32603453 was only 5.54e-10 atomic units. Remote and
collected output/audit hashes match. The registered gate still failed because the output
showed that the solver remained at the default 1e-6 convergence and 100 iterations; the
maximum tensor asymmetry was consequently unchanged at 8.86e-6 atomic units.

The recovery input had applied `SOLVER_CONVERGENCE` to Psi4's `CPHF` module. A direct
Psi4 1.11 option probe confirmed that this DFT response path instead reads the `SCF`
module's solver options. Job **32603908** (`cpd-drude-pol3`) was therefore submitted with
the same scientific target and `SCF` solver convergence set to 1e-10. The prior outputs
and failed triggers remain immutable. The watcher now follows the v3 archive and will not
launch dependent jobs.
