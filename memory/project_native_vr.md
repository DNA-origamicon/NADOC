---
type: project
status: active
authority: canonical
review_after: 2026-09-01
---

# Native VR expansion

## Controller-relative menus and tip-sphere grips (2026-10-05)

Sidebars now spawn 40 cm along the invoking controller's -Z pointer, with a
30° backward local-X tilt, then remain world-docked. Head pose no longer chooses
menu placement. Desktop and View tools use the same controller orientation at
1.35 m / .8 m; attached authoring/lattice panels inherit their parent pose.
Follow mode and both touchpad wheels share the 30° tilt. Border targeting uses
selection-sphere center (-.12 m in controller space) and the current per-hand
radius against the visible rail band, including its inner edge at minimum
sphere size. Contact metadata preserves the real controller origin for drag/resize
anchoring. Sidebar, desktop, View tools and lattice borders use the same contact
path; lattice interior zoom keeps its existing interaction. Semantic Witness
`touch_menu` and physical grip tours place the tip sphere on the border.
The registered `grips` tour checks both controller spawn poses, midpoint-only
rejection, world-fixed placement, move/resize/release and stereo frame colors.
All four profiles pass for sidebar grips, detached Desktop and both wheels,
including stereo pixels and actual desktop delivery. 72 native tests, 48 focused
Python tests, 7,375 frontend tests and the 397-state menu render audit pass.
Evidence, retained timing/acquisition attempts and cleanup:
`.development-artifacts/vr-controller-menus-20261005/validation.json`. Physical
feel and through-lens comfort remain MV-41.

## Right touchpad Edit wheel (2026-10-05)

The Edit wheel now shares the left wheel's `TouchpadWheel` gesture/render module:
thumb-axis sector hover, light tick on entry, last-held selection on release,
center cancellation and controller-following pose. Existing compass is preserved:
Ligate right, Nick up, Undo left, Redo down. The old `RadialToolMenu` world-volume
hit implementation is removed. Right-sidebar focus navigation remains when open.
`edit-wheel` is registered under Controls & layout; its empty-scene metadata
fixture verifies history request publication without editing a user document.
Ligate/Nick/avatar probes use profile-driven pad axes. The separate
`edit-wheel-history` tour exercises real document Undo/Redo. Broader Nick/Ligate
pixel workflows still fail (ISSUE-57/58); do not claim their full flows validated. Physical haptic feel and
through-lens comfort remain manual validation (MV-40). Both wheels and real
document history pass all four profiles; 72 native tests and 397 rendered states
pass. Full evidence, failures and cleanup: `.development-artifacts/vr-edit-wheel-20261005/validation.json`.

## Left touchpad selection wheel (2026-10-05)

`selection_wheel.hpp` owns the six-sector thumb gesture and rendering. Hold the
left pad; clockwise from up: Drill, Cluster, Strand, Domain, Crossover, Bases.
Amber hover plus light haptic requests precede release-only scope publication;
center release and focus/tracking loss cancel. The controller-following wheel
uses thumb axes, not world controller translation. It replaces general selection
rows and Move/Rotate scope buttons. Right pad focus stays; left sidebar tours use
pointer scrollbars. Scope changes cancel Move previews, preserving panels.
Registered `selection-wheel` (`menu_tour --selection-checks --validate`) covers
four motion profiles, stereo highlights, haptic requests, delayed commits and
sidebar independence. Physical feel remains MV-39. `selection_wheel` live JSON
exposes six item axes/centers, current scope, hover and visibility.

## Sidebar-only menus and history feedback (2026-10-05)

The old Options/Tools/selection/representation/coloring/jobs/trajectory menu
renderer, hit targets and navigation state have been removed. Current sidebar
panels own settings and tool transactions; Tools contains direct authoring actions
and the left touchpad wheel selects scope. Visualization retains recentering, Simulations owns job
selection and trajectories, and the left VR tab owns the detached desktop.
Radial Undo/Redo dispatch history and pulse the initiating controller without
opening menus. ScryWrite exposes per-hand haptic request counts/amplitudes; its
synthetic input records requests while physical vibration remains suppressed.

The registered Nick/Undo/Redo tour now asserts haptic requests and unchanged,
closed sidebars both at dispatch and after acknowledgement. Navigation, focus,
Extrude/selected-end probes, wheel fixtures and formatting atlas coverage use
only current sidebars/tool panels. The registered Current menu routes entry
(`menu_tour --action-checks --validate`) exercises all five authoring choices,
selection scopes and trajectory controls with four profiles on an empty viewer
and a temporary metadata fixture. See [sidebar guide](../docs/vr_sidebar_menus.md).
Final validation results belong in the current task report; this records the
implemented contract, not a physical headset or vibration verification claim.

## Continuous Move/Rotate at nominal 90 Hz (2026-10-03)

Final full-24HB Ball & Stick cluster drags sustain 89.50–89.53 measured FPS across
all four profiles (the workstation's nominal 90 Hz cadence), zero repeats and
0/1/0/0 drops. All four pass stereo, save/reopen and Undo. Retained changes:
self-shadows off + eight-to-four-sided ordinary bonds during changing previews;
restore full detail after 180 ms settled or preview cleared; ordered atomic event
publication on a worker; mirrored eye rendered last. Full-detail final-binary
control remains 86.37 FPS with 93 repeats / 3 drops, so temporary reduction is
still needed. Motion GPU span p95 is now 5.91–6.12 ms. A fused transform/bounds
experiment showed no clear gain and was reverted. Event publication previously
blocked for 3.1 s; its worker preserves snapshot order and drains at shutdown.

Remote acquisition feedback now includes the original >15 cm condition, fixing
early near-hover termination without changing profiles or thresholds. The settled
tour retains motion/settled stereo captures outside measurement. Six native
checks, full-quality parity, 39 focused Python tests and scoped lint pass.
This is sustained-drag evidence, not a universal no-hitch claim: first-grab setup
is separate; one stationary control shows a 134 ms grouped feed-polling stall.
Through-lens transition comfort remains MV-VR-MOTION-QUALITY. See
[audit](../docs/audits/vr_motion_optimization_20261003.md) and
`.development-artifacts/vr-motion-20261003/`. `NADOC_VR_MOTION_DETAIL=0` provides
full-quality A/B mode; default enables temporary reduction.

## Settled Move/Rotate drag (2026-10-02)

Long held-trigger Ball & Stick cluster tests exclude initial preview and >=5 s
warm-up. Steady-fast/deliberate sustain 77.27/78.39 FPS over 30.38/31.90 s;
last ten seconds remain 77.01/74.59 FPS. Subsequent 10 s stationary holds reach
89.53 FPS with zero compositor repeats/drops. Motion GPU-span p95 ~10.0 ms
versus hold ~7.64 ms; active packed-preview p95 3.00–3.11 ms. Prioritize recurring
transform/upload/presentation costs for continuous motion; this is not merely
startup recovery. Rare event-publication stalls of 62–76 ms are a separate
worst-case-latency issue. Exact upload vs shader vs synchronization attribution
still needs isolation. Both steady profiles pass persistence/Undo; both variable
profiles fail remote-grab acquisition before measurement, so no all-four pass.
Reusable Debug authoring tour `move-settled-drag`; frame audit accepts
`--settled-drag`. 38 focused tooling tests pass. See
[audit](../docs/audits/vr_settled_drag_20261002.md) and
`.development-artifacts/vr-settled-drag-20261002/` for retained evidence and limits.

## Move/Rotate first-grab cache reuse (2026-10-02)

Current-code baseline identified first-grab setup, not continuous transforms, as
the dominant preview stall. Static Full/Stick/Ball & Stick/VDW now construct the
packed preview from the displayed prepared representation, preserving explicit
endpoint weights, aliases, colors, IDs and resident-cache isolation. Visualized
and committed-pose cases retain the general path. Full-24HB Ball & Stick cluster
first-preview work: 560.5 ms baseline → 116.5 ms final steady-fast (79% reduction);
all four final cluster profiles pass edit, stereo, save/reopen and Undo, with
113–123 ms first previews. This is still above the 11.111 ms budget. Continuous
motion/uploads are unchanged; no sustained-90-Hz claim. Eight isolated setup
cases improve; all 32 paired images match exactly. Five native checks pass.
Live nucleotide acquisition fails before preview, also reproduced in the baseline;
do not claim full live nucleotide coverage from the isolated renderer results.
The existing Debug authoring renderer regression now covers prepared first grabs
and accepts `--compare-setup` with `--scene-dir` for reproducible A/B measurements.
See [audit](../docs/audits/vr_preview_preparation_20261002.md) and
`.development-artifacts/vr-preview-20261002/` for results and failed attempts.

## Staged static scene activation (2026-10-02)

Static refresh now reuses the live renderer and stable object IDs, uploads prepared
buffers with a 1 ms/256 KiB per-poll target, then atomically swaps after a nonblocking
fence check. Old geometry/picking remain active until ready; CPU caches retire on
the worker. Nonempty visualization snapshots retain the synchronous fallback.
Full-24HB Ball & Stick isolated blocking activation 976 ms becomes <=1.15 ms
staging polls. Two physical OpenXR reloads: staging/swap at nominal 90 Hz with no
long submission gaps, max stage 1.30 ms / swap 0.062 ms. The broader parse-to-ready
interval still had three gaps in the first reload; no universal 90 Hz claim.
Six native checks and 35 tour tests pass; FAST suite has 9525 passes, 93 skips,
and six failures in unchanged geometry/surface/representation-control code.
Subsequent user-authorized FULL validation ran 10,130 tests: 10,002 passed,
94 skipped, 18 failed and 18 setup errors. Explicit GROMACS thread-MPI rank
selection repaired all 18 setup errors (18/18 focused reruns pass); the 18 other
failures remain and FULL debt is retained. See
`.development-artifacts/deferred-validation-20261002/findings.txt`.
Debug > VR Tours & Tests > Authoring includes scene-activation regression.
Evidence: `.development-artifacts/scene-activation-20261002/findings.txt`.
This supersedes the static activation stall below, not active visualization or
End Resize correctness limitations. Before this round, cluster tint removed the
duplicate glow and selection-triggered rebuild; older glow timings are historical.

## Researched CPU fixes and desktop-off validation (2026-10-02)

Retained: indexed owner lookup, selection-aware hover, cached preview bounds,
async parsing and one-pass style activation/CPU-source retirement. Audit drawing
now defaults off; production preference and native mirror unchanged. Full-24HB
Bend lookup <1 ms, hover ~0.31 ms, highlights ~39 ms (first candidate ~392 ms).
End Resize activation ~423 ms (first candidate ~1,282 ms); +6/−6 failure remains.
Both GPU candidates rejected: conservative depth ineffective; cached cylinder
frames regressed live rotation ~45→36 FPS despite isolated GPU improvement.
Original renderer restored. Final 28 attempts, 9 workflow/audit passes; no 90 Hz
certification or hardware ceiling proven. Native 4/4 and focused Python 62 pass.
See [research and feature table](../docs/audits/vr_research_fixes_20261002.md), with
remaining style/activation/GPU/pacing limits and evidence links.

## Desktop contention isolation (2026-10-02)

Fresh full-24HB Ball & Stick draw-only controls confirm desktop GPU contention:
selected nucleotide idle 47.46→89.53 FPS, compositor GPU p95 12.71→7.51 ms.
Cluster idle remains 44.76 FPS although GPU p95 falls 18.21→12.69 ms. Device-wide
utilization is only ~56% for desktop-off cluster: half-rate pacing leaves idle
GPU time; do not require 100% utilization to diagnose missed 11.111 ms deadlines.
Both corrected draw-only edit/save/reopen/Undo controls pass. Selection lookup
scans, full style rebuilds on changed highlights, synchronous scene refresh and
model-sized preview uploads were separate software targets at that point. The End Resize
4.19 s input stall coincides with VR_SCENE_APPLIED; not all of it is pure CPU.

Help → Desktop 3D during VR now provides a persisted draw preference (default
on), paused notice/resume control, and automatic normal desktop drawing after
VR exits. Callbacks and scene updates continue; WebXR is unaffected. This does
not fix hidden-tab requestAnimationFrame suspension or disable native mirroring.
Four-profile preference validation passes all four steady workflows; all four
variable workflows retain prior target-acquisition failures. Final UI/edit/Undo
verification passes. See [bottleneck report](../docs/audits/vr_bottleneck_isolation_20261002.md)
for controlled conditions and remaining limits. A diagnostic Playwright route
must be removed before synchronous native probes, otherwise browser network
feedback stalls; failed setup traces are retained. Test teardown now resolves
the actual frontend root and random smoke port for bridge-credential cleanup.

## Ball & Stick 90 Hz follow-up (2026-10-02)

User time box ends 18:00:40 UTC; two optimization candidates maximum per workflow,
Surface performance excluded. Shader experiment was pixel-identical but ineffective
and reverted. Retained candidate avoids first eligible Move commit/Undo rebuilds.
A PBO/fence readback experiment was also reverted after only a ~0.19 ms median
sample-cost change with no cadence gain. Final native parity/diagnostic checks pass. Comparable full-size Move/cluster edit/save/reopen/Undo pass; longest measured
frames fell ~307→34 ms and ~715→34 ms, but sustained cadence still misses 90 Hz.
Desktop Playwright focus emulation can retain ~60 FPS desktop draws during VR.
Minimizing stops draws but pauses callbacks and can block cluster commits; that
experiment was archived and its dependency/harness focus changes restored. Do not
use it as a production remedy or attribute all GPU cost to native rendering.
Completed 48 second-candidate cases across all four profiles (8 workflow passes),
then both final retained-code Move checks passed. All 12 feature categories remain
unresolved for consistent 90 Hz; Bend selection reached 838 ms and End Resize
commit 4.21 s. Browser-free idle/grip baseline passed 12 intervals / 4,612 frames.
See [campaign report](../docs/audits/vr_ballstick_90hz_20261002.md) and its compact
review ZIP. No fundamental hardware limit proven; original 24HB preserved and
audit viewers closed.

## Full-size 24HB audit (2026-10-02)

Full-size follow-up uses private copies of `workspace/24hb_0xT.nadoc` (24 helices,
76 strands, 6,720 nucleotides; original SHA unchanged). Fresh physical OpenXR
baseline: 48 idle/grip intervals, 18,450 frames, roughly 89.36–89.64 FPS across
Full/Stick/Ball & Stick/Quick Surface. Synthetic controller profiles, not wearer
validation. Controlled 12-tool × 4-style × 4-profile matrix completes 192 attempts;
31 complete workflow/audit passes (14/6/7/4), plus four separately failed Full
Nick observation retries. Latest requested-style measured coverage is 48/45/44/43
of 48 respectively; valid traces alone do not imply tool-stage success.

Confirmed full-size candidates: selected Surface Move `pick` p95 ~32.74 ms,
~21 FPS without repeated `setStyle` calls; Ball & Stick cluster commit includes
~654 ms inclusive `setStyle`; End Resize native +6 can save -6 at an interior
forward 3′ end because non-singleton outward sign follows nearest helix endpoint.
The initial dataset collection did not implement these fixes; the later 90 Hz
follow-up above addresses eligible Move commits. Preserve failures, selection
semantics and invalidation correctness.

An earlier long multi-launch campaign exhausted Steam shared memory; graceful
Steam/SteamVR reset reclaimed it. Controlled batches reset between styles and
record host resource counters; this does not establish a NADOC leak or growth
in one uninterrupted session. Fixed benchmark budget is 11.111 ms at 90 Hz,
independent of adaptive OpenXR pacing. Compositor GPU spans overlap CPU wall
time and are not isolated shader cost. Dataset retains 409 attempts and 4,592
interval rows, with an offline browser, CSVs and compact provenance ZIP; complete
raw logs/capture trees stay in the archive. See the
[full-size audit](../docs/audits/vr_24hb_tool_performance_20261002.md).

## Frame calculation audit (2026-10-01)

Opt-in native `NADOC_VR_FRAME_AUDIT=1` records exclusive outer-frame phases and
inclusive calculation counts/times. Live audit entry points are
`tools.vr_workflows.frame_audit_tour` (private 24HB idle/grip, four representations)
and `tool_frame_audit` (isolated tool fixtures). Raw compositor delivery and GPU
timing are separate from application wall time; scene-only p95 is not a full
budget check. Findings, reproduction, failed attempts and coverage boundaries:
[frame calculation audit](../docs/audits/vr_frame_calculations_20261001.md).

Confirmed: standalone deferred representation activation needed polling even
without lazy startup (fixed). Quick Surface selected Move still rebuilds style
(~45 ms per changed preview on a small 6HB fixture); Full/Stick/Ball & Stick use
packed updates. Spectator diagnostics synchronously read pixels every 30 mirror
frames, causing recurring p99 wall costs invisible to p95. Neither candidate
optimization has been implemented by this audit. Preserve readback provenance
and slab geometry authority when optimizing; do not lower render quality.

## Component gallery (2026-10-01)

Debug → VR Component Gallery now offers native VR and headset-free desktop
thumbwheel evaluation demos. Both share solid ridged meshes and inertia, with
20/35/50% exposure columns and 0–10/100/1000 range rows. Extrude and Bend share
the new clipped solid rendering. Launch, controls and validation:
[component gallery](../docs/vr_component_gallery.md). Range-dependent sizing is
approved by the user: Extrude uses 0–1000 / 35%, and Bend uses 0–100 / 35% with expanded layout and raised-surface hit testing. The gallery also offers six button styles inspired by MRTK, visionOS, Material and Blender, with VR/desktop demos and all-four-profile validation. Cards and lists adds six expandable studies with selectable children and the same launch modes.

## Resource limits after the October 1 UI evaluation crash

The workstation exhausted RAM while native C++ builds, the auto-parallel backend
suite and unrestricted Vitest ran together. The user requested cautious resumption.
For subsequent local VR UI work, run these jobs sequentially: native builds with
`-j1` and reduced priority; Vitest with `--maxWorkers=2`; focused backend checks.
Check available RAM and memory pressure before launching the next job. Preserve
suite guards and report interrupted broad checks as incomplete. Do not stop user
applications to make room for validation.

## Selected-part Move/Rotate slowdown (2026-10-01)

User clarified the FPS drop concerns the selected-part Move/Rotate tool. A
controlled production-GlScene diagnostic reproduces full representation rebuilds
on every changed preview: single-base translation medians are Full 18.5 ms,
Stick 161 ms, Ball & Stick 294 ms, VDW 130 ms on the saved 24-helix part.
This is separate from whole-model grip/browser contention investigations below.
Packed preview caching is now implemented for Full/Stick/Ball & Stick/VDW.
Full update+draw p95 is 2.4 ms in the controlled 24-helix test; VDW and single-base
atomistic selections also fit 11.1 ms. Large Stick/Ball & Stick cluster draws
remain above budget (14.1/16.5 ms total p95). All 32 renders exactly match baseline.
Four live Full base-edit profiles pass with 520 compositor samples and no
repeats/drops during measured edits (GPU p95 1.73–2.51 ms). The 24-helix numbers
remain isolated renderer timings, not live atomistic FPS. See the
[optimization audit](../docs/audits/vr_move_rotate_optimization_20261001.md) for
correctness, live validation, remaining setup hitches and reproduction.

## Motion regression (2026-09-29)

The user confirms loaded-model motion was satisfactory before the loading-freeze
changes. Isolate that regression rather than changing shadow quality or lighting.
Rendering experiments did not clear the timing gate and were reverted.
See [investigation](../docs/audits/vr_motion_regression_20260929.md).

## Quick Expand removed from VR (2026-09-29)

VR now exports, parses and caches natural geometry only. The View Tools tablet
has ten entries; the Expanded control and native animation are removed. End,
plane, ligation and resize catalogs no longer calculate expanded placements.
Legacy feedback readers accept old paired fields only for wire compatibility;
there is no expansion rendering or interaction state. Desktop expansion stays
separate and cannot override the natural VR model. Use model scaling and physical
movement for close inspection. See the startup/load-time comparison in
[removal audit](../docs/audits/vr_quick_expand_removal_20260929.md).

## Visible model during representation loading (2026-09-29)

The frame-gap guard now draws an unlit point cloud from the displayed GPU
buffers instead of suppressing the model. Atoms, bond endpoints and surface/box
centres retain colors, object IDs, depth and model transforms; CPU picking remains
on the displayed representation. No extra export or geometry upload is needed.
Normal rendering resumes on completion, cancellation or failure. The existing
on-demand representation tour checks both-eye model pixels during loading and
covers Surface → Stick. See [visibility audit](../docs/audits/vr_loading_visibility_20260929.md).

## Loading frame delivery (2026-09-29)

Static natural representations prepare geometry/indexes on the parsing worker,
upload in 1 ms / 256 KiB slices, and activate after a nonblocking GL fence. GPU
inactive cache is 256 MiB; CPU inactive sources are budgeted at 512 MiB (Full,
active and view-volume sources protected). CPU disposal and latest avatar-file
publication run off the XR thread. The earlier loading hitch was avatar I/O,
not merely GPU draw time. Shadow reuse was removed during investigation of the subsequent motion regression;
the original head-relative lighting and shadow pass are restored.
Debug → VR Tours & Tests → Representation loading frame delivery retains outer
loop/subphase timing and actual SteamVR compositor samples. Logs are asynchronous;
trace overflow fails acceptance. Use the fastest observed runtime period for
the guard/gate: SteamVR may lengthen predicted periods during reprojection.
Existing draw-only green metrics are insufficient. Full-state RPC progress polling
uses 100 ms spacing; motion profiles and their 150 ms deadline are unchanged.
Dynamic deformation/expansion paths and physical comfort remain distinct checks.
See [implementation audit](../docs/audits/vr_loading_frame_delivery_20260929.md).

## Browser/native verification and backend lifetime (2026-09-29)

Use the registered `browser-representations` tour for real browser launch/style
acknowledgements; `startup_tour` has a private responder and cannot establish that
path. Browser readiness requires loaded geometry and a dismissed Welcome screen,
not only backend document metadata. The tour opens an isolated __e2e__ copy,
asserts identifiable geometry in both eyes, and owns cleanup. `backend-lifetime`
checks real worker shutdown. `vr_lifecycle` tracks Popen ownership and joins native
cleanup on FastAPI lifespan teardown. Do not ask the user for the View in VR click
when automated browser orchestration can perform it.

## Early VR loading and menu depth (2026-09-29)

Normal launch now enters OpenXR before model export, with a head-height,
view-facing loading panel and named preparation stages. Export uses a private
copy of the document; native parsing is asynchronous, and GPU preparation submits
loading frames during preparation. First-frame readiness continues to mean the part.
Startup loads Full in its natural pose only. Other styles export and
parse on demand, with a counted-work percentage/bar inside the selected button;
previous geometry stays visible. Cached CPU geometry is reused until scene refresh or budgeted eviction.
Menu blur uses same-eye depth rejection; controller sticks, spheres and other
world-space guides write depth so foreground elements remain sharp.
See [startup and depth behavior](../docs/vr_startup.md). Debug Controls & layout
includes reusable `startup`, `representation-loading`, and `menu-depth` checks. Stereo evidence does not
establish worn-headset comfort or a fresh operating-system reboot.

## Frosted menus and calibrated floor (2026-09-28)

Native menus now use per-eye blurred white glass (`frosted_glass.hpp`), including
sidebars and the view-tools tablet. The user prefers barely visible frosting: 10% white, 90% blurred scene, with light
lettering and very faint button fills. Tablet SVGs retain desktop RGB/gradients
and computed styles; native-only controls use stable subtle accents. See the
[white-glass audit](../docs/audits/vr_white_glass_20260928.md). `room_floor.hpp` anchors a 0.5 m grid and cyan
play-area rectangle to OpenXR STAGE, never model transforms or invented bounds.
Debug → VR Tours & Tests → Controls & layout → Frosted menus & SteamVR floor
runs the isolated `room-ui` demo/validation. All four profiles pass stereo blur,
calibrated-edge and actual desktop checks. Worn-headset review remains pending.
See [usage](../docs/vr_room_ui.md) and [audit](../docs/audits/vr_room_ui_20260928.md).

## Simulation results (2026-09-28)

The left Simulations tab now mirrors desktop engine tabs and job selection through
`vr_simulations.js` and `simulation_panel.hpp`. Selecting a job extends a separately
scrollable Visualizations pane to the right. Native touchpad focus/Trigger and ray
input invoke the desktop's real result handlers; trajectories are omitted. Actual
static meshes use the existing view-tools scene feed. **Frame result** uses result
bounds. The Debug Left-sidebar tour `simulations` uses private copies of completed
`2hb_1xT` jobs, including archived NAMD results. See [usage](../docs/vr_simulations.md)
for operation and the known, deferred CanDo small-design predicted-shape bug.
The complete tour verified 22 available static modes; a final navigation campaign
passed all four motion profiles with one mode per engine. Actual stereo/menu and
desktop-mirror checks passed. Physical headset comfort remains pending. Exact
coverage and failed attempts: [audit](../docs/audits/vr_simulations_20260928.md).

## Standing user requirement: organized VR tours

Every future session adding or changing VR behavior must create or extend a
reusable tour/test and organize its entry in **Debug → VR Tours & Tests…**.
Register it in `tools/vr_workflows/tour_catalog.py` under the related sidebar tab
or interaction category; follow the [registration checklist](../docs/vr_sidebar_menus.md#adding-future-tours-and-tests).
Do not leave new major demos or validation workflows as undiscoverable shell commands.

## Quiver gesture for scissors (2026-09-28)

Either controller can now toggle global Nick mode by reaching from in front of
the headset to behind the head/shoulder and dwelling 0.35 s, with buttons released.
A 0.15 s front dwell rearms it; remaining behind cannot repeat. Head-relative
position uses horizontal headset facing, with a real controller-travel requirement
so head turns alone do not count. Tracking loss, menus, buttons, active gestures
and pending edits suppress detection. Equip/stow use different haptic amplitudes.
Selecting Nick again on the wheel remains the alternate way to put scissors away.
The existing **Nick with scissors, Undo and Redo** tour now includes two quiver
reaches, held-behind non-repetition, no design mutation and visible sphere/scissors
restoration before its cut/history checks.
All four profiles passed; evidence `.development-artifacts/vr-nick/a4fdd8b73e/`.
See the [gesture audit](../docs/audits/vr_quiver_gesture_20260928.md) for the precise
region/dwell, rendered pixel checks and remaining human comfort/tracking limits.

## Radius-wheel Nick and history (2026-09-28)

All four wheel sectors are now active. Undo/Redo use the ordinary desktop design
history and refresh native geometry. Nick replaces both selection spheres with
scissors: analog trigger pressure closes the blades and brightens the candidate
backbone bond; the existing full-click threshold creates one backend nick. A held
trigger cannot repeat the edit. The browser shares the versioned, serialized
ligation transaction path for Nick/Undo/Redo; requests are deduplicated per session.
Nick keeps the canonical selection level `base` while owning bond targeting itself
(the event protocol does not have a `bond` selection level).
Debug → VR Tours & Tests → Tools · Authoring → **Nick with scissors, Undo and Redo**
is the discoverable demo and four-profile validation route. The API excludes
synthetic/loop-copy/ambiguous-coordinate targets. See [workflow](../docs/vr_ligation.md).
All four physical runtime profiles passed nick, partial-pressure pixels, empty
click, held-trigger non-repetition and exact wheel Undo/Redo. Evidence:
`.development-artifacts/vr-nick/145d008fa4/`; see the
[audit](../docs/audits/vr_nick_history_20260928.md) for the retained protocol failure
and remaining Expanded/large-design/human checks. User deferred the previously
reported apparent moving/resetting base; do not claim this work resolves it.

## Radius-wheel Ligate (2026-09-28)

Latest user direction replaces the four radial tool sectors with Ligate/Nick/Undo/
Redo. Ligate was implemented first; Nick and history now also work as described
above. Existing tools retain sidebar entry points. Either controller can
trigger-pick a real 3′ or 5′ end, stretch a cyan preview, snap green to a compatible
opposite end on another strand, and release to create one forced ligation through
the desktop API. Versioned catalogs and deduplicated release events protect the
transaction; scene/menu/tracking changes cancel active drags. Each saved bond is
independently undoable on desktop.
Debug → VR Tours & Tests → Tools · Authoring → **Ligate ends with the touchpad wheel**
runs the reusable demo or four-profile validation. All four profiles passed both
pickup polarities, invalid release, native refresh, stereo/mirror preview pixels,
saved-bond pixels and exact Undo. Evidence: `.development-artifacts/vr-ligation/69c3958ea7/`.
See [workflow](../docs/vr_ligation.md) and [audit](../docs/audits/vr_ligation_20260928.md)
for the retained acquisition failure/retry and human/Expanded/large-design limits.

## Selected-end trigger resizing (2026-09-28)

Selected end arrows now accept either controller's trigger grab: outward extends,
inward shortens, release saves through the desktop strand-end-resize API. Shared
collision/terminal limits and whole-bp snapping apply to all selected arrows;
each release is independently undoable. Grips still move the scene and cancel
an active end drag. Versioned handles reject changed targets/designs.
Debug → VR Tours & Tests → Tools · Authoring → **Resize selected ends** runs an
isolated demo or all four motion profiles. Final campaign passed +12/−6 bp,
scene refresh, projected stereo/mirror pixels, negative control and Undo for all
profiles. Evidence: `.development-artifacts/vr-end-resize/42939ae168/`.
See [workflow](../docs/vr_end_resize.md) and [audit](../docs/audits/vr_end_resize_20260928.md)
for retained failures and the remaining human/Expanded/multi-end validation scope.

## Mission and current state

VR recovery starts with [the restoration guardrails](feedback_vr_restore_proven_path.md)
and [the workstation fix record](project_steamvr_drm_lease_fix.md). On 2026-09-08 the
user confirmed the existing physical left-eye mirror displaying `24hb_0xT` worked
after restoring direct mode/GPU selection and using existing dummy framing. Do not
recreate that method; this confirmation does not close controller/editing gates.

Make NADOC's native VR view a faithful, comfortable counterpart to the desktop application without creating a second geometry, selection, or job model. As redirected on 2026-08-20, the active implementation priority is now complete in-headset **Extrude** and **Move/Rotate** UI/UX; Twist/Bend and simulation-result expansion remain secondary until those two workflows have safe Confirm/Cancel/Undo transactions and pass their physical gates.

Current integration branch: `master`; optimization branch integrated in `7c235bb4`. The older native navigation baseline was developed on `feature/native-vr-navigation`.

Shipped baseline:

- `87ba1698` — native OpenXR viewer fallback.
- `dcc9eb4e` — molecular inspection controls and Steam dashboard access.
- `93da06b1` — self-shadowing and a more faithful Full representation.
- `44353007` — faithful overhang half-cylinders and extension markers.
- Current VR supports headset/controllers, grab and two-hand scale, recenter, in-VR representation/color menus, near inspection, and SteamVR desktop access.

## Representation switching benchmark (2026-09-27)

Debug → VR Tours & Tests → Right sidebar → Visualization demo (current open design)
runs the maintained `tools.vr_workflows.representation_tour` workflow. The nested
Debug menu directly launches a private snapshot of the active document, including
unsaved edits; CLI defaults to workspace/24hb_0xT.nadoc. It exports all eleven desktop representation choices (Beads and VDW share source geometry),
and exercises all 110 directed transitions with physical OpenXR and ScryWrite.
Its private style responder isolates native renderer latency from browser polling.
Visualization tours now reuse byte-verified immutable exports across resets via
`tools/vr_workflows/snapshot_cache.py`, capped at two entries / 2 GiB under
`.development-artifacts/vr-scene-cache`. Keys cover full design bytes, backend
exporter/geometry/template files, workflow exporter and uv.lock; edits invalidate.
`--no-cache` provides an explicit cold measurement. The earlier four-representation 24hb baseline was
42.93 s cold versus 11.09 s warm to live readiness (export 32.54 s vs 0.317 s).
That baseline loaded in roughly 10.6 s; the complete eleven-style catalog includes a much larger surface mesh. See `docs/audits/vr_all_representations_20260927.md` for current measurements.
The tour waits for tracked-eye placement, closes the left sidebar and moves the
right sidebar 0.35 m along its own horizontal axis using the real grip path.
An enlarged isometric view and submitted-eye pixel checks require an unclipped
design separate from the menu before and throughout the switches.

`representation_buffers.hpp` caches GPU instance buffers for unchanged static
styles; one color per representation, prepared before interactive rendering.
Natural ownership indexes are retained so object IDs remain
correct without rebuilding large hash maps on every style change. Highlighted,
transformed and trajectory geometry bypasses the static GPU cache;
baked changes clear caches. See `docs/audits/vr_representation_switching_20260927.md`
for timings, validation and remaining scope limits.

Complete representation validation: all 440 directed switches passed across the
four controller profiles; the final color cycle passed 22 menu-pixel checks and
actual desktop correspondence 1.0. Unsupported color choices use the desktop
support table and remain gray. The new **Representation colors** Debug entry runs
that shorter cycle on the current design. Current 24hb export is 1.62 GB, 80.48 s
cold, with 23.63 s native readiness; cached checksum preparation varies from
0.70 s warm to 16.21 s on the Archive drive after a long tour. See the audit above;
the older four-style startup timings are not the complete-catalog timings.

## Controller Dimensions (2026-09-27)

`dimensions.hpp` owns model-space measurements;
`dimension_panel.hpp` owns focused panel/restore and input arbitration. Dimensions
or Measure in right Properties hides both sidebars. Each trigger pins/recalls its
controller tip; new/exit freezes the old line. Model grip movement/resizing carries
measurements, preserves nm, and pins live endpoints. Eye/eye-off and X match the
desktop entry controls. Commands stay fixed above five scrolling entries, with
new-entry auto-scroll; menu-button or main Dimensions-button restores both menus.
Use `just vr-menu-tour --dimension-checks --validate` for physical-runtime synthetic
input and stereo/desktop evidence. See `docs/audits/vr_dimensions_20260927.md`.
Measurements persist through the document-bound native journal and appear in the desktop Dimensions list. Saved document measurements import at VR launch. Human through-lens validation remains separate from synthetic checks.

## Desktop-mapped sidebars (2026-09-27)

Desktop verification now samples X11 concurrently with native capture encoding,
retaining per-sample scores without pausing XR rendering or relaxing the 95%
threshold. A desktop mismatch keeps the default tour open for review and reports
failure; `--exit` still fails immediately. See `docs/audits/vr_desktop_capture_20260927.md`.

Left/right controller menu buttons independently open their matching desktop
sidebar; both can remain open. Outer vertical tabs preserve desktop ordering,
labels and dark/blue styling. Tools is appended on the right; the right-trackpad
shortcut is retained. Unsupported controls are gray and consume clicks. Existing
native representations/colors, recenter, tools, jobs and trajectory panels remain
connected through thin adapters. Tool and trajectory availability is contextual.

`sidebar_menu.hpp` owns layout/state and `sidebar_runtime.hpp` owns placement,
rendering and input. `frontend/scripts/generate-vr-sidebar-catalog.mjs` generates
851 rows/options in `sidebar_catalog.json` and its native header from the desktop
DOM plus source-linked dynamic control templates. Check drift with
`just vr-menu-catalog-check`. Detailed usage: [VR sidebar menus](../docs/vr_sidebar_menus.md).
`just vr-menu-tour` runs a visible isolated ScryWrite tour; `--validate --hold 0
--exit` covers all pages with all four unchanged human-motion profiles. It keeps
stereo/pixel evidence and checks the actual owned desktop mirror. Headset comfort
still requires physical human review. Evidence lives under
`.development-artifacts/vr-sidebar/`; failed iterations are retained. Final full
tour: all four presets passed 113 pages / 851 controls each; imprecise fast and
deliberate profiles required 43 and 41 retries respectively, all successful on
the second attempt. Native 37/37 and focused Python 8/8 passed. See the
[audit](../docs/audits/vr_sidebars_20260927.md).

## Grippable menu frames (2026-09-27)

Sidebars now reserve wide outer rails with corner/side grip marks, proximity and
move/resize colors plus status text, and acquisition haptics. Shared MenuPlacement
keeps the 75 mm physical near-grip tolerance; sidebar targeting chooses the nearest
edge and retains grip ownership. Capture metadata exports frame targets/state and
panel position/scale. `just vr-menu-tour --grip-checks --validate` exercises both
menus, model isolation and pixel feedback. Evidence: `.development-artifacts/vr-grip-frame/`.
Detailed menu/lattice outlines share the frame styling.

## Collapsible VR cards (2026-09-27)

The sidebar catalog now includes desktop card titles and ancestry, including
nested simulation cards and details. Native sidebars toggle sections via either
pointer/trigger or touchpad focus/trigger, keep independent session state, hide
collapsed descendants from input/export/rendering and recalculate scroll ranges.
Cards start expanded; toggling retains the title on the current visible page.
The existing focus tour now checks both input paths for both hands. Evidence:
`.development-artifacts/vr-cards/`; see `docs/vr_sidebar_menus.md`.

## UI style and trackpad focus (2026-09-27)

Sidebar buttons now have rounded fills/outlines, desktop muted borders and subtle
blue action / red Close accents. Scroll up/down buttons are replaced by a vertical
scrollbar, on the left of left-menu content and right of right-menu content.
With rail focus, pad up/down pages while retaining focus; left/right
exits to adjacent controls. Pointer trigger positioning also scrolls. Tests and
live evidence are in `.development-artifacts/vr-scrollbar/`.

`ui_style.hpp` centralizes native sidebar colors/focus/press tokens;
`menu_focus.hpp` owns input arbitration. Per-controller trackpad clicks navigate
its open sidebar or sidebar tool panel. Sidebar up/down stays in its column
and clamps at both ends (including unavailable controls); left/right moves
spatially between tabs, scrollbar, and content, mirrored on the left hand.
Tab selection requires trigger. Initial focus uses the pointed-at control or
the active tab. Detailed lists also clamp rather than wrap. Trigger activates; center
click explicitly restores pointing. A ray must leave its initial resting target
and dwell on one target for 450 ms to restore pointing automatically. Held
triggers suppress handoff. Gray controls remain inert. The radial Tools shortcut
now applies when the right menu is closed, as approved by the user. Physical
trackpad touch scrolling is suppressed while navigation focus is active.

ScryWrite exports mode/focus and accepts validated `trackpad_axis` input before
ordinary click events. `just vr-menu-tour --focus-checks --validate --hold 0
--exit` exercises both hands and pointer handoff with all four motion profiles.
Evidence: `.development-artifacts/vr-ui-focus/`; style research and asset/license
shortlist: [VR UI standard](../docs/vr_ui_style.md). No third-party assets bundled.
Final focus checks passed all four profiles (one extra reach per pointer
handoff); 37 native, 20 live-bridge and 3 pixel tests passed. The actual desktop
comparison passed at 99.04%. See [focus audit](../docs/audits/vr_ui_focus_20260927.md).
Headset comfort/haptic strength remains on the manual validation debt list.

## Binding invariants

VR loading optimization (2026-09-27): export-local bounded caches now reuse
selection tokens and per-base atomistic ownership; validated atom base keys are
reused at bond endpoints. Synthetic 6k/30k-atom serialization is 1.92–1.94× faster
with exact wire/manifest parity. Both natural and expanded outputs of the real
1,740-atom two-helix fixture are byte-identical and pass native gzip validation.
77 focused VR tests pass; FAST has 9,257 passes and one unchanged scalar/array
geometry exact-equality failure. These are export timings, not headset startup
or FPS measurements. See [loading review](../docs/audits/vr_loading_20260927.md)
for measurements, incoming optimization review, and larger transport candidates.

Atomistic shadow parity (2026-09-27): Ball-and-Stick and Stick now cast and
receive the same 2048² soft self-shadows as Full; the representation-specific
shadow bypass was removed. Native build and all 36 CTest checks pass with the
system linker. SteamVR was not running during verification, so rendered shadow
appearance and dense-scene headset frame timing remain unverified.

2026-09-29 correction: the atomistic color pass still used an unlit GL_LINES
branch despite the earlier shadow-pass fix. It now uses Full's lit cylinder
renderer. A real GL removed-occluder control proves cast shadows (36 receiver
pixels); the browser/ScryWrite tour captures visible Stick/Ball & Stick in both
eyes. Sidebar pad navigation now reveals one logical row with 200 ms easing and
ancestry indentation. See [shadow/scroll audit](../docs/audits/vr_shadow_scroll_20260929.md).

1. Desktop geometry, topology, job data, and visualization state remain authoritative. VR is a projection and intent source, never a competing model.
2. VR selection emits normalized intents through the canonical selection controller; it does not become a second state writer. Assembly selection remains an explicit boundary.
3. DNA polarity and topology follow `REFERENCE_DNA_TOPOLOGY.md`. Ask before encoding an ambiguous handedness, strand order, loop/skip, crossover, or spatial relation.
4. Keep the composition root thin. Cohesive VR logic belongs in testable modules, not `main.js` or route handlers.
5. Never mutate a shared live server merely to verify behavior. Use pure/unit tests, isolated fixtures, or read-only inspection.
6. A visual change needs both a numeric/snapshot oracle and an actual rendered-image or headset check. A status label is not visual verification.
7. Each phase ends in a narrow, reversible checkpoint commit. Stage only phase-owned files in the shared worktree; never stash, reset, restore, or sweep up unrelated edits.
8. Preserve user scale and spatial context across representation changes. Display element sizes must be derived from model-space geometry and one world transform, never camera distance or FOV visibility.

## Phase-boundary loop

At every phase boundary:

1. Record shipped behavior, evidence, known debt, and unresolved questions here; move obsolete history to `project_native_vr_archive.md` only when this head approaches 200 lines.
2. Re-evaluate the complete headset workflow for discoverability, reach, visual legibility, comfort, error recovery, dominant-hand assumptions, and desktop escape hatches.
3. Research or refresh appropriate fidelity, interaction, comfort, and performance metrics from primary/official sources; revise thresholds when evidence warrants it.
4. Update later phases from what was learned, run proportionate automated checks, and record any manual headset validation still owed.
5. Make a clean checkpoint commit after review. Push checkpoints that are useful for remote recovery or user testing.

## Phase ledger

| Phase | Scope | Exit checkpoint | State |
|---|---|---|---|
| 0 | Durable plan, source inventory, validation metrics, fixture strategy | Memory lint; inventory and first acceptance matrix recorded | Complete |
| 1 | Exact static visual fidelity: overhangs, crossovers, forced ligations, extra bases, extensions, same-helix domain gaps, ends/markers/arcs | Primitive/topology parity tests plus headset visual check | Manual gate |
| 2 | Scene-projection contract and representative VR regression fixtures | Stable-ID scene snapshots, tolerance tests, failure diagnostics | Complete |
| 3 | Expanded Quick View controller shortcut | Superseded: right trackpad now owns radial Tools; no quick-expand binding | Superseded |
| 4 | VR picking and selection intents from cluster through smallest supported element | Canonical selection matrix passes in desktop and VR | Manual gate |
| 5A | Complete Move/Rotate UI/UX: exact previews, Confirm/Cancel, transaction-bound one-step Undo, recovery | Cluster/Base/End/Domain/Strand workflows pass transaction and headset gates | Automated gate complete — physical gate required |
| 5B | Complete exact-End Extrude UI/UX: settings, preview, revalidation, Confirm/Cancel, one-step Undo | One-cell continuation workflow passes safety, fidelity, and headset gates | Queued behind 5A |
| 5C | Twist/Bend editing transactions | Safe preview/commit/undo with plane-pair fidelity | Deferred by user redirect |
| 6 | Unified job-list shell and simulation-result navigation in VR | Job identity/status/action parity with desktop | Active (read-only live-status foundation) |
| 7 | Every simulation engine's visualization options and time/result controls | Engine-by-option parity matrix and playback checks pass | Queued |
| 8 | UX polish, accessibility, comfort, performance, resilience | Sustained task tests and headset regression checklist pass | Queued |

## Provisional validation contract

Ratify thresholds during Phase 0 research; do not silently turn provisional numbers into science gates.

- Geometry fidelity: primitive count/type/visibility by stable design identity; topology-edge parity; position RMS and maximum error in nm; orientation angular error; dimension/scale error; negative-space checks for intentional gaps.
- Styling fidelity: representation/color parity and, where screenshots are deterministic, perceptual image difference. Lighting may differ stereoscopically but must not obscure topology.
- Interaction: selection hit/miss and false-positive rates; task completion time; accidental activation, re-grab, cancel, and undo counts; menu acquisition time; controller travel/reach.
- Comfort/performance: target the active headset refresh rate (original Vive normally 90 Hz); record application CPU/GPU frame-time p50/p95/p99, missed frames/reprojection, long-frame bursts, and scale/pose stability. The 90 Hz frame interval is 11.11 ms, but application budgets must leave compositor margin.
- Manual comfort: short symptom rating before/after demanding tasks, with explicit stop criteria for eyestrain, nausea, disorientation, or loss of balance. Never optimize comfort by merely blocking close inspection.
- Simulation UX: job/state mapping completeness; engine-option parity; frame/time identity; seek latency; playback stalls; overlay correctness; preserved user context when switching results.

## Archived foundations

Detailed Phase 0–4 inventory, acceptance reasoning, and scene-contract lineage moved to `project_native_vr_archive.md`. The active invariants, phase states, manual gates, and unresolved questions remain here.

Radial-tools / Extrude-interface slice (2026-08-21): the right trackpad no longer toggles Expanded Quick View. Historical implementation (superseded by the 2026-10-05 thumb wheel): holding it snapped a world-fixed, depth-extruded four-sector radial menu around the right Selection Volume; its pose includes the same sign of backward X tilt as the tablet, now exactly 45°. Controller motion produces hover/haptics and release activates Extrude, Twist, Bend, or Move/Rotate, while release in the dead zone cancels. Extrude opens an already-docked settings tablet and a separate docked lattice tablet; both reuse the established one-border-grip move and two-border-grip uniform resize contract. Private End feedback v4 carries the validated desktop lattice type and exact footprint cell, so the picker centers on the real cell without native geometry inference; v1–v3 remain parseable. VR now duplicates the measured desktop/caDNAno formulas exactly: HC `x=col·1.125√3`, `y=row·3.375 + (odd(row+col)?1.125:0)` nm, Square pitch `2.25 nm`; a direct test measures the representative HC neighbour at exactly `2.25 nm`. Panel-local pitch and circle radius are recalculated from immutable nm→view normalization, live scene scale, and panel scale, making every circle's world radius equal the displayed DNA radius of `1 nm`. Rendering and picking share exact circle/viewport intersection enumeration across the full grid; clipped edge arcs remain selectable only through their visible viewport portion. A held right trigger paints multiple cells, with the first cell choosing add/erase and a visited set preventing repeat toggles during one stroke. Free-cell parity and colors match desktop/cadnano (even row+column Forward blue `#29b6f6`, odd Reverse red `#ef5350`); selected cells are amber and visibly labeled `VR DRAFT`. Each selected cell now draws a live wireframe cylinder normal to the lattice plane with exact `1 nm` radius and `length_bp × 0.334 nm` depth after scene/panel scaling; cyan/amber shows outward/inward direction. The Extrude tablet's depth-bearing thumbwheel uses lattice-repeat clicks—7 bp Honeycomb, 8 bp Square. A deliberate slow release cancels sub-click travel and sticks to the last detent, while a release above the provisional flick threshold preserves signed velocity under exponential damping. Wheel capture has priority over panel buttons, lattice paint, and scene selection. A bounded, ray-highlighted `EXIT` control emits Cancel, clears the draft/configuration and wheel motion, and closes both Extrude windows. All tablet text now uses measured 5×7 glyph width and fits/shrinks within explicit bounds. This checkpoint is deliberately interface-only: lattice picks do not yet cross the authoritative extrusion footprint protocol or enable Confirm/design mutation. Pure tests cover fixed tilted radial pose, sector/depth hit testing, exact HC/Square coordinates, physical preview depth/scale, full/partial circle intersection and clipping, add/erase paint strokes, lattice detents, slow-release settling, thumbwheel direction/inertia, bounded text width, parity, reversible cell toggles, and v4 lattice metadata. Physical headset legibility, preview depth perception, acquisition, thumbwheel damping/flick threshold, panel overlap/reach, and grip-priority checks remain required.

Phase 5 transactional-shell slice: the in-headset options panel now opens a separate, explicitly **READ ONLY** Tools page with Inspect, Move/Rotate, Extrude, Twist, and Bend modes plus Preview, Confirm, Cancel, Undo, and Back. Tool actions travel in the existing bounded/sequenced private event record; the browser owns one pure reducer that requires a canonical selection and preview-before-confirm, returns typed effects, and performs no API/store mutation. Native status text says `SELECT TARGET`, `PREVIEW ONLY`, `CONFIRM STAGED`, or `NO VR COMMIT` rather than claiming an edit occurred. Confirm emits an unexecuted `commit_requested` effect until a desktop-authoritative adapter is attached; Undo is deliberately inert before the first real VR commit. Focused evidence: 30 frontend tests, 22 route tests, 4 native tests, and a production Vite build pass.

Phase 5 selection-seed slice: a pre-existing desktop primary selection now crosses launch only as its URL-safe canonical `selectionRefKey` owner token. The local route bounds the token list and passes each token as a distinct process argument; no renderer ID or shell string is accepted. The native viewer resolves the token against the immutable v8 owner-alias table for the launch representation, then preserves the alias fallback across representation changes. An absent/non-rendered owner does not create a false native selection. This removes the reselect-in-VR requirement while keeping the browser selection controller authoritative.

Phase 5 desktop executor inventory:

| Tool | Desktop target/input | Preview ownership | Commit/undo boundary | Safe first VR adapter |
|---|---|---|---|---|
| Move/Rotate | One or many canonical movable Clusters; Assembly Instance is a separate mode | `clusterGizmo` applies local renderer/pending transforms; cancel restores committed geometry | `commitPendingTransforms({log:true})`, feature edit path, or Assembly commit; several overlay/axis reconciliation steps | Cluster only; reuse pending gizmo transform and cancel path, never generalize Base/Atom to Cluster silently |
| Bend/Twist | Two global-bp planes plus optional Cluster scope; current selection is only an entry hint | `deformation_editor` creates/patches a backend preview op and ghost rendering | Delete preview before non-preview `addDeformation`; feature-edit cancel restores original params | Read-only plane/axis preview first; Cluster scopes directly, Base/End may suggest a plane only after explicit confirmation |
| Extrude | Lattice cells/plane/length or explicit continuation/blunt-end/overhang context; empty-design new bundle needs no target | Slice-plane and overhang ghost geometry are local | Four different API routes plus topology/ligate options; normal feature history/undo is backend-owned | End/continuation affordance only after target-owner and parameter UI exist; do not treat arbitrary selected elements as extrudable |

The requested “all levels from cluster to atom” is therefore a UI selection ladder, not a promise that every tool accepts every level. Cluster is the only current direct Move/Rotate edit owner; atom remains a transient visualization pick because canonical design selection stops at Base. Domain/Strand/Base/End/Bond inputs need visible promotion or tool-specific handles rather than implicit widening.

Phase 5 first visual-preview slice: canonical selection acknowledgements now include a bounded kind discriminator in feedback v3, while retaining v1/v2 parsing. Kind cannot identify a target by itself; native readiness still requires its opaque owner alias to resolve in the immutable scene. Both browser and native shells enforce Cluster-only Move/Rotate, reporting `UNSUPPORTED TARGET` for finer refs rather than widening them. Preview draws a model-following RGB translation triad around the acknowledged cluster representative; Cancel removes the triad by clearing pure preview state, including when selection changes mid-preview. No design/store/API/history mutation or transform executor exists yet, and Confirm remains staged only. The representative marker is not yet a centroid/pivot oracle, so actual dragging remains disabled until owner-wide bounds and desktop pivot rules are shared. Evidence: 26 focused frontend tests, 23 route tests/Ruff, four native tests, production Vite build, and the 7,073-test fast suite pass; 114 tests are skipped and the guarded slow suite remains deferred.

Phase 5 owner-bounds slice: the Move/Rotate locator now resolves the most-specific canonical owner token, accumulates every matching sphere, cylinder/half-cylinder, and oriented box in the active natural/Expanded representation, and positions the triad at that owner-wide bounds center. A pure bounds accumulator supplies a numeric center/radius oracle and follows the single model transform, while the displayed handle radius is reach-capped. This removes the arbitrary first-primitive locator and keeps representation fallback deterministic. Bounds center is still not the desktop cluster transform pivot; controller-driven rotation remains disabled until pivot metadata is projected explicitly rather than inferred from display geometry. Native build and all four native tests pass.

Phase 5 authoritative-handle slice: scene v9 adds bounded `K` records keyed by opaque canonical Cluster owner token in every natural/Expanded representation. Each record is the mean live backbone position of exactly the member set used by desktop `clusterMemberFilter`, which is the current visual point at which desktop pivot rebasing leaves its TransformControls dummy; it never trusts or mutates stale persisted `cluster.pivot`. The native reader normalizes handles in the same coordinate frame as geometry, requires natural/Expanded token parity, retains v4-v8 compatibility, and uses v9's handle center with owner-wide bounds only for reach-scaled triad size. The numeric contract parser compares handle position at the same `1e-6 nm` geometry tolerance. Primitives now retain the smallest containing Cluster as the direct-click default while advertising up to the bounded alias budget for larger overlapping containing Clusters, so a sidebar-selected parent Cluster can resolve without changing VR click semantics. Evidence: 33 focused Python tests/Ruff and six native validator/interaction tests pass.

Phase 5 controller-pending foundation: Move/Rotate Preview now owns a pure, reversible model-local rigid transform with an identity activation snapshot. Right-trigger-only motion accumulates controller translation/rotation across re-grabs; left trigger remains model grab and both triggers retain uniform model resize. Model scale is removed from controller displacement before accumulation, so tool motion stays in selected-model space. Changing/clearing the canonical target, changing tools, re-entering Preview, or Cancel restores the pending value exactly to identity. For honesty, only the v9 RGB handle moves in this foundation slice: design geometry, backend state, undo history, and the native scene remain unchanged until endpoint-aware transform ownership is versioned. Native tests lock scaled-model conversion, multi-grab accumulation, rigid rotation, and exact Cancel; all six native test targets pass.

Phase 5 endpoint-ownership contract: scene v10 adds bounded `T` records that bind a primitive to opaque Cluster owner tokens with independent start/end weights. Whole beads, slabs, atoms, domain cylinders, and same-owner connectors receive `(1,1)`; ordinary backbone bonds, direct crossovers/forced ligations, and atomistic bonds derive each endpoint from its actual nucleotide owner, yielding `(1,0)` or `(0,1)` at Cluster boundaries. Natural and Expanded poses must have byte-identical transform ownership, tokens must name a v9 handle in the same representation, and both Python/native readers reject unknown owners, duplicates, out-of-range weights, and pose mismatches while retaining v4-v9 compatibility. The numeric comparator reports ownership regressions independently of geometry. Crossover inserts, flexible/linker interpolation, and warning-marker motion remain explicit debt rather than receiving guessed endpoint semantics. Evidence: 35 focused Python tests/Ruff and all eight native validators pass.

Phase 5 native endpoint-preview slice: the reversible controller delta now projects through scene-v10 weights when CPU instance buffers are refreshed. Points, boxes, and atoms use their whole-owner weight; cylinders/half-cylinders transform start and end independently, so internal connections stay rigid and Cluster-boundary connections stretch only at the selected endpoint. Box axes rotate without inheriting translation. The transformed instance buffers feed both-eye color and the shared shadow pass, while ray picking and exact selected-primitive anchors apply the identical weighted pose instead of targeting stale source geometry. The v9 handle remains the rigid transform center/locator and Cancel reuploads the immutable source pose. Pure tests lock endpoint isolation and axis-vector rotation; all eight native targets pass. Performance of per-frame CPU/VBO refresh for large atomistic scenes is now an explicit headset/frame-time gate before this implementation is considered final.

Phase 5 desktop-mirror preview slice: native now converts its normalized model-local pending matrix back into the immutable snapshot's view-coordinate nanometres before publishing a separately sequenced 4×4 affine record. The localhost backend validates finiteness/affine form/bounds, conjugates it through the launch camera's stored view rotation, and returns a column-major NADOC-space matrix. The browser queues the latest matrix while the existing desktop Move/Rotate tool attaches, snapshots the pivot-rebased Cluster transform exactly once, and derives every absolute target position/quaternion from that baseline rather than integrating 50 ms polling samples. `clusterGizmo.setTransform` remains the sole live-paint/pending-transform authority. A pre-existing desktop tool is never commandeered; VR-origin preview blocks Confirm, and Cancel or native-session exit discards pending transforms and restores store-backed geometry. No backend mutation, feature-log entry, or undo entry exists yet. Evidence: 36 focused Python tests/Ruff, 52 focused frontend tests, production Vite build, and eight native targets pass.

Phase 5 interpolated-detail slice: scene-v10 weights now describe continuously attached small visuals instead of only binary rigid ownership. Each crossover-insert bead/slab/slab connector receives its geometric `(i+1)/(n+1)` parameter between the two canonical crossover endpoints, and every insert-backbone cylinder stores the independent parameters of its two adjacent sites. Flexible ssDNA bases use their ordered interior parameters while all 32 Catmull-Rom edges use exact sample parameters from 0→1. ss-linker bases and 48-segment quadratic paths similarly interpolate between the two canonical overhang anchors, including the FJC path variant that omits explicit anchor sites. Overlapping Clusters saturate at weight 1 instead of double-moving. Native linear skinning applies these weights consistently to render/pick/shadow preview; endpoint translation is exact, while large rotations remain linear-blend skinning and require the headset visual gate. ds-linker bridge/connector ownership remains queued. Focused route/contract tests and Ruff pass.

Phase 5 remaining-attachment slice: each ds-linker boundary connector now moves rigidly with its own overhang-anchor Cluster, while the recovered coarse bridge cylinder assigns its A/B endpoints independently to the two canonical anchors. This keeps both short connector arcs attached while allowing the bridge body to span a moved boundary. The amber unligated-crossover warning is midpoint-skinned at 0.5/0.5 (or weight 1 when both endpoints share a Cluster), so the diagnostic stays with the junction instead of floating at the immutable launch pose. Extension/modification markers and overhang half/full cylinders already inherit whole nucleotide/domain ownership through v10; no extra rule was needed. Focused route/contract tests and Ruff pass.

Phase 5 preview-timing slice: a bounded nearest-rank timing window now reports p50/p95/p99/max every 240 active-preview samples. One window measures the CPU transform projection plus dynamic instance-buffer uploads; a second measures the complete post-`xrWaitFrame` CPU submit interval through `xrEndFrame` and prints the runtime-provided predicted display period beside it. Output is flushed to the private VR log so it can be tailed during the headset gate. This deliberately does not claim GPU time: SteamVR's official performance overlay remains the authority for GPU/reprojection and rolling target/headroom behavior. Pure tests lock percentile calculation, invalid-sample rejection, and reset behavior; all eight native targets pass.

Phase 5 action-target snapshot slice: every native tool intent now captures the exact browser-acknowledged primitive identity, canonical selection kind, and bounded opaque owner aliases at controller-click time. The localhost reader validates target presence/kind/token consistency, and the browser resolves the snapshot against live topology plus the current canonical ref before the reducer can emit any preview/commit effect. Preview state stores a collision-safe target key; Confirm naming a different primitive/owner is rejected with `target_changed_preview_required` even when both selections share the same kind. This closes the asynchronous polling race that could otherwise apply Cluster A's preview state to Cluster B. Exact atom/bond identity remains transient session metadata beneath the stable canonical Base/Bond selection, creating an atom-level tool seam without inventing renderer-index-backed design identity. A canonical selection change during a VR-origin desktop preview cancels/restores the gizmo rather than retargeting it; the native shell also disarms Preview when feedback changes identity/aliases, and transform samples outside the narrow async-attach window are discarded so stale motion cannot seed the next session. Confirm and design/history mutation remain disabled pending the physical gate. Evidence: 26 route tests/Ruff, 69 focused frontend tests, production Vite build, native build, and all eight native targets pass before the full fast gate.

Phase 5 semantic-atom identity slice: scene v11 replaces atomistic draw indices with collision-checked `(base key, chemical atom name)` identities and names each atomistic bond by a canonicalized pair of those semantic atom references. Bond endpoint order, emitted positions, and transform-owner weights are canonicalized together, so reversing an undirected topology edge produces a numerically identical scene contract. Snapshot generation fails on a missing or duplicate chemical atom name instead of inventing an order suffix. The browser decodes the opaque URL-safe identity into transient `atomRef`/`atomRefs` metadata under the existing canonical Base/Bond owner, while the native reader remains compatible with v4-v10. This establishes rebuild-stable exact atom targeting for later tools and simulation results without yet expanding NADOC's persistent selection model. Evidence: 38 focused Python route/contract tests and Ruff, 70 focused frontend tests, native build, and all nine native validators pass; the checkpoint gates pass 7,080 fast backend tests (114 skipped), all 5,676 frontend tests, and the production Vite build. Slow simulation debt remains guarded pending a user-opened test session.

Phase 5 generalized-scope preview slice: scene v12 adds representation-independent Base, End, Domain, and Strand pivots plus Ball-and-Stick semantic Atom pivots. Every primitive can carry endpoint-specific weights for those exact scopes; canonical owner aliases imply rigid 1/1 ownership, while explicit weights preserve boundary bonds and interpolated detail. A collision-checked compact owner dictionary prevents repeating long selection tokens in `A`/`T`/`W` records; v4–v11 remain readable. Native Move/Rotate and the desktop nucleotide adapter now preview Base/End/Domain/Strand without widening to a Cluster, use an action-time exact ref even under co-selection, and restore on Cancel, selection change, or session exit. Bond/Crossover and persistent Atom editing remain refused; Confirm still has no mutation executor. Real-design size gate: the first uncompressed encoding inflated `6hb_validated.nadoc` 683.5 MB→1.148 GB and was rejected; the compact final natural pose is 666.5 MB (295,388 atoms/331,178 bonds, 51.3 s serialization), while `2hb_control.nadoc` is 3.884 MB versus the observed v11 3.805 MB (+2.1%). The large-design launch size/time is pre-existing architectural debt and a future streaming/binary-contract gate, not evidence that a 1.3 GB paired snapshot is acceptable. Evidence: 40 focused Python tests/Ruff, 23 focused frontend tests, 10 native validators, 7,082 fast backend tests (114 skipped), all 5,679 frontend tests, and the production Vite build pass; slow simulation debt remains guarded behind the user-opened test session.

Phase 5 streamed-transport slice: launch serializes natural and Expanded v12 records directly into a private mode-0600 gzip file; constant-size category/count digests preserve backend parity checks without retaining either pose or a bundled copy. The native zlib stream reader transparently accepts both gzip production snapshots and plain v4–v12 fixtures, and rejects truncated/checksum-invalid gzip. No new system package or sudo is required (`zlib.h`/`libz` were already installed). On `6hb_validated.nadoc`, gzip level 1 reduces 666.5 MB to 68.0 MB in 1.35 s; direct stream+compression peaks at 744,220 KiB versus 2,925,328 KiB for the text-return path (−74.6%), with 54.8 s versus 53.2 s natural serialization. A real `2hb_control` natural/Expanded stream is semantically identical to the legacy bundle. Evidence: 42 focused Python tests/Ruff, 12 native validators, and all 7,084 fast backend tests pass (114 skipped); the prior v12 checkpoint also covers all 5,679 frontend tests and the production Vite build. Remaining latency is dominated by atom/record construction; later work should measure launch-to-first-frame and consider representation-on-demand or a binary numeric payload rather than weakening geometry fidelity.

Phase 5 first-frame diagnostic slice: each launch records backend snapshot start/finish and viewer-process start, while native publishes the first successfully submitted stereo frame's wall-clock milestone, post-`xrWaitFrame` CPU interval, and runtime-predicted display period through the existing bounded event file. `/vr/status` derives snapshot, process-to-first-frame, and total launch latency on the same workstation; Firefox reports the metrics once per launch. This is diagnostic-only and does not imply that `xrEndFrame` submission equals photon presentation. Native timestamps retain full double precision; old event/state files default safely to “not ready,” and non-finite/inconsistent telemetry fails closed. The system toolchain is required for native linking when Miniforge shadows `/usr/bin/ld`; no sudo/package change is needed. Evidence: 30 focused route tests/Ruff, seven focused session tests, all 12 native validators, all 7,085 fast backend tests (114 skipped), all 5,680 frontend tests, and the production Vite build pass.

Phase 5 capability-matrix slice: the tool shell no longer claims that every canonical target can be previewed. A canonical definition classifies exact v12 Move/Rotate for Cluster/Base/End/Domain/Strand as `direct_preview`; End Extrude and Cluster/End Twist/Bend as `configuration_required`; every unlisted pairing as unsupported without implicit promotion. Native compiles from that definition, and a frontend parity test locks its exported policy to the same rows. Amber menu tools plus `CONFIG REQUIRED` distinguish valid targets still missing length/direction/footprint or plane-pair/amount controls; unsupported rows are dim/red and Firefox explains that no widening occurred. Preview remains unarmed for both categories, so no generic “PREVIEW ONLY” state can masquerade as visual feedback. Confirm and mutation remain disabled. Evidence: 19 focused frontend contract tests, all 12 native validators, all 5,683 frontend tests, and the production Vite build pass.

Phase 5 configuration-draft slice: valid parameterized targets now open a separate in-headset **DRAFT** page. Extrude adjusts length (bp), direction sign, strand filter, and adjacent ligation; Twist adjusts signed amount and total-degrees/degrees-per-nm units; Bend adjusts angle and cross-section direction. A fixed, sequenced localhost record binds every draft to the exact acknowledged target identity/kind/owner aliases; malformed, stale, non-finite, and transport-unbounded values fail closed in backend and browser reducers. Target changes reset settings rather than retargeting an old draft. Geometry inputs are deliberately not guessed: extrusion always says `MISSING FOOTPRINT`, deformation says `MISSING PLANES A/B`, and the panel says `DESIGN UNCHANGED`; Preview/Confirm remain disabled for these tools. Transport caps (1,000,000 bp, signed 32-bit plane indices, 1,000,000 twist magnitude) are defensive IPC limits, not scientific or operation-validation claims. Existing repository/system toolchains suffice; no sudo or package installation is needed. Evidence: 31 route tests/Ruff, 22 focused frontend configuration/session/shell tests, native build and all 12 native validators, all 7,086 fast backend tests (114 skipped), all 5,688 frontend tests, and the production Vite build pass.

Phase 5 exact-End-context slice: every rendered desktop domain-end face now retains all exact `(strand, domain, direction)` owners instead of exposing only the strand that won face deduplication. A pure resolver binds a canonical End ref to one live terminal nucleotide and exactly one such face, then returns helix/bp/disk/continuation bp, open side, plane/offset, end role, overhang identity, deformation/cluster-transform state, and any crossover or forced-ligation occupying that site. Internal same-helix gap faces remain valid; synthetic extension/linker tips, loop-copy beads, stale/nonterminal owners, mismatches, malformed rows, and duplicate faces fail closed without choosing a neighbor. The resolved context is carried only in the browser's target-bound draft state; native still says `MISSING FOOTPRINT` or `MISSING PLANES A/B`, and no visual preview/API/store/history write exists. This is the geometry seam for later read-only footprint/plane adapters, not permission to extrude through a connected or occupied end. Evidence: 30 focused End/config/shell tests, all 5,700 frontend tests, and the production Vite build pass; the preceding checkpoint covers the unchanged backend/native gates.

Phase 5 exact-End-locator slice: the browser now returns the resolved physical face center and outward continuation normal through a separate private mode-0600, atomic, bounded, sequenced feedback file. The backend rotates both into the immutable launch-view frame; native accepts only the current End draft identity/sequence, applies the scene's exact normalization, and draws a model-following ring plus outward normal. Cyan marks an ordinary open face, purple a face affected by deformation/cluster transform, and red an occupied crossover/forced-ligation site; the settings panel says `FACE LOCATED`/`OCCUPIED` while retaining `MISSING FOOTPRINT` or `MISSING PLANES A/B` and `DESIGN UNCHANGED`. The locator follows grab, rotation, and two-hand scale, but creates no footprint/plane inference, Preview, API/store mutation, or history entry. Malformed, non-finite, out-of-bounds, stale, mismatched, synthetic, ambiguous, or nearby-only candidates remain invisible. No sudo or package installation is needed. Evidence: 32 focused route tests/Ruff, 17 focused End/config frontend tests, all 7,087 fast backend tests (114 skipped), all 5,701 frontend tests, production Vite build, native build, and all 12 native validators pass.

Phase 5 single-End-footprint slice: selecting an exact physical End now explicitly supplies that helix's one canonical lattice cell—using validated `grid_pos` or the same legacy ID recovery as desktop—and never invents a cell for ungridded/non-lattice helices. Extrude settings render a wireframe helix-volume from the desktop continuation anchor using exactly `length_bp × 0.334 nm`, outward/inward direction, and the scene normalization; cyan is outward, amber inward, and red occupied. The visible domain-end ring and continuation anchor intentionally remain distinct at near ends: the ring is one disk slot outside the first bead, while desktop continuation starts at the actual axis endpoint. Domain-end endpoint metadata now follows deformation interpolation, unfold/cadnano poses, Cluster transforms, and revert so this distinction remains live rather than launch-stale. The volume follows the single model transform and two-hand scale. It is labelled `READ ONLY`; multi-cell footprint selection, collision validation, Preview, Confirm, API/store/history mutation, and deformation plane pairs remain unresolved. No sudo/package change is needed. Full checkpoint evidence: all 7,087 fast backend tests pass (114 skipped), all 5,702 frontend tests pass, the production Vite build succeeds, and the native build plus all 12 validators pass.

Phase 5 explicit-plane-pick slice: Twist and Bend settings now expose `PICK PLANE A` and `PICK PLANE B`. Choosing one closes the panel for an aim-and-right-trackpad hit without changing the canonical tool target; a separately sequenced, target/config-bound, private atomic feedback channel lets the browser resolve that exact native primitive against current topology. Only one live physical nucleotide cross-section, a semantic atom owned wholly by it, or an intra-base atom bond is accepted. Domain cylinders, ordinary bonds spanning two bps, crossovers, flexible/linker visuals, extensions, crossover-insert copies, stale helices, and out-of-range bps fail closed. On acknowledgement the panel reopens with the exact global bp, retains A/B independently, and reports reversed/equal order instead of silently sorting it. Full and Ball-and-Stick are the supported placement views for this checkpoint; Cylinders is intentionally too coarse, while Stick may only succeed on an unambiguous intra-base bond. Values remain `READ ONLY`: no bundle-wide plane quad/frame, deformation preview, feasibility request, API/store/history mutation, or Confirm exists yet. The dedicated plane channel avoids racing the existing exact-End locator response. No sudo/package change is needed; use the system linker (`PATH=/usr/bin:/bin`) when Miniforge shadows `/usr/bin/ld`. Full checkpoint evidence: all 7,089 fast backend tests pass (114 skipped), all 5,705 frontend tests pass, the production Vite build succeeds, and the native build plus all 12 validators pass.

Phase 5 authoritative-plane-frame slice: one pure numeric helper now supplies both desktop deformation meshes and VR with the same scoped bundle center, averaged contour tangent, fixed 8 nm half-extent, 7-bp curved-axis interpolation (including a short final interval), straight-axis stagger/extrapolation semantics, and fail-closed handling of malformed or cancelling axes. A Cluster target explicitly scopes the frame to that Cluster instead of borrowing incidental desktop UI state. The private plane response v2 carries the bp and complete frame through the launch camera rotation; native rejects missing/non-finite/degenerate/unbounded geometry, normalizes it with the immutable scene, and draws A as yellow and B as orange 16 nm squares with center crosses and normal ticks. Guides follow model grab/rotation/two-hand scale and are deliberately hidden in Expanded Quick View until Q-VR-013 has an authoritative coordinate projection. Repicks replace one slot; rejected repicks retain the prior configured plane. Everything remains read-only, and Preview/Confirm/API/store/history mutation remain disabled. No sudo/package change is needed. Evidence: 34 focused VR route tests and Ruff pass, all 5,708 frontend tests pass, the production Vite build succeeds, and the native build plus all 12 validators pass. The broad backend run reports 7,458 passed, 154 skipped, one expected xfail, and two isolated pre-existing `tests/test_fem_solver.py` failures; neither FEM source nor test is touched by this slice.

Phase 5 Expanded-plane-frame slice: desktop Expanded Quick View and the VR plane resolver now share one pure 2.25→5 nm per-helix lateral-offset calculation with the desktop's deterministic Z/Y/X dominant-axis tie order; the Python immutable-snapshot generator is locked to the same fixture semantics, correcting its former `argmax` X-first tie. Each accepted A/B response v3 carries a complete natural and Expanded frame, both camera-rotated, finite/bounded, normalized independently, and rejected as a unit if either is absent or degenerate. Native selects the matching pose while right grip is held, so yellow A/orange B remain centered across the visibly separated scoped helices without camera/FOV inference; extent and tangent remain fixed because Expanded is translation-only. Older v2 records still parse for diagnostics but cannot arm a new guide without the Expanded frame. The menu says `PLANES A/B EXPANDED READ ONLY`; Preview, Confirm, design/history mutation, and all other parameterized tool geometry remain disabled. The existing `1e-6 nm` projection contract remains the numeric gate—no threshold change is warranted for an exact translation. Evidence: 35 VR route tests and Ruff, all 5,711 frontend tests, the production build, native build, and all 12 validators pass. No sudo/package change is needed.

Phase 5 Expanded-End-tool-geometry slice: the exact End locator and single-cell extrusion footprint now carry an all-or-nothing natural/Expanded pose pair in private feedback v3. The browser validates the physical continuation face first, applies the same shared per-helix translation used by desktop Expanded Quick View, and never infers an offset from camera pose or rendered visibility. The backend independently validates and launch-camera-rotates both poses; native selects the matching ring, normal tick, and wireframe origin while right grip is held, and hides legacy natural-only v2 geometry rather than displaying it at a false location. The settings page reports `1 CELL EXPANDED READ ONLY`; releasing grip restores the natural pose. This is locator/preview geometry only: no extrusion, API/store/history mutation, Preview, or Confirm has been enabled. Evidence: 35 VR route tests and Ruff, all 5,711 frontend tests, the production Vite build, native build, and all 12 validators pass. No sudo/package change is needed.

Phase 5 parameterized-transaction descriptor slice: one pure, non-executing browser module now converts a target-bound VR draft into the exact existing desktop operation contract. A free, flat End maps to `addBundleContinuation` with face-relative signed length and copied one-cell footprint; occupied Ends and deformed Ends lacking an authoritative frame fail closed. Twist/Bend map to the existing `validateDeformation` preflight, transient `addDeformation` preview, mandatory preview deletion before non-preview commit, and desktop feature-log undo. End-targeted deformation now resolves the same most-specific containing Cluster as desktop picking, so its read-only A/B frames no longer silently span every helix in a multi-Cluster design. Invalid/stale targets, missing or reversed planes, and unresolved scopes produce typed refusal reasons. The descriptor has no API calls and is not wired to Preview or Confirm. Evidence: 83 focused tests, all 5,718 frontend tests, and the production Vite build pass. No backend/native/package/sudo change is needed.

Phase 5 continuation-preflight slice: `POST /design/bundle-continuation/validate` now dry-runs the exact pure continuation builder and returns `ok`/`block` plus the new/extended helices and new/affected strands, without replacing the active design or adding history. A shared 0.4-bp-stripped interval guard matches the desktop slice-plane boundary-touch rule and is also enforced by the real continuation route, so reversing an exact End extrusion through existing DNA is blocked even when a caller bypasses the UI. Duplicate cells, malformed cells, non-finite offsets, zero length, and invalid planes fail closed. The frontend client and non-executing VR descriptor name this preflight explicitly; no runtime call, Preview, Confirm, or mutation was enabled. Evidence: three new endpoint/state-invariance tests, 35 existing VR route tests, 164 CRUD/lattice/feature-log tests (two skipped), 24 focused frontend tests, Ruff, and the production Vite build pass. No package or sudo change is needed.

Phase 5 sequenced-preflight-feedback slice: every complete exact End Extrude or Cluster/End Twist/Bend draft now invokes only its existing read-only desktop validator and reports `OK`, `WARN`, `BLOCK`, or `ERROR` in the native settings page. A private mode-0600 atomic v1 record binds the verdict to the configuration sequence, mode, canonical target kind, and exact target identity; native rejects late, malformed, mismatched, oversized, or superseded responses. Any draft or target change immediately returns the display to `PREFLIGHT WAITING`, so a slow older request cannot authorize a newer configuration. Local descriptor failures are reported without making an API request. This remains status-only: parameterized Preview and Confirm are disabled, and no design, store, history, or preview mutation is reachable. Evidence: 39 focused backend route/continuation tests and Ruff, all 5,720 frontend tests, the production Vite build, the native build, and all 12 native validators pass. Native linking required clearing the inherited Miniforge `LD`/`PATH` shadow so the system linker could resolve the installed OpenXR/X11 libraries; no source, package, or sudo change was needed.

Phase 5 design-state-aware preflight-delivery slice: an active parameterized draft now revalidates whenever the desktop design or geometry object is replaced, publishing a neutral `PREFLIGHT WAITING - DESIGN CHANGED` or `GEOMETRY CHANGED` before the new verdict. A superseding browser coordinator suppresses completed work from older requests. Feedback protocol v2 adds a second monotonic sequence within each tool-configuration sequence, so backend atomic publication and native parsing both refuse out-of-order messages even when network completion order differs from logical order. The backend reports its current sequence when a reconnected Firefox page starts below an already-running native session; only the current final verdict may rebase and retry, never an older WAITING message. Six exhaustive arrival permutations converge on the newest record, and synchronous delivery failures remain contained. Parameterized Preview/Confirm remain disabled and all validators remain read-only. Evidence: 40 focused backend route/continuation tests and Ruff, all 5,725 frontend tests, the production Vite build, the native build, and all 12 native validators pass. No package or sudo change is needed; the established `.venv` is required for backend checks and the clean system-linker environment remains required for native linking.

Cross-phase periodic-seam/owner-parity slice: native launch now snapshots the desktop `End-to-End Crossovers` visibility state. Periodic-seam forced ligations remain absent by default, but when the desktop toggle is on their exact authored endpoint chord, forced-ligation owner, natural pose, and Expanded pose enter the same immutable scene contract as ordinary cross-helix ligations. Extension beads/markers/atoms and Overhang beads/domain-axis half-cylinders now also advertise their exact canonical Extension or Overhang owner token in addition to Base/Domain/Strand ownership, so a pre-existing desktop selection can seed native VR and survive representation fallback without being silently demoted. Default click promotion and all tool-capability rules are unchanged. Evidence: 50 focused route/scene-contract tests and Ruff, all 5,725 frontend tests, the production Vite build, and the previously unchanged native 12-validator gate pass. No package or sudo change is needed.

Cross-phase loop-insertion parity slice: one pure projection rule now derives missing `copy_k` identities from canonical geometry emission order independently per strand/site, matching desktop without mutating the shared payload; sequence coloring and backbone emission consume that same rule. Reverse strands thread copies from highest to lowest copy index, so their 5′→3′ backbone and sequence colors remain monotone instead of zig-zagging or collapsing every inserted nucleotide onto duplicate copy-0 identities. Natural and Expanded poses retain the same stable identities and connector order. Evidence: 58 focused route/scene-contract/projection tests and Ruff pass; the real `exp18` loop/skip fixture projects all 672 nucleotides, gives unique identities to all ten repeated sites, and preserves identical order across 3,464 natural/Expanded Full primitives. No frontend/native/package/sudo change is needed; the physical appearance remains part of the Phase 1 gate.

Cross-phase semantic base-color slice: extension geometry now carries the exact residue letter already used by atomistic generation: `ext_k` grows root→tip, so a 5′ tail reverses its stored 5′→3′ sequence while a 3′ tail does not. Desktop bead colors and letter sprites now share one semantic sequence map, while VR applies the equivalent authoritative assembly; all paths prefer explicit residue identity and exclude extensions from the independent core `Strand.sequence` walk, preventing a 5′ tail from shifting every core base color or a 3′ tail from becoming uncolored. Reverse-loop traversal agrees across paths, and the OverhangSpec fallback honors assembled sub-domain sequence overrides when a strand sequence is absent. Natural/Expanded colors and identities are locked together. Evidence: 75 focused geometry/VR tests and Ruff, all 5,727 frontend tests, and the production build pass; the real `NS_trans_fix` fixture maps and compactly transports all 334 extension sequence bases exactly. No native/package/sudo change is needed.

Phase 6 unified-job snapshot foundation: native launch now reads the active design's existing `GET /simulate/jobs` unified nodes and projects at most 64 rows into a private immutable launch file; it does not scan job directories or create a second job store. Engine-qualified job identity, parent hierarchy, canonical status, bounded progress, stale/viewable/archive flags, and a display label cross a strict URL-escaped v1 contract; duplicate identities, malformed counts/booleans/escapes, controls, and oversized fields fail closed. An unavailable fetch is distinguished from a genuinely empty design and says `JOB LIST UNAVAILABLE AT LAUNCH` instead of falsely claiming no runs; a list over the transport cap explicitly says `SHOWING 64 OF N` instead of silently omitting older rows. The options page opens a paginated five-row **SIMULATION JOBS SNAPSHOT** and a progressive-disclosure detail page with an engine-qualified canonical ID and an explicit statement that actions remain on desktop. Running status is intentionally a launch snapshot, not falsely live; Run/Stop/Delete/result-loading intents do not exist yet. The first-frame timing record now includes the job-list fetch and browser-click-to-first-frame interval, closing the earlier blind spot before the backend request. Evidence: 17 focused frontend projection/client/session tests, all 5,731 frontend tests, the production build, 40 VR route tests plus Ruff, native build, and all 12 validators pass. No package or sudo change is needed; the clean system linker path remains required when Miniforge shadows `ld`.

Phase 6 live-status checkpoint: while native VR is active, Firefox now refreshes the same document-scoped unified list every 1.5 s and publishes only successful reads; it never replaces a known list with false emptiness after a transport failure. The localhost backend owns a monotonic sequence across browser reloads and atomically replaces the private mode-0600 v2 feed, while the native reader accepts only newer complete records and retains legacy v1 launch parsing for diagnostics. An open detail page follows the same engine-qualified job identity across reorder/status updates and returns safely to the list if that job disappears. The panel says `LIVE READ ONLY` for a feed no more than five seconds old and `LINK STALE READ ONLY` thereafter, including capped lists; action controls and result loading still do not exist. Evidence: 44 VR route tests plus Ruff, 19 focused frontend projection/client/session tests, all 5,772 frontend tests, the production build, native build, and the interaction validator pass. The physical mixed-engine/status/staleness gate remains required before widening Phase 6. No package or sudo change is needed.

Tailscale-origin bridge checkpoint: native VR endpoints retain their host-local boundary but now accept both the exact HTTPS `*.ts.net` origin exported as `NADOC_PUBLIC_URL` and the exact Tailscale self-address exported as `NADOC_TAILSCALE_IP` by `start.sh --tailscale`. The self-address is required because Tailscale Serve/Vite may preserve it as the FastAPI client instead of presenting loopback; origin-less same-origin GET polling is therefore also admitted only from that declared self-address. A different tailnet client, hostname, port, scheme, URL path, non-tailnet setting, or ordinary network peer still fails closed. Paired workspace discovery does not redirect VR: the viewer always starts on the active URL's host. Evidence: focused VR route/network-boundary tests and Ruff pass, and source-level checks cover the running Compy5000 launcher's exact public URL plus `100.89.83.24` self-address. The non-reload backend must be restarted after this checkpoint before it serves the change; no live VR session was launched during automated verification.

2026-08-20 goal redirect and transaction audit: stop broadening the VR surface until Move/Rotate and exact-End Extrude are complete workflows. Existing Move/Rotate preview is exact and reversible for Cluster/Base/End/Domain/Strand, but Cluster commit currently refuses VR ownership, residue-scope persistence can create multiple undo entries, and native has no authoritative committing/succeeded/failed acknowledgement. Existing Extrude has exact End context, one-cell footprint, natural/Expanded preview geometry, configuration, and sequenced preflight, but Preview/Confirm remain disabled. Both tools therefore need one shared browser-authoritative transaction state machine with action/target identity, final-state revalidation, duplicate-confirm suppression, exact Cancel, completion feedback, and an Undo token that refuses to consume an unrelated desktop edit. Phase 5A will first add atomic residue-scope persistence and Move/Rotate commit/undo; Phase 5B will reuse the lifecycle for `addBundleContinuation`. Atom editing, multi-cell extrusion, deformed-End extrusion, Twist/Bend execution, job actions, and simulation results are explicitly out of the critical path.

Phase 5A atomic-transaction foundation: `PUT /design/nucleotide-transforms` now validates a bounded, duplicate-free exact residue set before mutation, composes every pose in one state mutation, emits one `nucleotide-transform-batch` snapshot/feature-log entry, refreshes all affected helices once, and returns an explicit VR transaction identity. This removes the former one-request/one-undo-entry-per-residue failure mode for Domain/Strand moves. The nucleotide VR mirror now keeps its hidden persistence pose aligned with the native matrix—previously it moved only renderer matrices, so a future Confirm would have saved an identity transform—and exposes an atomic commit adapter; the Cluster adapter can likewise commit its existing pending transform and capture the resulting log identity. A pure coordinator serializes duplicate Confirm attempts and permits Undo only while that exact feature entry remains the current desktop log tail. These adapters are intentionally **not yet connected to the native Confirm button**: the launch scene needs an acknowledgement-driven committed-transform layer before clearing Preview, otherwise a successful desktop commit would visually snap back in the headset. Focused evidence currently covers atomic backend undo/refusal, Base/Domain persistence, Cluster commit identity, duplicate execution, and stale-desktop Undo refusal. Next checkpoint is the native pending/succeeded/failed protocol plus retained committed transform and exact Undo rendering; only then may Move/Rotate Confirm become reachable.

Phase 5A acknowledged Move/Rotate checkpoint: Confirm is now reachable for exact Cluster/Base/End/Domain/Strand previews. Native locks tool/menu actions at `COMMITTING`; Firefox executes the corresponding Cluster or atomic residue adapter; and a new private mode-0600 monotonic feedback record returns pending/succeeded/failed/refused plus the exact feature-log entry. Out-of-order pending writes cannot replace a terminal result, terminal feedback can safely rebase after Firefox reconnect, duplicate controller Confirm is suppressed, and failed Confirm remains retryable. Native promotes a preview only after success, retains it through representation and Expanded changes, bakes an older accepted layer when a newer commit succeeds, and removes only the newest layer after an exact feature-bound Undo. Picking, anchors, owner bounds, handles, shadows, and every representation use the same committed-plus-pending geometry. If any unrelated desktop mutation changes the feature-log tail, VR refuses Undo and invalidates its token rather than consuming that desktop edit. Automated evidence: 59 focused backend tests, 71 focused frontend tool tests, all 5,782 frontend tests, production build, clean-system-linker native build, and all 12 native validators pass. No package or sudo change is needed. Physical Full/Ball-and-Stick and recovery checks remain the Phase 5A go/no-go gate before exact-End Extrude is enabled.

## Workstation VR runtime gotcha (system-local, not a NADOC feature)

**2026-09-08 saved-session regression:** the workstation was logged into GNOME Shell 46
Wayland. `wayland-info` exposed no `wp_drm_lease_device_v1`; SteamVR 2.16.7 failed
with `VRInitError_Compositor_GnomeNoDRMLeasing`. Forcing SDL/Xwayland found the
Vive's 2160×1200 Vulkan display and selected 90 Hz, but Xwayland could not acquire
it and failed with `VRInitError_Compositor_CannotDRMLeaseDisplay`. This is distinct
from the Xorg connector-ownership case below. `_assert_vr_display_lease_available()`
now fails before launching SteamVR when a Wayland session does not advertise the
lease protocol. Boot journals show the successful 2026-08-17 and 2026-08-28 runs
were automatically selected GDM X11 sessions. The 2026-08-30 reboot instead used
Wayland after the account's saved session reverted to generic `ubuntu`. Persist
`Session=ubuntu-xorg` and `SessionType=x11` through AccountsService, then sign out
and back in; no per-login gear-menu choice is required. A process-local X11
override cannot transfer DRM master ownership away from a running Mutter session.

The 2026-08-17 Codex transcript and preserved 2026-08-28 SteamVR logs settle the
architecture: the custom component was NADOC's native OpenXR companion, including
the real submitted-eye mirror, while SteamVR remained the runtime/compositor. The
physical success path recorded `CHmdWindowSDL: Using X11`, `Direct mode: enabled`,
`Headset is using direct mode`, and `Startup Complete`; no alternate runtime or
bespoke headset driver participated.

SteamVR's compositor fails `xrCreateSession` with `CannotDRMLeaseDisplay` ("Failed to acquire xlib
display" / "VR requires direct mode") whenever the Vive's `HDMI-0` connector is a live ordinary
GNOME/X desktop monitor: the Vive's own EDID does not self-report as non-desktop, so X does not
release the connector for SteamVR's DRM lease. Fix is `xrandr --output HDMI-0 --set non-desktop 1
--off`; this is **session-local** and resets on every connector re-link (headset standby/wake,
replug, logout) — a one-off manual run does not stick. `_detach_hmd_from_desktop()` in
`backend/api/routes_vr.py` now runs unconditionally at the top of `_start_steamvr()`, before the
already-running early-return — deliberately unconditional, because `_runtime_payload()`'s
"steamvr_running" only checks process names (`vrserver`/`vrcompositor` present), which says nothing
about whether direct mode actually succeeded. Gating the detach behind "not already running" (the
first version of this fix) meant it silently never ran whenever SteamVR was already up from an
earlier, possibly-failed attempt — exactly the case that matters most. Regression-tested by
`test_start_steamvr_detaches_hmd_even_when_already_ready` in `tests/test_vr_routes.py`.
`--reload-dir backend` means editing this file should hot-reload `just dev`; verify the running
uvicorn worker PID actually changed (`ps -o pid,lstart -p <pid>`) before assuming a code edit here is
live — reload has been observed to silently not fire. If `CannotDRMLeaseDisplay` recurs, check
whether the backend serving the request is actually running the current file before assuming the fix
regressed.

This is orthogonal to a **genuinely disconnected** `HDMI-0` (`xrandr --query` shows no mode line, or
the headset is idle/asleep) — no xrandr property can lease a connector with no live signal. That's a
physical link-state check, not a desktop-ownership one; don't conflate the two when triaging.

**The launch environment is a two-sided constraint.** `_build_environment()` must satisfy *both*:

1. Drop conda/Miniforge `LD_LIBRARY_PATH` — it shadows SteamVR's own bundled Qt5 and kills
   `vrmonitor` (`libQt5OpenGL.so.5: cannot open shared object file`), after which SteamVR silently
   falls back to SteamVR Home and never hands off to NADOC.
2. Keep `/usr/sbin` on `PATH` — Valve's `vrsetup.sh:40` does `command -v getcap` to verify
   `vrcompositor-launcher`'s `CAP_SYS_NICE`. A PATH of `/usr/local/bin:/usr/bin:/bin` (the first
   version of fix 1) makes that lookup fail, and `vrstartup` then raises a **blocking zenity
   dialog** ("SteamVR setup is incomplete") that stalls the launch until a human clicks it —
   observed stalling ~59 s and causing the whole VR launch to fail. The capability itself is
   already correctly set; the dialog is a false alarm with a real blocking cost.

Locked by `test_build_environment_keeps_sbin_on_path_but_drops_conda`.

**Steam must be fully restarted for an env fix to take effect.** `steam steam://rungameid/250820`
against an already-running client just hands the URL to that client, which keeps its original
environment; `vrsetup.sh` then runs under the *old* `steam-runtime-launcher-service`. Verify with
`tr '\0' '\n' < /proc/$(pgrep -f steam-runtime-launcher-service)/environ | grep ^PATH=` before
concluding an environment fix did not work.

**`SYNCHRONIZED` is not a failure.** A healthy viewer sits in `XR_SESSION_STATE_SYNCHRONIZED`
(rendering, submitting frames, holding Scene Focus) while the headset is **not being worn** — the
Vive's proximity sensor gates presentation. It advances `SYNCHRONIZED → VISIBLE → FOCUSED` only when
someone puts the headset on. A 2026-08-18 live run measured a 65 s gap that was purely the human
picking the headset up. Do not read `SYNCHRONIZED` as a hang. The real failure signature is
`STOPPING`/`EXITING` arriving seconds after start (seen when SteamVR was half-started behind the
zenity dialog); a healthy run logs **zero** of those.

Verified end-to-end on 2026-08-18 19:33–19:35 after both env fixes, with Steam fully restarted:
no getcap error, no zenity, `Acquired xlib display` → `Direct mode: enabled` → `Headset is using
direct mode` → `Startup Complete (1.72 s)`; SteamVR Home cleanly disconnected and NADOC captured
Scene Focus 60 ms after connecting, then held `SYNCHRONIZED` with zero `STOPPING`/`EXITING`.

## Metrics research decisions

- Runtime cadence is authoritative: OpenXR `xrWaitFrame` supplies `predictedDisplayTime`, `predictedDisplayPeriod`, and `shouldRender`; advance one frame from that shared predicted time and skip heavy rendering when `shouldRender` is false. Do not hard-code 90 Hz even though the original Vive normally uses it. Source: [OpenXR frame synchronization](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#frame-synchronization).
- SteamVR's official performance assessment compares rolling average frame time over 32 frames with a runtime-derived target that already includes compositor headroom, and records repeated excursions rather than failing one isolated frame. Phase gates therefore record rolling timing plus burst/p95/p99 evidence and the in-headset assessment; they do not use 11.11 ms as the only pass line. Source: [SteamVR Performance Assessment Overlay](https://partner.steamgames.com/doc/steamhardware/steamframe/compat/perf_criteria).
- First-frame CPU submission and `predictedDisplayPeriod` are app diagnostics, not GPU/compositor proof. The physical gate must also capture SteamVR compositor timing: total render GPU time, dropped/mispresented frames, reused presentations, and CPU/GPU reprojection reasons over a sustained interaction window. Source: [Valve `Compositor_FrameTiming`](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming).
- Comfort regression uses a short pre/post VR-specific symptom measure, with symptom-level stop criteria. The original SSQ remains a historical reference, but later validation found VRSQ/CSQ more psychometrically suitable for consumer HMD environments; scores are compared to this user's own baseline, not treated as a population diagnosis. Sources: [Kennedy et al. SSQ, DOI 10.1207/s15327108ijap0303_3](https://doi.org/10.1207/s15327108ijap0303_3), [Sevinc and Berkman 2020](https://doi.org/10.1016/j.apergo.2019.102958), [Josupeit 2023 environment-specific VRSQ analysis](https://doi.org/10.3389/frvir.2023.1291078).
- Interaction trials collect objective task completion, wrong-control activations, cancel/undo/re-grab counts, then the six NASA-TLX workload dimensions when a workflow is mature enough to compare. Source: [NASA Task Load Index](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/).
- Preflight freshness is a hard safety invariant, not a latency percentile: zero stale verdicts may be accepted. Automated coverage must permute every arrival order in each bounded test set, while the physical gate must force rapid config changes, desktop design/geometry replacement, and Firefox reconnection with native still running. Latency is measured separately from freshness so a fast wrong verdict cannot pass.
- Projection-space geometry copied from the same authoritative numeric records must agree within `1e-6 nm` and `1e-5°` after serialization, unless a primitive explicitly uses a documented approximation. Rendered-image and human comfort checks are separate gates and do not loosen topology parity.
- Scene-contract changes are benchmarked on both a small interactive design and a large atomistic design. Reject avoidable byte amplification; separately track serialization time, natural/paired bytes, atom/bond/record counts, native parse time, and launch-to-first-frame latency. Large paired text snapshots now require a streaming/binary follow-up even when a new version is byte-neutral.
- In-headset job rows are placed on the existing head-relative panel at 1.0 m. Their 46 mm hit height subtends about 2.63°, above Microsoft's 2° minimum comfortable target recommendation; five rows plus a separate details page implements progressive disclosure rather than dense scrolling. The physical gate still checks aim error and fatigue on the original Vive wands because another headset's nominal guidance is not proof. Sources: [Microsoft head-gaze/dwell guidance](https://learn.microsoft.com/en-us/windows/mixed-reality/design/gaze-and-dwell-head), [Microsoft interactable-object sizing](https://learn.microsoft.com/en-us/windows/mixed-reality/design/interactable-object).
- Keep the job panel in the central frame with minimal head/neck movement, avoid rapid near/far focus changes, and do not animate depth to indicate status. Apple recommends keeping spatial controls within the field of view and minimizing repetitive gestures; Microsoft recommends most immersive content at least 1 m away and explicitly testing near content for comfort. Sources: [Apple spatial accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [Microsoft mixed-reality comfort](https://learn.microsoft.com/en-us/windows/mixed-reality/design/comfort).

## Current UX review and manual debt

- Representation switching still preserves one model transform; all new primitives therefore scale through the same two-hand world transform rather than changing apparent size with view/FOV.
- The v5 half-cylinder is closed and shadow-casting. Its axial roll follows the same deterministic but visually arbitrary default as the desktop straight-domain cylinder; no new biological orientation is inferred.
- Loop-insertion checkpoint: open a design containing both +1/+2 loop insertions and a skip on FORWARD and REVERSE strands. In Full, follow each backbone through the repeated site and confirm it stays monotone in 5′→3′ order with no long zig-zag, missing bead/slab, duplicate selection, or wrong sequence color; the skip must remain an actual absence. Hold right grip and repeat in Expanded, then inspect Ball-and-Stick/Stick for the same residue and bond order. **No-go** on duplicate/missing geometry, reverse-copy order inversion, an atom/bond attached to the wrong copy, or any natural/Expanded identity mismatch.
- Base-color checkpoint: choose Base coloring on a design with distinguishable 5′ and 3′ extension sequences plus an OverhangSpec whose parent strand is unassigned and whose sub-domains override its parent sequence. In Full, compare desktop letter sprites/bead colors and VR from root→tip: 5′ extension letters/colors must appear in reverse storage order, 3′ in direct order, the adjacent core strand must retain its own first/last colors, and each overhang sub-domain must use its override. Repeat in Expanded and Ball-and-Stick against atom residue colors. **No-go** on a shifted core sequence, disagreement between desktop labels and bead colors, strand-color fallback for a known extension/overhang base, ignored sub-domain overrides, natural/Expanded disagreement, or CG/atomistic residue mismatch.
- Phase 6 live-status checkpoint: with at least seven mixed-engine runs including a parent/child pair, one running run, one stale result, one archived result, and one viewable result, open Menu → Jobs and compare every identity, hierarchy indent, status/progress, and flag against the desktop unified list. Leave one detail page open while that run advances and while list order changes; it must stay on the same engine/job identity. Pause/close Firefox for over five seconds and require `LINK STALE READ ONLY` without row loss, then reopen/reload Firefox and require `LIVE READ ONLY` plus current values without relaunching VR. Remove the selected fixture job and require a safe return to the list. Page forward/back and verify each 46 mm row is acquired reliably at the panel's 1 m placement. **No-go** on wrong/missing/duplicate identity, sequence rollback after reload, false empty data during an outage, stale status labeled live after five seconds, detail retargeting by array index, page loss, unreadable ambiguous truncation, any job/design/history mutation, or any Run/Stop/Delete/result-load implication. Record click-to-first-frame, initial job-fetch, and observed update latency. Selection mirroring, job actions, and result visualization remain later Phase 6/7 gates.
- Manual checkpoint: relaunch VR to obtain a fresh immutable snapshot, then verify (a) a same-helix empty interval stays empty in Full and Cylinders, (b) an unbound overhang reads as a half-cylinder while a direct-bound overhang reads full, (c) 1xT/2xT crossover inserts show ordered beads/slabs and no direct chord, (d) a Cy3 extension tip is a larger orange marker, (e) an unrelaxed ss linker has the same bowed path/base count in desktop Full and VR Full while Cylinders retains only its thin path, (f) each pre-relax ds linker shows two short boundary arcs that collapse after relaxation, while Cylinders reads as two two-tone bound-overhang shafts joined by one full bridge cylinder, (g) a slack flexible run bows away from the bundle with the same base count in desktop/VR Full, straightens when taut, and disappears—not breaks into rigid remnants—in Cylinders, (h) a known cycle-closing crossover has a readable amber warning centered over it in Full only, and (i) an end-to-end periodic forced ligation is absent with the desktop toggle off and appears at the exact same endpoints after relaunch with the toggle on, in both natural and Expanded views. Record mirrored/headset evidence before calling Phase 1 complete.
- Phase 3 headset checkpoint: launch a two-or-more-helix part, hold the right wand grip, and confirm helices move laterally apart while beads/slabs/atom radii remain constant; crossovers and linkers must stretch continuously rather than detach. Release must restore the exact natural pose. Repeat in all eleven representations, while holding a trigger, and at close-inspection scale. **Go** if grip never latches, model/world scale stays fixed, and there is no disorienting viewpoint jump; **no-go** on missing input, detached junctions, pose drift, or a grip/trigger conflict.
- Phase 4 hover checkpoint: with triggers released, point the right wand at a bead, slab, connector, cylinder, and atom. The cyan ray/marker should land on the visible surface, prefer the nearer primitive through overlaps, clear on empty space, and disappear during grab/resize. **No-go** on sticky markers, hits behind the wand, systematic slab misses, or frequent coarse-cylinder false positives.
- Desktop mirror checkpoint: while native VR is open and the normal desktop is visible in SteamVR Dashboard, VR hover over a nucleotide/domain/crossover should produce the same yellow desktop preview as mouse hover at the active selection level, and clear within one poll after leaving the model or exiting VR. **No-go** if canonical green selection changes, undo/history changes, Assembly selection is touched, or stale yellow preview remains.
- Selection checkpoint: at each cluster/strand/domain/end/xover/base level, aim at a valid target and fully pull the trigger. Desktop and VR should show the same canonical green selection; invalid target/level pairs must be no-ops, repeated pulls must follow desktop toggle/drill semantics, and selecting must not move/scale the model. **No-go** on duplicate selections, missed selections during a steady hover, any trigger/grip conflict, or selection surviving an Assembly boundary incorrectly.
- Selection-menu checkpoint: launch while a non-default desktop level is active and confirm that row starts green in VR. Change through all seven in-headset rows and confirm the matching desktop filter state changes exactly once without selecting or moving geometry; representation/color choices must still work. **No-go** on cramped/overlapping text, ambiguous section labels, wrong desktop level, trigger-driven model motion while using the menu, or a level reverting after the panel closes.
- Selection-feedback checkpoint: click one valid target and confirm a larger green marker replaces ambiguity around the cyan hover cue after the desktop turns green; move/scale and hold Expanded View to confirm the marker follows. Switch through all eleven representations and confirm exact Base/Bond/Crossover ownership falls back deterministically to the matching Domain, Strand, or Cluster when the finer primitive is absent. Click again to deselect, then try an invalid target at End and Crossover levels. **No-go** if green appears before canonical acknowledgement, survives deselection, attaches outside the selected canonical owner, jumps between primitives on repeated representation switches, lags noticeably, or appears for an invalid pair.
- Bond/backbone checkpoint: in Full, select a thin ordinary backbone connector through default drill and confirm the same desktop bond/cone becomes green. In Ball + Stick and Stick, an inter-residue bond should reach that same connector, an intra-residue bond should select its Base only at a compatible level, and flexible/ss-linker curve edges should choose a nearby visible base rather than an arbitrary curve segment. ds-linker connector arcs must remain no-ops. **No-go** on cross-strand jumps, reversed/wrong connector selection, a green acknowledgement for display-only arcs, or materially biased nearest-base ownership along a curve.
- Phase 4 consolidated gate: run the hover, desktop-mirror, selection, selection-menu, selection-feedback, and bond/backbone checkpoints above in one fresh VR launch. Include an unbound overhang half-cylinder: point through its missing curved side and confirm the hit lands on the visible flat face or the next actual primitive, never the absent half. Before two additional launches, select one canonical Overhang and then one Extension on desktop; each must seed the native green selection on its actual primitives and remain exact across Full/Cylinders or Full/Ball-and-Stick fallback without becoming merely Domain/Strand/Base. **Go** only if canonical green state, native green acknowledgement, active selection level, and representation fallback agree throughout without stale or duplicate intents; otherwise stop at this checkpoint and report the failing target/level/representation tuple.
- Phase 5 shell checkpoint: test Cluster, Base, End, Domain, and Strand separately. Each must report `READY`, place the triad at its authoritative v9/v12 pivot, and move only the exact selected scope; a boundary bond's selected endpoint follows while the opposite endpoint remains fixed. Right trigger manipulates the target, left trigger still grabs the model, and both triggers still resize it. Change targets mid-preview: both mirrors must restore the old target, require a fresh Preview, and restart at identity. Cancel/session exit must restore exactly. Bond, Crossover, and transient Atom targets must remain `UNSUPPORTED TARGET`, never widen. Exercise Confirm/Undo and verify staged/inert wording. Record Full and Ball-and-Stick timing plus SteamVR reprojection. **No-go** on coarse/wrong ownership, detached/interpolated detail, target retargeting, stale motion, trigger/menu conflict, pose jump, false Atom persistence, implied edit success, or any design/history mutation.
- Tool-capability menu checkpoint: with Cluster selected, Move/Rotate must be directly ready, Twist/Bend amber `CONFIG REQUIRED`, and Extrude unsupported; with End selected, Move/Rotate must be ready and all three parameterized tools amber; with Base/Domain/Strand, only Move/Rotate may be ready. Press Preview on amber and unsupported rows: neither may arm target manipulation or claim a visual preview, and Firefox must explain configuration versus exact-contract absence. **No-go** on browser/headset disagreement, an implied preview, silent selection promotion, or loss of the current selection.
- Tool-settings checkpoint: with an End target, open Extrude and verify length ±1 bp, direction toggle, Both→Scaffold→Staples cycling, and Ligate Yes/No; `MISSING FOOTPRINT` and `DESIGN UNCHANGED` must remain visible. With Cluster and then End targets, open Twist and Bend, verify 5° total/0.1°·nm⁻¹ twist steps, 1° bend steps, 5° wrapped bend-direction steps, and unit toggling; `MISSING PLANES A/B` must remain visible. Change target after adjusting each tool and confirm defaults reset. Back must preserve the current draft for the same target, while selecting Move/Rotate clears it. **No-go** on a stale-target carryover, Preview becoming armed, any desktop geometry/history change, unreadable overlap, or accidental controller/model manipulation while using settings.
- Extrude lattice/thumbwheel checkpoint: at minimum/default/maximum scene and window scales, verify Honeycomb and Square circles maintain the displayed DNA radius, fill the grid to every edge, and expose selectable clipped arcs without accepting rays in the title/footer. Hold the right trigger across several cells and require one add/erase decision for the whole stroke with no revisit toggle. At 1, 7/8, and a long length, every selected cell must show a 1-nm-radius cylinder growing by exactly `bp × 0.334 nm`, cyan outward and amber inward, including clipped edge cells. Grab the attached wheel and verify Honeycomb clicks land on 7-bp multiples and Square clicks on 8-bp multiples; slow/sub-click releases must settle without coasting, while fast flicks coast smoothly and stop without reversal. Wheel use must never activate the overlapping panel or scene. Exit during/after a stroke or coast must clear all selection, preview, and motion. **No-go** on gaps at the viewport edge, desktop/VR cell-position disagreement, wrong preview radius/depth/direction, duplicate paint toggles, stale momentum after Exit/tool change, text overflow, or wheel/menu input leakage.
- Preflight-delivery checkpoint: first settle an Extrude/Twist/Bend draft at a known verdict. While its settings page remains open, make a harmless desktop design change or Undo and require neutral `PREFLIGHT WAITING - DESIGN CHANGED`, followed by a verdict for the new state only; force a geometry-only refresh and require the analogous geometry transition. Change the same setting twice before either validation settles and verify no older WAITING/final status reappears. Finally reload Firefox while leaving native VR running, reconnect, adjust one setting, and require the current final verdict to recover despite the browser's reset feedback counter. **No-go** on a red WAITING state, retained `OK` across a desktop state replacement, an older status overwrite, a reconnect that never settles, Preview/Confirm becoming active, or any mutation caused by validation.
- Exact-End locator checkpoint: test Extrude, Twist, and Bend settings on an ordinary outer blunt end, each side of an internal same-helix domain gap, an unbound overhang tip, and a crossover/forced-ligated terminal site. A ring must sit on the exact desktop face and its line must point into the open continuation side; connected sites must be red and say `OCCUPIED`. Grab, rotate, and resize the model, then switch representation: the locator must stay attached and scale with the model. Hold right grip and require the ring to translate with the selected separated helix without changing its normal or size; releasing grip must restore the exact natural pose. Extension tips, ss/ds-linker synthetic tips, ambiguous/stale refs, and a nearby-but-different face must show no ring rather than snapping. **Go** only if all natural/Expanded positions, directions, occupancy, and restoration agree and the design/history remain unchanged; **no-go** on a wrong face, inward direction, stale locator, Expanded drift, scale change, hidden mutation, or any inferred footprint/plane.
- Single-End footprint checkpoint: on a gridded outer End, set Extrude length to 1, 7/8 (matching the design lattice period), and a visibly long value. The wireframe must begin at the actual helix endpoint, grow by the expected bp length, remain one helix diameter, and reverse amber when Direction is flipped. The outward direction must settle at `PREFLIGHT OK`; the reversed, into-body direction must settle at `PREFLIGHT BLOCK` and never become committable. Change length/direction quickly and require an immediate `PREFLIGHT WAITING`, followed only by the newest verdict—an older result must never overwrite it. At a near end, verify the start is one rise inward from the locator ring; at a far end they coincide. An occupied face must be red and an ungridded/synthetic target must show no volume. Resize/switch all representations and confirm exact attachment and uniform scale. Hold right grip and require the locator and footprint to translate together with the selected separated helix while dimensions and continuation direction remain unchanged; releasing grip must restore the exact natural pose. **No-go** on ring-origin growth at the near end, wrong length/radius/direction, an inward `OK`, a stale verdict after any setting/target change, camera/FOV-dependent size, Expanded mismatch or drift, or any design/history change.
- Deformation-plane input checkpoint: select a Cluster and then an End, open Twist and Bend, choose `PICK PLANE A`, aim at a known bp bead in Full, and fully pull the trigger; the settings page must reopen with that exact global bp while the original Cluster/End remains selected. Repeat for B in Ball-and-Stick and verify ordered A < B reads cyan. Pick B before/equal to A and require the explicit order warning with no silent swap. Aim at a Cylinders domain shaft, cross-bp backbone/atom bond, crossover insert, extension, or linker and require `NOT SET`; press the Vive System/menu button while aiming and require a clean return to settings without a pick. Repeat while Expanded is held only for semantic bp retention—there is no plane geometry gate until Q-VR-014. **No-go** on target replacement, a rounded/coarse bp, stale response, menu/trigger motion, hidden mutation, or Preview/Confirm becoming active.
- Deformation-plane frame checkpoint: after selecting A/B above, close the settings panel and compare the yellow A/orange B squares with desktop deformation planes at the same global bps. Test one straight staggered bundle and one already curved bundle, first as a Cluster target and then as an End target. Each square must remain centered across the same scoped helices, perpendicular to the local contour, visibly 16 nm wide, and attached through grab, rotation, two-hand scale, and representation changes. Hold right grip: helices must separate while both squares recenter across their separated scope, retain orientation/size, and return exactly on release; the settings page must say `PLANES A/B EXPANDED READ ONLY`. Repick only A and verify B does not move; make a rejected coarse pick and verify the prior guide remains. Complete A/B should settle at the same `PREFLIGHT OK`, `WARN`, or `BLOCK` class as desktop validation. Repick a plane or change amount rapidly and require `PREFLIGHT WAITING` followed only by the newest verdict; an old response must not reappear. **Go** only if desktop/VR natural and Expanded centers, orientation, scope, ordering, color, transform behavior, and preflight status agree with no design/history mutation; **no-go** on an averaged wrong Cluster, camera/FOV-dependent size, stale guide or verdict after target/tool/config change, Expanded jump/drift, or Preview/Confirm becoming active.
- Next slice after the manual gate: run the physical geometry, status-fidelity, stale-response, and timing gates. If they pass, design one parameterized preview/commit/one-step desktop undo transaction at a time, starting with exact End Extrude; if upload/CPU timing or SteamVR reprojection threatens the compositor budget, evaluate a GPU-weighted path first. Keep Preview/Confirm disabled until mirrored fidelity, Cancel/session-exit restoration, preflight status fidelity, and timing all pass. Phase 1, Phase 3, and Phase 4 remain pending their headset gates.

## Open questions log

- **Q-VR-001 — Right-grip semantics (implemented, validate):** hold-for-expanded/release-to-restore. Reopen only if headset testing finds grip fatigue or trigger conflict.
- **Q-VR-002 — Smallest selection identity:** atom spheres and intra-residue bonds currently resolve to canonical Base because the design selection model has no atom ref. Before atom-level editing/simulation inspection, decide whether individual atoms become canonical design selections or transient tool/result picks beneath Base; do not infer atom identity from an atomistic draw index.
- **Q-VR-003 — Edit safety:** what confirmation, preview, cancel, and undo affordances should VR tools share with desktop editing?
- **Q-VR-004 — Handedness/accessibility:** should menus and tools auto-mirror by dominant hand, expose an explicit setting, or both?
- **Q-VR-005 — Lighting:** should photo shadows remain scene-locked, offer a head-light fill, or expose a small lighting menu for inside-model inspection?
- **Q-VR-006 — Simulation defaults:** which job fields, plots, overlays, and playback controls deserve persistent wrist/panel placement versus on-demand menus?
- **Q-VR-007 — FJC transform authority:** desktop visibly stretches relaxed ssDNA representatives along the live chord, while the older Python `transform_to_chord` currently only rotates/translates despite its docstring. VR intentionally matches desktop locally; decide in a separate science-aware change whether the shared Python helper should be corrected and migrated.
- **Q-VR-008 — Warning-marker style:** the current physical triangular sign stays in model space and scales with the design; when billboard support exists, decide whether unligated warnings should instead remain head-facing like desktop sprites or keep the spatial sign for depth stability.
- **Q-VR-009 — Right trackpad:** resolved for this checkpoint as hold-to-open radial Tools with release-to-activate. Selection remains on full trigger; the old Expanded Quick View click binding is removed. Validate sector acquisition, accidental activation, and dominant-hand comfort before freezing the gesture across controller profiles.
- **Q-VR-010 — Tool manipulation binding (provisional, validate):** explicit Preview arms right-trigger-only target manipulation; left trigger remains model grab and both triggers remain model resize. Reopen if headset testing finds mode errors, two-trigger transition jumps, or dominant-hand/accessibility problems.
- **Q-VR-011 — Cross-level tool semantics (design-aware sequenced preflight implemented, validate):** Move/Rotate has exact preview coverage for Cluster/Base/End/Domain/Strand. End Extrude and Cluster/End Twist/Bend now have scalar drafts, exact read-only geometry, non-executing desktop-operation descriptors, read-only preflight APIs, and target/config/design-aware sequenced native status feedback, but remain non-previewable pending physical gates and transaction attachment. Decide whether Base/Domain/Strand should gain explicit plane/footprint handles; Bond/Crossover/Atom remain refused rather than promoted.
- **Q-VR-012 — Atom edit semantics:** v11 now supplies stable transient `(base key, atom name)` and semantic atom-bond refs beneath canonical Base/Bond, but NADOC has no persistent per-atom design selection or transform owner. Decide whether atom editing should persist those semantic refs/overrides, remain a simulation-results-only interaction, or expose residue transforms with an atom-local handle.
- **Q-VR-013 — Expanded tool geometry (read-only exact poses implemented, validate):** A/B planes, the exact End locator, and the single-cell extrusion footprint now carry exact natural/Expanded geometry using the shared 5 nm per-helix translation. Physical gates remain required, and actual deformation/extrusion execution still needs an authoritative transaction contract; do not infer that every future tool handle supports Expanded pose from these read-only projections.
- **Q-VR-014 — Deformation plane geometry (natural/Expanded read-only frames implemented, validate):** validate both poses in the physical frame checkpoint before enabling a deformation preview. Decide whether the final controller gesture should remain point-then-trackpad or become direct plane-handle dragging.
- **Q-VR-015 — Periodic seams (launch parity implemented, validate):** the desktop End-to-End Crossovers toggle is now honored when creating the immutable native snapshot. Decide whether the final VR options page should expose a live seam-arc toggle; until then changing it requires relaunch so natural/Expanded identity sets remain immutable.
- **Q-VR-016 — Job panel persistence and actions (sequenced live status implemented, validate):** decide after the physical live-status gate whether the unified job panel should be a head-recentered modal, wrist/hand-attached view, or user-placeable world panel. Do not enable Run/Stop/Delete or result loading until confirmation, stale-job refusal, focus restoration, and desktop selection mirroring have explicit contracts.
- **Q-VR-017 — Transaction acknowledgement (priority):** Confirm must remain visually pending until the desktop-authoritative mutation response identifies the committed feature-log entry. Native should then expose committed/failed/cancelled status and enable Undo only for that exact transaction; a later desktop edit must make the VR Undo token stale rather than undoing unrelated work.
- **Q-VR-018 — Move/Rotate residue granularity (priority):** Base/End/Domain/Strand previews already resolve to exact residues. Persist the whole target set atomically as one feature-log/undo entry; do not loop single-residue endpoints or silently promote them to Cluster.
- **Q-VR-019 — Extrude scope after exact End (deferred expansion):** finish one-cell continuation first. Multi-cell slice footprints, overhang extrusion, new-bundle extrusion, and deformed-End continuation need separate discoverable target/footprint contracts and must not be hidden behind the current End action.

## Immediate handoff

Implement Phase 5A's shared transaction identity and atomic residue-scope persistence, then attach Move/Rotate Confirm and exact transaction-bound Undo for Cluster/Base/End/Domain/Strand. Native must display pending/succeeded/failed state from browser feedback, suppress duplicate Confirm, keep Cancel exact before commit, and refuse stale Undo after any unrelated desktop edit. Run focused backend/frontend/native tests and then the physical Move/Rotate gate in Full and Ball-and-Stick, including selection change, Firefox reload/session exit, controller transition, large rotation, and SteamVR frame timing. Only after that passes, attach the same lifecycle to exact one-cell End Extrude: final preflight immediately before mutation, explicit footprint/direction summary, duplicate-confirm suppression, committed geometry refresh, and exact one-step Undo. Keep Twist/Bend commits, broader extrusion modes, atom persistence, job actions, and simulation results deferred until 5A/5B are complete or the user redirects again.

## Debug tour entry points (2026-09-27)

Desktop **Debug → VR Tours & Tests…** groups Overview, Left sidebar, Right sidebar,
Controls & layout, Dimensions and Authoring. Catalog lives in
`tools/vr_workflows/tour_catalog.py`; `routes_vr_tours.py` owns allowlisted isolated
subprocess launches/status/cancellation. `menu_tour --tab side:key` scopes page
coverage. Demo uses steady_fast; validation uses all four profiles. The existing
authoring demo remains terminal-only because of its special viewer/review assets.

## Hand-specific quiver tools (2026-09-28)

Scissors/Nick now belongs to the **right hand only**, including the radius-wheel
entry point. Left quiver gestures independently toggle a two-column view tablet.
Its eleven controls use the original desktop SVGs and invoke the shared desktop
view handlers: Length, Sequence, Undefined, Loop/skip, Grid, Overhang names,
Clashes, Expanded, Deform, Unfold and Cadnano 2D. The native stereo renderer reads
validated document-bound binary geometry/texture snapshots, retaining mesh
instancing; world manipulation remains native. Straight and 2D inspection layouts
suppress canonical edit picks whose positions no longer match. Panel feedback
explains desktop layout prerequisites. See `docs/vr_view_tools.md` and the
`view-tools` Debug tour (`tools.vr_workflows.view_tools_tour --validate`).


Validation for the hand-specific view-tablet checkpoint: all four profiles passed
both the complete eleven-toggle menu workflow and scissors/left-menu independence,
left-trigger non-nicking, right nick and Undo/Redo. Evidence and retained failed
attempts: `docs/audits/vr_view_tools_20260928.md`; aggregate
`.development-artifacts/vr-view-tools/view-validation.json`, plus
`scissors-final/result.json`. Through-lens comfort remains a human check.

### Share sidebar (2026-09-28)

Prior VR authoring/view tools pushed as `d9f9f252`. Left menu-button Share tab now
controls existing desktop presentation: pause/resume perspective and End all links.
No creation/start/link management in VR. `vr_share.js` delegates to existing desktop
presentation controls; `backend/api/vr_share.py` publishes doc-bound `.share` status;
native sequenced events are acknowledged, busy-gated and status expires after 3 s.
Camera source remains desktop; headset/model-grab presentation is not broadcast.
Assessment: `docs/vr_sharing.md`. Four-profile isolated mock-hosting controller tour
passed with stereo and delivered-mirror checks (`.development-artifacts/vr-share/final`).
Debug tour: Left sidebar → Share presenter controls. Internet guest transport and
through-lens comfort were not verified by this tour.

### VR presenter avatar (2026-09-28)

Share tab adds native-local default-on `Show VR model`. Head/controller metric poses
plus exact model normalization/manipulation are atomically sampled in `.avatar` at
20 Hz. `/api/vr/presenter-pose` inverts the complete source-nm-to-tracking transform;
local doc binding and 1 s feed freshness apply. Desktop `vr_avatar_publisher.js`
sends bounded latest poses at 10 Hz to existing room's host-only `/avatar` endpoint,
including paused-perspective rooms. `vr-avatar-v1` capability required. Guest SSE
state validates revision and expires after 1.5 s. No model edits or snapshot churn.
`vr_avatar.js` draws primitive headset/controllers, shoulder bar and analytic two-link
estimated arms outside `current.scene`. Reattach after prepared scene replacement;
overlay mode explicitly renders the transient figure too. Inverse scale applies to
all avatar dimensions. Research/algorithm: `docs/vr_presenter_model.md`.
Debug → VR Tours & Tests → Left sidebar → VR presenter model uses real local hosting
and guest SSE with physical profile-driven poses; no public invitation.

## VR menus in guest presentation (2026-09-28)

Show VR model now includes native menu textures and tracking-space controller/tool
lines. Both sidebar tablets, the desktop-icon view tablet, legacy/desktop panels,
selection aids, radius wheel, scissors, nick glow, ligation and resize guides use
actual XR draw data and the avatar's inverse source transform. Guest controls are
read-only. Hidden/closed/stale presence removes them. PNGs cache natively and per
SSE connection; changed images send once, positions/guides continue at pose cadence.
Room SSE now handles backpressure by coalescing the latest pending state instead
of destroying the connection on a menu-sized write. The Debug Left-sidebar
**VR menus and tools in guest view** entry runs the real-host guest pixel checks.
Details: [presenter model](../docs/vr_presenter_model.md#guest-visible-vr-controls).

## QR calibration and cube (2026-09-29)

VR Share has Calibrate QR code / Cancel and status rows. `qr_calibration.hpp`
launches an offline isolated `tools.vr_qr.worker` for the original Vive V4L2 feed,
serial-specific FTHETA calibration, OpenVR camera-to-head and standing poses.
The native OpenXR STAGE-to-LOCAL mapping registers a stable QR anchor. Source
scene origin snaps to it, preserving presentation scale/orientation and geometry.
An RGB axis marker persists; the camera panel is an edge-filtered mono preview.
The helper needs cached openvr 2.12.1401 / opencv-python-headless 4.12.0.88 in uv's
isolated Python 3.12 environment; no research-venv dependency changes. The sanitized
VR PATH omits ~/.local/bin, so the launcher explicitly resolves uv there first.
Physical target accuracy/comfort remain pending. See docs/vr_qr_calibration.md,
manual_validation_debt.md and Debug's qr-calibration tour. `generate-qr-cube.mjs`
produces a 150 mm core and six paint/two-color face plates with stable IDs; these
are separate from expiring meeting invitations. Mobile cube registration is pending.

### 2026-09-29: representation parity and real-browser coverage

- Both API client visualization publishers must use `nativeRepresentation` from
  `scene/vr_representations.js`; the former four-name list silently acknowledged
  Surface/Hull/Beads/VDW/input previews as Full and stranded their VR buttons at 99%.
- Selective native scene installation must check `incoming.available[i]` before
  replacing blocks. `loadScene` injects reference axes into Full after deriving
  availability, so nonempty geometry alone can erase resident Full/Beads.
- Cylinder exports reuse desktop `buildHelixObjects(..., 'cylinders')`, including
  default radius and saved strand/group colors. They are triangle-backed native
  geometry, like Surface/Hull. Transient desktop radius-slider changes after
  export are not synchronized by this static export bridge.
- Sidebar hover rays use the same panel intersection as input and do not require
  the trigger to be held. GL regression checks open/closed panels.
- Browser representation checks now cover every representation and require
  nonzero model IDs in both eyes for every style, in addition to 100% and correct
  acknowledged style. Let delayed display uploads settle outside measured reaches;
  do not run broad parallel suites during timing-sensitive controller playback.
  Details and retained attempts: `docs/audits/vr_representation_parity_20260929.md`.

## 24HB live follow-up (2026-10-01)

See `docs/audits/vr_move_rotate_24hb_live_20261001.md`. Full single-base drags on
24HB (6,720 nt versus generated 6HB 511 nt) complete all four profiles at GPU
p95 3.27–4.26 ms. Fresh 6HB p95 is 1.41–2.26 ms. Rare hitches occur on both
(24HB max 24.50 ms, 6HB max 66.01 ms); do not claim a strict 90 Hz guarantee.
Mixed desktop focus/rendering and additional 24HB presentation zoom are recorded.
24HB stereo/scope/commit/save pass, but Undo after save returns 404 Nothing to
undo; full authoring matrix stays failed. Fresh 6HB complete matrix passes.
Use complete `workspace/24hb_0xT.nadoc` via private `move_tour --design` copies,
not API summaries missing snapshot payloads. `--direct-activation` isolates drag
from known large-response menu replay delays; it does not validate menu acquisition.
Inactive Nick bond arrays are omitted while Move/Rotate or Bend is active in
ScryWrite; `scene_hover` exposes the actual molecular hover separately from menus.

## Feature performance guards (2026-10-01)

View Volumes now skip same-style `setStyle` calls (including restoration), skip
clipping work when no volume is active, and retain unchanged clipping-buffer
contents between eyes/frames. Do not add a general early return inside `setStyle`:
callers also use it to invalidate geometry after selection/configuration changes.
Bend/Twist cache sidebar rows by all displayed inputs/status; opening and panel
replacement invalidate the cache. Pending volume journals are rewritten only when
the immutable sequence range changes, with failed writes remaining retryable.

Evidence and reproducible benchmark script:
`.development-artifacts/vr-feature-guards-20261001/report.json` and `benchmark.py`.
24HB whole-cluster Move/Rotate with one same-style opaque volume, production
shadows and two 1852x2056 draws: worse motion p95 wall time before → after is
Full 296.80 → 7.30 ms, Stick 2261.79 → 29.18 ms, Ball & Stick 3988.16 → 25.50 ms,
VDW 2889.04 → 5.19 ms. Five warmups plus 20 samples per mode; all 16 before/after
images byte-identical. Timings exclude XR/UI/commit work. Old-path GPU query times
include CPU submission gaps and must not be called pure GPU execution time.
Generated-fixture live volume movement/resizing passed all four motion profiles
for square and hexagonal volumes. Native Bend/Twist guide rendering, menu cache
invalidation and volume journal retry/ack tests pass. This is not new live 24HB
Bend/Twist deformation timing. Different-style volume transitions and synchronous
View Tools scene/atlas refreshes can still hitch; large highlighted Stick/Ball &
Stick with a volume remain over 11.1 ms. No geometry or lighting quality reduced.

## Move/Rotate hand-role trial (2026-10-01)

While Move/Rotate is active, only the left trigger/selection sphere acquires
molecular targets. Only the right trigger can grab by pointing at selected geometry;
release still commits. The right selection sphere and radius scrolling are
suppressed, and right clicks away from selected geometry cannot clear selection. Selection
is frozen while the right hand drags. Exiting Move/Rotate restores normal selection
for both hands; scene grips and menu controls retain their existing behavior.
The native viewer binary is rebuilt for trying this mapping. Performance work was
pushed separately as `eb637ca5`; this hand-role trial remains a local change.

Move/Rotate pointing trial: removed selected-element axis/cross overlays. A green
beam connects the right hand to selected geometry when aimed, and follows the
grabbed point during manipulation. Picking uses cached selected packed instances;
owner-token parent aliases must not be mistaken for multiple selections. Pointing
padding is one degree, bounded to 2–12 mm in tracking space. The Move menu has a
Selection options card with three inline icon buttons: Base, Domain, Cluster.
Native panel/hand tests pass, including remote acquisition and pointing away.
Live generated-6HB Base, Domain, and Cluster workflows each passed. Across four
motion profiles, high-jitter acquisition can miss a tiny base. Observer-side beam
captures pass both stereo-eye pixel checks; an earlier behind-model cluster beam
capture was occluded in one eye. One observer-side steady-fast reopen assertion
failed on quaternion roundoff (~1e-16), after manipulation passed. Failed attempts
are retained in `.development-artifacts/vr-move-ray-card-20261001/report.json`.
These are rendered/injected-controller checks, not physical through-lens validation.

## Full slab registration after residue moves (2026-10-01)

VR Full export previously solved paired slab placement after persisted nucleotide
transforms. Moving a domain therefore re-seated its slabs against stationary
mates and also moved those mates' slabs. Desktop live edits keep the native
bead/slab offset. `full_slab_reference_geometry` now undoes saved residue poses
for the contact solver, then the exporter carries each solved slab/connector by
its own pose. Five-prime cube orientation follows the saved residue rotation too.
Simulation slab-frame delivery remains separate. This does not change underlying
saved geometry or the general cluster/deformation placement pipeline.

Read-only reproduction on the current `workspace/24hb_0xT.nadoc` (7 saved residue
poses): old moved primitive error up to 0.62956 nm; stationary partner error up to
1.13316 nm. Fixed: all 20,160 bead/slab/connector primitives agree with rigid
reference within 6.7e-6 nm (text export precision), stationary primitives exact.
77 backend checks and native packed-preview parity pass. Native close-up renders
show the corrected bead contacts. Evidence, failed framing attempt, scripts and
scope: `.development-artifacts/vr-slab-rigid-20261001/report.json`. No new physical
headset/motion-profile validation was run for this snapshot-only correction.

## Part origin and room-centered startup (2026-10-01)

Previous move controls and slab fixes pushed as `a360c112`. The following origin
correction remains local: native axes previously started at hard-coded normalized
(-.28,-.28,-1.3), independent of the part. NADOCVR v16 now carries O metadata
(source X/Y/Z directions after desktop-camera rotation); native axes use source
zero and 4 nm lengths matching desktop AxesHelper(4). Geometry normalization and
coordinate conversions stay fixed. Legacy snapshots assume identity source axes.
Normal startup anchors source zero 1.1 m above the calibrated OpenXR STAGE center,
with horizontal head yaw and existing 2x presentation scale. Stable tracked poses
and completed initial geometry are required. Without STAGE, LOCAL X/Z zero is
used at head Y minus .35 m. Explicit inspector in-view placement and QR anchors
still override this default; manual Fit/Recenter remains head-relative.
76 backend tests and native origin/preview checks pass. Read-only live 24HB launch
placed the origin within .004 mm of the expected stage target. First capture was
out of view with headset set aside; user repositioned it toward center and the
second submitted stereo capture shows the model. Diagnostic viewer was left open
for inspection. Evidence: `.development-artifacts/vr-origin-20261001/report.json`.
