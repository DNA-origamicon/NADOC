# Cis-anti first-candidate closeout and shape-correction review

The first locked candidate passes its four prospective relative-energy tests but
fails conformational qualification because shape correspondence fails. This closes
the registered validation of that candidate; neither its parameters nor its
acceptance criteria have changed. The next correction must address the observed
ring/attachment shapes. More optimization of the already stationary structures
does not address that parameter error.

Execution update: the [shape-v2.2 contract](cpd_anti_shape_fit_v2_r2.md) was frozen
and launched at 02:29:42 UTC, reserving the second and final round in a registered
successor state. This residual review and the first candidate's verdict remain
historical evidence; the original candidate lock remains closed.

## Complete prospective evidence

The acquisition service completed at 2026-09-27 02:05:54 UTC. Its actual wake
`a88710de-cc8e-4d06-b9c8-116f9aed758e` was acknowledged at 02:06:33 UTC.
`cpd-anti-prospective-qm-service-v2-r1/completion_delivery_verified.json` checks
all 73 native MP2 gradients (20/19/15/19), input/result hashes, electronic responses,
trajectory and final XYZ coordinates, chemistry, constraint satisfaction, and
three Cartesian projections plus the analytic constraint normal. All four pass
constrained stationarity. No new Hessian was calculated or minimum certified.

The frozen scorer's second invocation, service `cpd-anti-prospective-score-service-v2-r1-b`,
finished at 02:07:17 UTC. It reused the first three scores and performed one new
36-evaluation MM relaxation for the fourth target. Independent verification in
its `scientific_review.json` checks all 133 saved MM evaluations and re-evaluates
the four final energies/forces from the exported candidate. Historical reviews
and the archived three-target snapshot remain unchanged.

| Target | MM−QM relative energy, kcal/mol | Heavy RMSD, Å | Maximum heavy torsion error |
|---|---:|---:|---:|
| Endpoint 1 −22.5° | +0.436778 | **0.334798** | 17.396° |
| Endpoint 1 +22.5° | −0.197031 | 0.156410 | 16.814° |
| Endpoint 2 −22.5° | +0.264849 | 0.159494 | 16.614° |
| Endpoint 2 +22.5° | +1.621983 | 0.192642 | 13.883° |

RMS energy error **0.855945 kcal/mol** and maximum **1.621983 kcal/mol** pass the
unchanged 1/2 kcal/mol limits. Endpoint 1 −22.5° fails the 0.25 Å shape descriptor.
The seven original shape failures remain. The 20° torsion descriptor, representative
0.03 Å/3° targets, electrostatics, and context requirements are unchanged.

## What the model diagnosis establishes

`cpd-anti-shape-model-diagnosis-v1c/assessment.json` examines all 23 saved QM/MM
pairs and all 19 pre-fit MM baselines, inventories the actual parameter terms,
and reads saved MM gradients at the exact QM coordinates. It performs no new QM
or MM energy calculation, relaxation, or parameter fit.

1. The original energy fit reduced shape failures from **10/19 to 7/19**, but
   created the worst remaining failure: lower-basin endpoint 2 +15° changed from
   RMSD 0.136614 Å / torsion error 15.057° before fitting to 0.688454 Å / 40.105°
   afterward. Aggregate improvement cannot conceal this regression.
2. Six of the twelve fitted coefficients describe the scanned O4′–C1′–N1–C2
   torsions. At a fixed value of that coordinate, a Fourier term depending only
   on it has zero derivative along allowed geometry changes. All 66 applicable
   unit-feature checks reproduce this, with maximum projected norm
   1.382e−9 Å⁻¹. This is useful for fitting scan energies but supplies no direct
   shape correction at that fixed angle. The unconstrained remote case is exempt.
3. Only the other attachment proper, C2′–C1′–N1–C6, directly changes constrained
   shapes in the first model. The capped partner's N1 force at the same QM
   geometry is unchanged by the fit. Endpoint-1 failures, including the new
   prospective failure, share that capped endpoint-2 distortion.
4. The observed large torsion residuals specifically implicate the coordinates
   attachment/cap–N1–C6–opposite C5, attachment–N1–C2–N3, and N1–C2–N3–C4.
   Existing proper terms around these ring bonds were outside the first fit.
   This localizes a correction opportunity; it does not prove that changing any
   one term will fix the coupled structure.
5. The topology has four carbonyl-centered impropers and no explicit N1-centered
   improper. This alone is not evidence that a term is missing: proper torsions,
   angles and nonbonded forces also govern out-of-plane response. QM N1 heights
   are nonzero and conformation-dependent, so imposing planar N1 would not be a
   justified correction. Signed height changes are not stereochemical inversions.

The diagnostic's first attempt stopped on an OpenMM attribute-name error before
analysis; it is preserved under `cpd-anti-shape-model-diagnosis-v1/failure.json`.
The second attempt's numerical results were valid, but its frozen-coordinate flag
omitted reversed quartet ordering. Its original output and classification erratum
remain under `v1b`; `v1c` handles both orientations and checks all 66 identities.

## Bounded correction design

The next model should retain the CHARMM additive form, charges/LJ and parent
sugar/phosphate parameters, and examine existing lesion proper families involving
the three coordinates above. Both ordered bases and methyl-cap versus sugar
attachments require explicit mapping. A revised objective must assess relaxed
geometry alongside energies so that the +15° regression cannot improve the
objective unnoticed. A force-based diagnostic must project out the actual scan
constraint; full constrained-QM gradients are not zero-force targets.

This follows the separation of bonded geometry and conformational-energy targets
in [Mayne et al., ffTK](https://pmc.ncbi.nlm.nih.gov/articles/PMC3874408/) and the
combined geometry, vibrational and energy-surface checks in
[Vanommeslaeghe et al., CGenFF](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/).
The specific CPD term selection and numerical stopping limits are local decisions,
not thresholds established by those papers.

Before consuming the last permitted fit round, prepare one versioned execution
contract with exact parameter keys/multiplicities/bounds, a fixed objective and
evaluation budget, and the complete 23-case exposure history. Keep the original
candidate lock closed. The new contract must carry forward the consumed round
and stop after the remaining round; it cannot reset the two-round budget.
Observed ±22.5° targets may be regression data for a revision, but cannot serve
again as blind validation. Register fresh independent targets before acquiring
them and freeze the revised candidate before that acquisition. No fit was
reserved or performed during this diagnostic review; the later execution update
above records the separate second-round reservation.

Do not launch the six prescribed 10 ns context trajectories while parameter gates
fail. Existing 100 ps NAMD engineering passes remain valid for the first candidate;
changed parameters require their own engine checks. Product placement and normal
application promotion are separate. No cloud spending or scientific release.
