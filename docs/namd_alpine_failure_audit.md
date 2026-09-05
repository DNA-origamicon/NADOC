# Alpine NAMD transition audit — 2026-09-04

## Observed failure

The originally investigated Alpine `small_plate.nadoc` job is `d882c98ac759`, Slurm `32086330`,
node `c3gpu-g7-u5`. Slurm recorded FAILED, exit `6:0`, elapsed `00:22:47`.
The saved `output/nadoc_failure.log` identifies the first dynamics stage,
`small_plate_0S_300K_NPT_settle_fixed_dna_p100`, and NAMD's fatal:

> Periodic cell has become too small for original patch grid!

Minimization completed and its final coordinate, velocity and extended-system files
are present. The initial cell is 348.655 × 70.726 × 349.180 Å. The settle stage uses
4 fs, hydrogen mass repartitioning, rigid bonds, GPU-resident integration and isotropic
NPT. It failed before the first 5,000-step restart; no settle restart triplet exists.
The surviving log contains only the step-zero energy record, so it does **not**
establish the exact failure step or final volume.

NAMD sizes its patch grid at startup. A contracting NPT cell can invalidate that
grid; restarting with the checkpoint cell rebuilds it. This mechanism is described
in the [NAMD developers' explanation](https://www-s.ks.uiuc.edu/Research/namd/mailing_list/namd-l.2018-2019/0966.html).
Alpine's generated script previously terminated on this error, unlike the local
runner and RunPod. Merely retrying the original input would rebuild the original
grid. Here, a checkpoint-only retry would also be insufficient because none exists.

## Fixes

- Alpine now handles this exact fatal inside the existing allocation, for every
  dynamics segment, with at most four retries. A valid checkpoint supplies coordinates,
  velocities, cell and remaining step count. Missing/torn checkpoints, lack of forward
  progress and cumulative volume below 85% of the starting volume refuse recovery.
- One pre-checkpoint retry is allowed with the original starting state, a 10× slower
  Langevin piston and denser restart output. Later checkpoint-free retries are refused.
  The piston is softened once relative to the original input, not exponentially.
- Retry configurations retain the timestep, HMR structure, constraints, physical
  anchor targets/weights, electric field and extra bonds. Partial trajectories are
  copied to `output/<segment>.cell_archiveN.*`; these diagnostic archives are separate
  from the ordinary displayed trajectory. Recovery state and failed logs remain in output.
- Initial submission and manual Resume both stage the Python 3.6-compatible recovery
  helpers, including the shared remaining-step configuration builder.
- Appended production now preserves harmonic anchor settings instead of interpreting
  the binary anchor marker as hard fixed atoms. Production children inherit the parent's
  harmonic stiffness by default; an explicit stiffness remains authoritative.
- Graphene-only control production retains NVT, including legacy packages whose
  solvation metadata incorrectly said NPT was allowed.

## Anchor and nanopore checks

The actual package contains 818,525 atoms, including 42 DNA anchor atoms and 38,617
graphene atoms. The minimization, settle and final-release configurations all retain
DNA anchor k=0.1 and graphene k=50 kcal/mol/Å². Settle adds k=1 restraints on 32,706
other DNA heavy atoms; the final release removes those temporary restraints.
The observed failure is therefore not loss of the physical anchor selection.

The audit covered generated Alpine GPU/CPU commands, initial/resume helper staging,
checkpoint continuation, harmonic production inheritance, graphene-only NVT lineage,
and the existing anchor, graphene, replica and early-stop tests. Mock-NAMD tests execute
the emitted shell loop and establish that patch-grid failures retry while RATTLE
failures remain terminal. These checks do not establish live molecular stability.

## Existing job

The saved job and completed minimization are preserved. A reviewable regenerated
submission and helper files are under its local `recovery/` directory. No new Slurm
allocation has been submitted. **Superseded by the R1 investigation:** do not resume these graphene checkpoints.
The [graphene wall audit](namd_graphene_wall_failure_audit.md) identified an additional
force-field defect missed by this initial restraint/submission audit. Copy and Run
must rebuild the package and repeat minimization with the corrected wall model.

## Verification results

- Focused NAMD/Alpine/anchor/nanopore tests: **332 passed**, 5 deselected.
- Generated recovery sbatch: `bash -n` passed. Ruff and `git diff --check` passed.
- Final `just test-smart`: **FAST**, 7,620 passed, 35 skipped, 1 failed, 1 setup error;
  76 s, below the 90 s backstop, with no remaining per-test budget violations.
  The remaining failures depend on mutable workspace fixtures: the VoltronCoreArm
  cluster test expects empty clusters, and the BigO assembly fixture expects 56
  flattened helices while its current file produces 168. Those assertions are outside
  the changed NAMD paths and their fixture files were left intact.
- Updated the NAMD prep test's solvation stub to accept the existing `padding_xyz_nm`
  keyword. Three full six-helix atomistic projection tests measured 9.8–10.9 s each;
  required slow-test triage retained them in the registered slow/oxdna suite. Fast
  selection intentionally decreased by three tests; slow collection confirmed all three.

The gate reported:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
