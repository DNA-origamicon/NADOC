# Graphene pressure equilibration and literature check

Implemented after the user approved the cavity-investigation proposal on 2026-09-14. Applies to newly prepared packages; archived fixed-volume jobs retain their recorded configuration. The existing dry cube_pore checkpoint has not been restarted or submitted to Alpine.

## Resulting behavior

New graphene packages use the standard explicit-solvent DNA restraint-release ladder with a pressure target of 1.01325 bar. DNA-plus-wall jobs regain the 500 ps solvent-settling stage. Bare-wall controls retain their single equilibration stage, now with pressure control. The default ladder duration and user-selected integrator/chemistry remain those of the shared DNA recipe.

The two tangential cell dimensions remain fixed. Only the membrane-normal dimension changes. Z-normal sheets use NAMD's constant-area mode; X/Y-normal sheets use its per-axis cell constraints. All six Cartesian normal directions are supported. Non-Cartesian normals are rejected rather than scaling the wrong direction. The scaling origin is placed on the membrane plane **in minimization as well as dynamics**, so the first XSC and subsequent restart chain inherit it. Coordinates, pore geometry and Cartesian restraint references are not rotated or resized during preparation of this pressure policy.

The piston period/decay defaults are 1000/500 fs, with at least a 4 Å patch margin. Already slower recovery settings or larger margins are preserved. Group pressure is enabled, and pressure tensors are logged at the energy-output cadence. Fixed-area mechanical pressure is the normal component; the existing scalar pressure metric includes lateral stresses and is not the target pressure for this ensemble.

Production remains NVT and copies the equilibrated checkpoint/XSC. Its saved segment metadata and wizard preview now agree with that ensemble. Closed-wall screening profiles use the cell actually recorded in the production trajectory; changing-cell trajectories are rejected by that fixed-slab analysis rather than normalized using the original box. Standard DNA and archived graphene ensembles remain separate from this new versioned policy. The relaxation recipe version is now 4.

## Literature comparison

**A directly matching graphene protocol:** Shankla and Aksimentiev (2014) used membrane-normal-only NPT equilibration followed by NVT electric-field-driven transport. Their methods specify 50–60 ns equilibration, a 2 fs timestep, CHARMM CA carbon sites, 1 M KCl, and harmonic restraints on outer-edge carbon atoms. Their field convention uses voltage divided by the periodic normal length. This supports the ensemble sequence and field construction, but does not make our model or transport coefficients identical. [Primary methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC4236004/).

**Origami on a solid support:** Li et al. (2015) describe reservoir contraction as origami hydrates. Their origami/SiO₂ hybrid used roughly 20 ns of constant-area pressure equilibration, then NVT current simulations. This is a solid-supported-origami precedent, not a graphene-specific force-field validation or a universal equilibration duration. [Author manuscript, methods](https://api.repository.cam.ac.uk/server/api/core/bitstreams/75e87e28-cbcc-4e24-ace0-b8e6275a92d3/content).

**Implementation reference:** NAMD documents constant-area scaling and group pressure with rigid bonds. Its controller and parameter definitions provide the per-axis constraints needed for X/Y-normal membranes. [Pressure manual](https://www.ks.uiuc.edu/Research/namd/3.0b3/ug/node39.html), [controller source](https://www.ks.uiuc.edu/Research/namd/doxygen/Controller_8C_source.html), [parameter definitions](https://www.ks.uiuc.edu/Research/namd/doxygen/SimParameters_8C_source.html).

| Setup item | Assessment for NADOC |
|---|---|
| Pressure equilibration | Confirmed missing step in recent graphene packages; restored with compatible cell constraints. |
| Water placement | Prior investigation reproduced the solvent census and found a wet initial aperture. No cylindrical solvent-exclusion bug was found. |
| Wall mechanics | Our NGRC sites are independently restrained everywhere, with zero wall–wall LJ and CA-like solvent cross interactions. This is a rigid-wall approximation, unlike an edge-restrained deformable graphene model. Changing it requires separate validation; the cavity controls show that it can remain wet. |
| Wall charge and pore edge | Neutrality, surface charge, layer count and ideal pore termination are model choices. They must match the experiment being compared; a neutral ideal pore is not an oxidized or chemically terminated pore. No automatic charge/edge chemistry change was made. |
| Electrolyte and temperature | The audited cube_pore uses NaCl/counterions at 300 K; the cited graphene study uses KCl and different conditions. These are substantive differences for quantitative current, not evidence of a solvation error. Keep the intended experimental chemistry explicit. |
| Integrator | NADOC can use 4 fs/HMR and different PME settings; the cited methods use 2 fs. Earlier bulk controls did not attribute the cavity to the timestep. Conductance/diffusion comparisons still warrant a 2 fs sensitivity check; the pressure change does not silently alter the integrator. |
| Thermostat | The shared ladder uses strong coupling during relaxation and weaker coupling in production. Thermostat choice differs between studies and can affect kinetics; matching temperature alone does not validate transport coefficients. |
| Voltage | The audited 300 mV normalized field conversion is correct. Production uses the equilibrated cell; no voltage or force-field tuning was used to force crossings. |
| Reservoir and duration | The original cube_pore's far-side clearance was about 2.4 nm. Neither one padding number nor a fixed number of ps guarantees adequate reservoirs or hydration. The original shortened 1.68 ns relaxation is not equivalent to the cited multi-nanosecond protocols. |

The remaining differences are not grounds for changing all defaults at once. The pressure defect has direct intervention evidence. Quantitative conductance still requires stable pore hydration, volume/density convergence, adequate bulk-like reservoirs and sufficient sampling. Energy/volume/structural plateau checks alone do not certify a connected wet pore. A full fresh cube_pore relaxation has not been completed as part of this implementation check.

## Verification

The final targeted suite passed **334 tests**, including real solvation. Regression coverage includes the entire generated ladder, minimized-cell origin, all Cartesian normals, old fixed-volume compatibility, softened-piston preservation, actual production metadata/XSC inheritance, preview parameters, and surface profiles after cell equilibration. Real GROMACS solvation checks the Y-normal package and magnesium restraint indices.

The local NAMD verification executes three independent processes for each X/Y/Z-normal version of the same wet bare-pore system: 4 ps pressure equilibration, 4 ps pressure continuation, then 4 ps NVT. The sheet is deliberately offset to 1.2 nm from the coordinate origin. All nine runs completed, preserved both tangential dimensions and the membrane-centered origin, and retained exactly the inherited dimensions in NVT. These are integration/restart smoke tests, not converged transport or full-origami hydration tests.

[Executable verification](../../experiments/graphene_pressure_implementation_20260914/verify_namd.py) and [recorded cells](../../experiments/graphene_pressure_implementation_20260914/namd_verification.json). The earlier paired cavity experiments are in [the investigation report](../../experiments/cube_pore_cavity_20260914/FINDINGS.md).
