# Streptavidin coatings: implementation and simulation audit

Updated 2026-09-13. PDB-derived coatings are supported in the design and viewport.
CPU oxDNA/DNANM jobs now support the constrained one-gold/one-tetramer/one-DNA
workflow below. Other coating simulation paths remain guarded.

## Coating construction

Gold creation contains only size and optical references. For gold, open
**Conjugate Manager… → Conjugation scheme → Streptavidin** to apply, change or remove a coating.
Imported QDs retain their **Streptavidin coating…** context-menu entry.
Core diameter stays separate from the protein layer. Resize recomputes packing;
translation/rotation carries all tetramers with the particle, including live
previews. Each operation uses the existing nanoparticle snapshot history, so
undo/redo, deletion and save/load preserve the complete coating.

The default target count is `floor(pi * core_diameter_nm² / 40)`, at least one.
[Biofunctionalization of gold nanoparticles and their spectral properties (2007)](https://doi.org/10.1016/j.mee.2007.01.247)
reported approximately 40 nm² per streptavidin molecule for a monolayer on
citrate-stabilized gold. This is a practical reference, not universal saturation.
Another [adsorption study (2017)](https://www.beilstein-journals.org/bjnano/content/pdf/2190-4286-8-1.pdf)
uses an approximately 25 nm² projected area and estimates roughly 25–30 proteins
on its particles. Users can set 25–100 nm² per tetramer. The implementation
supports 5–100 nm core diameters; these bounds are computational/model scope,
not the validity range of a universal experimental law.

Example default area targets: 10 nm → 7 tetramers, 20 nm → 31, 40 nm → 125.
Fibonacci sites distribute the targets over the sphere. Every protein heavy atom
must clear the core by at least 0.17 nm, and heavy atoms on different tetramers
must remain at least 0.25 nm apart. Rejected sites are omitted; the persisted
actual count can be below the target. No hidden increase in linker length is
used to force a requested count. This is a deterministic geometric packing
estimate, not an adsorption thermodynamics or flexible-linker calculation.
These distance thresholds are implementation clash criteria, not measured
bond lengths. DNA/other particles are not included in this packing check.
Mixed thiol-DNA and streptavidin surface layers are rejected until their shared
surface occupancy is modeled.

## PDB and attachment orientation

The bundled file is [PDB 1STP biological assembly 1](https://www.rcsb.org/structure/1STP),
downloaded from `https://files.rcsb.org/download/1STP.pdb1`; its SHA-256 is stored
with the imported asset. This is the experimentally determined tetramer, not
four independently placed monomers. The assembly file contains four MODEL blocks;
they are deliberately flattened and renamed A–D before the normal PDB parser,
which ordinarily reads only the first model. It yields 484 Cα atoms and 3,604
protein heavy atoms. The viewport instances the four actual PDB backbone traces;
the full heavy-atom structure and inferred bonds are persisted once per coating.
Coordinates convert Å to nm and are centered without changing internal geometry.

- **Adsorption:** seeded isotropic rigid-body orientations are moved into surface
  contact with a default 0.3 nm geometric gap, plus heavy-atom clearance. There
  is no experimentally unique adsorption orientation. The model makes no claim
  that a particular amino acid forms a covalent gold bond.
- **Biotin tether:** one crystallographic biotin is retained in chain A; the other
  three are removed. The C10→C11 carboxyl-tail direction points toward the core,
  with C11 at `core radius + spacer`. Rotation around that radial axis is sampled.
  Default spacer is 4 nm to provide clearance for the imported rigid structure;
  users can change it and impossible placements are rejected. The occupied
  binding pocket is accounted for structurally; the remaining pockets are not
  automatically declared sterically accessible. Linker atoms and bonding to the
  core are **not** synthesized.

Both modes use the crystallographic holo protein conformation. Removing biotin
does not simulate apo relaxation. Missing residues, terminal chemistry, protonation,
hydrogens and linker conformations are not repaired by the import.

For QDs, this creates a **custom geometric coating** using the gold-derived
footprint estimate. It does not claim a measured vendor loading or reconstruct
proprietary polymer/coating chemistry. Existing vendor-functionalized Qdot presets
remain deferred because their reported diameter includes polymer/protein and
cannot simply be reused as an uncoated core plus another protein layer.
Uncoated-core optical references remain labeled as such. Gold-quenching curves
are not silently reused for streptavidin-coated gold.

## Minimal gold–streptavidin–DNA workflow

Create a gold sphere, then open **Conjugate Manager → Conjugation scheme → Streptavidin**, override
count to **1**, and apply. Reopen the manager and use **Biotinylated DNA** to
enter 2–200 bases, choose a pocket (or the most outward core-clear pocket), and
set linker reach. Attach DNA, then create an **oxDNA CPU** job. The attachment
has feature history, undo/redo, save/load and deletion; moving or rotating gold
carries both the protein and DNA. Remove the DNA before changing coating or size.

The model is explicitly **fixed-core**, with prescribed attachment mechanics:

- The full 1STP tetramer becomes 484 Cα DNANM beads with ANM springs. Gold is
  an external exclusion body, not a mobile bead or an atomistic gold lattice.
- The installed CPU `repulsive_sphere_moving` force with zero rate acts on all
  beads in every stage. Its parameter radius is core radius minus 0.8 nm;
  the upstream 4–2 repulsive shell starts approximately 0.4 nm outside the
  nominal core. Stiffness is 10 in engine units. This is a finite repulsive
  barrier at the nominal surface, not an exact hard-wall constraint.
- Three separated contact-side Cα beads receive positional traps (stiffness
  10) to preserve the prescribed coating orientation with elastic fluctuations.
- A symmetric harmonic tether (stiffness 1.424 in engine units) joins the DNA
  5′ bead to the Cα nearest the selected pocket's crystallographic biotin tail.
  Its equilibrium distance comes from the initial geometry, including the
  requested linker reach. Biotin/linker atoms are not separate simulated beads.
- Pocket A is unavailable when occupied by the gold-facing biotin tether.
  Automatic selection screens a straight linker path against the gold core;
  it does not certify protein clearance or equilibrium binding accessibility.
- The ssDNA simulation seed is extended with legal oxDNA backbone spacing.
  CPU MD timesteps are capped at 0.0001. Gold remains in the absolute reference
  frame; trajectory display fits the PDB coating to simulated protein beads.

`nanoparticles.json` records core identity, pose, size, protein identity and DNA
attachments. Build/run guards require CPU DNANM and core forces; unsupported
mixed nanoparticle models and surface simulations are rejected. The audit API
reports this subset as `oxdna_fixed_core_ready`; generic `simulation_ready`
remains false because other engines cannot include it.

Validation includes a real installed-engine run through MC, MD relaxation and
equilibration, with all 500 beads (484 protein + 16 DNA) finite and outside the
nominal 10 nm core, plus API history/movement and browser creation/undo/redo tests.
These short smoke runs validate inclusion and execution, not long-time stability
or quantitative binding predictions. The trap constants and core shell are
model choices requiring calibration. Mobile gold, multiple coating tetramers,
CUDA/live oxpy and adsorption/binding thermodynamics remain future work.

## Engine audit

| Engine / path | Existing support found in code | Missing for a physically included coating |
|---|---|---|
| NAMD explicit, GBIS and vacuum | `namd_topology.py` supports ordinary protein-attachment segments and CHARMM aliases; `protein_enm.py` supplies protein restraints. `nanoparticle_atomistic.py` supports direct C3 thiol-DNA linkers on an implicit fixed gold sphere, not Au atoms or explicit Au–S bonds. | Expand coating instances into independent chain/segment identities; prepare protein termini/missing atoms; parameterize retained biotin and the actual linker; implement protein/core exclusion and adsorption or tether forces. Generalize the existing fixed-gold model instead of assuming the DNA thiol restraint attaches streptavidin. QD core interactions are separate missing physics. |
| OpenMM implicit + verification checker | `openmm_implicit.py` builds a DNA-only topology with `build_atomistic_model(design)`; `checkers/openmm_checker.py` verifies DNA with Amber14/OL15/GBNeck2. | Protein and ligand topology, compatible force-field/solvation parameters, core interactions and attachment constraints. Protein import alone does not add them to the system. |
| oxDNA, DNANM, live oxpy (see supported subset above) | `oxdna_protein.py` maps existing `Design.protein_attachments` into Cα beads/ANM springs with protein-first indexing and DNA tethers or centroid traps. | Coating-instance expansion and stable bead identity; tetramer inter-chain mechanics; core excluded volume/mass; protein-to-core anchors in the particle frame. A centroid trap in world coordinates is not a mobile nanoparticle attachment. |
| mrDNA / ARBD | `mrdna_bridge.py` and its manifest/field/surface modules operate on the DNA multiresolution bead model. | Rigid protein/core bodies, interaction and attachment terms, hydrodynamics, stable identity through resolution changes, and coated trajectories. |
| CanDo | DNA elastic/FEM prediction through `routes_cando.py` and `cando_runner.py`. | Protein/core mechanical bodies and contact constraints; mass/drag and attachment coupling if dynamical effects are modeled. Cannot provide atomistic binding chemistry. |
| SNUPI | DNA mechanical and hydrodynamic models under `physics/snupi_*`. | Coating geometry in contact mechanics, coupled rigid bodies/tethers and appropriate core/protein drag. |
| Local geometric/linker relaxation | DNA and connection-specific geometry optimizers. | Coating excluded volume and coupled attachment motion. These remain local DNA-only geometric tools, not coated-system simulations. |
| Assembly projection | `assembly_flatten.py` projected DNA and omitted nanoparticle coatings. | Namespace and transform core/coating instances into the flattened design; current flattening refuses a coated part instead of dropping it. |

## Safeguards implemented

`require_coating_simulation_support()` rejects coated-system NAMD package/protocol
and CHARMM topology builds, OpenMM implicit and verification builds, oxDNA topology
and unsupported DNANM protein builds, and live oxpy engine preparation. The fixed-core CPU/GPU job subset above passes the DNANM guard. The CanDo, SNUPI and
mrDNA job-creation APIs reject coated designs. Assembly flattening refuses coated
parts. This is an explicit unsupported-physics condition, not a claim that a
successful DNA-only job included the coating. Existing jobs retain their frozen
snapshots; adding/moving/removing a coating changes the shared build fingerprint,
while visibility and protein display-name changes do not. Uncoated fingerprints
retain their previous hash projection.

`GET /api/design/nanoparticles/coating-simulation-audit` reports particle/tetramer
counts, readiness and per-engine gaps. Local geometry tools and historical jobs
are not converted into full-system coating simulations by these guards.

## Work needed before enabling simulations

1. Define the intended physical preparation: core composition, surface treatment,
   attachment chemistry/site, linker composition, loading and solvent. Select
   fixed-core versus mobile-core dynamics explicitly.
2. Expand saved instances into ordinary protein/ligand topology without merging
   residue/chain identities. Repair missing atoms and termini, assign protonation
   and validate tetramer/biotin interactions.
3. Implement core excluded volume and attachment forces for each engine. Adsorption
   requires a validated interaction potential; a geometric touching pose is not
   an adsorption energy. Biotin-tether chemistry requires the real linker.
4. Extend particle/atom manifests, trajectories, alignment, restraints, force
   indexing, serialization and assembly projection to include all coating bodies.
5. Validate one tetramer, then a complete coating: atom/bead census, charge,
   force/energy checks, no core penetration, preserved tetramer and biotin pocket,
   stable tethering under motion, timestep/energy stability and loading-dependent
   mechanics. Compare to experimental coverage and binding accessibility. Only
   remove the engine guard once that engine passes these checks.

## Follow-up literature assessment

The [simulation and packing literature check](streptavidin_literature.md) found a
direct Martini/GROMACS coated-sphere precedent and distinguishes its sparse
loading assumption from denser experimental estimates. It documents limitations
of the current footprint range, uniform spacing and geometric tether default.

## Publication presets and count overrides

The manager offers three cited targets from the shared
`backend/data/proteins/streptavidin_coverage.json`: 2007 effective area 40 nm²,
2019 sparse simulation effective area 50 nm² (25 nm² at 50% occupancy), and
2017 optical estimate 30 tetramers per 14.1 nm core, area-scaled at other sizes.
The latter is an explicitly labeled extrapolation. Selecting a publication resets
the number box to its estimate; editing the number sets a count override (1–1500).
Use publication estimate clears the override. Resize recalculates publication
targets but preserves explicit counts. Clash checks may reduce actual loading.
Publication, source and override are persisted and participate in snapshot history.
The legacy footprint remains available for old designs/API callers; publication
presets use their own effective areas, including the dense estimate below 25 nm².
Coverage references do not establish attachment chemistry: the attachment selector
remains separate, and the 2019 preset reproduces loading, not its amino-group bonds.

## Physics v3 integration (2026-09-14)

GPU is now the explicitly requested default for supported fixed-core gold/strep/DNA
MD stages; MC remains CPU. The minimum build includes current-energy Bussi handling,
point-rotation masking, and the CUDA zero-vector guard. The fixed core, exclusion,
attachment forces, and 0.0001 timestep ceiling persist on both backends.

This default does not certify CPU/GPU ensemble equivalence. Further convergence,
sampling and useful-sample performance checks remain TD-OXDNA-PHYSICS. Protein–DNA
contact amplitudes remain unchanged pending model validation. The original strep
on nanoparticles system also needs full NAMD validation (TD-STREP-NAMD), including
force-field completeness, attachment/linker physics, stability, and accessibility.
