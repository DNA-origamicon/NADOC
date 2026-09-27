# Fresh Sella attempt, 2026-09-26

**Completed and independently accepted for constrained stationarity.** Sella
finished at 19:23 UTC after 20 new gradients (19 optimizer steps), in 55.5 minutes.
It met the original force and constraint limits; no extension or tolerance change.
The actual completion wake was received and acknowledged. Positive curvature and
minimum certification were not evaluated.

| Final check | Measured | Fixed limit | Verdict |
|---|---:|---:|---|
| Maximum projected atom gradient | 1.4434545e−5 hartree/bohr | <1.5e−5 | Pass |
| RMS projected atom gradient | 6.2129007e−6 hartree/bohr | <1e−5 | Pass |
| Torsion error | 1.2190e−8° | <0.01° | Pass |
| Chemistry and atom correspondence | All 20 evaluated geometries and trajectory frames pass | Existing graph, bond and orientation screens | Pass |

Terminal energy: **−1364.507961799582 hartree**. This is +2.50790 kcal/mol
relative to the existing lower-basin endpoint-2 reference and 1.41969 kcal/mol
below the older +15° conformer. The two +15° structures remain separate development
targets: heavy-atom aligned RMSD 0.64169 Å, maximum heavy proper-torsion difference
71.178°. Same scanned angle does not establish the same conformer.

The delivery audit rehashed all 20 inputs/results/native outputs and parsed the
printed MP2 energies and Cartesian gradients. Those agree with the saved arrays
to native printing precision. Every trajectory frame corresponds to its evaluated
coordinates; the final exported XYZ matches the last gradient. Projection of the
printed gradient passes at three finite-difference steps and agrees with Sella's
analytic constraint Jacobian. The maximum-force result passes narrowly; the
predeclared threshold was applied as written, with no extra polishing run.

Evidence: `cpd-anti-sella-fresh-v1/completion_delivery_verified.json` and
`cpd-anti-sella-service-v1/{completion_wake_ack,completion_delivery_verified}.json`.
The audit script is `experiments/cpd_anti_additive/review_sella_completion.py`.
Native Sella's final printed `fmax` lags one geometry because ASE logs before its
convergence call and Sella caches that tuple. The retained current-gradient audit
and `convergence_checks.json`, rather than that lagging display, establish the pass.

Campaign continuation: the already declared 15 historical plus four lower-basin
QM cases are assembled in `cpd-anti-conformational-inventory-v2b/inventory.json`.
All source geometries and atom maps were verified; 18 have cached gradient metrics
and the legacy endpoint-1 −15° case retains its original native audit/electronic
tolerance caveat. No historical target was discarded or relabeled blind. The
inventory proposes the same common reference identity for QM and MM in each
endpoint; torsion identities/bounds and MM branch correspondence still need to be
fixed before locking the fitting stage. No fit, Hessian or additional QM was run
in the completion review. Full-DNA construction remains a separate failed stage.
The initial inventory attempt's tuple-indexing error and source are preserved in
`cpd-anti-conformational-inventory-v2a`; its corrected read-only audit is v2b.

## Original authorization and frozen setup

The user explicitly requested: “Ok, do a from scratch attempt to push the cis-anti
CPD through Sella and see what we get.” This authorizes one new isolated Sella
acquisition attempt. It selects a different method from the previously proposed,
unlaunched geomeTRIC continuation. No old policy, failure or fitting lock is changed.

The target is the unresolved **49-atom endpoint-2 +15° lower-basin fragment**.
“From scratch” means a fresh optimizer and approximate Hessian, starting from the
original screened seed before its previous 60-evaluation trajectory. No previous
optimizer history, Hessian, gradient or final iterate is reused in the new run.
The chemical identity and already established electronic model are retained.

The immutable plan, explicit authorization, source snapshots and preflight evidence
are in `.development-artifacts/cpd-anti-sella-fresh-v1/`. Runtime dependencies are
isolated in `/home/jojo/.cache/nadoc-qm/sella-runtime-v1/`, using the existing
Psi4 environment as the read-only base. No production dependency was changed.

| Item | Frozen choice |
|---|---|
| Electronic model | Psi4 1.11, frozen-core DF-MP2/6-31G(d), RHF; energy/density convergence 1e−12, response 1e−10 |
| Optimizer | Sella 2.6.0, `order=0`, internal coordinates, quasi-Newton minimization, `eig=False`; initial trust parameter 0.1; no finite-difference initial Hessian |
| Constraint | Freeze the seed's signed dihedral 19–18–17–13, zero-based; target 99.46594372731363° |
| Hard budget | 60 new gradient attempts, six hours, zero automatic continuations |
| Local resources | Four physical CPU cores, 6 GiB Psi4 allocation, 10 GiB service cap, no service swap; no cloud |
| Expected duration | Approximately three hours; watcher overdue at 4.5 hours. Estimates are not an extension of the six-hour cap. |
| Final force criteria | Independently projected Cartesian maximum atom gradient <1.5e−5 and RMS atom gradient <1e−5 hartree/bohr |
| Final constraint | Absolute circular dihedral error <0.01° |
| Chemistry | Exact existing graph/map and anti crosslinks; preserve all screened tetrahedral neighbor-order signs and 0.7–1.3 covalent-radius bond ratios |

Sella's documented constraints may have residuals during optimization. Intermediate
torsion deviations are recorded; final acceptance remains 0.01°. This algorithmic
choice is declared before calculation. Chemical screens apply before every QM
evaluation. All attempted inputs, native outputs, completed gradients and evaluated
coordinates are retained. No relaxed-scan energy is accepted from a nonstationary
iterate.

Sella is a saddle-point optimizer by default, so minimum mode is explicit.
[Official implementation](https://raw.githubusercontent.com/zadorlab/sella/master/sella/optimize/optimize.py),
[constraint documentation](https://github.com/zadorlab/sella/wiki/Constraints).
The [alternatives review](cpd_qm_md_alternatives_20260926.md) records the selection
rationale and the limits of the published optimizer benchmark.

## Preflight completed without new QM

- Three focused regression tests passed: analytic torsion-normal projection,
  both independent force limits, and rejection of nonfinite data.
- Sella's constraint Jacobian reproduces the previous failed point's maximum
  projected gradient: 4.67220437e−5 versus independent 4.67220442e−5 hartree/bohr.
  The old point still fails; it was used only to check the adapter.
- Signed torsion conventions agree; energy/force sign and unit conversion pass.
- Installed Sella/ASE/JAX completed a constrained analytic pair-potential check
  in 16 steps; independently projected force passed. This is a software preflight,
  not CPD scientific evidence.
- The original seed has the exact C5–C6/C6–C5 inter-residue links. All 12 four-neighbor
  orientation signs match the independently relaxed reference; these include
  non-stereogenic methyl/methylene sites as well as actual stereocenters.

The worker requires both native Sella convergence and an independent Cartesian
force/constraint check before accepting optimizer completion. Its terminal review
rehashes every completed native result and repeats the final projection at three
finite-difference steps. Even a pass establishes constrained stationarity only;
positive curvature/minimum certification, parameter qualification and full-DNA
construction remain separate. No fitting or MD is chained to this attempt.

Status and completion receipt: `.development-artifacts/cpd-anti-sella-service-v1/`.
Launched 2026-09-26 at 18:28 UTC as `nadoc-cpd-anti-sella-fresh-v1.service`.
The watcher was independently verified armed before the first MP2 gradient;
token `a4dba472-7edd-497e-9d8b-cc0eef55d68c`, originating thread
`01a0db22-ab9c-78d1-beca-a95e0be69849`. This launch record is not a completion claim.
The external watcher is armed before QM starts and reports command termination
separately from scientific acceptance. Review `assessment.json`,
`independent_review.json`, `convergence_checks.json` and the native evaluations
on completion. If the hard service cap kills the process, retained partial files
are failure evidence; do not infer a final gradient or minimum.

At 18:32 UTC, the first fresh MP2 gradient completed in 179 s and the second
gradient was underway. Starting energy −1364.5058627938863 hartree; independent
projected maximum/RMS 0.00627785/0.00182527 hartree/bohr, both unconverged. The
first Sella trial preserves all chemistry screens and has torsion error
1.89e−8 degrees. Comparison with the archived calculation at the same original
seed gives energy difference −2.63e−9 hartree and maximum Cartesian gradient
difference 2.34e−6 hartree/bohr; these measured differences are retained, with no
new numerical acceptance gate. `first_gradient_verification.json` links an
immutable independent audit snapshot. This was the initial progress report;
the terminal result is recorded above.
