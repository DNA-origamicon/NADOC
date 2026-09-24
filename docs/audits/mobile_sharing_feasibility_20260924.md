Mobile sharing feasibility — 24 September 2026

**Assessment: high feasibility for mobile guest viewing, conditional on scene size
and mobile-specific controls/resource management.** A native Android/iOS app is
not necessary for the first release. Unrestricted desktop-scene parity across
every phone less than five years old is not a credible performance promise.

Scope is joining a shared presentation, inspecting geometry, following/sharing
camera views, seeing annotations and presenter edits, and potentially playback.
Running the full editor, generating molecular geometry, and simulations on the
phone are separate projects. This is a source-code and platform-documentation
assessment, not a physical-phone benchmark. No mobile implementation was made.

Assume roughly late-2021-or-newer hardware with a maintained browser/OS. Purchase
age alone is insufficient: budget Android hardware, available memory, GPU drivers,
browser version, scene size and sustained thermal load all affect usability.
Use Safari on iPhone and Chrome on Android as the first qualification targets;
test other browsers and in-app invitation browsers separately.

**Platform fit is good.** NADOC uses Three.js r172 and WebGLRenderer. Three.js
requires WebGL 2 for this renderer from r163 onward. Safari added WebGL 2 in
Safari 15, and Khronos documents broad support across major browsers. Check
WebGL 2 at startup rather than inferring it from a phone model or user agent.
These facts establish API feasibility, not a frame-rate guarantee.
[Three.js renderer](https://threejs.org/docs/pages/WebGLRenderer.html),
[Safari 15](https://webkit.org/blog/11989/new-webkit-features-in-safari-15/),
[Khronos compatibility](https://www.khronos.org/blog/webgl-2-achieves-pervasive-support-from-all-major-web-browsers).

The standalone viewer consumes prepared binary scenes; it does not require the
editor backend on the guest. Geometry generation and representation construction
remain on the presenter. Instancing, shared geometry, binary typed-array views,
revision validation, camera preservation, network reconnection hooks, and slow
network/rendering indicators are already useful foundations. Keep the existing
WebGL renderer initially; WebGPU or a native wrapper is not needed to prove this.

Expected suitability below is engineering judgment, not measured phone performance.

| Feature | Feasibility | Main qualification |
|---|---|---|
| Join, orbit/pan/zoom, follow presenter, saved perspectives | High | Responsive layout and reliable gestures |
| Hull Prism, cylinders, mrDNA coarse | High for bounded scenes | Large assemblies and many objects still cost memory |
| mrDNA fine, oxDNA, Full/beads | Moderate to high | Instance count, bonds, pixel coverage and model size |
| Atomistic stick/ball-and-stick/VDW, surfaces | Conditional | Atom/bond count, mesh resolution and GPU fill rate; local detail is a better first target than whole large atomistic structures |
| View volumes and independent colors | High for modest scenes | Additional geometry remains part of the transmitted scene; visual masking does not inherently reduce download size |
| Hull openings | Feasible | Custom shader compilation, uniform limits and the number of active volumes need device checks |
| Multi-overlay | Conditional | Multiple scene copies and one render pass per layer; transparency adds cost |
| Presenter design edits | High for small/moderate snapshots | Whole-scene replacement bandwidth and peak memory |
| Long or dense trajectories | Higher risk | Frame decoding, caches, sustained rendering and transfer rate |

**Concrete gaps in the current implementation:**

1. Touch navigation: OrbitControls already implements one-finger rotation and
   two-finger zoom/pan. However, `makeMultiscaleControls()` sets `noZoom = true`
   and adds wheel-based zoom; it has no equivalent pinch handler. A shared pose
   can currently switch the guest into that mode. Prefer Orbit for touch initially,
   and preserve the guest's input mapping when applying presenter camera poses.
   Centering currently relies on `dblclick`; provide an explicit touch action.
   [OrbitControls](https://threejs.org/docs/pages/OrbitControls.html).
2. Layout: the viewer has a viewport tag and `touch-action:none`, but its header
   is a single unwrapped flex row. Multiple presentation/status bars compete with
   the canvas. Replace desktop header controls with a compact menu, use dynamic
   viewport sizing and safe-area padding, support portrait/landscape and the
   virtual keyboard, and provide comfortably sized touch targets.
3. Rendering budget: runtime enables antialiasing, alpha and stencil, caps device
   pixel ratio at 2, and continuously renders. A mobile quality profile should
   start near ratio 1, adapt resolution from measured performance, and avoid
   unnecessary idle rendering. Ratio 1 versus 2 draws one quarter as many pixels
   at the same CSS size; this reduces pixel work, not geometry memory. Preserve
   stencil when required by sectioning. Use existing health instrumentation.
   [Three.js high-density rendering guidance](https://threejs.org/manual/pages/responsive.html).
4. Loading and replacement: the package ceiling is 512 MiB and the validator
   permits five million instances. These are format limits, not mobile budgets.
   A replacement is constructed before the previous scene is disposed, so old
   scene resources and new decoded arrays/objects coexist. GPU allocations and
   temporary buffers add pressure. Typed-array views reduce copying but do not
   eliminate this peak. There is no universal safe browser-memory allowance;
   qualify actual devices and bound caches/resources.
   [WebGL memory guidance](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices).
5. Adaptive content: prepared packages contain the exported representation, not
   a complete topology engine or all alternate representations. A guest cannot
   simply turn a heavy atomistic package into cylinders. A meaningful low-memory
   mode needs a lightweight package generated by the presenter, with a manifest
   that allows choosing it before downloading the heavy scene. Make fidelity
   changes explicit; do not silently hide scientifically relevant content.
6. Live updates: whole-snapshot replacement is viable for small scenes but costly
   on cellular. An older repository audit recorded a 22,629,044-byte Voltron
   package. At 10 Mbit/s that is about 18 seconds of ideal payload transfer alone,
   excluding export, latency, decode and rendering. This is a historical package
   measurement plus arithmetic, not a mobile measurement or every representation's
   size. Coalesce revisions, avoid an unbounded backlog, and eventually reuse
   unchanged geometry/materials or transmit deltas if measurements justify it.
7. Lifecycle: existing EventSource and online/offline hooks provide a starting
   point. Add explicit foreground-resume reconciliation, background pause policies,
   and WebGL context-loss/restoration UX. After an app switch or screen lock,
   resume from the newest usable revision and retain the guest camera when possible.
   Mobile browsers can freeze or discard pages, and unload callbacks are not a
   reliable recovery mechanism. Do not require a permanent foreground connection.
   [Chrome lifecycle guidance](https://developer.chrome.com/docs/web-platform/page-lifecycle-api).

**Recommended delivery sequence and planning effort.** These are rough estimates
for one engineer familiar with NADOC, assuming physical test devices are available;
they are not measured delivery commitments.

| Phase | Work | Estimated effort |
|---|---|---|
| Device qualification | Instrument package/instance counts, load/replace timing, frame times; establish phone/scene matrix | 2–4 engineer-days |
| Mobile guest beta | Responsive UI, Orbit touch defaults, centering action, conservative resolution, foreground recovery and clear load failures | 5–10 additional engineer-days |
| Broader scene support | Lightweight/full package selection, memory-aware loading, bounded playback, per-guest quality | 1–3 additional engineer-weeks |
| Large-scene update optimization | Shared resources/deltas, progressive delivery or other changes demonstrated necessary by measurements | Scope after benchmarks |

A useful mobile beta is therefore plausibly a 2–3 working-week effort; broad,
well-qualified support could take 4–6+ weeks. The uncertainty is concentrated in
large scene memory and update throughput, not basic browser capability.

**Qualification should be on real phones.** Use at least an older supported iPhone
(including a smaller/lower-memory class), a newer iPhone, an older budget/midrange
Android, and a newer high-end Android. Browser emulation is useful for layout and
touch-event tests but does not establish GPU, thermal, memory or lifecycle behavior.
Record actual model, OS and browser versions instead of defining support by age alone.

Exercise a small origami, `3x6SQ_norm_skips`, a large Voltron-class design, local
atomistic volumes, two/four overlays and representative trajectories. Repeat
overhang creation, end resizing and extrusion while guests remain connected.
Test portrait/landscape, keyboard entry, 15–30-minute sessions, screen lock/app
switch, Wi-Fi/cellular transitions and simulated context loss. Proposed beta
acceptance targets: usable touch controls with no horizontal overflow, at least
30 FPS during ordinary orbit on qualified scenes, no reload/context-loss over a
20-minute session, and eventual convergence to the newest design after interruption.
Measure join/update latency under stated bandwidth and package sizes before
setting a promise; no FPS or base-pair capacity has been established here.

Implementation evidence: `frontend/viewer.html`, `frontend/src/viewer/runtime.js`,
`prepared_viewer.js`, `prepared_scene.js`, `package_container.js`, `shared_overlay.js`,
`meeting_presentation.js`, `meeting_scene_updates.js`, `viewer_health.js`,
`frontend/src/scene/multiscale_controls.js`, `hull_volume_cutouts.js`, and
`docs/audits/prepared_lan_20260920/README.md`. Existing live-edit work is preserved.
