# GPU electrode correction (experimental, 2026-09-14)

`correction.cu` implements the existing fixed-cell EW3DC slab correction,
repulsive walls and harmonic electrode/PEG anchor forces through NAMD's
`CudaGlobalMasterClient` interface. The installed December 2025 NAMD source
already provides the dynamic plugin interface: no installed engine rebuild or
replacement is necessary. The local NADOC runner now selects this validated plugin for compatible resident
electrode jobs. See `docs/namd_electrode_gpu.md` for package checksums, restart and
fallback behavior; the scientific qualification scope remains explicit.

## Physics and transfers

For axis a, M = sum(q_i x_ia), the correction is U = C M² and
F_ia = -2 C q_i M, using the existing generated package's coefficient C.
Mobile atoms outside [low, high] receive -k_wall d along a. Anchors receive
-k_anchor (x - reference), with the corresponding half-k-displacement-squared
energies. All reductions use doubles. Charges include water and electrode atoms,
not just ions. Charge density is represented by the existing electrode sites;
this does not implement a constant-potential metal or electronic polarization.

Static charges, mobility and anchors are uploaded once. Atomic positions, moment
reduction and applied forces stay on GPU in ordinary dynamics. Only the scalar
correction energy is copied to CPU when NAMD requests energy output. The `audit`
command deliberately copies positions and forces for validation only. NAMD's
GPU server still synchronizes its CUDA stream each step; this implementation
removes CPU atom/force handling but does not eliminate every CPU synchronization.

The plugin rejects nonresident mode, known barostats/multigrator, malformed
parameters and nonneutral cells. It supplies no pressure virial: fixed-cell
production only. It is locally qualified on one RTX 3080 Ti with 38,644 atoms,
2 fs, fixed charges, orthogonal padded cell. Multi-GPU, distributed execution,
variable cell, minimization, the full accelerated ladder, actual DNA/PEG systems
and long-time transport/screening remain separate qualification work. Generic
harmonic mobile tethers are included in the force audits.

## Reproduce locally

Run from the repository root. Output directories must be new. The build uses
CUDA 12.0, supported GCC 12, sm_86, and the installed NAMD build's exact ABI flags.
It records the engine/plugin/source SHA-256 and copies our CUDA source beside the
library. NAMD headers/source are not copied into this repository.

```bash
uv run python experiments/electrode_relax/gpu_correction/build.py \
  --source /home/jojo/Applications/NAMD_Git-2025-12-04_Source \
  --output workspace/my_electrode_gpu_plugin

PYTHONPATH=. uv run python experiments/electrode_relax/gpu_correction/validate.py \
  --package workspace/md_jobs/2fb3c67ae5d9/package/system_namd_solvated \
  --plugin workspace/my_electrode_gpu_plugin/electrode.so \
  --binary workspace/electrode_native_bridge_v2/namd3 \
  --output workspace/my_electrode_gpu_validation

PYTHONPATH=. uv run python experiments/electrode_relax/gpu_correction/benchmark.py \
  --package workspace/md_jobs/2fb3c67ae5d9/package/system_namd_solvated \
  --plugin workspace/my_electrode_gpu_plugin/electrode.so \
  --binary /home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3 \
  --cpu-binary workspace/electrode_native_bridge_v2/namd3 \
  --output workspace/my_electrode_gpu_benchmark
```

The harness clones the prepared final checkpoint into an isolated directory,
retains input files read-only by symlink, and never changes the original job.
It is deliberately specific to generated `system_validation_p3` packages.
`render` refuses unknown Tcl callbacks or pre-existing GPU clients rather than
silently dropping additional forces. All immutable settings must precede
`gpuGlobalCreateClient`: that command initializes NAMD. The generated config
removes the CPU electrode callback to avoid applying the same force twice.

Parameter file: `N axis C low high wall_k`, followed by N rows
`charge mobile reference_x reference_y reference_z anchor_k`; atom order is PSF
order, lengths Å, energies kcal/mol. Preserve its hash, plugin hash, installed
engine hash and prepared package when adopting an experimental continuation.
The application restart/provenance integration is now implemented in
`backend/core/namd_electrode_gpu.py`; the runner pins package-local library,
parameters, topologies, reference callback and engine checksums.

## Validation evidence

- `workspace/electrode_gpu_validation_final/results.json`: all three axes with
  deliberately active walls, a perturbed electrode anchor, a generic mobile
  tether, plus the normal system; GPU/NumPy and GPU/direct-CPU force and energy
  audits. Maximum force differences are below 1e-8 kcal/mol/Å. Deliberately huge
  stress energies use absolute + relative tolerance (1e-8 + 1e-12 |U|), since
  different reduction orders differ by a few micro-kcal/mol at ~4e8 kcal/mol.
- `workspace/electrode_gpu_validation_v4/sanitizer_{race,mem}100.log`: 100-step
  fused/warp candidate, correction/dipole/reduce kernels only; zero reported
  race hazards or memory errors. This is not a whole-engine sanitizer claim.
- `workspace/electrode_gpu_tuning_v1/results.json`: 20,000-step individual-option
  screen, median timing from the second half of each run.
- `workspace/electrode_gpu_benchmark_final/results.json`: longer matched CPU/GPU
  timings and independent force/energy audits after dynamics/atom migration.
  `qualification.json` records zero restart-position discrepancies, passing
  final-library 100-step kernel memcheck/racecheck and nonneutral-cell rejection.
  The tuned repeats sustain 291–297 ns/day versus 43.1 ns/day CPU (6.8–6.9×).
- `tests/test_namd_gpu_correction.py`: configuration ordering, duplicate-force
  avoidance, preservation of the CPU control and rejection of unrelated callbacks.

## Additional optimization search

NAMD's [release notes](https://www.ks.uiuc.edu/Research/namd/3.0.2/notes.html)
recommend reducing frequent energy output and examining migration margin and
patch layout. Its [GPU documentation](https://www.ks.uiuc.edu/Research/namd/cvs/ug/node103.html)
describes experimental `GPUAtomMigration on` and `twoAwayZ on` for smaller systems.
The local notes also document splitting patches and small-system margins.

The screen holds timestep, cutoff, switching, PME spacing, vacuum padding and
forces fixed. Output is every 1,000 steps. Migration + twoAwayZ improved throughput
from ~253 to ~295 ns/day in the initial screen. More CPU workers, larger margin,
automatic steps-per-cycle selection, and fused/warp reductions did not provide
consistent gains. The final library therefore uses the simpler unfused reduction.
The longer benchmark finds margin 0 combined with migration/patch splitting slower (~271 versus ~297 ns/day), so retain the default margin 4.

Further candidates are NAMD GPU-server synchronization/event scheduling and energy
reduction only on requested steps. Removing the unconditional stream wait requires
an audit of dependencies across NAMD CUDA streams; simply deleting it is unsafe.
Changing PME resolution/padding, cutoffs, or 2 fs to 4 fs would change the numerical
or physical validation problem, so those are not counted as speed improvements.
No subsequent long scientific campaign is launched by these tools.

The selected experimental settings are `GPUAtomMigration on`, `twoAwayZ on`,
`+p1 +devices 0`, default margin 4 and the unfused library. NAMD explicitly
labels GPU atom migration experimental. Its differing Langevin gamma warning
(hydrogen thermostat disabled) remains; changing that thermostat is a separate
physical comparison, not a free performance adjustment.

Canonical maintained CUDA source: `backend/core/native/electrode_gpu.cu`. The
build script now uses that source. This directory retains the initial experiment
source and the independent native audit/benchmark harnesses.
