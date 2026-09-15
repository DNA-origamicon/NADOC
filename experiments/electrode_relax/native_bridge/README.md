# Direct-array electrode force prototype

This experimental NAMD build removes per-atom Tcl coordinate/force conversion from
EW3DC slab correction, harmonic compartment walls, and electrode/PEG-anchor springs.
One Tcl command per step reads NAMD's gathered coordinate arrays and appends native
force arrays. It still gathers coordinates to a CPU worker; this is not a CUDA force
kernel or a replacement for the slab electrostatics model.

`build.py` reads an existing compiled NAMD source tree, adds a static command to
GlobalMasterTcl, compiles one replacement object and links a separate binary. It
preserves the installed source, objects and engine. Existing SDKs, libraries and
compiled objects are required. Output must be a new directory. No third-party
NAMD source or binary is committed here.

```bash
uv run python experiments/electrode_relax/native_bridge/build.py \
  --source /home/jojo/Applications/NAMD_Git-2025-12-04_Source \
  --output workspace/electrode_native_bridge_v2

PYTHONPATH=. uv run python experiments/electrode_relax/native_bridge/validate.py \
  --package workspace/md_jobs/222963230bfc/package/system_namd_solvated \
  --binary workspace/electrode_native_bridge_v2/namd3 \
  --output workspace/electrode_native_bridge_validation_v2
```

These commands are for explicitly user-authorized native experiments. Automated
heavy test suites retain their separate test-session gate. Existing output paths
above are retained artifacts; choose new paths for another invocation.

The command takes charges, mobile atom IDs, normal axis, EW3DC coefficient, wall
bounds/stiffness and site references. An optional true `audit` argument returns
energy and per-atom forces for comparison; ordinary dynamics avoids that conversion.
The audit tests all three normal axes and activates wall penetration and a displaced
spring without modifying the input coordinates. It compares every requested force
and correction energy to the existing compiled Tcl implementation before timing.

The first audit attempt failed because the test tried to rename NAMD's `addforce`
command before NAMD registered it. The corrected harness intercepts it during the
callback and restores it immediately afterward; this was a harness startup error,
not a force discrepancy. Failed-attempt artifacts are retained separately.

Limitations: fixed orthorhombic volume and neutral cell are enforced by package
preparation, not independently reimplemented by this low-level command. No barostat
virial support, multi-GPU/distributed qualification, actual PEG/DNA trajectory
qualification, or long-timescale equilibrium claim. The default application binary
has not been replaced. Native candidate use requires this custom binary and its
matching callback; the standard callback remains usable with the installed engine.

## Measured result (2026-09-14)

24,677 atoms, one worker, same checkpoint and 2 fs timestep:
- Existing compiled Tcl: 17.721 ms/step resident; 23.452 ms/step offload.
- Direct-array bridge: 2.674 ms/step resident; 5.043 ms/step offload.
- 40 ps resident check: 2.678 ms/step, normal exit, finite coordinates/energy,
  confinement passed, mean temperature 299.32 K.
- Three-axis force audits with active wall penetration and displaced spring:
  exact agreement for every atom and correction energy.

This is about 6.6x faster than the existing resident callback. It remains a short
experimental qualification, not long-run or DNA/PEG validation. The reference GPU
path itself is not trajectory-identical across identical-seed repeats; endpoint
coordinate equality was therefore not used as the force-equivalence criterion.
Detailed logs/results: `workspace/electrode_native_bridge_validation_v2/README.md`.

New electrode packages now resolve GPU mode `auto` to `on`; explicit `off` remains
available for comparisons. The user-authorized experimental driver uses one worker
and requests resident mode. Minimization retains its existing offload startup path.
Selecting this prototype binary alone does not enable the bridge: its matching
`bridge.tcl` callback is also required. General application integration is still open.

A subsequent [GPU correction prototype](../gpu_correction/README.md) removes the
remaining CPU coordinate/force handling through NAMD's dynamic CUDA client API.
The direct-array bridge remains the independent CPU reference for force audits.
