# Phase 1: solvent inventory and constant-potential feasibility

Local, isolated qualification campaign authorized on 2026-09-15. The calculation
budget is four GPU-hours including a 60-second allowance for the preceding restart
diagnosis. Individual trajectories are capped by this campaign at 300 ps, below
the approved 1 ns ceiling. All dynamics run sequentially on local GPU 0.

## Reproducible protocol

- Two independently prepared bulk TIP3P/CUFIX NaCl systems, seeds 317 and 719:
  periodic translations of the starting water template, independent ion placement,
  independent thermal initialization and Langevin streams. No shared equilibrated
  starting checkpoint between replicas.
- 298.15 K, nominal 150 mM NaCl, ordinary water masses, 1 fs, rigid water/SETTLE,
  nonbonded and full electrostatics every step, 10–12 Å LJ switching/cutoff,
  PME spacing 1 Å, PME tolerance 1e-6, GPU resident, atom migration disabled.
- Bulk: 500 minimization steps and 200 ps isotropic NPT at 1.01325 bar, Langevin
  piston period/decay 200/100 fs, group pressure. This follows NAMD's requirement
  to use group pressure with rigid bonds.
  [NAMD pressure documentation](https://www.ks.uiuc.edu/Research/namd/3.0/ug/node39.html)
- Gold: Au(111) pair of five-layer slabs, 3 nm slit, or 0.85 nm fcc-cut particle
  in a 4.7 nm cell. Gold uses native position restraints U=k|r-r0|²,
  k=10 kcal/mol/Å². Geometry and LJ parameters are unchanged.
- Each geometry gets water tiled from its own bulk NPT endpoint, preserving
  intramolecular geometry; Na/Cl positions are independently selected. Initial
  gold controls run 100 ps NVT after minimization. Slits retain fixed-cell EW3DC;
  particles use ordinary 3D PME. No barostat acts on the gold slit or its vacuum.
- Revised preparations adjust water inventory using measured depletion and keep
  the same final water count for both seeds of a geometry. They run 200 ps NVT.
  [Inventory calculation and sensitivity](inventory_revision.json).
- A second slit-only count update uses the observed density response between the
  initial and revised pilots, followed by fresh 300 ps pilots. This replaces the
  first update's assumed response volume with a measured estimate; it does not
  alter the force field. Six ion pairs are held fixed across this last comparison
  to prevent integer salt rounding from changing the electrolyte inventory.
  [Secant update](slit_refinement.json).

### Inventory update is a preparation estimate

The first update estimates ΔN=(rho_bulk−rho_local)V_response while holding the
first adsorption layers' inventory approximately fixed. V_response is the volume
beyond an operational 0.65 nm surface layer. Boundaries at 0.6 and 0.8 nm are also
reported to expose this approximation's sensitivity. The planar boundary follows
the two observed density peaks; it is not a universal gold parameter. The revised
trajectories test the estimate. No LJ, charge, Au restraint or solvent parameter
is fitted to force a target density.

To realize an exact inventory, the preparer makes an excess of whole waters by
scaling only their centers, selects the requested number with a recorded random
seed, then replaces whole waters with ions. The final packing is minimized.
The count target is identical across the two replicas. Actual salt counts and
local concentrations are outputs, not forced to equal 150 mM in each spatial bin.

## Analysis definitions

- Bulk water density: oxygen count divided by the instantaneous NPT volume.
- Slit central density/concentration: the middle 1 nm divided by its physical
  volume. Folded interfacial profiles use both surfaces and twice the area.
  Matching its mean does not by itself establish a flat bulk plateau in this
  narrow slit; wider-gap comparisons remain separate validation work.
- Particle outer density/concentration: the spherical shell from radius+1 nm to
  half the shortest box dimension, with exact shell-volume normalization.
- Water orientation: unit vector from oxygen toward the midpoint of its two
  hydrogens, dotted with the direction away from the nearest slit interface or
  away from the particle COM. Full spatial profiles are retained; a global average
  alone would hide interfacial structure.
- Translational/rotational temperatures: molecular COM and relative kinetic
  energies from every 1 ps velocity-DCD frame, three degrees of freedom for each
  mode. The latter is the rigid-water relative-motion estimate. Native source and
  a direct kinetic-energy comparison establish the Å/AKMA velocity units:
  [unit check](velocity_units_check.json).
- Times come from DCD headers and the configuration's firsttimestep, excluding
  minimization steps from elapsed physical dynamics.
- Statistics use the last half of each trajectory, with 10/20/50 ps block means
  and Student-t intervals. These are **conditional** on stationary independent
  blocks. Two 50 ps blocks cannot establish an uncertainty plateau. Independent
  seeds and early/late comparisons supplement the block analysis; none certify
  equilibration by themselves. This treatment follows the distinction between
  sampling diagnostics and physical validity in
  [Grossfield et al., 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC6286151/).
- Operational accessible volume: 100,000 Monte Carlo points outside initial Au
  atom-pair exclusion distances at the preparation ceiling of 6 kcal/mol, with
  standard errors. Separate oxygen/Na/Cl volumes are reported. This is an explicit
  preparation convention, not a unique thermodynamic solvent volume.

## Files and commands

`campaign.py` prepares and executes isolated native runs. `analyze_campaign.py`
generates profiles/time series/mode temperatures. `revise_inventory.py` constructs
the data-driven revision. `summarize.py` rebuilds figures, tables and `summary.json`.
Each native stage has a configuration, log, execution record and binary outputs.
Manifests retain input hashes and bulk-checkpoint provenance.

Run from the NADOC root with a fresh copy of these scripts in a new campaign
directory; preparation and stage execution refuse existing outputs:

```bash
PYTHONPATH=. uv run python workspace/<new_campaign>/campaign.py bulk
PYTHONPATH=. uv run python workspace/<new_campaign>/analyze_campaign.py
PYTHONPATH=. uv run python workspace/<new_campaign>/campaign.py gold
PYTHONPATH=. uv run python workspace/<new_campaign>/analyze_campaign.py
PYTHONPATH=. uv run python workspace/<new_campaign>/revise_inventory.py
PYTHONPATH=. uv run python workspace/<new_campaign>/summarize.py
```

`analyze_campaign.py` analyzes completed stages only. Stop launching new work when
the recorded native time reaches the ceiling; the executor also bounds each native
subprocess. Relative and absolute package paths are recorded because the local
workspace is symlinked to the archive volume.

## Limits and retained failures

This campaign calibrates a starting water inventory for two specific bare-gold
geometries. It does not reproduce a published hydration benchmark, measure Au ion
adsorption free energies, establish constant-potential physics, or qualify Au–S,
PEG/DNA contact, mobile morphology, multi-GPU execution or cloud deployment.
The [constant-potential design](../../../../docs/namd_constant_potential_design.md) records
the separate source audit and implementation requirements.

An initial minimization config attempted to set velocity-DCD frequency after the
minimize command; NAMD rejected that ordering. The corrected `minimize_v2` sets all
output options before execution. The original failure is retained under
`bulk_317/minimize.log`. Analysis initially needed an explicit DCD reader for the
`.veldcd` extension; that error is retained in `analysis_driver.log`.
These were configuration/analysis errors, not accepted trajectories.

`slab_317_calibrated/pilot` was deliberately stopped after discovering that automatic
salt rounding changed six NaCl pairs to five when the target water count decreased.
Its files remain intact and it is not an accepted calibration result. The final
`slab_*_calibrated_fixed_ions` controls preserve six pairs. The earlier initial-to-
revised slit comparison changed five to six pairs under the nominal-salt recipe;
its water-response slope is an estimate, and the fixed-ion final controls test it.
