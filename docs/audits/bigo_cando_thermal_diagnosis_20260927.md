# BigO CanDo thermal reconstruction: live, non-interrupting diagnosis

Observed 2026-09-27 21:11–21:14 America/Denver. Job `29da658d7294`,
`BigO-poly.nass`, 424,144 nucleotides / 211,680 mesh nodes. Linear prediction,
RMSF and thermal fluctuations enabled. No backend source, job files, process
settings or server state changed. No simulation or broad tests launched.

## Live evidence

At 21:14:20 the job remained `running`, about 97 minutes since its stage started.
Snapshot, mesh, elastic deformation and normal modes/RMSF were complete.
Latest thermal checkpoint: 30/48 frames (0.625), written at 21:06:27.
Progress is written every five frames, so the actual frame may be further ahead.
Overall UI progress was 93%; cache phase had not begun. An ETA cannot be inferred
reliably from this single checkpoint, and total elapsed time includes the NMA.

API process PID 447004 hosted the worker; thread 448540 consumed 86.5% of one
CPU over a 40.9-second /proc sample. Process RSS was approximately 7.4 GiB,
with a process high-water RSS of about 15.1 GiB. Host available memory was
about 13.4 GiB; swap usage and memory-pressure averages were zero. Disk had
426 GiB free; process read_bytes stayed constant during observation. These
measurements indicate CPU work, not a swapping or disk-capacity bottleneck;
CPU activity alone does not prove useful frame completion. The process also
hosts API traffic, so whole-process CPU/IO are not exclusively this job.

Nonblocking py-spy stack inspection was denied by OS permissions; passwordless
sudo was unavailable. No signal, debugger stop, restart or permission change
was used. Consequently no claim is made about measured per-function shares.

## Confirmed repeated work in source

`backend/physics/fem_solver.py:3237` loops serially over all 48 thermal draws.
Each calls `deformed_positions_with_axis`, retaining only backbone XYZ values.

- Every draw rebuilds strand/overhang membership, helix/node reference axes,
  nucleotide identity/copy metadata, straight geometry and displayed reference
  geometry, although these are immutable across the ensemble.
- `_wound_backbones_for_helix` uses Python per-node/per-nucleotide loops and many
  tiny NumPy operations. It transports normals and tangents for every draw;
  the thermal trajectory discards those orientation fields.
- Full per-nucleotide dictionaries and 211,680 axis dictionaries are emitted
  per draw; thermal frames discard the axis result immediately.
- The snapshot has 112 StrandExtensions. Their reconstruction path builds
  `native_nucs` by visiting **every helix again**, despite only needing terminal
  anchor geometry. This repeats on every frame. The snapshot has no deformation
  operations or cluster transforms, so straight/shown/native geometry duplicate
  underlying nucleotide generation three times per frame.
- The selected representative is reconstructed once more after all 48 draws.
- Frames accumulate as Python lists containing 61,076,736 coordinate scalars.
  The subsequent dense float64 copy alone is 466 MiB; boxed Python floats/lists
  and RMSF temporaries add substantially more. The complete trajectory is then
  serialized using `json.dumps`, another allocation-heavy phase still pending.

This establishes avoidable work and allocation, not a measured speedup. The
prior ~162-second BigO app runs disabled RMSF/thermal sampling and therefore
are not comparable to this 48-frame workload.

## Improvement order, preserving numerical/scientific behavior

1. Build an immutable, per-job reconstruction context once: reference geometry,
   strand coverage, copy identities, node registration, terminal anchor offsets
   and Kabsch target. Never cache across mutable editor designs.
2. Provide an XYZ-only thermal reconstruction path; retain full orientation/axis
   reconstruction for the selected representative. Preserve the exact winding,
   rigid alignment, terminal-following and loop-copy semantics.
3. Preallocate numeric frame storage and avoid per-frame dictionaries and boxed
   scalar lists; bound RMSF/statistics temporaries and serialization memory.
4. Report each completed frame and representative/statistics/cache phases.
   Current phase weights allocate only 8% to all thermal reconstruction and 4%
   to caching, so 93% is not 93% of elapsed runtime.

Do not reduce mode/frame counts, alter physical parameters or change geometry
constants as a performance shortcut. Implement after the live job finishes (or
in a separate checkout), because the current server watches backend source for
reload. Validate numerical equivalence and profile a bounded representative
workload before claiming gains. This diagnosis intentionally changes no code.
