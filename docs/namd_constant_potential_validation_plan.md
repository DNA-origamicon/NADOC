# Constant-potential gold: literature benchmarks and approval plan

2026-09-15 — **Proposal for review; no constant-potential implementation or benchmark runs performed in this review.**

For the separate biological-interface literature search, see [charged gold with proteins, DNA and lipids](charged_gold_biomolecules_literature_review.md). It adds adsorption and polarization-compatibility checks to the numerical benchmark plan.

## Recommendation

Implement a fixed-site, Gaussian-charge ideal-metal reference model first. Validate its charges, energies and forces independently before assessing aqueous gold capacitance. Then reproduce a published gold system with its original parameters, followed by a separate transfer assessment for NADOC's IFF Au / TIP3P / CUFIX model.

The current fixed-charge Debye screening results do not establish constant-potential correctness: they cannot test local induced charges or whether every site on each electrode has the prescribed potential. Their short-time statistical limitations also remain unresolved.

See the [NAMD implementation design](namd_constant_potential_design.md) for equations and the native source audit. The current GPU correction interface does not supply the required engine charge setter. Native charge propagation, self-energy refresh and slab corrections remain implementation work.

## What the literature and reference implementations actually test

| Benchmark | Evidence and observable | Proposed use |
| --- | --- | --- |
| Tiny charged periodic capacitor | LAMMPS ELECTRODE `madelung` examples compare an independent lattice calculation with computed charges, energy, potential terms, forces and matrix quantities. | First numerical reference: exposes sign, unit, Gaussian self-interaction and periodic electrostatics errors. |
| Empty parallel-plate capacitor | ELECTRODE `planar` examples compare vacuum capacitance with continuum theory using several electrostatic boundary treatments. | Compare the identical discrete model across implementations first; examine convergence toward the continuum limit as separation increases. |
| Charge fluctuations and capacitance | Scalfi et al. derive the extra empty-capacitor contribution required when electrode charges are minimized. | Compare the slope of mean charge versus voltage with the corrected fluctuation expression. |
| Gold / aqueous NaCl charging | Ahrens-Iwers et al. report equilibrium capacitance and charging response for a gold capacitor adapted from MetalWalls. | A concrete wet-gold reference after matching the complete recipe. |
| Gold / electrolyte capacitance and response | Pireddu et al. provide MetalWalls and LAMMPS input examples and processed equilibrium/response data. | Preferred later reproducibility dataset; begin with equilibrium quantities, then charging dynamics. |

Primary implementation assets: [pinned ELECTRODE examples](https://github.com/lammps/lammps/tree/c8bd2ae5927ee236a8892dbd51c18a92cc9c33cf/examples/PACKAGES/electrode). The example scripts report differences; they do not justify a universal percentage acceptance threshold. The upstream direct-sum script uses a very large image range, so a bounded convergence study is needed before executing it locally.

### Specific published targets and their limits

**Ahrens-Iwers et al. (2022):** the three-layer gold / saline capacitor has reported cell capacitance per area of **2.94 μF/cm²** under constant potential at **2 V**, and **2.91 μF/cm²** under constrained electrode charge at **4.4 e**. These are recipe-specific cell values, not universal gold or single-interface capacitances. The supporting protocol includes 5 ns of zero-bias equilibration and 100 charging starts. Full dynamical reproduction therefore exceeds the short diagnostics proposed below. [Paper and supporting information, DOI 10.1063/5.0099239](https://arxiv.org/html/2203.15461)

**Scalfi et al. (2020):** for minimized electrode charges, capacitance contains both a charge-variance contribution and an empty-capacitor term. In consistent electrical units, this is `Cdiff = β Var(Q_BO) + Cempty`. A vacuum capacitor is an especially useful check: its minimized charges have no thermal variance, but its capacitance is nonzero. Finite charge width and lattice structure affect the effective electrical separation, so an atomic capacitor need not exactly equal `ε₀ A / d` at small gaps. [Charge fluctuations in the constant-potential ensemble, DOI 10.1039/C9CP06285H](https://arxiv.org/abs/1911.09351)

**Pireddu et al. (2024):** the published gold / NaCl study uses SPC/E water and compares MetalWalls and LAMMPS implementations. Its data release includes input examples, capacitance, charge autocorrelation and charging-response curves across concentrations and separations. This supports a matched simulation benchmark; agreement between engines alone does not establish experimental gold accuracy. [Paper, DOI 10.1073/pnas.2318157121](https://pmc.ncbi.nlm.nih.gov/articles/PMC11067016/) · [Author data and input archive](https://zenodo.org/records/10958682)

The 451 MB Pireddu archive's inventory was inspected, but the archive was not downloaded and its full parameters have not been audited. This is a pending preparation step, not an already reproduced reference.

## Model and boundary choices to freeze before comparisons

- Use the selected reference's Gaussian convention, width, self-energy and interaction kernels explicitly. Width is a physical model parameter, not a PME tolerance. The inspected LAMMPS `au-aq` example uses `eta = 1.805132 Å⁻¹`; this is a reference setting, not a universal gold calibration.
- Audit the exact water model: the package README identifies SPC water, whereas the 2024 study uses SPC/E. Neither can be silently replaced by our TIP3P recipe for a numerical reproduction.
- Match gold geometry, electrolyte composition, LJ parameters, mixing rules, exclusions, voltage convention and Coulomb constants. State whether reported capacitance belongs to the complete cell or one interface.
- Match electrostatic boundaries. The inspected aqueous LAMMPS example uses a finite-field formulation; the proposed NAMD implementation uses slab-corrected electrostatics with vacuum padding. Use matching slab references first, or explicitly demonstrate boundary equivalence before comparing wet observables.
- Keep electrode sites and the cell fixed initially so the electrode interaction matrix is reusable. Defer moving gold and finite-metal-screening extensions until the ideal-metal implementation passes.

The point-charge/hardness formulation is a possible later optimization, but its agreement with the chosen Gaussian model must be demonstrated under our conditions. [Sitlapersad et al., DOI 10.1063/5.0171502](https://doi.org/10.1063/5.0171502) · [Official ELECTRODE model documentation](https://docs.lammps.org/fix_electrode.html)

## NAMD acceptance checks

The following are our engineering tests derived from the constant-potential energy and existing source audit; they are not presented as a verbatim published test suite.

1. **Independent snapshot comparison:** compare per-atom electrode charges, electrostatic energy components and electrolyte forces against a converged independent Gaussian calculation and pinned LAMMPS. Include asymmetric electrolyte positions, rather than only a symmetric empty capacitor.
2. **Constraint checks:** report maximum and RMS site-potential residuals in volts after accounting for the common neutrality multiplier, total charge error in elementary charges, and invariance to adding the same voltage to both electrodes. Bias reversal is a symmetry test only for an appropriately symmetric fixture.
3. **Force consistency:** finite-difference the minimized voltage-controlled energy `G = U − vᵀq`, re-solving charges at every displaced coordinate. Refine the displacement and solver accuracy. Track short unthermostatted integration behavior using the corresponding energy, including voltage-source work.
4. **Native charge propagation:** change electrolyte coordinates and voltage, then compare an updated process with a fresh process at the same snapshot. Verify real-space, reciprocal-space, self-energy and slab terms all see the new charges. A small solver residual alone cannot detect a consistently wrong electrostatic operator.
5. **Restart consistency:** preserve charge model and operator provenance, electrode grouping, voltage, coordinates, velocities and cell. Recompute restart charges and compare same-state forces and energies; retain the diagnosed `COMmotion yes` treatment. Do not require long chaotic trajectories to remain identical.
6. **Numerical convergence:** refine direct-sum bounds, PME settings, vacuum padding and charge-solver tolerance. Record charge, force and energy differences with the independent reference's own convergence uncertainty.

**Threshold policy:** no arbitrary “within 5%” or fitted Debye-length gate. Determine numerical tolerances from reference convergence and the intended observable accuracy, then freeze them before assessing the final candidate. For wet observables, use stationarity checks, correlation-aware block uncertainties and independent starts. A trajectory ending successfully is a prerequisite, not a physical validation result.

## Proposed approval scope

### Stage A — reference fixtures and native implementation

1. Pin and inspect complete reference inputs; record model equations, parameters, hashes and boundary conventions. Build bounded double-precision reference calculations and run the tiny charged and empty-capacitor LAMMPS cases.
2. Implement an isolated experimental NAMD build with fixed gold sites, neutral total cell, two prescribed electrode potentials and charge minimization at every force evaluation. Complete GPU charge propagation, self-energy refresh, slab consistency and restart provenance.
3. Run the static acceptance checks and short native diagnostics. Proposed ceiling: **4 additional local GPU-hours; at most 1 ns per diagnostic trajectory**. These are resource limits, not convergence criteria. Report achieved checks and unresolved failures at the limit.

Deliverables: reproducible fixtures, reference and engine hashes, charge/force/energy convergence results, restart evidence and a clear pass/open assessment. This scope is awaiting approval; no new native development or simulations were started during the review.

### Stage B — matched aqueous gold validation

After Stage A, select a fully audited published recipe and estimate the sampling cost. Reproduce mean charge versus voltage, cell capacitance and the corrected charge-fluctuation relation. Add charging response once equilibrium sampling is established; impedance is a later, more demanding target. Request a separate sampling budget based on measured performance rather than promising full literature reproduction within the short diagnostic cap.

Then assess transfer to NADOC's IFF Au / TIP3P / CUFIX recipe, including density and screening profiles. Differences following a force-field change are model-transfer questions and must not be disguised as solver failures or removed by tuning the charge width to a Debye fit.

## Review provenance

Small upstream input and script files were inspected at LAMMPS commit `c8bd2ae5927ee236a8892dbd51c18a92cc9c33cf`. Their URLs and SHA-256 hashes are recorded in [the reference asset inventory](audits/constant_potential_reference_assets_20260915.json). Local downloaded papers and inspected assets are cached under `.development-artifacts/constant_potential_review_20260915/`. No reference examples were executed during this review.
