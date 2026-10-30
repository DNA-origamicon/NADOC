# CPD isomer repeats: publication review — 23 October 2026

Update, 25 October: [the new three-control comparison](cpd_control_comparison_20261025.md) supersedes the older-baseline comparison and includes the completed third cis-syn-I repeat. The dated analysis below is retained as its original evidence snapshot.

This review concerns the current CGenFF-derived MVP models in the 2hb_1xT constructs. It does not transfer validation from the historical fitted additive or Drude models to these different parameter files. No force fields, simulations, or user designs were changed.

## Assessment

The appropriate claim is replicated, finite-duration structural testing of provisional CPD models. A claim of validated predictive CPD mechanics, equilibrium isomer rankings, or photochemical performance would need substantially more evidence. Successful NAMD execution establishes neither correct solution energetics nor experimental realism.

The principal publication risks are model-specific physical validation, inadequate sampling for equilibrium claims, and absence of contemporaneous matched undamaged controls. The simulation engine itself is not the principal concern. Local opening is a result to investigate, not a sufficient reason to change parameters until the DNA remains closed.

## Scope and reproducibility

The completed-run inventory contains eleven 20 ns production trajectories (220 ns aggregate): three cis-anti-I, three trans-syn-I, three trans-syn-II, and two cis-syn-I. The third cis-syn-I was running at the analysis cutoff and is excluded from endpoint comparisons. Each isomer's repeats share a relaxed coordinate start; velocity reseeding provides different trajectories, not independent starting conformational basins. Aggregate time is not equivalent to one 220 ns equilibrium trajectory.

The new analysis and compact results are in `/media/jojo/Archive/NADOC_archive/analysis/cpd_repeats_20261023/`. `summary.csv`, `summary.json`, per-job JSON/CSV traces, `supplement.json`, `replica_traces.png`, and the analysis scripts provide the quantitative evidence. The earlier baseline evidence remains in `docs/audits/cpd_production_20ns_20261019/`; those baseline trajectories were not newly reread for this report.

The principal audit uses `scripts/analyze_cpd_production.py` and examines every retained 20 ps frame: both intended covalent crosslinks, all four CPD stereocenters, finite coordinates, lesion-adjacent heavy-atom bond lengths, lesion–DNA nonbonded distances excluding bonded and angle neighbors, global/local rigid-fit RMSD, and all 42 reference base pairs. It verifies packaged assets and native log completion. Supplemental diagnostics sample every fifth saved frame (100 ps): explicit donor–hydrogen–acceptor angles, six lesion-sugar chirality signs relative to the starting structure, glycosidic torsions, CPD ring torsion, sugar-attachment separation, DNA radius of gyration, raw DNA bond continuity, and a conservative periodic-image clearance bound. This is not an all-atom, all-frame hydrogen-bond or sugar-stereochemistry audit.

RMSD selections contain 1,963 DNA heavy atoms globally and 126 locally (the two extra thymidines and their four sequence neighbors). Each selection is independently aligned to its own production start. Thus local RMSD measures internal deformation after removing local rigid-body movement; it does not measure a spring constant. The lesion connects D001 residue 15 to D000 residue 8, on different strands, rather than two adjacent bases in an ordinary duplex.

The inherited pairing proxy requires every canonical heavy-atom donor/acceptor distance to be no greater than its design-reference distance plus 0.75 Å. The supplemental criterion instead requires each canonical interaction to have donor–acceptor distance ≤3.5 Å and donor–H–acceptor angle ≥150°, accepting either chemically attached amino hydrogen where relevant. Both criteria are geometric occupancy definitions, not experimental equilibrium constants. Four flanking base pairs are evaluated; the two crosslinked extra thymidines themselves are not canonical paired bases. Summary time windows use rounded trajectory times to avoid floating-point boundary ambiguity. Older per-job summaries can differ by one frame at a 5 ns boundary.

## New trajectory results

All 11 completed jobs terminate normally at 10,000,000 production steps and provide 1,000 frames each. Across 11,000 frames, both intended crosslinks exist, the four CPD stereocenters retain their specified signs, coordinates remain finite, and seven packaged assets per run pass verification. Mean crosslink lengths span **1.530–1.564 Å**. The maximum audited lesion-adjacent heavy-atom bond length is **1.704 Å**; the smallest lesion–DNA nonbonded heavy-atom separation, excluding 1–2 and 1–3 neighbors, is **2.382 Å**. These are useful screens for gross distortions, not a complete force-field accuracy test. Mean logged temperatures are **299.16–299.23 K** under a 300 K thermostat target.

The 2,200 supplemental samples have no sign inversion at the six checked lesion-sugar centers and continuous raw DNA heavy-atom bonds (maximum **1.738 Å**). The minimum conservative image-clearance bound is **13.12 Å**, exceeding the actual 10 Å real-space cutoff in every sampled frame. This bound uses the shortest orthorhombic lattice vector minus twice the maximum DNA heavy-atom radius about its centroid. It is a lower bound, not an exact nearest-image distance, and does not eliminate all long-range finite-size effects.

| Isomer | Completed repeats | Mean attachment C1′–C1′ separation (Å), range of replica means | Whole-DNA RMSD (Å), range of replica means | Four flanking pairs retained in final 5 ns, range across replicas |
|---|---:|---:|---:|---:|
| cis-syn-I | 2 | 3.37–3.41 | 5.76–9.46 | 94.2–94.3% |
| cis-anti-I | 3 | 7.00–7.04 | 4.97–5.61 | 71.5–79.1% |
| trans-syn-I | 3 | 4.10–4.39 | 5.34–5.91 | 60.2–95.9% |
| trans-syn-II | 3 | 4.08–4.19 | 4.01–9.12 | 87.8–95.1% |

These are descriptive ranges, not confidence intervals. C1′–C1′ is the distance between the two sugar attachment atoms, not a duplex width or covalent bond length. Pairing percentages use the inherited distance criterion; they must not be labeled hydrogen-bond populations without the definition.

- **Cis-syn-I:** compact attachment geometry (~3.4 Å), local fitted RMSD means 1.85–2.17 Å. One repeat has a transient local pairing loss around 5–10 ns and recovers; both end with ~94% flanking pairing. Whole-DNA motion is substantial, including one mean RMSD of 9.46 Å, so this is not a globally rigidified bundle.
- **Cis-anti-I:** much wider attachment geometry (~7.0 Å), local fitted RMSD means 2.02–2.69 Å. D000:THY9–D002:ADE9 has only **39.8%, 40.6%, and 43.0%** late-window distance-proxy occupancy in the three repeats. The angular criterion gives **24%, 16%, and 16%**, respectively, in the 50 supplemental late-window samples. Thus the same vulnerable pair recurs under both criteria. The newest repeat has a broader early pairing loss and partial recovery. This supports an isomer-associated local perturbation in this starting context; it does not identify its physical cause or establish an equilibrium occupancy.
- **Trans-syn-I:** attachment separations average 4.10–4.39 Å, with the largest local deformation in two repeats. D000:GUA7–D002:CYT44 late-window distance-proxy occupancy is **0%, 14.7%, and 96.0%** in chronological repeat order; angular occupancies are **0%, 4%, and 70%**. Two repeats therefore develop pronounced local disruption while one remains largely paired. Late six-residue RMSD is about 4.5–5.7 Å in the affected traces. The third run prevents treating that disrupted state as inevitable.
- **Trans-syn-II:** attachment separations average 4.08–4.19 Å and local fitted RMSD means 1.75–1.89 Å. Final flanking pairing is 88–95%, with some weakening at D001:GUA16–D002:CYT43 in one repeat. It is the most consistently modest local deformation among the three-repeat groups on these metrics, but one run has much larger global deformation. This is not an established ranking of mechanical stability.

Angular pairing fractions are lower than distance-only fractions even in apparently intact neighborhoods: requiring all two or three canonical interactions to simultaneously meet a 150° angular threshold is strict. The agreement of both criteria on the specific cis-anti and trans-syn-I weak pairs is more informative than interpreting every angular failure as complete base flipping.

There is **no gross structural impossibility demonstrated by these checks**: the bridges remain chemically intact, the bundles retain most reference pairing (whole-run mean 42-pair fractions span 92.9–96.2%), and DNA heavy-atom radius of gyration means remain approximately 27 Å. However, persistent local loss of pairing and continuing global drift are real concerns for claims of universal stabilization. Whether they are realistic junction strain or an artifact remains unresolved without matched controls and independent validation of the current Hamiltonian. Covalent linkage is expected to restrict local degrees of freedom; lower local RMSD does not quantify stiffness or prove the restriction has the correct magnitude.

The earlier undamaged baseline summaries show whole-DNA RMSD means of 6.23–6.89 Å, local means 2.05–3.31 Å and flanking pairing 93–94% over their first 20 ns. Current CPD values overlap these ranges, while some global displacements are larger. Because the protocols and starts differ, these numbers are contextual only.

Several traces continue changing late in the run. Diagnostic integrated-autocorrelation estimates for local pairing after 5 ns correspond to only roughly 7–15 effective samples in the strongly changing trajectories; these estimates themselves are unreliable under nonstationarity. No frame-based p-values or equilibrium confidence intervals are reported. At most two or three independently seeded trajectories per isomer are available, all conditional on the shared relaxed start.

[Replica traces](/media/jojo/Archive/NADOC_archive/analysis/cpd_repeats_20261023/replica_traces.png) are retained with the analysis artifacts. Repeat numbers follow creation order within each isomer.

| Isomer | Repeat | Managed job | Whole-run local RMSD (Å) | Final-5-ns flanking pairing |
|---|---:|---|---:|---:|
| cis-syn-I | 1 | `edb512c46112` | 1.85 | 94.3% |
| cis-syn-I | 2 | `d6bcdef3d59f` | 2.17 | 94.2% |
| cis-anti-I | 1 | `e345c67349bf` | 2.02 | 78.7% |
| cis-anti-I | 2 | `972af34aa9c5` | 2.17 | 71.5% |
| cis-anti-I | 3 | `577c8d057768` | 2.69 | 79.1% |
| trans-syn-I | 1 | `37d39cc6b88f` | 2.79 | 60.2% |
| trans-syn-I | 2 | `ffef0085e16d` | 2.94 | 75.9% |
| trans-syn-I | 3 | `35254aa13b01` | 1.77 | 95.9% |
| trans-syn-II | 1 | `9b08bed08561` | 1.88 | 91.9% |
| trans-syn-II | 2 | `395337bdb061` | 1.80 | 95.1% |
| trans-syn-II | 3 | `94d5148b6911` | 1.75 | 87.8% |

## What published refinement studies actually establish

| Primary study | Relevant evidence and implication |
|---|---|
| [Mayne et al., 2013, ffTK](https://pmc.ncbi.nlm.nih.gov/articles/PMC3874408/) | Develops CHARMM-compatible charge, bonded and torsional fitting; tests small-molecule parameters against condensed-phase properties. Using ffTK/CGenFF is an established route, but running the software is not the validation result. |
| [Xu et al., 2016, modified ribonucleotides](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/) | Uses model-compound QM, charge/torsion optimization and aqueous nucleotide/oligonucleotide simulations, with experimental refinement where available. This supports retaining unchanged parent chemistry while specifically validating the new base–sugar boundary and solution conformations. RNA is methodological precedent, not a CPD reference dataset. |
| [Ma and van der Vaart, 2017, CPD and base flipping](https://pubs.acs.org/doi/10.1021/acs.jcim.7b00215) | Deposits CPD force-field tables and uses free-energy simulations for bending/flipping. It provides a direct CPD modeling precedent; it does not validate these current parameters, other stereoisomers, or an interstrand origami bridge. |
| [Pang et al., 2020, AT130](https://pmc.ncbi.nlm.nih.gov/articles/PMC10198747/) | Refines CGenFF charges and torsions against QM and tests solution conformations and protein-bound behavior. A 10 ns isolated-ligand test is part of that larger evidence package, not a universal duration requirement. This illustrates why 20 ns is neither automatically inadequate nor automatically validating. |
| [Wu et al., 2022, β-lactam cores](https://link.springer.com/article/10.1007/s10822-022-00464-3) | Particularly relevant to coupled four-membered rings: an apparently good torsional energy fit could still yield the wrong MD conformation. Their workflow checks ring geometry and conformational clusters in 50 ns solution runs. This is a reason to validate coupled CPD ring/attachment conformations, not to impose their exact runtime as a publication rule. |

Taken together, these studies support the broad workflow but not a general acceptance stamp. Our current repeats add useful DNA-context stability evidence. They do not supply the missing parameter-specific comparisons against QM conformational/interaction targets or appropriate experimental observables. There is no need to demand an exact match to every arbitrary water orientation, require a polarizable model by default, or refit every inherited parent parameter; those would be stronger requirements than the evidence here justifies.

## Major reviewer concerns

1. **The deployed model is provisional and its provenance must be described accurately.** The packaged qualifications explicitly say physical validation is insufficient. The sugar-bearing external CGenFF assignments have maximum parameter penalties of 46.1 and charge penalties of 41.989 (syn products) or 42.054 (cis-anti). These are analogy/validation flags, not measured errors or proof of failure. The current topology uses transferred bonded terms and matched lesion-minus-reference charge increments; those increments are a modeling hypothesis. Historical MP2 minima, Drude work, and fitted cis-syn validation cannot be credited to this model without explicit parameter-level linkage. Describe the actual CGenFF transfer, and deposit its exact numerical assets; do not call it a fully validated bespoke QM/ffTK refinement.
2. **Sampling does not establish equilibrium or mechanical constants.** Three reseeds of one starting basin help assess variability, but common initialization and late structural changes remain. Frames are correlated. Statistical units are replicas, with block/drift diagnostics within each replica. Neither a low RMSD nor an intact CPD establishes equilibrium, rigidity enhancement, melting stability, or persistence length. The small number of repeats makes precise confidence intervals fragile. This aligns with the reproducibility concerns examined by [Knapp et al., 2018](https://doi.org/10.1021/acs.jctc.8b00391).
3. **The available undamaged baselines are confounded.** The earlier comparison used 4 fs/HMR undamaged runs in much smaller boxes versus 2 fs/no-HMR CPD runs; the oldest baseline also used different thermostat damping. Relaxation histories differ. They contextualize normal motion/fraying but cannot isolate a causal CPD effect. Matched box, solvent/ions, integrator, relaxation protocol and starting-ensemble controls are needed for that claim.
4. **Biological lesion precedent is not this structural context.** These are extra-base bridges between different strands in a two-helix construct. Published adjacent intrastrand cis-syn duplex bend/twist values are not universal targets for them. Interstrand-type cis-anti photoproducts have experimental precedent, but formation is context-dependent; [Su et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18680367/) established a specific sequence/pH-dependent product, not the yields or isomer distribution of this 2hb design.
5. **Fixed topology limits claims.** Covalent bonds remaining present are partly built into the Hamiltonian. These trajectories cannot test photochemical yield, isomer interconversion, bond rupture, photorepair, or relative isomer free energies. In particular, absence of crosslink rupture under ordinary thermal MD does not measure junction strength.

## Protocol appraisal

The current inputs use 2 fs without HMR, constrained hydrogen-containing bonds, PME, Langevin temperature control and an isotropic Langevin piston. DNA positional constraints are off and the audited extra-bond files contain no DNA restraints. These are recognizable all-atom explicit-solvent NPT choices. Constraints on hydrogen bonds do not freeze the carbon cyclobutane ring.

The actual current nonbonded settings are switching 8–10 Å, pair list 12 Å and nominal PME grid spacing 1.5 Å. They differ from the 10–12 Å force-switch scheme in the β-lactam study and from parts of our historical campaign. This is a methods/protocol sensitivity issue, not evidence by itself that the trajectories are invalid. For small quantitative isomer differences, check that the conclusion survives a force-field-consistent cutoff/switching and PME-accuracy comparison. Report the actual settings rather than copying historical methods prose. Instantaneous NPT total-energy fluctuations must not be interpreted as NVE integration drift.

The existing `docs/cpd_namd_methods_si_draft.md` has an earlier evidence cutoff and describes different campaigns. It must not be used unmodified as the Methods for these runs.

## Minimum work before stronger publication claims

- Freeze and deposit the exact current PSF/RTF/PRM files, atom/stereochemical maps, charge-transfer policy, parent force-field hashes, actual run inputs and analysis code. Clearly separate historical parameter branches.
- Validate each deployed isomer against applicable ring/attachment QM structures and low-energy coupled torsional profiles, plus representative electrostatic/water-interaction targets. Include a small DNA/sugar-context test. Where suitable NOE/ROE or scalar-coupling data exist, compare with a stated forward model and matching chemical identity/conditions. Unsupported observables must remain limitations.
- Complete the remaining cis-syn repeat and add matched undamaged controls if claiming CPD-induced stabilization or destabilization. Use a second independently prepared conformational start and sufficient sampling to test the particular observable; do not choose a universal number of nanoseconds as a substitute for convergence evidence.
- Investigate persistent opening with geometric and angular criteria and report all replicas. Do not select only favorable traces or tune parameters merely to eliminate opening. Establish reversible transitions and uncertainty before reporting opening populations or kinetics.
