# View-volume trigger grabs — 2026-09-27

Either controller highlights a visible volume's centroid within 7.5 cm. A fresh
Trigger press latches its rigid offset; holding follows controller translation
and rotation. While held, the other controller highlights the nearest finite
face within 5 cm. Its Trigger latches that face for normal-axis resizing. The
centroid remains the resize center: box faces change one dimension, hex sides
change the regular radius, and hex ends change length. The minimum half-extent
is 1 mm in tracking space. Grab radii and marker sizes are independent of zoom.

Releasing the second trigger leaves the rigid grab active. Releasing the first
or losing its tracking ends both grabs; a fresh press is needed to reacquire.
Grips still manipulate the scene and rebase trigger anchors, preserving volume
coordinates within the part. Proximity trigger ownership precedes ray-menu and
scene-selection input. Dimensions and the radial menu retain their existing
modal ownership. Hidden outlines have no grab targets; disabled but outlined
volumes remain editable.

The v2 native feed includes exact center, half-extents and orientation alongside
outline vertices. Geometry edits enter the acknowledged document-bound journal
at 10 Hz, with an immediate final write on release. Active/unacknowledged local
poses survive older feeds; remote deletions win. The backend reverses launch
rotation, validates finite positive geometry/unit quaternions and changes only
geometry fields, preserving desktop names, representation and switches. Normal
part-file save/autosave and the shared desktop polling apply to these edits.

Validation:

- Native build and all **43 CTests pass**. New coverage includes all six box and
  eight hex faces, rotation and scene scale, finite-face range rejection,
  minimum size, either primary hand, second-trigger release, tracking loss,
  hidden/disabled volumes, model-grip rebasing, stale-feed protection and final
  journal flush. Marker drawing includes a negative highlight case.
- **62 focused backend tests pass**, including transformed-pose persistence,
  launch-rotation reversal, part-file round trip, metadata preservation, invalid
  geometry rejection, journal replay, document binding and deleted-record safety.
- The production launch route and physical OpenXR runtime pass **eight live
  cases**: both shapes with steady_fast, steady_deliberate, variable_fast and
  variable_deliberate. Each checks centroid highlighting against a cold negative
  capture, face highlighting in both submitted eyes, rigid trigger movement and
  rotation, second-trigger resizing, grip-only scene movement while the centroid
  trigger remains held, release, journal acknowledgement, and agreement of
  saved geometry with the native state.
- Mirror captures were visually inspected. This establishes rendered eye/mirror
  feedback with simulated controller input, not human through-lens comfort.

Observation and test corrections are retained. The first live run placed the
fixture on tracking-space -Z while the physical headset faced elsewhere, so its
capture was blank. The adjusted fixture uses the actual captured eye orientation;
physical head tracking and production hit geometry were unchanged. A later
variable_fast case exposed an incorrect test assumption that a noisy controller
must reach its intended endpoint. The final check compares the volume to the
rigid transform of the *observed* hand pose, with the same motion profile and
path. No grab ranges or motion-profile parameters were relaxed.

[Final results](../../.development-artifacts/vr-view-volumes/trigger-grabs-observed-pose-20260927/result.json)
· [Centroid mirror](../../.development-artifacts/vr-view-volumes/trigger-grabs-observed-pose-20260927/steady_fast-box-centroid/mirror.png)
· [Hex face mirror](../../.development-artifacts/vr-view-volumes/trigger-grabs-observed-pose-20260927/steady_fast-hexagonal-face/mirror.png)

The initial and intermediate attempts remain under `trigger-grabs-20260927` and
`trigger-grabs-tracked-view-20260927` in the same artifact parent. The workflow
stops its owned viewer and removes its isolated backend document on completion.

Reproduce with a healthy runtime and no other active native viewer:

```sh
.venv/bin/python -m tools.vr_workflows.view_volumes_check --validate \
  --output .development-artifacts/vr-view-volumes/trigger-grabs-review
```
