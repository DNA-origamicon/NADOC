# When a photoproduct parameter set is acceptable

## Short answer

A molecular picture cannot establish that a force field is acceptable. NADOC now uses
hash-pinned quantitative screens for generated QM inputs, and reserves the visual reviewer
as a diagnostic aid rather than a required gate. Charges, atom types, Lennard-Jones
choices, bonded force constants, torsion multiplicities, and transfer to DNA must pass
reproducible numerical tests; input screening alone never releases parameters.

The machine-readable NADOC policy is
`backend/data/forcefield/photoproduct_parameter_acceptance.json` version 2.1.0. It is intentionally
stricter than “NAMD starts”: a complete but physically poor parameter set is not acceptable,
and a good-looking structure is not parameter evidence.

## Evidence behind the policy

The additive CHARMM/CGenFF workflow fits partial charges against model-compound water
interaction energies and distances plus molecular dipoles. The ffTK implementation gives
target accuracies of 0.2 kcal/mol for water interaction energies and 0.1 Å for distances.
It fits bond and angle equilibrium values and the energetic response to small distortions,
using 0.03 Å, 3 degrees, and 1 kcal/mol as objective scales. The Hessian is calculated at
MP2/6-31G(d) and scaled by 0.89. Flexible dihedrals are fit against relaxed QM potential
energy scans, not inferred from a snapshot. See the primary
[CGenFF paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/) and
[ffTK paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC3874408/).

CGenFF 5 uses tight QM optimization, removes duplicate conformers only when both heavy-atom
RMSD and energy are nearly identical, and evaluates difficult fused, bridged, and
four-membered rings explicitly rather than assuming ordinary parameter transfer. Modern
force-field benchmarks additionally report optimized-geometry RMSD, torsion fingerprint
deviation, and relative conformer-energy errors on held-out molecules. Those observations
motivate NADOC's separate identity/input, response-fit, and final MM-validation layers; they
do not make a single RMSD value sufficient. See the primary
[CGenFF 5 paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11938330/) and
[OpenFF Sage paper](https://doi.org/10.1021/acs.jctc.3c00039).

For catastrophic geometry errors, the automated input screen also follows the same class
of checks used by PoseBusters: molecular identity, sanitization, bond geometry, internal
overlaps, and consistency of stereochemistry. These are plausibility checks, not energetic
validation. See the primary [PoseBusters paper](https://doi.org/10.1039/D3SC04185A).

## Automated QM-input authorization

The machine-readable v2.1 policy replaces the former mandatory conformer and cap-viewing
steps with two narrow authorizations:

1. A coupled conformer may enter fixed-coordinate QM only if hashes, atom order, elements,
   graph, all four signed stereocenters, proper-rotation alignment, displacement magnitude,
   graph-bond ratios, and the internal-overlap check all pass. Both signs of the two most
   ring-active modes are retained. An alternating sign assignment gives two training and
   two untouched validation conformers.
2. The cis-syn d(TpT) boundary model may enter QM only if RDKit sanitizes its exact 63-atom,
   charge -1 graph; every cap, glycosidic, phosphodiester, and CPD bond is present with the
   declared order; phosphorus has no artificial stereolabel; the four CPD stereocenters and
   crosslink distances pass; and two independent 1N4E copies agree under a proper rotation
   without reflection.

These artifacts say `simulation_ready: false`, have `gate_effect: none`, and state exactly
which QM work they authorize. They cannot substitute for a complete topology, parameters,
held-out fit performance, or NAMD validation.

The closest precedent for a modified nucleic acid is the CHARMM36 modified-nucleotide
work. It used the same water/dipole and bonded workflow, fit flexible and ring torsions to
PES scans, emphasized the region below 12 kcal/mol, reevaluated torsions after changing
other parameters, and then tested nucleosides and oligonucleotides in aqueous MD against
experiment. One worked example reached water-interaction RMS differences of 0.20 kcal/mol
and 0.10 Å. The authors also show why fitting vacuum QM alone is insufficient: solution
sampling sometimes required further experimental refinement. See
[Xu et al. 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/).

CHARMM36 DNA itself was accepted through ensemble behavior rather than maintenance of one
starting structure, including the DNA backbone BI/BII equilibrium and comparisons to
experimental observables. The TT-CPD workflow therefore needs a final DNA-context layer
after model-compound fitting. See the primary
[CHARMM36 DNA paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/).

## NADOC release gates

1. **Identity and topology.** Stable atom mapping is bijective; atom count and pair charge
   are conserved; the ordered lesion has exactly the intended C5/C6 crosslinks; all
   product atom types, charges, bonds, angles, dihedrals, stereochemical impropers, and
   parameters are present. Any failure is fatal.
2. **QM reference integrity.** The atom-mapped product minimum has no imaginary modes and
   retains the declared stereochemistry. All raw targets, program versions, inputs,
   outputs, and hashes are retained.
3. **Nonbonded fit.** Training and held-out water probes are reported separately. The
   current targets are 0.2 kcal/mol energy RMSE and 0.1 Å distance RMSE, after the standard
   CHARMM scaling/offset. Exact charge constraints must pass. Dipole and ESP residuals
   must be reported; the 0.5 D dipole-component scale is a provisional NADOC optimization
   choice, not a universal published release cutoff.
4. **Bonded fit.** MM minima and the coupled energy/Hessian response must match QM. Fits
   must cover multiple stereochemistry-preserving conformers and keep an independent
   validation partition. A low training error with a rank-deficient or non-identifiable
   parameter basis fails.
5. **Torsions and impropers.** Relaxed scans must reproduce the relevant low-energy PES,
   minima ordering, accessible barriers, and stereochemistry. There is no defensible
   universal torsion-RMSE cutoff; the scan-specific threshold and weighting must be
   declared before fitting and tested on held-out coupled conformers.
6. **PSF/NAMD integration.** psfgen must produce exactly the expected lesion bonds,
   types, charges, and impropers with complete reverse identity mapping and no missing
   parameters. Staged minimization and a real explicit-solvent NAMD smoke at 2 fs must
   retain chirality and have finite energies and forces.
7. **DNA-context validation.** Adjacent intrastrand and antiparallel interstrand placement
   must be tested, followed by matched reactant/product solution simulations. Available
   structural or spectroscopic data should be used as ensemble validation. RCSB 1N4E and
   CCD TTD are structural references, never parameter authority.

No single score substitutes for these layers. A release decision is mechanical wherever
an exact or preregistered quantitative criterion exists. Visual review remains available
for diagnosis and documentation, but is not required to launch evidence generation.

## Unattended decision hierarchy

For weekend/unattended work, NADOC distinguishes three outcomes rather than waiting for a
visual sign-off:

1. **Reject** on identity/hash/graph/chirality failure, an imaginary mode, missing or
   ambiguous parameters, rank deficiency, non-finite energy, an unclassified engine
   diagnostic, severe overlap, or topology mismatch.
2. **Candidate smoke authorized** only after charge constraints and the declared held-out
   nonbonded bounds pass, the bounded response fit is identifiable and selected only from
   training/validation evidence, the workbook is complete, and real psfgen proves the
   atom/type/charge/bond/improper delta. This permits staged minimization and ordinary-mass
   2 fs dynamics on the model compound while keeping `simulation_ready: false`.
3. **Production release** only after MM-vs-QM geometry/energy/vibrational tests and
   explicit-solvent DNA-context validation pass for the required intrastrand and
   interstrand contexts. A short stable trajectory is necessary but not sufficient.

The engine smoke records full logs and hashes plus: atom/charge conservation; exact
crosslink and improper counts; finite energy records; timestep and HMR state; signed
chirality on every saved frame; ranges for crosslink, retained-ring, and glycosidic bond
lengths; and the minimum nonbonded heavy-atom covalent-radius ratio. This replaces a
subjective “looks good” gate for automated progression without pretending that a short
model-compound run establishes transferable solution physics.

The first cis-syn-I candidate additionally exposed why a successful NAMD exit is not the
gate: an algebraically valid earlier fit inverted one stereocenter and was rejected. The
fixed-QM-improper candidate passed both the standard smoke and a separate 100 ps stress
run, but one explicit improper curvature is nearly zero. This does not automatically fail
the candidate because the coupled ring terms retained all signed centers in 5,000/5,000
frames; it does require sensitivity and transferability checks in the remaining MM/QM and
DNA-context stages. NADOC does not assign an invented minimum force constant in place of
those tests.

## Complete-ring correction rule

The first cis-syn-I engine candidate exposed a case that the original missing-term-only
workflow did not cover: generic CGenFF supplied syntactically complete cyclobutane terms,
but the resulting equilibrium definitions and dynamics diverged from CPD-specific QM,
structural, and literature comparisons. A term being present is therefore not evidence
that it is transferable.

For the correction family, all four cyclobutane bonds, all four internal angles, all ring
proper occurrences, and all four ordered stereochemical impropers are treated as one
coupled block. The generic values may be retained as a regularization prior and benchmark
but not silently retained as final values. Promotion is selected by stable atom keys,
requires exact 4/4/4 bond-angle-proper occurrence counts, and fails closed if the graph
changes. Fitting one visibly long crosslink in isolation is prohibited.

Every corrected candidate must carry a unique variant ID and hash-link its immediate
parent, refit policy, parameter workbook, topology, parameter stream, and topology audit.
Candidate NAMD execution remains allowed at ordinary mass and at most 2 fs so competing
corrections can be tested. Such runs have no registry effect and cannot be submitted
through production paths until the MM-versus-QM, nonbonded, explicit-solution, and release
gates in the machine-readable policy all pass.

## 3D review interface

Open **Help → TT-CPD Scientific Review…**. The viewer reads hash-pinned evidence from the
Archive drive and provides orbit, pan, zoom, and reset controls. Magenta cylinders mark
the new inter-base product bonds, gold cylinders mark the two reduced C5–C6 ring bonds,
cyan atoms/labels mark the four audited stereocenters, and a red dashed line marks the
closest nonbonded contact for conformer review.

Approve, Reject, and Revise require a reviewer and a substantive note. Approved conformers
also require a training or validation partition. Decisions are written atomically to
`photoproduct_evidence/tt-cpd-human-visual-review-v1/visual_review_decisions.json` on the
Archive drive, pinned to the source packet, index, and geometry hashes. This overlay has
`gate_effect: none`; **Revise** remains explicitly unresolved, and no button in the viewer
can release a force field or enable NAMD. These decisions are supporting annotations; the
quantitative v2.1 policy is the authoritative automated path.
