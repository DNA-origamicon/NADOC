# Phase 1 items 2–4: calibration, electrode design and qualification review

2026-09-15. **The authorized local calibration and feasibility work is complete.**
This supplies measured preparation recipes and an implementation design; it does
not qualify gold adsorption or voltage-controlled NAMD production.

## Results

- Two independent bulk NPT references give a mean of **33.760 waters/nm³**
  for the actual 298.15 K TIP3P/CUFIX setup. The approximate 33.4 reference is no
  longer used as a density target for these controls.
- Bulk-filled gold slits were strongly depleted in their centers, near 26–27
  waters/nm³. A measured inventory update and a second response-based adjustment
  produced the final independent slit controls below.
- Nanoparticle water inventory was adjusted once, producing independent outer
  densities of **33.736 and 33.699 waters/nm³**.
- Final slits contain **2017 waters and six NaCl pairs** each;
  final particles contain **3431 waters and nine pairs** each.
  Final inventories apply to these specific geometries and bulk-snapshot recipes.
  They are not universal water-loading defaults.

### Final independent controls

Bulk/slit/particle densities mean whole-box, central-1-nm and outer-shell densities,
respectively. Temperatures and concentrations use the same late windows. Bulk and
particle runs last 200 ps; final slit runs last 300 ps. The last half of each run
is analyzed. See the methods for exact volumes and timing.

| Case | Waters / Na / Cl | Density, waters/nm³ | Conditional 95% halfwidth, 20 ps blocks | Na / Cl, mM | Water translation / rotation, K |
| --- | --- | ---: | ---: | --- | --- |
| bulk_317 | 3367 / 9 / 9 | 33.755 | 0.037 | 149.8 / 149.8 | 298.50 / 297.97 |
| bulk_719 | 3367 / 9 / 9 | 33.765 | 0.063 | 149.9 / 149.9 | 298.61 / 297.45 |
| nanoparticle_317_revised | 3431 / 9 / 9 | 33.736 | 0.135 | 130.6 / 69.8 | 298.25 / 298.29 |
| nanoparticle_719_revised | 3431 / 9 / 9 | 33.699 | 0.125 | 163.4 / 124.1 | 298.38 / 297.92 |
| slab_317_calibrated_fixed_ions | 2017 / 6 / 6 | 33.876 | 0.126 | 313.3 / 93.4 | 299.02 / 298.45 |
| slab_719_calibrated_fixed_ions | 2017 / 6 / 6 | 33.907 | 0.091 | 194.3 / 84.3 | 298.02 / 297.65 |

Intervals are conditional sampling estimates, not physical acceptance thresholds.
Only 5–7 complete 20 ps blocks contribute to these final intervals; the 50 ps
analysis has fewer blocks. The block-length sensitivity, separate seeds and early/
late means remain visible in [summary.json](summary.json). A narrow confidence
interval alone cannot establish equilibrium or force-field accuracy.

The bulk pressure check retains instantaneous group-pressure samples at 1 ps.
Their late means are −35.3 and −35.8 bar, with conditional 20 ps-block 95%
halfwidths of 110.1 and 40.8 bar. These noisy short estimates do not demonstrate
precise pressure convergence; the density reference remains a pilot estimate.

### Inspectable evidence

- [Density traces](density_traces.png)
- [Water/ion profiles and water orientation](interface_profiles.png)
- [All initial, revised and final measurements](measurements.md)
- [Methods, definitions, commands and retained failures](README.md)
- [Initial inventory estimate](inventory_revision.json), [slit refinement](slit_refinement.json)
- [Bulk pressure and native temperature samples](bulk_pressure_check.json)
- [Completed-stage integrity audit](integrity_audit.json), [source hashes](source_hashes.json)

Per-case CSV files retain every sampled density, mode temperature and spatial
profile. Complete PSF/PDB inputs, fixed-cell configurations, native logs, coordinate/
velocity trajectories and binary checkpoints remain in their case directories.

## Constant-potential feasibility result

The [NAMD implementation design](../../../../docs/namd_constant_potential_design.md)
identifies a feasible route through new electrostatics development. The current
GPU force plugin receives charges; its charge-buffer interface does not update
native PME charges. A host `reloadCharges` route exists, but per-step resident
updates and cached PME self-energy refresh need explicit native validation.

The design specifies electrode groups, charge neutrality, voltage gauge, the
charge solve, consistent EW3DC energy/force derivatives, GPU synchronization,
checkpoint state, memory scaling and an experimental API. It proposes fixed metal
sites first. No installed engine was modified and no constant-potential solver is
claimed to have been implemented or benchmarked.

## Qualification disposition and next work

The [qualification matrix](../../../../docs/namd_gold_qualification_matrix.md) separates
existing pair/restart evidence, new preparation evidence and the remaining physical
questions. The stale blanket “native validation pending” statement in the abstract
two-electrode guide has been replaced with the actual scope of existing evidence.

1. **Preparation is improved; interfacial physics is still unqualified.** Compare
   larger gaps/solvent extents and independent longer samples before interpreting
   the central/outer region as a bulk reservoir. Match published hydration cases
   using their actual solvent, facet and electrostatic model.
2. **Ion statistics remain a major limitation.** Six or nine ions per species
   produce coarse counts and noisy local concentrations. The nominal 150 mM input
   does not imply a measured 150 mM central compartment. The final slit update fixes
   ion counts to isolate water loading; the rejected five-pair attempt is retained.
   Do not fit adsorption or electrolyte inventory to these short, sparse profiles.
3. **Temperature and numerical qualification remain separate.** Mode temperatures
   are measured rather than judged by an invented tolerance. Longer stationary
   samples and appropriate equipartition/timestep tests are needed for quantitative
   predictions; the preceding 0.5 fs energy-convergence limitation remains open.
4. **Before implementing voltage control**, select and document the electrode
   charge-width/hardness model and matched reference. Then validate native charge
   propagation, charge-dependent self energy and forces on small systems before
   optimizing or integrating a production solver. No assumed universal capacitance
   converts a voltage input into fixed Au charges.

Statistical interpretation follows [Grossfield et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6286151/).
The charge-solver design draws on [constant-potential methods](https://doi.org/10.1063/5.0171502)
and the [ELECTRODE reference implementation](https://doi.org/10.1063/5.0099239),
with the source-level NAMD feasibility conclusions explicitly identified as our audit.

## Cost and verification

The twelve completed dynamics controls total **2.2 ns**, with no accepted trajectory
longer than **300 ps**. Recorded native wall time, including the stopped control and
configuration retry, was **25.55 minutes**
(0.426 GPU-hours allocated to sequential native processes),
well below the four-hour ceiling. The prior restart diagnosis adds about one minute.
No remote compute was used.

Completed native stages passed input-hash, atom/charge accounting, finite energy/
checkpoint, step-count and GPU-resident checks; those are integrity checks rather
than physical qualification. The velocity-DCD unit check matches native kinetic
energy to the expected printed/single-precision scale. Scoped script lint and
`git diff --check` passed. No application/backend behavior changed in items 2–4,
so the full backend and browser suites were not rerun for these isolated experiments
and documentation changes.
