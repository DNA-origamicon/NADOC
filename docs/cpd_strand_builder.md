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

## Deliberate extra-base test structures

At the **Base** selection level, select exactly two unused crossover/forced-ligation
extra bases whose sequence is T, then right-click **Convert to CPD…**. The dialog
lists all registered forms and shows a rotatable 3D preview of the available
cis-syn template. Other forms are disabled and labeled **In development**.

Conversion places both complete residues from the hash-verified template and
adds the C5–C5 and C6–C6 bonds in the atomistic view. The coarse view uses fitted
residue poses. A deformed CPD uses the same named Full-view landmarks as native
measured placement: the backbone bead is its actual O5′ coordinate and the base
reference is the centroid of N1/C2/N3/C4/C5/C6. Slab orientation is fitted to those
six ring atoms; dimensions remain standard. The local conformation supplies both
sites before the saved unit transform. Projections are regenerated on load, so
existing CPDs receive the correction without re-minimization.
Conversion, save/load, and undo preserve the pair. Selecting either
base or its crossover makes Move/Rotate act on both residues in one transaction.
A converted endpoint cannot be independently reset or moved away from its partner.

The available template is labeled **Preliminary research template**, reflecting
its actual qualification. Extra-base pairs are test structures; they do not pass
the adjacent-internal-TT NAMD qualification. Conversion does not relax export
checks or assert that the repositioned backbone is equilibrated.

Full representation draws two amber bars between the converted slabs. They follow
live slab movement and respect representation, hiding, and opacity settings.
Conversion runs a bounded local relaxation combining flanking O3′–P bond-length
errors (0.16 nm target) with repulsion from nearby atoms. Fresh conversion and
saved-product relaxation use the same canonical template frame and 24 deterministic
orientation starts. Six sugar/phosphate single-bond torsions allow the attachments
to adjust while preserving the CPD ring, stereochemistry, internal covalent bond
lengths and bond angles. Surrounding residues remain fixed. An analytic Jacobian,
quasi-Newton refinement and a constrained clearance pass improve convergence.
Bonded and 1–3 neighbors are excluded from repulsion; actual emitted atoms are used
without counting phosphate aliases or absent template hydrogens twice. Both paths
also use the same residue projection, so their Full-view slabs agree.

Properties reports bond-length errors, close contacts (below 85% of summed
van der Waals radii), and severe clashes (below 50%). Existing converted CPDs
have a **Relax CPD bonds and clashes** button; its result is one undoable edit.
The old backbone-to-backbone annotation rails are suppressed for converted
products, leaving only the two slab bars in Full representation.

This is geometric relaxation, not force-field equilibration. The saved
`2hb_1xT_CPD` regression now has zero CPD-to-neighbor close contacts (originally
116, including 20 severe; the previous relaxed copy had 10). Attachment-bond RMS
error is 0.179 nm, compared with 0.366 nm in the previous relaxed copy. Significant
attachment strain remains because the surrounding backbone stays fixed; the UI
continues to report it. The constrained pass tolerates at most 0.005 nm additional
internal overlap relative to the template's existing close contacts. The 2HB solve
takes approximately 12 seconds on the development machine.

### Headless reproduction

The fixture `tests/fixtures/cpd_2hb_1xt.nadoc` preserves the original clashing
CPD geometry without depending on the user's workspace or live backend.

```sh
PYTHONPATH=. .venv/bin/python scripts/relax_cpd_design.py \
  tests/fixtures/cpd_2hb_1xt.nadoc --output /tmp/cpd-relaxed.nadoc \
  --report /tmp/cpd-relaxation.json
.venv/bin/python -m pytest tests/test_cpd_design.py tests/test_cpd_steric_relaxation.py -q
npm --prefix frontend test -- src/scene/photoproduct_overlay.test.js src/scene/cpd_slab_bonds.test.js
npm --prefix frontend run test:e2e -- cpd_conversion.spec.js
```

The CLI writes a separate design snapshot and JSON metrics; it requires no GUI,
GPU, or running server. Tests independently measure output clashes, preserve
ring distances/handedness, internal bond lengths/angles and fixed neighbors,
exercise save/load and API undo, verify fresh/saved/repeated coordinate parity,
and verify exactly two Full-view CPD bars in headless Chromium. Browser tests
use isolated test servers rather than the user's active design session.

The **New Positioning** debug toggle defaults ON (candidate); OFF selects the
comparison baseline. Both slots now start from the accepted 2026-09-20 measured
placement. The former legacy viewer mode and its stored preferences have been
retired. CPDs retain their authored conformation and O5′/ring landmarks in both slots. The headless
bead audit explicitly sets and records the mode, checks atomistic requests, and
compares actual rendered beads/slabs directly to atom landmarks:

```sh
CPD_AUDIT_FILES=workspace/2hb_1xT_CPD.nadoc \
  npm --prefix frontend run test:e2e -- cpd_bead_audit.spec.js
CPD_AUDIT_MEASURED=false CPD_AUDIT_FILES=workspace/2hb_1xT_CPD.nadoc \
  npm --prefix frontend run test:e2e -- cpd_bead_audit.spec.js
```
