# Cis-anti shape evidence and bounded Sella refinement

The shape discrepancy is a difference between MM and specified QM conformers,
not a demonstrated disagreement with an experimentally established cis-anti
shape. The user's caution about inherited expectations is now recorded in
[the optimizer preference](../memory/feedback_sella_default.md).
Sella remains the geometry optimizer. The existing torsion model can substantially
reduce the discrepancy; its inadequacy has not been established. The new bounded
attempt did **not** produce a development-passing parameter set.

## What the shape target means

The 23 targets contain actual optimized QM coordinates, with fixed atom mapping
and explicit scan constraints. They are not an idealized CPD template, an assumed
planar N1, or a desired full-DNA placement. The 0.25 Å heavy-atom RMSD and 20°
proper-angle limits are local correspondence criteria. They are not experimentally
calibrated uncertainty intervals, and crossing either limit alone does not show
that the MM conformation is physically impossible.

Of the three failures in the previous model61, endpoint-1 −15° and −30° use
pre-Sella QM acquisitions. The −22.5° target was acquired with Sella and Psi4
DF-MP2/6-31G(d). Its saved QM coordinates and energy match the fitting target
exactly. Independent re-projection of its native gradient gives maximum
1.29788e−5 and RMS 4.85366e−6 hartree/bohr, satisfying the existing constrained
stationarity limits. Thus, older optimizers alone cannot explain every failure.
This establishes a stationary reference at the chosen electronic level, not a
unique relevant minimum or a solution-state structural distribution.

The audit found inherited metadata in all four ±22.5° records: several provenance
and gradient fields still describe the parent reference used to construct the
scan seed. Both endpoint-1 records also contain `constrained: false`. The actual
fitting coordinates and QM energies match the new native Sella calculations
bitwise/exactly, and the MM worker applies the correct constraint using `branch`,
not that inherited flag. These are metadata defects, not an identified numerical
scoring error. Correct source links, constraints and force metrics are recorded
in new audit sidecars; frozen historical inputs remain unchanged. Future consumers
must use those resolved links instead of treating the inherited fields as the
target's own evidence.

## Saved sensitivities

[The reproducible review](../experiments/cpd_anti_additive/review_shape_sensitivities_v1.py)
reconstructed all three 22-column Jacobians and verified all 69 completed residual
vectors against 1,587 saved QM/MM coordinate comparisons. The largest aligned
coordinate response to any 0.02 kcal/mol coefficient probe was 0.00269 Å.
Those local probes show usable response, not a demonstrated lack of corrective
degrees of freedom.

At model61, using the Jacobian from center47 only 0.02 kcal/mol away, a local
minimax calculation predicts all existing gates can be satisfied without changing
the original ±5 kcal/mol bounds or adding terms. A maximum coefficient step of
2 kcal/mol predicts a worst normalized gate ratio of 0.9972. This is only a local
prediction: the old unfinished model70 already gives a counterexample to reliable
large-step extrapolation, with a maximum RMSD prediction error of 0.0663 Å.

The predicted passing vector has original least-squares objective 3.4265, worse
than model61's 2.5295. Minimizing the aggregate original objective therefore need
not prioritize satisfaction of every separate gate. This supports testing a
gate-directed parameter search before adding new chemical terms. It does not
establish nonlinear feasibility.

## Separate bounded attempt and actual outcome

The current user direction was implemented as a separately versioned local
development attempt, `cpd-anti-shape-gate-refinement-v1`. Its plan was written
before calculation: at most 12 new vectors / 600 seconds, Sella `order=0` with
the existing internal-coordinate settings and force checks, fresh process per
vector, four CPU cores and a 6 GiB cgroup ceiling. All 23 exposed targets and
three representatives, original parameter identities/bounds, reference energies
and acceptance limits were retained. No parent sugar terms, bond/angle terms,
charges or LJ parameters were changed. The old two-round contract remains closed;
its locks, ledger, candidates and failure verdicts were hash-checked unchanged.

The outer proposal minimizes the largest normalized gate ratio, using the saved
Jacobian followed by Broyden secant updates and a bounded trust radius. Actual
Sella relaxations determine acceptance. This is a feasibility-oriented development
experiment, not convergence of the original least-squares optimizer. No new full
Jacobian was acquired at the later trials.

All 12 vectors completed in 280.2 seconds; the attempt stopped at its model cap.
Trial7 was selected by the preregistered smallest actual maximum gate ratio.
It is a tradeoff against the previous candidate, not a promoted replacement:

| Metric | Previous model61 | New trial7 | Existing limit |
|---|---:|---:|---:|
| Worst profile heavy RMSD, Å | 0.321259 | 0.258881 | 0.25 |
| Endpoint-1 −15° RMSD, Å | 0.296755 | 0.241594 | 0.25 |
| Endpoint-1 −30° RMSD, Å | 0.320938 | 0.235586 | 0.25 |
| Endpoint-1 −22.5° RMSD, Å | 0.321259 | 0.256064 | 0.25 |
| Relative-energy RMS, kcal/mol | 0.294398 | 0.997450 | 1 |
| Relative-energy maximum, kcal/mol | 0.915744 | 2.015809 | 2 |
| Worst representative bond error, Å | 0.026073 | 0.029474 | 0.03 |
| Worst representative angle error, degrees | 2.672994 | 3.111811 | 3 |

Trial7 still has three RMSD failures: endpoint-1 +30° (0.258881 Å), endpoint-2
lower-basin reference (0.256570 Å), and endpoint-1 −22.5° (0.256064 Å).
All profile proper-angle limits pass. The maximum-energy and one representative
angle criterion fail. The worst normalized violation decreased from 1.2850 to
1.0373. No tolerance was relaxed and no failed target was dropped.

Larger proposals were unreliable. Trial1 fixed the three original RMSD failures
but produced endpoint-1 +30° RMSD 0.4371 Å / proper error 32.26°, energy maximum
4.8718 kcal/mol, and a representative angle failure. Later nearby trials also
show abrupt relaxed-coordinate changes. These observations are consistent with
changes in the local conformation reached by Sella; identifying their physical
relevance requires QM comparison, not an assumption that the old conformer must
always be recovered.

## Verification and next scientific decision

The [native verifier](../experiments/cpd_anti_additive/audit_shape_gate_refinement_v1.py)
replayed all 11,074 saved OpenMM energy/gradient evaluations from the 312 fragment
optimizations, with zero observed replay difference. It independently recomputed
the final geometry descriptors, numerical/chemistry checks, residual blocks,
relative energies and gate decisions. It also checked the selected export on all
five topology fixtures and re-projected the four Sella QM targets at three finite
difference steps. All audit checks passed; the scientific development verdict
remains failed. Three analytic numerical regression tests passed in 1.17 seconds
through `just test-file tests/test_cpd_shape_sensitivities.py`.

The next useful evidence is a targeted Sella QM comparison of the competing
conformations, particularly endpoint-1 +30°, alongside Sella rechecks of the older
negative-offset references if their stability becomes decisive. Use the same
electronic model, graph, stereochemistry and constraint for both starting shapes.
Compare energies, projected gradients and local stability where needed. A changed
target should be justified by that evidence in a new dataset version, preserving
old verdicts; agreement with an inherited visual expectation is not a criterion.

If those references survive and the existing torsions still cannot reproduce
their response, acquire targeted QM bond/angle distortion or curvature data
before revising coupled attachment/ring terms. The [ffTK tutorial, section 5](https://www.ks.uiuc.edu/Training/TutorialsOverview/science/ffTK/fftk-tutorial.pdf)
uses QM Hessian-derived bond/angle distortion targets and also cautions that overly
tight geometry tolerances can inflate force constants. This supports checking
stiffness as well as positional agreement; it does not supply a CPD-specific
0.25 Å tolerance.

No further fitting or QM acquisition was chained to this attempt. Prospective
validation, final-parameter NAMD checks and interstrand context remain outstanding.
All targets used here are exposed. Trial7 is not a minimum certificate, an engine
validated bundle, or a scientific release.

Evidence is retained under `.development-artifacts/cpd-anti-shape-sensitivity-review-v1/`
and `.development-artifacts/cpd-anti-shape-gate-refinement-v1/`. The latter contains
the frozen plan/worker, every attempted vector, `native_audit.json`, and
[the all-target comparison](../.development-artifacts/cpd-anti-shape-gate-refinement-v1/comparison.svg).
An initial archived-worker import failure occurred before any calculation; its
environment correction is preserved. No historical artifact or user file was deleted.
