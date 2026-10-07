# Twist and Move point previews — 2026-10-07

Twist and Move / Rotate now share Bend's cyan GPU point cloud. The original
selection remains visible. Twist distributes signed rotation between its planes;
Move applies the controller's rigid matrix. Selection/style changes refresh bounded
index buffers; dragging changes uniforms. At most 49,152 points are drawn per eye.
Move's weighted detailed geometry is materialized once on successful commit
feedback when an authoritative scene refresh has not already arrived. Cancel,
tracking loss, commit and Undo retain the existing interaction semantics.

These are spatial guides. Twist does not duplicate the backend's bp-based solver,
and boundary primitives in both tools may differ from the final geometry.

## Native validation

The production shader was checked by transform feedback against independent
quaternion/matrix calculations: signed twists through multiple turns, arbitrary
axis orientation, both outside-plane tails, and translation plus rotation.
Visible cyan pixels were asserted for both tools, with absent-selection,
disabled-preview and offscreen negative cases. Full-size captures were inspected.
The existing Bend shader and interaction tests also passed.

Twist input/wheel tests and Move hand ownership/cancellation tests passed.
Move deferred commits (including repeated commits) and Undo were compared with
the established detailed path: zero differing color bytes in those checks;
depth and picking parity also passed.

## Isolated stereo GPU benchmark

Fixture: `workspace/24hb_0xT.nadoc`, SHA-256
`bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
Snapshot: `.development-artifacts/vr-frame-audit-20261001-selective/scene.nadocvr`.
RTX 3080 Ti; explicit 1852×2056 framebuffer for each eye, shadow pass included for
original-scene modes, 10 warmups then 120 measured samples per mode.
The angle/transform changes every frame. No builds or other GPU tests ran during
these measurements. Values are p95 GPU milliseconds for both eyes.

| Tool | Representation | Selected original | Original + cloud | Cloud only | Points/eye |
| --- | --- | ---: | ---: | ---: | ---: |
| Twist | Full | 0.795 | 0.724 | 0.025 | 29,824 |
| Twist | Ball-and-stick | 7.312 | 7.424 | 0.026 | 24,576 |
| Move | Full | 0.797 | 0.807 | 0.025 | 29,824 |
| Move | Ball-and-stick | 7.281 | 7.418 | 0.027 | 24,576 |

The cloud is cheap relative to the 11.11 ms budget at 90 Hz. The differences
between original-only and combined runs include timing/clock variation; the
lower Twist Full number is not evidence of a speedup. These isolated GPU numbers
exclude OpenXR, compositor and browser work and cannot establish headset FPS.

Reproduce a benchmark with:

```sh
native/vr_viewer/build/nadoc-vr-bend-viewer-test --benchmark \
  .development-artifacts/vr-frame-audit-20261001-selective/scene.nadocvr \
  ballstick /tmp/twist-preview twist
```

Use `move` as the last argument for Move / Rotate. The historical Bend test and
`renderBendPoints` calculation-scope name now cover the shared point renderer.

## Live headset validation

Both `steady_fast` full-size workflows passed editing, backend commit, save/reopen
and Undo. Twist's 21 cloud-active reach intervals contained 1,224 frames at
89.368–89.544 application submissions/s, zero gaps over 1.5×11.11 ms, and zero
compositor repeats/drops. Maximum interval GPU p95 was 2.885 ms.

Move's first attempt failed in obsolete test setup (`move:cluster` no longer
exists). The probe now uses the production left selection wheel. Its retry
passed; release-to-ack was 0.431 s, no representation rebuild occurred, and the
committed center differed by 0.001 mm from the expected center.

That retry's short 68-frame preview reach measured 88.22 submissions/s with one
long gap. The associated compositor window reported 4 repeats and 6 drops. A
stereo capture immediately preceded acquisition; records show a brief runtime
period switch to 22.22 ms around that boundary, dominated by `xrEndFrame` rather
than point-preview CPU work. This is an observed hitch, not proof of its cause;
it must not be reported as a clean 90 FPS run.

Four-profile results (Full representation; these are reach intervals in which
the shared point-render calculation scope ran):

| Tool/profile | Complete workflow | Preview frames | Submission FPS range | Compositor repeats/drops |
| --- | --- | ---: | --- | --- |
| Twist steady_fast | Passed | 1,224 | 89.368–89.544 | 0 / 0 |
| Twist steady_deliberate | Undo refused after reopen | 3,104 | 89.506–89.616 | 0 / 0 |
| Twist variable_fast | Passed | 1,587 | 89.504–89.565 | 0 / 0 |
| Twist variable_deliberate | Amount-wheel acquisition missed | 1,590 | 89.515–89.540 | 0 / 0 |
| Move steady_fast, corrected setup | Passed | 68 | 88.221 | 4 / 6 |
| Move steady_deliberate | Passed | 188 | 89.528 | 3 / 0 |
| Move variable_fast, initial | Browser startup check timed out | 0 | — | — |
| Move variable_deliberate | Passed | 189 | 89.535 | 0 / 0 |

All four Twist profiles rendered the cloud; together their measured preview
reaches contain 7,505 cloud-active frames, zero long submission gaps, and zero
compositor repeats/drops. Two complete Twist workflows failed later and are not
reported as passes. The slower run's saved failure state says `UNDO REFUSED`;
its probe eventually timed out waiting for `UNDONE`. The variable-deliberate run
failed `acquired(..., 'twist:amount')` after its rotation-preview capture.
Backend inactive-view-volume warnings also occurred in a successful run, so they
are not established as the cause of either failure.

Move's variable-fast startup failure was the browser rendered-frame counter not
advancing before the desktop-during-VR setting check, before native interaction.
The steady-deliberate Move reach had no long native submission gaps but its
compositor interval included three repeats; polling boundaries have roughly
100 ms uncertainty. Captures and setup are not evidence of sustained drag cost.

## Sustained Move diagnostic

A separate `variable_fast --settled-drag` run passed the full workflow, including
save/reopen and Undo. It retained ordinary noisy reaches and held-trigger editing;
5.55 s of motion warmed the path before a 31.62 s capture-free drag. This is a
separate diagnostic condition, not a replacement for the short-run results above.

| Interval | Frames | Submission FPS | GPU p95 ms | Non-runtime-wait wall p95 ms | Repeats / drops |
| --- | ---: | ---: | ---: | ---: | --- |
| Sustained drag | 2,829 | 89.527 | 2.181 | 1.699 | 0 / 0 |
| Stationary hold, 10.04 s | 887 | 88.429 | 2.212 | 1.514 | 4 / 7 |

The drag had one application timestamp gap above 1.5×11.11 ms despite zero
compositor repeats/drops. The later stationary hold had seven such gaps, a
24.35 ms maximum compositor GPU sample, and a 21.89 ms maximum non-runtime-wait
wall sample. Therefore the point renderer supports nominal 90 Hz during this
full-size drag, but these measurements do not establish hitch-free 90 Hz across
the whole application/session. A stationary cloud does not upload changed point
positions; the hold result needs a separate runtime/whole-application investigation
before attributing those hitches to deformation or Move computation.

Run the diagnostic with:

```sh
PATH="$HOME/.nvm/versions/node/v22.22.2/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
.venv/bin/python -m tools.vr_workflows.tool_frame_audit \
  --tools move_cluster --representations full --design workspace/24hb_0xT.nadoc \
  --validate --profiles variable_fast --settled-drag --output /tmp/move-point-audit
```

All four Move profiles have now completed the edit/save/reopen/Undo workflow,
with the variable-fast success in this diagnostic retry. Twist completed two of
four entire workflows; all four supplied successful live point-preview evidence.
No interaction thresholds, motion profiles or FPS limits were relaxed.

## Evidence

[Artifact bundle](../../.development-artifacts/vr-twist-move-point-preview-20261007/)
contains native tests, raw interval/compositor records, all failed attempts,
benchmark captures, source snapshots, and build/design hashes.

- [Twist submitted left eye](../../.development-artifacts/vr-twist-move-point-preview-20261007/twist-left.png)
- [Move submitted left eye](../../.development-artifacts/vr-twist-move-point-preview-20261007/move-left.png)
- [Twist Full isolated view](../../.development-artifacts/vr-twist-move-point-preview-20261007/benchmark/twist-full-1.png)
- [Move Full isolated view](../../.development-artifacts/vr-twist-move-point-preview-20261007/benchmark/move-full-1.png)

Stereo captures establish rendered visibility and the compositor records describe
presentation performance. They do not establish through-lens comfort or legibility.
All tours used owned temporary sessions and copied designs; the source design was
not modified. The build and code remain in the working tree.
