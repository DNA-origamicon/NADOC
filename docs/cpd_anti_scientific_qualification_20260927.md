# Cis-anti scientific qualification continuation

**Latest review — 2026-09-27 17:20 UTC:** the
[shape evidence audit and separate bounded Sella refinement](cpd_anti_shape_evidence_review_20260927.md)
completed 12 additional development vectors. Worst RMSD improves to 0.2589 Å,
but selected trial7 still fails three shape, one maximum-energy and one
representative-angle criterion. Native replay verifies all 11,074 evaluations.
No candidate is qualified. The older closed runs below remain historical evidence;
no further calculation is active. Current evidence supports checking competing
QM conformations before interpreting an operational shape cutoff as physical truth.

The user selected Sella as the main optimizer and requested continuation toward
scientific quality on 2026-09-26 America/Denver. The durable
[optimizer preference](../memory/feedback_sella_default.md) now applies to new QM
and fragment-MM geometry work. Psi4 remains the electronic evaluator and NAMD the
MD engine. Frozen historical and active inputs are unchanged.

The working qualification target remains the previously selected preliminary
structural use with documented limitations, under the
[fixed v2 protocol](cpd_preliminary_protocol_v2.md). An optional scope question is
pending about quantitative mechanics/free energies; work below is necessary for
either scope and does not assert that the broader scope is validated.

**Current execution:** the [second/final fit](cpd_anti_shape_fit_v2_r2.md) and its
authorized OOM recovery are closed at the original04:29:42UTC deadline. The
[audited closeout](cpd_anti_shape_fit_closeout_20260927.md) retains69 complete
models; selected61 passes exposed energy RMS0.294398/max0.915744 and all three
representatives, but fails three profile RMSDs (0.297–0.321Å versus0.25Å).
There is no optimizer-convergence or scientific-qualification claim. Native
audit verifies all36 recovery models plus24 recorded fragments of incomplete70;
the original33-model evidence is unchanged. Recovery memory peaked near672MiB.
Both rounds and wall budget are exhausted, all23 structures are exposed, and
no further fit, newQM or contextMD has launched. The table below describes the
original locked candidate; model61 is a failed development trial, not a promoted
replacement. Original candidate verdicts remain valid.

## Current evidence and gates

| Stage | Evidence | Qualification status |
|---|---|---|
| Electrostatics | Existing 17 clean water curves pass fixed criteria | Passed for the declared scope |
| Exposed conformational energies | 19 cases, RMS 0.5421 / maximum 1.0099 kcal/mol | Pass energy criteria |
| Representative geometry | Three representatives pass 0.03 Å / 3° lesion/attachment criteria | Passed |
| Profile shape correspondence | Seven of 19 fail retained 0.25 Å / 20° descriptors | Unresolved; remains blocking |
| Native implementation | Four full-solute/solvent static comparisons and paired 100 ps full-DNA tests | Engineering stage passed |
| Prospective conformational validation | All four scored; RMS 0.855945 / maximum 1.621983 kcal/mol | Energy passes; one shape mismatch remains blocking |
| Preliminary interstrand context | Three seeds per anti/control, 10 ns each prescribed by v2 | Awaiting parameter qualification and a frozen context execution plan |

The existing source-placement screen remains failed. Normal application geometry
promotion is separate. No minimum, equilibrium, quantitative mechanics, or full
scientific release certificate is asserted.

## Prospective scoring performed

The original candidate registration preceded all four prospective QM targets.
The new scorer executes the follow-on method already recorded in that acquisition
plan. It never changes parameters or energy-reference conformer identities.
Its preparation and inputs are frozen in `cpd-anti-prospective-score-v2-r1`.

Each completed target first receives a native audit: exact atom order, inputs,
printed MP2 energy/gradient, electronic response, Sella trajectory and XYZ,
chemistry, three independent Cartesian projections, and Sella constraint-normal
agreement. The locked CHARMM candidate then receives one Sella MM relaxation from
that target's own QM geometry, with the existing 400-step/600-evaluation limits,
0.001 kcal/mol/Å projected force and 0.01° constraint limits. An independent reload
of the exported potential checks the final energy, force, geometry and descriptors.

The scorer has a two-hour cumulative active scoring allowance, four target
identities, and one attempt per target. A failed or interrupted attempt is retained
and never automatically rerun. Partial data cannot pass the four-target aggregate;
failed targets cannot disappear from its denominator. The original seven exposed
shape mismatches remain visible even if all four prospective energies pass.

Service `cpd-anti-prospective-score-service-v2-r1-a` completed its first invocation
at 2026-09-27 01:35:56 UTC. Independent review verifies 54 native QM gradients
(20/19/15), 97 MM optimization evaluations (36/30/31), and all three final MM
replays. Both frozen MM reference energies were also reproduced before scoring.

Its completion wake `7f89baac-4fc6-4060-86c0-4147f5b7943a` was received and
acknowledged at 2026-09-27 01:43:24 UTC. A fresh read-only audit reproduces all
54 native QM gradients, 97 saved MM evaluations and the three scores, preserving
the original reviews. The service records this in `completion_delivery_verified.json`.
`scoring_progress_snapshot.json` preserves the exact partial scoring record before
the mutable master progress later includes the fourth target; its hash and origin
are recorded in `scoring_snapshot_archive.json`. Service completion means this
partial scoring invocation finished, not that the four-target gate passed.

| Prospective target | QM relative energy | MM relative energy | MM−QM, kcal/mol | Heavy RMSD, Å | Max heavy torsion error |
|---|---:|---:|---:|---:|---:|
| Endpoint 1 −22.5° | −0.23415 | 0.20263 | +0.43678 | **0.33480** | 17.396° |
| Endpoint 1 +22.5° | 1.37038 | 1.17335 | −0.19703 | 0.15641 | 16.814° |
| Endpoint 2 −22.5° | −3.28666 | −3.02181 | +0.26485 | 0.15949 | 16.614° |
| Endpoint 2 +22.5° | 2.84678 | 4.46876 | +1.62198 | 0.19264 | 13.883° |

The complete four-target energy gate passes: RMS 0.855945 / maximum 1.621983
kcal/mol against the unchanged 1/2 limits. Endpoint 1 −22.5° fails the
unchanged 0.25 Å descriptor. This is new validation evidence, not a fitting target
silently added to the original round.

The acquisition completed at 02:05:54 UTC after 73 native gradients (20/19/15/19).
The fourth target's final projected maximum/RMS is 1.07264e−5 / 4.73245e−6 au;
all four independent constrained-stationarity checks pass. Its actual completion
wake was acknowledged at 02:06:33 UTC and independently reviewed. The second
scoring invocation finished at 02:07:17 UTC with 36 new MM evaluations for target
four and no rerun of the first three. Its independent `scientific_review.json`
replays all 73 QM gradients and 133 saved MM evaluations and recomputes four final
MM energies/forces from the exported potential. No Hessian/minimum certification.
The earlier health snapshot remains historical evidence; no QM task is active.

## Localization of the existing shape failures

`cpd-anti-profile-geometry-diagnosis-v1` reuses all 19 saved QM/MM coordinate pairs;
it performs no energy calculation, optimization or parameter fit. Recomputed
descriptors match the original seven failures. It records the largest heavy-atom
bond/angle/torsion errors, independent base/sugar alignments, and N1 heights above
the plane defined by the explicitly mapped C2, C6 and glycosidic/cap attachment.

The worst lower-basin +15° case retains RMSD 0.68845 Å and maximum heavy torsion
error 40.105°. Its endpoint-2 N1 signed height changes from −0.0825 Å in QM to
+0.1608 Å in MM. Several endpoint-1 failures similarly show a change at the capped
endpoint-2 N1. Other flagged cases involve torsions within the base ring. These
signed heights are local shape descriptors, not new stereochemical acceptance gates.

The first fit varied attachment torsions centered on C1′–N1. Important remaining
differences involve N1–C2/N1–C6 base-ring motions and coupled sugar geometry.
This is evidence for examining the parameter model and its coupled conformations;
it is not proof of an irreducible model error or permission to relax a threshold.
Every scored MM structure already passed stationarity, so further optimization of
the same stationary coordinates does not resolve this demonstrated mismatch.

The completed [shape-model review](cpd_anti_shape_correction_review_20260927.md)
extends this analysis to all 23 pairs and the 19 pre-fit baselines. The first fit
reduced shape failures from ten to seven but introduced the largest +15° failure.
Six of twelve fitted coefficients govern the frozen scan coordinate; all 66
applicable unit-gradient checks show zero tangent contribution. Existing ring/cap
proper families governing the affected shapes were outside that fit. The topology
inventory does not justify imposing planar N1 or loosening shape criteria.

## Next bounded actions

1. The first candidate's prospective verdict is complete: energy passes, shape
   fails. Preserve its registered dataset, all seven exposed and one prospective
   shape failures, and the NAMD engineering result. No repeat scoring or QM.
2. The shape-v2.2 fit and authorized memory-isolation recovery are closed at the
   original deadline. Native audit and saved-coordinate residual review are
   complete; selected61 remains failed. Both permitted rounds and wall budget
   are exhausted; any further fitting needs an explicitly versioned execution
   decision. Preserve all evaluated models. The original candidate lock stays closed. A revised
   candidate needs newly registered independent validation after an exposure
   audit; observed ±22.5° targets cannot be called blind again. No fit extension.
3. Only after parameter gates pass, freeze the prescribed anti/control context
   execution budget and structural checks, then run the original three-seed,
   10-ns-per-replica stage locally. No automatic trajectory extension.

Four focused scoring guard tests passed in 1.34 seconds through `just test-file`.
No backend/frontend application behavior, saved design, frozen policy, fit ledger,
candidate parameter, or old verdict changed. No cloud spending.
