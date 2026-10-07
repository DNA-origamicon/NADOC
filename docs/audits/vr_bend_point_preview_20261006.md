# Full-size 24HB Bend point preview

Implemented a bounded GPU point-cloud guide for Bend. It is an approximate
spatial deformation of selected resident geometry; Confirm still uses the
backend's authoritative deformation. See [controls and limits](../vr_bend.md#live-point-cloud-shape-preview).

## Isolated renderer measurement

Source: `workspace/24hb_0xT.nadoc`, 24 helices, 76 strands, 6,720 nucleotides;
SHA-256 `bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
Reused the immutable full-size selective export recorded in
`.development-artifacts/vr-frame-audit-20261001-selective/export.json`.
Hardware: NVIDIA RTX 3080 Ti, driver 580.178.04.

Both eyes render to an explicit 1852 × 2056 offscreen framebuffer. The whole
model is selected; the arc varies continuously between 30° and 90° around the
authored axial direction. Each mode has ten warmup frames and 120 measured
frames. GPU query time covers both eye draws and the original shadow pass for
modes including the detailed model. CPU measures draw submission. The cloud-only
mode includes clears and is a diagnostic, not the production display policy.

| Representation | Preview points / eye | Original GPU p95 (ms) | Original + cloud GPU p95 (ms) | Cloud-only GPU p95 (ms) | Original + cloud CPU p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full | 29,824 | 0.790 | 0.755 | 0.025 | 0.025 |
| Ball & Stick | 24,576 | 7.288 | 7.350 | 0.027 | 0.071 |
| Stick | 16,384 | 6.855 | 6.929 | 0.020 | 0.060 |
| Quick Surface | 8,192 | 3.046 | 2.751 | 0.012 | 0.036 |

The preview itself is inexpensive relative to the **11.111 ms** 90 Hz budget.
All measured original-plus-cloud GPU frames fit that budget in this view;
Ball & Stick was the most expensive (7.458 ms maximum). Sequential mode timing
has clock/scheduling variation; lower values with the cloud do not establish a
speedup. CPU and GPU timings overlap and must not be added.

These are warmed renderer timings with a fixed diagnostic view, no menus and no
tour browser. They do not establish headset delivery, first-use index-upload latency,
commit performance, or arbitrary close-up views. Full-headset tests are separate.

## Optimizations included

- Borrow existing resident point, cylinder and box buffers. No geometry copies or
  position uploads during a bend drag, and no backend preview requests.
- Transform points in the vertex shader from the existing circular arc parameters.
- Cache selected indices across frames and eyes; rebuild only when selection/style
  masks change. Deterministic sampling caps each channel at 8,192 selected
  instances, with cylinder endpoint draws sharing their index buffer.
- Render unlit three-pixel points, without meshes, normals, shadows or new picking
  identities. Preserve the original detailed model and clipping behavior.

The bound is 49,152 point vertices per eye and 128 KiB of retained index buffers.
If a scene still misses 90 Hz, reducing this cloud further is unlikely to help
much: the detailed original geometry, scene/selection changes, browser contention
and commit work remain potential costs. The live audit must identify which one
actually exceeds budget before changing it.

## Validation and retained failures

Native shader tests pass using GPU transform feedback against the independent
existing arc/quaternion calculation: both fixed endpoints, rotated basis,
near-zero angle, bends over 180°, and straight tails outside the planes. Bounded
selection tests exclude hover-only/unselected rows. Native GL pixels prove the
point cloud is visible; moving it offscreen, clearing selection or disabling
preview removes it. The controller integration check verifies the cloud remains
enabled while an endpoint is held. Existing Bend panel/viewer checks and all 12
backend Bend regression tests pass.

The first isolated benchmark used the default framebuffer of a hidden desktop
window. Its captured image revealed a monitor-clamped height. Those timings are
excluded above; the retained benchmark now allocates its own eye-sized FBO.

Live attempts are retained separately: the first failed before launching because
the restricted build PATH omitted Node's `npx`; the second reached the headset
but the old tour timed out waiting for planes while native state had no selection.
The next attempt explicitly selected through the controller, but the persistent
Bend panel intercepted the acquisition rays. The revised tour uses the existing
stereo-framing helper before selection, then chooses **Use selection / Pick
planes** through the production panel. These are observation/setup corrections,
not relaxed motion thresholds or successful preview measurements.

The framed retry successfully selected the cluster and initialized both default
planes, then stopped in an obsolete sidebar-focus check. Bend now assigns the
right touchpad to Back/Next rather than sidebar focus. The corrected probe tests
**Next** to initialize planes and retains the established thumb-motion lateness
budget and all bend/commit/pixel assertions.

## Live preview result and limits

The corrected `steady_fast` Full-representation tour reached both endpoint
previews with **29,824 points per eye** and passed the existing stereo handle
pixel checks plus the new nonempty-cloud check. Visual review of the submitted
left eye confirms the cyan bent cloud beside the original selected model and
the panel. The native pixel test separately distinguishes cloud pixels from
centerline/handle guides with offscreen and empty-selection negatives.

Six measured controller-reach intervals containing the point-cloud pass cover
**422 frames** (414 with an active cloud pass), with
**89.479–89.533 application-submission FPS**. Each interval
had zero submission gaps exceeding 1.5 × 11.111 ms; the compositor reported
**zero repeats and zero drops** in those intervals. Preview CPU submission p95
was **0.010–0.015 ms** per frame (both eyes). Non-runtime-wait wall p95 ranged
**1.90–3.11 ms**. This runtime's approximately 89.5 FPS cadence is nominal 90 Hz;
it is not a measurement of physical panel scanout or wearer comfort.

This establishes feasibility of the live point preview on the full-size model
in the tested view. It does **not** establish consistent 90 Hz through startup,
selection, style changes or backend Confirm. The tour stopped later when the
held left endpoint was lost while acquiring a wheel with the right hand. The
cloud remained visible, but the combined interaction assertion failed. The
complete authoring/commit/Undo workflow is therefore not certified by this run.

The final build stops treating panel-border pointer reservation as scene motion
when processing held bend endpoints. Crossing a panel border with the free hand
should reserve that pointer without cancelling the other hand's bend; actual
world motion and the existing model-matrix guard still end the grab. This narrow
correction did not resolve the steady-fast wheel assertion. It is retained with
the successful complete variable-profile workflows below, not presented as a
fix for every acquisition failure. Renderer/shader code was unchanged between
these live attempts. All four native motion replays passed separately.

## Final physical-runtime matrix

| Profile | Complete edit, save/reopen and Undo | Result |
| --- | --- | --- |
| steady_fast | No | Both point previews passed; held endpoint lost while acquiring a wheel. |
| steady_deliberate | No | Viewer startup/socket readiness exceeded the existing 30-second test deadline; no preview measurement. |
| variable_fast | Yes | Full authoring workflow and point-preview checks passed. |
| variable_deliberate | Yes | Full authoring workflow and point-preview checks passed. |

The two **complete successful** runs contain 38 measured controller-reach
intervals with the cloud active, totaling **4,702 frames** (the cloud pass ran in 4,686; the remaining
16 are the zero-angle start of a reach). Submission cadence
was **89.513–89.565 FPS**, with **zero** gaps over 1.5 × the target budget and
**zero compositor repeats or drops**. Largest interval GPU p95 was **2.808 ms**;
largest interval non-runtime-wait wall p95 was **2.364 ms**. These are Full-style
physical OpenXR measurements with synthetic controller motion and the ordinary
desktop-drawing preference off. They do not establish Ball & Stick live cadence
or a passing four-profile headset gate.

Counts exclude the separately named commit interval to avoid double-counting its
nested reach. They also exclude the final steady-fast attempt, during which
local evidence archival ran concurrently. That attempt's workflow failure is
retained rather than hidden. No archival ran during the two successful runs.
The earlier clean 422-frame result above belongs to the pre-correction build.

`physical-matrix/` retains all four final attempts and `matrix.json`.
`nadoc-bend-final-preview-summary.json` lists the measured preview reaches and
compositor statistics without counting nested commit spans twice.

Evidence: [local artifact directory](../../.development-artifacts/vr-bend-point-preview-20261006/).
`benchmark/` contains lossless images and raw timing logs;
`nadoc-bend-live-preview-summary.json` contains the six intervals and compositor
statistics. `failed-attempts/nadoc-bend-points-live-workflow/` contains the full
live trace and both stereo endpoint captures. `native-profiles/` contains all
four native replays and pixel evidence. Earlier setup failures and the discarded
window-clamped benchmark are retained in `failed-attempts/`.

Representative submitted-eye image: [bent selection in VR](../../.development-artifacts/vr-bend-point-preview-20261006/live-end-1-left.png).
