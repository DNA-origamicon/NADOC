# Debye screening assessment — 2026-09-14

## Current status and scope

All three 40 ns solvent-only trajectories completed normally: local RTX 3080 Ti,
RunPod RTX 4090, and Alpine RTX PRO 6000. Alpine Slurm allocation 32557806 reports
COMPLETED, exit 0:0, elapsed 1:54:11. Its 47 selected output files (9.344 GB) were
downloaded and matched against remote SHA256. Its NADOC job reports completed
with verified downloads. RunPod's 36 selected files (9.322 GB) were retrieved using
podless S3; remote sizes, complete DCD time axis and local hashes were checked.
Each production trajectory contains 20,000 frames at 2 ps cadence, with 20,001 finite
energy records through step 10,000,000. Both remote force and restart probes passed.

These are jobs in `2electrode_solvent_only.nadoc`: local created 10:43:27 MDT,
Alpine 10:52:43 MDT, RunPod 10:52:44 MDT. They share their initial prepared state
and random seed; they are hardware duplicates, not independently equilibrated replicas.

The present model has 38,644 atoms, 11,772 explicit waters, 64 Na+ and 64 Cl−,
a 6 nm electrode gap, 64 nm² electrode area, and fixed charges ±16e
(±0.25 e/nm², about ±0.0401 C/m²). The 300 mM setup target becomes 276.8 mM
when counted over the entire geometric compartment; the measured central ionic
strength is 317–324 mM. The cell is padded to 18 nm along the normal, with EW3DC
slab correction and repulsive barriers. Ordinary rigid-water masses, 4 fs steps,
300 K thermostat and fixed-cell production were used. No DNA or PEG is present
in these screening tests.

## What the experiments established

1. Initial small-cell and window-length trials exposed sparse-ion statistics and
   density/loading failures. Short-window gate passes were not sufficient to
   establish equilibration.
2. The 240 ps lateral-volume screen increased ions/species from 10 to 22 to 39.
   Larger counts improved distribution statistics, but the larger cases failed the
   unchanged density criterion; they were not qualified as production seeds.
3. Matched 2.64 ns tests compared 4 and 6 nm gaps. The 4 nm pooled fit looked
   plausible (0.573 nm) despite separate chunks giving 0.405 and 1.745 nm.
   The 6 nm fit was better identifiable but still unstable (0.580 then 0.819 nm).
4. Moving slab/wall forces from the CPU bridge to GPU preserved independently
   checked forces and energies. The matched 2 fs benchmark improved from
   43 ns/day to approximately 291–297 ns/day; 4 fs subsequently enabled practical
   long sampling. This is numerical implementation validation, not a change in physics.
5. The managed short campaign completed 9.84 ns at 4 fs plus a 1.20 ns 2 fs control.
   Fits of 0.519, 0.597 and 0.604 nm remained too variable to determine timestep bias.
6. The three 40 ns trajectories substantially improve screening-length consistency.
   They do not by themselves establish salt scaling, timestep independence or a
   quantitatively calibrated metal interface.

## Long-run results

Fits use the finite-gap odd ion-ratio profile, excluding 0.6 nm at each wall.
Classical comparisons use the measured central ionic strength, 300 K and assumed
relative permittivity 78.3. Bootstrap intervals below use 300 ps blocks and are
conditional on sufficient block independence and stationarity.

| Run | Full 40 ns fit, nm | Bootstrap 95% interval, nm | Classical, nm | Difference | Last 20 ns fit, nm |
|---|---:|---:|---:|---:|---:|
| Local | 0.553 | 0.529–0.580 | 0.536 | +3.3% | 0.558 |
| RunPod | 0.551 | 0.528–0.580 | 0.539 | +2.3% | 0.556 |
| Alpine | 0.575 | 0.552–0.602 | 0.541 | +6.3% | 0.547 |

Alpine's successive 10 ns fits are 0.631, 0.580, 0.565 and 0.528 nm. This downward
trend makes its full-run average less convincing as an equilibrium estimate;
its classical comparator is outside the conditional full-run interval. The last
20 ns fits agree across hardware to about 2%, but selecting this interval after
inspection is exploratory, not an independently validated equilibration cutoff.

Ionic half-cell compensation is 96.7–97.1%. Central all-charge field estimates
are −0.82 ±1.11, −1.12 ±1.20 and −1.86 ±1.15 mV/nm (300 ps block SEM).
These do not resolve a small residual field precisely. A symmetric zero of
potential at the midplane does not establish zero field.

RunPod bootstrap sensitivity using 0.6–2.4 ns blocks gives intervals approximately
0.517–0.588 nm. The fitted length also varies only 0.540–0.551 nm across the
0.5/0.6/0.8 nm wall exclusions. These are useful robustness checks. Block counts
fall to 16 at 2.4 ns, and a stationarity assumption remains necessary.

## Comparison with literature and omitted physics

There is no universal acceptance percentage supplied by the papers reviewed.
Our 2–6% conditional agreement is a useful engineering check of diffuse ion
screening. It does not constitute a matched reproduction of a published electrode
model or validate every electrostatic observable.

- **Dielectric response and timestep:** our comparison assumes ε=78.3, while the
  actual salt/water force-field response has not been measured. Using ε=100 would
  give about 0.605–0.612 nm instead. The short control measured water translational/
  rotational temperatures of 300.18/294.18 K at 4 fs, versus 300.25/298.93 K at 2 fs.
  [Asthagiri et al., Chemical Science 2025](https://pubs.rsc.org/en/content/articlehtml/2025/sc/d4sc08437c)
  demonstrate timestep-dependent equipartition, volume and dielectric errors in
  rigid-water simulations. Longer sampling does not remove this systematic effect.
- **Diffuse layer versus microscopic potential:** explicit water orientation,
  hydration, excluded volume and classical ion correlations are already present.
  They need not follow a uniform-dielectric continuum close to the surface.
  [Water molecules mute the dependence of the double-layer potential profile on ionic strength](https://pubs.rsc.org/en/content/articlehtml/2023/fd/d3fd00114h)
  uses constant-potential Pt/SPC/E simulations and shows how molecular water can
  dominate the potential profile. Agreement of an ion-ratio decay length therefore
  cannot validate the full interfacial potential. Our near-wall profiles visibly
  deviate from continuum PB.
- **Force-field-specific salt behavior:**
  [Tavakol and Voïtchovsky, PCCP 2026](https://pubs.rsc.org/en/content/articlehtml/2026/cp/d5cp03058g)
  find that silica/NaCl comparisons depend on model dielectric and Stern-layer
  charge; ion pairing complicates their comparison above roughly 0.21 M. That is
  a result for their system, not a universal cutoff. Our central concentration is
  about 0.32 M, so testing lower salt and measuring pair statistics is preferable
  to demanding exact Debye–Hückel agreement here.
- **Gold and applied voltage:** the walls do not respond as conducting gold.
  Missing elements include spatially induced electrode charge/image response,
  constant-potential charging, gold–water/ion interactions, specific adsorption,
  reconstruction and electronic charge transfer. Not all require QM for the next
  stage: a classical constant-potential model is a useful intermediate step.
  [Park and McDaniel, J. Phys. Chem. C 2022](https://pubs.acs.org/doi/10.1021/acs.jpcc.2c04910)
  simulate Au(100)/NaCl at fixed voltage and show that polarizable and
  nonpolarizable force fields can yield different microscopic structures even
  when capacitance profiles are similar. Our present tests do not calibrate gold
  capacitance, voltage-dependent DNA forces, charging kinetics or transport.
- **Finite size and boundaries:** the 6 nm gap is about eleven fitted screening
  lengths. Finite-inventory PB predicts a small, nonzero midplane field; the gap
  is not presently the main demonstrated limitation. Normal padding and gap were
  previously changed together, so padding/PME and lateral-size convergence remain
  separate tests. The established
  [Yeh–Berkowitz slab method](https://doi.org/10.1063/1.479595)
  supports the chosen correction; GPU/CPU arithmetic agreement does not itself
  prove convergence with padding or mesh spacing.

## Recommended next steps

Prioritize controlled validation over another larger or longer 4 fs box:

1. Extend a matched 2 fs control from independently prepared equilibrated starts;
   add a shorter 0.5–1 fs reference to quantify timestep sensitivity. Measure bulk
   water/salt dielectric response using the same model, density and integrator,
   with boundary conditions appropriate to that measurement.
2. Add a neutral-wall control and a modest salt series, using measured accessible/
   central concentrations. Test the expected approximate inverse-square-root salt
   dependence and distinguish interfacial polarization from diffuse screening.
3. Vary normal padding/PME precision at fixed physical geometry; use independently
   prepared seeds to assess the residual Alpine-like time trend.
4. For exploratory PEG brush mechanics, the abstract fixed-charge wall is a
   defensible starting model if its scope is stated. For quantitative gold-contact
   predictions, introduce and validate constant-potential metal response and the
   relevant surface/linker interactions. PEG/DNA hydration, ion partitioning and
   force–compression curves then require their own tests; none are measured by
   these solvent-only runs.

[All hardware comparison plots and per-window results](../workspace/electrode_remote_40ns_20260914/RESULTS.md)

Historical failed and completed jobs remain under the documented Archive location;
see [archive inventory](namd_electrode_archive.md). No new simulation was launched
for this assessment.
