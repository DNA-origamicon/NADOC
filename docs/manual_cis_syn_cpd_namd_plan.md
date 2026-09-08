# Manual cis-syn TT-CPD conversion for NAMD

## Goal

Let a user select exactly two thymine nucleotides in NADOC, explicitly mark them as a
formed cis-syn cyclobutane thymine dimer (TT-CPD), and prepare a chemically complete,
stable NAMD system containing that product. This is the product-state arm needed to ask
how much stability comes from an actual interstrand photoproduct rather than from the
presence of unreacted extra thymines.

This work is intentionally limited to a manual, pre-simulation conversion. Automatic
reaction detection, KIMMDY-triggered conversion during a trajectory, reactive dynamics,
and kinetic/quantum-yield predictions are later work.

## Scientific and implementation contract

A TT-CPD is not two distance restraints. It is a changed covalent molecule. The product
retains each thymine's C5-C6 bond and adds the two cross-residue bonds C5(1)-C5(2) and
C6(1)-C6(2), forming the cyclobutane ring. C5 and C6 also change from the reactant's
sp2-like environment to a product-specific sp3-like environment. Consequently, a valid
implementation must provide the complete product topology: atom types, partial charges,
bonds, angles, dihedrals, impropers/chirality, and every corresponding parameter.

NAMD `extraBonds` may be useful for temporary steering or restraints during coordinate
preparation, but it is not the product topology and must never be presented or exported
as the final CPD model.

The reaction does not add or delete atoms and should not change the total charge of the
two-residue system. The two selected residues remain thymine-derived nucleotides in the
design sequence, with an additional lesion annotation.

## Scope

### In scope

- Select any two individually addressable thymine nucleotides, including ordinary bases,
  loop copies, strand extensions, and crossover-extra bases.
- Allow both interstrand and intrastrand products. Show the relationship prominently so
  the interstrand Dietz-style products cannot be confused with conventional adjacent
  intrastrand CPDs.
- Persist an ordered, unambiguous lesion identity in `.nadoc` and preserve current
  scadnano-CPD compatibility.
- Preview and delete the product through a normal, undoable feature-log operation.
- Materialize product coordinates and a validated CHARMM-compatible topology during
  production-grade NAMD preparation.
- Package every required topology/parameter file and reference it in every generated NAMD
  configuration that supports CPD designs.
- Produce machine-readable provenance and topology/geometry audits with the job.
- Start CPD simulations conservatively at a 2 fs time step. A 4 fs HMR path is a separate
  validation target, not an assumption.

### Out of scope

- Automatic conversion while NAMD is running.
- KIMMDY/KMC reaction selection or dynamic topology changes.
- Inferring a CPD merely because two bases satisfy a geometric gate.
- UV dose, reaction rate, or absolute yield prediction.
- 6-4 photoproducts, Dewar products, cytosine-containing CPDs, or cis-anti/trans isomers.
- Treating a restraint-only model as a formed photoproduct.
- Automatically forming every annotated/imported candidate.

## Existing NADOC foundations

Use these rather than creating competing identities or topology paths:

- `backend/core/models.py` has a dormant `PhotoproductJunction` and
  `Design.photoproduct_junctions`.
- `backend/core/scadnano.py` round-trips the legacy scadnano-CPD fields
  `t1_stable_id`, `t2_stable_id`, and `photoproduct_id`.
- `frontend/src/scene/base_ref.js` defines the canonical nucleotide keys:
  `helix:bp:direction[:copy]` and `__xb__:crossover_id:k`.
- `frontend/src/scene/selection_manager.js` already supports multi-base selection and
  exposes `getSelectedBaseKeys()`.
- `backend/core/atomistic.py` carries `crossover_id`, `extra_base_k`, and `copy_k` on atom
  provenance.
- `backend/core/atomistic_to_nadoc.py` already emits matching `base_key` identities.
- `backend/core/namd_topology.py::build_charmm_psfgen_topology` is the authoritative
  all-hydrogen CHARMM/psfgen topology path. It already solves the design-strand to
  `segid:resid` mapping problem, including designs with more than 26 strands.
- `backend/core/cpd_metrics.py` and `frontend/src/scene/cpd_geometry.js` define the existing
  reactant-state C5/C6 geometry and should remain analysis-only.

The current local force-field bundle contains standard CHARMM36 nucleic-acid, water/ion,
and optional protein files, but no CPD topology or parameter file. The dormant
`PhotoproductJunction` is not rendered and is not consumed by NAMD preparation. The
CPD-ready comment in `backend/core/pdb_export.py` describes only optional bond records;
that legacy export is not chemically sufficient for this feature.

## Non-negotiable gate: validated CPD parameters

The first implementation milestone is a short parameter-provenance spike. Do not invent
missing values, copy a few bond constants from an unrelated force field, or mix an AMBER
lesion residue with CHARMM36.

A parameter set is acceptable only when all of the following are established:

1. It describes the cis-syn thymine CPD with the intended C5-C5/C6-C6 connectivity and
   stereochemistry.
2. It is demonstrably compatible with the additive CHARMM nucleic-acid force field used
   by NADOC, or it has been reparameterized and validated for that context.
3. It defines all changed charges/types and all bond, angle, dihedral, improper, and
   nonbonded terms introduced by the lesion.
4. Its source, version, license, derivation, and validation evidence can be shipped or
   reproducibly obtained.
5. A minimal psfgen plus NAMD parameter-parse test has no guessed or missing terms.

Record the decision in `docs/cpd_forcefield_provenance.md` and add a machine-readable
manifest beside the force-field files. If no defensible parameter set is available, it is
acceptable to finish the design/UI plumbing behind a clear `parameters unavailable`
capability gate, but NAMD preparation must fail closed. It is not acceptable to silently
fall back to ordinary thymine plus two bonds.

Useful structural references for validating connectivity and stereochemistry are the
cis-syn CPD DNA crystal structure [RCSB 1N4E](https://www.rcsb.org/structure/1N4E), its
[primary publication](https://pmc.ncbi.nlm.nih.gov/articles/PMC138548/), and the RCSB
[TTD chemical-component definition](https://www.rcsb.org/ligand/TTD). The official
[MacKerell CHARMM force-field distribution](https://mackerell.umaryland.edu/charmm_ff.shtml)
is the authority for the base force-field version. A crystal structure is a geometry
reference, not by itself a force-field parameter source.

## Target architecture

Keep the three layers explicit:

1. **Design intent**: the selected nucleotide pair, product type, stereochemistry, and
   manual provenance are stored in `Design.photoproduct_junctions`.
2. **Atomistic product geometry**: an atomistic builder converts only the affected local
   coordinates to a valid cis-syn product seed while retaining stable base identities.
3. **Simulation topology**: psfgen resolves the two residues and applies a real CPD patch;
   NAMD reads the matching parameter file.

The design model should not store NAMD atom indices, PSF serials, or transient residue
numbers. Those are package-derived values and belong in package metadata.

## Phase 1: lesion identity and migration

Extend, rather than replace, `PhotoproductJunction`.

The target logical fields are:

- `id`: stable feature UUID.
- `base_key_1`, `base_key_2`: ordered canonical NADOC base keys.
- `product`: initially only `TT-CPD`.
- `stereochemistry`: initially only `cis-syn`.
- `formation`: initially only `manual`.
- `patch_order` or an equivalent explicit orientation value identifying which selected
  endpoint maps to patch residue 1 versus residue 2.
- optional legacy scadnano stable IDs for lossless import/export.

The exact Pydantic representation may use endpoint objects if that makes migration
cleaner, but newly created features must always contain canonical base keys. A legacy
record that cannot be resolved must remain losslessly readable, be labelled unresolved,
and be rejected by NAMD preparation with a specific error.

Implement one pure backend base-key parser/resolver whose grammar mirrors
`frontend/src/scene/base_ref.js`. It must resolve a key to:

- design ownership and current base letter;
- strand/domain/crossover/extension identity;
- atomistic residue provenance;
- whether the base is ordinary, a loop copy, an extension, or a crossover insert.

Do not parse keys with naive left-to-right `split(':')`; IDs can contain colons. Add
shared JSON fixtures so the JavaScript and Python parsers are tested against the same
normal, loop-copy, extension, linker, and `__xb__` cases.

Validation rules for a new lesion:

- exactly two distinct, resolvable bases;
- both are T at commit time;
- neither endpoint is already consumed by another CPD;
- both provide the required C5 and C6 atoms in the production atomistic model;
- the selected pair can be assigned to a supported cis-syn orientation;
- relationship metadata (same/different strand, adjacent/nonadjacent, extra/native) is
  derived and returned, not trusted from the client.

Canonical sorting alone is not enough for patch order because improper signs and template
assignment can be directional. Evaluate the two endpoint-to-template assignments against
the current local geometry, choose deterministically, and persist the choice. Resolve exact
ties by canonical key order.

Define dependency behavior. Editing an endpoint from T to another base, deleting its
owner, deleting a crossover that owns an extra base, or shortening an insert must either
remove the lesion in the same undoable operation with a warning or reject the edit. No
stale product may reach NAMD prep.

## Phase 2: backend mutation API

Add a focused router such as `backend/api/routes_photoproducts.py` and mount it from
`backend/api/main.py`.

Suggested contract:

- `POST /api/design/photoproducts/preflight` with two base keys. This is read-only and
  returns eligibility, resolved identities, relationship, current C5/C6 geometry,
  selected patch/template orientation, and actionable warnings/errors.
- `POST /api/design/photoproducts` with the two keys and `stereochemistry="cis-syn"`.
  Re-run every validation server-side and commit one snapshot feature-log operation.
- `DELETE /api/design/photoproducts/{id}`. Remove one lesion through the feature log.

Use `backend.api.state.mutate_with_feature_log`; do not mutate global state directly.
Return normal design validation and the smallest correct render update. Concurrent or
stale client requests must not bypass the T/identity checks.

## Phase 3: manual user workflow and rendering

Add the action to the selected-bases area of `frontend/src/ui/properties_panel.js`, or a
small dedicated component called from it.

User workflow:

1. Switch to base selection and select two bases.
2. See each base's key, base letter, source class, and strand/crossover context.
3. Press **Form cis-syn TT-CPD**.
4. Review a compact preflight summary: interstrand/intrastrand, extra/native pairing,
   C5/C6 distances and orientation, and warnings.
5. Confirm once. The feature is persisted, rendered, and undoable.

The action is disabled with a visible reason unless exactly two eligible T bases are
selected. Geometry outside a configurable preparation envelope should be an explicit
preflight failure, not silently forced into a highly strained product. Do not reuse the
KIMMDY structural gate as a stability verdict; it is only one product-placement input.

Rendering requirements:

- In the coarse design view, show one unmistakable product glyph/double-rail connector
  between the two bases and make it selectable.
- In the atomistic product view, draw the actual C5-C5 and C6-C6 bonds from atom
  identities, not from base centers.
- Distinguish a formed product from the existing photoproduct-*propensity* colormap.
- Show product type, endpoint keys, extra/native status, and a remove action in the
  properties panel.
- Save/reload, undo/redo, feature-log seek, deletion, and partial render diffs must all
  preserve the marker.

## Phase 4: product coordinate construction

Create a dedicated pure/core module, for example `backend/core/cpd_product.py`. Its inputs
are the design, atomistic model, lesion endpoints, and parameter/template manifest. Its
output is a new atomistic model plus a detailed placement report. Never mutate a cached
reactant model in place.

Use a versioned cis-syn reference geometry derived from an authoritative structure such
as 1N4E/TTD, with a script that records exactly how the local template was extracted. Do
not vendor an unexplained coordinate blob.

For each lesion:

1. Resolve both full atomistic residues from their base keys.
2. Evaluate supported endpoint/template assignments without reflection.
3. Fit or optimize the two base moieties toward the product template while preserving the
   two glycosidic C1'-N1 connections and minimally disturbing sugar/phosphate atoms.
4. Enforce the parameter set's C5-C5 and C6-C6 equilibrium region and the intended
   cis-syn improper signs.
5. Locally minimize the affected bases plus a small configurable neighbor shell while
   restraining the rest of the structure.
6. Reject placement when required movement, residual bond/angle strain, steric clash, or
   ring/backbone piercing exceeds documented limits.

The algorithm may use a constrained least-squares/local energy solve. It must not merely
translate two carbons onto one another or mirror a template to make it fit. Test both
intrastrand and antiparallel interstrand examples because a template extracted from an
ordinary adjacent dinucleotide cannot be assumed to map correctly across two strands.

The placement report should include endpoint keys, template/parameter versions, selected
assignment, before/after C5-C5 and C6-C6 distances, relevant improper signs, maximum atom
displacement, local clashes, and pass/fail reasons.

## Phase 5: psfgen and NAMD topology

Extend `backend/core/namd_topology.py` so the authoritative builder can accept the CPD-aware
atomistic model and lesion list.

For each lesion:

1. Resolve its two base keys to the generated psfgen `segid:resid` values by atomistic
   provenance and residue ordinal. Do not reconstruct residue numbers independently from
   domain lengths.
2. Load the validated CPD topology/patch file in addition to `top_all36_na.rtf`.
3. After segments and coordinates exist, apply an ordered patch such as
   `patch <validated-name> SEG1:RES1 SEG2:RES2`.
4. Regenerate angles and dihedrals, guess only genuinely missing coordinates, and write
   the PSF/PDB.
5. Audit the resulting product before solvation.

The audit must prove:

- the same atom count as the corresponding reactant model;
- exactly one C5-C5 and one C6-C6 cross-residue bond per lesion;
- both original intrabase C5-C6 bonds remain;
- no duplicate product bonds and no endpoint appears in two products;
- product atom types and charges match the manifest;
- pair charge is conserved relative to two precursor thymine residues;
- all expected angles/dihedrals/impropers exist;
- all endpoint base keys map back from the product PSF/PDB;
- psfgen reported no guessed product heavy atoms or topology warnings.

Store this under `charge_audit.json` or a sibling `cpd_topology_audit.json`. Include the
exact `segid:resid` mapping, force-field hashes, patch command, topology builder version,
and placement report.

## Phase 6: force-field and package propagation

The repository currently duplicates force-field file lists and NAMD `parameters` stanzas.
Introduce a small shared manifest/helper for required topology and parameter assets, then
use it from all supported CPD paths. At minimum inspect and update:

- `backend/core/namd_topology.py`
- `backend/core/namd_solvate.py`
- `backend/core/namd_vacuum.py`
- `backend/core/namd_gbis.py`
- `backend/core/md_protocols.py`
- `backend/core/namd_package.py`
- `backend/core/periodic_cell.py`
- `backend/core/md_precondition.py`
- `backend/api/routes_md.py`

The first supported target should be the equilibrium-aware, full-psfgen explicit-solvent
NAMD path used for scientific production. GBIS and vacuum may follow through the shared
builder, but they must either include the same complete parameter set or reject CPD
designs. Legacy stub-PSF/export paths must reject products until upgraded.

Every NAMD stage—minimization, equilibration, reseed, continuation, and production—must
read the CPD parameter file. Child ensemble packages must inherit it. Remote/cluster and
downloaded packages must ship the same bytes. Record SHA-256 hashes in job metadata.

Use 2 fs and ordinary conservative integration defaults initially. Explicitly disable a
CPD job's 4 fs/HMR option until product-specific HMR and stability tests pass. Ensure any
heavy-residue logic for crossover inserts does not overwrite product atom masses or types.

## Phase 7: staged relaxation and simulation preflight

A covalent product seed needs more than a successful topology parse. Add a CPD-specific
preflight protocol before general equilibration:

1. Zero-step NAMD load/energy evaluation to prove parameter completeness.
2. Short minimization with the environment strongly restrained and the local product
   region mobile.
3. Staged release of the local shell and then the broader DNA restraints.
4. Short restrained NVT, then the normal production protocol's solvent/pressure stages.

Abort on NaN energy, constraint failure, missing parameters, excessive initial product
bond/angle energy, broken glycosidic/backbone bonds, loss of the two cross bonds, or an
invalid stereochemical improper. Save before/after local structures and energy summaries
for inspection.

The product bonds must be present in the PSF throughout; steering restraints, if used
during the local placement stage, must be separately named and absent from the final free
production stage.

## Phase 8: tests

### Unit and model tests

- Python/JavaScript shared base-key grammar, including IDs containing colons.
- Model migration and `.nadoc` save/reload for new and legacy photoproduct records.
- scadnano import/export remains lossless.
- Eligibility: wrong selection count, duplicate endpoint, non-T, stale key, already-used
  endpoint, absent C5/C6, and supported normal/loop/extension/extra cases.
- Deterministic patch orientation under reversed UI selection order.
- Dependency behavior when sequences, strands, extensions, loop copies, or crossovers
  change.
- Product coordinate placement and chirality against versioned reference fixtures.

### API and frontend tests

- Preflight is read-only; create/delete are one feature-log entry each.
- Server rejects a stale client request even if the button had been enabled.
- Properties action enables only for two eligible Ts and reports why otherwise.
- Form, display, save/reload, undo/redo, feature seek, and delete a lesion.
- Coarse and atomistic renderers distinguish product from propensity.

### Topology and package tests

- psfgen script snapshot contains the topology load and one ordered patch per lesion.
- Real psfgen integration test verifies C5-C5/C6-C6 bonds, atom types, charges, bonded
  terms, atom count, segment-safe mapping, and no warnings.
- Fixtures include ordinary adjacent intrastrand T-T, antiparallel interstrand extra-extra,
  extra-native, loop-copy, and a design with more than 26 strands.
- Every supported package contains the CPD assets; every NAMD config references them.
- Every unsupported exporter fails with a clear message rather than emitting reactant
  thymine topology.
- Solvation/ionization preserves charge neutrality.
- HMR cannot be selected for CPD jobs until explicitly qualified.

### Real NAMD smoke and scientific sanity tests

- NAMD zero-step parameter load succeeds with no missing terms.
- Restrained minimization and a short 2 fs run have finite energies and stable product
  topology.
- Both new bonds remain near their parameter-set equilibrium distributions.
- Glycosidic and neighboring backbone bonds remain intact.
- Product chirality matches the cis-syn reference after relaxation.
- A matched reactant control goes through the same preparation stages without the patch,
  enabling later paired stability comparisons.

Mark real psfgen/NAMD tests as slow and skip only when the executable is genuinely absent;
do not replace the only chemistry validation with mocks.

## Acceptance criteria

The feature is complete only when all of the following are true:

1. A user can select two resolvable T bases and manually create/remove one cis-syn TT-CPD.
2. The lesion survives save/reload and normal undo/redo/feature-log behavior.
3. Ordinary and crossover-extra bases map unambiguously into the generated PSF.
4. The generated PSF contains the two real cross-residue covalent bonds plus complete,
   provenance-backed product parameters—not only restraints.
5. Product coordinates pass documented geometry, chirality, clash, and topology audits.
6. A packaged full-topology explicit-solvent job loads and runs a real short NAMD 2 fs
   smoke test with finite energies and no missing parameters.
7. All generated stages and continuations carry the CPD parameter file, and unsupported
   paths fail closed.
8. The package records enough identity and force-field provenance to reproduce and audit
   the product.
9. Automatic in-trajectory conversion remains unimplemented and clearly identified as
   future work.

## Recommended implementation order

1. Baseline tests and CPD parameter-provenance gate.
2. Shared base-key resolver and `PhotoproductJunction` migration.
3. Backend preflight/create/delete operations and dependency handling.
4. Properties-panel action, confirmation, and product rendering.
5. Product coordinate/template builder with independent geometry tests.
6. psfgen patching, topology audit, and a minimal real NAMD test.
7. Shared force-field propagation through explicit-solvent packages and all stages.
8. GBIS/vacuum/legacy-path capability decisions and fail-closed guards.
9. End-to-end test, documentation, and a matched reactant/product scientific smoke pair.

Do not begin automatic NAMD-time conversion as part of this plan. The output of this work
is a trustworthy manually authored product state that can later become the target topology
for an automatic reaction workflow.

## Efficient post-QM trigger

The primary 0xT/1xT/2xT question now has a bounded unattended continuation in
`scripts/run_post_qm_efficient_sequence.py`. A user-systemd path unit watches for the
passed remaining-isomer QM queue receipt. It then:

1. reruns the stored matched trajectories with `all-tt` and `pair_scope=all`, retaining
   both interstrand opportunity and competing intrastrand opportunity;
2. writes an Archive-backed stable-base-key shortlist separated into intended
   interstrand weld, other interstrand, and intrastrand extra/native classes; and
3. preregisters a small 24hb 0xT/1xT/2xT pilot matrix (three 20 ns replicas at 2 fs),
   with extension toward 250 ns conditional on pilot discrimination.

This trigger does not reinterpret the KIMMDY score as yield or stability and does not
choose a stereoisomer from the current two-coordinate metric. Product arms remain
fail-closed until isomer-resolved accessibility assigns a supported form and that form has
released, hash-verified topology, parameters, placement, and NAMD capability. A timer
rechecks those gates every 30 minutes, so the sequence can resume as later assets become
available. All analysis, shortlist, pilot-plan, status, and log files are written under
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-efficient-sequence-v1`.

## 2026-09 literature-correction addendum

The broader active goal now includes all eight ordered DNA-level TT-CPD forms and a
reusable future-photoproduct workflow.  For cis-syn-I, the first runnable candidate is a
retained diagnostic baseline, not the starting point for release.  Its generic CGenFF
cyclobutane transfer differs materially from the CPD-specific Ma/van der Vaart comparison:
the generic internal-angle equilibrium is 106 degrees rather than about 90 degrees, and
the 100 ps model-compound trajectory has a long/asymmetric C6-C6 distribution even though
C5-C5 agrees well with 1N4E.

The correction sequence is therefore part of the goal and precedes production release:

1. Preserve the current candidate and every audit by hash as a baseline variant.
2. Promote all four ring bonds, all four internal ring angles, and all ring proper terms
   out of the generic-transfer set and refit them jointly with the four ordered
   stereochemical impropers against the existing MP2 minimum and coupled displaced
   conformer forces/Hessians.  Do not tune C6-C6 alone.
3. Re-minimize every training and held-out conformer in MM and compare the full ring,
   low-frequency response, heavy-atom RMSD, relative energies, and signed chirality with
   QM under the preregistered acceptance policy.
4. Revalidate the charge model, emphasizing N3, C5, and C6, against held-out water,
   dipole, and ESP evidence.  Pair charge and atom count remain exact hard gates.
5. Treat the published Ma/van der Vaart tables as an independent benchmark variant only.
   Missing original topology information may not be invented, and the published terms
   may not be redistributed beyond their license.
6. Run every corrected candidate through real psfgen, a product-versus-reactant PSF
   audit, zero-step NAMD load, staged minimization, and ordinary-mass 2 fs dynamics.
   Candidate execution is allowed only in the parameterization/validation workflow and
   never bypasses the production registry.
7. Compare at least three explicit-solvent replicas each for adjacent intrastrand and
   antiparallel interstrand DNA against matched reactant controls.  Evaluate local
   hydrogen bonding, stacking, opening asymmetry, pucker, backbone BI/BII state, bend,
   unwind, grooves, and topology integrity before release.
8. Apply the same per-product validation to the remaining ordered forms.  Share a fitted
   block only after atom-mapped equivalence or a joint multi-isomer fit passes.

The machine-readable policies are
`backend/data/forcefield/photoproduct_parameter_acceptance.json` version 2.1.0 and
`backend/data/forcefield/photoproduct_bonded_refit_policy.json` version 1.0.0.  Corrected
candidate manifests carry a stable variant ID, parent-manifest hash, correction-policy
hash, workbook hash, and topology/parameter hashes.  This preserves the ability to run
and compare variants in NAMD while the normal NADOC production path remains fail closed.
