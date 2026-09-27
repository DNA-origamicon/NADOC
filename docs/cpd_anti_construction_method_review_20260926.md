# Cis-anti construction review after the first torsion fit

The delayed conformational completion wake was received and acknowledged at
2026-09-26 21:07:54 UTC, token `e84c10a1-cc03-434f-98bb-f53a1c5529bd`.
`completion_delivery_verified.json` in its service directory verifies all38
baseline/candidate MM relaxations and1323 saved evaluations, input/output hashes,
final evaluated coordinates and independent force projections. Energy RMS0.54206
and maximum1.00992kcal/mol are reproduced. The seven profile geometry mismatches,
missing prospective validation and later full-DNA construction failure remain.
This wake did not launch a fit, optimization or dynamics job.

## What the saved construction actually did

Read-only analysis of the existing starting geometry and20 checkpoints is retained
in `cpd-anti-construction-method-review-v1/assessment.json`. No new QM or MM energy
evaluation was performed; the analysis uses saved coordinates, energies and logs.

| Quantity | Observation |
|---|---|
| System | 3043 DNA atoms, net−93e; no water or counterions;514 mobile/2529 fixed |
| Saved Reference potential-energy change | −2004.277kcal/mol |
| Lesion maximum base displacement | 7.522Å initially →14.051Å at step1000 |
| Frames satisfying the existing3.5Å screen | None of21 saved starting/checkpoint frames |
| Lesion heavy-base centroid movement from the construction seed | 8.695Å |
| Lesion heavy-base RMS change after proper rigid alignment to seed | 0.2955Å |
| Largest unmodified-residue displacement | D002:26, maximum heavy-atom22.030Å from source; centroid14.477Å from seed |
| Nearby unmodified residue | D000:7, maximum heavy-atom19.842Å; centroid13.851Å from seed |

Substantial motion therefore occurs outside the lesion, including the independent
remote repair region. The lesion's displacement has a large rigid-motion component.
The starting seed already fails the placement screen, and its lower-energy
successors move farther from the source. Reaching an optimizer stopping condition
would not itself repair this mismatch between the construction objective and the
desired placement.

The initial native NAMD record has an electrostatic component of42350.44kcal/mol
within55326.41kcal/mol total potential energy. This is an initial-state
decomposition only; no saved component trajectory attributes the subsequent
energy decrease. Unscreened electrostatics and the fixed boundary are plausible
contributors, **not proven causes**. The evidence does not show that solvent
alone will solve the geometry or that the CPD parameters are scientifically
qualified.

## Literature-supported next direction

[Hart et al., CHARMM36 DNA development (2012)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/)
used TIP3P-solvated, counterion-neutralized periodic DNA. Preparation included
500 ABNR minimization steps with5kcal/mol/Å² restraints on solute heavy atoms,
20ps restrained equilibration, and500 further minimization steps after removing
those restraints. This supports solvent and staged restraint release as part of
DNA preparation. It does not establish a universal force tolerance, validate
this interstrand CPD site, or justify copying that protocol's production duration.

The selected next method direction is a separately registered, local engineering
construction in a solvated, neutralized environment with staged positional
restraints and a matched undamaged control. CPD and native DNA parameters remain
fixed. The source/site identity, construction seed, solvent/ion model, atom
selections, restraint removal, exact stage checks and finite computational budget
must be explicit before launch. The user-authorized preliminary scope already
specifies150mM salt for eventual context qualification; an engineering diagnostic
does not substitute for that qualification.

At the time of this review, this was method selection only. The subsequent
[paired solvent construction](cpd_anti_solvated_construction_20260926.md) now
freezes and executes that direction as an isolated diagnostic; it does not claim
successful construction. The original0.01kcal/mol/Å force criterion and3.5Å
product-displacement screen remain recorded and failed; the two capped attempts
remain terminal. No larger optimizer cap, second torsion fit, prospective QM
acquisition or full-DNA dynamics follows automatically. Before any integration,
the actual proposed geometry still requires the established shared-frame A/B
review. No normal application path or saved design changed; no cloud spending.
