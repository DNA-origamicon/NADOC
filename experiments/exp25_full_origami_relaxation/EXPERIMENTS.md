# Exp25 Experiment Notes

## F001_min_only_5k

Status: complete.

Method: full B_tube GBIS NAMD package from Exp22, 5000 minimization steps,
constraints enabled with `constraintScaling 5.0` against the raw template PDB.

Result: completed without fatal errors in `142 s`. The GBIS line minimizer still
emitted intermittent `-99999999999.9999` sentinel energies during bracket tests,
but the accepted energies were finite and the run wrote restart files.

Final displacement from raw template:

- RMSD `0.0504 nm`
- mean `0.0384 nm`
- p90 `0.0724 nm`
- p99 `0.1911 nm`
- max `0.4237 nm`

Artifact: `results/B_tube_full_F001_minimized_reference.nadoc`.

## F002_cold_10ps_k5

Status: failed.

Method: 50 K, 0.5 fs, `constraintScaling 5.0`, but restraints referenced the
raw initial template while coordinates started from the F001 minimized restart.

Result: failed shortly after step 100. Temperature jumped to `438 K` at step
100 and NAMD reported atoms moving too fast. This is likely a bad protocol:
the strong restraint field pulled the minimized structure back toward the
pre-minimized high-strain template.

## F002b_cold_1ps_minref_k1

Status: complete.

Method: generated a new restraint/reference PDB from the F001 minimized
coordinates. Ran 1 ps at nominal 10 K, 0.25 fs, `constraintScaling 1.0`,
`fullElectFrequency 1`, `pairlistdist 28`, `margin 10`.

Result: completed without fatal errors. The system warmed above the thermostat
target and settled near `55-60 K`, which indicates residual relaxation energy
is still being released even under restraints.

Final displacement from raw template:

- RMSD `0.1004 nm`
- mean `0.0890 nm`
- p90 `0.1404 nm`
- p99 `0.2704 nm`
- max `0.5659 nm`

Artifact: `results/B_tube_full_F002b_cold_1ps_reference.nadoc`.

## F003b_cold_50K_1ps_minref_k1

Status: complete.

Method: continued from F002b restart velocities for 1 ps at nominal 50 K,
0.25 fs, `constraintScaling 1.0`, same minimized-coordinate restraint
reference.

Result: completed without fatal errors. The run heated sharply during the first
0.05 ps (`~271 K` at step 200), then cooled toward `~139 K` by the end. This is
still not a production protocol, but it is bounded and provides another relaxed
coordinate reference.

Final displacement from raw template:

- RMSD `0.1026 nm`
- mean `0.0911 nm`
- p90 `0.1428 nm`
- p99 `0.2740 nm`
- max `0.7357 nm`

Artifact: `results/B_tube_full_F003b_50K_1ps_reference.nadoc`.

## Working Interpretation

- Whole-origami coordinates are much more viable than the reduced periodic cell
  for short restrained relaxation, but the raw hand-tuned template pose still
  releases substantial local strain immediately.
- The starting reference matters. Restraining dynamics to the raw template after
  minimization is destabilizing; restraining to the minimized reference makes
  short dynamics viable.
- The useful CAD starting poses are currently F001 and F002b/F003b. F001 is the
  least thermally perturbed; F002b/F003b include a tiny amount of dynamic
  relaxation but still show thermostat/strain transients.
- Next protocol should use the F001 minimized reference as the starting
  atomistic CAD pose, then try a longer low-temperature relaxation with either
  weaker architecture-level restraints or staged all-atom restraints referenced
  to the current stage, not the original template.

## CAD Atomistic Reference

Status: implemented.

Artifact: `workspace/B_tube_relaxed_atomistic_F001.nadoc`.

This file is the current recommended B_tube CAD starting point. It keeps the
normal NADOC topology but includes a persisted `Design.atomistic_reference`
generated from the F001 minimized full-origami coordinates. When the design
topology hash still matches, `build_atomistic_model()` now reuses those stored
heavy-atom coordinates instead of rebuilding the older hand-tuned template pose.
If the topology or sequence changes, the reference is ignored and the ordinary
template builder is used.

F001 is preferred over F002b/F003b for CAD because it is only minimized, not
thermally perturbed. The later references are useful diagnostic snapshots, but
they include large startup temperature transients.

## Base-Pair Monitor

Status: implemented.

Script:
`experiments/exp25_full_origami_relaxation/scripts/basepair_monitor.py`.

The monitor identifies C1' partners from a reference PDB/PSF, polls a growing
DCD, writes JSONL metrics, and can own a NAMD subprocess via `--namd-cmd`. If
the paired fraction falls below `--min-paired` after `--grace-frames`, the
monitor terminates the NAMD process group and exits nonzero.

Calibration note: the strict `12 Å`/`95%` rule was too aggressive for this
full-origami GBIS reference. The F001 reference itself is only `93.45%` paired
under a `12 Å` cutoff, while `13 Å` gives a `100%` baseline. For this Exp25
series, use `--paired-max-ang 13.0 --min-paired 0.90` unless a future
calibration establishes a better physical cutoff.

## F004_validate_310K_5ps_minref_k1

Status: failed before first useful DCD frame.

Method: continued from the F003b restart, nominal `310 K`, `0.5 fs`, 5 ps,
`constraintScaling 1.0`, restraints referenced to the F001 minimized
coordinates, monitored with the first strict base-pair monitor settings.

Result: NAMD failed around step 100 with margin/fast-atom errors before the
base-pair monitor could make a useful decision. The reported high-velocity
atoms were local DNA atoms near residues `A3972` and `A3673`. Direct room
temperature startup from the staged cold pose is not stable yet, even with
k=1 restraints.

## F005_validate_150K_5ps_minref_k1

Status: monitor-tripped, but the trip threshold was miscalibrated.

Method: continued from F003b, nominal `150 K`, `0.25 fs`, 5 ps,
`constraintScaling 1.0`, F001 minimized restraints. The monitor still used
the too-strict `12 Å`/`95%` setting.

Result: the monitor tripped after a few analysed frames because the `12 Å`
cutoff measured only about `46-48%` paired in the moving trajectory. Later
calibration showed that this was not a fair pass/fail threshold for this full
origami. The NAMD log also showed substantial heating above the target
temperature, so the run is not a clean validation.

## F006_validate_150K_5ps_bp90

Status: failed.

Method: same physical setup as F005, but monitored with the calibrated
`13 Å`/`90%` base-pair threshold.

Result: first monitored frame was above threshold (`92.74%` paired), then NAMD
failed around step 400 with a high-velocity local sugar atom (`DT b 10`,
`C4'/O4'` neighborhood). This failure is local dynamics/geometry, not the
base-pair monitor tripping.

## F007_validate_50K_5ps_bp90

Status: complete.

Method: continued from F003b, nominal `50 K`, `0.25 fs`, 5 ps,
`constraintScaling 1.0`, F001 minimized restraints, monitored with
`--paired-max-ang 13.0 --min-paired 0.90`.

Result: NAMD completed all `20,000` steps without fatal errors. The monitor did
not trip; paired fraction stayed around `91.7-92.5%` through the run and the
last analysed frame reported `92.19%` paired, mean C1' distance `12.04 Å`, and
p90 `12.90 Å`.

Relaxation analysis relative to F001 minimized reference:

- frames: `100`
- final RMSD: `0.0743 nm`
- final mean displacement: `0.0661 nm`
- final p90 displacement: `0.1040 nm`
- final p99 displacement: `0.1728 nm`
- final max displacement: `0.8282 nm`

Important caveat: this was only nominally `50 K`. Because the run inherited a
hot restart and was short, the reported kinetic temperature remained roughly
`240-250 K` near the end. F007 is therefore best interpreted as a bounded
low-temperature validation of the F001-restrained start, not as a true 50 K
equilibrium or room-temperature production protocol.

## Updated Interpretation

- The new CAD atomistic reference should reduce the worst raw-template
  minimization strain and is a better starting pose than the hand-tuned
  template coordinates.
- F004 and F006 show that the current GBIS full-origami protocol is still not
  ready for direct 310 K or 150 K dynamics from the staged cold pose.
- F007 shows a short, restrained, lower-energy validation can complete while
  maintaining the calibrated base-pair metric. That is encouraging but still
  not evidence of production stability without restraints.
- Next protocol work should focus on cooling/restarting velocities cleanly,
  auditing the repeated local high-velocity residues, and ramping toward 310 K
  from the F001 reference with the live base-pair monitor enabled.

## F008_ramp_310K_k1_reinit

Status: failed as a 310 K production protocol.

Method: restarted from F001 minimized coordinates, discarded inherited
velocities, initialized at `50 K`, used `0.25 fs`, `constraintScaling 1.0`,
`langevinDamping 5`, and ramped target temperature through
`50/100/150/200/250/310 K`. The final 310 K block was 5 ps. Monitored with
`13 Å`/`90%`.

Structural result: completed without NAMD fatal errors and without a monitor
trip. The paired fraction stayed narrowly above threshold during the 310 K
block, ending at `91.22%` paired with mean C1' distance `12.06 Å` and p90
`12.95 Å`.

Thermal result: failed. The final 4,000-step tail reported temperature
`507.36 K` mean (`498.38-518.17 K`), with final `TEMPAVG = 499.10 K`.

Relaxation relative to F001 minimized reference:

- frames: `100`
- final RMSD: `0.0793 nm`
- final mean displacement: `0.0709 nm`
- final p90 displacement: `0.1118 nm`
- final p99 displacement: `0.1815 nm`
- final max displacement: `0.8795 nm`

Interpretation: fresh velocities and a gentle target ramp avoid the immediate
room-temperature local blow-up, but they do not remove heat fast enough to make
a valid 310 K production segment.

## F009_ramp_310K_k1_rethermalized

Status: failed as a 310 K production protocol, but is the best bounded warm
attempt so far.

Method: restarted again from F001 minimized coordinates, used `0.25 fs`,
`constraintScaling 1.0`, stronger `langevinDamping 20`, and explicitly
`reinitvels` at each 0.5 ps ramp plateau from `25 K` to `310 K`. The final
310 K block was 5 ps. Monitored with `13 Å`/`90%`.

Structural result: completed without NAMD fatal errors and without a monitor
trip. The paired fraction started near `99%`, drifted into the low-90s, and
ended at `92.06%` paired with mean C1' distance `12.04 Å` and p90 `12.92 Å`.

Thermal result: improved but still failed. The final 4,000-step tail reported
temperature `353.83 K` mean (`351.96-357.37 K`), with final
`TEMPAVG = 351.32 K`. This is much better than F008 but still not a true 310 K
production run.

Relaxation relative to F001 minimized reference:

- frames: `110`
- final RMSD: `0.0756 nm`
- final mean displacement: `0.0684 nm`
- final p90 displacement: `0.1078 nm`
- final p99 displacement: `0.1647 nm`
- final max displacement: `0.7959 nm`

## Broader Issue Reassessment After F008/F009

Two 310 K ramp attempts avoided catastrophic structural failure under k=1
restraints, but neither produced a thermally valid 310 K production segment.
The likely broader issue is ongoing release of stored potential energy from the
full-origami atomistic pose under GBIS, not just inherited bad velocities.

Evidence:

- F007 nominal `50 K` also ran much hotter than target (`~240-250 K`).
- F008 fresh velocities still climbed to `~500 K`.
- F009 aggressive re-thermalization and damping reduced the overshoot but only
  to `~353 K`.
- Base-pair metrics remained bounded in F008/F009, so the dominant failure is
  thermostat/relaxation energy balance, not immediate duplex separation.

Recommended next branch: stop simple temperature-ramp tuning and audit the
energy source. Split the system diagnostically by (1) longer restrained
minimization from F001, (2) identifying high-energy bonded terms/residue
clusters in the starting structure, (3) testing whether lower restraint force or
restraint reference mismatch injects heat, and (4) comparing GBIS behavior
against a small explicit-solvent subset or smaller origami subdomain. A valid
310 K run should first demonstrate temperature control for at least a short
restrained segment before trying weaker restraints or production-length windows.

## Established-Practice Remediation Implementation

Status: implemented, not yet production-validated.

The literature/tutorial audit identified four major gaps: explicit
solvent/Mg2+ support, local-order elastic-network restraints, Watson-Crick
base-pair monitoring, and nanosecond-scale staged equilibration. The following
repo changes close those gaps enough to start testing them directly:

- `backend/core/namd_solvate.py` now supports explicit-solvent NaCl + MgCl2
  package generation through `mg_conc_mM`, includes the CUFIX water/ion stream
  by default, writes Mg2+ ions into PSF/PDB output, uses `rigidBonds all`, and
  uses Langevin damping `1 ps^-1` in the generated explicit-solvent config.
- `scripts/generate_enm_restraints.py` generates NAMD `extraBonds` local-order
  restraints from the F001 reference. The current B_tube ENM artifact contains
  `61,186` restraints: base-pair registry plus nearest-neighbor base-stacking
  restraints.
- `scripts/watson_crick_monitor.py` adds a canonical heavy-atom Watson-Crick
  monitor. It reports both absolute H-bond-proxy retention and
  reference-relative retention, because the current F001 atomistic reference
  itself does not satisfy strict published-style H-bond cutoffs.
- `scripts/build_explicit_mg_package.py` exposes the explicit-solvent Mg path
  as an experiment script. Use `--stats-only` before building the full package;
  the whole B_tube explicit package is expected to be large.
- `scripts/setup_established_practice_protocol.py` generated:
  `results/runs/F010_established_practice_gbis_enm/`.

F010 stages:

- `F010_00_positional_310K.conf`: longer restrained minimization plus k=1
  positional startup at 310 K.
- `F010_01_enm_weakpos_310K.conf`: local-order ENM plus weak positional
  scaffold (`constraintScaling 0.10`).
- `F010_02_enm_only_310K.conf`: ENM-only local-order equilibration.

Important new diagnostic:

- F001 reference under strict absolute Watson-Crick heavy-atom proxy:
  `24.21%` paired at `3.6 Å`, reference-relative baseline `100%`.
- F009 final frame under the same monitor:
  absolute `0.39%`, reference-relative `15.10%`.

Interpretation: the old C1' monitor was useful as a gross-distance tripwire but
too forgiving to validate base-pair chemistry. Even when F009 stayed around
`92%` paired by C1' distance, Watson-Crick heavy-atom geometry was mostly lost
relative to F001. This strongly supports the next branch: improve/hold local
base geometry with ENM restraints and/or rebuild atomistic base positions, not
just tune thermostat ramps.

Remaining limitations:

- The explicit-solvent Mg implementation places Mg2+ ions directly using CUFIX
  parameters. The included forcefield also defines MGH hexahydrate residues, but
  NADOC does not yet place rigid Mg-hexahydrate clusters. This is close enough
  for a first explicit-solvent Mg test, but not a full reproduction of every
  Aksimentiev-style ion-placement detail.
- The F010 GBIS+ENM branch closes the restraint/monitoring gaps before paying
  explicit-solvent cost. It should be smoke-tested before launching the much
  larger explicit-solvent full-origami package.

## F011_quick_enm_ab

Status: complete; all immediate-310 K quick smokes failed, but the failure modes
are informative.

Purpose: quick A/B tests to see whether the established-practice local-order ENM
improves minimization and early production behavior before committing to longer
F010-style stages.

Important implementation correction: NAMD `extraBonds` atom indices are
zero-based. The first generated ENM file was 1-based and produced a huge
artificial initial bond term. `generate_enm_restraints.py` has been corrected
and both F010/F011 ENM files were regenerated.

Runs:

- `F011A_positional_310K_smoke`: k=1 positional restraints, 5000 minimization
  steps, then 2 ps at 310 K.
  - C1' monitor stayed high through the available frames: final monitored
    `99.58%` paired, mean C1' `11.52 Å`.
  - NAMD failed shortly after dynamics began with
    `Low global CUDA exclusion count` at step `5400`.
  - Minimized phase contained `2463` sentinel-energy lines.
  - Last reported dynamics temp: `328.7 K`, tempavg `231.4 K`.
  - Watson-Crick final DCD frame: absolute `0.14%`, reference-relative `78.67%`.

- `F011B_positional_enm_310K_smoke`: k=1 positional restraints plus ENM, but
  using the bad 1-based ENM file.
  - Invalid as a physics result.
  - Initial bond energy was about `1,014,952`, confirming artificial ENM strain.
  - Tripped the C1' monitor at `84.06%` paired.

- `F011C_positional_enm_zeroidx_310K_smoke`: k=1 positional restraints plus the
  corrected zero-based ENM, 5000 minimization steps, then 2 ps at 310 K.
  - Initial energy matched the positional-only control, so indexing was fixed.
  - C1' monitor tripped at `76.34%` paired by frame 15.
  - Temperature ran away: last reported temp `606.4 K`, tempavg `584.6 K`.
  - Watson-Crick final DCD frame: absolute `0.23%`, reference-relative `11.73%`.

- `F011D_enm_zeroidx_no_min_310K_smoke`: corrected ENM, no extra minimization,
  direct 310 K dynamics from F001.
  - C1' monitor tripped at `89.36%` paired by frame 7.
  - Temperature ran away faster: last reported temp `987.8 K`, tempavg `979.5 K`.
  - Watson-Crick final DCD frame: absolute `0.20%`, reference-relative `4.51%`.

Interpretation:

- The corrected ENM is technically wired correctly, but switching it on hard at
  310 K is not stabilizing. It increases local-order force response and
  accelerates overheating/geometry loss unless introduced through a much gentler
  ramp.
- The 5000-step immediate-310 K minimization path is not beneficial. It emits
  many GBIS sentinel energies and can lead to early CUDA exclusion failure even
  when the C1' geometry still looks good.
- C1' distance alone overestimates health. F011A retained `99.6%` by C1' but
  only `78.7%` reference-relative Watson-Crick geometry in the final available
  frame; ENM direct-start tests were far worse.

Next recommended quick branch:

- Do not run the current F010 310 K stages as-is.
- Use the corrected zero-based ENM file, but introduce it cold and weak:
  e.g. start at `25-50 K`, scale ENM force constants by `0.05-0.10`, keep k=1
  positional restraints initially, ramp temperature slowly, and only then reduce
  positional restraints.
- Alternatively, test the corrected ENM first in explicit solvent/Mg on a
  smaller subdomain, because GBIS direct 310 K continues to show severe heat
  release.

## F012_cold_weak_enm_production

Status: production attempt halted by early-instability gates.

Purpose: try to turn the F011 lesson into a production-capable path by starting
cold, keeping k=1 positional restraints, and introducing local-order ENM weakly
before warming.

Protocol generated:

- `local_order_enm_005.extrabonds`: corrected zero-based ENM at `5%` strength.
- `local_order_enm_100.extrabonds`: corrected ENM at `10%` strength.
- `local_order_enm_200.extrabonds`: corrected ENM at `20%` strength.
- `F012_00_25K_weak_enm.conf`: 25 K, k=1 positional, 5% ENM, 2 ps.
- `F012_01_50K_weak_enm.conf` through `F012_04_310K_weak_enm_smoke.conf` were
  staged but not promoted because stage-00 health failed the Watson-Crick gate.

Results:

- `F012_00_25K_weak_enm` completed with no fatal errors and no sentinel
  energies. Final C1' monitor stayed above threshold (`~93.1%` paired). However,
  temperature settled near `70 K` despite a `25 K` target, and Watson-Crick
  reference-relative retention was only `20.46%`.
- `F012_00b_25K_enm020` repeated the 25 K cold start with `20%` ENM. It also
  completed mechanically with no sentinel energies and similar C1' health
  (`~93.2%` paired), but Watson-Crick retention did not improve:
  `20.82%` reference-relative. Final temperature was still about `69 K`.
- `F012_00c_25K_enm100` tested full-strength ENM at 25 K. It failed before the
  first meaningful monitor window with `Low global CUDA exclusion count`
  at step `600`.

Interpretation:

- The cold/weak ramp fixes the worst immediate GBIS/NAMD blow-ups, but it does
  not preserve Watson-Crick heavy-atom geometry. This means it is not a valid
  base-pair-stable production path, even though the C1' tripwire looks passable.
- Raising ENM strength from `5%` to `20%` is not enough to recover base geometry.
  Full-strength ENM at 25 K destabilizes the CUDA run almost immediately.
- This brackets the GBIS+ENM approach: weak ENM is too weak to enforce chemistry;
  full ENM is too stiff for the current starting pose/implicit-solvent dynamics.

Production decision:

- Do not continue the staged F012 ladder to 50/100/150/310 K as a production
  attempt. It fails the early chemical-geometry gate at the cold first stage.
- Next credible production branch is explicit-solvent/Mg with a smaller
  subdomain or full B_tube if resources allow. The other necessary branch is a
  better atomistic base-pair rebuild: the F001 reference itself is not
  Watson-Crick-clean enough under strict heavy-atom criteria, and GBIS dynamics
  rapidly worsens that geometry.

## F013_explicit_mg_full

Status: full B-tube explicit-solvent/Mg warmup reached short unrestrained
310 K NPT without NAMD fatal errors, but failed the base-pair geometry gate.

Purpose: retry the warmup-to-production path using explicit TIP3P solvent,
150 mM NaCl, and 12.5 mM MgCl2 instead of GBIS, starting from
`workspace/B_tube_relaxed_atomistic_F001.nadoc`.

Build and setup:

- Package directory:
  `results/runs/F013_explicit_mg_full/B_tube_namd_solvated/`.
- Full explicit system after ion replacement:
  `2,314,212` atoms = `289,470` DNA atoms, `668,498` waters, `16,400` Na,
  `190` Mg, and `2,658` Cl.
- Box: approximately `15.63 x 15.37 x 104.96 nm`.
- Hardware check: RTX 2080 SUPER 8 GB. NAMD used about `5.8 GB` GPU memory.
- Fixed package-builder issues:
  - `build_explicit_mg_package.py` now inserts the repo root into `sys.path`
    when run directly.
  - `namd_solvate.py` water/ion segment IDs now scale to large explicit
    systems via fixed-width `W000`, `W001`, `I000`, ... segments instead of a
    short hard-coded water segment list.
  - Solvation stats now count final atoms after waters are replaced by ions.
- CUFIX issue: `toppar_water_ions_cufix.str` includes protein/lipid NBFIX atom
  types that are not defined by this DNA-only force-field bundle. The package
  now uses `toppar_water_ions_cufix_dna_only.str`, generated by
  `filter_cufix_for_package.py`, which filtered `95` undefined NBFIX lines.

Protocol generated by `setup_explicit_mg_warmup.py`:

- `F013_00_min`: 500-step restrained minimization, k=5 DNA heavy-atom
  positional restraints.
- `F013_01_25K_1ps`: restrained NVT, 25 K, k=5.
- `F013_02_50K_1ps`: restrained NVT, 50 K, k=5.
- `F013_03_100K_1ps`: restrained NVT, 100 K, k=3.
- `F013_04_200K_1ps`: restrained NVT, 200 K, k=2.
- `F013_05_310K_2ps`: restrained NVT, 310 K, k=1.
- `F013_06_310K_NPT_2ps`: restrained NPT, 310 K, k=1.
- `F013_07_310K_NPT_unrestrained_2ps`: unrestrained NPT, 310 K.
- `F013_08_310K_NPT_unrestrained_monitor_1ps`: unrestrained NPT, 310 K,
  DCD every 200 steps for monitor analysis.

Key results:

- Initial direct NPT at 25 K failed immediately with
  `Periodic cell has become too small for original patch grid`; pressure was
  around `-433 kbar`. This confirmed early warmup must be fixed-volume NVT.
- Restrained NVT ramp completed. The 25 K stage heated to `~549 K` at step 100
  from solvation/starting strain, then cooled monotonically. By the end of
  `F013_05_310K_2ps`, temperature was `300.44 K`, but pressure was still
  around `-40.6 kbar`.
- After NVT pre-equilibration, short NPT no longer patch-grid-crashed:
  `F013_06` ended near `310.15 K`, instantaneous pressure `-13.9 bar`,
  pressure average `-3.3 bar`.
- The unrestrained 2 ps NPT smoke (`F013_07`) completed and was numerically
  stable: final temp `310.15 K`, instantaneous pressure `-13.9 bar`, pressure
  average `-3.3 bar`.
- The trajectory-emitting unrestrained continuation (`F013_08`) also completed,
  but monitors showed rapid base-pair geometry loss:
  - C1' monitor, final frame: `56.72%` paired at `13 Å`, tripped below the
    `90%` gate.
  - Watson-Crick monitor, final frame: `1.78%` absolute, `9.97%`
    reference-relative, mean heavy-atom proxy `5.46 Å`, p90 max proxy `8.35 Å`.

Interpretation:

- Explicit solvent/Mg fixes the worst numerical warmup behavior seen in GBIS:
  the full B-tube can be heated to 310 K and pressure-coupled on this machine,
  albeit slowly (`~0.47 ns/day` NVT, `~0.41 ns/day` NPT).
- It does not solve the structural problem when restraints are removed. The
  origami can run numerically, but base-pair heavy-atom geometry is lost within
  the first few picoseconds of unrestrained NPT.
- This points back to starting atomistic geometry and/or missing production
  restraints, not just implicit-solvent artifacts. A production protocol should
  keep a chemistry-aware restraint/ENM term during longer solvent equilibration,
  or rebuild base-pair coordinates before attempting unrestrained production.

## F014_explicit_mg_restraint_ladder

Status: found the first stable full B-tube explicit-solvent/Mg production-like
foothold, but it requires strong DNA heavy-atom positional restraints.

Purpose: after F013 showed that unrestrained 310 K NPT is numerically stable but
rapidly loses base-pair geometry, bracket the minimum positional-restraint
strength that preserves Watson-Crick-like geometry.

Branch point:

- All F014 one-picosecond tests branch from the good restrained NPT state
  `F013_06_310K_NPT_2ps`, not from the degraded unrestrained F013 frames.
- Config generator:
  `scripts/setup_explicit_mg_restraint_ladder.py`.
- Scoring:
  - C1' gate: `paired-max-ang 13.0`, target `>= 90%`.
  - Watson-Crick gate: reference-relative retention; use this as the stricter
    chemistry-health signal because the strict absolute cutoff is low even for
    the current reference.

Short ladder results:

- `F014_01_k1_310K_NPT_1ps`: numerically stable, final temp `309.83 K`,
  pressure average `11.87 bar`, C1' `94.84%`, but Watson-Crick
  reference-relative only `38.26%`. k=1 is not enough.
- `F014_00b_k3_310K_NPT_1ps`: numerically stable, final temp `311.44 K`,
  pressure average `22.02 bar`, C1' `98.68%`, Watson-Crick reference-relative
  `76.24%`. k=3 improves geometry but is still weak.
- `F014_00a_k4_310K_NPT_1ps`: numerically stable, final temp `311.83 K`,
  pressure average `1.56 bar`, C1' `99.15%`, Watson-Crick reference-relative
  `85.72%`. k=4 is marginal.
- `F014_00_k5_310K_NPT_1ps`: numerically stable, final temp `312.24 K`,
  pressure average `8.23 bar`, C1' `99.20%`, Watson-Crick reference-relative
  `92.17%`. k=5 passes the current short-run geometry gate.

Longer validation:

- `F014_10_k5_310K_NPT_4ps` continued from `F014_00_k5_310K_NPT_1ps`,
  giving 5 ps total at k=5 after the F013 warmup.
- It completed without NAMD fatal errors. Final temp `309.84 K`, tempavg
  `309.80 K`, instantaneous pressure `55.99 bar`, pressure average `8.85 bar`,
  volume `24,135,353 Å^3`.
- Final C1' monitor: `99.45%` paired, mean C1' `11.48 Å`, p90 `12.36 Å`.
- Final Watson-Crick monitor: `94.12%` reference-relative, mean heavy-atom
  proxy `3.90 Å`, p90 max proxy `5.08 Å`.

Interpretation:

- The current full-origami explicit-solvent/Mg route has a stable simulation
  mode: 310 K NPT with DNA heavy-atom positional restraints at
  `constraintScaling 5`.
- The restraint boundary is sharp enough to be useful: k=5 passes, k=4 is
  marginal, k=3 and k=1 fail the Watson-Crick geometry gate despite passing the
  looser C1' tripwire.
- This is not yet an unrestrained physical production protocol. It is a
  restrained-equilibration/prototype-production protocol that preserves the
  current reference geometry long enough to study solvent, ion, and pressure
  behavior.
- Next iteration should try more chemically specific stabilization, such as
  base-pair/stacking ENM in explicit solvent, so positional restraints can be
  reduced without immediately losing Watson-Crick geometry.

## F015-F017_literature_parameter_probes

Status: established-practice parameters improved physical alignment, but did
not yet replace the strong positional restraint floor.

Literature targets checked:

- Maffeo/Yoo/Aksimentiev 2016 used NAMD, CHARMM36 nucleic-acid parameters,
  TIP3P, PME, `300 K`, Langevin damping `1 ps^-1`, and NVT production after box
  setup. Explicit-solvent startup included DNA non-hydrogen Cartesian
  restraints at `k=1 kcal/mol/A^2`, then dense intra-helical ENM restraints at
  `k=0.1 kcal/mol/A^2` between nearby non-hydrogen DNA atoms within `0.5 nm`.
- The same work reports later explicit-solvent equilibration with weak
  Watson-Crick restraints at `k=0.1 kcal/mol/A^2`.
- The Aksimentiev practical tutorial also uses Mg-containing explicit solvent
  and NAMD extraBonds workflows; the local force field defines `MGH`
  Mg-hexahydrate residues, but the current NADOC package still places direct
  `MG` ions.

Baseline longer run:

- `F014_20_k5_310K_NPT_20ps` continued the successful k=5 positional-restraint
  branch. It completed cleanly at temp `309.85 K`, tempavg `309.91 K`,
  pressure average `19.31 bar`, volume `23,356,488 A^3`, throughput
  `0.400 ns/day`.
- Final C1' monitor: `99.48%` paired, mean `11.44 A`, p90 `12.33 A`.
- Final Watson-Crick monitor: `96.12%` reference-relative, mean heavy-atom
  proxy `3.88 A`, p90 max proxy `5.04 A`.

Literature-leaning probes from `F014_20`:

- `F015_01_enm_k0p5_300K_NVT_2ps`: sparse local-order ENM at the tutorial-style
  k=0.5 stage, NVT, `300 K`, damping `1`, piston off. Numerically stable, but
  structurally failed: C1' tripped at `68.51%`; Watson-Crick final was
  `20.97%` reference-relative. Do not continue this sparse ENM ladder.
- `F016_01_dense_enm_k0p1_300K_NVT_2ps`: generated a dense non-hydrogen DNA
  5 A ENM at `k=0.1`. First attempt failed before dynamics because the dense
  file duplicated PSF covalent bonds; `generate_dense_enm_restraints.py` now
  filters topology bonds. The filtered ENM has `3,483,488` restraints and ran
  at `0.451 ns/day`. It improved C1' retention to `90.94%`, but Watson-Crick
  retention was still only `42.24%`.
- `F017_01_wc_k0p1_300K_NVT_2ps`: weak Watson-Crick heavy-atom restraints only,
  `15,597` extraBonds at `k=0.1`, NVT, `300 K`, damping `1`. Numerically
  stable and cheap (`0.470 ns/day`) but failed structurally: C1' tripped at
  `68.28%`; Watson-Crick final was `19.19%` reference-relative.

Interpretation:

- The current successful mode remains k=5 DNA heavy-atom positional restraints.
  It is not physical production, but it is the only branch that preserves
  Watson-Crick geometry over a 20 ps explicit-solvent/Mg window.
- Published-like weak ENM/WC restraints assume a better-prepared starting model
  and much longer restrained equilibration. On the current B-tube coordinates,
  replacing k=5 directly with weak chemistry-aware restraints loses geometry
  within the first saved picosecond.
- The dense ENM result is informative: it preserves gross C1' pairing much
  better than the sparse ENM, so the sparse restraint set is underconstrained.
  However, preserving actual Watson-Crick geometry still needs either stronger
  base restraints, longer k=1/k5 equilibration before release, a cleaner
  atomistic rebuild, or the missing `MGH` Mg-hexahydrate treatment.
- Recommended next branch: implement MGH placement/extrabonds or build a
  smaller literature-faithful package first; in parallel, test a staged ramp
  from k=5 positional to k=1 positional over tens of ps before switching to
  dense ENM, rather than abrupt k=5 -> weak ENM/WC.

## F027_literature_aligned_enm_production

Status: planned; supersedes zero-restraint production as the main long-run
candidate.

Reason for the pivot:

- The literature-standard origami workflow is not a short ps-scale positional
  release. It uses explicit solvent, CHARMM36/CUFIX, TIP3P, PME, Mg-containing
  ion conditions, nanosecond-scale DNA non-hydrogen positional equilibration,
  and dense local-order ENM support before long production.
- Existing F018-F020 packages used MGH Mg-O extraBonds at k=500 kcal/mol/A^2.
  Published counterion protocols use k=1 kcal/mol/A^2 at 1.94 A. NADOC package
  generation has been corrected for new packages; existing F018-F020 artifacts
  remain historical.
- The full B_tube hardware benchmark found standard CUDA at `+p8`,
  `fullElectFrequency 1` is the current usable full-system production setting
  at about 0.97 ns/day. GPU-resident full B_tube runs are not production-ready
  until they produce valid `ns/day` and pass health checks.

Protocol summary:

- Build a fresh explicit-solvent MGH package.
- Verify `mgh_extrabonds.txt` contains `1.0000 1.9400`.
- Use `rigidBonds all`, `fullElectFrequency 1`, 1 fs timestep, and Langevin
  damping 1 ps^-1 after warmup.
- Run 10 ns with DNA non-hydrogen positional restraints at k=1.
- Handoff to dense intra-helical ENM at k=0.1, 5 A cutoff, filtering PSF bonds.
- Retain ENM through the first 50 ns production candidate.
- Gate with both C1' and Watson-Crick reference-relative monitors.

Detailed card: `exp_cards/F027_literature_aligned_enm_production.md`.
