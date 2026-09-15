# Gold interfaces: scientific selection and integration review

2026-09-14. **The user selected the neutral INTERFACE baseline. Shared preparation,
native execution and managed qualification jobs are implemented; physical
qualification remains incomplete.** Numerical results and retained failures are in
[the validation report](../workspace/gold_validation_20260914/RESULTS.md).
Existing screening evidence and DNA topology are preserved. No frontend code changed.

## Recommendation and decision

Start with **neutral nonpolarizable INTERFACE 12–6 gold**, retaining NADOC's
CHARMM-modified TIP3P/CUFIX electrolyte, as a controlled baseline. Qualify bare
gold/water before biomolecular contact. Treat its Na/Cl adsorption as a prediction
to test, not as established gold chemistry. This recommendation prioritizes a
shared slab/nanoparticle foundation with native pair interactions; it does **not**
meet a requirement for image-charge response.

If adsorption of charged solutes is the primary near-term result, select
**Geada et al. polarizable core–shell gold first** instead. This changes atom counts,
PSF bonds/exclusions, temperature diagnostics, force checks and restart identity.
It is a scientific scope choice, not merely a performance toggle.

| Candidate | Au structure | Water/contact behavior | Ions and electronic response | NAMD consequence |
|---|---|---|---|---|
| Heinz 2008 / INTERFACE 1.5, 12–6 | LJ fcc cohesive model; potentially mobile, restrained or fixed | Established interface model; mixing is defined, but chosen solvent must be matched | Neutral Au has zero electrostatic image attraction; mixed LJ does not establish specific adsorption | Native CHARMM LJ; simplest baseline; no Au bonds |
| Geada 2018 polarizable IFF | Mobile cores with bonded electron sites | Native LJ plus charge response | Targets image response; local polarization is not a constant-potential solver | Native bonds/LJ/Coulomb appear representable; must verify exclusions and GPU integration rather than assume generic Drude settings |
| GolP / GolP-CHARMM | Surface-specific constructions; transfer to mobile particles is a separate problem | Explicit facet-sensitive fitting; useful Au(111)/(100) water/biomolecule reference | Rotating dipoles and extra sites; not equivalent to neutral LJ | Different topology and interaction assignments; not a drop-in Au parameter |
| Constant-potential electrode model | Requires a separately specified metal structural model | Requires a matched electrolyte/interface force field | Solves electrode charge subject to potential constraints | Existing EW3DC CUDA correction does not provide charge equilibration |

Primary references: [Heinz et al., 2008](https://doi.org/10.1021/jp801931d),
[INTERFACE authors' distribution](https://bionanostructures.com/interface-md/),
[Geada et al., 2018](https://doi.org/10.1038/s41467-018-03137-8),
[GolP-CHARMM, 2013](https://doi.org/10.1021/ct301018m), and
[Park and McDaniel, 2022](https://doi.org/10.1021/acs.jpcc.2c04910).
The last compares fixed-voltage Au(100)/NaCl simulations; similarity of capacitance
does not imply equivalent microscopic structure across polarizability choices.

## Verified parameters and compatibility

The author's [CHARMM-format IFF file](https://github.com/hendrikheinz/INTERFACE-force-field-and-surface-models/blob/584179265906d93aa40f7d5b275143985871b654/charmm27_interface_v1_5.prm)
contains `AU 0.0 -5.29 1.4755`. In CHARMM units this means well depth
5.29 kcal/mol and **Rmin/2 = 1.4755 Å**, not sigma = 1.4755 Å.
For unbonded pairs:

```
Uij = epsilon_ij [(Rmin_ij/r)^12 - 2 (Rmin_ij/r)^6]
epsilon_ij = sqrt(epsilon_i epsilon_j)
Rmin_ij = (Rmin_i/2) + (Rmin_j/2)
sigma_ij = Rmin_ij / 2^(1/6)   # conventional 4*epsilon LJ form
```

An explicit NBFIX overrides the mixed pair. Engine switching/cutoff must be
recorded separately from these unswitched equations. Geometry uses nm internally;
NAMD coordinates/radii use Å, energy kcal/mol, mass daltons, charge elementary e.
For the neutral candidate use Au mass 196.96657 Da, charge zero, isolated Au
residues and no invented Au–Au bonds or exclusions. LJ cohesion must not be
suppressed as it is for the abstract NGRC wall.

Actual local files, inspected directly:

| Component | Active source | Consequence |
|---|---|---|
| Water | `toppar_water_ions_cufix.str` | OT: ε=0.1521, Rmin/2=1.7682; HT: ε=0.046, Rmin/2=0.2245; charges −0.834/+0.417 e. Au–H LJ must be included. |
| Sodium | Same | SOD: ε=0.0469, Rmin/2=1.41075, +1 e |
| Chloride | Same | CLA: ε=0.150, Rmin/2=2.27, −1 e |
| Na–Cl | Same, NBFIX | ε=0.083875, Rmin=3.74075; preserve override, not mixed radius 3.68075 |
| DNA | `par_all36_na.prm` and CUFIX | Preserve sodium–phosphate ON3 NBFIX Rmin=3.20075 |
| Protein/linker | `par_all36m_prot.prm`, `par_np_thiol.prm` | The latter contains C3 linker and NGRC wall terms, **no gold model** |
| PEG | Pinned `par_all35_ethers.prm` | OT/HT entries agree with local water; ether parameters are additive CHARMM. No gold adsorption or Au–S validation follows from this compatibility. |

**Do not load the entire old CHARMM27-IFF distribution over modern NADOC files.**
The polarizable distribution itself contains SOD Rmin/2=1.36375 Å, different from
NADOC's 1.41075. Extract and namespace only the selected metal types; audit actual
load order, repeated types and NBFIX partners. Existing stub types cover missing
CUFIX partners but are not a general-purpose biomolecular parameterization.
Initial gold qualification should reject Mg, custom ions, DNA/PEG contact and
thiol attachment until their corresponding tests/assets are defined.

## Polarizable alternative: concrete difference

The Geada supplementary CHARMM file gives AUC/AUE LJ depths 3.50/0.20 kcal/mol,
both with Rmin/2=1.473 Å, and a zero-length harmonic bond coefficient
50 kcal/mol/Å². Bonded core–electron nonbond exclusions are essential.
The publication uses a 1 Da electron site and supports finite-mass dynamics;
do not automatically reinterpret this as a cold, massless or self-consistent
CHARMM Drude oscillator. Reproduce its initialization and temperature treatment.
The supplement reports 1 fs integration and discusses 0.5/2 fs sensitivity.
Its CHARMM parameter download does not include a topology file; PSF construction
remains implementation work. These points were checked in the downloaded
[supplementary dataset](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-018-03137-8/MediaObjects/41467_2018_3137_MOESM11_ESM.zip)
and [supplement](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-018-03137-8/MediaObjects/41467_2018_3137_MOESM1_ESM.pdf).

## Shared implementation architecture

1. `backend/core/gold_model.py`: versioned `iff-au-12-6-neutral-v1`, capabilities, atom types,
   provenance hashes, energy convention, supported electrolyte and mobility,
   approved parameter load order, explicit unsupported physics.
2. `backend/core/gold_geometry.py`: deterministic fcc cells, commensurate (100)/(111) slabs and
   fcc-cut spherical particles. Keep crystal basis, lattice parameter, termination,
   integer repeats and source IDs. A spherical lattice cut is not a relaxed Wulff
   particle. Use existing `SurfaceFrame`/`RigidTransform` for the complete package.
3. `backend/core/namd_gold_package.py`: shared PSF/PDB identities and exclusion policy; solvation
   via existing GRO/water/ion helpers with metal-aware atom-pair exclusion. Record
   retained water count and accessible volume. Avoid borrowing the abstract-wall
   oxygen clearance; it can remove physically occupied adsorption layers. An explicit
   `water_loading_scale` adjusts water inventory while preserving each water's geometry.
   It is recorded, never a force-field change. The first slit was underloaded after
   adsorption; scale 1.18 yields ~34.27 waters/nm³ centrally in a 100 ps pilot.
   This is a local recipe, not a universally calibrated default.
4. Boundaries: explicit periodic nanoparticle solvent cell with ordinary 3D PME.
   Planar finite liquid slab may use normal vacuum padding and EW3DC. A periodically
   repeated solid/liquid stack is a different boundary problem. Slab correction
   must follow geometry, not the presence of Au atoms.
5. Mobility: fixed atoms, native position restraints, mobile cohesive model only
   as separately qualified. Reject mobile Au if the chosen model does not provide
   cohesion. No added hard-wall force at the explicit Au interface.
6. Execution adapter: native LJ/bonds/Coulomb; GPU EW3DC only for planar geometry.
   The gold adapter supplies the existing CUDA kernel with zero wall/anchor force.
   Native harmonic gold restraints are separate. Require GPU resident
   execution and pinned compatible runtime; do not silently fall back to Tcl.
7. Managed jobs: `backend/core/namd_gold_job.py` creates ordinary `MdJob` entries;
   `namd_runner.run_job` dispatches their qualification stages using its existing
   cancellable subprocess machinery. Material/asset hashes persist in manifests.
   Resume complete coor/vel/xsc
   with firsttimestep and original atom order, without reseeding solvent or rebuilding
   gold. Existing two-electrode health metrics are not gold qualification criteria.
8. Visualization: PSF/PDB contain explicit Au identities and coordinates. Persistent
   packing/trajectory plots provide review. Gold-specific application rendering and
   sidebar/setup-preset integration remain unimplemented; no abstract wall is substituted.

The preparation API is `POST /api/md/gold/jobs` (body: geometry and preparation
options), followed by the ordinary `/api/md/jobs/{id}/start`. The model is inspectable
at `GET /api/md/gold/model`; `/api/md/gold/jobs/{id}/continue` appends a qualification
segment after a completed checkpoint. Remote execution, generic job-settings edits
and ordinary production promotion are rejected explicitly. Sample JSON recipes and
CLI commands are in [the experiment README](../experiments/gold_interfaces/README.md).

## Validation targets and bounded sequence

The parameter audit is complete at the arithmetic level: five Au pairs agree
between Rmin and conventional sigma expressions, and analytic radial forces agree
with central finite differences. See the persistent report below. This establishes arithmetic consistency, not
physical validation. Additional native GPU pair probes agree to maximum force error
6.12e-6 kcal/mol/Å. Slab/particle native controls and managed continuations completed.
The original strict NVE split-run comparison failed an unvalidated 1e-4 velocity
threshold. The [2026-09-15 diagnosis](../experiments/gold_interfaces/evidence/gold_restart_diagnosis_20260915/RESULTS.md)
identified default restart removal of center-of-mass velocity. New gold restart
configs preserve it with `COMmotion yes`. Residual split-run differences are
comparable to repeated uninterrupted GPU runs; the old threshold is retained as
a historical diagnostic, not a physical qualification gate. Short NVE timestep
controls support 2→1 fs convergence but do not establish full numerical qualification.

Qualification checklist (completed pilot measurements versus remaining physical
comparisons are distinguished in the validation report):

- Verify every loaded type, total charge, PSF/PDB ordering and exclusions; native
  single-point pair tests should cover NBFIX, switching and gold cohesion.
- Build persistent planar and nanoparticle solvent cases. Start at 1 fs with
  ordinary masses; include 0.5 fs reference and 2 fs sensitivity. Track water
  translational/rotational temperature separately. No 4 fs qualification default.
- Run a bounded minimization and short dynamics/restart probe before estimating
  longer runs. Verify resident mode from engine logs and checkpoint fidelity;
  thermostat stochastic divergence is distinct from missing restart state.
- Establish bulk water density, gold nearest-neighbor/coordination distributions,
  particle radius and slab relaxation for each supported mobility. Fixed atoms
  staying fixed is not evidence of a stable mobile model.
- Compare planar water density/orientation against matching facet, solvent,
  temperature and cutoff data. Geada Table 2 distinguishes nonpolarizable and
  polarizable Au(100)/(111) hydration targets; its water calculations use SPC/E.
  Reproducing them would require a separate matched reference package.
- A useful [bare-Au nanoparticle study](https://arxiv.org/html/2009.07245) uses mobile
  IFF gold, SPC/E, 298.15 K and 1 fs, with long sampling after NPT equilibration.
  Its AuNP1 case has 201 Au atoms, 9,141 waters and 22 NaCl pairs in a 6.53 nm cell.
  This is a benchmark recipe, not a direct acceptance target for TIP3P/CUFIX.
- Measure Na/Cl profiles, contact residence, adsorption free energies and uncertainty
  under matched conditions. Compare lateral size, solvent extent/normal padding,
  mesh, timestep, restraint strength and independent seeds. Do not fit to the
  existing Debye result. Report runtime, published-implementation reproduction and
  experimental comparison as three separate validation levels.

No new QM is needed to implement the existing models. Au–S bonding, charge
transfer, reconstruction chemistry or new adsorption fitting may require separate
QM/experimental references later; a stronger arbitrary Au–S LJ term is not a
general validated bonding model. See the dedicated
[Au–S parameterization study](https://doi.org/10.1021/acs.jctc.8b00992).

## Provenance, redistribution and barriers

Author assets are cached locally in `workspace/gold_model_review_20260914`, with
exact URLs, retrieval date, immutable GitHub commit and SHA256 in `sources.json`.
The GitHub tree has no explicit LICENSE file. Public availability must not be
reported as an unrestricted redistribution license. The Geada article states
CC BY 4.0 with third-party exceptions; its bundled historical CHARMM files contain
other authors' parameters. Record applicable notices, and package only the required
metal data with attribution rather than redistributing the full mixed archive.
No upstream mixed force-field archive has been installed into the production
force-field directory. Each gold package receives the attributed numerical Au entry
and the existing NADOC solvent/biomolecular files.

| Barrier | Disposition / next check |
|---|---|
| Scientific first-model scope | Resolved: user selected neutral INTERFACE baseline |
| Matched water/ion validation | TIP3P/CUFIX differs from SPC/E references and author SOD parameters; isolate matched reference suite |
| Au-specific Na/Cl adsorption | No experimental or matched simulation agreement established |
| Electronic polarization | Absent from recommended baseline; polarizable alternative requires qualification |
| Constant potential / charge transfer | Neither existing wall nor neutral IFF supplies these; separate solver/chemistry |
| Au–S / functionalized PEG / DNA contact | Separate chemistry and cross-interaction qualification; existing linker is insufficient |
| Structural mobility and curvature | Fixed/restrained/mobile short controls completed; long stability/reconstruction not established |
| GPU boundary adapter | Implemented, fixed-cell single-GPU EW3DC; particles omit it. Experimental GPU atom migration disabled after native failures; preparation requires cells >=4 nm |
| Job/restart/preset/visualization integration | Managed create/start/completed-checkpoint continuation implemented; new restart configs preserve COM velocity. Partial-stage restart and gold sidebar presets/rendering remain barriers; exact trajectory identity is not a physical gate. |
| Remote deployment | Existing 40 ns runtime bundles qualify old wall physics only; gold probes required per target |
| Long sampling | Estimate from measured short-run throughput before launching; no cloud rental authorized |

**Next stage recommendation:** further bare-gold validation, then choose either
polarizable/constant-potential electrostatics for charged-interface questions or
explicit Au–S chemistry for grafted PEG. Do not promote thiol/DNA predictions on the
basis of a stable bare-gold trajectory.

## Reproducible local review

```
uv run python -m experiments.gold_interfaces.audit_parameters \
  --sources workspace/gold_model_review_20260914 \
  --output workspace/gold_model_review_20260914/pair_audit_repeat
```

The command refuses an existing output directory, verifies cached source hashes,
reads actual repository water/ion parameters, and writes JSON, CSV and a PNG.
Initial results: `workspace/gold_model_review_20260914/pair_audit/`.
No managed job or simulation evidence was modified. No backend/frontend behavior
changed; `main.js` LOC delta for this task is 0.

## Phase 1 preparation calibration, 2026-09-15

The [completed calibration report](../experiments/gold_interfaces/evidence/gold_phase1_calibration_20260915/RESULTS.md)
replaces the approximate water-density target with two same-model bulk NPT pilots
(mean 33.760 waters/nm³). Independent revised particle and slit preparations use
measured water inventories with reported profiles and sampling uncertainty. These
counts apply to the documented geometries and snapshot recipes; they do not replace
the existing package defaults with a universal loading factor. Hydration, ion
adsorption and size/sampling convergence remain unqualified.

The [constant-potential design](namd_constant_potential_design.md) identifies native
charge propagation and consistent PME/self-energy accounting as implementation work.
The current neutral Au baseline does not supply voltage control. See the
[qualification matrix](namd_gold_qualification_matrix.md) for the evidence boundaries.
