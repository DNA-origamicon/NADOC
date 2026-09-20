# Published cis-syn comparator: isolated reconstruction

## Overnight benchmark completed and reviewed

`cpd-overnight-8h-v1`: **34 ns in 68 blocks**, 7 h 53 min elapsed; 17,000 frames
independently audited. All native/stability gates pass and image-clearance bounds
remain above 43.60 Å. CPD/control replica 1 each reached 6 ns; others reached
5.5 ns, so comparisons use the common 5.5 ns window.
CPD replica 3 opens the lesion-opposing A6–B15 pair around 4–4.5 ns and remains
open through 5.5 ns, with intact crosslinks and stereochemistry. This requires
local-state/energetic review, not an automatic bond/angle refit or an indefinite
extension to flatten global RMSD. The bounded stability benchmark passes;
lesion-site ensemble validation and general strand integration remain pending.
See the campaign's `completion_review.md`, `overnight_review.png` and
`overnight_review_audit.json`. The completion wake was acknowledged and no new
simulation was launched by the review.

## Eight-hour overnight array started, 2026-09-20

`cpd-overnight-8h-v1` continues all six validated 90 Å-box / 1T4I replicas from
`cpd-dna-largebox-v1` restart coordinates, velocities and cell state. No new
minimization or positional restraint is applied. `overnight_dna.py` alternates
CPD/control and replica numbers in 0.5 ns blocks, using one local GPU and two CPU
threads. The total wall budget is 28,800 seconds, including analysis; the scheduled
deadline is 2026-09-20 10:18:44 America/Denver. No cloud resources are used.

Measured pilot throughput predicts approximately 450 seconds per 0.5 ns block
including a small analysis allowance. Actual throughput determines total sampling;
a partial final round can leave replica durations unequal by at most one block.
Scheduling records completed duration, rather than claiming a fixed ns target.
At each boundary, admission requires 120 seconds of reserve plus 1.2 times the
median duration of the most recent six completed blocks. If an admitted block
runs to the remaining budget, its own native process is terminated, its restart
files are retained, and that partial block is explicitly excluded from validation.
This enforces the user's time budget; it does not classify a budget stop as a
physical instability or a completed block.

Every completed block receives the native/geometry/stereochemistry/thermodynamic
checks and a >16 Å conservative periodic-image clearance bound at all saved 2 ps
frames. `local_diagnostics.json` also records central and lesion-local RMSD,
all ten base-pair distance contacts, glycosidic torsions and sugar-ring torsions.
These descriptive observables support the final bounded benchmark review; global
RMSD drift is not itself a failure and convergence is not inferred from elapsed time.
A failed numerical or clearance gate stops the batch for review.

A block exceeding 1.5 times estimated duration (minimum 300 seconds) sends one
targeted overdue wake per campaign, then the supervisor continues within budget.
Completion/failure wakes the exact originating session via the previously verified
`codex queue` route. A separate event-driven monitor refreshes CPD progress at block
boundaries. No periodic model polling is needed. Status, expected/admitted keys,
restart hashes, completion records and review acknowledgments are retained in the
campaign root. `overnight_checks.py` admission/throughput tests pass, and its image
bound was regressed against the independently audited real pilot trajectory.

## Revised pilot completed and reviewed

All six `cpd-dna-largebox-v1` replicas pass. Independent audit verifies 1,320 saved
frames (600 production), native endpoints and source hashes. Image separation's
conservative lower bound remains above 45.62 Å at all saved frames, and both
A8–B13 contacts are present in 91–99% of production frames per replica. The new
setup supports longer matched sampling, but 100 ps production per replica does
not establish convergence. See `completion_review.md` in that evidence root.
The completion event successfully woke this session and was acknowledged. No
additional simulation was launched by the review.

## Revised source and larger-box pilot, 2026-09-20

The isolated `cpd-start-1t4i-v2` fixture adopts deposited 1T4I A/B heavy coordinates,
renumbering chain B 1–10 to 11–20 for existing topology compatibility. Every
heavy coordinate is checked against that source before native execution. The
v6 PSFs and parameters remain unchanged. Hydrogens are rebuilt with psfgen and
minimized for 500 steps with heavy atoms fixed. All 64 CPD/60 control monitored
stereocenter signs agree with the previous fixture; maximum bond length is 1.763 Å.
The current/candidate/overlay view is `starting_pair_comparison.png`, with
per-residue displacements and source hashes in `starting_structure_audit.json`.
The primary change is A8 (2.04 Å residue RMS displacement after overall alignment).
A8–B13 contacts are now 3.077/2.711 Å rather than 5.500/5.825 Å. This uses an
experimental deposited conformer rather than manually imposing pairing.

Source: https://www.rcsb.org/structure/1T4I (same study, unbrominated sequence).
1SM5 was inspected but contains bromouracil substitutions and was not selected.
The first isolated reconstruction attempt omitted PDB segment IDs; psfgen failed
to assign coordinates and native startup failed. It is retained as failed v1.
V2 fixes the segment mapping and asserts every heavy atom matches its deposit.
No v1 coordinates were used in the new solvated campaign.

`cpd-dna-largebox-v1` contains three CPD and three matched control pilots in
90 Å cubic boxes (approximately 71,300 atoms), with the same salt, solvent and
force field as before. Each runs 100 ps staged equilibration + 100 ps unrestrained
production. This establishes the corrected setup before longer extensions.
Each completed replica receives existing stability checks plus a conservative
periodic-image separation bound: shortest box edge minus the maximum heavy-atom
solute diameter must exceed 16 Å at 5 ps sampled frames. The bound is invariant
under rigid solute rotation; passing it is not a full box-size convergence test.
Changing both source and box means differences from the old batch cannot be
uniquely attributed to either intervention. The control still inherits damaged
crystal geometry, so independent undamaged starting-state validation remains open.

`large_box_pilot.py` registers an event-driven completion wake before simulation;
expected runtime is initially one hour, with a single overdue query at 90 minutes.
`watch_progress_snapshot.py` refreshes the UI on state changes without polling.
Progress and review delivery are tracked in `status.json` and `completion_wake.json`.
No cloud resources are used. All changes remain isolated research fixtures and
have not changed production geometry or enabled production CPD simulation.

## Drift localized: end motion, starting-pair bias and box-size contamination

See `.development-artifacts/cpd-drift-localization-v2/REPORT.md` and plots.
CPD replica 2's late motion localizes mainly to A8–A10; lesion base-ring RMSD
changes only 0.35 → 0.37 Å. A8–B13 is already open in the starting coordinates.
CPD 3 and control 2 additionally show terminal contact loss. Every-frame image
checks find control 1 reaching 5.61 Å from its periodic copy, below the 12 Å cutoff
for 70.6% of its final block. CPD 2 briefly reaches 11.81 Å. Prioritize box-size
and initial-state controls before parameter refitting. No coordinate repair or new
MD has been launched. Recorded numerical stability passes remain valid, but they
do not validate an isolated, converged solution ensemble.

## Completed extension and recovered review

All 30 one-nanosecond blocks completed and passed their recorded stability gates.
The direct audit verifies 15,000 saved frames, native endpoints, restart hashes
and analysis-source hashes. See `cpd-dna-extended-v1/completion_review.md` and
`completion_evidence_audit.json`. Late RMSD evolution, especially CPD replica 2,
precludes a convergence claim; local structural diagnostics are the next priority.
The automatic reviewer hit a filesystem sandbox failure; its original report is
retained and the direct review supersedes it. Trigger success now requires a
structured confirmation of completed evidence review, not merely exit code zero.

## Completion review trigger (repaired)

The extension runner now requires an originating thread (`--wake-thread`, default
`CODEX_THREAD_ID`) and arms `trigger_dna_review.py` before native work. The watcher
uses inotify for atomic status updates and pidfd for supervisor exit, with no
periodic polling. It queues completion/failure review to the exact originating
session using `codex queue`, reusing that session's working tool environment.
The old separate reviewer failed initializing its filesystem sandbox and is retired.

`--expected-seconds` defaults to 14,400 for this 30 ns batch. The overdue threshold
is estimate + max(50%, 300 seconds): six hours for a four-hour estimate. At the
threshold the watcher captures log progress and queues one diagnostic wake.
Completion events remain armed afterward. No automatic cancellation or new MD
is authorized by being overdue. The resumed agent may set a revised deadline.

`completion_wake.json` records registration and delivery attempts. A successful
queue response means **queued**, not delivered or reviewed. The resumed agent
must write `completion_wake_ack.json` with the matching token, event and receipt
time. Scientific review is a separate outcome. A file lock prevents concurrent
watchers, and existing wake records require explicit inspection before retrying.

`monitor_dna_extension.py` likewise waits on file events rather than polling.
Unit tests exercise atomic replacement, deadlines, exact-thread delivery and
rejection of a zero-exit failed review. Long-job policy is retained in
`memory/feedback_long_job_completion.md`.

## Longer replicated sampling launched, 2026-09-19

The local continuation is running under `.development-artifacts/cpd-dna-extended-v1`.
It schedules **5 additional ns per replica**, 30 ns total, in 1 ns blocks,
alternating CPD/control and replica number within each round. `status.json`
records the supervisor PID, active NAMD PID, current block and completed checks.
The sequential GPU batch uses two CPU threads; no cloud resources are involved.
At approximately 200 ns/day, native dynamics should take roughly 3.6 hours,
plus analysis and startup overhead; this is an estimate, not a completion claim.

`extend_dna_replicas.py` reads saved binary coordinates, velocities and extended
cell state, preserving the timestep and using new Langevin seeds for each block.
It applies no minimization, velocity regeneration or positional restraints.
Each block saves 500 frames (2 ps spacing) and restart files every 10 ps.
The supervisor stops on failed native execution or any failed structural check.
Original pilot evidence remains intact. The extension analyzer uses explicit
start-step, duration and expected-frame metadata rather than pilot constants.

`monitor_dna_extension.py` writes `sampling_diagnostics.json` with per-replica
1 ns block means and half-block drift for DNA RMSD and central base-pair contacts,
plus temperature, density and lesion bond means. It refreshes the progress
snapshot after each assessed block and exits when the batch completes or fails.
The UI's **Reload evidence** fetches that snapshot. Longer sampling remains
pending even if all numerical checks pass: drift and replica agreement still
require review, and duration alone does not establish convergence.

```sh
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m experiments.cpd_published_comparator.extend_dna_replicas --root .development-artifacts/cpd-dna-extended-new
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m experiments.cpd_published_comparator.monitor_dna_extension --root .development-artifacts/cpd-dna-extended-new
```

Run the monitor alongside the extension after its status file exists. Use a
fresh evidence root; the runner refuses to overwrite an existing campaign.
The UI exporter currently reads the active `cpd-dna-extended-v1` status path.

## Replicated DNA short stability pilot, 2026-09-19

**Six of six replicas pass the short-pilot checks:** three cis-syn duplexes and
three matched undamaged controls using candidate `cpd-cis-syn-joint-v6`.
Evidence is retained in `.development-artifacts/cpd-dna-replicas-v2`, including
`protocol.json`, per-replica inputs/logs/trajectories/assessments, `assessment.json`,
and `replica_diagnostics.png` / `.pdf`. This is an additive CHARMM candidate;
it does not validate a Drude model. `simulation_ready` remains **false**.

Each system contains 12,284 atoms: 634 DNA atoms, 3,870 CHARMM TIP3P waters,
29 sodium ions and 11 chloride ions (nominal 150 mM salt plus neutralizing ions).
Three seeds (41017, 52021, 63029) are paired across the CPD/control conditions;
ion placements and velocities vary between replicas. All runs use native GPU
NAMD, PME, a 2 fs timestep with rigid hydrogen bonds, 300 K and 1.01325 bar.
After 10,000 minimization steps, each trajectory has 100 ps of staged NPT
equilibration and 100 ps of unrestrained NPT production. Restraint scales are
1, 0.5 and 0.1 for 20 ps each, then zero for the final 40 ps of equilibration.
Production contains 100 saved frames at 1 ps intervals.

All six runs completed with finite observables, no sampled stereochemical
inversions, and all DNA heavy-atom bonds within the preregistered 0.8–2.1 Å
sanity range. The CPD runs retain all 64 monitored centers; controls retain all
60. Replica mean temperatures are 299.03–300.12 K and mean densities are
1.0608–1.0635 g/mL, within the 280–320 K and 0.9–1.2 g/mL pilot gates.
RMSD, central base-pair contacts and CPD crosslink lengths are plotted as
structural diagnostics, not fitted acceptance targets.

The builder converts the GROMACS SPC216 template to CHARMM TIP3P geometry,
checks parameter coverage and charge neutrality, and copies CUFIX NBFIX terms
to CPD type aliases. Solvation preserves each input solute's atom types,
charges and bond graph. `solvent_parameter_audit.json` records force-field
sources and alias corrections.

The retained v1 attempt failed when switching the GPU-resident engine from
NVT to a pressure-controlled stage: energy records became zero and NAMD
segfaulted. V2 starts the piston at initialization and keeps NPT throughout;
all six fresh runs completed. Execution checks now reject zero dynamic
energies as well as native failures. No corrupted v1 state was reused.

The complete v2 batch took approximately 10.4 minutes locally, with **no new
cloud expense**. This is 1.2 ns aggregate MD, including 0.6 ns production.
It demonstrates short-time numerical and structural stability, **not solution
convergence or a reliable lesion effect**. Both conditions start from the same
crystal-derived coordinates; the control is not an independently equilibrated
undamaged reference. Longer replicated sampling, independent glycosidic
energetics and integration into the general DNA-strand builder remain open.

To reproduce, choose a fresh evidence root and run from the repository root:

```sh
.venv/bin/python experiments/cpd_published_comparator/dna_replicas.py --root .development-artifacts/cpd-dna-replicas-new
.venv/bin/python experiments/cpd_published_comparator/dna_replicas.py --root .development-artifacts/cpd-dna-replicas-new --run
.venv/bin/python experiments/cpd_published_comparator/analyze_dna_replicas.py --root .development-artifacts/cpd-dna-replicas-new
.venv/bin/python experiments/cpd_published_comparator/plot_dna_replicas.py --root .development-artifacts/cpd-dna-replicas-new
.venv/bin/python experiments/cpd_published_comparator/export_progress.py --dna-root .development-artifacts/cpd-dna-replicas-new
```

The builder uses the workstation's pinned local NAMD and GROMACS installations
and retained v6 input evidence. Completed per-replica analyses are cached;
use a fresh root for a new campaign rather than replacing its trajectories.

## Cis-syn: recorded local failures resolved, 2026-09-19

The current isolated candidate is **`cpd-cis-syn-joint-v6`**. All recorded local
geometry, stereochemistry, minimum, implementation and core-energy checks pass.
This resolves the previous 14 fragment-angle failures without relaxing thresholds.
It does **not** complete independent glycosidic energetics or replicated solution
validation; `simulation_ready` remains false.

| Model | Bond checks | Maximum bond error (Å) | Angle checks | Maximum angle error (°) |
|---|---:|---:|---:|---:|
| Capped cis-syn core | 38/38 pass | 0.027451 | 72/72 pass | 2.568227 |
| Sugar endpoint 1 | 52/52 pass | 0.028815 | 99/99 pass | 2.882661 |
| Sugar endpoint 2 | 52/52 pass | 0.023046 | 99/99 pass | 2.885473 |

All 18 stereocenters retain their reference signs. Maximum residual forces are
below 6.1e-6 kcal/mol/Å. Step-halved minimum internal curvatures are positive:
core 0.973275, endpoint 1 0.382572, endpoint 2 0.060659 kcal/mol/Å².

### What changed

The earlier shared atom types tied distinct lesion-ring environments together.
`prepare_cis_syn_types.py` creates CPD-specific aliases by chemical atom role and
original type, shared across the two residue endpoints. It copies the original
numerical parameters first and verifies energy/force equivalence before fitting.
Aliases also isolate sugar corrections from ordinary DNA. These are bespoke
research types, not the original published topology or a new CHARMM36 release.

`refine_cis_syn.py` jointly fits 109 shared equilibrium bond/angle parameters across
the capped core and both sugar fragments, with ±0.01 Å / ±6° bounds relative to the
boundary-v4 baseline. Force constants, charges, torsions, nonbonded terms and
Urey–Bradley terms remain fixed. All three geometries are training evidence. A
stationary-minimum Hessian response provides optimizer derivatives; final acceptance
uses actual re-minimized coordinates and separately recomputed checks.

The standard sugar model is not globally replaced: `scope_cis_syn_export.py` removes
every parameter entry that does not involve a CPD-specific type. The final overlay
produces **exactly zero** energy and force change in the ordinary-DNA control.
Independent sugar conformational energetics remain necessary because the underlying
CHARMM36 sugar model was calibrated partly against solution behavior.

### Export issues found and fixed

- ParmEd 4.3.1's CHARMM parameter writer omitted Urey–Bradley terms and rounded
  equilibrium values. The alias exporter restores explicit UB terms and full
  equilibrium precision, and copies the existing NBFIX entries to alias pairs.
- ParmEd's generic PSF save conversion dropped the title. Direct PSF writing with
  a nonempty title fixes native NAMD's `DIDN'T FIND NATOM` failure.
- The first broad fitting implementation selected UB distances as ordinary bonds
  when their outer atom-type pair matched a bonded pair. Selection now uses only
  the primary HarmonicBondForce. Exported-vs-fitted energy/force comparison catches
  this class of mismatch.
- Materialized ordinary-DNA improper entries changed permutation matching despite
  equal constants. Restricting the final overlay to CPD-specific terms preserves
  ordinary DNA exactly. The intermediate v5 control-invariance failure is retained.

All earlier alias and joint-fit attempts remain under their versioned evidence
roots. V6 copies the successful v5 fitted systems and scopes the exported parameter
file; it does not perform another geometry fit. No failed export is presented as
the current candidate.

### Verification and usage limits

- All four boundary NAMD/OpenMM comparisons pass at QM and MM geometries:
  max energy discrepancy 0.000401 kcal/mol, max force discrepancy 0.000441 kcal/mol/Å.
- All three capped-core native comparisons pass; exported and fitted OpenMM
  energies/forces agree within 1e-7.
- Nine fixed QM core geometries were re-evaluated without energy fitting. The six
  low-energy nonreference points give RMSE **0.563453** and max error **0.830392**
  kcal/mol, passing the existing 1/2 kcal/mol criteria.
- The typed 63-atom d(TpT), 634-atom duplex and 634-atom control load in native NAMD
  and complete 500 fixed-heavy-atom minimization steps. These remain startup probes.

Use the **matching typed PSFs** under the candidate's `dimer`, `duplex`, `core` and
`endpoint-*` directories with `comparator_last.prm` and the pinned parent NA/CGenFF
files. `aliases.rtf` contains mass definitions only. The old untyped MVSY patch is
**not** a topology for this typed candidate. Do not apply the overlay to an old
untyped CPD PSF, and do not promote these fixture builders into production without
the remaining validation and a general strand-build integration check.

Help → CPD progress opens the corrected core first, followed by both corrected
sugar fragments. They have no recorded failures; local scope is green and overall
readiness remains incomplete. Historical originals retain their old failures.

The current fit can be regenerated using `refine_cis_syn.py --all-angles --all-bonds
--typed-input .development-artifacts/cpd-cis-syn-types-v5 --warm-start
.development-artifacts/cpd-cis-syn-joint-v3 --root <fresh-root>`. The warm start uses
only the retained development parameter shifts; it does not validate that intermediate
export. Then scope the result into a new root with `scope_cis_syn_export.py`, and run
`verify_boundary_engines.py`, `verify_angle_export.py` (with its `--fit` and `--psf`
pointing to the new core), `independent_energy_check.py`, `verify_core_minimum.py`, and
`verify_typed_startup.py`. Use `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` throughout.

All work ran locally. No new cloud spend, production parameter changes or VR edits.

## Shared sugar-boundary correction, 2026-09-19

`cpd-sugar-boundary-refinement-v4` is the current isolated **training candidate**.
`refine_boundaries.py` fits one shared glycosidic equilibrium bond length and five
shared equilibrium angles across both sugar endpoints. Bounds remain ±0.03 Å and
±6°; charges, force constants, torsions, nonbonded terms and the capped-core model
are unchanged. Geometry acceptance remains 0.03 Å / 3°, consistent with the
[CGenFF parametrization procedure](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/).
The previous independent boundary geometries are now training data for this correction.

| Check | Endpoint 1 | Endpoint 2 |
|---|---:|---:|
| Glycosidic bond error, before → after (Å) | +0.04025 → **+0.02602** | +0.00223 → **−0.01096** |
| Maximum attachment-angle error, before → after (°) | 4.52499 → **2.30322** | 5.22579 → **2.81938** |
| Newly failing bonds/angles elsewhere | **0** | **0** |
| Preserved sugar + lesion stereocenters | **7/7** | **7/7** |
| Minimum internal curvature, step-halved (kcal/mol/Å²) | **+0.123258** | **+0.205329** |
| Remaining full-fragment angle failures | **5** | **9** |

All full-fragment bonds pass. The existing full-fragment angle outliers remain:
maxima 5.035° and 6.455°. Some existing failures worsen slightly; the collateral
gate means **no newly failing checks**, not zero displacement or universal improvement.
The optimizer uses penalties for crossing 2.95° / 0.0299 Å for previously passing
terms, then checks actual results against the unchanged 3° / 0.03 Å acceptance limits.
All before/after angles and bond lengths are retained, not just the fitted subset.

Earlier attempts are preserved: v1 passes attachment geometry but introduces two
angle failures; v2 retains one new angle failure and a marginal new bond failure;
v3's stronger no-worsening penalties avoid new failures but miss attachment-angle
targets. V4 focuses the collateral constraint on previously passing terms. Each
attempt retains its exact executed fitting source and assessment. This is an adaptive
training campaign, not four independent validations.

Native checks for v4 all pass:

- NAMD/OpenMM at both QM and MM boundary geometries: maximum energy discrepancy
  **0.000389 kcal/mol**, force-component discrepancy **0.000594 kcal/mol/Å**.
- Capped-core export regression: original OpenMM candidate and exported parameters
  agree within 1e-7 at the core minimum and two distortions; all three native checks pass.
- The nine-point independent capped-core energy regression remains unchanged:
  low-energy RMSE **0.723288**, maximum error **1.154970 kcal/mol**.
- Fresh 63-atom d(TpT), 634-atom duplex and control each load in NAMD and complete
  500 fixed-heavy-atom hydrogen-minimization steps. These are startup checks only.

Help → CPD progress now retains original probes and adds two corrected training
minima. Every candidate bond/angle check shows its before/after error; remaining
outliers, shared implementation checks, and pending independent tests are visible.

Reproduce with one numerical thread (use a fresh output root; frozen evidence must
not be overwritten):

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/refine_boundaries.py --root .development-artifacts/<fresh-candidate> --guard-collateral
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/verify_boundary_engines.py --root .development-artifacts/<fresh-candidate> --candidate .development-artifacts/<fresh-candidate>
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/verify_angle_export.py --root .development-artifacts/<fresh-candidate>
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/independent_energy_check.py --root .development-artifacts/<fresh-candidate>/core-energy --candidate .development-artifacts/<fresh-candidate>/core_exported.xml
OPENBLAS_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/export_progress.py
```

All work ran locally with one numerical thread and no cloud spend. No production
parameters, molecular placement, VR files or release gates changed. **Next:** independent
glycosidic conformational energies and assessment of the remaining full-fragment
angle outliers, followed by separately equilibrated solvent/ion and DNA controls.
Do not widen the fit to standard sugar terms solely to make gas-phase minima green.

## Independent energy and sugar-boundary checks, 2026-09-19

The frozen angle-refinement-v2 candidate was evaluated without refitting. All new
checks ran locally with one numerical thread; no cloud jobs, VR files or production
assets were changed. Ruff passes for the experiment directory.

### Independent deformation energies: pass

`independent_energy_check.py` evaluates nine archived MP2/cc-pVTZ geometries at exactly
their QM coordinates, with identical stable atom order. Geometry and QM output hashes
are checked. These energies were not used in the present angle fit, although earlier
independent development campaigns had used this archive. Each model's minimum-point
energy is subtracted; no fitted offset or re-minimization is used. The reference-zero
point is excluded from error statistics.

For six non-reference points below the existing 12 kcal/mol QM ceiling:

- Relative-energy RMSE **0.72329 kcal/mol**, passes existing 1 kcal/mol limit.
- Maximum absolute error **1.15497 kcal/mol**, passes existing 2 kcal/mol limit.
- The two higher-energy points are retained in the report, not silently discarded.

This validates these fixed-geometry deformations, not relaxed torsional barriers or
the full conformational landscape. Evidence: `.development-artifacts/cpd-independent-energy-v1`.

### Independent sugar attachments: geometry fails, implementation passes

`check_sugar_boundaries.py` uses two separate 49-atom QM-optimized cis-syn fragments,
one per retained sugar endpoint. The prior native-handedness audit passed both sugar
references. Standard CHARMM terminal deoxythymidine sugar charges/types come from a
fresh psfgen build; the opposite N1 methyl uses the explicit neutral cap convention.
Each fragment has 52 bonds and net charge zero, and all parameters load. No missing
boundary constants were invented. The initial v1 run stopped at an OpenMM terminal-H
name alias issue before model evaluation; the corrected v2 run is the result below.

| Check | Endpoint 1 | Endpoint 2 |
|---|---:|---:|
| C1'-N1 bond error, A | **+0.04025 (fail)** | +0.00223 (pass) |
| Maximum attachment-angle error, degrees | **4.52499 (fail)** | **5.22579 (fail)** |
| Sugar + lesion stereocenters | All 7 retained | All 7 retained |
| Maximum residual force, kcal/mol/A | 5.40e-6 | 5.86e-6 |
| Minimum internal curvature, kcal/mol/A^2 | +0.075205 | +0.213499 |

The 0.03 A/3 degree targets are unchanged. Endpoint 1's largest angle error is
C1'-N1-C6; endpoint 2's is O4'-C1'-N1. All five angles spanning each glycosidic bond
are recorded, including the H1' angle. These are gas-phase fragment comparisons,
not a claim about the solution-state nucleotide geometry.

`verify_boundary_engines.py` verifies positive internal curvature with halved finite
difference steps, and compares native NAMD with OpenMM at both QM and MM geometries
for each endpoint. All four native comparisons pass the existing 0.001 tolerances:
maximum energy discrepancy 0.000338 kcal/mol, maximum force-component discrepancy
0.000443 kcal/mol/A. Thus the observed geometry discrepancies are present in both
implementations and are not explained by an export mismatch.

Evidence: `.development-artifacts/cpd-sugar-boundary-validation-v2`, including native
logs, parameters, graph/charge assertions, atom maps through hash-pinned source model
manifests, optimized coordinates, all boundary angles, chirality and curvature checks.

**Verdict:** the independent capped-core energy check passes; sugar-boundary geometry
does not yet pass. Production remains disabled. Next correction should be restricted
to the glycosidic bond/angle model and tested across both endpoints, keeping the core
fixed and rerunning the core regression. Once boundary targets inform a correction,
they become training evidence and cannot alone establish independent boundary accuracy.
Relaxed glycosidic energetics and explicit-solvent validation remain outstanding.

## Angle refinement and NAMD verification, 2026-09-19

The user authorized continued angle correction toward NAMD verification. A new,
explicit **training refinement** follows the frozen earlier benchmark round; it does
not rewrite those failed results or turn the training geometry into held-out evidence.

`refine_angles.py` optimizes shared equilibrium angles only, each within +/-6 degrees
of the last-entry published-table reconstruction. Charges, force constants, torsions
and nonbonded parameters remain fixed. The C5 planarity impropers remain removed.
Version 1 retains a maximum angle error of 3.1568 degrees. Version 2 emphasizes
outliers in the objective while preserving the same 3 degree/0.03 A criteria:

| Calibration/check | Result |
|---|---|
| Maximum angle error | **2.852565 degrees**, passes 3 degree target |
| Maximum bond error | **0.0288818 A**, passes 0.03 A target |
| Maximum residual force | 3.78e-6 kcal/mol/A |
| Four lesion stereocenters | All retained |
| Smallest of 102 internal Cartesian curvatures | +1.05939 kcal/mol/A^2 |
| Exported vs fitted OpenMM energies/forces | Agrees within 1e-7 |
| Native NAMD vs OpenMM, minimum and +/- seeded distortions | All three pass existing 0.001 energy/force tolerances |
| Largest native energy difference | 0.0004673 kcal/mol |
| Largest native force-component difference | 0.0003203 kcal/mol/A |

Some angle shifts reach the imposed bounds; this is a bounded fitted candidate, not
proof that the published interpretation or its functional form is uniquely correct.
No independent conformational-energy or solution acceptance is claimed.

`export_angle_candidate.py` exports the same angle corrections as CHARMM parameters
and explicitly deletes the two C5 planarity impropers from the DNA patch. Fresh
63-atom d(TpT), 634-atom duplex, and matched control builds each pass native loading
and 500 fixed-heavy-atom hydrogen-minimization steps. The control still starts from
the damaged crystal geometry and needs separate equilibration. The full-nucleotide
and duplex runs are startup checks, not trajectory/solution validation.

Evidence roots:

- `.development-artifacts/cpd-angle-refinement-v1` (retained failed first attempt)
- `.development-artifacts/cpd-angle-refinement-v2` (training candidate, frozen source)
- `.development-artifacts/cpd-angle-native-v1` (export, minimum/chirality audit,
  source snapshots, native fixtures and energy/force agreement)

Next: independent conformational energetics and sugar-boundary checks, followed by
replicated explicit-solvent d(TpT)/duplex behavior with matched control. The anti/Drude
track remains separate; production remains disabled. This round ran locally with one
numerical thread, with no VR changes and no additional cloud allocation. Ruff passes
for the experiment directory; native checks above were actually executed.

The old cloud campaign is closed: provider absence was verified in its teardown
record, estimated cumulative cost including disk reserve is **$4.42744**, and all six
water validation cases were collected. The independent water RMSE is 1.2134 kcal/mol
for native terms, 0.3647 for the shared-depth hypothesis, and 0.1738 for the separate
O2/O4/H3-depth hypothesis. These results belong to the earlier anti/Drude work and do
not validate this additive cis-syn candidate.

## Local benchmark update, 2026-09-16

The user authorized a finite stopping criterion based on implementation correctness,
independent local evidence, available experiments, and application-specific uncertainty.
The versioned `local_benchmark_policy_v1.json` defines the first local checks; existing
historical results remain unchanged. The 0.03 A bond/3 degree angle targets follow the
CGenFF methodology, while numerical stationarity/curvature tolerances are project choices.

`local_benchmarks.py` builds the neutral 36-atom N-methyl CPD comparison model using
an explicit CGenFF 1MTH methyl-cap transfer, preserving published lesion charges. It
checks the archived QM atom map and coordinates by hash and evaluates both duplicate
interpretations without parameter fitting. Evidence:

- `.development-artifacts/cpd-published-local-benchmarks-v1`: original reconstruction.
  Both variants preserve four lesion stereocenters and reach stationary minima with
  positive internal curvature. Geometry fails: maximum bond error 0.1137/0.1196 A,
  maximum angle error 10.29/10.53 degrees.
- A controlled diagnostic identifies the inherited **C5 planarity impropers** as a
  major cause. The first reconstruction retained ordinary-thymine C5-C4-C6-C5M
  impropers, even though the product C5 is tetrahedral. SI Table S4 provides a
  matching type-level constant but not the authors' full topology. Thus this is a
  reconstruction issue, not evidence that the published author's implementation
  had the same fault. Earlier independent campaign plans also listed these exact
  precursor impropers for removal.
- `.development-artifacts/cpd-published-local-benchmarks-no-c5-planarity-v1`: explicit
  removal of those two impropers, no numerical parameter changes. First-entry variant:
  maximum bond error 0.03036 A, maximum angle error 6.39 degrees (10/72 above 3).
  Last-entry variant: maximum bond error **0.02840 A (pass)**, maximum angle error
  **5.40 degrees (11/72 above 3, fail)**. Both remain stationary, retain all four
  centers, and have positive internal curvatures. The C5-C5 error drops to 0.013/0.017 A.
  The geometry motivated this correction and is explicitly development evidence for
  the corrected candidate, not a fresh held-out validation claim.

The earlier full-nucleotide/duplex files still contain the original C5 impropers and
must be regenerated with explicit deletion before further dynamics. They remain
comparison-only artifacts. No production parameter or application topology changed.

`soft_mode_benchmark.py` records directional curvature along six independent QM soft
directions, including step-halving checks and cap/heavy-atom participation. Different
minimum conformations and methyl rotations confound a direct Cartesian comparison;
the ratios are **not intrinsic stiffness ratios or a mechanical acceptance verdict**.
Internal-coordinate mapping or matched finite-conformation QM energies are still needed.

Current verdict: bond geometry, local minimum and stereochemistry checks are available;
angle accuracy remains a limitation and independent conformational energetics and full
engine force agreement remain untested here. **No local-acceptance or release pass.**
Next work should address the named ring-junction angle outliers and independent
conformational energetics, rather than restart broad charge/bond fitting. Both source
interpretations remain explicit alternatives; the one passing bond geometry is not
thereby identified as the authors' intended model. All experiments ran locally with
one numerical thread. Ruff passes; no broad backend/UI tests were needed.

Started 2026-09-16 following the user's approved course correction. All outputs are in
`.development-artifacts/cpd-published-comparator-v1`. No production assets, scientific
thresholds, VR files, shared settings, or capability gates were changed.

## Completed

- Recovered Ma/van der Vaart SI through the publisher's Figshare API, article 5226184,
  DOI 10.1021/acs.jcim.7b00215.s001. Metadata records CC BY-NC 4.0. PDF SHA256:
  `f3ae73efc282af07671139946d2dbf58de2172aad8d68085edf300af79681e74`.
- Visually transcribed Figure S1 atom types/charges. The base charge sums to zero.
  Extracted 148 table rows with page/line provenance, including three commented rows.
- Found 43 conflicting active type/multiplicity groups in Table S3. Built explicit
  first-entry and last-entry hypotheses; neither is claimed as an exact reproduction.
  Parameter-overlay reports preserve replacement warnings and inherited Fourier terms.
- Fresh psfgen builds of a 63-atom complete CPD d(TpT), a 634-atom 1N4E A/B duplex,
  and matched ordinary-thymine control. Net charges are -1 and -18 respectively.
  Syn C5-C5/C6-C6 links come from deposited LINK records B15/B16. No historical anti
  product PSF was reused. Standard sugar/phosphate chemistry is retained.
- Both CPD interpretations and the control load successfully in native NAMD: five
  reference-fixture loads total. All 37 dimer/404 duplex surviving reference heavy
  atoms retain their deposited coordinates exactly.
- Five native 500-step hydrogen-only minimizations completed on one CPU core with
  heavy atoms fixed and fixedAtomsForces on. Heavy coordinate changes are below
  8e-15 A. This is neither a convergence assertion nor DNA dynamics validation.
- OpenMM/native total-energy comparison at the same relaxed coordinates is recorded:
  absolute discrepancies 0.00164/0.00186 kcal/mol for the dimer hypotheses,
  0.00490/0.00610 for duplex hypotheses, and 0.05360 for control. These are diagnostic
  results, NOT a declared engine-agreement pass. Force and per-component checks remain.
- Ruff passed for both experiment scripts. No backend/UI behavior changed, so no broad
  application test suite was run. Existing cloud worker and budget watchdog remained
  active; this comparator used no new cloud allocation and no GPU.

## Remaining limitations and next work

1. Resolve/document Table S3 interpretation and inherited Fourier terms. CGenFF 5.0
   supplies explicitly pinned nonbonded/parent terms; the exact 2017 dependency is
   unavailable. Avoid calling this hybrid dependency choice the original authors' model.
2. Audit every applied parameter's origin and independent graph/term coverage, including
   stereochemical impropers. Compare per-component energies/forces and electrostatic
   constant conventions before claiming engine agreement.
3. Check lesion and sugar signed volumes. The deposited heavy coordinates establish
   the initial structural reference, but guessed hydrogen relaxation is not sufficient
   for a stereochemical or conformational acceptance verdict.
4. Build compatible explicit solvent/ions and equilibrate each hypothesis and control
   independently. The control currently shares the damaged crystal geometry and is not
   an equilibrated undamaged baseline. Replicated dynamics and structural comparisons
   remain outstanding. Do not run a long trajectory from the unrelaxed topology probe.
5. Keep anti/Drude separate; no parameter in this comparator validates the interstrand
   anti product. No additional bespoke fitting was launched for this reconstruction.

## Reproduction

With the source PDF, pdftotext extraction, and downloaded 1N4E PDB in the evidence root:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/reconstruct.py --root .development-artifacts/cpd-published-comparator-v1
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/reference_build.py --root .development-artifacts/cpd-published-comparator-v1
```

Evidence includes publisher metadata, source hashes, source transcription, explicit
duplicate policies, topology/parameter files, native logs, fixed-heavy minimizations,
energy-comparison script/results, and executed source snapshots. The parameter and
coordinate files are comparison candidates only; `simulation_ready` remains false.
