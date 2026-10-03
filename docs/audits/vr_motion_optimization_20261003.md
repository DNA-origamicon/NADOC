# VR continuous-motion optimization — 2026-10-03

The final 24HB Ball & Stick cluster drags reach the workstation's nominal 90 Hz
submission cadence (measured 89.50–89.53 FPS). All four profiles pass edit,
stereo evidence, save/reopen and Undo. Three measured drags have no compositor
repeats or drops; steady-deliberate has one drop and no repeats. This is a
substantial improvement over the prior settled-drag measurements of 77–78 FPS,
not a guarantee that every frame or every VR feature meets its budget.

## Changes retained

1. During changing Move/Rotate previews, omit self-shadows and render ordinary
   cylinder bonds with four rather than eight sides. Atoms, bond endpoints,
   colors, object identities and CPU picking remain intact. Both eyes share a
   decision latched at the shadow pass. Full tessellation and shadows return
   after 180 ms without preview changes, or on the first frame after the preview
   clears (commit/cancel). This is temporary display quality, not molecular
   placement, topology, export or saved-design modification. Half-cylinder and
   box geometry retain their normal tessellation.
2. Publish event snapshots through a bounded FIFO worker using atomic file
   replacement. Preserve every queued snapshot in order, including commit/Undo
   sequences. Serialization stays on the render thread; filesystem operations
   do not. The queue holds up to 256 pending snapshots and applies backpressure
   if storage remains stalled that long. Failures are observable through
   `loading_diagnostics.event_write_failures`; shutdown drains queued work.
3. Render the mirrored eye last, while retaining original projection-view and
   capture indices. This queues both headset eye draws before desktop blit/swap
   can stall the GL thread. The mirror remains the actual selected submitted eye.
4. Add transform/upload/bounds timing and a live `motion_detail_reduced` field.
   The settled tour captures motion and settled stereo quality outside measured
   windows and checks that full detail returns. Remote acquisition now requires
   the existing >15 cm distance during stable feedback, instead of letting a
   near-contact hover stop the approach early. Profiles, seeds, deadlines and
   distance thresholds are unchanged.

`NADOC_VR_MOTION_DETAIL=0` disables both temporary reductions for comparison;
`NADOC_VR_MOTION_MESH=0` retains eight-sided bonds while allowing temporary
shadow removal. Defaults enable both. The isolated preview renderer comparison
explicitly disables motion detail so its full-quality parity contract remains.

## Final four-profile validation

Each run uses the existing full 24HB source copied into a private workspace,
Ball & Stick, 5+ seconds of held-trigger warm-up, 30+ seconds of alternating
translation/rotation, then 5 seconds settling and a 10-second stationary hold.
Captures and persistence operations are outside timing windows. No builds or
tests run concurrently with measured VR work. Physical HMD tracking and the
existing SteamVR/native mirror stack are preserved.

| Profile | Drag FPS | GPU span p95 | Repeated | Dropped | Edit/save/reopen/Undo |
|---|---:|---:|---:|---:|---|
| steady_fast | 89.526 | 6.115 ms | 0 | 0 | Pass |
| steady_deliberate | 89.495 | 5.984 ms | 0 | 1 | Pass |
| variable_fast | 89.527 | 6.071 ms | 0 | 0 | Pass |
| variable_deliberate | 89.527 | 5.912 ms | 0 | 0 | Pass |

Three stationary controls reach about 89.53 FPS without repeats/drops. The
variable-fast stationary control has a separate outlier: 87.93 FPS, four repeats
and eleven drops. Its largest frame is 142 ms, with 133.6 ms inside the grouped
`feeds_view_tools` scope (simulation/share/view-tool polling and input). The view
version is unchanged across the interval. This identifies a separate feed-path
stall, not a repeated representation rebuild; the trace does not isolate the
specific read versus descheduling. Do not claim universal hitch-free behavior.

## Experiment trail

Artifacts retain all attempts under `.development-artifacts/vr-motion-20261003/`:

- `baseline`: added timing only. The drag fails late with an observation timeout.
  The native trace attributes a 3097 ms stall, followed by 1028 ms, to synchronous
  event publication. Its interrupted interval is not a clean completed baseline.
  Before this turn, completed settled baselines were 77.27 and 78.39 FPS; see
  `vr_settled_drag_20261002.md`. Current instrumentation reports active transform
  p95 1.10 ms, upload 0.65 ms and bounds 0.61 ms.
- `shadow-motion`: omit shadows only. 88.996 FPS; GPU span p95 7.494 ms;
  10 repeats / 6 drops. Persistence passes.
- `shadow-events`: add ordered background publication. 89.195 FPS; 4 repeats /
  6 drops. Event-publication maximum during drag is 0.029 ms, versus the baseline's
  seconds-long stalls. Persistence passes.
- `fused`: calculate exact bounds in the transform pass. No clear gain in total
  active preview cost (p95 2.532 vs 2.548 ms; median slightly worse). Reverted.
- `coarse`: add four-sided bonds. 89.395 FPS; GPU p95 6.076 ms; 4 repeats / 0 drops.
  Motion/settled stereo captures confirm temporary reduction and restoration.
- `final`: mirrored-eye-last scheduling plus the retained changes, default-enabled;
  results above. All four acquisition/persistence tours pass.
- `full-detail-control`: same final binary, `NADOC_VR_MOTION_DETAIL=0`. Drag
  86.365 FPS, GPU p95 9.544 ms, 93 repeats / 3 drops; stationary 89.527 FPS with
  zero repeats/drops. Persistence passes. Temporary quality reduction remains
  necessary for the demonstrated near-90-Hz motion result.

Runs are sequential observations on a live workstation, not randomized,
thermally controlled experiments. GPU spans include synchronization effects;
CPU and GPU times overlap and must not be added. Profile reaches use the existing
20 Hz synthetic input, not a measured 90 Hz wearer trace. No through-lens comfort
claim follows from these results. First-grab preparation remains a separate
one-off cost; this work measures sustained motion after warm-up.

## Correctness and review

Native tests cover ordered publication under a deliberately stalled writer,
shutdown drain, complete atomic output, motion timeout/release, coarse indices,
mirrored-eye-last ordering, rigid preview parity and origin handling. A renderer
check verifies shadow-only mode leaves depth unchanged; coarse mode changes
bond depth as expected while retaining CPU picking; both modes restore identical
full-quality pixels at the same settled pose. Commit and Undo restore full quality.

The real 24HB reduced-detail left-eye image was inspected and retains molecular
geometry, selected bounds and controller context. Stereo captures are available
for every final motion and hold. Physical comfort and the acceptability of the
brief lighting/detail transition remain recorded as MV-VR-MOTION-QUALITY in
`manual_validation_debt.md`.

Reusable route: **Debug → VR Tours & Tests → Authoring → Move / Rotate cluster ·
settled drag**. Reproduce via:

```sh
uv run python -m tools.vr_workflows.tool_frame_audit \
  --tools move_cluster --representations ballstick --settled-drag --validate \
  --design workspace/24hb_0xT.nadoc --min-available-gib 5 --output <new-directory>
```

The initial build used Conda's linker and failed on system X11 dependencies;
using the established `/usr/bin:/bin` PATH fixed linking. No runtime replacement
or workstation display changes were made.

Validation: six focused native checks (five CTest targets plus the renderer's
shadow/coarse restoration exercise), an additional full-quality renderer parity
run, and 39 focused Python tests pass. Scoped Ruff and `git diff --check` pass.
`frontend/src/main.js` LOC delta is zero. No broad suite was run.

Cleanup: ten proven-owned empty socket directories removed; no new private
workspaces, bridge credentials or native viewer processes remain. Original
24HB SHA256 is unchanged:
`bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
`cleanup.json`, `provenance.json`, and `summary.json` preserve the final inventory,
source/binary hashes and stage metrics. SteamVR and user applications were left
in place. No commit or push was made.
