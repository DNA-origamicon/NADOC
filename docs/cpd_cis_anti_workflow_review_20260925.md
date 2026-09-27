# Cis-anti-I QM → NAMD review, 2026-09-25

**Decision scope:** the user confirmed a preliminary additive NAMD model for
exploratory structural simulations, with documented limitations. The intended
context remains the ordered interstrand pair in `2hb_1xT_CPD`. Quantitative weld
mechanics, equilibrium free energies, photochemistry, other stereoisomers and
general force-field release are separate deliverables.

**Recommendation:** retain the useful evidence and correct the fitting strategy
before generating more targets. The campaign has not demonstrated that additive
CHARMM is incapable of meeting this scope. It has demonstrated failed transfer
of particular candidates and a genuine unresolved QM optimization. Neither a
fresh start from zero nor another continuation of the stalled job is justified.

At the time of writing this was a review and proposed replacement scope, **not
an activated policy**. The user's subsequent explicit resume activated
[protocol v2](cpd_preliminary_protocol_v2.md); see the separate
[execution results](cpd_anti_resume_results_20260925.md). The statements below
describe what this review itself did.
No QM, MM minimization, fit or MD was run. The pause receipt, launch guards,
validation v1, parameter assets and product registry remain unchanged. Historical
failed verdicts remain failed. A replacement preliminary protocol must be
implemented explicitly before execution; do not bypass v1's guards.

## What is actually available

The [closeout](cpd_anti_closeout_20260925.md), [campaign](cpd_anti_additive_campaign.md),
[fixed protocol](cpd_validation_protocol.md), fitting code and selected native
audit records were reviewed. Artifact names below are relative to
`.development-artifacts/`, currently linked to the Archive drive.

| Component | Existing evidence | Meaning for the next milestone |
|---|---|---|
| Chemical identity | Corrected anti fragment graphs and ordered stereochemistry are carried through the recent audits. | Reuse them. Full DNA assembly still needs its own mapping, charge and topology audit. |
| QM reference structures | Both original 49-atom sugar-boundary models have stationary geometries, positive harmonic spectra and tighter directional checks. | Usable local-reference evidence exists. Endpoint-1's lowest original frequency is not precision validated. Local minima do not prove global minima. |
| Local MM geometry | The three remote-coupled candidates reach maximum endpoint angle errors 2.702–2.726° and bond errors reported ≤0.0261 Å. All nine core/boundary systems pass recorded MM stationarity, two-step curvature and CHARMM-export checks. | Local fitting and export work. This does not establish conformational energies or NAMD DNA integration. |
| Electrostatics | The least-regularized three-conformer charge trial has maximum water-energy errors 1.277 and 1.553 kcal/mol on the original endpoints and 1.214 kcal/mol on the remote conformer. | It misses even v1's practical 0.5 kcal/mol criterion on these development targets. The problem is not solely an unusually demanding blind orientation. |
| Conformational energies | After correcting the QM reference, the −30° comparison improves to 0.740–0.861 kcal/mol error, but remote comparisons still differ by −7.653 to −8.550 kcal/mol. | Serious unresolved discrepancies. These compare lowest observed branches with incomplete full-conformer matching; they are not certified global-minimum errors. |
| Latest +15° QM branch | 60 evaluations and the sole 20-new-evaluation continuation exhausted. Projected max/RMS gradients 2.74580e−4 / 9.14524e−5 au. | Not converged. Retain as unresolved coverage; do not call it an excluded high-energy point. |
| Full anti NAMD system | No anti DNA validation in this additive parity campaign. | Fragment export is not evidence of a usable interstrand system. |

Key records: `cpd-anti-remote-coupled-v1/independent_review.json`,
`cpd-anti-remote-coupled-verify-{1,10,100}-v1/assessment.json`,
`cpd-anti-multiconformer-water-charge-v1/assessment.json`,
`cpd-anti-refined-basin-qm-v2/energy_comparison.json`, and
`cpd-anti-lower-profile-restart-v1/{method_review,coordinate_review}.json`.
This review verified 33 candidate review/system/geometry/PSF/parameter hash links;
it did not recompute the reported energies, forces or Hessians.

## What the primary literature actually establishes

The literature supplies target conventions and validation methods. It does not
provide a universal numerical certificate that an arbitrary cis-anti force field
is accurate, or guarantee that a given functional form can satisfy every target.
The proposed stage boundaries below are our engineering decisions, distinguished
from published numerical guidance.

| Primary source | Relevant evidence | Appropriate use here |
|---|---|---|
| [Vanommeslaeghe et al., CGenFF (2010), Scheme 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/) | Bond/angle deviations of 0.03 Å/3° are generally acceptable; 0.2 kcal/mol water-energy agreement is described as ideal. Charges, internal geometry, vibrations and torsions form an iterative workflow. | Retain geometry targets at representative minima. An ideal fitting target is not automatically a maximum-error requirement for every arbitrary validation configuration. |
| [Mayne et al., ffTK (2013), charge/bond/dihedral methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC3874408/) | Water-energy/distance objective scales are 0.2 kcal/mol/0.1 Å. Bonds and angles target geometry and distortion energies; dihedrals target relaxed scans. The MP2 Hessian is scaled by 0.89. Bidirectional scans can retain useful low-energy segments when high-energy traversal fails. | Fit the actual objective being assessed. Positive MM curvature alone does not show agreement with QM stiffness. A failed point is usable as neither a converged energy nor an inferred high-energy exclusion. |
| [Xu et al., modified ribonucleotides (2016), parameterization and dipole sections](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/) | Uses unscaled HF dipoles as fit targets, transferred LJ terms, and torsion optimization emphasizing energies below 12 kcal/mol. Rechecks torsions after other parameters change. Some methyl-capped bases have underestimated MM dipoles; solution validation informs refinement. | This is the closest parent-family workflow. A universal 1.2–1.5 dipole-ratio requirement conflicts with this published implementation. Low-energy torsion fitting and molecular context matter more than exact reproduction of every vacuum diagnostic. |
| [Qiu et al., TorsionDrive (2020), method](https://pmc.ncbi.nlm.nih.gov/articles/PMC7320903/) | Propagates newly available or improved lowest-energy grid structures to neighbors; stops when no active points remain. Supports multiple seeds, bounded scan ranges and energy upper limits. | Use an established acquisition algorithm. It does not demand exhaustive certification of every retained stationary branch or prove global optimality. |
| [CGenFF 5 development (2025), water/dipole results](https://pmc.ncbi.nlm.nih.gov/articles/PMC11938330/) | Reports error distributions and difficult water orientations; optimized water-distance RMSD is 0.18 Å over its broad dataset. Its dipole convention includes scaling. | Published implementations differ. Select one coherent convention before fitting; broad benchmark averages cannot certify this CPD or justify ignoring its outliers. |
| [Su et al., interstrand-type cis-anti thymine dimer (2008), structural assignment](https://pmc.ncbi.nlm.nih.gov/articles/PMC2724876/) | Experimental stereochemical assignment of a nonadjacent cis-anti photoproduct using MS and NMR. | Relevant identity evidence exists. This acidic-pH oligonucleotide is not an experimental structure or mechanical benchmark for the origami junction. Do not equate its structure labels with NADOC's ordered labels without an atom map. |

## Why the previous workflow kept expanding

**The fitted degrees of freedom did not address the main residual.**
[`refine_joint.py`](../experiments/cpd_anti_additive/refine_joint.py) changes bond
and angle equilibrium values. Its geometry-response calculation uses an MM
Hessian to differentiate the objective; it is not a fit of that Hessian to QM.
Recent remote-coupled rounds keep force constants and torsions fixed. A good
minimum can therefore coexist with a poor conformational landscape. Further
angle/charge sweeps are not a substitute for fitting the changed torsions.

**The charge objective and acceptance objective differ.**
[`multiconformer_water_charge_fit.py`](../experiments/cpd_anti_additive/multiconformer_water_charge_fit.py)
uses ESP blocks scaled by 0.005 au and three points near each water minimum,
scaled by 1 kcal/mol, plus regularization. Dipoles are calculated afterward;
neither dipole agreement nor the actual MM minimum distance is directly fitted.
This does not prove that ESP dominates numerically, but it does mean the optimizer
is not minimizing the full acceptance objective. Methyl-H shifts are constrained
to be equal but may vary; their chemical compatibility also needs review before
changing more charges. The recent additive water protocol already specifies
uncorrected HF interactions, 1.16 scaling and the distance offset: preserve that
coherent target definition rather than importing the older Drude conventions.

**The new validation contract grew beyond the preliminary scope.**
V1 has 94 records: 63 acquisition, 28 prospective holdouts and 3 exports.
It requires all branches, all relevant bond/angle limits at profile points,
all-heavy-torsion basin matching, and mandatory dipole ratios. These are local
decisions, not a published package of minimum requirements. In particular,
propagating every newly found basin, even when it is not lowest, is stronger than
the TorsionDrive algorithm. Extra tests can reveal useful limitations without
each becoming a new prerequisite for the same milestone.

**Some discoveries were necessary corrections, not goalpost changes.**
The former anti/syn graph problem, genuinely lower QM conformers, mixed-site water
contacts and inconsistent reference energies materially change the interpretation.
They cannot be waived. The current +15° gradient is far above the stationary-point
limit; a repeat-gradient mismatch near 1e−6 au does not by itself explain a plateau
near 2.7e−4 au. The cached Jacobian audit found full rank and the expected graph,
but did not validate the optimizer's constrained step. The cause remains unresolved.

## Proposed finite milestones

Use separate statuses for reference adequacy, parameter adequacy, engine validity
and preliminary context support. This table defines the recommended scope; it is
not a claim that any missing stage has passed.

| Stage | “Good enough” to advance | Stop/failure condition |
|---|---|---|
| 1. Reference set for fitting | Correct graph/map/stereo; converged representative local minima; an explicit finite scan/seed manifest covering both glycosidic boundaries and known competing low basins; consistent methods and energy references. Reuse qualified cached results. | A required low-energy branch remains unresolved or cannot be matched. Do not demand a proven global minimum or arbitrarily precise soft frequencies. |
| 2. Preliminary parameter candidate | Literature geometry targets at registered representative minima; a water/dipole objective following one declared CHARMM convention; changed torsions fit to the registered low-energy PES; independent configuration checks and complete outlier report. | Known large energy errors persist, chemistry is distorted, or numerical/identity checks fail. No acceptance by training geometry alone. |
| 3. NAMD implementation candidate | Complete two-residue interstrand patch and parameter coverage; correct charges/exclusions/impropers; energy/force checks at multiple registered geometries; staged explicit-solvent startup preserves all stereocenters. | Missing terms, incorrect connectivity, sign inversion, nonfinite forces, unexplained engine disagreement or integration failure. This stage establishes an engine candidate only. |
| 4. Preliminary exploratory support | Fixed anti/undamaged replica campaign in the intended junction passes the registered numerical/chemical checks. Report structural variability, sampled conformations, sensitivity and all limitations. Portable assets and provenance accompany the model. | Numerical failure, chemical corruption or systematic occupation of a known badly represented low-energy state. Insufficient equilibrium sampling limits claims; it does not automatically trigger endless extensions. |

Recommended quantitative choices for the replacement preliminary policy:

- Retain **0.03 Å / 3°** at representative optimized structures for the changed
  lesion and attachment terms. Report unchanged sugar/backbone discrepancies;
  avoid refitting parent DNA chemistry merely to match one isolated vacuum cap.
  The measured geometry of a minimized molecule, not a raw equilibrium constant,
  is what is compared.
- Retain v1's local **0.5 kcal/mol and 0.2 Å maximum errors** for the fixed clean
  polar water fitting set; also report the ideal 0.2 kcal/mol score. These are
  prospective local acceptance limits, not universally published cutoffs. Existing
  1.2–1.6 kcal/mol residuals still fail. Extra azimuth tests measure transfer and
  need a declared role; do not silently convert all of them into new hard gates.
- Adopt the modified-nucleotide **direct HF dipole-target convention**, with
  explicit objective weights and charge restraints. Report magnitudes/directions
  and cap effects; remove mandatory 1.2–1.5 ratios from this proposed preliminary
  policy. This is a documented method change, not a retrospective v1 pass.
- Retain local **≤1 kcal/mol RMSE and ≤2 kcal/mol maximum error** for the fixed
  relevant energy-validation set. Define its members and low-energy window from
  QM/chemistry before fitting, include known competing low basins, and report
  training and validation separately. A 12 kcal/mol QM window is a literature
  precedent for weighting, not evidence that every point outside it is irrelevant
  in the DNA environment. Missing QM must never be assigned an inferred energy.
- Keep v1's **1e−5 kcal/mol energy / 1e−4 kcal/mol/Å force** export tolerances
  for the existing static export comparison. These are local engineering bounds.
  Pin engine settings and numerical precision before native NAMD comparisons;
  do not infer a NAMD test from an OpenMM reload of exported files.
- Keep ordinary masses and **≤2 fs**. Retain the already proposed **100 ps pilot,
  then three 10 ns replicas per condition**, anti plus matched undamaged junction.
  This is a bounded local research budget, not a published convergence threshold.
  Record a wall-time cap before launch. A new interstrand cis-syn qualification
  should not become a prerequisite: existing syn support covers adjacent
  intrastrand DNA. Its existing fixture remains a useful software regression.

For stage 4, keep the existing chemistry/numerical screens, including all saved
stereocenters, finite energies, bond excursions and thermostat/density checks;
check periodic-image clearance throughout. Track lesion-local geometry, sugar/
glycosidic states, contacts/opening and between-replica differences. Anti need
not resemble syn or maintain every initial base pair. A 10 ns stable trajectory
does not establish equilibrium populations, reaction rates or mechanical accuracy.

An isolated engineering smoke can be useful before stage 2 is complete if a new
policy explicitly permits it, with known failures attached and no preliminary
research promotion. The user-facing exploratory model requires both parameter
and context evidence. A successful NAMD exit cannot erase the existing energy
and hydration failures.

## Bounded next work, after this review

1. **Finish a cached-data and objective audit first.** Record exact candidate,
   atom types, transferred parameters, water-target conventions, reference
   conformers, exposed data and missing cases. Inspect the stalled constrained
   steps/trust model from saved evaluations. Do not resume +15° unchanged.
2. **Replace the contract deliberately.** Write one versioned preliminary
   protocol with exact case IDs, fitting terms, target weights, stage-specific
   numerical rules and budgets. Keep v1 as its historical verdict. Finalizing
   this manifest is required before the next calculation; this review is not
   an executable case manifest or an instruction to collect all 94 records.
3. **Acquire only identified missing reference evidence.** If scans are needed,
   use the established multiseed wavefront algorithm with a finite declared
   domain. Keep old branches for diagnosis without requiring exhaustive closure
   of all branches. The unresolved low-basin +15° point must be resolved or its
   relevance assessed explicitly; it cannot simply be discarded to advance.
   Full tight Hessians at every scan point, every water azimuth and a Drude
   campaign are not default next steps.
4. **Use a conventional, bounded fit.** Fit water minima and dipoles coherently,
   regularize toward transferable CHARMM chemistry, then fit the minimal changed
   torsion basis jointly over both boundaries. Treat coupled ring terms together;
   retain unchanged sugar/phosphate and transferable LJ parameters. Check local
   geometry/response again after torsion fitting. Do not compensate a cap clash
   by arbitrary LJ softening or an unconstrained torsion expansion.
5. **Assemble and test the actual two-strand chemistry.** Each T retains its own
   sugar/backbone; the pair gains the anti C5–C6/C6–C5 links. Do not use an adjacent
   d(TpT) phosphodiester connection as the interstrand model. The frozen site is
   currently a syn placement, not usable anti starting coordinates. Prepare the
   concrete isolated molecular review artifact before normal app integration,
   as required by the existing geometry policy.

Keep the existing **two fit rounds maximum per functional model** and **one
evidence-supported optimization continuation** rules. A second fit needs a
specific residual-based change and improved development performance; repeated
regularization sweeps do not reset the count. Register a candidate before using
prospective validation. Once inspected, failed holdouts become development data.
Do not replace them repeatedly until a favorable set appears.

When a budget is exhausted, record **pass**, **fail**, or **incomplete** for that
stage and stop that branch. New data, a new functional form or changed thresholds
belong to a separately scoped decision with an explicit cost; they do not extend
the same milestone automatically. If the corrected additive workflow still fails,
retain an engineering candidate only and report that preliminary structural
qualification was not achieved within the declared scope and budget.
