# CPD constrained-optimization strategy — 2026-09-23

## Evidence and literature

These are molecular geometry minimizations with an exactly frozen glycosidic
coordinate. Target convergence uses projected allowed-coordinate forces; raw
Cartesian force along a constrained coordinate need not vanish. Small energy
changes alone are not evidence of convergence. No optimizer status is a
harmonic-minimum certificate.

The practical first choice is safeguarded quasi-Newton/RFO optimization in
internal coordinates: inexpensive curvature updates, predicted-versus-actual
energy reduction, adaptive trust radius, and bounded rejection/backtracking.
The installed OptKing implementation already supports these mechanisms.
Its defaults dynamic_level=0 and consecutive_backsteps_allowed=0 permit
continuing despite bad steps. Large energy excursions and skipped Hessian
updates are visible in our native logs. Merely extending150-step budgets failed.

Primary sources consulted:

- Bakken & Helgaker (2002), *The efficient optimization of molecular geometries
  using redundant internal coordinates*, JCP117,9160–9174:
  https://trygvehelgaker.no/Publications/JChemPhys_117_09160_2002.pdf .
  Coordinate selection and approximate curvature matter for iteration efficiency.
- Wang & Song (2016), *Geometry optimization made simple with translation and
  rotation coordinates*, JCP144,214108, doi:10.1063/1.4952956.
  Author implementation: https://geometric.readthedocs.io/en/latest/how-it-works.html .
  geomeTRIC combines delocalized coordinates, BFGS and step-quality trust control.
  TRIC is a fallback benchmark candidate, not demonstrated faster for this CPD.
- OptKing algorithms/source:
  https://optking.readthedocs.io/en/latest/algorithms.html and
  https://optking.readthedocs.io/en/latest/_modules/optking/stepAlgorithms.html .
  Installed source is authoritative for options; version differences matter.
- Gradient accuracy troubleshooting:
  https://geometric.readthedocs.io/en/latest/help.html .
  Inconsistent energy/gradient predictions can collapse trust radius. Tightening
  an irrelevant option does not improve the actual gradient calculation.
- Denzel & Kästner (2018), *Gaussian Process Regression for Geometry Optimization*,
  JCP148,094114, https://arxiv.org/abs/2009.05803 . Their26-system benchmark
  reduced steps relative to L-BFGS. This is promising future work, not evidence
  that GP optimization outperforms constrained RFO for our49-atom CPD fragments.

Full finite-difference MP2 Hessians are expensive at this size; do not calculate
one each iteration. If cheap trust safeguards fail, compare a one-time model/
lower-level Hessian or geomeTRIC on the same screened seed and tolerances.
Evaluate cost in actual gradient calls and core-hours, not step count alone.
L-BFGS saves optimizer memory but that is negligible beside this QM calculation;
its small memory footprint alone is not a reason to change engines.

## Implemented experiment-only policy

`experiments/cpd_anti_additive/optimization_guard.py` instruments OptKing inside
the individual Psi4 process, without changing installed libraries or product
geometry paths. Native optimizer retains convergence authority.

- Adaptive trust radius0.05 initially, bounded0.001–0.1 in OptKing's internal
  coordinate convention (not a Cartesian angstrom radius).
- Two consecutive backsteps permitted. Dynamic level1, maximum1: exhaustion
  ends the attempt rather than silently switching coordinate/constraint schemes.
  This is bounded backtracking, not an implemented multi-engine recovery ladder.
- After each gradient, save the actually evaluated coordinates and Cartesian
  gradient in bohr/atomic units BEFORE proposed/backtracked coordinates replace
  them. Save projected-force metrics, step sizes, trust radius, and best-energy
  and best-force checkpoint references. Latest approximate internal Hessian is
  retained for diagnosis, not advertised as a complete restart checkpoint.
- Stop at12 successive large-force/tiny-step evaluations with<10% force
  improvement (force>10× tolerance, maximum internal step<3e-4).
- Stop after3 consecutive large excursions (>0.005Eh above best energy AND
  force>max(10× best-energy-point force,100× tolerance)), after at least12
  evaluations. One uphill trial is allowed to recover.
- Stop on nonfinite values; maximum60 evaluations. Native convergence bypasses
  the diagnostic budget but still needs final independent geometry audit.
- Thresholds are explicit CPD heuristics, not literature constants or proofs
  of divergence. A diagnostic stop is a failed/unreviewed attempt, never success.

Retrospective v5 replay flags endpoint1+15 at16 steps and both endpoint2
trajectories at36, versus150 steps spent on each completed failure. Replay uses
rounded printed rows and these same development trajectories; it is not an
independent validation of detector sensitivity or future savings.

## Verification and bounded pilot

Five pure tests cover stall versus progress, near-convergence behavior,
single versus sustained excursions, nonfinite/budget handling, and partial/
duplicate native rows. Native HF/STO-3G water smoke optimization converged with
the instrumented installed Psi4/OptKing driver. This verifies integration only,
not CPD convergence or scientific correctness of a relaxed CPD geometry.

Stopped the remaining v5 job after documented repeated excursions, preserving
all native evidence. v6 runs only endpoint2+15 from its screened near-converged
v2 seed. Other prepared points are held. Method/basis, frozen-core and GAU_TIGHT
geometry criteria remain. SCF E/D=1e-12; use SOLVER_CONVERGENCE=1e-10 (verified
as the actual SCF response option), replacing CPHF_R_CONVERGENCE, which did not
tighten the observed solver. Native residuals still must be verified. One4-thread,
6GiB job with local scratch;12GiB service cap and6h hard deadline. No cloud.

Next gate: inspect native solver residuals, evaluated-geometry provenance,
constraint/chirality/covalent checks, convergence and gradient consistency.
If diagnostic stops recur, choose a bounded recovery from a screened good
checkpoint; do not repeatedly continue from a worse last iterate or loosen
geometry tolerances. A repeated-gradient/directional-energy consistency check
and alternative-coordinate/Hessian comparisons remain pending, not claimed done.

Additional native integration check: constrained HF/STO-3G hydrogen peroxide
converged with the guard installed and retained its frozen H–O–O–H dihedral
(error0.0degrees at reported precision). Both native smoke artifacts and
retrospective detector results are in `cpd-optimization-guard-validation-v1`.
This checks instrumentation compatibility with constraints, not MP2 CPD accuracy.

## v6 failure and option-alias correction

v6 stopped after14 evaluations/36minutes through the sustained-excursion guard.
Native output hash matches its failed run manifest. Response solves actually
reached<1e-10, verifying the corrected SOLVER_CONVERGENCE control. No optimized
minimum or successful constrained convergence resulted.

However, the native optimizer ignored internal field names supplied as keywords:
normalization uppercases keys but fields with explicit aliases require those
aliases. Thus v6 did not test the intended trust/backtracking settings. Corrected
keys are DYNAMIC_LVL, CONSECUTIVE_BACKSTEPS, INTRAFRAG_STEP_LIMIT[_MIN/_MAX],
with DYNAMIC_LVL_MAX. Now verify all effective values immediately after helper
construction, before the first gradient. Preserve v6 as failed configuration
and diagnostic evidence, not a successful adaptive-method benchmark.

Six unit tests pass, including fail-closed mismatched effective options. A new
native constrained HF/STO-3G peroxide optimization converged while verifying the
0.1 trust cap throughout and zero frozen-dihedral error at reported precision.
Artifacts: `cpd-optimization-guard-validation-v2`. v7 repeats the single screened
endpoint2+15 pilot using a copied corrected guard; all other points remain held.
