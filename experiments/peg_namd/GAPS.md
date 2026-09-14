# NAMD PEG–gold–DNA interaction inventory

Assessment date: 2026-09-10. A missing repository asset, an unvalidated interaction,
and an absent physical mechanism are different gaps. New parameter generation is
an available workstream, not a reason to abandon the atomistic approach.

## Existing local capabilities

Read-only inspection found NAMD, VMD/psfgen, VMD solvate/autoionize, GROMACS, Psi4
1.11, RDKit, ffTK 1.1, ForceBalance 1.9.5 and OpenMM 8.6.0. The repository's toolchain
probe also reports its pinned distributed response/Hessian dependencies present.
This is an installation inventory, not a new execution qualification on H200/B200.
The installed `/usr/bin/orca` is the screen reader, not a QM executable; Psi4 is
available instead. Runtime snapshot: `workspace/peg_namd/toolchain_20260910.json`.

Reusable code/infrastructure:

- `backend/core/namd_topology.py`: psfgen discovery and DNA topology construction.
- `backend/core/namd_solvate.py`: DNA-centric explicit-solvent packaging and ion
  conventions. It is NOT a general PEG builder; the new experiment uses VMD's
  established solvation tools without modifying the production DNA path.
- `backend/core/photoproduct_toolchain.py`: read-only availability/provenance probe.
- `backend/parameterization/photoproduct_qm.py`, `photoproduct_charge_fit.py`,
  `photoproduct_boundary_nonbonded.py`, `photoproduct_charmm_export.py`: useful
  patterns for QM evidence, charge constraints, cross-interaction fitting and
  CHARMM export. These contain photoproduct-specific definitions and policies:
  adapt through a PEG-specific schema rather than submitting PEG as a CPD molecule.
- Existing force-field release/provenance practice: separate fit data from held-out
  validation, compare reference energies/forces with engine implementations, and
  retain parameter hashes and chemical-state identities.

## Interaction matrix

| Interaction or mechanism | Current status | What closes the gap |
|---|---|---|
| PEG bonded terms and caps | No PEG PSF/RTF/parameter package in bundled force-field tree | Import a documented additive CHARMM ether model, pin exact release/terms/end groups, or fit missing terms; check conformers, torsions and chain dimensions |
| PEG–water | Published atomistic models exist; not locally qualified | Hydration/conformer statistics plus bulk chain dimensions, density and concentration-dependent osmotic behavior in the chosen water model |
| PEG–PEG | Not validated by isolated-chain agreement | Concentration/brush compression tests; reject a model that matches dilute Rg but has wrong solution interactions |
| PEG–DNA | Compatible atom types can produce mixed LJ/Coulomb forces, but no dedicated validation here | PEG fragment interactions with bases/sugar/phosphate, hydrated PMFs and preferential-interaction/duplex data; fit pair corrections only if needed |
| PEG–Na/Cl/Mg | NaCl infrastructure available; PEG binding and partitioning unqualified | Hydration/coordination and ion-partition tests. MGH versus bare Mg are different models, not interchangeable residue labels |
| Gold–water and gold–PEG | No installed physical gold slab model identified in bundled files | Select facet, surface model and polarization treatment; test water layering/wetting and hydrated ether adsorption |
| Gold–DNA | Not covered by CHARMM36 DNA alone | Adsorption of bases/nucleosides and phosphate-containing fragments; needed where PEG coverage permits contact |
| Au–S/linker–PEG | Existing C3 DNA-thiolate patches are NOT PEG linker parameters or an explicit Au–S model | Define actual linker, protonation/charge and binding motif; derive bonded and nonbonded terms for that state, with surface geometry and independent validation |
| Fixed-potential electrode | Not implemented by this scaffold; no verified repository NAMD implementation located | Qualify a constant-potential/polarizable electrode method and ensemble, charge response/capacitance, cell electrostatics and force accounting |
| Faradaic chemistry and attachment failure | Conventional fixed-topology classical MD does not model these reactions | Coated-electrode experiments plus targeted electronic-structure/reactive work if needed; not a pair-parameter patch |
| Grafted-brush mechanics | New harmonic-graft reference infrastructure only | Height/density and compression curves versus literature/experiment; stiffness, surface-model and finite-size sensitivity |
| Tile support, orientation and force coordinate | Deferred until brush and interface model selected | Mechanically explicit constraints; restrained-height sampling with relaxation and uncertainty diagnostics |

`backend/data/forcefield/top_np_thiol.rtf` contains NP5C/NP3C DNA terminal patches.
`par_np_thiol.prm` contains organic linker supplements and NGRC wall terms.
**NGRC is a restrained graphene-wall site; it must not be relabeled as gold.**
There is no Au–PEG validation hidden in these filenames.

## Published starting points and their limits

**PEG:** Lee, Venable, MacKerell and Pastor's C35r study validates ether conformers
and short PEO/PEG solution dimensions. This is a concrete starting model, not a
promise that every current CHARMM ether parameter release is numerically identical.
Caps matter: methyl-capped PEO and hydroxyl-capped PEG are distinct systems.
[Lee et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18456821/).
The official CHARMM distributions provide topology/parameter sources; select and
record a version rather than mixing arbitrary recent files with older terms.
[MacKerell force-field distribution](https://mackerell.umaryland.edu/charmm_ff.shtml).

**PEG–DNA:** experiments distinguish chemical preferential interactions from
excluded-volume effects, with different consequences for duplex and hairpin
formation. Therefore a steric-only cross model is a hypothesis to test, and generic
mixing rules are a baseline rather than evidence of correct PEG–DNA thermodynamics.
[Knowles et al., 2011](https://pmc.ncbi.nlm.nih.gov/articles/PMC3150925/).

**Gold:** GolP-CHARMM is an established starting point for biomolecule adsorption
at aqueous Au(111)/Au(100), originally developed for peptides. That scope does not
establish PEG or DNA adsorption accuracy, nor an applied-potential response.
[Wright et al., GolP-CHARMM](https://wrap.warwick.ac.uk/id/eprint/56263/).
There is also explicit molecular simulation of thiolated short PEG on solvated
gold, useful for identifying existing interface parameter choices; heat-transfer
validation does not establish compression forces or electrochemical accuracy.
[Heat transfer in PEG-capped gold interfaces](https://arxiv.org/abs/2312.05689).
DFT studies of PEG-thiol/Au work-function changes offer relevant electronic-structure
benchmarks, but their particular linker/coverage must match the intended model.
[PEG-thiol/Au work-function study](https://arxiv.org/abs/1911.12165).

**Electrode implementation:** NAMD's uniform external-field feature is not the same
as charge redistribution at fixed electrode potential. An established alternative
implementation to evaluate is LAMMPS ELECTRODE; compare model physics and force-field
compatibility before choosing an engine for this stage.
[LAMMPS constant-potential documentation](https://docs.lammps.org/latest/fix_electrode.html).

## Parameterization work order

1. Acquire/version a PEG additive CHARMM candidate and define both chain ends.
   Generate capped N36/N45/N76 PSF/PDB conformers; confirm atom counts, net charge,
   bonded coverage and single-chain behavior. Keep fitting and validation sets distinct.
2. Qualify a neutral Au facet/water model and ether adsorption. Build a commensurate
   slab; start the harmonic-graft brush reference only with intentional cross terms.
3. Define the actual linker. Use chemically representative ether/terminal/linker
   fragments for charge/water-interaction targets, torsion scans and bonded response.
   Use suitable relativistic treatment and a surface/cluster model appropriate to
   gold; the existing organic CPD QM protocol is not automatically valid for Au.
4. Test PEG–DNA and PEG–ion cross terms against solvated observables. Gas-phase
   pair energies alone cannot validate interfacial solvation or osmotic pressure.
   If corrections are needed, introduce isolated atom types/pair overrides so DNA's
   validated internal force field is not changed inadvertently.
5. Add constant-potential physics and benchmark the actual combination of NAMD
   features, GPU architecture and electrostatic boundary conditions. Fitting a
   static LJ well cannot substitute for a missing electrode response mechanism.

For each work item, the machine-readable backlog records targets and held-out
validation. It is a planning interface; it does not falsely claim that the
photoproduct runner already accepts these PEG/Au definitions. None of this work
requires changing the current oxDNA force field or extending its running allocations.
