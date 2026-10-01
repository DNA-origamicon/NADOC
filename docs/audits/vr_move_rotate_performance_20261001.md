# Selected-part VR Move/Rotate performance — 2026-10-01

Follow-up: [implemented optimization and budget results](vr_move_rotate_optimization_20261001.md).
This document records the unchanged baseline before that implementation.

The reported slowdown is reproduced in the production native preview path for
non-surface atomistic representations. The user clarified that this concerns
**Move/Rotate on selected parts**, not the whole-model grip interaction.
A changed preview rebuilds the entire representation synchronously on the XR
thread, even when only one base moves. Both translation and rotation are affected.

## Controlled measurements

Source revision: `6e3c2ab387970537786a4169331712154e7547af`.
Machine: Ryzen 9 9950X, RTX 3080 Ti, NVIDIA 580.178.04. Optimized `-O3` diagnostic
includes the unchanged production `main.cpp` and calls `GlScene::setToolPreview`,
selection highlights, shadow rendering, and two eye-sized draw passes.

Saved September 30 geometry: 24 helices, 76 strands, 137,721 atom points in
Ball & Stick. Full contains 27,288 authored primitives; Stick contains 154,914
bonds; Ball & Stick contains 292,635 atom/bond primitives. The parser additionally
inserts three reference-axis cylinders. VDW uses the same atom source with VDW
radii and hides molecular bonds. Surfaces were excluded as requested.

Times below are **median milliseconds spent inside one preview update**, including
CPU geometry preparation and GL uploads, excluding the subsequent draw. Each
cell uses 40 measured updates after five warmup updates. Highlights stay active
in both stationary-selection and moving-selection cases.

| Representation | Stationary base | Translate base | Rotate base | Translate cluster | Rotate cluster |
| --- | ---: | ---: | ---: | ---: | ---: |
| full | 0.01 | 18.53 | 19.47 | 37.10 | 37.92 |
| stick | 0.81 | 161.12 | 161.91 | 339.19 | 337.43 |
| ballstick | 1.87 | 294.45 | 295.46 | 632.33 | 630.13 |
| vdw | 1.30 | 130.46 | 129.05 | 433.71 | 420.32 |

For the single-base translation cases, median GPU draw times (shadow plus two
eye-sized passes) were Full 0.64 ms, Stick 6.64 ms, Ball & Stick 6.99 ms and VDW
0.59 ms. The corresponding stationary-selection draws were 0.72, 6.01, 5.83 and
0.59 ms. The dramatic movement penalty is in preview preparation/upload, rather
than a comparable increase in GPU drawing time.

The selected base affects only 26 Stick bonds or 48 Ball & Stick primitives
(22 atom points and 26 bonds), including two boundary bonds with independently
owned endpoints. The cluster includes the whole saved part. Update cost thus
remains substantial even for a tiny selection. Full is also affected; this is
not exclusive to atomistic representations, but their larger geometry makes it
much worse.

At 90 Hz the entire frame budget is 11.11 ms. These preview-update costs alone
exceed that budget, before rendering, controller processing, UI, event publishing
or compositor work. They are not measured headset FPS.

## Cause and secondary costs

- `native/vr_viewer/src/main.cpp:9769`: `processMoveInput` applies the changing
  selected-part transform through `setToolPreview`.
- `main.cpp:1588`: `setToolPreview` calls `setStyle` for each changed transform.
  Unchanged previews return early, but only after ownership/alias scans.
- `main.cpp:1734`: preview, committed-edit and selection-highlight state exclude
  the prepared/static GPU cache fast path.
- `main.cpp:1864`: every rebuild recollects ownership weights over the complete
  representation. The following loops recreate all point, cylinder, box and
  highlight instances, perform identity/color/ownership lookups, issue full
  `glBufferData` uploads, and recompute bounds through `main.cpp:2142`.
- Large selection highlights also add draw work. This is secondary to the
  hundreds of milliseconds spent updating atomistic geometry.
- Existing `style_apply upload_ms` is misleading as a pure GPU-upload metric:
  its interval includes weight-map construction, CPU geometry/highlight loops
  and bounds calculation, as well as the GL calls. Do not attribute its entire
  value to transfer bandwidth.

The earlier September 29/30 investigations measured whole-model grips and
competing browser rendering. Those results do not cover this selected-part
rebuild path. The current reproduction needs neither a browser nor SteamVR.

## Evidence, limits and next change

Evidence is retained under `.development-artifacts/vr-move-performance-20261001/`:
`probe.cpp`, `run.py`, build logs, per-representation logs, `results.json`,
`count_scopes.py`, `scopes.json`, `pixel-checks.json`, and rendered review images.
All 32 timing cases completed without GL errors. All 16 moving-versus-stationary
selection image comparisons have changed pixels; `review.png` shows the cluster
cases as enlarged crops. Full frames are retained as lossless PNGs. Inputs remain in
`.development-artifacts/vr-split-20260930/{full,stick,ballstick}.nadocvr`.
Reproduce with the build command in `build-command.txt`, then
`/usr/bin/python3 .development-artifacts/vr-move-performance-20261001/run.py`.

The diagnostic uses a fixed broadside model pose, production shaders and shadows,
and a 1852×2056 hidden GL framebuffer. It draws twice with the same diagnostic
projection, not physical stereo tracking. Blocking timer-query retrieval occurs
only in the diagnostic, after CPU submission, to isolate iterations. Its serial
wall time is not an asynchronous XR-frame measurement. Captures occur outside
measured intervals. Review crops enlarge the model for observation; they do not
change the measured view. Geometry is visibly present in retained renders.

No physical headset session was running. This establishes the production-path
performance defect, not actual headset FPS, comfort, or all-four-profile input
acceptance. No production code, renderer quality, user document or runtime
settings were changed. The first diagnostic link failed because the environment
selected Conda's linker; the retained retry uses the system linker explicitly.

The appropriate fix is to keep unchanged geometry resident, cache owner-to-instance
membership/endpoint weights when selection changes, and apply preview transforms
without rebuilding the style. A GPU transform/weight path suits large selections;
sparse instance updates can suit small selections. Preserve independently owned
boundary-bond endpoints, highlight geometry, picking, shadows, bounds and
Cancel/commit/Undo semantics. Changing lighting or reducing atom detail does not
address this update bottleneck. Extend the existing Debug → VR Tours & Tests →
Tools · Authoring → Move / Rotate tours with this atomistic matrix and frame-time
evidence when implementing the fix.
