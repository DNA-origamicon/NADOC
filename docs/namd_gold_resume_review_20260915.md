# Gold surfaces and two-electrode NAMD: review and proposed work

2026-09-15. Status: **Phase 1 approved and completed within the local compute ceiling.**
The original plan is retained below. See the [restart diagnosis](../experiments/gold_interfaces/evidence/gold_restart_diagnosis_20260915/RESULTS.md),
[items 2–4 results](../experiments/gold_interfaces/evidence/gold_phase1_calibration_20260915/RESULTS.md) and
[qualification matrix](namd_gold_qualification_matrix.md) for the current evidence.
Neutral INTERFACE remains the starting model; physical and voltage-control qualification remain open.

## Evidence at the initial review (historical)

- `gold_geometry.py` and `namd_gold_package.py` already construct explicit fcc
  Au(100)/(111) pairs of slabs with a solvent slit, and isolated spherical fcc-cut
  nanoparticles. This is real atomistic gold geometry, with neutral Au interactions.
- Gold preparation, local Start, completed-stage continuation, input hashes and
  export exist. Gold setup remains separate from the abstract two-electrode UI.
- The retained [native report](../workspace/gold_validation_20260914/RESULTS.md)
  records five native LJ pair probes, 100 ps reference trajectories, short mobility
  and timestep controls, and managed execution. These results were reviewed here,
  not rerun. Native pair forces agree within 6.12e-6 kcal/mol/Å.
- Today's guarded focused tests: gold interfaces 20, gold jobs 5, gold API 3,
  two-electrode packages 4: **32 passed**. Lifecycle tests mock native execution;
  passing them is not new engine or physical validation. No browser check was run.
- The [40 ns screening assessment](namd_debye_assessment.md) concerns abstract
  charged walls. Its hardware trajectories share an initial state and seed; they
  are not independent replicas of a gold interface.

## Gaps recorded at the initial review

| Gap | Evidence and consequence | Required next result |
| --- | --- | --- |
| Electrode electronic response | Au charge is explicitly zero; UI selects `abstract_fixed_charge`. GPU EW3DC corrects periodic electrostatics but does not solve electrode charges. | An explicit fixed-charge versus fixed-potential scope, with a NAMD feasibility design for voltage control. |
| Solvent preparation | Retained slab central density is 34.268 waters/nm³; particle outer density 31.708, roughly +2.6%/-5.1% against an approximate reference. Slab loading 1.18 is an empirical pilot choice. | Same-model bulk density calibration, accessible-volume accounting and stable profiles with independent preparations. |
| Restart fidelity | All four strict 40 versus 20+20 step NVE comparisons fail the original velocity tolerance. Completed checkpoints can be read, but interrupted-stage recovery is rejected. | Diagnose restart/integrator phase, rigid-water treatment, restraints and correction initialization against a solvent-only control; preserve failed verdicts. |
| Surface/ion validation | Only 6 or 9 ions per species and ~100 ps in reference gold runs; TIP3P/CUFIX differs from SPC/E literature. | Matched hydration reference, sampling uncertainty, then ion adsorption validation. |
| Numerical envelope | Small-cell NaNs/exclusion failures and GPU migration limits are retained. Final packages disable migration and require cell dimensions >=4 nm. | Controlled padding, mesh, timestep and lateral-size comparisons at matched density; switching-region force checks. |
| Nanoparticle chemistry | Bare lattice cuts and short mobile controls do not establish equilibrium morphology. Existing authored thiol linkers do not supply validated Au–S chemistry. | Separate mobility/curvature tests and an explicit Au–S topology/parameterization before grafted DNA or PEG. |
| Application integration | Gold has a standalone API/recipe path; no dedicated surface selector/rendering/presets. Managed segments are capped at 100,000 steps, or 100 ps at 1 fs. | After qualification, explicit material capabilities, atom identities in playback, robust continuation and practical bounded campaign scheduling. |

## Approved work package: Phase 1

Local development and qualification only, with at most **4 GPU-hours total** and
**1 ns per individual pilot trajectory**. These are approved resource ceilings,
not promises of equilibration. Stop at the ceiling and report incomplete gates.
Use fresh evidence directories and the existing pinned runtime; retain all failures.

1. **Resolve restart behavior first.** Reproduce the strict test for particle and
   slit at 0.5/1 fs; compare matched solvent-only controls and inspect local NAMD
   integration/restart code. Add independent energy-drift and first-step force
   diagnostics. Deliver a root-cause report and narrowly scoped correction if
   justified. Do not increase tolerances to manufacture a pass. Any replacement
   criterion requires a documented physical/numerical justification for review.
2. **Calibrate water inventory.** Measure bulk TIP3P/CUFIX density at the same
   temperature, salt, cutoff and timestep using appropriate bulk NPT. Prepare
   confined fixed-cell NVT slit/particle cases from that reference. Use two
   independent preparations per geometry, beginning with 100 ps and extending
   only within the ceiling. Report central/outer density, water orientation,
   translational/rotational temperatures, actual ion concentration and time blocks.
   Compare against the measured bulk reference and uncertainty rather than treating
   33.4 waters/nm³ as a universal acceptance value.
3. **Prepare the conducting-electrode implementation design.** Inspect the local
   NAMD source interfaces for charge updates, PME consistency, energy accounting,
   resident GPU synchronization and checkpoint state. Specify two electrode groups,
   imposed potential difference, potential reference, electrolyte/electrode charge
   constraints, and coupling to EW3DC. Deliver a concrete algorithm/API proposal and
   feasibility verdict; do not assume the existing force plugin can update all PME
   charge paths correctly. A small reference solve may support the design, but a
   production constant-potential solver is a later approval scope.
4. **Publish a qualification matrix.** Separate passed arithmetic/runtime checks
   from physical checks and remaining failures. Include commands, hashes, costs,
   profiles and proposed next acceptance criteria. Fix stale documentation such as
   the broad “native validation is still pending” statement in the two-electrode
   setup guide without broadening the claims of existing wall results.

Phase 1 succeeds by resolving or isolating restart failure, supplying calibrated
preparation evidence, and producing an actionable NAMD electrode design. It does
not claim converged adsorption or validated voltage-dependent gold physics.

## Later phases, to review after Phase 1

**Phase 2 — bare-gold physical validation:** reproduce a selected published
hydration case with its actual solvent and surface conditions in a separate
reference package; compare the NADOC solvent separately. Add controlled finite-size,
timestep, facet, restraint and particle-curvature tests. Determine ion counts and
sampling from pilot autocorrelation/uncertainty before proposing long trajectories.

**Phase 3 — voltage-controlled two-electrode implementation:** implement the
reviewed charge solver and validate against independent electrostatic solutions,
electrode potential residuals, charge conservation, energy/force derivatives and
restart consistency. Then test neutral/positive/negative bias, screening, electrode
charge versus voltage and finite-size dependence. Potential differences must not
be converted to fixed charge using an assumed universal capacitance.

**Phase 4 — functionalization and product integration:** qualify Au–S chemistry and
Au/PEG/DNA cross interactions, then connect authored particles and two-electrode
controls to the qualified material model, presets and trajectory rendering.
Distinguish an isolated particle's electrical boundary condition from an electrode
connected to a potential source. Redox and electronic transport require separate
models if they become part of the intended experiment.

## Scientific scope decision

The recommended destination for applied-voltage experiments is constant-potential
gold, keeping neutral IFF as its independently tested structural/contact baseline.
The precise electrostatic model and parameters still require selection and validation.
A Geada core–shell model is a useful alternative for local induced polarization,
but adding it alone does not supply imposed electrode voltage. Avoid requiring
both implementations unless the scientific observable needs both and the coupling
is defined without double-counting polarization.

Primary references checked during this review:

- [Geada et al. (2018)](https://www.nature.com/articles/s41467-018-03137-8):
  bonded core–shell charges model induced response; the electron sites remain
  tethered to their cores.
- [Sitlapersad et al. (2024)](https://doi.org/10.1063/5.0171502): constant-potential
  algorithms adjust electrode charges to maintain the imposed potential difference.
  The published example uses LAMMPS; it does not establish NAMD compatibility.

**Disposition:** the user authorized restart diagnosis and then items 2–4. Those
items are complete; the linked results define their limits. Later physical-validation
campaigns and constant-potential solver implementation remain separate work scopes.
