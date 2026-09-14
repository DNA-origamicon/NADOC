# Atomistic PEG brush infrastructure

2026-09-10. Independent experiment tooling; does not modify NADOC's production
molecular geometry, force fields, scheduler or ongoing oxDNA validation.

## What is available

- Deterministic length/density/replica planner with actual graft counts and units.
- Asset registry for existing all-atom PEG PSF/PDB conformers and a commensurate
  periodic gold slab, with parameter provenance and compatibility evidence.
- Builder that preserves supplied bonds/angles/dihedrals/charges while rigidly
  orienting and replicating chains, checks severe dry intercomponent overlaps
  under XY periodic boundaries, and writes a VMD solvation/NaCl script.
- Separate NAMD smoke, minimization, equilibration, timing and pilot inputs;
  NVT with fixed gold and harmonic anchor restraints. No HMR, electric field or
  implicit change to the electrode charge model.
- Hash-protected portable packages and post-build PSF/PDB/mask/charge checks;
  stage ordering, output preservation, per-case execution locks and Slurm-array
  entry point. No automatic submission, remote transfer or local MD launch.

**Current readiness:** planner and file-building path implemented and tested.
No physical PEG or gold assets have been imported, fitted or validated. Example
registry intentionally has null assets. A parameterized physical brush has NOT
been built, and NAMD has NOT been run on this new model. Missing assets are reported
before staging, rather than replaced with generic atom types. See
[GAPS.md](GAPS.md) and [parameterization_tasks.json](parameterization_tasks.json).

## Default pilot matrix (provisional design choices)

30 × 30 × 25 nm cell; N36, N45 and N76; requested graft densities 0.1, 0.3 and
0.5 chains/nm²; three replicas = 27 cases. Periodic square lattices round to
81, 256 and 441 chains, giving **0.0900, 0.2844 and 0.4900 chains/nm²**. Every
case records requested and achieved values. Replicas vary lattice translation,
chain azimuth, ion placement and velocity seed; they are NOT initially independent
polymer conformations when the same chain asset is used. Equilibrate and assess
mixing; use separate registries/conformers when testing initialization dependence.

Temperature 294 K keeps a link to current PEG comparisons. The 150 mM NaCl bath is
an explicit initial PEG-only reference condition, not an adopted origami buffer.
No Mg(H2O)6, DNA, Au–S bonds or electrode voltage are present in this first protocol.
The hypothetical slab top is 1.8 nm and graft plane 2.0 nm; replace both consistently
with the chosen physical slab. Do not force an Au lattice to exactly 30 nm by strain:
choose commensurate lateral cell dimensions and regenerate the plan.

The neutral fixed-gold + capped-PEG harmonic-tether construction measures a
mechanical reference brush with supplied gold cross interactions. It does not
claim to be a chemically complete thiolated PEG coating. A covalent linker model
will require explicit intercomponent topology and must not be silently substituted
for this protocol. Graft stiffness 5 kcal/mol/Å² is provisional and needs sensitivity
checks; a harmonic tether has three translational degrees of freedom, unlike a
fully specified Au–S attachment geometry.

Allocation per case: 5,000 minimization iterations, 2 ns initial equilibration,
100,000-step timing branch, 20 ns pilot. A 20 ns pilot is a sampling diagnostic,
not a convergence guarantee. At 2 fs, the timing branch is 0.2 ns. Pilot allocation
across all cases is 540 ns, plus 54 ns equilibration and timing. Do not run the whole
matrix before benchmarking and checking one low-density and one dense short brush.
N76 extended templates may not fit vertically: supply relaxed conformers instead
of truncating chains or wrapping them through the slab.

## Commands

From repository root, create a new plan (existing output directories are refused):

```bash
.venv/bin/python -m experiments.peg_namd.campaign \
  --output workspace/peg_namd/brush_plan_v1

.venv/bin/python -m experiments.peg_namd.build \
  --campaign workspace/peg_namd/brush_plan_v1 \
  --assets experiments/peg_namd/assets.example.json \
  --case n36_s0p1_r1 --check-assets
```

Copy the example registry to a new file and supply assets. Paths resolve relative
to that registry. Every chain must have exactly one segment and matching ordered
PSF/PDB atom identities (including segment, residue, atom names). Indices are
one-based PSF atom indices. Set repeat_units, exact end-group chemistry, provenance,
anchor/end atoms, and ordered parameter files. Parameters must be NAMD-readable
CHARMM parameter files/streams, not arbitrary topology streams. Audit duplicate
atom types and NBFIX load order; compatible file syntax is not physical validation.
The slab must have neutral, positive-mass atoms, explicit commensurate XY evidence,
coordinates in the declared frame, and no P*, WT* or ION segment names.

```bash
.venv/bin/python -m experiments.peg_namd.build \
  --campaign workspace/peg_namd/brush_plan_v1 \
  --assets /absolute/path/to/assets.json \
  --case n36_s0p1_r1 --output workspace/peg_namd/packages/n36_s0p1_r1
```

Within the staged package:

```bash
vmd -dispdev text -e build.tcl > build.log 2>&1
python3 verify_inputs.py --seal
# On the selected compute host, after checking the built geometry:
export NAMD_BIN=/absolute/path/to/namd3
bash run.sh smoke
bash run.sh minimize
bash run.sh equilibrate
bash run.sh benchmark
bash run.sh pilot
```

Native smoke is the first actual parameter/feature compatibility check. It is
required before minimization. GPU-resident fixed atoms/restraints must work on the
selected build; do not silently drop them if unsupported. `run.sh` does not overwrite
outputs or automatically restart failed stages. Investigate failures and stage a
new case/revision. Restarts between completed stages use binary coordinates and,
where appropriate, velocities; NVT cell dimensions stay fixed. Benchmark and pilot
both branch from equilibrated coordinates; timing data are not pooled into pilot
statistics. Record NAMD version/binary hash, GPU model/MIG slice, allocated GPU
count, driver/CUDA and CPU threads with measured timings on the target machine.

`run_array.sh` supports a prepared Slurm array using JOB_LIST, NAMD_BIN, PEG_STAGE,
NAMD_THREADS and NAMD_DEVICES. Cluster-specific account/partition/GRES/module setup
belongs in submission arguments or a reviewed site wrapper. It deliberately contains
no guessed H200/B200 resource names and no auto-submission. Benchmark 1 GPU/window
versus multi-GPU/window before selecting allocation strategy.

## Required checks before interpreting physical runs

1. Inspect slab seams, minimum-image solvent/solute contacts and chain placement.
   The built-file seal checks integrity, not water packing or force-field quality.
   VMD solvate does not guarantee periodic-image clearance; repair boundary solvent
   overlaps before sealing. Cell-size and solvent-density checks remain required.
2. Confirm all PEG bonded terms, terminal charges, nonbonded terms and cross pairs
   are intentional. NAMD smoke catches missing terms, not inaccurate ones.
3. Check the equilibrated water region's density and actual ion concentration;
   autoionize's nominal concentration is not a measured reservoir concentration.
4. Measure PEG density profiles, chain/end heights, Rg and chain relaxation; compare
   replicas and initialization histories. Block uncertainty by independent samples.
5. Verify finite-size and graft-stiffness sensitivity. Add a plate/tile force coordinate
   only after brush behavior is understood. No force-curve analysis is claimed here.

For Mg/DNA expansion, reuse the repository's established ion conventions deliberately;
MGH requires its extra bonds and NBFIX companion definitions. Do not simply replace
SOD with bare MG in this monovalent builder.
