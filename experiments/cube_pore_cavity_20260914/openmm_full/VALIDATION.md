# Independent-engine validation and limitations

This is an experimental OpenMM feasibility check, not an application engine change. The installed build is `8.6.0.dev-c6173db`, CUDA mixed precision. Original input files are read-only.

The full original dry checkpoint was evaluated without wall restraints in both CPU NAMD and OpenMM. All source particle masses match, are finite, and are positive. The importer retains the zero NGRC self-NBFIX and all loaded DNA/water/ion force-field parameters. OpenMM's default long-range LJ correction is disabled, and NAMD's r² switching function is used explicitly. PME uses the same alpha and mesh dimensions; interpolation implementation differs.

| Component | NAMD (kcal/mol) | OpenMM (kcal/mol) | Difference |
|---|---:|---:|---:|
| Bonds | 41874.0944 | 41874.0619 | −0.0325 |
| Angles + Urey–Bradley | 101711.8300 | 101711.8297 | −0.0003 |
| Dihedrals | 135318.5789 | 135318.6009 | +0.0220 |
| Impropers | 2170.6578 | 2170.6575 | −0.0003 |
| LJ, including 1–4 exceptions | 520539.0316 | 520537.8685 | −1.1631 |
| Electrostatics | −6985332.5469 | −6984347.5375 | +985.0094 |
| Total | −6183718.3541 | −6182734.5491 | +983.8050 |

The electrostatic difference is 0.0141%; total differs by 0.0159%. OpenMM stores LJ 1–4 exceptions in its `NonbondedForce`, so that contribution was computed separately before comparing LJ and Coulomb components. Comparing its two nonbonded force objects directly to NAMD's two printed columns would be incorrect.

The restored graphene restraints evaluate to 23039.5604 kcal/mol versus 23038.8966 in NAMD. The initial local water-void estimate is exactly the same, 373.952 nm³. The membrane plane is moved to coordinate z=0 by translating all coordinates and references equally; the initial physical periodic lattice is unchanged. Binary velocities use the documented conversion of 2.045482706 nm/ps per NAMD internal velocity unit.

Both experimental dynamics branches start from the same original dry coordinates and velocities, retain the source masses and force field, and use the same 2 fs LangevinMiddle integrator at 300 K. The NVT branch disables pressure moves. The NPzAT branch attempts Monte Carlo pressure moves only along z at 1.01325 bar. Neither has an applied field or ENM at this final-relaxation starting state. The wall spring remains K=50 kcal/(mol Å²).

Differences from the original NAMD dynamics remain: 2 fs single-rate electrostatics versus the original 4 fs/8 fs multiple-time-step relaxation, a different Langevin integrator/thermostat acting on hydrogens as well, PME interpolation, and a Monte Carlo barostat. These are **independent-engine controls**, not a quantitatively matched continuation of the Alpine trajectory. The within-OpenMM pair is needed to attribute differences to pressure control. Slow volume-move acceptance can limit equilibration; a run ending with negative normal pressure is not an equilibrated 1 atm result merely because it used a barostat.

See `energy_validation.json`, `meta.json` inside each branch, and the original logs in `../openmm_validation/`. Early importer/configuration failures are excluded from physical conclusions. Both full-system branches completed 50 ps. The small NAMD water-count control was temporarily paused during this pair to reduce GPU contention; the watcher resumed it after completion, as recorded in `../openmm_validation/gpu_schedule.json`, and that control subsequently completed.
