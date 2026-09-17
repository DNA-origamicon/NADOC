# Streptavidin / biotin parameter literature audit

Research date: 2026-09-16. Published atomistic models exist; absence from our
downloaded CGenFF library is not evidence that nobody has parameterized these
components. The exact NADOC Biotin-TEG–5′-DNA parameter package remains unqualified.

## Closest published models

- [Comer, Ho and Aksimentiev, Electrophoresis (2012)](https://doi.org/10.1002/elps.201200164)
  simulated streptavidin/NeutrAvidin attached to DNA through biotin in NAMD.
  Methods describe CHARMM-compatible biotin parameters supplied by Chris Chipot,
  custom linker topology/parameters and patches joining biotin, linker and DNA.
  Figure 7 reports linker force–extension calibration from simulations. This is
  the closest integration precedent, but that calibration is not independent
  experimental validation of the force field. Exact equivalence to our existing
  Biotin-TEG graph has not been established; raw topology/parameter files have
  not been obtained. The article lists a supporting DOCX and a movie, which
  should not be assumed to contain a reusable force-field package.
- [Sedlak et al., Science Advances (2020)](https://doi.org/10.1126/sciadv.aay5999)
  used GPU NAMD, CHARMM36 and CGenFF-parameterized biotin plus a PEG3 linker.
  An initial QM/MM step generated linker geometry; subsequent production work
  was classical MD. This supports the CHARMM/CGenFF route. It does not supply
  an established match to our DNA phosphodiester boundary. The authors report
  geometry-dependent mechanics and limitations of ligand/linker parameters.
  Raw CGenFF assignments have not been obtained or audited here.
- [Rico et al., PNAS (2019)](https://doi.org/10.1073/pnas.1816909116)
  combined high-speed force spectroscopy with atomistic unbinding simulations,
  providing an experimental comparison over overlapping loading rates. Their
  Amber99sb model and effective PEG description are not a drop-in CHARMM36m
  Biotin-TEG–DNA parameter package. The measurements are useful benchmarks;
  binding mechanics depend on loading rate and pathway.

## Implementation decision

Reuse the existing CHARMM36m protein and CHARMM DNA framework. Pursue the
published CHARMM-compatible ligand/linker assignments before generating new
ones. Compare chemical graphs, stereochemistry, attachment position,
protonation, atom types and charges explicitly. Free biotin parameters cannot
silently substitute for its covalently modified linker form. Audit force-field
version compatibility rather than mixing parameter families by atom name.

The remaining local deliverable is a fully sourced BTE residue and BTE5
ligand–DNA boundary patch: hydrogen definitions, charges, bonded terms,
stereochemical impropers and nonbonded types. Preserve the existing 5′ phosphate
and audit all cross-boundary angles/dihedrals as well as the O4T–P bond.
If the published files cannot be recovered or differ chemically, use CGenFF
assignment and targeted QM validation/refinement for uncertain charges and
torsions, especially at the modified linker/phosphate boundary. This does not
require reparameterizing streptavidin.

Validation still required for our assembled system:

1. Complete PSF identity, valence, charge and parameter-coverage checks.
2. GPU NAMD minimization and replicated short equilibration of one tetramer,
   bound Biotin-TEG and a short DNA duplex. Monitor pocket pose, hydrogen-bond
   occupancy, protein structure, phosphate geometry, linker conformations and
   DNA pairing. Benchmark throughput before increasing system size.
3. Use independent structure and, where available, conformational/force data
   to assess the model. Stable short trajectories alone do not establish
   binding affinity, lifetime or rupture accuracy. Quantitative unbinding
   claims require matching experimental tether geometry and loading rates.

No force-field values were changed and no simulations or RunPod jobs were
launched for this literature audit. Useful full-text reference XML is retained
under the ignored `experiments/strep_biotin_namd/ws/literature/` directory;
the main user workspace was not used.
