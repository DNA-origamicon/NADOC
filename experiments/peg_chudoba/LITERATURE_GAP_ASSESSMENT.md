# Literature gap assessment — 2026-09-10

Targeted literature check prompted by the user's concern that a published
failure or fundamental limitation might explain the absence of chemical PEG
in an oxDNA/gold-surface workflow. This is not an exhaustive novelty review.
No simulation settings, acceptance criteria, or active allocations were changed.

## Assessment

No retrieved publication establishes a fundamental incompatibility between
chemical PEG and the oxDNA simulation engine, or documents abandonment of
this exact Chudoba/oxDNA combination after failure. This negative search result
cannot prove absence. Related systems have already been simulated. The apparent
gap is narrower: a validated, transferable coupled DNA–PEG–gold/linker model.

The plausible explanation is the cost of developing the missing cross
interactions and interfacial physics, alongside existing alternative simulation
frameworks. That explanation is our inference, not a documented account of why
individual research groups chose their models.

## Direct precedents

- **Hong et al., 2020, Understanding DNA interactions in crowded environments
  with a coarse-grained model.** oxDNA2 extended with repulsive spherical
  crowders; the authors explicitly identify polymeric PEG chains as a possible
  further extension. This supports extensibility, not chemical PEG accuracy.
  [Article](https://pmc.ncbi.nlm.nih.gov/articles/PMC7641764/),
  [authors' code](https://github.com/sulcgroup/crowderoxdna).
- **Liang et al., 2023, Quantification of macromolecule crowding at
  single-molecule level.** Magnetic-tweezers PEG experiments compared with an
  extended crowder-oxDNA model. The abstract reports agreement for PEG effects
  on hairpin critical force. Full simulation details were not accessible in
  this check; do not treat this as validation of a monomer-resolved PEG brush.
  [Article/abstract](https://pubmed.ncbi.nlm.nih.gov/37583195/),
  DOI 10.1103/PhysRevE.108.014406.
- **Jiao et al., 2022, Molecular basis of transport of surface functionalised
  gold nanoparticles to pulmonary surfactant.** Martini-based coarse-grained
  simulations include PEG-thiol-functionalized Au nanoparticles, varying ligand
  length and density. This establishes that coarse-grained PEG–gold systems
  exist; it does not validate an implicit-solvent Chudoba/oxDNA combination or
  a planar gold brush.
  [Article](https://pmc.ncbi.nlm.nih.gov/articles/PMC9205331/),
  DOI 10.1039/D2RA01892F.

## Published limitations relevant to our scope

- **Knowles et al., 2011:** PEG changes DNA duplex/hairpin thermodynamics through
  both excluded volume and preferential chemical interactions. Their balance
  depends on PEG size and DNA process; small glycols can favor the base surfaces
  exposed during melting. A repulsive-only DNA–PEG cross interaction therefore
  needs condition-specific validation, even if pure PEG dimensions and osmotic
  pressure pass.
  [Article](https://pmc.ncbi.nlm.nih.gov/articles/PMC3150925/),
  DOI 10.1073/pnas.1103382108.
- **Chudoba et al., 2017:** the model targets aqueous PEG chain dimensions and
  solution thermodynamics. These data do not determine interactions with DNA,
  gold, or a linker. Combining two calibrated self-interaction models does not
  supply a calibrated cross interaction; this last statement is our modeling
  inference.
  [Primary manuscript](https://arxiv.org/html/1710.09191v1).
- **Chain Conformation and Hydration of Polyethylene Oxide Grafted to Gold
  Nanoparticles, 2020:** atomistic calculations show that curvature, chain length,
  and grafting density affect conformation/hydration; planar brush criteria can
  be insufficient for highly curved particles. Match geometry when choosing
  reference data.
  [Article](https://pubs.acs.org/doi/10.1021/acs.macromol.0c01499).
- **Perrin et al., 2018:** an implicit-solvent treatment of PAAm/PDMA near silica
  missed interfacial dynamics captured with explicit solvent and competitive
  solvation. This is a concrete transferability warning from another system,
  not a demonstration that PEG on gold requires explicit water for every
  equilibrium observable.
  [Primary manuscript](https://arxiv.org/html/1904.09583v1),
  DOI 10.1021/acs.jpcb.7b11753 (journal 2018; arXiv deposit 2019).
- **Zoloff Michoff et al., 2026:** ab initio simulations of PEG attached to
  Au(111) through a thioctic-acid anchor find water-dependent mechanical rupture
  and chemical degradation pathways under applied stress. Fixed anchors cannot
  describe those processes. This does not invalidate stable-tether equilibrium
  steric models; the linker and loading regime differ from a generic brush.
  [Article](https://pubs.rsc.org/en/content/articlehtml/2026/mr/d5mr00030k),
  DOI 10.1039/D5MR00030K.
- **Zohra et al., 2025:** tethered DNA under shear in PEG solutions required
  treatment of viscosity and an effective PEG-induced attraction between DNA
  segments in their fitted Brownian-dynamics model. This supports keeping flow
  and physical kinetics outside our current equilibrium claim. The effective
  DNA–DNA attraction should not automatically be added to an explicit-PEG model,
  where depletion may already emerge (our double-counting caution).
  [Article](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0329961).

## Consequence for current work

Finish the bounded pure-PEG equilibrium validation. Before quantitative coupled
surface predictions, test a defined PEG/linker/gold layer against hydrated
height or density profiles and steric compression data. If DNA interactions are
the target, separately validate a relevant DNA–PEG observable. Preserve clear
limits on salt dependence, hydration-sensitive adhesion, anchor chemistry,
conducting-surface electrostatics, and physical dynamics.

A failed cross-system test should prompt interaction-model revision or a more
detailed local reference calculation, rather than longer bulk trajectories.
These findings support continuing a scoped equilibrium model, while opposing a
claim that the bulk port alone is a generally validated PEG–DNA–gold model.

## Search coverage and limitations

Searched exact oxDNA + PEG/polyethylene glycol/poly(ethylene glycol), chemical
PEG + gold/grafting/coarse-graining, Chudoba + surface/brush/transferability,
PEG–DNA preferential interactions, implicit/explicit interfacial solvent, and
PEG–gold anchor stability. Distinguished PEG used experimentally for purification
or coating from PEG actually represented in a simulation. Some publisher/PMC
pages were accessible only through indexed full text or abstracts. An Oxford
repository search hit could not be opened and is not treated as evidence.
