# CPD physics assessment — 2026-09-16

**Superseded by the bonded continuation audit:** the archived P2/P3 Drude
evaluators used syn crosslinks on the anti QM geometry. Their prior scientific
acceptance cannot be used downstream. See
[`experiments/cpd_drude_recovery/README.md`](../experiments/cpd_drude_recovery/README.md)
for the corrected-graph refit, bonded diagnostics, and full-nucleotide precursor
checks. The assessment below records the earlier checkpoint, before that defect
was discovered.

The ordered cis-anti-I Drude campaign has passed its fragment electrostatic stage,
but no CPD product has completed the scientific release path. The remaining work
is water-target consistency, bonded mechanics, nucleotide transfer, and solution
validation. A stable model-compound trajectory does not close those gaps.

This assessment checked campaign artifacts and the live scheduler around 01:17–01:20
MDT. Evidence root: `/media/jojo/Archive/NADOC_archive/photoproduct_evidence`.
No parameters, policies, running services, or registry gates were changed.

| Stage | Observed status | Interpretation |
|---|---|---|
| Anti P1 response QM | Recorded complete: 97 cases, 72 fit and 24 holdout perturbations | Provides polarization targets for the capped fragment |
| Anti P2 electrostatics | Completion trigger and assessment pass; assessment, frozen parameter, and holdout hashes match | Independent response ESP relative RMS 0.16328; dipole-response RMS 0.14449; tensor error 0.06249 on training |
| P2 engine agreement | Assessment records eight-case CPU NAMD/OpenMM pass; worst relative discrepancy 0.000674 versus 0.02 limit | Verifies the fixed-nucleus electrostatic implementation, not full molecular dynamics |
| Anti P3 water | Three orientation folds pass; independent fourth orientation unscored | Largest fold energy/distance RMSE 0.19016 kcal/mol and 0.09161 Å versus 0.20 and 0.10 limits |
| Fourth orientation QM | Alpine 32610248_[0] PENDING (Priority); collection/scoring service active | No P3 completion trigger exists yet |
| Anti P4 bonded | Input inventory passes; all six linked source hashes match | Three training and two validation force/Hessian structures exist; execution depends on P3 |
| Earlier additive anti smoke | Recorded vacuum and TIP3P solution integration pass, scientific nonbonded failure | Cannot validate the new Drude model |
| Canonical cis-syn-I | Separate additive candidate/comparator development track | Anti progress and failures cannot establish canonical readiness |
| Production registry | No validated contexts; registry target still additive CHARMM36/TIP3P | Drude release needs explicit model-family and engine capability representation |

The active `watch_collect_score.sh` collects QM and scores the fourth orientation.
It does not launch P4. P4 readiness is an input inventory, not an implemented bonded
fit or an automatic continuation service.

The critical sequence is:

1. **Close the water-target convention audit alongside P3 scoring.** The frozen P3
   policy explicitly targets `1.16-scaled counterpoise-corrected HF/6-31G*`
   interaction curves, and `fit_water.py` consumes `scaled_target_kcal_mol`.
   The 1.16 factor is documented in the CHARMM *additive* modified-nucleotide
   workflow. Its use with explicit Drude polarization needs a specific derivation
   or benchmark; this assessment has not established that justification. Audit
   method/basis, counterpoise convention, energy scaling, distance offsets, and
   monomer polarization/deformation references together. Preserve the present
   preregistered score. Any target correction requires a new policy and refit,
   with fresh independent validation if an opened holdout informs that revision.
2. **Implement the Drude-aware P4 refit.** Reuse audited QM targets and their split,
   not additive fitted coefficients. Fit the coupled ring bond/angle/proper block
   with the accepted electrostatics and nonbonded terms. Relax Drude coordinates
   consistently at each displaced nuclear geometry: the target is the nuclear
   energy surface after induced polarization relaxes, not a Hessian containing
   artificial Drude oscillator modes. Check finite-difference convergence,
   identifiability, physical equilibrium parameters, held-out forces/Hessians,
   minimized geometry, ring puckering, all four signed stereocenters, and
   low-energy conformer ordering. Freeze the acceptance policy before selection.
3. **Validate attachment chemistry and interactions beyond water.** Assemble a
   Drude-consistent sugar/backbone fragment for the ordered product; audit charge,
   masses, lone pairs, anisotropy, exclusions, screened pairs, and all changed
   bonded terms. Check both glycosidic boundaries, sugar pucker, relevant coupled
   torsions, base pairing/stacking, and intended ions. The six site/ODW NBFIX pairs
   constrain CPD–water interactions; they do not validate CPD–base or CPD–ion LJ
   interactions. The cyclobutane sp3 LJ assignments remain analogy-based priors.
4. **Qualify full NAMD dynamics.** Resolve the documented psfgen
   `DELETE ANISOTROPY` incompatibility with an audited builder path. Use the
   demonstrated compatible NAMD build initially, full Drude DNA, SWM4-NDP, and
   compatible ions. Start at no more than 1 fs, verify thermostat/Drude temperature,
   displacement bounds, finite forces, timestep sensitivity, restart continuity,
   and stereochemical retention. Spot-check total energies and nuclear forces
   across engines in addition to the completed induced-response comparison.
   Earlier 2 fs additive smokes and ordinary-DNA HMR/4 fs work are not evidence here.
5. **Test solution ensembles and the intended weld context.** Progress from the
   attached fragment to a short DNA system and the actual extra-base interstrand
   junction, with matched unwelded controls, independent seeds, and sampling
   uncertainty. Measure local pairing, stacking, hydration, sugar/backbone
   distributions, distortion, and the weld's bend/twist compliance. A canonical
   cis-syn structure is not an experimental anti-junction reference. A d(TpT)
   boundary test does not replace the intended interstrand context. Extend
   sampling according to uncertainty and transitions rather than an arbitrary
   trajectory length. Report unavailable experimental validation explicitly.
6. **Release by stereoisomer, context, and observable.** Require reproducible
   artifacts, redistributable assets, correct registry/model-family metadata,
   and a recorded release decision. Keep the cis-syn additive comparator track
   independent; consult `cpd_parameterization_literature_reassessment.md` for its
   proposed Ma/van der Vaart comparison and DNA-context validation.

“All the physics right” should mean quantified accuracy for the intended observables
and conditions. These parameters describe an already formed ground-state product.
UV excitation, bond formation, photochemical yield, and cleavage require separate
reactive/excited-state evidence; geometrical proximity is not a calibrated reaction
rate. Product-mechanics validation alone cannot settle those questions.

Primary references checked for this assessment:

- [Xu et al., modified-ribonucleotide parameterization](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/): additive water-target scaling and subsequent aqueous validation.
- [Baker et al., Drude nucleic-acid bases](https://pubmed.ncbi.nlm.nih.gov/21166469/): validation includes base–base/base–water energies, vibrations, crystal properties, and electrostatic response.

Local evidence: `anti-cpd-drude-electrostatic-fit-v3/stage_assessment.json`,
`anti-cpd-drude-water-fit-v2/policy.json`, `pipeline_status.json`,
`p4_readiness_assessment.json`, and `watch_collect_score.sh`, plus
`docs/cpd_qm_fragment_campaign.md` and the product registry. Historical scientific
results were reviewed, not rerun. No application test suite was needed for this
assessment-only documentation change.
