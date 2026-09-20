# Preliminary cis-syn CPDs in the strand builder

The **cis-syn v6 additive** model is available for preliminary explicit-solvent
NAMD research. Full force-field release gates remain pending; this does not
qualify Drude, other stereoisomers, or quantitative lesion-opening populations.

Open [the example duplex](examples/cpd_preliminary_duplex.nadoc), or select two
adjacent internal thymidines on one strand and choose **Form cis-syn TT-CPD** in
the properties panel. The preflight reports placement and research qualification.
Nonadjacent, terminal and interstrand lesions remain unsupported for this model.

Use the explicit-solvent NAMD workflow. It uses full psfgen topology, ordinary
masses and at most 2 fs. The standalone Python entry point is
`build_namd_solvated_package(design, require_full_topology=True, box_mode="rotation")`.
Legacy heavy-atom PDB/PSF, vacuum and GBIS exporters still reject formed products.
The normal design view marks product intent; the placed product coordinates and
complete chemical topology are in the NAMD package.

Every package contains frozen topology/parameters, placement and static topology
audits, a preliminary review, and benchmark evidence with hashes. Asset files
live in the repository; package creation does not require the development archive.
The patch replaces both lesion residues with the tested CPD-specific atom types,
inherits CUFIX pair corrections, and removes the two reactant planar C5 impropers.
Carbonyl impropers are retained, matching the validated v6 fixtures.

A builder-generated 12-bp duplex (40,061 solvated atoms) passed 1,000 native NAMD
minimization steps and 1,000 dynamics steps at 2 fs. All 10 saved dynamics frames
retained all four CPD stereocenters and both crosslinks; energies were finite.
This verifies integration and startup, not equilibrium convergence. The earlier
34-ns matched benchmark remains the stability evidence. Inspect each new design's
startup and subsequent trajectory before interpreting results.
