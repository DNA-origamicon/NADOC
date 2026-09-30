# Charged gold with proteins, DNA and lipids: model comparison

2026-09-15. Targeted primary-literature search, supplementing the [constant-potential validation plan](namd_constant_potential_validation_plan.md). No simulations or engine changes were performed.

## Conclusion

There is substantial prior work combining gold and biomolecules, including CHARMM-compatible and AMBER-compatible interfacial force fields. The rationale for using LAMMPS as a numerical reference is its established electrode implementation, not an absence of biological applications or inherently different physics in NAMD.

The major scientific distinctions are the electrical ensemble, treatment of metal polarization, molecular adsorption parameters, surface chemistry and solvent model. A constant-potential solver addresses only part of this list. Our recommendation is therefore to retain the independent electrostatics benchmarks and add a separate biomolecular interface validation track.

## Representative primary studies

### Proteins and peptides

- **GolP (Iori et al., 2009):** an explicit-water protein–Au(111) force field developed for use in biomolecular codes, explicitly including GROMACS and NAMD. Parameters draw on quantum calculations and small-molecule adsorption experiments; the model includes metal image-charge effects. [Original paper, DOI 10.1002/jcc.21165](https://onlinelibrary.wiley.com/doi/full/10.1002/jcc.21165)
- **GolP-CHARMM (Wright et al., 2013):** CHARMM-compatible Au(111)/Au(100) peptide interactions, including dynamic gold polarization and specific adsorption terms. It is evidence for established biological interface modeling, not evidence of an imposed-voltage electrode solver. [Original paper abstract, DOI 10.1021/ct301018m](https://pubmed.ncbi.nlm.nih.gov/26587623/)
- **Protein adsorption with GolP (2016):** explicit-water GROMACS simulations use rotating charged rods to represent metal polarization; Brownian-dynamics orientation screening uses an image-charge/continuum-solvent model. These are different approximations even within one study. [Three steps to gold, DOI 10.1039/C6CP00201C](https://pubs.rsc.org/en/content/articlehtml/2016/cp/c6cp00201c)
- **Charged gold and azurin (Bizzarri, 2006):** hydrated, surface-anchored protein simulations compare neutral, positive and negative substrates using CHARMM and CHARMM27. This directly establishes precedent for charged gold plus proteins. The accessible methods excerpt does not establish a per-step constant-potential solve. [Original paper, DOI 10.1016/j.bpc.2006.03.012](https://www.sciencedirect.com/science/article/abs/pii/S0301462206000834)
- **Amyloid β40 (Kalipillai et al., 2023):** a gold surface-charge-density study reports competition between peptide residues and condensed sodium ions. This makes ion competition a relevant biological observable. The abstract was inspected; the complete charge assignment and engine settings remain unaudited, so this is not classified as a verified constant-potential recipe. [Original paper, DOI 10.1039/D2SM01581A](https://pubs.rsc.org/bn/content/articlelanding/2023/sm/d2sm01581a)

### DNA and nucleobases

- **GolDNA-AMBER (2014):** a first-principles-derived force field including dispersion and polarization, demonstrated for nucleobase monolayers and aqueous nucleobase adsorption on Au(111). This is a useful source of base-specific interface tests; it does not establish quantitative validation for a complete DNA oligomer under applied electrode bias. [Enthalpy–Entropy Tuning in the Adsorption of Nucleobases, DOI 10.1021/ct401117g](https://pubs.acs.org/doi/10.1021/ct401117g)
- **Electrically switched tethered DNA (2006):** experiments on gold are interpreted using Brownian dynamics with charged bead chains and hydrodynamic interactions. The simulations reproduce differing switching mechanisms for single- and double-stranded DNA. This is a coarse representation of the biological response, not an atomistic gold charge-solver reference. [Dissimilar Kinetic Behavior of Electrically Manipulated DNA](https://pmc.ncbi.nlm.nih.gov/articles/PMC1440747/)
- **NAMD biased-pore precedent (2016):** self-consistent electrostatic calculations supply an external grid potential for subsequent DNA MD. The paper explicitly discusses real gold as a further material-specific consideration. It should not be relabeled as a validated, explicit constant-potential gold model. [Electrically Tunable Quenching of DNA Fluctuations](https://pmc.ncbi.nlm.nih.gov/articles/PMC4918906/)

### Lipids

- **Charged coated Au nanoparticles / skin lipids (2017):** coarse-grained particles have charged terminal beads on thiol ligands. Here “charged gold nanoparticle” refers to ligand-shell charge, which is physically different from supplying electronic charge to a voltage-controlled metal. [Original simulation study, DOI 10.1038/srep45292](https://www.nature.com/articles/srep45292)
- **Supported DMPC bilayers / gold (Schneemilch and Quirke, 2016):** an atomistic adhesion-free-energy method is used to calibrate lipid–gold interactions to an experimental adhesion energy. This provides an interface-specific target beyond electrostatics. The accessible abstract does not establish a constant-potential implementation. [Original paper, DOI 10.1016/j.cplett.2016.10.010](https://www.sciencedirect.com/science/article/abs/pii/S0009261416307795)

### Direct organic / constant-potential example

**4-mercaptobenzonitrile (4-MBN) on gold:** the 2023 spectroscopy study uses a two-electrode constant-potential simulation with an organic monolayer and SPC/E water. A 2024 companion simulation paper describes LAMMPS production calculations. This is a direct precedent for voltage-controlled gold with organic molecules. Its hydration structure and hydrogen-bond dynamics provide a possible intermediate benchmark between a bare capacitor and a full biomolecule. [2023 experimental/simulation paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10756189/) · [2024 simulation paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11219078/) · [Author manuscript containing engine details](https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/6556b881dbd7c8b54b6bbf9e/original/Manuscript-11-16.pdf)

## Major differences in underlying physics

| Model choice | What it represents | Difference from the proposed Gaussian constant-potential model |
| --- | --- | --- |
| Fixed gold atomic charges | Prescribed metal charge distribution | Cannot redistribute locally when a charged residue approaches; potential can change with the environment. |
| Charged surface ligands | Chemical charges on the coating, often set by protonation | Charge lies outside the metal and introduces steric, hydration and acid–base effects. It is not an electrode-voltage boundary condition. |
| Rotating dipoles or core–shell gold | Local polarization through auxiliary charged sites | Induced dipoles do not by themselves impose a common electrode potential or exchange net charge with an external circuit. |
| Constant electrode potential | Electrode charges adjust to the instantaneous surroundings and prescribed voltage | Appropriate electrical boundary for a potentiostatically controlled electrode, provided the electrostatic model and boundaries are correct. |
| Fixed total charge with internal redistribution | An isolated conductor can polarize while retaining its net charge | Often a more appropriate starting electrical ensemble for a disconnected nanoparticle than imposed voltage. |
| Prescribed external field/grid or continuum solvent | Selected electrical and screening effects without an explicit coupled electrode response | Can reproduce certain biological observables while omitting local metal/ion/water feedback. |

These are distinctions in the mathematical models, not intrinsic limitations imposed by an engine name. The constant-potential comparison is grounded in the [ELECTRODE formulation](https://arxiv.org/html/2203.15461); the consequences in the table are our interpretation of those model definitions.

### Polarization and adsorption must be considered together

A polarizable extension of the INTERFACE gold model uses harmonically coupled core/dummy-electron sites. Its published checks include image interactions, gold structural properties, hydration and peptide binding. It offers relevant biological-interface evidence close to our current IFF baseline, but is not itself the same model as fluctuating Gaussian electrode charges. [Geada et al., 2018, polarizable Lennard–Jones gold](https://pmc.ncbi.nlm.nih.gov/articles/PMC5818522/)

**Implementation inference:** do not simply add a complete GolP or core–shell polarization model on top of Gaussian constant-potential charges. Both can represent metal response, so their combination needs a derived energy partition and validation against double counting. Similarly, carrying adsorption parameters from one polarization model into another requires rechecking adsorption free energies and hydration.

### Chemistry, solvent and voltage conventions

A bare Au–NaCl benchmark does not determine nucleobase binding, amino-acid specificity, lipid adhesion or Au–S anchoring. The model must distinguish bare gold from a ligand-coated surface and fixed attachment from reactive bond formation. Classical fixed-topology constant-potential MD does not, on its own, provide redox chemistry or electronic transport through DNA/proteins.

The inspected studies use different biological force fields and water descriptions. Their interfacial hydrogen bonding, ion binding and screening cannot be assumed identical after substitution with NADOC's TIP3P/CUFIX combination. This is a model-transfer issue to assess after numerical equivalence is established.

Experimental working-electrode potential relative to Ag/AgCl is also distinct from the simulated voltage across two electrodes. Coatings and unequal interfaces can redistribute that voltage. The 4-MBN study explicitly distinguishes the two; our comparisons must record the potential convention rather than identify the numerical values directly.

## Revised recommendation for NADOC

1. **Keep the original charge/energy/force reference tests.** They remain the strongest way to isolate errors in NAMD electrode implementation.
2. **Add small biological interface tests before full systems.** Select published aqueous adsorption free-energy profiles for representative charged amino-acid groups and nucleobases, plus lipid–gold adhesion if lipids are a priority. Match each reference model before evaluating transfer to our intended model. These are physical observables, not arbitrary simulation-stability metrics.
3. **Assess polarization compatibility explicitly.** Compare the assumptions behind IFF, its polarizable extension, GolP-CHARMM and GolDNA-AMBER; choose one consistent energy model. A software-compatible file is not proof of physical compatibility.
4. **Consider 4-MBN as a voltage-dependent organic benchmark.** Audit the full inputs and surface bonding before committing to reproduction. Its molecular size is more manageable than a protein or DNA layer, although its chemistry is not a substitute for their validation.
5. **Specify the experimental system before biological production.** Required distinctions include connected electrode versus isolated particle, bare versus coated gold, anchoring and protonation, electrolyte, and experimental voltage reference. No production model choice is made by this review.

## Search coverage and limits

This was a targeted search of original force-field papers, charged-gold applications, DNA switching studies, lipid-interface studies and constant-potential organic-electrode simulations. Primary publisher abstracts, accessible methods and author manuscripts were used; some publisher full texts were inaccessible. The detailed 2023 organic-electrode and 2018 polarizable-IFF texts were also retrieved through Europe PMC and cached in `.development-artifacts/charged_gold_biomolecules_review_20260915/`.

The search found direct precedents in all three biomolecular categories, but did not verify a turnkey published NAMD recipe combining explicit constant-potential gold with complete lipid/protein/DNA systems. That is a bounded search result, not a claim that such work does not exist. No claim of methodological novelty is justified by this review.
