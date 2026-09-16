# CPD parameterization literature reassessment

Date: 2026-09-15

## Finding

Difficulty parameterizing modified nucleotides is common, but the present NADOC
failure is not primarily a failure to obtain QM structures. The CPD optimizations,
frequencies, response calculations, ESPs, and water curves have generally completed.
The unresolved result is narrower: a fixed-charge, atom-centered additive model fitted
to two water orientations does not predict a third orientation for the ordered
cis-anti-I fragment within the preregistered limits.

That is credible evidence of limited transferability for that model and target. It is
not evidence that the underlying QM structures are unresolved, that no usable CPD model
can exist, or that every CPD must move to a polarizable force field.

## What the established workflows say

The broad literature agrees that modified-nucleotide parameterization is difficult and
iterative. The 2026 NIST/modXNA tutorial calls it a difficult, non-trivial prerequisite
and reduces repeated work by assembling compatible pre-parameterized base, sugar, and
backbone modules. A review focused on modified RNA reaches a similar conclusion: force-
field-family consistency is necessary, but does not establish accuracy, and missing
experimental data makes validation especially difficult.

The conventional CHARMM additive sequence is:

1. choose the smallest representative model compounds and transfer parameters whose
   chemistry is unchanged;
2. obtain an initial CGenFF assignment and inspect penalties and chemical analogies;
3. optimize geometry and electrostatics against the force field's own target convention,
   including water interactions and dipole information;
4. fit bonded terms against geometries, vibrations, conformers, and potential-energy
   surfaces, iterating because the terms are coupled; and
5. validate the assembled nucleotide in its intended condensed-phase context and, where
   possible, against experimental structures or observables.

The CGenFF and modified-ribonucleotide papers emphasize hierarchical parameter transfer,
restraints that preserve compatibility with the parent force field, extensive torsion
work, and iterative refinement. The current FFParam guide implements the same order and
explicitly treats comparison, manual adjustment, and refitting as a loop rather than a
single automatic fit.

The usual approximately 0.2 kcal/mol CHARMM water-interaction objective is a development
target for the water poses included in the charge fit. The sources reviewed here do not
make leave-one-azimuth-out prediction across arbitrary water orientations a universal
release condition. NADOC's held-out orientation test is valuable because it exposed a
real limitation, but it is a stronger model-selection test than the conventional
additive workflow.

## CPD-specific precedent

Ma and van der Vaart published a CHARMM-compatible CPD model in 2017. Its supporting
information gives atom types and charges plus bond, angle, dihedral, and improper tables.
The parameters started from ParamChem and were further optimized with the CHARMM protocol.
This is the closest published comparator to NADOC's canonical cis-syn product. A 2026
Nucleic Acids Research study still uses those CPD parameters with CHARMM36, so the set is
not merely an abandoned historical example.

Other CPD simulations have used more pragmatic models. A 2008 photolyase study derived
RESP charges and transferred bonded terms from an AMBER thymine-dimer entry. A 2023 Rad4
study assigned CPD charges with Antechamber and adopted the remaining lesion terms from
GAFF alongside parmbsc1 DNA. These precedents demonstrate accepted practice, not proof
that the models are accurate for NADOC's observables.

The scope difference matters. Adjacent CPDs in ordinary A- or B-form DNA are dominated by
cis-syn-I; a stereochemistry review states that it is the adjacent product permitted by
the Watson-Crick geometry. The full set of ordered cis/trans and syn/anti designs in the
NADOC registry is therefore a broader synthetic-design scope than the usual biological
lesion parameterization problem. The Ma/van der Vaart set does not validate transfer to
ordered anti products.

## Assessment of the NADOC campaign

| Campaign choice | Assessment against conventional practice |
|---|---|
| Neutral N-methyl complete CPD core plus one-sugar boundary fragments | Well supported model-compound hierarchy |
| Transfer of unchanged CHARMM36 sugar-phosphate chemistry | Conventional and preferable to refitting the whole dinucleotide |
| Frequencies, response Hessians, coupled four-membered-ring fit, physical equilibrium checks | More rigorous than many published CPD parameter sets |
| Separate training and held-out conformers | Sound protection against bonded overfitting |
| Multiple water orientations with held-out azimuths | Useful stress test, but stronger than the conventional CHARMM charge-fitting criterion |
| Treating cis-anti-I failure as a blocker for every CPD | Over-broad; it delays the biologically standard cis-syn-I deliverable |
| Starting a Drude response campaign after systematic orientation failure | Scientifically justified for the anti research model, but not the shortest path to a canonical CPD in NAMD |
| Full d(TpT), duplex, and engine validation | Required and currently more important for the canonical release than adding further fragment orientations |

The fixed additive failure should remain recorded. It should not be converted into a pass
by changing its thresholds. The appropriate change is to narrow what that gate controls.

## Recommended campaign split

### Track 1: canonical cis-syn-I release

Use the existing cis-syn QM evidence and reconstruct the Ma/van der Vaart published model
as a hash-pinned comparison candidate with an explicit atom map. Because the supporting
information is a parameter table rather than a complete redistributable topology stream,
the reconstruction needs independent topology, charge, and term-coverage audits.

Select among the published comparison, the current NADOC additive fit, and any bounded
hybrid using preregistered cis-syn criteria. Then validate in d(TpT) and a short duplex
against 1N4E/1TTD-compatible structural observables, matched undamaged DNA, stereochemical
retention, and replicated explicit-solvent stability. The held-out water results remain a
reported limitation and comparison metric. They need not veto the cis-syn candidate if
the intended DNA observables pass a new, versioned release policy.

This is the conventional route to the first scientifically usable CPD in NADOC and NAMD.

### Track 2: ordered anti and other design stereoisomers

Keep the current anti additive failure as a closed gate. Continue the Drude work only for
products whose intended use depends on reproducing orientation-dependent electrostatics.
The CHARMM Drude protocol requires unperturbed and perturbed ESP maps, molecular
polarizability targets, fitted charges/polarizabilities/Thole factors, acceptor lone pairs,
and potentially anisotropic polarizability. The present polarizability pilot and planned
perturbed-ESP campaign are therefore appropriate inputs for this track.

No syn-to-anti or additive-to-Drude transfer should establish readiness without product-
specific validation. The remaining six ordered products can be prioritized by an actual
NADOC design requirement rather than treated as prerequisites for the canonical lesion.

## Practical decision

The campaign has generated useful evidence and is not stuck in a meaningless QM loop.
It has reached the point where more additive water-probe fitting has diminishing value.
The next highest-value work is:

1. complete the already submitted polarizability pilot so the anti-model diagnosis is
   preserved;
2. stop automatic expansion of the Drude campaign pending an explicit anti-product need;
3. build and audit the Ma/van der Vaart cis-syn comparison candidate; and
4. run the canonical cis-syn d(TpT)/duplex validation as a separate release track.

## Guides and reviews

- [NIST/modXNA modified-nucleic-acid tutorial (2026)](https://www.nist.gov/publications/parameterizing-modified-nucleic-acids-molecular-simulations-amber-md-software)
- [Challenges with Simulating Modified RNA (2022)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8949676/)
- [CGenFF development and hierarchical parameterization (2010)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/)
- [CHARMM modified-ribonucleotide parameterization (2016)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/)
- [FFParam workflow guide](https://ffparam.silcsbio.com/manual/workflow.html)
- [Nucleic-acid force-field development review (2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10398263/)
- [CHARMM additive and Drude force-field review (2015)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4334745/)
- [Ma and van der Vaart CPD parameters and application (2017)](https://pubs.acs.org/doi/10.1021/acs.jcim.7b00215)
- [Recent CHARMM36 use of the Ma/van der Vaart CPD parameters (2026)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13401050/)
- [CPD stereochemistry in DNA (2023)](https://doi.org/10.1111/php.13694)
