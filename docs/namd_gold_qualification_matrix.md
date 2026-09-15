# Gold / two-electrode qualification matrix

Updated 2026-09-15. This matrix distinguishes numerical implementation evidence,
preparation calibration and physical validation. There is no aggregate score or
automatic promotion based on a short trajectory finishing.

## Evidence by question

| Question | Evidence | Status / remaining requirement |
| --- | --- | --- |
| Are the neutral Au parameters represented correctly? | Prior source audit and five native Au pair probes, including water hydrogens; native force error up to 6.12e-6 kcal/mol/Å. | Arithmetic/native-pair evidence exists. Switching-region and complete interfacial force validation remain separate. |
| Does restarting preserve the saved motion? | The default COM-removal impulse was predicted and measured; newly generated gold restarts preserve COM velocity. Residual split differences resemble repeated uninterrupted GPU runs. | Dominant restart discrepancy resolved. Historical 1e-4 threshold is diagnostic only; partial-stage recovery remains unimplemented. |
| Is the integration physically convergent? | Short NVE controls show approximately quadratic energy-fluctuation reduction from 2→1 fs, but not across 1→0.5 fs. | Partial numerical evidence; no full timestep/precision qualification. |
| What bulk solvent density does this exact setup produce? | Two independent 200 ps NPT references at 298.15 K and nominal 150 mM NaCl: 33.755 and 33.765 waters/nm³ over the last halves. | A measured model-specific preparation reference exists. This is not experimental water-density validation. |
| Does initial gold solvation supply enough water? | Bulk-snapshot-filled slits deplete to 26–27 waters/nm³ centrally; particles are near 32.96. | Initial loading is insufficient. Revised whole-water inventory controls and their uncertainties are in the campaign report. |
| Do revised preparations approach that reference? | Final independent slit central densities 33.876/33.907 and particle outer densities 33.736/33.699 waters/nm³; identical water counts within each geometry, measured profiles. | See final campaign measurements; near agreement of one mean does not qualify a bulk plateau or interfacial physics. |
| Are water modes sampled correctly? | Per-frame molecular translational and relative-motion temperatures, with block summaries and independent seeds. | Measured, not universally passed. Finite sampling and any sustained mode imbalance must be resolved before quantitative predictions. |
| Are concentrations and accessible volumes defined? | Exact water/ion counts, local Na/Cl profiles, geometric volumes, and explicit preparation-based exclusion volumes with Monte Carlo errors. | Definitions are reproducible. Small ion inventories do not qualify adsorption or salt partitioning. |
| Does the gold interface match published hydration or adsorption data? | No matched published solvent/facet/model reproduction in this phase. | Unqualified; create a matched reference package and compare uncertainty before interpreting adsorption. |
| Are size/boundary effects converged? | Prior exploratory controls and current fixed geometry; EW3DC remains fixed-cell. | Unqualified; vary lateral size, gap, padding and mesh independently at controlled inventory. |
| Are the gold electrodes voltage-controlled? | Local source audit and concrete charge-solver/PME design. | Not implemented. Neutral Au and abstract fixed-charge walls do not supply constant potential. |
| Is functionalized gold ready? | Authored linker/display structures exist separately from bare-gold qualification. | Au–S and Au/PEG/DNA cross-interactions require explicit chemistry and validation. |
| Are mobile gold and production workflows ready? | Short prior mobile controls; current inventory work restrains Au. | Long morphology, partial-stage recovery, remote runtime and gold-specific UI integration remain separate work. |

## What to use as acceptance evidence next

1. **Density/preparation:** compare independent preparations with the same-model
   bulk reference, report full density profiles and block-size sensitivity, and
   require enough sampling to distinguish residual bias from uncertainty. Test
   whether the center/outer region is actually bulk-like as geometry is enlarged.
   A universal percentage error is not supplied by the literature.
2. **Integrator and thermostat:** use conservation/timestep convergence and
   appropriate kinetic-energy/equipartition tests. Do not replace them with an
   atomwise restart distance threshold. [Merz and Shirts](https://doi.org/10.1371/journal.pone.0202764)
3. **Uncertainty:** distinguish sampling error from model error, examine time
   correlation/block-length dependence, and use independent preparations. A narrow
   interval computed from too-short blocks is not an equilibration certificate.
   [Grossfield et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6286151/)
4. **Constant potential:** first verify charge updates, energy/self terms and
   forces against an independent electrostatic reference. Then demonstrate
   neutrality, gauge invariance, solver/PME convergence and matched capacitor
   behavior. Define tolerances by reference accuracy and effects on observables.
5. **Gold contact:** select matched published conditions and model assets before
   comparing hydration structure, adsorption or capacitance. Keep TIP3P/CUFIX
   predictions distinct from reproductions using another solvent/ion model.

## Review artifacts

- [Native gold baseline and historical failures](../workspace/gold_validation_20260914/RESULTS.md)
- [Restart diagnosis and correction](../experiments/gold_interfaces/evidence/gold_restart_diagnosis_20260915/RESULTS.md)
- [Solvent calibration methods and retained files](../experiments/gold_interfaces/evidence/gold_phase1_calibration_20260915/README.md)
- [Completed Phase 1 results](../experiments/gold_interfaces/evidence/gold_phase1_calibration_20260915/RESULTS.md)
- [Calibration measurements](../experiments/gold_interfaces/evidence/gold_phase1_calibration_20260915/measurements.md)
- [Constant-potential implementation design and source audit](namd_constant_potential_design.md)
- [Abstract-wall 40 ns screening assessment](namd_debye_assessment.md)

The prior abstract-wall screening evidence is useful for that model. It does not
validate gold contact, image response or an imposed electrode voltage.
