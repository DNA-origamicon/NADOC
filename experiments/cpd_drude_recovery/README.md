# Anti-CPD Drude recovery and bonded continuation

The continuation found a chemical-graph defect in the previously passing P2/P3
evaluators. `drude_model.py` and its NAMD PSF both used C5–C5/C6–C6 syn crosslinks
for cis-anti-I. The registry, independent bonded plan, and QM geometry instead
require C5–C6/C6–C5. At the reference geometry, the correct crosslinks are
1.5562/1.5523 Å; the incorrectly bonded diagonals are 2.1727/2.0991 Å.
This changes exclusions and screened Drude pairs. Prior engine agreement therefore
does not establish the right chemical model. P1 fixed-geometry QM remains reusable.

All prior hashed evidence is preserved. The superseding invalidation is
`.development-artifacts/cpd-drude-anti-graph-recovery-v1/upstream_invalidation.json`.
No registry release or simulation-readiness flag was enabled.

The corrected graph retained acceptable response-training metrics with unchanged
parameters but failed the absolute dipole gate: 0.18818 au versus 0.10 au. Two
registered charge/scale refinement cycles recovered the training objectives:

| Corrected-graph electrostatic quantity | Result |
|---|---:|
| Response ESP relative RMS | 0.16560 |
| Dipole-response relative RMS | 0.14966 |
| Scaled polarizability tensor relative error | 0.05345 |
| Zero-field ESP RMS | 0.00027055 au |
| Zero-field dipole vector error | 0.011875 au |
| Maximum training Drude displacement | 0.17692 Å |

The frozen file is `corrected_parameters.training_frozen.json` in the recovery
directory. Historical holdout target values were not read during this correction.
This is a training recovery, not restored P2 acceptance. Corrected electrostatic
engine response agreement now passes (see below); independent QM validation
remains outstanding. A previously exposed holdout must
not be relabeled as fresh evidence.

## Bonded diagnostics

`campaign.py` verifies the registered anti crosslinks and the entire independent
QM bonded graph, builds a Drude-family fixed bonded baseline, promotes missing
terms, and differentiates the relaxed-polarization nuclear surface. Lone pairs
follow their local coordinate frames; induced particles relax at every displaced
geometry. The analytic nuclear gradients are checked against energy differences,
and Hessians are checked with a halved displacement. Artificial Drude vibrational
modes are not included in the nuclear target Hessian.

The first preflight also exposed an unofficial `HDA1` label in the archived water
evaluator and special 1–4 LJ values that must be retained in intramolecular work.
The corrected bonded evaluator uses the published CD31A/HDA1A methine analog,
actual CHARMM LJ/1–4 records, and declared MTHY sp2-planarity priors. Those analogies
remain subject to geometry and transferability validation.

The original five QM structures retain their three-training/two-validation split.
They have been used in prior fitting; these diagnostics do not create a new
independent validation set. Native Drude coefficients are used only for explicit
transfer hypotheses; old additive fitted coefficients are not transferred.

| Diagnostic | Result |
|---|---|
| Initial 144-parameter baseline | Numerical response checks pass; later superseded by corrected LJ conventions |
| Corrected 142-parameter baseline | Joint design full rank; selected ridge 0.01; geometry fails, maximum bond error 0.08018 Å and C2 endpoint 2 reaches 0.20 Å Drude limit |
| Broad pyrimidine expansion | 174 parameters, joint rank 172; selection rejected under unchanged rank gate |
| Pyrimidine bond/angle expansion | Selected ridge 0.0001; retains all stereocenters but maximum bond error 0.04791 Å exceeds 0.03 Å; worst term is C5–C7 |
| Corrected electrostatics plus methyl attachments | 162 parameters, joint rank 162; ridge 0.0001; final relaxation iterate still fails with C5–C7 error 0.04885 Å |

The final recorded diagnostic includes corrected electrostatics and refits the
methyl-attachment heavy-atom bond/angle terms as well. It is stored under
`.development-artifacts/cpd-drude-bonded-pyrimidine-v3`. It retained all four
stereocenters and stayed inside the Drude displacement domain during relaxation,
but reached the 2,000-iteration limit without satisfying the optimizer's gradient
criterion (final gradient RMS 1.44e-5 kcal/mol/Å). The last iterate has heavy-atom
RMSD 0.1190 Å. Its largest bond errors are C5–C7 at endpoint 1 (+0.04885 Å),
C5–C7 at endpoint 2 (+0.03580 Å), and C2–N3 at endpoint 1 (+0.03490 Å).
These are last-iterate diagnostics, not a demonstrated converged MM minimum.
The geometry result fails the unchanged 0.03 Å limit independently of the
optimizer's non-success status. **P4 and full CPD-nucleotide validation remain
blocked.** Coefficient selection alone is not an acceptance gate.

## Full-nucleotide precursor

An isolated unmodified d(TpT) build now passes independent nuclear-graph and
parameter-load checks. The psfgen compatibility investigation preserved its failed
attempts: unsupported redundant anisotropy deletion, duplicated patch bonds and
anisotropy, and a surviving serial-zero bond to the deleted 5′ phosphate.

The local candidate removes only redundant inherited patch interactions. The PSF
repair removes the specifically identified zero-index bond and its derived
angles/dihedrals; it rejects other malformed or duplicate surviving terms. The
complete surviving nuclear graph must match the independent additive precursor
exactly before parameter loading is attempted.

The corrected precursor has **63 nuclei, 66 nuclear bonds, 37 Drudes, 18 lone
pairs, 12 unique anisotropy centers, 118 total particles, and charge −1 e**.
OpenMM builds its system, and the compatible CPU NAMD build completes a real
zero-step load with finite energy. This high-energy source geometry is not an
equilibrated nucleotide. No CPD product, solution stability, or DNA-context
validation is claimed.

Evidence lives in `.development-artifacts/cpd-drude-nucleotide-preflight-v4`.
The compatible RTF and raw psfgen build are retained in `...-preflight-v2`;
`nucleotide.py` reproduces the audited PSF repair and independent graph comparison.
Native warnings about lone-pair/Drude bond representation are classified in
`namd_load_assessment.json`. Future aqueous runs must explicitly specify SWM4-NDP;
the dry zero-step probe's default-water warning is not a water-model validation.

## Remaining gates and automation

1. Complete corrected-graph electrostatic validation and engine comparison.
2. Resolve the water-target convention (the archived P3 uses additive-style
   1.16-scaled HF targets), and revalidate using the corrected graph and types.
3. Pass independently minimized geometry/Hessian/PES checks with the accepted
   nonbonded model, including the methyl and glycosidic boundaries. The immediate
   bonded problem is the remaining C5–C7/C2–N3 geometry error: reassess the
   force/Hessian weighting and an identifiable geometry-constrained refinement.
   Add targeted coupled torsion/conformer QM only when the existing five
   structures cannot identify the necessary correction; retain the rejected
   174-parameter expansion as evidence of that limitation.
4. Assemble the CPD full-nucleotide product and audit its sugar-interface charges,
   atom types, virtual sites, bonded terms, and stereochemistry; a correct
   precursor graph does not establish this transfer.
5. Run staged ≤1 fs Drude/SWM4-NDP solution validation and then the intended
   interstrand junction with controls and replicated sampling.

The old P3 fitting/scoring service was stopped to prevent promotion based on the
wrong graph. Its Alpine azimuth-240 QM job remains submitted (last checked:
PENDING, Priority). `nadoc-cpd-water-qm-collect-only-v1.service` collects and
audits raw QM only; it cannot fit or promote P3/P4.

`fit.py` applies the existing physical-equilibrium/selection policy; `geometry.py`
performs unrestrained nuclear minimization with small trial steps and rejects
invalid induced-particle states. Five lightweight regression tests cover syn/anti
graph substitution, duplicate/invalid bonds, and serial-zero PSF handling.
Application backend behavior and user designs are unchanged.

Verification: `just test-file tests/test_cpd_drude_recovery.py` passed all five
tests; Ruff check and format check passed. Native evidence generation included
the five-structure Drude response campaigns, bounded coefficient fits,
independent nuclear relaxations, actual psfgen builds, OpenMM parameter loading,
and the NAMD precursor zero-step run. No production trajectory was launched.
Scientific evidence is retained outside the user workspace under the
`.development-artifacts` archive symlink; only disposable Python caches were
removed. The recovery directory's `continuation_closeout.json` and
`artifact_inventory.json` identify the current state and retained evidence.

## Fitted-response audit and stationarity diagnosis

`audit.py` independently evaluates the selected 162-parameter system at all five
QM structures. The archived linear response reproduces direct forces to
1.46e-11 kcal/mol/Å maximum error; three seeded directional Hessian checks per
structure agree within 5.74e-9 relative error. Projected residual bookkeeping also
passes. Evidence is retained in
`.development-artifacts/cpd-drude-bonded-reconstruction-audit-v2/assessment.json`
(the initial reconstruction-only audit is retained as v1).

At the QM minimum, unrestricted least squares in the current gradient basis has
rank 76 and an irreducible raw gradient RMS of 4.35205 kcal/mol/Å. Its largest
atom residual norms are on hydrogens (up to 16.16 kcal/mol/Å). Thus simply
increasing the minimum-gradient weight cannot make this basis exactly stationary.
Adding 50 independent hydrogen-containing bond/angle gradient columns raises
rank to the 102 internal degrees of freedom and lowers the unconstrained residual
to 6.41e-11 kcal/mol/Å. This is a local linear-space diagnostic, **not** an
identifiable or physically constrained fitted candidate and not proof of the
cause of the C5–C7 bond error.

The next bounded fit experiment should promote chemically grouped hydrogen
bond/angle transfer hypotheses, audit joint identifiability before fitting, and
retain physical curvature/equilibrium constraints. Assess minimum stationarity,
full relaxation and Hessians together; do not retune against a renamed fresh
holdout. The existing 0.03 Å geometry threshold and all release gates remain.

## Hydrogen expansion: current bonded candidate

The `--promote-hydrogen` experiment promotes available hydrogen-containing
bond/angle transfers, sharing chemically equivalent methyl hydrogens and both
endpoints while distinguishing N-methyl, C5-methyl, amide and methine environments.
Its artifacts are in `.development-artifacts/cpd-drude-bonded-hydrogen-v1`:
178 parameters, joint rank 178 at the unchanged 1e-8 relative threshold, and
condition number 3.11e7. The unconstrained minimum-gradient residual floor falls
from 4.35205 to 0.53650 kcal/mol/Å RMS. The physical fit selects ridge 0.0001;
the historical validation score decreases from 0.78959 to 0.20328. These are
model-development diagnostics on reused data, not new independent acceptance.

The direct force/Hessian reconstruction audit passes for all five structures
(`cpd-drude-bonded-hydrogen-audit-v1`). Initial BFGS relaxation preserves all four
stereocenters and reduces heavy-atom RMSD to 0.09153 Å, but stops at numerical
stagnation. `geometry.py` now explicitly detects 20 consecutive sub-1e-10 Å steps
without weakening its original 1e-5 kcal/mol/Å maximum-gradient requirement.

`stationary.py` then applies only small Newton corrections in the Cartesian
internal-coordinate subspace, checks positive curvature, and verifies the final
Hessian by step halving. The current result is
`.development-artifacts/cpd-drude-bonded-hydrogen-stationary-v2/assessment.json`.
It proves a local MM minimum: maximum gradient 6.51e-10 kcal/mol/Å and all 102
internal curvature eigenvalues positive. **Geometry still fails:** endpoint 2
N3–C4 is too long by 0.03153147 Å against the unchanged 0.03 Å bound. This is now
a converged-minimum failure, not an unfinished-optimizer result. Earlier
reconstruction and stationary runs remain retained.

Next: inspect minimum versus displaced-conformer residuals and the N3–C4
bond/angle/improper balance; formulate a prospective, physically constrained
stationarity-aware fit objective before refitting. Retain endpoint/equivalent-atom
sharing unless independent evidence justifies differentiation. Require geometry,
QM Hessian/mode and torsional profiles together; no release based on this local
minimum check. Water-target methodology and the required correlated-QM pilot are
recorded in [water_target_audit.md](water_target_audit.md).

Run local numerical scripts with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`.
The initial 32-thread fit consumed excessive CPU; its deliberate resource restart
is recorded in `fit_resource_restart.json`. The unchanged frozen specification
completed with one BLAS thread. This interruption is not classified as a failed
scientific fit.

## Equilibrium-weighted diagnostic: current candidate, not P4 acceptance

`equilibrium_fit.py` freezes one prospective diagnostic with a tenfold multiplier
on the audited minimum's projected gradient block; other training rows, ridge
0.0001, coefficient bounds and physical equilibrium constraints are unchanged.
There is no validation-driven weight search. Its custom diagnostic schema does
not impersonate selection under the original quantitative policy. The unchanged
178-parameter training basis retains full joint rank. The first attempt stopped
on a loader-field error before solving and is retained as `equilibrium-v1`;
`equilibrium-v2` contains the completed fit. Source arrays are read-only symlinks
to the original hydrogen experiment, with their original provenance retained.

The new candidate reaches a numerically verified local minimum and passes the
existing bond/stereochemistry diagnostic: maximum bond error 0.01232436 Å versus
0.03 Å, all four stereocenters retained, maximum gradient 9.81e-9 kcal/mol/Å,
positive internal curvature and a passing Hessian step-halving check. Evidence:
`.development-artifacts/cpd-drude-bonded-equilibrium-stationary-v2`. Direct force
and Hessian reconstruction also passes (`equilibrium-audit-v1`).

Broader physics is **not accepted**. Heavy-atom RMSD increases to 0.12552 Å.
The minimum projected gradient RMSE improves from 2.12786 to 1.47245, while its
Hessian RMSE increases from 7.08788 to 7.38205. Historical validation gradient
RMSE changes from 5.52383 to 5.42632 and Hessian RMSE from 6.85933 to 7.07487.
These are projected mass-weighted fitting metrics, not raw Cartesian forces.

`modes.py` compares the nuclear Hessians at each method's own minimum, removing
six rigid-body modes and rotating the MM Hessian into the QM frame. It excludes
auxiliary Drude modes and applies no empirical frequency scaling. Maximum-total
squared-overlap assignment gives frequency RMSE 169.49 cm^-1 and median squared
mode overlap 0.400; sorted-frequency RMSE is 133.37 cm^-1. Near-degenerate mode
assignments require subspace review. The largest angle error is 4.8633 degrees
at endpoint 1 C6–N1–CM; angle RMS error is 1.7071 degrees. Data are retained in
`cpd-drude-bonded-equilibrium-modes-v1`; no retrospective spectral or angle
acceptance cutoff has been asserted.

Next work must examine the N1/C4 planarity-transfer hypotheses and mode
subspaces, then obtain independent torsional/conformer validation. The original
MTHY N1 improper atom order was checked against `na.rtf`: N1 C6 C2 C1 matches the
candidate N1 C6 C2 CM (the parameter lookup is its reverse), so this is not an
atom-order discrepancy. No further weight sweep is justified merely to improve
a reported metric. Corrected electrostatics/engine agreement, correlated-QM water
targets, sugar/backbone transfer, full CPD-product construction, and replicated
solvated DNA validation remain required. The HF fourth-orientation job 32610248 subsequently completed; no replacement was submitted.

## Correlated-water pilot and historical BSSE correction

The one-contact frozen-core DF-MP2/cc-pVQZ counterpoise pilot completed on
Alpine as job **32612082** (25m50s; peak RSS 50,827,176 KiB). Frozen inputs,
submission hashes and collected output are under
`.development-artifacts/cpd-drude-water-correlated-pilot-v1`. Its canonical
endpoint-1 O4 / 1.8 Å interaction energy is -3.40681829375811 kcal/mol;
this is one rigid-geometry feasibility result, not a nonbonded validation pass.
The separate HF fourth-orientation job 32610248 also completed.

Preparing the pilot exposed another historical provenance defect: all **216**
HF job inputs referenced by the old P3 fit lack counterpoise correction, despite
the old P3 policy's CP label. Their manifests explicitly say false, and the
hash-verified inputs compute unghosted monomer energies. The old loader uses
these curves with both the 1.16 scale and -0.2 Å offset. This was an input-only
audit; no withheld QM energy values were opened. The evidence and revised method
assessment are in [water_target_audit.md](water_target_audit.md). This does not
change the independent syn/anti graph invalidation or rehabilitate old P3 fits.

The current bonded candidate remains `cpd-drude-bonded-equilibrium-v2`: local bond
geometry and stereochemistry pass, but broader mode/angle/PES validation is open.
Next local work can inspect N1/C4 planarity priors or corrected NAMD/OpenMM
agreement while the expanded correlated batch runs. Full CPD-nucleotide product and DNA
solution validation remain outstanding; no production gate has changed.


## Local / RunPod routing, total cloud budget $5 (2026-09-16)

The user authorized local execution where feasible and RunPod for larger jobs,
with **$5 cumulative new cloud compute/storage spending**, including retries.
The existing unrelated network volume is outside this campaign and is untouched.

The local portability benchmark ran in
`nadoc-cpd-local-memory-benchmark-v1.service` with eight CPU threads, 16 GiB
Psi4 memory, a 20 GiB cgroup cap, no swap and a two-hour deadline. Its artifacts
are in `.development-artifacts/cpd-drude-local-memory-benchmark-v1`. It repeated
the pilot chemistry without method changes but hit the two-hour limit without
finishing. `assessment.json` records the failed feasibility trial; substantial
disk I/O makes this method a poor local fit under the workstation memory cap.
No completed local energy or portability pass is claimed.

The cloud batch in `.development-artifacts/cpd-drude-cloud-budget5-v1` contains
12 counterpoise water targets: six training orientations and six alternate-plane
validation orientations at 1.8 Å. These reuse archived geometries and are not
fresh-geometry holdouts or complete interaction curves. The first case must
reproduce the Alpine result within 1e-5 kcal/mol before the batch continues.
`cloud_water.py` uses an eight-vCPU / 64 GB CPU-only quote, a cumulative $4
working ledger and $1 reserve, at most six hours, local and pod-side termination
guards, and continuous downloads onto Archive. The worker pins Psi4 1.11.
GPU attempts failed before allocation; current launch/teardown and ledger files
are the authority for cloud state and cumulative cost. No release gate changes
on launch, collection or process success. Full nucleotide and solution DNA
validation remain open.

Three cloud training targets have now completed and passed the independent
`audit_water_results.py` execution/provenance/arithmetic checks. The first target
agrees with Alpine within 3.7097e-9 kcal/mol (limit 1e-5). The audit verifies raw
unscaled MP2 component energies, convergence, common full basis, frozen-core
occupations and explicit CP subtraction, retaining hashes of outputs and results.
Its six focused regression tests pass, including rejection of scaled energies,
missing convergence, wrong basis/core occupations and NaN. Validation target
values remain unread by this audit. These three single-distance targets are
usable execution evidence, not independent nonbonded validation or P3 acceptance.
The cloud batch remains live under the original budget and termination deadline.


## Corrected electrostatic engine response (local)

`engine_compare.py` rebuilds the archived eight-case response probe with the
correct anti crosslinks and frozen corrected charges, polarizabilities, Thole
factors and anisotropy. The generated PSF nuclear graph must match the corrected
model in full and the registered crosslinks independently. Exact-coordinate
binary inputs remove PDB rounding from the fixed nuclear reference. NAMD CPU
uses the previously established fixed-atom, zero-temperature damped Drude method
with `fixedAtomsForces on`, 20,000 steps of 0.5 fs, and two CPU threads.
No withheld QM target values are read for this engine-only comparison.

All eight originally registered test positions pass the unchanged 2% tolerance
for molecular induced dipole, full per-Drude displacement vectors, and response
ESP. Maximum relative errors respectively are 5.947e-6, 3.4243e-5 and 6.420e-6
(0.000595%, 0.00343%, 0.000642%). All nuclear coordinates and the external charge
remain exactly fixed. Largest final Drude displacement is 0.16050 Å, within
0.20 Å. Each native run reaches step 20,000; final printed kinetic energy is zero.
Evidence, native logs, generated PSF/RTF, source hashes and assessments are in
`.development-artifacts/cpd-corrected-engine-v1`.

This restores only corrected-graph electrostatic response agreement. It does not
validate absolute energies/forces, the candidate bonded/LJ terms, independent QM
response, the full CPD nucleotide, or DNA solution behavior. Production remains
disabled. Continue with independent electrostatics scoring, bonded mode/PES and
sugar/backbone transfer, alongside the budget-limited water campaign.


## Historical regression and fresh electrostatic validation

The corrected frozen model passes all 24 historically reserved targets without
parameter changes: response relative RMS 0.166050, dipole-response RMS 0.148479,
reserved/training response ratio 1.002706, maximum Drude displacement 0.170067 Å.
Static and polarizability checks also pass unchanged thresholds. Evidence is in
`cpd-corrected-electrostatics-regression-v1`. These targets were already exposed
in the historical campaign; this is regression evidence, not fresh validation.

`prepare_fresh_esp.py` has frozen 24 new external-charge positions: 16 at surface
scale 2.2 and 8 at 4.0. Geometry-only maximin selection uses a denser 384-direction
exposed scaled-Bondi surface and all historical positions as exclusion anchors.
Minimum separation from prior positions is 1.89489 Å. No fresh QM targets or MM
errors were used for selection. Same capped anti geometry, B3LYP/aug-cc-pVDZ,
+0.5 e perturbation, ESP readout grid and acceptance limits; this tests new
perturbations, not new conformers or nucleotides. Inputs and frozen parameter
hashes are in `cpd-fresh-esp-validation-v1`.

A local zero-field DFT reference calculation is running under
`nadoc-cpd-fresh-esp-portability-v1.service`: eight threads, 10 GB Psi4 memory,
16 GiB cgroup cap, no swap, 30-minute deadline. Before running the new positions,
require successful completion and agreement with the archived zero-field target
within ESP RMS 1e-7 au and dipole-vector error 1e-6 au. Large MP2/cc-pVQZ remains
on the original RunPod campaign; no additional cloud allocation was launched.


The local DFT reference completed in 109 seconds and passed portability:
ESP RMS 8.9502e-11 au and dipole-vector difference 1.6321e-8 au. The full fresh
24-position campaign is now running serially in
`nadoc-cpd-fresh-esp-validation-v1.service` with the same 16 GiB cap and eight
threads. `run_fresh_esp.py` checks the frozen plan/input/grid/parameter hashes,
requires successful SCF and finite complete ESP/dipole outputs, and scores only
after all 24 cases finish. No refitting or production release is automatic.
Each case has a 30-minute bound; total service bound is 12.5 hours. Progress and
terminal assessments remain in `cpd-fresh-esp-validation-v1`. Three focused
runner regression tests pass. The separate RunPod water campaign keeps its
original cumulative $5 authorization; no new cloud resources were created.


## Bonded mode-subspace and directional diagnosis

`subspaces.py` now examines full mass-weighted mode subspaces and independent
neighbor-plane geometry; `directional_bonded_audit.py` resolves QM-reference
curvatures into fixed and fitted terms. Evidence is in
`cpd-bonded-mode-subspaces-v1`. Frequency bands/windows are diagnostic choices,
not new acceptance criteria; no fitted coefficients were changed.

The two worst high-overlap stretches are C6–H6: QM 2977/3094 cm^-1 versus MM
2480/2484 cm^-1, with squared overlaps 0.897/0.856. This discrepancy persists
beyond near-degenerate mode mixing. At the QM geometry, COM-preserving stretch
curvatures are 698.74/754.73 kcal/mol/Å² (QM) versus 484.57/485.62 (MM).
The common fitted H6 bond has k=239.0516 kcal/mol/Å², supplies ~478.10 of each
curvature, and lies inside its bounds. Thus the deficit is primarily a fitted
stiffness/objective compromise, not an inherited fixed bond or active bound.
This does not justify setting k directly from these two diagnostics.

Endpoint-1 N1 lies 0.289 Å from its neighbor plane in QM and 0.421 Å in MM;
neighbor angle sums are 348.04° and 335.08°. Its residual normal gradient at
the QM minimum is -1.414 kcal/mol/Å with contributions from both fixed and
fitted terms. The improper alone has not been isolated as the cause. Carbonyl
centers are much closer to planar. Next work should audit force/Hessian block
normalization and coupled sensitivities before formulating a prospective fit
change, then test independent PESs. No mode or full-nucleotide pass is claimed.


## H6 objective audit and endpoint hypothesis

`objective_audit.py` reproduces the actual training objective along H6 stiffness
at fixed equilibrium length. Force-block derivative +1.209895e-4, Hessian
-1.213975e-4 and ridge +4.07993e-7 cancel to -1.82e-11 per unit k; an independent
central difference verifies the derivative. This is a true constrained-fit
compromise, not solver nonconvergence. Conditional block optima at fixed other
coefficients differ sharply: the weighted minimum gradient favors k~102,
whereas its Hessian favors ~365.5. These conditional values are diagnostic,
not proposed physical force constants.

An isolated prospective `--split-h6-endpoints` hypothesis is now building in
`cpd-drude-bonded-h6-endpoints-v1`, service
`nadoc-cpd-h6-endpoints-basis-v1.service` (two threads, 6 GiB, one-hour bound).
It separates only the two C6–H6 bond groups, allowing different stiffness and
equilibrium length in the asymmetric anti environment. Exactly one occurrence
per endpoint group is verified. This adds two coefficients; full training-rank
and derivative checks are required again before fitting. All other groups,
electrostatics, dataset partitions and acceptance limits remain unchanged.
Five graph/topology regression tests pass. No new force-field candidate has
been accepted or released by this hypothesis.

The endpoint response build subsequently completed: 180 parameters, numerical
derivative checks passed. Its identifiability record is in the response campaign
manifest and the continuation closeout; inspect it before selecting a fit.


The endpoint-specific fit has now completed with the same fixed 10x minimum
force weight, ridge 1e-4 and physical bounds. The warm start reproduces the
previous gradients within 8.6e-14 kcal/mol/Å and Hessians exactly at all five
structures. A Newton refinement verifies a local minimum with maximum gradient
2.34e-8 kcal/mol/Å and maximum bond error 0.012672 Å, preserving all stereocenters.
However, matched mode RMSE remains 168.69 cm^-1 and maximum angle error increases
to 5.14°. Endpoint-2 H6 remains 700.57 cm^-1 too low with squared overlap 0.9504.
**Endpoint splitting does not resolve the physics and is not accepted.** Evidence:
`cpd-drude-h6-equilibrium-v1/hypothesis_assessment.json` and the corresponding
`cpd-drude-h6-stationary-v1` / `cpd-drude-h6-modes-v1` directories.

The target audit explains a major objective conflict: endpoint-2 C6–H6 is
1.09869 Å at the QM minimum but 1.29654 Å in training conformer-004 and
1.29697 Å in validation conformer-003. Its QM directional curvature changes
from 754.73 to 186.89/178.84 kcal/mol/Å². A common harmonic bond curvature cannot
represent that degree of anharmonic softening. This does not authorize dropping
those targets or weakening acceptance. Next obtain prospectively defined,
independent near-equilibrium stretch/PES evidence and conformers that preserve
covalent geometry; quantify the intended harmonic model domain explicitly.
The existing strained conformers and failed hypotheses remain documented.


## Independent H6 scan (prospectively frozen)

`cpd-independent-h6-scan-v1` now contains 17 fixed-coordinate QM calculations:
a reference, then COM-preserving C6–H6 displacements -0.04, -0.02, -0.01,
+0.01, +0.02, +0.04, +0.10 and +0.20 Å at each endpoint. This independently
samples bond-coordinate response on the same capped anti reference geometry;
it is not a relaxed torsion scan or a nucleotide model. The method matches the
original harmonic evidence: frozen-core DF-MP2/6-31G(d), RHF, Psi4 1.11.
[Psi4 DF-MP2 documentation](https://psicode.org/psi4manual/master/dfmp2.html)
documents the analytic-gradient capability used here.

Before displaced points run, the local reference must match the archived energy
within 1e-6 hartree and maximum gradient component within 1e-5 hartree/bohr.
`nadoc-cpd-independent-h6-scan-v1.service` runs serially with four threads,
4 GiB Psi4 memory, a 6 GiB cgroup/no-swap cap and two-hour total deadline.
`stretch_qm_worker.py` checks source/worker hashes, version and finite outputs.
The reference subsequently passed: energy difference 7.93e-9 hartree and
maximum gradient difference 2.32e-6 hartree/bohr. Displaced points are running.
No additional RunPod allocation.

`predict_h6_scan.py` already froze energies and gradients from both the shared
and endpoint-specific H6 candidates at all 17 points, without reading new scan
QM values. All positions stayed in the evaluator domain. Compare energy changes
from the common reference and projected gradients separately for near-equilibrium
and extended challenge points; retain every failure. No fitting to this scan
or new acceptance threshold is authorized by its diagnostic plan.


`assess_h6_scan.py` now compares provenance-checked QM scan outputs with both
frozen model predictions, using consistent hartree/bohr-to-kcal/mol/Å units.
It reports every missing case and separates endpoint and displacement regime;
partial RMS errors are not acceptance checks. Four focused tests pass for unit
conversion and malformed/nonfinite results. The first displaced point and
reference have been assessed, but the full scan is still running. Terminal
collection is armed as `nadoc-cpd-h6-scan-assessment-v1.service`, which records
native service state and generates the final (or explicitly incomplete) report.

RunPod's fourth water target completed and the worker was verified actively
computing the next target. Continuous downloads and the original cost deadline
remain in force. Use `training_execution_audit.json` for the latest audited
training coverage; validation values remain sealed from that training audit.


## Full-nucleotide boundary accounting

`nucleotide_boundary.py` now audits a complete base-site mapping from the frozen
capped anti fragment to the actual unmodified Drude d(TpT) PSF. It explicitly
combines each native core with its bonded Drude when comparing permanent
charges. Both removed N1-methyl caps are neutral; the remaining candidate base
charges are +0.02093384 and -0.02093384 e. Replacing both native neutral base
groups therefore preserves the precursor total charge of -1 e. No fitted
charges were changed. This is accounting evidence only, not sugar transfer.

The independent expected nuclear graph has 63 nuclei and 68 bonds after adding
the two registered anti crosslinks to the 66-bond precursor. No new product PSF,
geometry, bond-order assignment or intrastand anti conformation is validated by
that count. The audit identifies two glycosidic bonds, ten adjacent angles and
28 dihedrals containing the N1–C1-prime bond (12 with it as the central bond).
Their native types and atom identities are recorded for transfer review. DNA
uses ND2R6D at N1 while the capped analogue used ND2R6C; cap torsions cannot
establish sugar chi energetics or boundary polarization response. All of these
remain physical validation requirements. Evidence:
`cpd-drude-nucleotide-preflight-v4/boundary_charge_graph_audit.json`.


## Absolute electrostatic probe energy check

`engine_energy.py` compares OpenMM at exactly the nine saved NAMD coordinate
sets (zero field plus eight perturbations). It subtracts the independently
computed dummy CPDX nuclear/LP harmonic-bond energies from NAMD and verifies
that unrelated angle, torsion, improper, LJ, boundary, misc and kinetic entries
are zero. The largest remaining absolute difference is 0.00021402 kcal/mol.
NAMD energies have four printed decimals and its PSF charges have six, whereas
OpenMM uses the full frozen charge precision; no precision-adjusted fitting or
new acceptance gate was introduced. This diagnostic excludes a substantial
common energy offset that response differences alone could miss. Evidence:
`cpd-corrected-engine-v1/absolute_energy_diagnostic.json`. It is not a test of
the candidate bonded potential, nuclear-force agreement or nucleotide transfer.


## Frozen native-water predictions and stationary-force refinement

`predict_water.py` freezes all 12 batch predictions without reading QM target
values. It uses the corrected anti graph and frozen electrostatics, exact relaxed
monomer subtraction, native CHARMM LJ/NBFIX, and the actual HDA1A type for H6.
The old fitted water NBFIX, energy scaling, distance shift and far-separation
reference are not used. Evidence: `cpd-native-water-predictions-v1`.

Two validation-geometry predictions initially exceeded the unchanged 1e-4
kcal/mol/angstrom Drude-force tolerance despite displacements below 0.2 A.
`refine_water_minima.py` preserved an unsuccessful energy-based BFGS attempt;
`refine_water_forces.py` then solved stationary Drude forces directly with fixed
nuclei/LP sites. All 12 solutions pass: maximum force 1.272e-12 kcal/mol/A,
positive minimum Drude Hessian eigenvalue 196.335 kcal/mol/A^2 with both finite
difference steps (1e-5 and 5e-6 A), and exactly zero fixed-site motion. Maximum
interaction-energy change from frozen predictions is 1.832e-10 kcal/mol.
Evidence: `cpd-water-minima-refinement-v1` and
`cpd-water-force-refinement-v1`. This resolves numerical convergence, not
water-interaction accuracy; no parameters or thresholds changed.

`compare_water_training.py` compares the four completed, provenance-audited
counterpoise MP2 targets against those stationary native-model predictions.
MM-minus-QM errors are +1.3889 (endpoint1 O4), -1.4487 (endpoint1 H3),
+0.8637 (endpoint1 O2), and -1.1272 (endpoint2 H3) kcal/mol. This is a partial
training diagnostic at 1.8 A, not a full interaction curve or validation pass.
Validation QM values remain unread. Evidence:
`cpd-native-water-training-comparison-v1/assessment.json`. Nonbonded fitting
and independent validation remain outstanding.


## Independent C6-H6 near-equilibrium curvature evidence

`scan_curvature.py` audits and snapshots the 15/17-point independent scan
assessment, then computes central energy and gradient secants at +/-0.01,
+/-0.02 and +/-0.04 A. All six near-equilibrium points at each endpoint are
complete; the two missing points in this snapshot are endpoint2 +0.10/+0.20 A.
Evidence: `cpd-independent-h6-curvature-v1/assessment.json` and its immutable
`input_assessment.json`. No refit, target exclusion or acceptance gate change.

At +/-0.01 A, QM gradient curvatures are 698.915 and 755.063 kcal/mol/A^2,
consistent with the independent original minimum Hessian. The shared-bond
178-parameter model gives 484.571 and 485.622, whereas the split-bond
180-parameter candidate gives 683.224 and 450.778. Thus the latter improves
endpoint1 but further softens endpoint2. Complete near-equilibrium energy RMS
errors are 0.1421/0.1307 kcal/mol (shared) and 0.04177/0.1521 (split); directional
gradient RMS errors are 7.3049/7.3982 and 2.5417/8.5683 kcal/mol/A, respectively.
The complete endpoint1 extended pair already shows the tradeoff: energy RMS
error 0.5223 shared versus 3.0389 split kcal/mol. These are descriptive errors,
not new acceptance criteria. Both candidates remain unaccepted; the extended
endpoint2 pair must also be retained when it completes. This evidence rules out
mode matching alone as the explanation for the deficient stretch stiffness.


## Independent stretch scan completed (17/17)

The local native Psi4 service exited successfully with all 17 outputs. The
collector and explicit assessment audit cover every target, both endpoints and
both regimes. The complete curvature snapshot is
`cpd-independent-h6-curvature-complete-v1/input_assessment.json`; the native
outputs remain in `cpd-independent-h6-scan-v1`.

Extended-stretch energy RMS errors (endpoint1/endpoint2, kcal/mol) are
0.52235/0.90153 for shared bonds and 3.03887/1.06134 for split bonds. Corresponding
directional-gradient RMS errors are 15.3519/9.7065 and 43.5685/8.4758 kcal/mol/A.
At +0.20 A, QM energies are 9.51650/10.38377 kcal/mol, while the original minimum
QM Hessian predicts 13.97456/15.09442. The stretched configurations have strong
anharmonicity even in QM; forcing one harmonic stiffness across them competes
with correct local curvature. This is not permission to discard those targets
or weaken any acceptance limits. Both current bonded candidates remain
unaccepted. Future fitting must explicitly address the target-domain/objective
conflict and demonstrate near-equilibrium mechanics, relaxed conformer/PES
transfer, and the extended challenge behavior separately. The scan itself is
fixed-nucleus, one-coordinate evidence, not a substitute for those checks.


## Training-minimum H6 equality-constraint hypothesis rejected

`curvature_fit.py` adds four equalities to the existing 180-coefficient fit:
both C6-H6 directional gradients and curvatures at the audited training minimum.
All displaced training datasets, 10x minimum-gradient weighting, ridge 1e-4,
physical bounds and validation limits remain unchanged. The independent scan
motivated this diagnostic but provided no target values to the solve. The first
attempt preserved a pre-solve warm-start mapping failure; v2 solved successfully
in 459 iterations with normalized constraint violation 2.69e-16 and physical
directional residuals below 3.1e-13. An independent directional audit reproduces
both target curvatures, 698.7372/754.7254 kcal/mol/A^2.

This candidate is rejected. Relaxation distorted the ring despite satisfying
those local constraints. The stationary-force refinement confirms a true local
minimum (maximum gradient 1.26e-9 kcal/mol/A), but maximum bond error is
0.13513790 A for 1:C5-1:C6, versus the unchanged 0.03 A limit. All four stereo
signs survive; that does not rescue the geometry. Evidence:
`cpd-drude-h6-constrained-minimum-v2/hypothesis_assessment.json` and
`cpd-drude-h6-constrained-stationary-v1/assessment.json`. This rules out isolated
H6 training-minimum constraints as a sufficient repair of the present objective;
coupled ring geometry and local stiffness must be addressed together.


## Joint reference-gradient feasibility diagnostic

`minimum_feasibility.py` checks whether the existing 180-coefficient basis can
satisfy the full projected training-minimum gradient and both H6 curvatures.
The joint 110-row system has rank 92 at a relative cutoff of 1e-10, with a
nonzero normalized left-null target residual (0.00490506); its independent-row
bounded linear program is also infeasible. More decisively, the gradient-only
unbounded least-squares lower bound has rank 90 and projected mass-weighted RMS
residual 0.519735 at every tested cutoff (1e-8, 1e-10, 1e-12). After mapping the
projected residual back by sqrt(mass), its maximum Cartesian component is
2.60696 kcal/mol/A. Largest atom norms: 1:HCM2 3.19173, 2:HCM3 2.49379,
1:HCM3 2.20256, 2:HCM2 1.84252 kcal/mol/A, followed by methyl hydrogens.

Evidence: `cpd-drude-minimum-joint-feasibility-v2/assessment.json` with source
snapshot; v1 is retained. This proves exact reference stationarity is outside
the current basis, even without bounds. It does not prove that every acceptable
approximate force field is impossible, or identify a specific missing term by
itself. Cap/methyl torsional and shared hydrogen terms require inspection before
further global weight adjustments; cap-only improvements cannot establish sugar
transfer. No coefficients were accepted or release limits changed.


## Methyl-motion decomposition of the irreducible reference residual

`methyl_basis_audit.py` resolves the unbounded minimum-gradient least-squares
residual along each C-H bond and along rigid rotations of all three hydrogens
about N1-CM or C5-C7. Every one of the four methyl rotations already couples to
two fitted torsion groups. Residual rotational derivatives are only -0.00520,
+0.00391, +0.00473 and +0.01033 kcal/mol/radian (endpoint1 CM/C7, endpoint2 CM/C7).
Larger residuals remain in individual stretch and bending components: endpoint1
CM radial components reach +2.769/-2.027 kcal/mol/A; endpoint2 CM transverse
norms reach 2.447 kcal/mol/A. Evidence:
`cpd-drude-methyl-basis-audit-v1/assessment.json`.

Thus missing collective methyl torsions are not established as the cause. The
current equivalent-hydrogen bond/angle sharing and fixed response require joint
review; no inequivalent hydrogen types were introduced just to reproduce one
reference geometry. Exact stationarity at that QM reference remains an
unattainable constraint for this basis, but this alone does not rule out an
acceptable nearby MM minimum. Previously acceptable bond geometry and deficient
H6 stiffness must both be considered, along with new conformer/PES validation.


## Relaxed ring-torsion pilot launched locally

`cpd-relaxed-ring-pilot-v1/plan.json` freezes two independent constrained
optimizations at +/-5 degrees from the audited cyclobutane-ring torsion
1:C5-1:C6-2:C5-2:C6 (reference 24.94572538 degrees). Both start at the same
audited reference; all other coordinates relax. These are fresh conformational
diagnostics, not a comprehensive torsional PES or replacement for old targets.
The worker uses frozen-core DF-MP2/6-31G(d), RHF, tight SCF and GAU_TIGHT geometry
convergence, a +/-0.0001-degree range constraint and a 40-step per-case limit.
The installed OptKing 0.5.0 convention matches the repository dihedral within
1e-6 degree, and option validation passed before launch. Native output showed
SCF iterations after launch. No energies or geometries are accepted until
optimizer completion, constraint, topology/stereochemistry and geometry audits.

Service `nadoc-cpd-relaxed-ring-pilot-v1.service` uses 4 CPU threads, 4 GiB Psi4
memory, 6 GiB cgroup memory, no swap and a three-hour limit. Root and scratch
remain on Archive. `relaxed_ring_worker.py` and the plan are hash-linked;
preexisting case directories cause failure rather than overwriting output.
No additional RunPod resources were allocated for this pilot. Documentation:
https://psicode.org/psi4manual/master/optking.html and installed OptKing source.


## Fresh electrostatic validation completed: all 24 checks pass

The native local service exited successfully after all 24 previously uncomputed
external-charge perturbations. `seal_fresh_esp.py` verified frozen plan/input/grid
hashes, all case output/ESP hashes and native success markers, unchanged parameter
and evaluator hashes, complete case identities, and recomputed aggregate metrics
and Boolean decisions from the frozen limits. Evidence:
`cpd-fresh-esp-validation-v1/assessment.json` and `sealed_evidence.json`.

| Fresh response metric | Result | Frozen limit |
|---|---:|---:|
| ESP-response relative RMS | 0.1776401 | 0.35 |
| Dipole-response relative RMS | 0.1612433 | 0.25 |
| Fresh/training ESP-error ratio | 1.0726937 | 1.5 |
| Maximum Drude displacement | 0.1721776 A | 0.20 A |

The corrected anti electrostatics now pass genuinely new perturbation positions
on the reference capped-fragment geometry, in addition to the historical response
regression and corrected NAMD/OpenMM engine checks. This does not validate new
conformations, water LJ, sugar attachment, bonded mechanics, full nucleotide or
DNA solution behavior. No production gate changed. The relaxed ring pilot
remains active; its output audit is still pending.


## Relaxed-ring completion audit prepared

`audit_relaxed_ring.py` verifies plan/worker hashes and native Psi4 final-geometry
completion evidence, recomputes the constrained torsion independently, checks
all four stereocenter signs, and records every registered bond's length/change
from the reference. Bond changes are reported, not silently interpreted as a
new release criterion or as proof of bond order. Missing cases yield an
explicit incomplete audit. Three focused tests passed, including a mirrored
geometry that meets its torsion constraint but fails stereochemistry and a
nonfinite-coordinate rejection.

Collector `nadoc-cpd-relaxed-ring-audit-v1.service` polls the exact pilot service,
preserves its terminal state and invokes the audit on success or failure. It
has a 512 MiB memory cap and 11000-second timeout. No pilot restart or output
overwrite is performed. Both cases remained incomplete at initial audit.


## Separate canonical cis-syn additive track: minimum audit

The archived `charmm36-hybrid-v1/candidate-v3` syn candidate completed topology,
NAMD load, minimization and 2 fs smoke checks in September 5 evidence, but that
is not an independent physics release. Its 156-parameter ridge candidate was
selected using archived validation scores; those datasets cannot be described
as untouched final holdouts. Anti Drude validation does not apply to this model.

`syn_minimum.py` now hash-verifies the archived selected fit, basis and minimum
response sources and minimizes the complete 36-nucleus additive OpenMM system.
The 38-bond inventory has the correct syn C5-C5/C6-C6 crosslinks. A stationary
force solve in 102 internal coordinates reaches maximum Cartesian force
1.43e-12 kcal/mol/A. The solver itself reports stagnation rather than success;
the independently evaluated force and two-step Hessian, not that status flag,
provide numerical evidence. Both Hessians have minimum internal curvature
2.74403 kcal/mol/A^2 and step-halving relative difference 7.03e-10. All four
stereocenter signs remain unchanged.

Largest bond error versus its QM reference is 0.03219282 A at 1:C2-1:N3
(QM 1.40535581, MM 1.37316299 A). No anti threshold was transplanted into a syn
release decision and no scientific acceptance is claimed. Fresh conformer/PES,
nonbonded, nucleotide and explicit-solvent validation remain required.
Evidence: `cpd-canonical-syn-minimum-audit-v2/assessment.json`; v1 preserves the
initial energy-minimizer result. No archived parameters or release flags changed.


## Frozen relaxed-MM ring predictions

`predict_relaxed_ring.py` uses both existing frozen 178/180-coefficient anti
candidates at the ring pilot's reference, -5 and +5 degree constraints. Each
starts from the same audited QM reference geometry; no QM scan outputs are
read. All other internal coordinates relax on the adiabatic Drude potential.
The original six trust-constr optimizations matched their torsions but stopped
by step tolerance with Lagrangian-gradient residuals above 1e-5. They remain
marked unverified in `cpd-relaxed-ring-mm-v1`; optimizer success is not accepted
as force convergence. The source snapshot preserves the exact executed code.

A second isolated run, `cpd-relaxed-ring-mm-v2`, adds a constrained stationary
(KKT) force root solve after minimization, preserving the force tolerance.
Service `nadoc-cpd-relaxed-ring-mm-v2.service` has 2 CPU threads, 2 GiB memory,
no swap and a one-hour cap. Results require direct force/constraint checks and
constrained-curvature/chirality review before comparison; these are local
stationary candidates, not demonstrated global minima or validated parameters.
No candidate is refitted or selected from the new scan.


## Relaxed-MM ring predictions numerically verified; fifth water target audited

All six frozen constrained MM structures pass direct force/constraint checks,
positive tangent-space curvature, and all four stereocenter checks.
`audit_ring_mm.py` removes six rigid modes and the torsion normal, evaluates the
101-dimensional Hessian of E + lambda*theta, and halves the finite-difference
step from 1e-4 to 5e-5 A. Its minimum curvature across the six structures is
0.9473003 kcal/mol/A^2; largest relative step-halving difference is 1.85e-9.
The analytic torsion derivative comes from a separate OpenMM theta-only force
whose angle is checked against the repository convention. This demonstrates
local constrained minima, not global minima or agreement with QM.
Evidence: `cpd-relaxed-ring-mm-curvature-v1/assessment.json`. New ring QM outputs
remain unread while the first constrained optimization continues.

The fifth cloud training case, endpoint2 O2, passed execution/provenance and
counterpoise arithmetic audits. Native-model interaction -2.85076490 versus
QM -3.52775791 kcal/mol gives +0.67699302 kcal/mol error. The five-case training
RMS error is 1.14040991 kcal/mol. Versioned execution audit
`cpd-drude-cloud-budget5-v1/training_execution_audit_5cases.json` and comparison
`cpd-native-water-training-comparison-v2/assessment.json` preserve the earlier
four-case audit. No validation QM values were read and no LJ parameters changed.


## Water LJ identifiability: single-separation batch is insufficiently conditioned

`water_identifiability.py` evaluates analytic local sensitivities to log epsilon
and log Rmin using only the six frozen training geometries and native LJ pairs;
it reads no QM energies. All other parameters remain fixed. The four-variable
scheme sharing O2/O4 carbonyl interactions plus H3 is full rank, but its
column-normalized condition number is 4124.28. Separating O2, O4 and H3 into six
variables remains nominally full rank with condition number 8.0173e6. Finite
differences agree with analytic derivatives to 1.85e-7 kcal/mol per log parameter.
Evidence: `cpd-water-lj-identifiability-v1/assessment.json` includes singular
values, weak directions and pair distances.

This is not evidence for fitting six parameters to six energies. Both schemes
have poorly determined directions; the current single-contact-separation batch
cannot establish preferred distances or curve shapes. Radial target coverage
is required before claiming a well-determined nonbonded fit. No parameter was
changed, no new QM job was launched, and existing validation cases remain sealed.


## Prospective radial water design and local basis-cost pilot

`design_water_radial.py` freezes contact distances 1.6, 1.8, 2.2 and 2.6 A
for each of six canonical training orientations. Only rigid water translation
along the original contact axis changes; CPD coordinates, water internal
geometry and orientation are verified unchanged. The 1.8 A geometries reproduce
existing targets. No validation energies are read. Adding only the six 2.2 A
points improves column-normalized LJ sensitivity conditioning from 4124 to
25.92 (shared carbonyl) and from 8.017e6 to 26.05 (separate carbonyl). The full
24-geometry design gives 44.86/45.12. These local design metrics are not
force-field acceptance. Eighteen additional QM points are planned geometries,
not submitted jobs. Evidence: `cpd-water-radial-design-v1/plan.json`.

To evaluate a possible local resource route without assuming basis equivalence,
a single canonical endpoint1 O4 calculation is running at frozen-core
DF-MP2/cc-pVTZ with explicit counterpoise, against the completed cc-pVQZ result
at identical coordinates. `cpd-water-triple-zeta-pilot-v1/batch.json` explicitly
labels the changed basis and hashes both reference and worker. It is not a
replacement cc-pVQZ target or permission to merge methods. The local service
`nadoc-cpd-water-triple-zeta-pilot-v1.service` has 8 threads, 8 GiB Psi4 memory,
12 GiB cgroup cap, no swap and a one-hour deadline. Native output started.
No additional cloud resources were allocated. A one-site basis comparison
alone cannot validate a whole lower-basis radial campaign.


## Radial model-domain check completed

`predict_radial_water.py` evaluates all 24 proposed radial geometries with the
unchanged corrected electrostatics and native LJ. Stationary Drude forces are
solved and Hessians checked at two finite-difference steps. All 24 pass the
original force/displacement checks with positive Drude curvature: maximum
displacement 0.1733461 A, maximum force 1.61e-12 kcal/mol/A, minimum curvature
194.3783 kcal/mol/A^2. Fixed sites do not move. The original six 1.8 A energies
reproduce to 1.42e-10 kcal/mol. No QM targets were read or fitted.
Evidence: `cpd-water-radial-predictions-v1/assessment.json`. Numerical usability
is not a claim of QM accuracy or an authorization to exceed the cloud budget.

The water execution auditor now supports an explicit cc-pVTZ mode for the
separate local pilot (882 orbital functions in each full ghost-basis component),
while its default cloud audit still requires cc-pVQZ/1695. A new regression test
rejects treating triple-zeta output as quadruple-zeta or mixing basis sizes.
All seven focused execution-audit tests passed. This separates method identity;
it does not establish basis convergence.


## Full-nucleotide seed re-audit: sugar inversion invalidation

`audit_boundary_seeds.py` rechecks both archived UFF-screened cis-anti-I d(TpT)
seeds, including strict source hashes and relocations of old temporary paths,
the expected anti graph derived independently from the source dinucleotide,
formal charge, all four lesion stereocenters and all six sugar stereocenters.
Run with the nadoc-qm Python environment (RDKit is absent from repository .venv).
Both have 63 atoms, 68 expected bonds and charge -1, with lesion signs preserved.
**Neither preserves sugar stereochemistry.** Chain B inverts 1:C3', 2:C1',
2:C3' and 2:C4'; chain D inverts 2:C4'. Signs are measured from the same ordered
neighbor identities in the source and final coordinates, not inferred from
stale SDF stereo tags or a product label.

Evidence: `cpd-anti-boundary-seed-reaudit-v1/assessment.json` and
`input_invalidation.json`. These supersede the narrower archived input-screen
claim; source files are retained unchanged. Neither seed was launched for QM.
The nucleotide path must repair the boundary relaxation's missing sugar-chirality
protection and re-audit new isolated seeds before full-nucleotide QM. Matching
lesion chirality and bond counts alone cannot validate nucleotide chemistry.
The source context is covalently linked d(TpT), not an interstrand weld model.


## Local water basis pilot completed; isolated sugar repair launched

The one-site cc-pVTZ counterpoise calculation completed in 261.4 seconds and
passed the explicit triple-zeta execution/CP arithmetic audit. Interaction energy
is -2.85157868 kcal/mol versus cc-pVQZ -3.40681830, a +0.55523961 kcal/mol basis
difference. This is too substantial to silently substitute methods or merge
curves. Evidence: `cpd-water-triple-zeta-pilot-v1/basis_assessment.json`. Local
cost is promising, but basis equivalence is not established; no cheaper-basis
fit or radial campaign was accepted.

Inspection of `photoproduct_models.py` confirms the archived UFF relaxation
fixed 28 lesion nuclei and audited lesion chirality, with no source-sugar
handedness constraint. `repair_boundary_seed.py` tests a repair only in an
isolated experiment. Starting from the preserved chain-D rigid graft, it fixes
the same lesion core and constrains all six source-sugar signed tetrahedral
volumes to remain at least half their source magnitudes with the source signs.
This inequality is an experimental seed-construction constraint, not a new
physical acceptance limit. UFF and constraint directional derivatives are
finite-difference checked before optimization. It uses two CPU threads, a
2 GiB memory cap and one-hour limit in
`nadoc-cpd-boundary-chirality-repair-v1.service`; output root
`cpd-anti-boundary-chirality-repair-v1`. No backend or production geometry was
changed. Full bond/clash and independent stereochemical audits remain required
before any candidate could be used as a QM starting point.


The first sugar-repair solve has now terminated at its 3000-iteration limit.
It satisfies all six handedness inequalities with zero fixed-core motion, but
its Lagrangian-gradient maximum is 17.6855 kcal/mol/A: **not converged and not
an accepted seed**. UFF also emits its unrecognized phosphorus charge-state
warning for atom 17; this must remain visible in seed-method assessment rather
than being treated as force-field authority. Source, final coordinates and
failed result are retained for diagnostic continuation.


## Isolated chirality-preserving nucleotide seed passes structural screen

The feasible v1 boundary iterate was continued with SLSQP in a separate v2
output root, preserving the fixed lesion core, reference atom identities and all
six source-sugar handedness inequalities. It converged in 174 iterations with
zero primal/dual constraint violation and maximum Lagrangian-gradient component
5.00e-5 kcal/mol/A, below the original UFF force tolerance of 1e-4. Energy fell
from 572.666 to 478.473 kcal/mol; UFF energies are not physical parameter targets.

`audit_repaired_boundary.py` independently verifies the exact graph AND bond
orders against the anti chemical definition, charge -1, all six sugar and four
lesion stereocenters, unchanged core coordinates, original catastrophic-input
bond ranges and nonbonded clash bounds. All checks pass. Glycosidic distances
are 1.60585688/1.52962169 A; minimum nonbonded covalent-radius ratio is 1.73690.
Evidence: `cpd-anti-boundary-chirality-repair-v2/independent_structural_audit.json`.
The source phosphorus-typing warning remains a declared UFF limitation.

This is a newly screened, isolated 63-atom anti d(TpT) QM starting geometry,
not validated electrostatics, sugar/backbone parameters, a full QM minimum,
DNA dynamics, or an interstrand seed. The two archived inverted seeds remain
invalidated; no production geometry, backend constructor or registry changed.
Next use requires an explicit, hash-frozen nucleotide QM method/resource plan
and post-QM stereochemical/geometry audit, including all sugar centers.


## Anti 49-atom boundary QM evidence also inherited wrong sugars

Before duplicating full-nucleotide QM, the archived completed neutral 49-atom
endpoint geometries and collected frequency cohort were located. Their additive
campaign uses the same MP2 bonded method, so raw QM could have been reusable
for Drude transfer, subject to identity. `audit_fragment_sugars.py` checked
both syn and anti primary endpoints against the original source dinucleotide's
ordered sugar-neighbor coordinates, not merely their immediate starting seeds.
Both syn endpoints preserve all three retained sugar stereocenters. **Both anti
endpoints fail:** endpoint1 inverts C3'; endpoint2 inverts C1', C3', and C4'.
These are precisely the inherited chain-B UFF inversions and survive optimization.

Evidence: `cpd-primary-fragment-sugar-reaudit-v1/assessment.json` and
`input_invalidation.json`. Archived passing identity/continuity and frequency
results do not validate native deoxyribose if the starting stereoisomer was wrong.
Those anti geometries and their matching Hessians must not be used for native
sugar fitting/transfer; raw evidence remains unchanged. New anti 49-atom fragments
should be derived from the independently screened chirality-preserving seed,
with both sugar and lesion checks before and after optimization. This avoids
unnecessary full-63-atom QM while retaining the full nucleotide/DNA validation
requirement. No new nucleotide QM was launched before this audit.


## Progress check 2026-09-16 20:49 UTC

The local relaxed-ring QM pilot terminated at the unchanged 40-iteration limit
without convergence on ring_minus5; ring_plus5 was not started. Its terminal
service receipt and geometry audit report zero accepted cases. Preserve the
failed trajectory for optimizer diagnosis; no torsional validation follows.
The owned RunPod is provider-confirmed RUNNING with 5/12 results downloaded;
estimated accrued spend including disk reserve and the prior short-lived pod
is $2.304. The exact-pod watchdog remains active with the existing 21:55:40 UTC
deadline. Fresh electrostatic response remains 24/24 passed, while anti sugar
QM replacement, bonded and water validation, and nucleotide/DNA checks remain
outstanding. Snapshot: cpd-drude-anti-graph-recovery-v1/progress_check_20260916T2049Z.json.


## Replacement anti sugar-fragment QM launched

`prepare_repaired_fragments.py` materialized the independently screened repaired
63-atom boundary in `cpd-repaired-anti-fragments-v1`, with fresh manifests and
hash-linked provenance. Both neutral 49-atom endpoint fragments preserve all
three native-source sugar centers and all four lesion centers. All 46 retained
coordinates exactly match the serialized repaired source; SDF rounding is
explicitly recorded. No invalidated archived sugar QM is reused.

`nadoc-cpd-repaired-fragments-v1.service` was confirmed active, PID 1080380,
with native Psi4 integral setup underway for endpoint 1. Sequential endpoint
optimizations use frozen-core DF-MP2/6-31G(d), RHF, GAU_TIGHT, step limits
0.1/0.25 and 300 maximum iterations. The immutable worker/plan limits local
resources to four threads, 4 GiB Psi4 memory, 6 GiB cgroup memory, no swap, and
six hours total. Raw bonded QM only: additive electrostatic or water conventions
are not transferred to Drude. Sugar signs are checked after optimization; native
convergence, independent lesion/graph audits and minimum Hessians remain required.
Both new experiment scripts passed Ruff. Production gates remain closed.


## Fixed-torsion continuation of the failed ring pilot

The v1 native terminal output shows the minus5 torsion at 19.94582527 degrees,
inside the original range, but force convergence remains poor (~0.0028 au).
Installed OptKing source applies a force-direction-dependent active set near
ranged-coordinate boundaries. This suggests, but does not establish, an active
constraint oscillation. No completed QM value is inferred from the failure.

`prepare_ring_continuation.py` parses the terminal geometry, projects it onto
the exact unchanged target 19.94572538 degrees (maximum Cartesian correction
5.883e-7 A), verifies all four lesion centers, and prepares an isolated frozen
dihedral continuation. Native GAU_TIGHT criteria are unchanged; only the range
constraint is replaced by an exact frozen coordinate, with 80 maximum steps
and conservative 0.1/0.25 intrafragment step limits. The failed run is preserved.
`nadoc-cpd-relaxed-ring-fixed-v2.service` is verified active, PID1082828, native
SCF underway, four threads/4 GiB Psi4/6 GiB cgroup/no swap/three-hour deadline.
Its plan and script are immutable snapshots in `cpd-relaxed-ring-fixed-v2`.
Only minus5 is included; plus5 remains outstanding. The automatic geometry
audit compares bond changes against the continuation start; the separate
starting_geometry_audit.json compares against the original QM reference.
The local repaired sugar-fragment job PID1080380 is also confirmed active.


## Independent replacement-fragment QM audit prepared

`audit_repaired_fragment_qm.py` verifies hash-linked inputs, native MP2 geometry
optimization completion, element order and agreement of native/result/XYZ
coordinates, all native-source sugar and product lesion centers, neutral charge,
and broad existing covalent-radius/contact limits. It explicitly does not certify
a positive Hessian, electronic bond orders, force-field transfer or DNA readiness.
Initial execution correctly records both unfinished endpoints as missing.
`test_cpd_fragment_sugar_audit.py`: 3 passed via guarded test-file; rotation,
inherited mirror and planar/nonfinite rejection covered. Ruff passed the audit.
A terminal-service collector runs the independent audit after the exact fragment
service exits; missing/failed runs cannot become successful merely by timing out.
At 20:56 UTC both local QM handles remain active. Provider confirms the owned
RunPod RUNNING, 5/12 results and estimated spend $2.358; original shutdown and
$5 total authorization unchanged.


## Nucleotide bonded-term graph coverage

`nucleotide_term_coverage.py` independently enumerates bonds, angles and proper
torsions from the repaired 63-atom anti graph and the audited native Drude
precursor, normalizing explicit atom names (including O1P/O2P to OP1/OP2).
The complete product contains 68 bonds, 132 angles and 216 proper torsions.
The anti crosslinks add 2, 12 and 42 terms respectively. Every graph term
touching a modified base occurs in at least one repaired 49-atom fragment;
cap-generated atoms are excluded from coverage. This supports the fragment
strategy without substituting it for full-nucleotide validation.
Evidence: `cpd-anti-nucleotide-term-coverage-v2/assessment.json`; v1 records the
initial phosphate-name mismatch and produced no coverage claim. Three focused
tests pass (four-member ring, branched graph, reversal invariance); Ruff passes.
This inventory does not validate coefficients, impropers, Drude screening,
anisotropy, nonbonded exclusions or electrostatic transfer. Both local QM handles
remain active. Fixed-ring iteration 3 has maximum force 0.00109 au and is not
converged; no terminal result or successful QM audit is claimed.


## Planar-improper stiffness freedom does not remove the minimum force residual

A new training-only span diagnostic adds six independent stiffness-response
columns for the inherited C2/C4/N1 planar impropers (both endpoints), preserving
zero planar equilibria. `cpd-planarity-span-diagnostic-v1/assessment.json` shows
the gradient rank stays 90 and the best unbounded mass-weighted residual RMS
stays 0.5197346991 at all three SVD cutoffs 1e-8/1e-10/1e-12. Maximum Cartesian
residual remains 2.60696 kcal/mol/A. Thus simply freeing those six stiffnesses
cannot eliminate the existing equilibrium-force incompatibility. No full
refit or extra QM was launched for this hypothesis; Hessian improvements from
those terms are not ruled out by this gradient-only result. Ruff passes.

A separate current-180-fit directional audit is saved in
`cpd-drude-h6-equilibrium-v1/directional_audit.json`: endpoint2 H6 curvature
450.778 versus QM754.725 kcal/mol/A^2 remains the large local deficiency.
N1-normal curvatures are 318.011/284.517 versus QM339.391/229.488.
Local jobs remain active: fixed-ring iteration5 max force3.19e-4 au (not
converged); repaired sugar endpoint1 iteration2 max force0.036 au.


## Full nuclear bonded NAMD/OpenMM comparison passes

`bonded_engine_probe.py` exports the frozen 178-parameter candidate nuclear
potential to isolated CHARMM parameters and a unique-type PSF. The actual
NAMD CPU build and OpenMM Reference evaluate identical binary coordinates at
the candidate minimum and four deterministic 0.015-A random displacements.
The known completion-of-square/Fourier energy constants are accounted for.
All five cases pass predeclared 0.001 kcal/mol energy and 0.0001 kcal/mol/A
maximum-force tolerances: maxima 5.1674e-5 and 7.6495e-5 respectively.
`cpd-bonded-native-engine-v1/sealed_evidence.json` hash-links native logs,
force files, coordinates, parameters, policy and original executed source;
all native ELECT/VDW/BOUNDARY/MISC/KINETIC components are verified zero.
Ruff passes. This validates all candidate bonded terms including planar and
chiral impropers, but not combined Drude/nonbonded dynamics, QM accuracy,
full nucleotide or DNA. The candidate remains scientifically unaccepted.

The sixth cloud training water target has now arrived; all six native execution
and counterpoise audits pass in training_execution_audit_6cases.json.
Validation target values remain unread. The frozen native-LJ comparison is
saved in cpd-native-water-training-comparison-v3/assessment.json.
Six-case training energy RMSE is 1.313798382 kcal/mol; no nonbonded fit or acceptance follows.


## Training-only fixed-radius water depth hypotheses frozen

`water_depth_feasibility.py` solves exact nonnegative linear least squares for
CPD-water pair epsilon scales at unchanged native pair radii and corrected
electrostatics. Both declared schemes use all six training energies, without
ridge, target scaling, validation reads, or release selection. Native RMSE
1.313798 falls to 0.420519 kcal/mol for shared carbonyl/H3 (scales
0.720378/7.580387), and 0.197526 for separate O2/O4/H3 (scales
0.824178/0.616495/7.562306). KKT checks pass. These are pair-specific depth
hypotheses, not solute atomic-epsilon changes: the O-water pairs already use
native NBFIX, and changing solute atomic epsilon would affect other contexts.
The large H3-water correction and missing radial targets prevent physical
acceptance; no radius/well-depth identifiability issue is declared solved.

`freeze_water_depth_predictions.py` freezes both complete 12-case prediction
sets before validation QM reads, analytically reconstructs all six training
values to <1e-10 kcal/mol, and retains all native radii and frozen electrostatic
parameters. Later validation ranking cannot select a release model. Evidence:
`cpd-water-depth-feasibility-v1` and `cpd-water-depth-predictions-v1`. Both scripts
pass Ruff. No extra compute or cloud budget was consumed by these diagnostics.


## Drude electrostatic nuclear-force agreement passes nine native probes

`drude_nuclear_force_probe.py` extends the former fixed-nuclear response check
to nuclear forces, with OpenMM local-coordinate virtual lone pairs and the
full anisotropic Drude force. Native dummy bonds are retained identically in
both engines, isolating the electrostatic implementation without subtracting
forces approximately. All nine cases pass predeclared 0.001 kcal/mol/A maximum
nuclear/Drude force and 0.001 kcal/mol energy diagnostic tolerances. Maximum
nuclear force discrepancy is 0.00024555; maximum Drude force discrepancy is
0.00023991 kcal/mol/A; energy discrepancy is 0.00021351 kcal/mol.

Evidence: `cpd-drude-nuclear-force-probe-v3`, including native binary forces,
logs, hashed input coordinates and artifact inventory. v1 stopped before native
execution on an overly tight LP coordinate preflight (2.92e-8 A discrepancy);
v2 stopped at NAMD's Drude requirement for rigidBonds water. Both failures are
preserved. v3 reports LP reconstruction precision directly and uses rigidBonds
water in the water-free probe; original force/energy tolerances are unchanged.
Ruff passes. This supports electrostatic force redistribution but is not
combined candidate bonded/LJ dynamics, nucleotide transfer or DNA validation.


## Assembled capped Drude/LJ/bonded candidate native engine comparison passes

`combined_engine_probe.py` assembles the complete 178-parameter capped candidate
with the audited corrected Drude graph, virtual lone pairs, anisotropy, native
intramolecular LJ and special 1-4 LJ, and all candidate bonded terms. It
compares native NAMD against the summed OpenMM bonded and adiabatic nonbonded
energies/forces at five identical geometries, with stationary Drudes.

The first assembled export failed by ~60 kcal/mol and ~116 kcal/mol/A: its
explicit Drude spring incorrectly used 1000 as a CHARMM bond coefficient. The
native master parameter is 500; NAMD's drudebondconst=1000 uses a different
convention. LJ energy independently matched (4.16947097 kcal/mol). The exporter
now reads the 500 coefficient directly from the native parameter set. v1
failed calculations and v2 canonical-key preparation failure remain preserved.

All five corrected v3 probes pass unchanged 0.001 kcal/mol energy and
0.001 kcal/mol/A maximum-force tolerances. Maxima are 0.00011325 kcal/mol and
0.00031655 kcal/mol/A. Drude displacements stay <=0.15372 A and the OpenMM
stationary Drude force <=6.74e-13 kcal/mol/A. Evidence and artifact hashes:
`cpd-combined-native-engine-v3`; Ruff passes. This verifies the assembled
capped Hamiltonian implementation, not its QM accuracy, full nucleotide
transfer, numerical integration or DNA solution behavior. No production
parameters or gates changed.


## Short thermal trajectories expose a polarization-domain failure

The force-probe PSF used dummy nuclear masses; it was never suitable for MD.
`prepare_capped_dynamics.py` makes an isolated 64-particle model with physical
nuclear masses minus 0.4-Da Drudes, zero-mass LPs, exact total nuclear mass,
unchanged charge/bonded graph, and the unused zero-charge probe particle removed.
Four 5-ps native vacuum trajectories (0.25/0.5 fs, seeds137/281, 300 K warm/1 K
Drude dual Langevin; 5/20 per ps damping) completed. All 3000 saved frames
retain lesion stereochemistry, but all four runs exceed the unchanged 0.20-A
Drude domain. Maxima: 0.24778/0.22279/0.22988/0.21223 A. The principal failing
site is endpoint2 C2; one endpoint1 C2 frame also exceeds. Last-half reported
cold temperatures are 2.17-2.53 K. This is **not a dynamics pass**. No hard-wall
tightening or threshold relaxation was applied (wall remains0.25 A).

Re-minimizing Drudes at each trajectory's worst endpoint2-C2 nuclear frame
shows stationary displacements 0.20961/0.19680/0.20902/0.18511 A, with residual
forces <=8.27e-13 kcal/mol/A. Two remain out of domain even after removing
transient Drude heating, so timestep reduction alone cannot establish validity.
Stationary points have not yet received Hessian certification. Evidence:
`cpd-capped-dynamics-v1` and `cpd-thermal-adiabatic-check-v1`. All three experiment
scripts pass Ruff; no production change. Source method reference:
https://www.ks.uiuc.edu/Research/namd/cvs/ug/node27.html .

The fixed-ring optimizer holds its target angle within ~3e-9 degrees across
28 native geometries; constraint drift is excluded as the reason for its
nonmonotonic convergence. Both QM jobs remain live; no result is accepted yet.


## Independent DFT on the thermal polarization-domain failure

`prepare_thermal_qm.py` selects the largest observed endpoint2-C2 excursion
(dt0.25 seed137 frame325), restores the physical nuclear mapping, verifies
lesion chirality and re-minimizes induced coordinates. The stationary point
has positive Drude Hessians at both finite-difference steps; minimum curvature
149.92938 kcal/mol/A^2. Thus the 0.2096075-A displacement is a stable local
polarization minimum outside the unchanged0.20-A domain, not just a transient
cold-particle excursion. Nuclear stationary/minimum status is not claimed.

Model ESP on a newly generated 1041-point Bondi grid and model dipole
(-1.02940211,-1.01606268,-0.03951269) au are frozen before running independent
B3LYP/aug-cc-pVDZ at this exact thermal geometry. No optimization or parameter
change. `nadoc-cpd-thermal-conformer-qm-v1.service` runs locally with four
threads,4GB Psi4 memory,6GiB cgroup,no swap,one-hour deadline. Terminal collector
compares static ESP/dipole only after native completion/provenance checks.
Evidence: `cpd-thermal-conformer-qm-v1`; preparation Ruff passes.
This is a conformer-transfer diagnostic and cannot erase the existing domain
failure, certify response, or justify production DNA simulation.


## Thermal failure geometry and local resource adjustment

`thermal_geometry_diagnostic.py` finds a consistent negative correlation between
endpoint2-C2 Drude displacement and C2-O2 bond length (r=-0.575 to-0.608) in
all four short trajectories. Worst-frame C2-O2 lengths are1.174-1.202 A versus
QM1.22678 A. C2-N1/N3 compression also correlates; correlations are descriptive,
not causal proof. `cpd-thermal-geometry-diagnostic-v1` retains all features.
The training-minimum fixed-environment COM-preserving curvature diagnostic
`cpd-c2-compression-curvature-v1` shows endpoint2 C2-O2 model/QM ratio0.92650,
C2-N1 ratio0.72398, C2-N3 ratio0.99199. No empirical stiffness change is justified
solely by these values; compressed-geometry electrostatics/QM remain needed.

The live thermal-conformer DFT job hit exactly6GiB cgroup MemoryPeak during
SCF setup. Its MemoryMax was raised to8GiB with available workstation headroom;
Psi4 internal4GB,4threads and the original1hour deadline stay unchanged.
`runtime_memory_adjustment.json` records the exact live PID/property change;
no job restart or scientific input change. Geometry diagnostic Ruff passes.


## Equilibrium-gradient AND Hessian weighting diagnostic

`bonded_training_energy_audit.py` confirms training conformer001/004 are
93.75463/79.29232 kcal/mol above the portable MP2 reference. All targets remain
retained; these are point energies, not conformer populations. The normalized
minimum-only joint derivative design has numerical rank180 at1e-8 cutoff.
One prospective178-parameter fit now weights BOTH minimum derivative blocks
10x with unchanged ridge1e-4, physical bounds, old displaced targets, partitions
and acceptance limits. `equilibrium_fit.py --minimum-hessian-multiplier 10`
records the explicit new option (default1 preserves the former algorithm).
No weight search or release selection was performed.

`cpd-drude-equilibrium-both-blocks-v1` converged in416 iterations, constraint
violation8.9e-16. Geometry minimization stalled at force3.65e-5 kcal/mol/A;
a separate tiny Newton correction then verified stationarity5.22e-9 and
positive102-direction nuclear curvature2.12885, with Hessian step-halving
error8.6e-10. Max bond error0.0137284 A passes unchanged0.03-A limit.
`cpd-drude-equilibrium-both-modes-v1`: overlap-matched frequency RMSE94.5173
cm^-1 (formerly~169), sorted RMSE74.1458, median squared overlap0.37288, max
angle error3.58405 degrees. Better local mechanics, not a force-field release;
independent scans, polarization transfer and full nucleotide/DNA remain open.

The thermal-conformer B3LYP/aug-cc-pVDZ completed normally in409s. Independent
static comparison gives ESP RMS0.00433631 au (relative23.544%) and dipole-vector
error0.288717 au. QM dipole(-1.189529,-1.105796,-0.262369) au differs from
frozen model(-1.029402,-1.016063,-0.039513). This one-conformer test exposes
transfer limitations in addition to the already-failed Drude domain; it is not
a molecular-response test. Native output and collector assessment are saved in
`cpd-thermal-conformer-qm-v1`. Preparation/energy-audit/fit scripts pass Ruff.

## New bonded candidate: native export passes, thermal domain still fails

The minimum-gradient-and-Hessian-weighted 178-term candidate now has its own
native checks, rather than inheriting the older fit's engineering result.
`cpd-both-bonded-native-v1` passes all five bonded comparisons (maximum force
error8.021e-5 kcal/mol/A). `cpd-both-combined-native-v1` passes all five complete
capped Hamiltonian comparisons: maximum energy error0.00014886 kcal/mol,
maximum force error0.00029332 kcal/mol/A, unchanged0.001 limits.
Probe/preparation/audit scripts now accept explicit artifact paths; defaults
preserve the original experiments. No production assets changed.

`cpd-both-capped-dynamics-v1` repeats four5-ps native trajectories with the same
physical masses, seeds, timesteps, thermostats and0.20-A domain as before.
All3000 saved frames retain lesion stereochemistry. All four trajectories
still fail the Drude domain: maxima0.22418/0.22255/0.21082/0.22820 A.
Reported last-half cold temperatures remain2.17-2.48 K against1 K target.
The initial four worst-endpoint2-C2-frame rechecks all fall below0.20 A after
polarization minimization, but this subset is INSUFFICIENT: the subsequent
complete excursion audit finds31 offending saved frames, of which THREE
remain outside the domain at stationary Drude forces below1e-12 kcal/mol/A.
They are dt0.25/seed137/frame476:0.200071 A at2:C2;
dt0.5/seed281/frame424:0.223118 A at1:C2; and frame457:0.207920 A at2:C2.
Evidence: `cpd-both-thermal-adiabatic-v1` (limited subset) and
`cpd-both-all-excursions-v1` (every saved excursion, no subsampling).
Stationarity is verified, positive polarization Hessians are not yet checked
for these new frames. Better bonded mechanics does not remove polarization
transfer failure. A smaller timestep alone cannot establish acceptance.

The previously exposed H6 scans were also rechecked without changing targets:
`cpd-equilibrium-both-h6-recheck-v1`. Near-equilibrium energy RMSE is
0.10081/0.09567 kcal/mol for endpoints1/2; extended-challenge RMSE is
1.83543/0.63086. These are retrospective diagnostics, not fresh holdouts.
All six modified/new diagnostic scripts pass Ruff. The two local MP2 workers
remain live, and the owned cloud pod retains its original deadline and guards.

## Second thermal-conformer QM test and complete old/new excursion audit

Applying the same complete saved-excursion audit to the old bonded candidate
finds26 dynamic excursions among3000 saved frames,10 of which remain outside
0.20 A after Drude minimization (`cpd-original-all-excursions-v1`). The new
candidate has31/3000 dynamic excursions but3 stationary failures. These short,
correlated trajectories do not establish a statistically significant rate
improvement or validate either model.

`prepare_thermal_qm.py` now accepts explicit root/prior paths and an
`--all-excursions` selection mode. The new test selects the greatest stationary
excursion over all offending saved frames: new candidate dt0.5/seed281/frame424,
endpoint1 C2 at0.22311848 A. Its Drude Hessian is positive at1e-4 and5e-5-A
steps, minimum eigenvalue142.66291 kcal/mol/A^2. Thus this is a stable local
polarization minimum, not merely an unverified stationary point.
`cpd-both-thermal-conformer-qm-v1` freezes predictions on1032 ESP grid points
and launches fixed-geometry B3LYP/aug-cc-pVDZ locally with4 threads,4GB Psi4,
8GiB cgroup,no swap,1-hour limit. Source provenance and lesion chirality pass.
The companion collector verifies native completion before comparison. The job
is live; no QM result or acceptance is claimed. Ruff passes. This additional
geometry is diagnostic development evidence, not a fresh holdout for any
subsequent fit that uses it.

## First independent water target opened after prediction freeze

`compare_water_validation.py` audits every completed validation result against
its frozen batch/worker/geometry hashes, Psi4 version, all three native MP2
energies, frozen-core occupations, full cc-pVQZ ghost basis and unscaled CP
subtraction. It reports native LJ and BOTH previously frozen depth hypotheses;
it performs no fitting or selection. Training and validation roles remain
separate. `cpd-water-validation-comparison-v1` contains1/6 held-out cases:
endpoint1 H3 donor, alternate water plane. QM CP interaction=-5.49258912
kcal/mol; native prediction=-6.94719574 (error-1.45460662), shared-carbonyl/H3
hypothesis=-5.65911213 (error-0.16652301), separate-O2/O4/H3=-5.65826396
(error-0.16567484). The full independent validation is incomplete; neither
hypothesis is selected or accepted, and radial validation remains required.
Ruff passes. Three local QM services are live. Last provider/SSH check confirms
7/12 cloud results downloaded, estimated cumulative$2.7194, original21:55:40Z
shutdown unchanged. No additional cloud resources allocated.

## Two-conformer charge-only block rejected after self-consistent relaxation

`multiconformer_charge_block.py` freezes one development experiment using the
reference static DFT target and first thermal-conformer DFT target, equal
geometry weights, original ESP/dipole sigmas and prior penalty, native cap
neutrality/H equivalence constraints, atomic[-1.2,1.2] and LP[-0.5,0] charge
bounds. Polarizabilities, damping and anisotropy remain fixed. This is one
fixed-induced linear charge step, followed by a separately rebuilt complete
model; rebuilding preserves correct changed-charge1-4 products. No validation
geometry is used in the fit and no weight search is performed.

`cpd-multiconformer-charge-block-v1` is a FAILED diagnostic. SLSQP converges in40
iterations with charge constraints4.44e-16, but maximum charge change0.67570 e
and re-relaxed Drude displacements0.30991/0.39110 A make it unusable. Reference
ESP RMS0.001379 au/dipole error0.41232 au; thermal ESP RMS0.006747 au/dipole
error0.29409 au. Strong induced feedback defeats this fixed-induced charge
step. This does not prove a fully self-consistent multi-conformer fit cannot
work. Candidate remains isolated, simulation_ready=false, no gate changed.
Ruff passes. The second thermal static DFT completed natively in252s; its
separate collector handles provenance and quantitative comparison.
The second thermal geometry's native-completion/provenance audit passes:
static ESP RMS0.00473945 au (relative27.5837%), dipole-vector error0.495483 au
for the original frozen electrostatics. QM dipole=(-1.096178,-0.447400,-0.030469)
au versus model=(-1.053252,-0.173176,0.379972). This independent conformer confirms
poor static transfer at the endpoint1 C2 failure. It is not a response test;
response transfer and a self-consistent multi-conformer parameter treatment
remain necessary. No accepted parameter set results from this turn.

## Self-consistent two-conformer charge fit and excluded-geometry failure

`selfconsistent_charge_fit.py` now relaxes polarization at every SLSQP
objective/constraint evaluation, retaining prior weights, original charge
bounds/equalities and all40 per-site0.20-A displacement constraints across
the two development geometries. Live charge updates explicitly update nuclear
1-4 exception products; final observables agree with separately rebuilt models
to1e-8. No response parameters change. `cpd-selfconsistent-charge-fit-v1`:
53 iterations,2636 unique evaluations, convergence reported, charge constraint
8.88e-16. Reference ESP RMS0.00035649 au/dipole error0.11431 au, maxDrude0.17460 A;
thermal training ESP RMS0.00229307 au/dipole error0.09372 au, maxDrude
0.200000000750 A. The tiny negative margin is RETAINED, not rounded into a pass.
Maximum charge change0.41486 e. Ruff passes. No response or parameter acceptance.

The third, previously exposed geometry was excluded from this fit and assessed
without refitting (`excluded_geometry_assessment.json`). ESP RMS0.00415880 au,
relative24.2043%, dipole error0.441905 au, maxDrude0.29058653 A. This is a clear
transfer FAILURE, not a fresh holdout claim. Improving the two training static
targets does not establish multi-conformer polarization validity.

## Budget-preserving extension of existing cloud pod

At21:49:23Z, the SAME owned pod1ci049femlb4r9 received a deadline extension from
21:55:40Z to23:50:00Z (5:50PM MDT). Forecast cumulative cost including disk
reserve at the new deadline is$3.71739, below the unchanged$4 working cap and
user$5 maximum. Controller's$0.25 teardown reserve remains unchanged. Both
replacement guards were started and verified before original guards were
retired: remote PID4891 and local
`nadoc-runpod-watchdog-1ci049femlb4r9-extended.service`, still tracking exact
controller PID794701/start ticks65038233. This avoids discarding paid work
while retaining independent off-host/local teardown. No new pod or storage
allocated. Original launch and guard snapshots remain intact; extension plan,
script and receipt are in `cpd-drude-cloud-budget5-v1`.

## Thermal-geometry response targets launched locally

`prepare_thermal_response.py` freezes8 signed external-charge probes across the
two static-QM thermal failure geometries: both endpoint O2 sites, +/-0.5 e,
positions3.344 A from O2 along the C2-to-O2 direction (2.2 times oxygen Bondi
radius). All probe positions have nearest-nucleus distance>2 A. Model response
predictions exclude the explicit external charge from the reported solute ESP
and dipole, re-relax Drudes for every probe, and retain all domain failures.
Unperturbed QM reference outputs and all inputs/predictions are hash-linked.
These are prospective diagnostic targets for future development, not a release
validation set or a substitute for additional conformers.

Initial preparationv1 failed provenance checking because the first thermal
preparation script had since acquired a CLI. Its exact original source was
reconstructed and SHA256-verified against the ORIGINAL frozen plan, saved as
`cpd-thermal-conformer-qm-v1/original_preparation_snapshot.py`. No target or
manifest was changed. Preparationv2 checks that immutable historical source.
The failed attempt is retained, and `cpd-thermal-response-v2` is the new batch.
`run_thermal_response.py` runs sequential B3LYP/aug-cc-pVDZ jobs with4 threads,
4GB Psi4,8GiB cgroup,no swap,90-minute batch deadline and20-minute per-case
limit. It refuses output overwrites, audits native completion/ESP/dipole, and
reports response differences as each case completes. Service
`nadoc-cpd-thermal-response-v2.service` is live; no new QM response result yet.
Both scripts pass Ruff. No cloud resource or production parameter changes.

## Terminal response batch, cloud teardown and ring failure (00:18Z Sep17)

All8 thermal response jobs completed with native audits. RMS relative ESP
response error0.16931458 and dipole-change error0.11844346 are moderate, but
7/8 perturbed stationary models remain outside the unchanged0.20-A domain.
These response data must be retained with the static conformer targets in any
next fit; good response alone does not cure poor static transfer or domain
failure. Verified executed sources for the recent fitting/response/comparison
experiments are now copied into artifact-local source_snapshots inventories.

RunPod1ci049femlb4r9 is confirmed ABSENT by live provider query after scheduled
teardown. Shared ledger total including disk reserve=$3.71802788.10/12 cases
were collected; endpoint2 O2/O4 alternate-plane validation targets remain.
`cpd-water-validation-comparison-v2` audits4/6 validation cases: native LJ
RMSE1.21186978, shared-carbonyl/H3 depth hypothesis0.25668077, separate-O2/O4/H3
0.19365045 kcal/mol. No parameter selection or release acceptance follows.
Remaining user budget is$1.28197; no replacement pod was launched. A cold
cloud case previously took107min versus~39min thereafter, so remaining-budget
routing must account for cold-start runtime rather than assume two warm cases.

Fixed-ring-minus5v2 terminated at80 optimization iterations, unconverged;
its independent audit has zero accepted cases. The original target angle and
all failed native output remain preserved. No result is accepted based on a
near-converged intermediate step. Native-sugar endpoint1 QM remains active
(PID1080380), most recently step61 with force1.20e-5 au but unconverged step
criteria; no restart or threshold relaxation.

## Joint static/response charge fit launched (00:21Z Sep17)

`joint_static_response_charge.py` uses all3 exposed static geometries and all8
signed thermal response targets in one self-consistent charge-only fit.
Polarizabilities/damping/anisotropy remain fixed in this hypothesis. The
objective retains static ESP/dipole sigmas and prior penalty, adding mean
squared normalized response errors with relative scales0.35/0.25. Original
reference24 response cases remain outside this fit for a later regression
audit (previously exposed, not fresh). All220 induced distances across11
states are constrained to0.1999 A, a numerical fitting margin inside the
UNCHANGED physical0.20-A limit. No case is dropped; no weight search.

`cpd-joint-static-response-charge-v1` records sources, all response IDs and
optimizer settings before optimization. Finite-difference SLSQP has80 max
iterations; native local service uses one BLAS thread,3GiB cgroup,no swap,
1-hour deadline. Every objective evaluation relaxes polarization and checks
forces. Charge-dependent1-4 exception products are updated explicitly, with
final rebuilt-model agreement checked as in the previous fitter. Service
`nadoc-cpd-joint-static-response-charge-v1.service` is live at PID1295601;
intermediate infeasible iterates are not candidates or acceptance evidence.
Ruff passes. No production gate/parameter or cloud resource change.

The native-sugar endpoint1 job remains live at step62: maximum force6.24e-6 au
passes its force threshold, but displacement criteria remain unconverged.
Its original deadline and criteria are unchanged; endpoint2 still follows
only after native endpoint1 optimization succeeds.

## Reference-response regression collector prepared

`check_reference_response.py` evaluates all24 previously exposed perturbations
at the original reference geometry with an explicit candidate file, strict
Drude stationarity, zero external charge in solute ESP/dipole observables and
native QM completion checks. `cpd-reference-response-regression-control-v1`
rechecks the original frozen model: response RMS0.1776402895, dipole-change
RMS0.1612434722, maximumDrude0.1721776186 A. Differences from the historical
checker are1.754e-7 and2.055e-7, respectively, retained explicitly. An initial
numerical comparison assertion at1e-7 failed; it is not an acceptance gate and
no scientific thresholds were changed. The new evaluator uses the full
AdiabaticNonbonded implementation with force-root refinement and live LPs.
Ruff passes. No new QM calculation is implied by this regression.

Collector `nadoc-cpd-joint-reference-regression-v1.service` waits for the exact
live joint-fit service to terminate, checks native process success and the
candidate artifact, then runs the24-case regression automatically. It records
failure rather than evaluating an incomplete candidate if the fitter crashes.
Joint fit remains active; all intermediate iterates remain unaccepted.

## Joint fit converged; reference regression and all-frame stationary checks

`cpd-joint-static-response-charge-v1` converged in47 iterations/2321 unique
evaluations, charge constraint1.78e-15. All11 fitted states are inside0.20 A;
maximum perturbed displacement0.19730110 A. Static reference ESP RMS0.00024143
au/dipole error0.08183258 au; thermal1 0.00267757/0.17077038; thermal2
0.00257831/0.12193445. Both thermal geometries FAIL the unchanged static ESP
0.002-au and dipole0.1-au criteria. Maximum charge change0.66152 e; no release.
Thermal response RMS0.17479738 and dipole-change RMS0.16048974. The automatic
24-case reference regression completed: response RMS0.18525362, dipole-change
RMS0.16928105, maximumDrude0.15721340 A. This is a previously exposed regression,
not fresh validation or a substitute for missing physical checks.

`audit_all_thermal_excursions.py` now supports explicit --candidate and
--all-frames, with prior executed source copies retained. The candidate's
polarization was re-minimized at ALL3000 saved nuclear geometries from the
new bonded candidate's four trajectories: zero stationary domain failures,
maximumDrude0.18364299 A (`cpd-joint-charge-all-frames-v1`). The31 original
dynamic excursion frames are still identified separately. This does NOT
rerun trajectories with new charges, establish minimum Hessians at all frames,
validate nuclear mechanics after electrostatic changes, or prove QM accuracy.
An initial console label called all3000 processed frames excursions; the JSON
correctly records frames_reminimized=3000 and excursion_frames=31. Console
label corrected afterward, exact executed source retained. Ruff passes.
Static multi-conformer accuracy remains the immediate fitting blocker.

## Static feasibility trial and bounded final water batch

The joint fitter now accepts explicit output/initial-charge paths and
--enforce-static. `cpd-static-feasibility-charge-v1` starts from the converged
joint candidate and adds unchanged per-geometry ESP0.002-au/dipole0.1-au limits
as hard fitting constraints, retaining all11 states and response objectives.
This trial TERMINATED on its strict polarization force convergence assertion
at an optimizer trial point. It is a numerical optimization failure, not proof
of charge-model infeasibility and not an accepted candidate. Executed source,
terminal log and failure classification are preserved; force/domain checks
were not relaxed. The CLI changes pass Ruff.

The two remaining water targets are now routed to a new, bounded CPU pod
n545y20v8e9170, after original pod absence was verified. Live quote and actual
rate both$0.64/hr for16vCPU/64GB; disk allowance$0.03/hr. Root
`cpd-water-remainder-budget5-v1` shares the ORIGINAL spend ledger by symlink,
so previous$3.71803 is included. User cap remains$5. Working cap$4.75 plus a
10-minute runtime reserve gives4944 seconds, deadline01:50:33Z Sep17
(7:50:33PM MDT Sep16), forecast maximum cumulative~$4.6384. Controller also
stops when working remaining<$0.10. Exact-pod local watchdog is active;
resource preflight and remote guard must succeed before QM starts. Worker
uses16 threads, same frozen-core DF-MP2/cc-pVQZ CP method/geometries; only the
remaining endpoint2 O2/O4 validation cases are present. This is not a new
independent geometry set or any change to previously frozen predictions.

## Resumed-water provenance merge prepared

`compare_water_validation.py --additional-cloud` now audits remaining targets
against their OWN execution batch and worker hashes while requiring exact
case-definition equality with the original six-case validation plan. Method,
CP scale and distance conventions must match; duplicate results are rejected
for explicit reconciliation. Both frozen LJ hypotheses and native baseline
remain reported; no selection/refit. Original executed scripts were preserved
before adding the CLI. `cpd-water-validation-merged-preflight-v1` checks the
new batch definitions with4 existing results and reproduces the prior metrics.
Ruff passes. Collector `nadoc-cpd-water-remainder-validation-v1.service` waits
for the exact controller to terminate, then audits all completed results,
including when a deadline leaves the last case incomplete. It cannot turn
partial completion into a six-case pass. Cloud worker launch is confirmed
PID589 on owned podn545y20v8e9170; local controller PID1303888 remains active.

## Bounded local static-feasibility retry

After the unconverged-polarization trial in the unrestricted hard-constraint
run, the fitter adds optional --charge-neighborhood. The new local hypothesis
restricts each charge to +/-0.05 e around the converged joint candidate,
intersected with original physical charge bounds; the original charge model,
all datasets, static accuracy limits, response weights and Drude force/domain
limits are unchanged. It is explicitly a LOCAL feasibility search, not a
global model-feasibility proof. `cpd-static-local-feasibility-v1` is running
under `nadoc-cpd-static-local-feasibility-v1.service` (1 BLAS thread,3GiB,no swap,
1-hour limit,80 optimizer iterations). No failed run is overwritten or accepted.
Ruff passes. A candidate's native solver status and all criteria must be read
before any further validation or use; no release follows from merely staying
inside this search neighborhood.

## Failed ring optimization history reconstructed

`diagnose_ring_convergence.py` reconstructs all80 native convergence rows and
corresponding current geometries from the failed fixed-torsion run. The lowest
reported max-force step is9 (2.72e-5 au), still above the original1.50e-5
threshold; it is not accepted. There are25 energy-increase steps. The recovered
step9 seed has torsion19.9457253789 degrees, consistent with the unchanged
19.9457253760-degree target. All stepwise torsion errors and native force/step
metrics are retained in `cpd-ring-convergence-diagnostic-v1`. The traceable seed
allows a different constrained optimization strategy without restarting from
the severely unconverged final step. It requires fresh derivative evaluation
and eventual minimum certification; no QM energy target was accepted from
this diagnosis. Ruff passes. Current local charge-feasibility and native-sugar
workers remain separate, with their original criteria/deadlines intact.

## Fresh derivative evaluation of recovered ring seed

`cpd-ring-seed-gradient-v1` runs one fresh frozen-core DF-MP2/6-31G(d)
energy/gradient at the traceably recovered native step9 geometry. It reuses
the hash-pinned successful fixed-coordinate scan worker and method settings
without substituting an old convergence table for a derivative result. Local
service `nadoc-cpd-ring-seed-gradient-v1.service`:4 threads,4GiB Psi4,6GiB
cgroup,no swap,30-minute deadline. No optimization or scan-target acceptance.
A separate terminal collector checks execution/provenance and projects the
Cartesian gradient onto the tangent space of the exact ring torsion. The
constraint Jacobian is checked at two finite-difference steps. These Cartesian
projected-force metrics are explicitly distinct from Optking's internal-
coordinate GAU_TIGHT criteria; neither metric alone certifies a minimum.
The result will guide a different constrained optimizer, rather than another
restart from the failed final geometry. Other live jobs are not restarted.

## Fresh ring derivative confirms constrained residual

`cpd-ring-seed-gradient-v1` completed with its independent derivative audit.
Energy=-983.926004996772 Eh, target torsion19.945725378902 degrees. Raw maximum
Cartesian gradient0.01118298486 Eh/bohr is dominated by the constraint force;
projection into the torsion tangent space gives maximum5.1282600e-5 and
RMS1.6066264e-5 Eh/bohr. Constraint multiplier0.03962273328 Eh/radian.
Finite-difference Jacobian step-halving relative discrepancy3.24e-11.
This independently confirms the recovered seed is not stationary along the
allowed coordinates. No gradient threshold or minimum criterion is relaxed.
An unconstrained restart would minimize a different physical target; a new
optimizer must preserve the exact torsion and establish constrained
stationarity, followed by curvature checks. Native sources and all derivatives
are retained. The bounded charge feasibility solver and sugar-fragment QM
remain live; neither has been restarted based on elapsed observation time.
The subsequent terminal poll found local charge-feasibilityv1 FAILED:80-iteration
limit,4066 evaluations, charge equality residual3.08478e-6 e above1e-8.
The strict assertion prevented candidate export. Domain margin alone does not
rescue it. Terminal log/solver/failure classification are preserved. This is
not a global infeasibility proof; no third charge-only retry is launched here.
