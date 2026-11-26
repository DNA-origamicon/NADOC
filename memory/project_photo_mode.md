---
name: photo-mode
description: "Photo mode — GPU path tracing with EM emitters, unified materials, six Art Themes, studio lighting, scientific silhouettes, Advanced grading, and shared photo/compiled export. v1 remains archived."
metadata: 
  node_type: memory
  type: project
  originSessionId: caf07b9d-c547-4a4a-b679-8f8f745bc1f2
---

# Photo mode

## PHOTO-TRACE-STATUS-20261126 — Compact rendering status

Per user request, Appearance no longer shows the expandable subprocess breakdown
or Rendering metrics panel. A single accessible status line directly below the
progress bar combines percentage with current phase, readiness/sample counts,
or actionable errors. The spinner and measured cold/warm progress accounting
remain. Internal diagnostics stay available to benchmark tools; the panel no
longer enables optional noise readback. The metrics-panel descriptions below
record earlier work and do not describe the current UI.

Validation: 65 focused frontend tests and the real Appearance controls/native
OptiX startup, cancellation, warm reuse and export browser flows pass. Main.js
LOC delta 0. Unrelated nanoparticle/history work remains outside the rendering
commit; existing broad-regression debt is unchanged.

## PHOTO-TRACE-PROGRESS-20261126 — Measured staged preview progress

GPU path tracing now has the shared NADOC activity spinner and a yellow progress
bar directly below the toggle. The initially added expandable breakdown was
removed by the compact-status follow-up above. Both
WebGL and OptiX use weighted completed work, not a time estimate. Unknown driver
work is explicitly indeterminate; it never advances from a timer. Warm native
renders exclude reused device/snapshot/environment/upload/decode/geometry work
and retain reuse accounting internally. The quick one-sample image and target image
are accounted separately; only final delivery and denoise/display reach 100%.

Preview snapshots yield between vertex batches, with exact output parity against
the synchronous export snapshot. Upload progress counts acknowledged encoded
bytes. Native geometry reports five substeps per mesh weighted by attribute bytes;
Cycles reports samples; readback reports completed steps and client image receipt
counts actual bytes. Legacy unmeasurable parsing/driver operations remain marked
working. Changing the sample target during a native request waits for that request
before reusing the scene; unfinished preparation is not claimed as cached.

Validation: 58 frontend and 12 backend focused tests, lint, WebGL/EM/export browser
flow, and native startup/cancel/warm/sample-change/export browser flow pass.
Read-only full Plasmonic ball-and-stick: 14,743,332 triangles, 1615×1185, eight
samples, cold completion 169.0 s; 10 partial snapshot and 20 partial native-geometry
observations, monotonic overall progress, successful warm rerender, zero browser
errors. Screenshot and compact evidence: `.development-artifacts/trace-progress-20261126/`.
Source hash unchanged; isolated worker/profile/scratch and test artifacts cleaned;
live 5173 bridge preserved. Main.js LOC delta 0. Full-suite watermark and prior
ISSUE-179 smoke debt unchanged; no final-quality FPS claim.

## PHOTO-NATIVE-UPLOAD-RETRY-20261126 — Confirmed screenshot settings; recover connection timeouts

Reproduced `Failed to fetch` on an OptiX upload as Chrome
`ERR_CONNECTION_TIMED_OUT`, before rendering. The shown settings are supported:
Glossy ball-and-stick, native OptiX preview, 8 samples, denoising, WebGPU export,
exposure 1.15, contrast 1.00 and saturation 1.10. The interactive checkbox applies
only to WebGL; export selection does not control the preview renderer.

Upload pieces now retry transient network failures with bounded backoff (four
attempts maximum). The backend records a SHA256 receipt for the latest committed
piece, verifies identical duplicate bytes after a lost acknowledgement, and rolls
back interrupted appends to their preceding offset. Completed chunks remain for
retry; explicit cancellation/DELETE and lease expiry still release the worker and
scratch. Rendering requests themselves are never automatically replayed.

Validation: 26 frontend and 11 backend tests plus lint pass. Actual Plasmonic,
Windows Chrome / RTX 2080 SUPER, all 14,743,332 triangles, 1615×1185 and all eight
samples completed in 163.0 s cold. The final retained-scene eight-sample request
took 3.96 s including delivery. This run injected one pre-upload connection
failure and one lost post-commit acknowledgement; both recovered. Background
poll connection timeouts also occurred, without a rendering failure. The exact
cause of the underlying Windows/WSL loopback connection intermittency is not
established. Evidence and screenshot: `.development-artifacts/trace-settings-20261126/`.
No claim of final-quality 15 FPS. Part autosaves blocked before load, source hash
unchanged; owned scratch/profile/reports cleaned, live bridge preserved.
Main.js task LOC delta 0; broader regression debt unchanged.


## PHOTO-BALLSTICK-UPLOAD-20261126 — Native preview exceeded browser string/storage limits

- Plasmonic ball-and-stick expands to 14,743,332 traced triangles and roughly
  1 GB of base64 JSON. Eager binary-string packing plus whole-scene
  `JSON.stringify` exceeded browser string capacity. A giant/chained Blob also
  failed in real Chrome with `ERR_BLOB_REFERENCED_BLOB_BROKEN`; small Blob
  transfers still accumulated that storage failure. Final transport uses raw
  byte buffers, not Blob bodies, for large scenes.
- `path_trace_native_upload.js` retains typed-array views, encodes bounded
  base64 fragments, measures exact UTF-8 size before upload, and sends roughly
  8 MiB pieces sequentially. Small control/camera requests retain single-body
  compatibility. The backend validates frame identity, offsets, completeness
  and current RAM/scratch capacity before consuming the assembled temporary
  JSON. Interrupted pieces roll back; cancellation/expiry removes owned upload data. No atoms, bonds or
  geometry detail are dropped; no fixed total scene-size cap was added.
- Verified actual Plasmonic in Windows Chrome / RTX 2080 SUPER, 672×914, two
  diagnostic samples: native completed in 157.0 s (retained-scene next request
  636 ms), WebGL in 105.2 s. Cold preparation remains expensive; these are not
  final-quality FPS measurements. Source autosaves intercepted, original part
  hash unchanged. Evidence: `.development-artifacts/trace-ballstick-20261126/`.
- Validation: 30 frontend and 11 backend tests; native preview cancellation,
  camera/lighting reuse and export handoff; ordinary EM export; two 183,912,195-
  byte exports with changed EM palettes through chunk transport; lint all pass.
  Owned reports, worker scratch and test artifacts cleaned; live bridge kept.
  Main.js task LOC delta 0. Broader regression debt is unchanged.


## Startup and native refinement fixes — November 26, 2026

Stationary `Plasmonic_test.nadoc` (normal full representation, 845,184 triangles)
showed no scene-fingerprint churn. Its first WebGL draw blocked the main thread
for 36.5 s compiling the tracing shader after 4.7 s geometry preparation. The
500 ms status refresh could therefore remain at the earlier waiting label.
`path_trace_compile.js` precompiles the actual camera/material variant using
Three's async compiler, restoring the live render target before awaiting. The
GPU compile still costs ~35 s in a fresh browser profile, but raster/UI polling
continues. Disposal waits for the compiler's material polling to finish.
Preview forwards native stage/sample progress to the status line.

Native previously rendered 1/2/4/8/... samples from scratch and discarded driver
caches each session. It now renders 1 then target (65 samples total for a target
of 64 instead of 127, two frame deliveries instead of seven). Opening metrics
does not add doubling checkpoints to a renderer without a raw-noise probe.
Camera-pinned
lights no longer force a geometry/environment upload; paired light/rotation
updates reuse retained meshes. Environment and molecular display changes still
invalidate that reuse. Camera changes during a native request coalesce behind
that request, hiding obsolete pixels without restarting the worker. These are
rendering-only changes, not authored structures.

Evidence: `.development-artifacts/trace-startup-20261126/`, Windows Chrome,
RTX 2080 SUPER, actual 672×914 trace buffer. WebGL 2 samples arrived at 42.1 s
before / 40.6 s after; the fix removes the long UI freeze, not the cold compiler
cost. Native 64 samples arrived at 18.3 s / 16.2 s on successive fresh sessions;
the final retained-scene 64-sample request took 789 / 763 ms, including delivery
but excluding browser compositing. A follow-up camera-pinned update on the
actual part completed 64 samples in 2.814 s including settling, the quick image
and final target, with `scene_reused:true` (initial enable 19.5 s that run).
These are diagnostic runs, not repeated
quality benchmarks or measurements at the user's exact zoom/atomistic view.
37 frontend / 11 backend tests, native cancellation/metrics/pinned-light/delayed-
frame/export browser regression, WebGL/EM/WebGPU/export regression and lint pass.
Smoke: 26 passed, two skipped, known ISSUE-179 assembly fixture timeout before
its exit assertion. Owned test artifacts removed; main.js LOC delta zero.
Workspace autosave was intercepted before opening the part; its SHA256 stayed
unchanged. No claim of 15 finished images/s or 200 ms quality follows.

## Native hardware preview and completed-image benchmark — November 26, 2026

Appearance → Advanced → **Trace preview: Native OptiX** selects the persistent
Blender/Cycles NVIDIA renderer independently of Trace export. WebGL remains the
default. Both selectors work before enabling tracing and persist in profiles.
Native preview refines after movement stops; it is not the WebGL interactive
15-view/s mode. One native request runs at a time. Changed views hide stale
results; camera-only updates retain the uploaded geometry/materials/environment.
Camera-pinned light/rotation updates now retain native geometry and environment
pixels; changed environment/materials/geometry and EM billboard views rebuild. Clearcoat materials now work with Blender 3.x and 4.x socket names.
No software fallback is silently selected. Unsupported materials report an error.

Preview/export handoff awaits worker disposal, avoiding competing native sessions.
Startup cancellation now consumes the allocated session acknowledgement before
closing it, preventing an orphaned worker when the response arrives after abort.
`path_trace_native_session.js` owns pagehide/HMR release and heartbeat cleanup.
Admission reclaims expired/dead workers; unclaimed startup replies expire after
10 seconds, claimed idle owners after 120 seconds. Active uploads/renders and
live owners in other tabs remain protected. Cancellation before consuming the
startup response is exercised with the real native worker.
Matching completed native preview pixels can use the existing export reuse path;
new dimensions/scenes acquire an export renderer. The native process currently
renders one quick sample then the requested target; it does not resume a Cycles
accumulation. Driver CUDA/OptiX caches survive worker sessions; only frame scratch
is temporary. Native progress reports upload, preparation, samples and readback.
It still writes/reloads EXR, returns float RGBA through the local API, and uploads
pixels to WebGL for shared denoising/compositing. Native dimensions retain the
existing 2048-pixel per-axis limit; exports tile. GPU rendering alone does not
remove this delivery overhead. Native diagnostics expose startup, render/write,
readback and request latency; request latency excludes browser compositing.

`scripts/benchmark_trace_budget.mjs` and `e2e/helpers/trace_budget_fixture.js`
measure zero-accumulation full frames at 1280×720, with three trials/count and
GPU completion after shared denoising and ACES/sRGB presentation. Only quality
readback/scoring is outside timing. A count qualifies for 200 ms only if all
three trials meet it. References are finite raw 256-sample images from the same
backend, not ground truth or a cross-renderer physical-equivalence test. The
independent traced-geometry visibility mask reports foreground error separately.

Initial RTX 2080 SUPER bare-reflector evidence: WebGL 2 samples median **106.5 ms**
(max 114.3), SSIM **0.5894**, foreground RGB RMSE **0.1626** on 0–1 display RGB.
Four samples miss at 216.3 ms median. Native OptiX has **no** qualifying count:
one sample takes 1249.8 ms median; 32 samples take 1908.0 ms, SSIM 0.9417,
foreground RMSE 0.0185 against its own reference. Cold ready times are 39.2 s
WebGL / 35.7 s native. Neither result establishes adequately sampled images in
200 ms, much less 15 finished images/s. Evidence lives under
`.development-artifacts/trace-budget-20261126/`. Shared desktop GPU load is not
reserved or controlled. Plasmonic_test default full representation has 845,184
traced triangles but occupies only 5.87% of the saved overview. WebGL 4 samples
qualify at median 116.4 / max 117.6 ms, whole-image SSIM 0.9800 but foreground
RMSE 0.1338. Native qualifies at no tested count (one sample 752.3 ms median;
32 samples 841.9 ms, foreground RMSE 0.0576). This is not an atomistic close-up.
The first full-document benchmark unexpectedly triggered frontend workspace
autosave despite session-cache isolation. Current molecular content and feature
log exactly match the November 24 immutable main revision; embedded snapshot
also decodes identically. The harness now intercepts workspace save requests,
and the repeated read-only app inspection blocked one save and preserved the
file SHA256. No molecular edit was authored or published. Full-model results and validation are recorded alongside
that evidence; silhouettes remain a separate deferred review.

## Corrected performance goal — November 25, 2026

The user clarified that **15 FPS means 15 finished, adequately sampled images
per second**, not 15 new low-sample camera views. The existing ~15 traced-FPS
benchmarks measure roughly one new sample per moving view and **do not meet
that goal**. Keep completed-image latency/quality distinct from display FPS,
sample throughput and interactive view updates in future reporting. The user
deferred further silhouette tuning to a separate session. The current 200 ms quality benchmark is described above; empty-space sampling
optimization remains future work.

## Spatial denoising — November 25, 2026

Advanced → **Denoise path tracing** defaults on for live preview and WebGL,
WebGPU and OptiX image/video exports. Raw comparison is immediate and does not
reset accumulated samples or rebuild the BVH. Both denoise and interactive
settings restore through Appearance profiles. Diagnostic noise probes and raw
preview reuse remain unfiltered; export applies the filter exactly once before
Figure/Output/grading and before annotations/insets. Export cache keys include
the chosen denoise state, and progress explicitly names denoising.

`trace_denoise.js` owns two GPU edge-stopping à-trous passes (5×5 kernel,
strides 1 and 2). Color, log-luminance and alpha discontinuities limit smoothing.
Both passes now use the **original raw image** as their edge guide, preventing
the second pass from treating already-blurred contours as smooth regions.
The final pass restores coherent narrow detail using tangential support and
normal contrast in the raw 3×3 neighbourhood, including rasterized curved joins.
Isolated speckles lack that support and remain filtered. This bounded blend
does not sharpen beyond the raw/filtered values or add a render target; six-pixel
export halos still cover the complete filter footprint. Explicit FigurePass
silhouettes already run after denoising in both preview and export.
Weights use compressed color/log brightness, but averaged RGB stays linear HDR;
alpha is copied exactly. The log-brightness guard is essential: compressed color
alone visibly softened bright reflections and increased HDR reference error.
The filter never feeds back into ray accumulation. This is a spatial beauty
filter, **not** geometry-guided reconstruction, temporal reuse, OIDN or NVIDIA's
native AI denoiser. Low-sample highlights can remain grainy and fine reflection
features can soften. Raw comparison remains the scientific review reference.

Filtered targets are retained/cached until the raw sample revision changes;
resizing or scene/camera reset invalidates them. Three float RGBA targets cost
about 42 MiB at 1280×720. Errors/context loss report a tracing fallback instead
of breaking the render loop. Exports use a six-pixel real-neighbour halo around
each core tile (clipped at the full image edge), then crop after filtering. This
avoids artificial tile-edge clamping without adding tiles to a normal 1024²
export. The same compositor filters all export backends, including reused raw
preview samples; native OptiX's internal denoiser remains disabled.

Initial filter benchmark, native RTX 2080 SUPER, two bare reflectors, 1280×720: at 32 samples versus a
finite 128-sample reference, linear HDR RMSE **0.3221 → 0.3071** (4.66% lower),
SSIM **0.7742 → 0.8033**. Motion remains **15.0 traced FPS**, final adaptive
trace size **1259×708**. Shared GPU load changed between runs (even sampler-only
timings varied), so these runs do not isolate the filter's incremental cost.
This is not full-Plasmonic performance or a ground-truth radiance comparison.
The constant glossy-plane fixture reduces 16-sample RMSE versus 128 samples by
62.3%; a synthetic noisy-color fixture reduces it by 82%. One-pixel color detail
and alpha are preserved in that fixture, tiled/full-image filtering agrees
exactly, and a 30:3 HDR radiance edge has less than 3e-8 absolute error.
Evidence: `.development-artifacts/trace-denoise-20261125/summary.json`.

**Contour-preservation follow-up:** the original weak one-pixel contour repro
retained only 20.5% contrast. Raw guides plus local coherent-detail restoration
retain 99.2% in the expanded dark/bright, one/two-pixel and curved-contour fixture;
an isolated dark speckle retains only 4.9%. Alpha and tiled/full-image pixels
still agree exactly. Noise reduction is deliberately less aggressive: glossy
plane RMSE ratio is 0.407 (59.3% reduction), synthetic color-noise ratio 0.432.
Native 32-sample reflector RMSE is 0.3100 versus raw 0.3221 (previous filter
0.3071), while SSIM improves to 0.8149 (previous filter 0.8033, raw 0.7742).
The follow-up reaches 15.12 traced FPS at full 1280×720 on the RTX 2080 SUPER;
shared-load differences prevent attributing throughput changes to this filter.
Reviewed raw/filtered captures: broad grain decreases, residual speckles and
bright-highlight grain remain. This does not validate the full Plasmonic scene.
Evidence: `.development-artifacts/trace-denoise-20261125/contour-summary.json`.

The method follows the spatial edge-stopping idea in
[Dammertz et al., HPG 2010](https://diglib.eg.org/server/api/core/bitstreams/577ad3dc-c7f5-467b-8dce-30e7b5a1f645/content),
but does not implement that paper's geometry guides or claim its quality.

## Sampling throughput — November 25, 2026

`path_trace_schedule.js` now uses GPU fences for readiness independently of
asynchronous timestamp availability. Up to four ended queries collect timing in
parallel with later batches; delayed results never stall completed GPU work.
There is still only one fenced batch in flight, with a 12 ms target and at most
16 tile steps. Unsupported/disjoint timers fall back to two tiles. Query/fence
cleanup covers errors and disposal. The budget is a target, not a hard per-draw
execution bound; workload changes can make individual batches exceed it.

The worker now explicitly uses SAH (surface-area heuristic) splitting with four
triangles per leaf. This costs more preparation for dense scenes but reduces
repeated ray traversal; retained BVHs and refits amortize preparation. A finer
one-triangle tree was measured and rejected as the default because it offered
little extra throughput while adding build cost and tree storage. No geometry,
resolution, sampler, sample count, bounce depth or denoising setting is reduced.
Rendering metrics show the batch budget and tree strategy. A completion noticed
between the first frame poll and a camera reset is credited exactly once.

Native RTX 2080 SUPER / Windows Chrome / 1280×720, same bare-reflector scene:
warm 32-sample preview **4.437 → 2.112 s** (2.10× throughput); shared offline
sampling loop **1.737 → 1.355 s** (1.28×). Progressive 1→128 samples **16.543 →
8.572 s**, excluding initial preparation/compilation. Motion remains about 15
traced FPS at native resolution. RMSE/NRMSE/PSNR/SSIM agree to floating-point
roundoff; no nonfinite pixels. The 3.03-million-triangle scene now takes 3.788 s
for warm 32-sample preview and 2.366 s offline. Its preparation is 12.4 s versus
4.5 s with the old CENTER/four-triangle tree; full Plasmonic remains MV-EM-TRACE.
These are native workstation benchmarks, not guarantees for arbitrary scenes or
end-to-end PNG/video export speed.

The benchmark now separates warm preview and offline sample throughput from
shader compilation, probe readback and PNG encoding. `NADOC_BENCH_BVH` can supply
JSON MeshBVH options for controlled tree comparisons (forward through WSLENV
when launching Windows Node from WSL). Evidence: `.development-artifacts/trace-throughput-20261125/`.

## Measured interactive tracing — November 25, 2026

Appearance → Art & materials → Rendering metrics distinguishes display FPS from
GPU-fence-completed traced frames. It reports p95 frame/CPU latency, GPU batch
(not whole-frame) time, preparation time, first sample, samples/s, primary camera
paths/s, actual trace dimensions, triangle count and accumulation resets. Opening
metrics enables a 32×32 exact-pixel probe at doubling sample counts. The difference
between equal independent sample halves estimates normalized RGB standard error;
this is neither a bias detector nor a reference-image accuracy measure. Readback
cost is shown, and motion does not perform noise probes.

Advanced → Interactive tracing targets 15 fresh views/s during camera movement.
For unchanged geometry/materials, preview retains the BVH, geometry, materials and
environment; only camera, physical lights and environment rotation refresh. GPU
completion latency adapts motion resolution (initial 65%, bounded 25–100%). Still
views return to native drawing-buffer resolution after 200 ms. Geometry changes
and camera-dependent EM point radii retain the raster/rebuild path. Partial/moving
frames cannot satisfy completed-preview export reuse. No temporal reprojection,
denoising, geometry simplification or bounce reduction is implemented here.

Opaque renders avoid the old tracer's separate alpha blend targets. Transparent
output selects the actual latest ping-pong target (the dependency's fixed getter
lags on even samples). Repeated readiness polls now retain measured GPU batch
size; only devices without timer queries use the conservative fallback. The GPU
fence and bounded scheduling remain active for sharing with other workloads.

`scripts/benchmark_trace.mjs URL WIDTH HEIGHT [INSTANCES] [SAMPLES]` runs the real
preview in its own Chrome context. Native Windows Node uses the workstation's
ANGLE/D3D adapter; software-renderer results are rejected. The primary fixture
uses two bare reflective spheres, studio illumination and a rough colored plane,
no EM or authored molecular structure. Optional generic sphere instances stress
BVH traversal. Reference RMSE/NRMSE, fixed-peak linear-HDR PSNR and 8×8-window
luminance SSIM are recorded against a finite-sample reference, not ground truth.

RTX 2080 SUPER / Windows Chrome / 1280×720: old moving preview displayed at 60 FPS
but completed zero traced views. New preview completes 15.0 traced views/s at
native 1280×720 during motion, retains one scene build, and refines on stopping.
An initial conservative run used 832×468; the final controller recovers full
resolution when measured completion latency leaves room within the 15 Hz budget.
Stationary refinement from 1→128 samples took 19.9 s before and 16.5 s after,
excluding cold shader startup. The new 128-sample sparse noise estimate was 10.6%
on this glossy HDR scene. These are individual workload-dependent measurements;
full Plasmonic atomistic/trajectory performance remains separate validation.
The optional 18,000-sphere stress scene (3,029,954 triangles, still no EM) also
sustained 15.0 traced FPS, ending at 957×539 and restoring native resolution on
stopping; scene preparation took 5.7 s. Both tests submit one fresh sample/view;
this does not establish 15 FPS for converged multi-sample exports.
Raw JSON is in `.development-artifacts/trace-fps-20261125/` (baseline/native-motion).
No live user browser, design or oxDNA job was changed by the benchmark.

## Persistent live-preview speckles — November 25, 2026

WebGL tracing now explicitly selects the library's PCG random sampler (`RANDOM_TYPE=0`).
The bundled 0.0.20 stratified sampler allocates a depth-by-dimension texture but
indexes dimension-by-depth. Our five ordinary/five transmissive bounces produce
width 15; the diffuse/specular selection calls `rand(15)`, outside that width.
Its result therefore stays at the per-pixel blue-noise offset across samples,
leaving biased speckles despite a completed sample counter. PCG seeds from both
pixel and sample index, avoiding that texture lookup and the dependency's noted
Sobol/macOS compiler issue. This affects live preview and WebGL exports, not the
independent WebGPU or OptiX integrators. No denoising, geometry filtering or higher
sample/bounce budget is introduced. `photo_trace_convergence.spec.js` measures
spatial noise on a uniformly illuminated glossy plane through the real preview.

## Geometry loading and live tracing — November 25, 2026

Live tracing now waits on `geometry_loads.js`, not just a stable scene fingerprint
for 200 ms. Representation changes retain ownership through native mesh loading,
simulation-coordinate waits and the final refresh. Native atom/surface rebuilds,
selected-region atoms, volume layers and both assembly renderers also track their
actual asynchronous work. Superseded owners cannot clear newer waits; removal,
failure and cancellation release ownership. Shared assembly rebuild promises keep
their coalesced identity.

While loading, preview cancels obsolete tracing work, releases its GPU resources,
uses raster rendering and reports “Waiting for geometry to finish loading…”. A
load revision rejects late tracer results even if loading finishes between frames.
The enabled toggle persists. After completion, Appearance synchronizes materials,
lighting bounds and the final fingerprint before rebuilding/accumulating; this
avoids the periodic material refresh interrupting a newly restarted trace.
No molecular coordinates, representation caches or saved documents are changed.

## WebGPU export tile orientation — November 25, 2026

The float-readback pass now uses the tracer's bottom-origin UV convention.
`RenderToScreenNodeMaterial` expects bottom-origin UVs and flips top-down storage
rows itself; Three's `QuadMesh` supplies top-origin UVs. Combining them inverted
each tile before stitching, wrapping center content to the outer image edges.
An owned clone of the native WebGPU quad's UVs is normalized; shared geometry
and the editor's separate Three.js dependency are untouched.
The WebGPU → WebGL `DataTexture.flipY` conversion remains necessary and unchanged.
`photo_webgpu_tiles.spec.js` checks spatial marker positions and seam continuity
through Appearance's PNG API at one tile and 2560×1271 (six tiles, padded rows
and clipped edge tiles). No molecular structures or EM calculations change.

## Tracing output reuse and progress — November 25, 2026

Advanced samples/backend stay editable with tracing disabled. Preview export
leases pause accumulation; a completed exact-size/camera/scene WebGL view can
supply linear float pixels to the export compositor. Other cases release unused
preview GPU resources before creating the export tracer. Partial previews and
cross-backend/resolution reuse are deliberately rejected.

`path_trace_output.js` keys a one-image cache of the last completed export before
annotations/insets; these overlays are freshly composited on reuse. Content
keys include visible buffers/materials, transforms, lights/targets, camera,
settings, texture transforms, impostor radii/compiler identity, native dimensions,
and EM point screen scale. No molecular authoring
or EM recalculation is introduced. The cache is cleared on tracing stop.

`photo_image_export.js` owns the token-scoped cancellable image popup. Sessions
report EM/inset preparation, BVH progress, actual tile samples, composition and
encoding. Unknown totals remain indeterminate; video capture consumes subframe
trace progress. OptiX status uses an operation ID to avoid stale prior-frame
counts, parser-measured Cycles samples, one polling request at a time, and cleanup
on completion/cancel. Validation results are recorded in the fix log.

## Hardware/runtime scene capacity — November 25, 2026

The user reproduced the previously unlocalized export failure: snapshot's fixed
three-million-triangle check rejected OptiX and atomistic preview before GPU
allocation. That policy cutoff and the native worker's duplicate are removed.
WebGL checks packed textures and actual BVH dimensions against the device limit;
WebGPU requests adapter capacities instead of smaller default buffer limits,
checks actual packed storage, and reports validation/OOM/device-loss errors.
No free-VRAM value is guessed. 32-bit indexing and backend API limits remain.

Native upload no longer has the fixed 128 MiB ceiling. It queries current OS RAM,
cgroup ancestor headroom and scratch space, streams into owned scratch, and sends
small frame headers to avoid parsing/re-encoding geometry in the API process.
Older clients remain accepted through the JSON fallback. Concurrent frames are
rejected; partial-upload disconnect closes the worker and removes scratch.
Tile/sample limits remain controls on individual requests, not scene-size limits.

Validation: 24 frontend + nine backend tests; WebGL/WebGPU success flow; native
RTX 2080 SUPER exported two EM states with 18,000 sphere instances (3,024,328
triangles including surface/emitters), each upload 183,912,051 bytes (175.4 MiB).
64²/four samples: first 63.579 s, retained frame 27.566 s including scene transfer.
No full Plasmonic/maximum-capacity benchmark claim. Production build/lint pass;
owned native/build/browser output removed. Main.js task delta zero.
Isolated smoke: 28 passed; existing assembly setup timeout at scene_harness.js:434.
Owned smoke root removed. See PHOTO-TRACE-CAPACITY and MV-EM-TRACE for remaining
full-scene review.


## Native-resolution preview and export diagnostics — November 25, 2026

Preview now uses full drawing-buffer pixels, including DPR. The old 1024-pixel
cap blurred enlarged fine detail regardless of the sample target. Tiles remain
approximately 256 pixels per edge; higher pixel counts cost more tracing work.
A hardware target-size failure keeps raster output and reports the limit.
Export errors identify backend and pipeline step, retain the original cause,
and distinguish missing renderer modules, EM preparation and native transport.
OptiX uploads use current server RAM/scratch capacity instead of the former
128 MiB ceiling (see hardware-capacity update above); there is no silent fallback.
The user's original “Failed to fetch” was not reproduced: WebGL/WebGPU/OptiX
passed generic 512-instance + EM checks, not a full Plasmonic export at 512 samples.
Do not infer a queue fault or claim that original root cause was established.
31 focused tests, native-resolution browser check, all three backend exports and
four Appearance failure-message flows pass; lint passes. Main.js task delta zero.
Final isolated smoke: 28 passed; existing assembly setup timeout at
scene_harness.js:434. Owned browser/native/smoke output verified removed.
See PHOTO-TRACE-RESOLUTION / PHOTO-TRACE-FETCH and MV-EM-TRACE.


## Advanced trace controls — November 25, 2026

Trace sample drafts survive the panel's 500 ms status refresh. Input only commits
on blur/Enter; button and keyboard arrows change the draft to the next/previous
power of two within 1–512. Typed non-power-of-two integers remain valid. Empty
input restores the previous value. Advanced has hover explanations instead of
paragraphs and 96 px label columns; short backend names fit the 280 px sidebar.
The export tooltip explicitly distinguishes WebGL live preview from experimental
WebGPU/OptiX exports. No rendering/backend behavior changed in this UI fix.
Validation: 59 focused UI tests, real 280 px Appearance-panel flow and lint pass.
Smoke: 28 passed; existing assembly setup timeout at scene_harness.js:434.
Owned reports/smoke scratch removed. Main.js task delta zero.

## Experimental export backends — November 25, 2026

Advanced persists `pathTraceExportBackend`: WebGL (default), WebGPU, OptiX.
Preview remains WebGL. WebGPU's isolated pinned Three 0.187/tracer 0.0.28 tree
installs via frontend postinstall; do not mix its objects with editor Three 0.172.
JSON scene transfer + linear float readback preserve the shared compositor.
It still rebuilds BVHs for each frame. OptiX uses a persistent optional
Blender/Cycles worker and reused meshes; one export, two CPU support threads,
owned scratch and exact-process cancellation/idle/shutdown cleanup. All EM points
survive both bridges. Native export rejects textures/layered materials instead
of silently approximating them. Experimental lighting is not parity-certified.
This workstation uses its existing Windows Blender 3.3 on RTX 2080 SUPER because
Linux/WSL OptiX was unavailable; local runtime config is outside the repository.
See `docs/em_analysis.md` for setup/limits and MV-EM-TRACE for full Run1 work.
Validation: 132 frontend + five backend tests, four browser workflows, lint/build
pass. Smoke 28 passed, existing assembly setup timeout at scene_harness.js:434.
All owned test/build/native scratch cleaned. Main.js task delta zero.
Compact timing evidence: `.development-artifacts/em-render-backends-20261125/summary.json`.

## GPU path tracing — November 25, 2026

Art & materials has a persisted GPU path-tracing toggle; Advanced sets 1–512
samples, default 64. Art Themes preserve this independent renderer choice.
The installed `three-gpu-pathtracer` 0.0.20 is integrated through separate
`path_trace_*` modules, not the archived v1 controller. Snapshot projection bakes
visible ordinary/shared instances and recognized sphere impostors, preserving
world poses, colors and alpha. All visible EM points become colored emissive
20-face spheres, including crossfade clouds; raster EM lights are excluded.
No molecular authoring/state changes. Emission is illustrative, not radiometric.

Stationary preview accumulates at drawing-buffer resolution, including DPR,
with at least 4×4 tiles and approximately 256 pixels maximum per tile edge.
The former 1024-pixel cap was removed because it blurred enlarged previews;
sample count reduces noise, not that resolution loss. GPU fences
and timer queries bound/adapt batches toward 4 ms (two-tile fallback). Changes
invalidate old results and temporarily use raster preview. Stable connectivity
reuses the BVH, refitting positions and periodically rebuilding after 32 refits;
changed topology rebuilds. Pending obsolete builds are aborted. Renderer, atlas
and unchanged environment resources persist across export frames.
Exports use isolated camera/context/tiled accumulation and explicitly await EM
readiness. The shared photo/video canvas API now accepts an asynchronous frame.
PNG, GIF/WebM and compiled presentations respect the toggle and sample target.
Shadow-catching floor/guides are omitted; unsupported shaders/clipping or the
actual backend texture/buffer/index limits produce visible fallback/error, never
point thinning. The former three-million-triangle cutoff has been removed.
Toggle-off/deactivation abort preview work and dispose its resources; exports
observe cancellation between tiles and dispose their isolated renderer. Vite prebundles the
lazy dependency to prevent an editor reload on first activation.
See `docs/em_analysis.md` for user behavior and limitations. Large Run1 hardware
quality/performance remains MV-EM-TRACE; automated browser checks use software GL.
Validation: 200 focused checks, three browser workflows, lint and production
build pass. Browser checks exercise traced EM preview, changed-field PNG and
asynchronous video-frame capture, toggle-off, and existing raster exports.
Browser artifacts cleaned. Main.js task delta: zero.
Isolated smoke: 28 passed, one existing assembly-fixture timeout at
`scene_harness.js:434`; owned workspace/cache/report root cleaned.

## EM exports — November 25, 2026

Appearance PNG and frame-session capture now await scene-owned EM preparation.
Video's offline render clock explicitly settles saved/smooth fields before drawing;
unready or mismatched EM fails visibly. EM point sizes scale with full export
height (including DPR) across tiles and restore in finally. Eight optional,
non-shadowing illustrative lights per field survive photo activation. Glow alone
is the default and adds no active lights. Historical no-point-light statements
below predate this feature. Scientific values and molecular materials/topology
are unchanged. Validation: 170 focused tests, optical pixel/decoded-GIF export
and the Plasmonic Appearance PNG workflow pass. GIF refreshes visible EM palettes
per frame. Smoke: 26 passed, two skipped, existing assembly-fixture timeout at
scene_harness.js:434. Artifacts cleaned. Main.js task delta: zero.

## November 16, 2026 — unified art controls and export finishing

The first appearance card now has one representation-aware Material selector and
six complete Art Themes: Bright studio, Electric, Polished metal, Soft studio,
Scientific light and Scientific dark. Common finishes map across all four material
families; glass/wax/gummy/skin are enabled only for surface-only views. Dedicated
materials/impostors retain their rendering contracts and the panel reports exclusions.
Legacy per-representation profiles remain readable as Custom/mixed.

Advanced is initially collapsed and contains exposure, contrast and saturation.
The shared grade is used in preview and tiled still/video export; alpha and
annotation colors are preserved. Themes reset appearance while preserving molecular
colors and output dimensions. Manual edits show Custom; profiles persist the settings.
Modules: `photo_renderer/art_themes.js`, `color_grade.js`, `material_availability.js`,
`ui/photo_art_controls.js`. The studio environment and PBR material choices are live;
the old statements below about their removal describe the July rebuild only.

Compiled presentations now use the active photo frame session (including text and
endpoints), with cleanup on success/failure. Shared WebM encoding scales bitrate
with resolution and frame rate (8–120 Mbps), rather than using 8 Mbps at every size.
No topology or molecular positions are changed by these controls.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

> **REPLACED 2026-07-29.** What shipped as "Exp. Photomode" IS photo mode now.
> The old one (`photo_renderer.js` + `photo_mode.js` + `photo_panel.js` +
> `photo_figure_panel.js` + floor/post_processing/style_presets/inscatter) moved
> **verbatim** to `frontend/archive/photo_mode_v1/` — read its README before
> reviving anything. There is ONE photo tab. The v1 history — HDRI, bloom, path
> tracer, floor, mist, style presets, profiles, the export-rep upgrade — moved to
> [project_photo_mode_archive.md](project_photo_mode_archive.md); mine it only for
> a specific past decision.

**2026-09-11 — sidebar stack revision:** Rail clicks append full-height,
independently resizable columns, including shared-state copies. Source controllers
and DOM listeners are shared; other views mirror changed nodes/properties and
retain their own scrolling. Appearance uses an explicit `photo-lighting-enabled`
switch, never panel visibility. Closing a copy or hiding all controls preserves
lighting and playback. Columns have close buttons and subtle type-colored headers;
capacity reserves the right sidebar and 320px of workspace. Layout v3 migrates old
preferences. See `docs/expandable_panels_implementation_plan.md` for the pending
user checkpoint. Detached controls are assessed only in
`docs/detached_controls_feasibility.md`.

Photo mode lives at [frontend/src/scene/photo_mode.js](../frontend/src/scene/photo_mode.js),
UI in [frontend/src/ui/photo_panel.js](../frontend/src/ui/photo_panel.js)
(`data-tab="photo"`, HTML under `#tab-content-photo`), with the shared sub-modules
that SURVIVED v1 under `photo_renderer/`: `figure_pass`, `figure_camera`,
`material_presets`, `lighting_presets`, `shadow_bounds`, `mesh_repr`.
`main.js` carries only an import + factory init + the `TABS` entry (LOC 8074 → 8059
on the merge — the archive removed more wiring than the rename added).

**Why:** publication-grade rendering for figures and animations. Activate/deactivate must restore the live scene exactly (lights, materials, scene.environment, scene.background, **renderer tone mapping**) — the live editor still has to work after exit. **How to apply:** never mutate scene state from photo-mode code outside the saved-state pattern (`_savedMaterials`, `_savedSceneEnv`, `_savedSceneBackground`, `_savedLightState`, `_savedToneMapping`/`_savedExposure`). Adding a new visual feature means adding a save slot and a restore step in `deactivate()`.

## Inherited from v1 — tone mapping is load-bearing, don't drop it

v2 was written from the ground up, but one v1 fix was re-derived into it and must
stay: [photo_mode.js:513](../frontend/src/scene/photo_mode.js#L513) sets
`THREE.ACESFilmicToneMapping` in `activate()` (exposure defaults to `1.0`, adjustable in Advanced), restores both at [:621](../frontend/src/scene/photo_mode.js#L621), and the
offscreen export renderer sets the same at
[:772](../frontend/src/scene/photo_mode.js#L772). **Why it is not cosmetic:** with
`NoToneMapping` (the Three.js default), HDR values hard-clip at 1.0 — that clipping
is what produced v1's screen-filling **yellow/purple wash** (2026-06-18 audit).
Pinned by `photo_mode.test.js` (ACES on activate, `NoToneMapping` on deactivate).
Export parity depends on the offscreen renderer matching the preview.

Most of v1's lighting stack remains archived. Studio IBL has since returned via
RoomEnvironment; the current renderer still has no bloom, no
Sun/preset-rig duality, no fluorophore point-lights, and no *visible* ground plane
(there is now a shadow CATCHER — see below — which is a different thing). So v1's other four
remediations (Sun-sole, PMREM re-bake isolation, Reflector state isolation, the
emissive clamp) have **no live subject matter**; they are recorded in
[project_photo_mode_archive.md](project_photo_mode_archive.md) for anyone reviving
`frontend/archive/photo_mode_v1/`.

**One live orphan.** `FLUORO_EMISSIVE_MAX = 25` +`makeFluorophoreEmissive()` in the
surviving [material_presets.js:163](../frontend/src/scene/photo_renderer/material_presets.js#L163)
have **no caller in `src/`** (only the archived v1 renderer) and no test. Its
comment block is the only in-code record of the pre-tone-map bloom mechanism, and
it points at `photo_renderer.js`, which no longer exists live. Don't delete it
without moving that explanation; don't trust its file pointer.

<a id="camera-pinned-key-shadow--2026-07-28"></a>
- [Camera-pinned key shadow — 2026-07-28](details/project_photo_mode/01-camera-pinned-key-shadow--2026-07-28.md#camera-pinned-key-shadow--2026-07-28)

<a id="video-export--an-animation-rendered-through-photo-mode-2026-08-02"></a>
- [Video export — an animation rendered through photo mode, 2026-08-02](details/project_photo_mode/01-camera-pinned-key-shadow--2026-07-28.md#video-export--an-animation-rendered-through-photo-mode-2026-08-02)

- [Video export — an animation rendered through photo mode, 2026-08-02 — continued detail](details/project_photo_mode/01-camera-pinned-key-shadow--2026-07-28.md)

<a id="shadow-catching-floor--2026-08-01"></a>
- [Shadow-catching floor — 2026-08-01](details/project_photo_mode/02-shadow-catching-floor--2026-08-01.md#shadow-catching-floor--2026-08-01)

- [Shadow-catching floor — 2026-08-01 — continued detail](details/project_photo_mode/02-shadow-catching-floor--2026-08-01.md)

- [Shadow-catching floor — 2026-08-01 — continued detail](details/project_photo_mode/03-shadow-catching-floor--2026-08-01.md)

<a id="simulation-displays-survive-the-photo-tab--2026-07-14"></a>
- [Simulation displays survive the Photo tab — 2026-07-14](details/project_photo_mode/03-shadow-catching-floor--2026-08-01.md#simulation-displays-survive-the-photo-tab--2026-07-14)

<a id="publication--figure-mode--2026-07-14"></a>
- [Publication / figure mode — 2026-07-14](details/project_photo_mode/04-publication--figure-mode--2026-07-14.md#publication--figure-mode--2026-07-14)

<a id="decisions-that-cost-time--dont-re-litigate"></a>
- [Decisions that cost time — don't re-litigate](details/project_photo_mode/04-publication--figure-mode--2026-07-14.md#decisions-that-cost-time--dont-re-litigate)

### Known caveats

- **Zoomed far out, the outline swallows small features — Roberts mode only.** The contour is
  a pixel-space effect; when a bead is 2–3 px across, the crease term fires over the whole
  sphere and the strand renders as black line-art with no fill. At normal framing and at export
  resolution it is correct. The Thickness / Creases sliders are the mitigation. **The exp tab's
  ChimeraX mode is immune** — it reads no normals, so there is no crease term to fire; this was
  the specific reason for porting it.
- The v1 path tracer remains archived; the current live tracer uses separate `path_trace_*` modules.
- GTAO + the figure pre-pass add two full-scene renders per frame; on software GL (headless)
  frames get slow enough that Playwright's element-screenshot stability wait times out — use
  `page.screenshot` there, not `locator.screenshot`.

Verified in-app on the isolated smoke stack (never the user's :8000 — see
[[feedback_no_live_server_mutation_for_verify]]): Publication applies through to every
control, each control toggles independently, the pass disables when both effects are off,
`renderToBlob` produces a real PNG with the outline, exit restores the lens, zero console
errors (i.e. no shader-compile failures). Screenshots confirmed the flat/outlined look.

<a id="exit-on-file-closeopennew-in-session--2026-05-29"></a>
- [Exit on file close/open/new (in-session) — 2026-05-29](details/project_photo_mode/05-exit-on-file-closeopennew-in-session--2026-05-29.md#exit-on-file-closeopennew-in-session--2026-05-29)

<a id="no-design--no-open-sidebar-close-session--2026-08-02"></a>
- [No design ⇒ no open sidebar (Close Session) — 2026-08-02](details/project_photo_mode/05-exit-on-file-closeopennew-in-session--2026-05-29.md#no-design--no-open-sidebar-close-session--2026-08-02)

<a id="exit-on-sidebar-tab-switch--feature-log-default-on-load--2026-06-20"></a>
- [Exit on sidebar-tab switch + feature-log default on load — 2026-06-20](details/project_photo_mode/05-exit-on-file-closeopennew-in-session--2026-05-29.md#exit-on-sidebar-tab-switch--feature-log-default-on-load--2026-06-20)
