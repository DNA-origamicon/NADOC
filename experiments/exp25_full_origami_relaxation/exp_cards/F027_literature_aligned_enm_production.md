# F027: Literature-Aligned ENM-Retained Production Candidate

## Hypothesis

A fully solvated B_tube production run will remain stable on long timescales if
it follows the published DNA-origami atomistic workflow more closely than F020:
MGH Mg-O restraints at k=1 kcal/mol/A^2, nanosecond-scale restrained
equilibration, dense intra-helical ENM retained during production, and Watson-
Crick health gates throughout. The target is not zero-restraint production; the
target is a publishable, long-run production protocol consistent with established
DNA-origami MD practice.

The claim is falsifiable: after >=10 ns of restrained equilibration and >=15 ns
of ENM equilibration, a 50-100 ns ENM-retained production run should maintain
WC reference-relative fraction >=85% and C1' paired fraction >=90% without NAMD
sentinel energies, runaway pressure, or sustained temperature drift.

## Motivation

The current F020-style release ladder improved basic NAMD parameters
(`rigidBonds all`, 1 fs, `fullElectFrequency 1`, isotropic NPT), but it still
used ps-scale equilibration and attempted a fully unrestrained endpoint. The
published Aksimentiev workflow instead uses long restrained equilibration,
replaces Cartesian restraints with a dense local-order ENM, and only attempts
unrestrained dynamics after much more preparation. Recent Aksimentiev-derived
and adjacent protocols also keep base-pair or ENM-like support during long
production when the DNA object is large, stressed, or coupled to another soft
material.

F020 also used MGH Mg-O extraBonds at k=500 kcal/mol/A^2. Published counterion
work used a 1.94 A Mg-O distance with k=1 kcal/mol/A^2 during MGH formation and
equilibration. Future packages generated after this card should use the corrected
NADOC default.

Hardware benchmark F026 showed that local full B_tube runs are expensive:
standard CUDA at `+p8`, `fullElectFrequency 1` gives roughly 0.97 ns/day on the
tested workstation. GPU-resident full B_tube benchmark did not yield a usable
`ns/day` value and should not be used for production until it completes a
scientific smoke with normal health metrics.

## Starting Point

Use a newly generated explicit-solvent B_tube package, not the existing F018-F020
package, so that MGH extraBonds are regenerated at k=1. Use the F001 minimized
atomistic reference as the coordinate source if the topology hash still matches.

Recommended package settings:

- CHARMM36 nucleic acids + CUFIX water/ion stream.
- TIP3P water.
- MGH enabled, with Mg-O extraBonds at k=1 kcal/mol/A^2 and r0=1.94 A.
- Salt: keep current MgCl2 condition for comparability unless the wet-lab buffer
  target is more specific; record Na, Mg/MGH, and Cl counts in the manifest.
- PME grid spacing about 1 A.
- `rigidBonds all`.
- `timestep 1.0` for equilibration and first production candidate; only promote
  to 2 fs after a shorter A/B run shows identical health.
- `fullElectFrequency 1` for the first production candidate.
- Langevin damping 1 ps^-1 after cold warmup.
- Isotropic NPT for box equilibration; NVT may be used for the final production
  branch if pressure/volume have already settled and fixed volume is preferable.

2026-05-20 2 fs probe branch:

- `F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.conf` starts from the
  last healthy `F027_05` checkpoint, keeps weak DNA positional restraints
  (`constraintScaling 0.1`) plus dense ENM, and uses `timestep 2.0`,
  `rigidBonds all`, `fullElectFrequency 1`, `stepspercycle 20`.
- `F027_06b_310K_NPT_pos0p1_enm0p1_2fs_fef2_probe50ps.conf` is the MTS
  throughput comparator (`fullElectFrequency 2`). It should not be promoted
  unless it matches the fef1 probe on health and energy stability.
- Run with `run_f027_2fs_probe.sh fef1` first, then `run_f027_2fs_probe.sh fef2`
  or `both` after the NVIDIA driver/library mismatch is fixed.

2026-05-20 fast-screening branch:

- `setup_f027_fast_screen.py` creates deliberately labeled screening variants
  that trade absolute MD rigor for fast relative stability signals.
- The best stable explicit-solvent speed so far is
  `F027_fast_01_2fs_fef2_enm_pos0p1_10ps` at `+p12`: `1.80 ns/day`,
  C1' `99.81%`, temperature average `309.35 K`. This keeps dense ENM and weak
  positional restraints, so it is best interpreted as a fast relative stability
  screen rather than an unrestrained production trajectory.
- Fully unrestrained explicit solvent,
  `F027_fast_03_2fs_fef2_unrestrained_10ps`, reached `1.89 ns/day` but the
  short-window structural signal became much noisier: C1' `86.64%` and WC
  proxy `17.69%`. Removing dense ENM/positional restraints therefore improves
  throughput only modestly; full explicit solvent PME remains the main speed
  ceiling.

2026-05-20 GBIS implicit-solvent benchmark branch:

- Built `F027_gbis_implicit_screen` DNA-only and DNA+ions/MGH packages from the
  relaxed F027 checkpoint, stripping TIP3 water and using NAMD GBIS with no PME,
  `cutoff 16`, `alphaCutoff 14`, `ionConcentration 0.3`,
  `nonbondedFreq 2`, and `fullElectFrequency 4`.
- DNA-only raw dynamics, DNA-only minimized warm-start, DNA-only positional
  restraints, and DNA+ions/MGH all failed with fast-atom instabilities. The
  minimized warm-start showed a fast minimization-equivalent rate (`4.854 ns/day`)
  but produced sentinel electrostatic energies and failed shortly after
  velocities were assigned.
- Conclusion: naive all-atom GBIS stripping is not a usable B_tube stability
  screen yet. The benchmark notes are in
  `results/runs/F027_gbis_implicit_screen/GBIS_BENCHMARK_NOTES.md`.

## Protocol

1. Build a fresh package and verify:
   - `mgh_extrabonds.txt` contains `1.0000 1.9400`.
   - No NAMD fatal warnings in `run 0`.
   - `restraints_dna_heavy.pdb` restrains DNA non-hydrogen atoms only.

2. Minimize:
   - 10,000-50,000 steps with DNA non-hydrogen positional restraints at k=1.
   - Halt if sentinel energies persist after accepted minimization steps.

3. Warm to production temperature:
   - NVT 0 -> 50 -> 100 -> 200 -> 300/310 K.
   - Keep positional k=1.
   - Use health gates at every segment boundary.

4. Restrained equilibration:
   - 10 ns at 300/310 K with DNA non-hydrogen positional restraints at k=1.
   - NPT if the box has not settled; otherwise NVT at the settled volume.
   - Monitor Mg-P radial distribution or nearest-neighbor Mg-P distances every
     1 ns to ensure ion placement is no longer rapidly drifting.

5. ENM handoff:
   - Generate dense intra-helical ENM at k=0.1 kcal/mol/A^2, 5 A cutoff,
     non-hydrogen DNA atoms only, filtering PSF covalent bonds.
   - Run 1 ns with positional k=0.1 plus ENM k=0.1.
   - Run 15 ns with ENM k=0.1 and no Cartesian positional restraints.
   - Optional: add weak WC restraints only if the ENM-only stage loses WC
     registry but keeps gross C1' pairing.

6. Production candidate:
   - 50 ns ENM-retained run as the first milestone.
   - Extend to 100 ns only if the 50 ns trajectory passes health gates and the
     drift rate over the final 20 ns is flat.

## Health Gates

- C1' paired fraction >=90%.
- WC reference-relative fraction >=85%.
- Temperature mean within 300/310 K +/- 5 K after warmup.
- No sustained pressure or volume runaway.
- No NAMD sentinel energies or fatal CUDA/exclusion errors.
- Localize WC failures by helix/crossover before continuing a degraded run.

## Expected Outcome If Correct

The system remains stable under ENM-retained production for 50 ns, with local
base-pair registry preserved and global origami relaxation visible but bounded.
This becomes the first full B_tube production protocol suitable for scaling to
longer trajectories or stronger hardware.

## Expected Outcome If Wrong

The structure fails during the 10 ns k=1 stage or the 15 ns ENM stage. If failure
occurs under k=1, the atomistic rebuild or solvent/ion placement is still bad. If
failure occurs only after Cartesian restraints are removed, the handoff needs
stronger WC/crossover-local restraints or helix-level COM restraints before any
full production attempt.

## Priority

Highest. This supersedes zero-restraint F020-style production as the main
production path. F021/F022/F026 remain useful branches, but F027 is the clean
long-run candidate that best matches published practice and the hardware budget.
