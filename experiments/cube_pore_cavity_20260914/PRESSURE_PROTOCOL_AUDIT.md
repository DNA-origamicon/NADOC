# Pressure-control scope audit — 2026-09-14

Read-only audit of current generators, git history, and all 42 local package manifests with their root-level NAMD dynamics configurations. No application or existing-job changes. The census checks explicit numeric `run` statements and literal pressure settings; it is not a runtime/convergence audit or an interpreter for arbitrary Tcl overrides. Results: [pressure_protocol_census.json](pressure_protocol_census.json).

## Standard DNA relaxation

`md_protocols._pressure_block` emits a Langevin piston at 1.01325 bar with group pressure and isotropic cell scaling when NPT is enabled. `mgh_slow_release_segments` defaults to NPT, includes a 500 ps solvent-settling stage in the current default recipe, and retains pressure control through all four restraint-release stages. `_segment_conf` uses piston period/decay 1000/500 fs. Both `equilibrium_aware_namd` and `propagator_reference` wrap this shared ladder; soft/gentle integrator choices do not inherently disable pressure.

The local full-solvent DNA configurations support this: examples include 6hbx32 (`4dbc788c1b54`), 2hb_1xT (`29ac138f08a4`), VoltronCoreArm (`82a3cd08ed4f`) and duplex propagator-reference packages. Their dynamics configurations have the piston on. This establishes configured pressure control, not that every historical run completed or equilibrated. One inspected VoltronCoreArm live-metrics file is malformed and contains minimization data; it was not used as evidence of equilibrated pressure.

## Graphene regression

Commit `4719cd9990ad30193c9606e98ac438d18f60f1fe` (September 7, 2026) changed the ladder's `nvt_only` condition from `graphene_only` to `bool(graphene_nanopore)`, changed `solvation.npt_allowed` accordingly, and added the fixed-cell barostat-disabling branch in `graphene_pressure_conf`. This made the exception apply to DNA plus graphene, not just the bare-wall control. It also skips the solvent-settling stage because that stage requires `not nvt_only`.

Older small_plate packages `4a293b5d915b` and `e75ffd56c6f8` still contain pressure-on configurations. Newer small_plate `79c6dfa66d73` and cube_pore `60e854232e8c` contain pressure-off dynamics. Earlier bare-graphene packages can mix pressure-off managed stages with a pressure-on `namd_fast.conf`; template presence does not establish which template actually ran. The existing-job files, rather than current defaults or NPT tokens in filenames, are the evidence for a particular job's ensemble.

## Other pressure-off paths

- Energy minimization/preflight intentionally disables the piston and does not establish solvent density.
- Vacuum shape relaxation and implicit GBIS disable pressure control; they do not represent periodic bulk explicit solvent at 1 atm.
- Legacy carved water-shell packages intentionally run NVT because their periodic cells contain vacuum. The two non-graphene explicit-solvent exceptions in the local census are 6hbx100_90deg `8553cf4fa9a0` (1.2 nm water shell) and GT_corner_v2 `90ad54edddec` (0.6 nm shell). Their `charge_audit.ionization.water_shell_nm` records the carve, and their dynamics configurations disable the piston. Their bulk pressure is not comparable to a fully filled NPT box.
- Explicit NVT stage settings, manual overrides, and production `force_nvt` can also disable pressure. Benchmark and PEG qualification paths have deliberate fixed-volume settings; these are not the standard DNA relaxation recipe.

### Separate legacy metadata gap

The two old carved DNA packages lack the newer `solvation.carved` / `solvation.npt_allowed` metadata. Calling current `package_npt_allowed` on either returns **True**, despite their recorded water shell and pressure-off relaxation configurations. A newly generated descendant using that helper could therefore enable pressure incorrectly. This is a separate compatibility gap, not evidence that their archived relaxation ran NPT, and not the cause of cube_pore's cavity. It has not been changed in this audit.

## Meaning of comparable equilibration

The shared goals should be the intended temperature, equilibrated solvent density, stable volume/hydration and adequate restraint release. Graphene needs compatible normal-pressure control with fixed lateral area and a membrane-centered scaling origin; standard soluble DNA uses isotropic NPT. Equal scalar pressure traces or identical pressure tensors are not appropriate acceptance criteria for these different mechanical constraints. NAMD explicitly supports fixed-area, normal-pressure control via `useFlexibleCell` and `useConstantArea`; compare normal pressure for the membrane and report lateral stresses separately. [NAMD pressure documentation](https://www.ks.uiuc.edu/Research/namd/3.0b3/ug/node39.html).

The confirmed graphene override is a regression in density equilibration. Standard full-solvent DNA did not inherit that override. Certifying historical pressure convergence would require runtime averages and volume/hydration traces for each job; an enabled piston alone is not a convergence certificate.
