# ScryWrite physical-HMD desktop mirror

Status: proof of concept implemented 2026-08-21. Live runtime-pause fallback and
pose/frame telemetry are verified; same-direction movement still needs the final
physical dummy/headset observation.

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
the selected eye, source, frame counter (`F`), detected motion counter (`M`), tracking
state, position (`XYZ`), yaw/pitch (`YP`), and room-grid state. A small lower-left
square alternates green/orange every 15 frames as a visible liveness heartbeat.

Both paths preserve the eye aspect ratio with black letterbox/pillarbox bars. They
do not inject input, change the HMD pose, or publish design events.

## How to run the POC

Normal **View in VR** launches from NADOC now request the physical left-eye mirror.
The companion window opens at 960×540 and can be resized. Closing it or pressing
Escape ends the native VR session, matching the previous companion-window behavior.

For a fixture-only launch:

```bash
just vr-hmd-mirror
# Override the eye or scene:
just vr-hmd-mirror EYE=right SCENE=path/to/scene.nadocvr
```

This fixture command defaults `PLACE=on`. On the first valid tracked view it centers
the model 1.30 m down the HMD gaze ray, rotates the fixture's authored presentation
frame with the initial headset orientation, and uses 2× presentation scale. Override
with `PLACE=off` when testing saved world placement. The corresponding native option
is `--place-scene-in-view off|on`; ordinary NADOC browser launches leave it off.

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
   must keep increasing and the lower-left heartbeat must alternate.
3. For a diagnostic launch, confirm multiple colored cage faces are visible even if
   the design is out of frame. Slowly yaw and pitch the dummy/headset. The grid and
   desktop view must move in the same direction, `XYZ`/`YP` and then `M` must change,
   and the view must not switch to the scripted actor or freeze on an old frame.
   `SUBMITTED` is expected while the runtime accepts headset frames;
   `SPECTATOR FALLBACK` is expected when the dummy triggers runtime suppression.
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
The desktop capture proves placement in the submitted application eye. Seeing the
same object and grid through the physical lenses remains the human acceptance step.

Automation cannot yet prove that a particular GPU/runtime accepts the live blit or
that the human-visible desktop and headset images have the expected orientation.
That remains `MV-SCRYWITNESS`. The POC also has no live eye selector, recording,
timestamp overlay, or OpenXR submission ID. The `F`/heartbeat liveness signal is local
to the companion presentation, not proof of compositor acceptance. Before using
mirror pixels as an automated oracle, add submission correlation plus real
color/depth/object-ID capture and a black/invariant-frame detector.
