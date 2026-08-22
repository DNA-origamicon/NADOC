# ScryWrite physical-HMD desktop mirror

Status: proof of concept implemented and physically confirmed 2026-08-21 for the
left submitted eye, same-direction tracked motion, room grid, and framed asymmetric
origami. Pixel-liveness diagnostics are implemented with bounded claims below.

## Room reference grid

For diagnosis, `--reference-grid room` draws a five-meter cage centered on the
OpenXR LOCAL origin. It is independent of the design/manipulator and remains in the
physical-eye pass even when the headset session is not focused or no controllers are
active. Six 0.5 m-spaced face grids surround the origin, so a headset within the cage
has a reference in every viewing direction. Bright face-center crosses and axis
colors encode direction:

- +X red, −X cyan;
- +Y green, −Y magenta;
- +Z blue, −Z yellow.

The guides render over scene depth intentionally. This is a troubleshooting overlay,
not design geometry or a depth/occlusion oracle. `just vr-hmd-mirror` and
`just scrywrite-witness` enable the room grid by default; pass `GRID=off` to remove
it. Normal **View in VR** launches keep it off.

## What the window shows

The GLFW companion window has two deliberately distinct sources:

- `SUBMITTED` copies the selected eye after NADOC has drawn it and immediately
  before its swapchain image is released to OpenXR. This is the same undistorted
  application image submitted for that eye.
- `SPECTATOR FALLBACK` is used when OpenXR returns `shouldRender=false`, commonly
  because a propped-up headset does not satisfy its wear/proximity sensor. NADOC
  continues calling `xrLocateViews` and renders the selected eye's current pose and
  FOV directly into the companion window. There is no eye submission to copy in
  this state, so this is explicitly a rerender and not compositor evidence.

Neither mode is the scripted ScryWrite actor camera, lens-warped compositor output,
a SteamVR Dashboard overlay, or a camera feed through the headset. The title exposes
the selected eye, source, pixel state, tracking state, yaw/pitch (`YP`), frame counter
(`F`), detected motion counter (`M`), and room-grid state. World position remains in
the diagnostic trace rather than competing for the limited desktop title width. A
small lower-left square alternates green/orange every 15 frames as a visible liveness
heartbeat.

Both paths preserve the eye aspect ratio with black letterbox/pillarbox bars. They
do not inject input, change the HMD pose, or publish design events.

## Pixel liveness, render classes, and correlation trace

Every 30 mirror frames, ScryWrite downsamples the eye viewport—not its black bars or
desktop heartbeat—to 64×64 RGBA and evaluates:

- mean luminance and fraction above a small black threshold;
- a color signature and fraction materially changed from the prior sample;
- translation/rotation of the sampled HMD pose; and
- whether the source was `submitted` or `spectator_fallback`.

The same rendered eye pass carries an eight-bit stencil classification that is not
derived from visible color: background `0`, design geometry `1`, reference grid `2`,
and controllers/panels/other overlays `3`. Later visible layers replace earlier tags,
so the sampled classes describe what survives on screen. The stencil is downsampled
with nearest-neighbor sampling to the same 64×64 diagnostic. Four samples are required
before design or grid presence is called meaningful.

The title reports `DESIGN+GRID`, `DESIGN ONLY`, `GRID ONLY`, or `NO TAGS` immediately
after the source. `GRID ONLY` is the explicit failure signal for the false-positive
case where the cage keeps an otherwise missing design frame nonblack. `DESIGN` means
only that design-class fragments occupy samples; it does not identify the expected
origami or prove topology, handedness, depth, readability, or correct placement.

The title places `PX BASELINE`, `PX CHANGING`, `PX STABLE`, `PX BLACK`, or
`PX FROZEN?` after the render class so both cues survive ordinary title-bar truncation.
`CHANGING` claims only that sampled application-eye pixels
materially differ; it does not claim that the design, view, or compositor output is
correct. `STABLE` is healthy ambiguity for an unmoving headset. `FROZEN?`
requires meaningful tracked pose motion with fewer than 0.2% materially changed
sample pixels; the question mark is intentional because symmetry, empty space, or
downsampling can still create a false positive. `BLACK` is independent of pose.

Pass `--mirror-diagnostics <trace.jsonl>` to persist one JSON object per sample with
local frame, wall-clock milliseconds, OpenXR predicted display time, source,
signature, luminance/change statistics, pose deltas, class status, design/grid/overlay
counts and fractions, unknown tag count, synchronous readback CPU time, and the full
view-relative placement contract plus applied state.
`just vr-hmd-mirror` writes
`/tmp/scrywrite_mirror_diagnostics.jsonl` by default. This is application-side frame
correlation, not proof that the compositor scanned out a frame. In 276 samples from
the classified live build, combined color/stencil readback averaged 0.44 ms and
peaked at 1.45 ms. Production capture should use asynchronous pixel-buffer readback
rather than putting even that occasional stall on the render thread.

## How to run the POC

Normal **View in VR** launches from NADOC now request the physical left-eye mirror.
The companion window opens at 960×540 and can be resized. Closing it or pressing
Escape ends the native VR session, matching the previous companion-window behavior.

For a fixture-only launch:

```bash
just scrywrite-frame
# Named orientation or exact right-eye target:
just scrywrite-frame top
just scrywrite-frame front right right
```

The zero-argument command targets its mirrored left eye. After 15 consecutive fully
tracked, non-discontinuous views it centers the model 1.30 m down that eye's gaze ray,
uses the `front` authored frame, and applies 2× presentation scale. Named front/back,
left/right, top/bottom, and isometric orientations avoid quaternion work. Exact
parameters and direct CLI equivalents are in `docs/scrywrite_scene_framing.md`.
`just vr-hmd-mirror` remains available for saved-world-placement diagnostics.

Witness Mode also mirrors the physical observer by default:

```bash
just scrywrite-witness
```

The native CLI accepts `--mirror-eye off|left|right` and
`--reference-grid off|room`. Direct CLI launches default both to `off`; the NADOC
browser launch request defaults to a left-eye mirror with the reference grid off.

## Dummy-headset acceptance check

1. Prop the headset at head height and launch **View in VR** with a visibly asymmetric
   design such as `Chiral_test.nadoc`.
2. Confirm the desktop title says `NADOC HMD LEFT` and the design is upright. `F`
   must keep increasing, the lower-left heartbeat must alternate, and `PX` must not
   report `BLACK`. A framed design with the diagnostic grid must say `DESIGN+GRID`,
   not `GRID ONLY`.
3. For a diagnostic launch, confirm multiple colored cage faces are visible even if
   the design is out of frame. Slowly yaw and pitch the dummy/headset. The grid and
   desktop view must move in the same direction, `XYZ`/`YP` and then `M` must change,
   and the view must not switch to the scripted actor or freeze on an old frame.
   `SUBMITTED` is expected while the runtime accepts headset frames;
   `SPECTATOR FALLBACK` is expected when the dummy triggers runtime suppression.
   After deliberate movement, `PX` should normally report `CHANGING`, not
   `FROZEN?`; this is a liveness observation, not a correctness verdict.
4. Open the controller menu and confirm the same menu appears on the desktop mirror.
5. If running Witness Mode, confirm the physical-eye view includes the actor monitor;
   moving the physical headset changes the outer view while the scripted actor image
   remains governed by its script.
6. Repeat a direct launch with `EYE=right`; parallax should change slightly and the
   title must say `RIGHT EYE`.
7. Resize the window through wide, tall, and square shapes. The image must retain its
   aspect ratio with black bars rather than stretching or cropping.

## Automated coverage and remaining limits

The pure mirror module tests strict eye parsing, stereo view selection, mono/right-eye
rejection, aspect-fit math, invalid dimensions, and source-identifying titles. The VR
viewer compiles with the blit path; a pure grid test verifies the bounded cage, all
six independently colored face markers, and strict dimensions; the backend command
test verifies mirror/grid arguments; and existing ScryWrite/VR regressions cover
surrounding code.

Live composited-window inspection on 2026-08-21 first reproduced an empty clear-color
eye view, then showed the colored room cage after the diagnostic overlay was enabled.
The original apparent freeze was identified by telemetry: SteamVR accepted one frame
and then returned `shouldRender=false`. With the fallback active, the live title
advanced from F1185 to F1950 while reporting `TRACKED`, and the captured window showed
the cage and heartbeat. Slight tracked-pose motion also incremented `M`. This verifies
continuous fallback rendering and live pose acquisition; deliberate same-direction
physical headset motion still requires the user observation above.
The retained capture is
[`docs/generated/scrywrite/hmd_room_grid_live_poc.png`](generated/scrywrite/hmd_room_grid_live_poc.png).
The separately labeled fallback capture is
[`docs/generated/scrywrite/hmd_room_grid_spectator_fallback_poc.png`](generated/scrywrite/hmd_room_grid_spectator_fallback_poc.png).

After disabling SteamVR's **Pause VR when headset is idle**, a clean session remained
`SUBMITTED` and `TRACKED` beyond the previous five-second cutoff. The initial
head-relative placement then put the 3D asymmetric chiral-origami fixture in the
submitted eye image; its retained capture is
[`docs/generated/scrywrite/hmd_chiral_origami_submitted_poc.png`](generated/scrywrite/hmd_chiral_origami_submitted_poc.png).
The user confirmed that the same object and grid were present through the physical
lenses, and previously confirmed same-direction desktop motion. After leveling the
dummy, telemetry reported pitch near −0.6 degrees while remaining `SUBMITTED` and
`TRACKED`. The retained instrumented capture is
[`docs/generated/scrywrite/hmd_level_submitted_pixel_diagnostics_poc.png`](generated/scrywrite/hmd_level_submitted_pixel_diagnostics_poc.png).

The physical observation validates this machine/configuration at that moment; it is
not portable automated proof. Stencil classes now prevent grid-only color from being
mistaken for design presence: a `PLACE=off` live mutation produced 74/74 `GRID ONLY`
samples with zero design samples, while the centered run produced 276/276
`DESIGN+GRID` samples and up to 2.44% design coverage. Temporal noise can still
disguise a useful-content freeze, and the coarse design class can still pass for the
wrong or malformed object. The POC also has no live eye selector, recording,
per-object ID/depth capture, or OpenXR submission ID. Its predicted-display-time
trace and `F`/heartbeat remain local application evidence, not compositor acceptance.
The next gate is exact expected-object identity plus depth/occlusion evidence.
