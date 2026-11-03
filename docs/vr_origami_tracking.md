# Origami tracking for VR diagnostics

Entry: **Debug → VR Tours & Tests → Controls & layout → Origami tracking · pixels, poses and frame identity**. This terminal workflow measures actual molecular features in captured images. It does not change strand colors, geometry, or physical tracking.

Use two separate quantities:

- **Measured position:** a named patch of real molecular detail, located in an original eye image. Each accepted landmark has pixel coordinates, correlation, a distinct competing-peak score, and source/template hashes. Failed or ambiguous matches retain diagnostics without becoming accepted positions.
- **Expected position:** a reference surface point projected using the model transform and eye pose/FOV recorded with that application image. The residual is measured minus expected, in pixels. A stale model render can produce a residual proportional to speed and render age. Comparing against an intended motion trajectory is a different test from comparing against the applied draw transform.

Coordinates are top-left, full-source pixel centers: array element `[y,x]` has coordinate `(x,y)`. Rectangles are half-open `[x0,y0,x1,y1]`. Left/right rectangles are explicit; the other eye cannot become a duplicate-match candidate. Integer translation matching has at least ±0.5 pixel quantization, and is not a calibrated subpixel accuracy guarantee. Translation consensus is optional supporting evidence: perspective, rotation, or deformation can make correct individual landmarks disagree with a single 2D translation.

## Track existing final-output recordings

Use the repository virtual environment with NumPy, SciPy, and Pillow. Run offline decoding under `scripts/validation_guard.sh`, never during a timed VR capture. Put outputs and `TMPDIR` on the mounted Archive filesystem from the first byte. The capture process must already be prepared; these commands never restart SteamVR.

```bash
python -m tools.vr_tracking export --directory CAPTURE_DIRECTORY \
  --request REQUEST_ID --output NEW_EXPORT_DIRECTORY \
  --eyes '{"left":[0,0,1080,1200],"right":[1080,0,2160,1200]}' \
  --indices 20,21,22,23,24,25,26,27,28,29,30,31
```

The example rectangles describe the inspected 2160×1200 Vive recording. They are **not a universal headset layout**. Verify the original output before using them.

Edit the generated `manifest.json`: choose its `reference` from one of the exported frames, add named patches under `landmarks`, and supply a bounded search rectangle for each name. Example fields:

```json
{
  "landmarks": [
    {"id":"left-upper-cap","eye":"left","template_rect":[220,350,316,446]},
    {"id":"left-lower-elbow","eye":"left","template_rect":[300,550,396,646]}
  ],
  "search_rectangles": {
    "left-upper-cap":[100,300,500,550],
    "left-lower-elbow":[180,480,650,750]
  }
}
```

Choose actual distinctive origami detail, with a little surrounding silhouette. Thin repeated sticks alone can alias badly after movement. Keep matching thresholds fixed when comparing trials; preserve failed trials. The default compares original RGB samples. An explicitly configured spatial matching filter, if used, operates only on derived matching data and must remain recorded in results; it never alters the review originals or creates temporal blends.

For fine-stick aliasing, an explicit trial can add
`"config":{"spatial_sigma_px":2,"peak_exclusion_radius_px":6}` to the manifest.
The same Gaussian filter samples original surrounding pixels in the same eye for
both reference and search images. Its sigma/support are retained in results;
correlation thresholds remain 0.8 minimum score and 0.05 distinct-peak gap.
Filtering can improve stability but does not establish calibrated positional accuracy.

```bash
python -m tools.vr_tracking track NEW_EXPORT_DIRECTORY/manifest.json \
  --output NEW_REVIEW_DIRECTORY
```

Open `index.html`. Step frames, select one eye, and toggle measured/expected/residual overlays. Native pixel scale is the default; fit-width is labeled display scaling. `results.json` retains every accepted/rejected match, hashes, configuration, and source provenance. Original PNGs are copied byte-for-byte. Output directories must be new, preserving earlier evidence.

For final SteamVR output, measured positions are supported. Expected positions deliberately remain unavailable: application projection is undistorted, while the final swapchain includes lens warp and potentially a newer reprojection pose. Raw timestamps alone do not establish which application image produced each final present. The optional encoded marker below establishes submitted-image identity. Optical scanout and perceived doubling remain separate evidence.

## Application images: measured versus expected

Use ScryWrite `capture` to retain `evidence.json`, both original PNGs, `<eye>.depth.f32`, and `<eye>.classes.u8`. Capture metadata contains the model normalization and actual submitted eye transforms. It must remain beside the original eye images. Native depth/classes are bottom-up; the tool validates their formats and flips only the indexing for lookup.

Create one manifest per eye, using coordinate space `application_eye_undistorted` and an eye rectangle covering that full image. Every reference/frame item needs `file`, `png_sha256`, `evidence_file`, and `evidence_sha256`. Add an explicit integer `anchor_xy` and `anchor_from_depth:true` to each landmark. The anchor must lie on a design-class pixel with foreground depth. The tool unprojects that visible surface sample into source nanometers, then predicts its location in later captures. Current Flex exported meshes use object ID zero; these are surface landmarks, **not proven strand or nucleotide identities**.

Require the same viewer session, scene/coordinate/visualization sequences, representation, detail state, and View Tools version/flags/sequence. Re-anchor after any geometry or Flex change. Pure model movement may change the presentation matrix without invalidating the source anchor. Projection does not establish visibility; retain rejected matches and inspect occlusion. A reference depth→source→pixel round trip tests conventions only. A held-out moved capture is the independent comparison. Synthetic stale-render fixtures test detection sensitivity and must be labeled synthetic.

## Record coherent poses alongside final output

Launch a diagnostic viewer with `--pose-journal DIRECTORY` in addition to its existing private ScryWrite endpoint and compositor recorder configuration. This is opt-in; configured normal launches on this workstation supply it automatically. The existing **Tools → Record final output** action arms it through the recorder helper. The default short final recording remains useful; five seconds is unnecessary for frame-pair diagnosis.

The journal preallocates at most 8192 small frame records before requesting capture, accepts a maximum 30-second arm lifetime, binds the compositor's acknowledged monotonic capture window, and retains 100 ms of tail. It performs no pixel readbacks or journal-file writes during capture. Serialization occurs after final-output saving. Input poses are not changed. The arm/window commands and clock/pose sampling have overhead; measure that overhead before making timing-sensitive performance claims.

Each row includes application frame ID, predicted OpenXR time, optional `XR_KHR_convert_timespec_time` conversion to `CLOCK_MONOTONIC`, actual eye poses/FOVs/draw matrices, model normalization, runtime controller flags/poses, applied input source/poses, representation/geometry identity, and host frame/query/submission timestamps. Failed conversion is null, not an inferred clock offset. Journal and pixel saving verdicts are separate; a journal failure does not erase recorded pixels.

To project previously validated same-session anchors through the journal:

```bash
python -m tools.vr_tracking project-journal --journal POSE_JOURNAL.jsonl \
  --anchors APPLICATION_REVIEW/results.json --eye left --output NEW_PROJECTIONS.json
```

The reader checks complete counts, overflow, frame ordering, clock metadata,
render validity, eye ownership and unchanged geometry. Its output is expected
application pixels, not a guessed correspondence to distorted final frames.

The inspect-safe ScryWrite operation is `scrywrite_pose_journal`, with the usual session and expected command sequence:

```text
pose_journal arm REQUEST MAX_SECONDS
pose_journal window REQUEST START_MONOTONIC_NS END_MONOTONIC_NS
pose_journal flush REQUEST
pose_journal cancel REQUEST
```

Arm before requesting compositor capture, bind its exact acknowledged interval, flush only after the interval plus tail and final recorder saving, and cancel a failed journal explicitly. Commands never silently retry uncertain delivery. Coordinate ownership with any scripted motion controller because all commands share the viewer sequence.

## Identify the submitted image in each final presentation

Add `--submitted-frame-marker on` to a diagnostic launch that already has
`--pose-journal DIRECTORY` and a private ScryWrite session. The default is off.
Configured normal launches use `--submitted-frame-marker recording`, which
draws markers only while the recording's pose journal is collecting, including
its preparation and tail; idle views remain unmarked.
A 192×192-pixel marker is drawn in each actual acquired eye texture after scene
and menu rendering, before application capture and OpenXR image release. It is
centered at 50% image width and 40% height; inspect this location for occlusion of
scientifically relevant detail before using a new scene. It has no model object
ID and is classified as an overlay in diagnostic captures.

Protocol version 2 uses 24×24 cells at eight application pixels per cell, four
white 3×3 corner fiducials, a black moat, and a 16×16 binary payload. The decoder
uses the green channel for both corners and payload, avoiding cross-channel
geometry from SteamVR chromatic correction. The earlier colored-corner version 1
failed on actual final images; those failed captures remain preserved. The 32-byte, big-endian packet
contains `NF`, version, eye, full 32-bit PID, full 64-bit session-start value,
full 64-bit application frame ID, CRC32-IEEE of the first 24 bytes, and fixed
padding `a5 5a c3 3c`. The journal records configuration and each eye's actual
marker draw receipt, including its packet checksum and application rectangle.
There are no pixel readbacks, fences, or active-capture file writes in this draw.
State queries and a small draw still cost time; compare marker-off/on timings
before claiming negligible overhead.

Export original final frames as above, then add `marker_search_rectangles` to the
manifest: one explicit, bounded full-source rectangle per eye containing the
whole distorted marker. Derive these rectangles by inspecting the new capture;
do not reuse an assumed lens mapping. The decoder locates the four fiducials and
samples the local projective grid in one channel. This local sampling is **not a lens calibration
for the origami**. CRC/session/eye/padding failures and ambiguous candidates remain
unknown; the tool never substitutes a nearest timestamp or interpolated ID.

Calibrate the search rectangle from an original first frame: enclose all four
complete fiducials with a small pixel margin, excluding nearby molecular detail.
Record the rectangle, frame/hash and selection method before evaluating later
frames as held-out data. Preserve the original failures and any later unknowns;
do not expand acceptance thresholds or infer missing identities. The decoder
discards components smaller than its existing minimum fiducial area before
applying the unchanged 64-component bound, then densely remaps eligible labels
to bound allocation. Color, area, shape, geometry, bit-confidence, CRC and
session/eye thresholds are unchanged. A broad region full of molecular detail
can still correctly return unknown; automatic scene-independent localization
is not established.

The normal-launch verification retained the
[original broad-ROI failures and first-frame calibration](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/tight-roi-calibration-before.json).
Its [latest calibrated result](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/postfix-summary.json)
joins all 179 stereo panels in each of two stationary clips. Only menu frame 0
was used to develop the fix and choose rectangles; its remaining 178 frames and
all 179 physical-inspect frames were held out. Both eyes have consecutive IDs,
without repeats or gaps. This verifies recording and identity association, not
the user's motion symptom or optical output.

```bash
python -m tools.vr_tracking identify-frames FINAL_EXPORT/manifest.json \
  --journal POSE_JOURNAL.jsonl --request REQUEST_ID --output NEW_IDENTITIES.json
```

For motion that carries the marker outside a fixed search rectangle, the manifest
can explicitly enable bounded following without changing that command:

```json
{
  "marker_roi_follow": {
    "margin_px": 20,
    "max_search_rectangles": {
      "left": [336, 234, 713, 601],
      "right": [1414, 234, 1790, 599]
    }
  }
}
```

These example coordinates belong only to request `962531370889719`; they are not
a universal Vive mapping. Pin the initial `marker_search_rectangles` and maximum
motion allowance before evaluating a new sequence. Only an exact journal-joined
marker may update the next search rectangle. Unknown results freeze the last
accepted search; capture-index gaps reset it to the original rectangle. Each
maximum remains inside its explicitly declared eye and within the bounded search
allocation. CRC, contrast, bit-confidence and geometry thresholds are unchanged.
The opt-in follow trial used a fixed 80-pixel allowance around frame 0 and a
20-pixel adaptive margin: all 358 eye images joined, with 35 repeated-image pairs
per eye and zero unknowns. The original fixed-ROI result (313 joins, 45 unknowns,
22 proven pairs per eye) remains preserved. This was retrospective evaluation of
one recording, not an independently acquired validation clip. See the
[follow trial evidence](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json).

The report pins original PNG and journal hashes, validates request/presentation
provenance, and joins decoded session/eye/frame/checksum to the exact rendered
journal row. It reports consecutive reuse runs, forward frame-ID gaps, regressions,
and unknowns independently per eye. A valid marker outside the retained journal
is `decoded_unjoined`, not a fabricated pose association. A skipped application ID
is not by itself proof of a missed physical refresh.

A repeated ID on consecutive final presentations directly establishes reuse of
that submitted eye image at this capture boundary. Correlate it with independently
tracked molecular pixels and SteamVR GPU/presentation timing. A marker alone cannot
prove every molecule used the correct model uniform, distinguish two overlapping
molecular copies within one image, establish physical scanout timing, or reproduce
an optical persistence effect. Those are separate tests.

For independently tracked molecular patches from the same captured originals:

```bash
python -m tools.vr_tracking compare-temporal \
  --tracking TRACKING_REVIEW/results.json --identities NEW_IDENTITIES.json \
  --output NEW_TEMPORAL_MOTION.json
```

This joins exact request/capture-index/present identity and RGB hashes. It groups
accepted per-landmark image steps by reused versus advanced submitted image ID.
Unknown IDs, rejected landmarks and missing/nonadjacent frames break comparisons.
A held ID can still move through head reprojection, and an advanced ID can remain
stationary. Distances are molecular image jumps, not optical doubling separation.

## Menu, hover and haptic timing

Normal configured recordings now include bounded `capture_ui_diagnostics`
version 1 in each pose-journal frame. This is measurement only: it changes neither
controller behavior nor menu rendering. Run the offline reader after recording:

```bash
python -m tools.vr_tracking summarize-interactions \
  --journal POSE_JOURNAL.jsonl --identities NEW_IDENTITIES.json \
  --output NEW_INTERACTION_REVIEW
```

`--identities` is optional. When supplied, it must describe this exact journal,
session and request; the reader does not associate frames by nearby timestamps.
The new directory contains `summary.json` and a standalone `index.html`. Old
journals remain usable, with missing interaction telemetry marked unavailable
rather than treated as zero activity.

The diagnostics record per-hand requested/dispatched haptics, OpenXR return
values and host call durations; bounded hover IDs and changes; sidebar texture
updates/cache hits; and per-eye menu draws and backdrop copies. A dispatched
haptic means `xrApplyHapticFeedback` was invoked, not that physical vibration was
observed. Menu-open state and draw counts do not establish on-screen coverage.
Host GL-call time includes blocking/descheduling and is not GPU execution time.
Nested menu/texture/backdrop spans overlap and must not be summed as independent
costs. Positive OpenXR results are retained and are not classified as failures.

Storage is fixed at 1,240 bytes per frame (10,158,080 bytes for the 8,192-frame
journal capacity); at most 16 haptic events and 96 UTF-8 bytes per hover ID are
retained per frame. Overflow and truncation stay explicit, while aggregate haptic
counts include overflow. No diagnostic clocks run while collection is idle;
clock-query counts expose active observation work but do not calibrate its cost.
No GPU queries, pixel readbacks or active-capture file writes are added here.

The October 13 menu-lag recording contains 179 final presentations but only 144
distinct submitted images, with 35 reused-image pairs in each eye. Its longest
recorded input stage was 1.61 ms, versus 20.88 ms in `xrEndFrame`. That locates the
observed host wait; it does not identify GPU work, hover or haptics as its cause.
The later deployment check saved 179 frames with both menus closed and all UI
clock/counter values zero, as expected. Actual GL hover/cache tests and haptic
dispatch spies passed separately. A worn-controller reproduction with the new
telemetry is still required; ISSUE-77 and MV-44 remain open.
The [original motion interaction review](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/interaction-analysis-original/index.html)
and [closed-menu deployment review](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/interaction-analysis-validation/index.html)
retain these different coverage limits.

## Locate rendering cost

For a separate diagnostic launch, set `NADOC_VR_GPU_PASS_TIMING=1`. The default
is off. Four asynchronous OpenGL timestamp queries bracket the ordinary scene
shadow pass and both eye renders in their actual order. `VR_GPU_PASS` trace rows
include the application frame ID, raw timestamps, shadow/left/right/total
intervals, menu state, view-tools version/flags and shadow scope. The live
`gpu_pass_timing` object and shutdown status expose query counts, incomplete
frames, ring saturation and unavailable results. A full ring skips measurement;
the renderer never waits for a timestamp result.

These intervals include GPU queue idle/submission gaps. The eye intervals include
scene, menus, diagnostic marker, application capture, mirror and image release;
they are not isolated shader busy time. They exclude `xrEndFrame`, and the shadow
interval begins after Witness-only rendering. Do not compare unrelated scopes or
silently discard malformed/interleaved trace rows, invalid samples or genuine
`VR_TRACE_DROPPED` records. Preserve the source log and compare a timing-disabled
condition before making overhead claims.

```bash
python -m tools.vr_tracking summarize-gpu-passes VIEWER.log --output NEW_GPU.json
```

Optionally supply both `--start-ns` and `--end-ns`, with
`--boundary-exclusion-ns 300000000` to exclude 300 ms at each end. Membership uses
the host monotonic time at query submission, not GPU execution time or a guessed
OpenVR frame association. The report hashes the log and retains malformed rows,
duplicate frame IDs, query-loss counters and selected gaps alongside statistics.
One unavailable shutdown query makes full-log coverage incomplete even when the
selected central window has consecutive measurements.

## Rollback and remaining validation

No global SteamVR settings or installed runtime files are changed. Launch without `--pose-journal` to disable sampling; keep previously frozen binaries and launch plans for restoration. Never replace an executable/library mapped by a running process. Persistent viewer launch must occur outside `validation_guard.sh`, whose cleanup intentionally stops children.

Physical headset testing still needs the user's monocular symptom marker, head/controller motion, representation comparisons, and an independent high-refresh application condition. Final-output distortion/presentation calibration and optical equivalence are not claimed by these tools. See `manual_validation_debt.md`, MV-44.


## Require model movement in a recorded motion test

Scripted input has a two-second lease. Recorder preparation can outlast it, so
acquiring grip before preparation can produce a stationary recording despite
subsequent controller pose commands. Preserve such attempts as stationary evidence.
After the recorder acknowledges its capture window, refresh the shared command
sequence, release previous input, place the controller at the start, and acquire a
fresh grip through ordinary input. Wait for completed-frame state and require a
valid hand, active grip and scene input ownership.

Require actual model motion, not just controller commands: verify the guarded
endpoint translates the presentation by the requested displacement; measure model
span along the requested direction during the clip; compare applied hand and model
translation, rotation and perpendicular drift. Keep the entire movement and grip
release inside the acknowledged capture window. Reject failed cleanup or timing
checks even when pixels were saved. The retained comparison harness uses the
existing maximum matrix-element error of 2e-5, a 20 μm translation tolerance,
and at least 75% of the commanded
15 cm span. The four unchanged human-motion presets include wrist/position noise,
so they require agreement with the full applied rigid hand transform, measurable
model movement, and rejection of a frozen-model negative. A pure commanded-axis
endpoint threshold is inappropriate for those profiles; the retained failed trial
and reproduction demonstrate this distinction.
Neither a small hand/model residual on a stationary clip nor a new encoded frame
ID proves that a model moved.

## Dense Stick rendering and rollback

The native View Tools renderer now selects two optimizations by default when the
geometry and driver qualify. An opaque fragment program preserves the original
lighting and nine shadow samples for opaque, untextured geometry. Small instanced
meshes (at most 72 base vertices) can group eight logical instances in one hardware
instance. This retains the original batch, instance and triangle order, handles
the exact remainder, and reuses the existing instance buffer. Original molecular
vertices, radii, colors and topology are unchanged. Shadows, lines, sprites and
panels retain their established paths.

`view_tools.opaque_shader` and `view_tools.instance_groups` expose default versus
environment selection, eligibility, optional program/resource availability and
actual draw counters. Unsupported geometry, insufficient capabilities, or failed
optional shader/resource setup fall back to legacy rendering. Grouping adds only
27,648 base-vertex bytes on each of CPU and GPU for the recorded large Stick view;
per-view expansion is bounded to 32 MiB.

For a matched rollback comparison, launch a separate authenticated viewer with
`NADOC_VR_OPAQUE_VIEW_SHADER=0` and `NADOC_VR_GROUPED_VIEW_INSTANCES=0`. Use identical
saved assets and presentation, and verify actual path counters. Setting just the
second flag to zero isolates grouping while retaining opaque shading. Do not
change SteamVR settings or replace the active process without preserving its
source, arguments and placement. The measured 24HB P1 Alpine Aug 7 Flex workload
went from about 13.8 ms / 45 new images per second to about 5.6 ms / 90; these are
workload-specific software results, not a guarantee for every scene or a physical
comfort verdict.

## Ball+Stick indexing and motion verification

`NADOC_VR_INDEXED_VIEW_MESHES` selects exact indexing of eligible exported View
Tools meshes: the default is on, `1` explicitly enables it, and `0` retains their
original unindexed draws. The native path deduplicates complete vertex records
and indexes the original vertex sequence, preserving triangle order, geometry,
normals, colors and the selected shader. Existing grouped meshes with at most 72
base vertices keep their established path. The inspected Ball+Stick sphere has
420 original vertices and 91 byte-distinct vertex records; this is a geometry
count, not a measured performance result.

`NADOC_VR_GROUPED_INDEXED_MESHES` additionally groups eight indexed logical
instances into a hardware instance. It defaults to on; `0` isolates plain
indexing. Each group repeats the byte-exact unique vertex records and offsets the
original index sequence, including the final partial group. The existing grouped
vertex shader reads the original instance matrix/color buffer; normal arithmetic
and fragment shading are unchanged. CPU derived arrays share an 8 MiB per-view
budget with ordinary indexing. Missing shader/sampler capabilities, texture limits
or incomplete optional buffers fall back to plain indexing or original arrays.
The shadow path retains its ungrouped shader/draw behavior.

Use the existing **Origami tracking** entry to discover the following comparison.
Preserve the current document, exported assets, model placement, runtime identity,
viewer binary and launch settings before either separate viewer launch. Keep
representation, Flex data, eye dimensions, menus, shaders, grouping and SteamVR
settings identical. Keep `NADOC_VR_INDEXED_VIEW_MESHES=1` and compare only
`NADOC_VR_GROUPED_INDEXED_MESHES=0` versus `=1`, with
`NADOC_VR_GPU_PASS_TIMING=1` in both conditions. Setting the indexing flag to `0`
separately provides the original-array rollback. Verify the actual selection,
`grouped_active_batches`, resource reasons and grouped draw/instance counters in
`view_tools.instance_groups.indexed_meshes`;
record fallback reasons rather than assuming an environment request took effect.

Before timing, verify the actual browser is still attached to the viewer: check
its current publication/connection state and that repeated desktop renderer-frame
observations stay frozen while native VR renders. A disconnected browser can
resume a large desktop scene and contend for the same GPU. Normal managed launches
must name the actual ELF executable, not a shell wrapper, because the backend
verifies the process executable. Retain and exclude samples taken with an
unexpectedly active desktop renderer; reattachment must happen before, rather
than during, the comparison window.

1. Compare saved quiet and moving windows using `summarize-gpu-passes`, excluding
   the same 300 ms boundaries and preserving query coverage. Compare shadow and
   each eye separately. A GPU interval is not an isolated shader busy-time
   measurement, and host time inside `xrEndFrame` is not GPU execution time.
2. Record the user's coordinated torso/head/controller movement through **Record
   final output**, retaining its journal and frame markers. Keep the complete
   origami visible. Use `identify-frames` with first-image ROI calibration and
   held-out later images; retain failed decodes and exact session/eye/frame joins.
   Compare distinct submitted images, repeated-ID runs, skips and presentation
   accounting. Zero recorder drops does not mean a new application image on every
   presentation.
3. Track the same visible molecular landmarks in original images, excluding the
   marker and menus, then use `compare-temporal`. Inspect consecutive single-eye
   originals around repeated/advanced IDs for held-frame displacement followed by
   a return when the application image advances. Keep existing score/ambiguity
   thresholds, rejected observations and actual timestamps. No image blending or
   interpolation is evidence of a second image.
4. Report geometry preservation, GPU cost, submitted-image cadence and measured
   molecular motion as separate results. A faster draw or 179 saved presentations
   alone does not establish that the visible symptom is resolved. Repeat the
   physical monocular check with the user; software capture does not measure
   headset scanout or persistence.

At the measured 89.53 Hz presentation rate, the native-refresh budget is about
11.17 ms. A runtime-reported prediction period near 22.34 ms describes the next
application frame and can reflect half-rate scheduling; it is not a larger budget
that proves 90 new images per second. OpenXR permits the runtime to adjust frame
timing and specifies that the predicted application period can differ from the
hardware period. Preserve its predicted time for both located poses and submitted
views; do not manufacture a shorter period as a performance fix. See the
[OpenXR frame-loop specification](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#frame-loop)
and [Khronos frame-submission guidance](https://github.com/KhronosGroup/OpenXR-Guide/blob/main/chapters/frame_submission.md).

The [October 15 Ball+Stick motion review](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-ballstick-capture-20261015/index.html)
retains the pre-indexing observation: 90 distinct application images across 179
saved presentations, plus accepted molecular landmarks that shift on a reused
image and return on the next new image. It is evidence of temporal position
splitting, without an obvious second whole-model silhouette in the inspected
single frames. Plain indexing passed exact rendering tests but left the live
Ball+Stick workload near 13 ms and 45 new images per second. It did not resolve
this workload's half-rate behavior.

The [saved-view group comparison](/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/vr-temporal-fix-20261015/mesh-benchmark/run-3-summary.json)
then measured 18 alternating samples per condition: indexed grouping reduced
median stereo mesh time from 16.56 ms for plain indexing to 8.76 ms, with zero
RGBA/depth/object-ID differences in both saved views. The live viewer was also
using the GPU, so these are comparative offline intervals, not application-frame
costs. The experiment excludes canonical shadows, menus, mirror and runtime
submission; it uses a declared synthetic shadow texture. Simplified normal
arithmetic did not provide an isolated benefit and is not in the renderer.
The subsequent ordinary live viewer measured 87.343 Hz mean application cadence
(median interval 11.166 ms; occasional 22 ms intervals) versus the approximately
45 Hz baseline. Three complete 120-result GPU windows had medians 8.497, 8.473
and 8.577 ms, versus the prior approximately 13 ms. See the
[live timing evidence](../.development-artifacts/vr-temporal-fix-20261015/candidate2-performance/summary.json).
This is an improvement with remaining missed refreshes; a fresh motion capture
and physical check are still required. Neither this benchmark nor the earlier
Dense Stick result is a physical symptom verdict. The standalone benchmark and input preparation are documented in
`native/vr_viewer/benchmarks/README.md`.
