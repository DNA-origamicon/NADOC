# NADOC native VR viewer

This small OpenXR/OpenGL companion is the Linux fallback for browsers that do
not expose immersive WebXR. NADOC launches it through the local backend with a
read-only snapshot of the active design. It renders through the active OpenXR
runtime (SteamVR on the current Vive workstation).

Build:

```bash
env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS \
  CC=/usr/bin/gcc CXX=/usr/bin/g++ \
  cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build native/vr_viewer/build
```

Validate a snapshot without starting OpenXR:

```bash
native/vr_viewer/build/nadoc-vr-viewer --validate scene.nadocvr
```

Run the headless ScryWrite troubleshooting proof of concept:

```bash
just test-scrywrite
```

ScryWrite drives the viewer's real interaction state and rigid-preview core from a
versioned deterministic script, emits a JSON trace, and is wrapped by a Playwright
fixture. The example scenario is
`examples/scrywrite_move_rotate.scry`; the architecture and automation limits are
recorded in [`docs/scrywrite_architecture.md`](../../docs/scrywrite_architecture.md).
This proof does not start OpenXR, validate scene identities, render stereo images, or
perform a browser-authoritative design mutation.

To observe a ScryWrite replay inside the real headset, launch the viewer with a scene
and the explicit Witness Mode script:

```bash
just scrywrite-witness
# Or: just scrywrite-witness scene.nadocvr path/to/test.scry
```

Your physical headset remains the free observer camera. Cyan/orange ghost controllers
perform the script, a cyan scripted-head frustum marks its view, and a head-following
monitor shows the actor-eye render. A missing menu/control or hover mismatch pauses
with a red failure marker. Press the physical left menu button to pause/resume or the
physical right menu button to single-step while paused. Witness Mode refuses an event
output path and blocks haptics and X11 clicks, so the visual replay cannot publish a
design mutation. Check a script without starting OpenXR using
`nadoc-vr-viewer --validate-witness <script>`.

For the checked menu-debugging timeline, run `just scrywrite-menu-trace`. It opens the
real Options menu, captures open/hover/navigation/activation states from the
deterministic 960×540 actor-eye framebuffer, compares tolerant 32×18 luminance
fingerprints, exits when the witness passes, and has Playwright attach each PNG and
its semantic JSON state. `expect layout valid` checks renderer-native text/control
bounds; `expect framing valid`, `display submitted`, `tracking tracked`, and
`overlay visible` keep a clipped panel or spectator fallback from becoming a false
visual pass. `snapshot <safe_name>` requires `--witness-captures <directory>`;
`--witness-visual-expect <directory>` enables baseline comparison and
`--witness-exit on` makes live diagnostic jobs bounded.

The GLFW companion window can mirror the physical HMD eye with `--mirror-eye left`
or `--mirror-eye right`; `off` disables it. Normal NADOC **View in VR** launches
default to the left eye. `SUBMITTED` is the actual undistorted app eye copied before
OpenXR release. If the runtime suppresses headset rendering, `SPECTATOR FALLBACK`
rerenders from the latest located eye pose/FOV so an unworn dummy remains observable.
The resizable window preserves aspect with black bars. Its title reports source,
frame/motion counters, tracking and pose; a lower-left colored square pulses as a
liveness heartbeat. It is read-only and never includes runtime lens warp/overlays.
For the checked fixture launch use `just vr-hmd-mirror`; see
`docs/scrywrite_desktop_mirror.md` for the dummy validation.

For reproducible view-relative framing, use `just scrywrite-frame`. Its first three
optional arguments are orientation, target view, and mirrored eye; for example,
`just scrywrite-frame top` or `just scrywrite-frame front right right`. It waits for a
stable tracked window and records every placement parameter in mirror JSONL. See
`docs/scrywrite_scene_framing.md` for the compact workflow and bounded claims.

`just vr-hmd-mirror` defaults `PLACE=on`, which centers and presentation-orients the
fixture after 15 consecutive fully tracked, non-discontinuous HMD poses at a 1.30 m
viewing distance and 2× scale. Set
`PLACE=off` to preserve the scene's world placement. Direct launches use
`--place-scene-in-view off|on`; the default is `off`.

The mirror samples its viewport at 64×64 every 30 frames. Same-pass stencil tags
separate visible design, reference-grid, and overlay samples; the title reports
`DESIGN+GRID`, `DESIGN ONLY`, `GRID ONLY`, or `NO TAGS`. This is coarse category
presence, not expected-object correctness. `PX BLACK` flags nearly
empty color, `PX STABLE` permits stationary identical output, `PX FROZEN?` flags
invariant pixels only when tracked pose moved, and `PX CHANGING` reports only
material pixel change—not scene correctness. Persist the application-side correlation trace with
`--mirror-diagnostics <trace.jsonl>`; `just vr-hmd-mirror` defaults to
`/tmp/scrywrite_mirror_diagnostics.jsonl`. The trace includes local frame, wall time,
OpenXR predicted display time, source, color statistics, class counts/fractions, and
pose delta—not a compositor acknowledgement.

Add `--reference-grid room` when scene placement or headset direction is uncertain.
It draws a 5 m cage at OpenXR LOCAL origin with 0.5 m spacing and colored cardinal
faces (+X red/−X cyan, +Y green/−Y magenta, +Z blue/−Z yellow). It is a depth-free
diagnostic guide, never design geometry. `off` disables it.

When a headset is unavailable, export the scripted actor's POV, a top-down pose map,
and strict projection evidence from the canonical asymmetric perspective fixture:

```bash
just scrywrite-evidence
# Or override SCENE=... SCRIPT=... EXPECT=... OUTPUT=...
```

The retained example is in
[`docs/generated/scrywrite`](../../docs/generated/scrywrite/README.md). This export
uses the same scene normalization and scripted pose, but is a deterministic software
projection rather than a capture of the live OpenGL stereo renderer.
The default fixture is derived from `workspace/Chiral_test.nadoc`. The exporter says
`not_evaluated` without `--expect`; a checked threshold failure retains artifacts
and exits nonzero.

Ubuntu development packages:

```bash
sudo apt install build-essential cmake ninja-build libopenxr-dev \
  libopenxr-loader1 libglfw3-dev libglm-dev libgl1-mesa-dev libx11-dev \
  openxr-layer-corevalidation openxr-layer-apidump
```

`scripts/vr_diagnostics.sh check` reports the locally usable runtime, explicit API
layers, Nsight Systems, and RenderDoc. Its `validation` and `api-dump` modes enable
one explicit OpenXR layer around an arbitrary viewer command while removing Conda's
conflicting library path. `nsys` records OpenGL/OS-runtime activity; `renderdoc`
starts a frame capture when `renderdoccmd` is installed and otherwise fails clearly.
Set `NADOC_XR_DIAGNOSTIC_OUTPUT` to choose the log/capture path. API dumps are written
only to the log because even the bounded 284-frame menu trace is roughly 4 MB.

The backend selects SteamVR's `steamxr_linux64.json` automatically when it
launches the viewer. Help → Open SteamVR / Desktop starts SteamVR independently,
so its Dashboard remains available before, during, and after a NADOC VR session.
NADOC also provides its own X11 desktop surface in the controller tablet because
SteamVR's Linux Desktop overlay can be present but blank. Open the VR menu and
select Desktop; aim with either controller, fully pull the trigger to click, and
swipe vertically on either trackpad to scroll. The Desktop panel opens at twice
the regular tablet area and uses the live X11 desktop aspect ratio. Grip anywhere
within 7.5 cm of its surface to grab it directly, or hold both grips within 7.5 cm
of its border and change the controller spacing to resize it uniformly. The same
Dock/Follow and Size controls also apply to the desktop tablet.
MD/FEM visualization overlays are also mirrored into the native model while VR is
running. Selecting MD Display moves the corresponding VR bases and backbone geometry;
selecting a Flex Map applies both its mean positions and scalar colors. Clearing the
desktop overlay restores the launch geometry and normal VR coloring. This is a compact
per-base feed rather than a repeated full-scene rebuild, so the OpenXR session and the
user's scene placement remain intact.

For the full-origami atomistic regression, `just vr-atomistic-system` checks host
headroom, `just vr-atomistic-capture` extracts the already-downloaded latest
`24hb_2xT` MD frame, and
`just scrywrite-atomistic-24hb /tmp/nadoc-vr-XXXXXX.nadocvr.gz` drives and asserts
Ball + Stick → Full → Ball + Stick → Stick Only → Full → Ball + Stick through the
real menu. A headset-free style
benchmark is available as
`nadoc-vr-viewer --benchmark-atomistic <scene> [visualization]`. The exact fixture,
thresholds, SteamVR timing gate, evidence semantics, and failure map are in
[`docs/scrywrite_atomistic_md.md`](../../docs/scrywrite_atomistic_md.md).
For native-to-browser interaction, the backend creates a private (`0600`), bounded
event record and passes its path directly to the viewer. A localhost-only endpoint
exposes validated, sequenced hover, Select, and selection-level intents. The browser
routes those intents through NADOC's canonical selection controller; the companion
never writes design state directly. A second private, bounded record carries only the
browser's canonical acknowledgement back to the companion.
Feedback v2 also carries up to eight opaque, specificity-ordered canonical owner
aliases. The native parser retains feedback-v1 compatibility and rejects truncated,
oversized, stale, future, or whitespace-bearing alias records.
If a canonical desktop selection already exists at launch, NADOC passes its opaque
owner alias plus a bounded kind discriminator as separate process arguments. Kind
alone cannot select anything: the viewer must resolve the alias against the immutable
scene ownership table before the green highlight or Tools readiness appears, so the
target need not be reselected in VR and an absent owner cannot become a false match.

Controls on the original HTC Vive wands:

- Hold the right trackpad to open a world-fixed radial **Tools** menu around that
  controller's Selection Volume. Its volumetric sectors tilt 45° back from the
  controller pose for a more readable wrist angle. Move the right controller until the volume enters
  one of the four depth-bearing sectors (Extrude, Twist, Bend, or Move/Rotate); the
  sector highlights and gives a light haptic tick. Release the trackpad to activate
  the highlighted tool, or release in the center/outside the ring to cancel. The old
  right-trackpad Expanded Quick View toggle is intentionally unbound.
- Each controller carries a wireframe **Selection Volume** 12 cm beyond its tip. Slide a
  thumb upward or downward on that controller's trackpad to grow or shrink the volume
  from precision-pick to area-selection size. A partial trigger pull resolves overlaps
  through the active desktop selection filter and draws an amber additive shell over
  the complete target geometry. A full pull commits up to 16 nearest distinct canonical
  targets through NADOC's selection controller. Accepted targets retain a green
  geometry-shaped glow after the trigger is released. Triggers also press menu buttons
  while the menu is open.
- Click the left trackpad to cycle the exact desktop Tab order:
  Strand, Domain, End, Crossover, Base, then Auto / Drill. Cluster remains menu-only.
- Hold either grip/squeeze button to grab, move, and rotate the structure outside a
  tool preview. A grip within 7.5 cm of a menu border grabs the panel instead; on the
  Desktop page the whole surface is a grab target. During Move/Rotate Preview, the
  right grip alone moves/rotates the pending handle while the left grip remains a
  structure grab unless it is targeting a panel.
- Hold both grips and change the distance between the controllers to resize the
  structure around their midpoint. When both controllers are within 7.5 cm of a
  menu or Desktop border, the same gesture resizes that panel instead and preserves
  its aspect ratio. A second border grip transitions an active one-hand panel grab
  directly into resizing; the captured grips cannot also transform the structure.
- Press either application-menu button to open or close the in-headset menu.
  The menu sits close to the controller that opened it, with its matching side edge
  aligned to that controller and its top tilted farther away like a large hand-held
  tablet; use either wand to point and select. Choose
  Dock to leave the panel fixed in the world, or Follow to
  attach it to the controller that selected the button. Size - and Size + resize
  the panel while preserving accurate pointing. Gripping near a border grabs and
  docks the panel at its current pose; release it to leave the panel fixed, or choose
  Follow to attach it to a controller again. The tablet is non-modal: grips,
  Selection Volumes, trackpads, and scene tools remain active while it is open.
  A trigger is routed to the menu only while its controller points at a menu control;
  otherwise it continues selecting the scene. Entering a menu control with the ray
  gives one light haptic tick; clicking it adds no further vibration. Point a wand
  and pull its trigger
  to select a representation (Cylinders,
  Full, Ball + Stick, or Stick Only), coloring (Strand, Base, Cluster, or CPK),
  selection level (Auto / Drill, Cluster, Strand, Domain, End, Crossover, or Base),
  Recenter, or Desktop. The active level is green and begins at the desktop's current
  level when VR launches.
- A full trigger pull with an empty Selection Volume clears the canonical desktop
  selection and its retained native geometry glow. Controller rays are shown only
  while they intersect the tablet panel.
- The former native Jobs/OBS status page is disabled. It was read-only and could be
  mistaken for a visualization control even though it did not affect the model. Its
  rationale and deferred contract are retained in
  `archive/simulation_jobs_menu.md`; simulation display choices stay on the interactive
  desktop tablet for now.
- Select Tools in that panel to open the Phase 5 transaction shell. It exposes
  Inspect, Move/Rotate, Extrude, Twist, and Bend plus Preview, Confirm, Cancel,
  Undo, and Back. Move/Rotate is browser-authoritative and transactional; the
  parameterized Extrude/Twist/Bend workflows remain visibly read-only until their
  individual mutation gates pass.
  Choosing Extrude from the radial menu immediately creates a world-docked settings
  window plus a separate world-docked lattice window centered on the exact
  browser-resolved cell and laid out as the design's Honeycomb or Square lattice.
  The picker uses the exact desktop/caDNAno nanometre coordinates; its circles remain
  one DNA radius (1 nm) after scene and panel scaling. Cell circles now fill the
  complete grid viewport: edge circles are clipped visually but remain ray-selectable
  wherever their visible portion intersects the window. Either window can be moved
  with one grip at its border or uniformly resized with two border grips. Hold the
  right trigger and paint across cells to add a group; begin a new stroke on a
  selected cell to erase. Each crossed cell is applied once per held stroke.
  Free-cell parity matches desktop/cadnano: Forward is blue and Reverse is red;
  selected cells are amber. A partially exposed classic thumbwheel is attached to
  the right edge of the Extrude settings window. Trigger-grab and move it vertically
  to change length in lattice-repeat detents: 7 bp for Honeycomb and 8 bp for Square.
  A slow release settles back onto the last click without coasting; release a faster
  flick to retain momentum under provisional exponential damping. Every selected
  cell previews a helix cylinder emerging normal to the lattice plane, with exact
  1-nm radius and `length × 0.334 nm` depth. Cyan is outward and amber is inward.
  Select **Exit** to emit Cancel, clear the lattice draft and thumbwheel motion, and
  close both Extrude windows. These picks and cylinders are intentionally labeled
  **VR DRAFT** and do not yet arm Confirm or a design mutation.
  Move/Rotate directly previews exact Cluster, Strand, Domain, End, and Base
  scopes. End-target Extrude and Cluster/End Twist or Bend are amber and report
  **CONFIG REQUIRED**. Selecting one opens a target-bound draft-settings page:
  Extrude exposes length, direction, strand filter, and adjacent-ligation; Twist
  exposes amount and total-degrees/degrees-per-nm units; Bend exposes angle and
  direction. The authoritative exact slice footprint and ordered deformation planes
  remain visibly **UNRESOLVED**, so these settings cannot arm Preview or change the
  design yet.
  The browser resolves an End against the live nucleotide and the desktop's
  deduplicated physical-face table, including every strand/domain owner,
  overhang identity, deformation state, and crossover/forced-ligation occupancy.
  Synthetic extension/linker tips, loop-copy beads, stale owners, and ambiguous
  faces fail closed instead of borrowing a nearby face. Changing the canonical
  target resets the draft. Other pairings report
  **UNSUPPORTED TARGET** instead
  of silently widening the edit. Preview draws an
  RGB translation triad at the exact current visual centroid used by NADOC's desktop
  gizmo; its size is derived from owner-wide bounds and stays capped for reach.
  Right-grip drags accumulate across re-grabs and Cancel returns the handle exactly
  to its activation position. Scene-v10 endpoint ownership drives the same pending
  pose through native geometry, picking, selection anchors, and shadows: internal
  primitives move rigidly while a boundary bond or crossover leaves its opposite
  endpoint fixed. The native companion also publishes the same rigid delta through
  the private event bridge. NADOC converts it from view/snapshot coordinates back to
  nanometres and mirrors it through the desktop Cluster gizmo or exact nucleotide
  transform adapter from one immutable baseline. Confirm locks the tool while the
  browser commits the exact scope as one feature-log entry. Native keeps the preview
  visible until a sequenced success/failure acknowledgement arrives, retains a
  successful transform across representation/Expanded changes, and exposes Undo
  only for that exact current feature-log tail. A later desktop edit makes the token
  stale instead of undoing unrelated work. Cancel or native session exit restores an
  uncommitted preview exactly.
  Every tool button event snapshots the exact acknowledged primitive, canonical kind,
  and bounded opaque owner aliases at controller-click time. The browser rejects a
  delayed event if that snapshot no longer names its current canonical selection, and
  Preview/Confirm must name the identical snapshot. Changing selection during a
  VR-origin desktop preview cancels and restores it instead of retargeting the gizmo;
  stale transform samples are discarded rather than queued for a later Preview.
- Cyan and orange stems and Selection Volumes identify the left and right controllers.
  They turn green during a one-hand structure grab and magenta during a two-hand
  structure resize. A panel border turns orange when it is close enough to grab and
  remains orange while that panel is moving or resizing. Partial
  trigger pulls brighten the volume and add an inflated emissive shell around the same
  Strand, Domain, End, Crossover, Base, Auto/Drill, or Cluster geometry the desktop
  filter would preview, without changing selection. After a full trigger click is
  accepted by the desktop selection controller, the shell turns green and remains on
  the selected geometry; rejected target/level combinations never produce false green.
  When a representation has no exact copy of the clicked primitive, the highlight uses
  the browser-confirmed canonical owner hierarchy (including exact End, Bond, or
  Crossover aliases where available, then Base, Domain, Strand, and Cluster), so
  switching representations does not silently lose canonical selection.
  Ordinary backbone cylinders and inter-residue atomistic bonds resolve through the
  same canonical bond ownership as desktop connector picks. Intra-residue atom bonds
  and sampled flexible/linker curve edges resolve to their owning or nearest Base;
  display-only ds-linker connector arcs remain non-selecting. Overhang half-cylinder
  picking follows its curved wall, flat face, and caps rather than an enclosing full
  capsule, so the missing half cannot steal hits from geometry behind it.
- Select Desktop in NADOC's controller menu to operate the live workstation
  desktop without leaving the scene. Its enlarged panel matches the workstation
  aspect ratio; grip its surface to move it or use both grips at its border to resize
  it. SteamVR's System-button Dashboard/Desktop remains available as a secondary path.

Close inspection is intentionally unrestricted: structures may be pulled through
the headset or enlarged around the viewer. A 2 cm rendering near plane prevents
projection singularities while allowing atom-scale interior inspection.

After the first submitted stereo frame, Firefox reports snapshot, viewer-startup,
total launch, first-frame CPU, and runtime-period timing once. During an active
Move/Rotate Preview, the companion logs bounded 240-sample timing
windows for transform projection/VBO upload and total post-`xrWaitFrame` CPU submit
time (p50/p95/p99/max plus the runtime-predicted display period). The live log path
is returned by `/api/vr/status`; on the current workstation it can also be watched
with `tail -f /tmp/nadoc-vr-$UID.log`. Use SteamVR's performance overlay alongside
these CPU numbers to capture GPU/reprojection behavior.

The native renderer uses the Photo-mode Full lighting balance: a camera-pinned
directional key, low ambient fill, and one 2048² soft self-shadow map shared by
both eyes. Full representation geometry mirrors the editor's physical display
primitives: 0.10 nm backbone beads, 0.18 nm 5′ cubes, oriented
0.30 × 0.06 × 0.70 nm base slabs, 0.025 nm slab connectors, and 0.075 nm
same-helix strand connectors.
Production snapshots are streamed into private gzip files; the viewer reads them
incrementally while retaining transparent support for plain legacy fixtures.
Scene format v12 pairs natural and Expanded Quick View poses by the URL-safe
semantic identities introduced in v6, retains v8's bounded canonical-owner aliases,
retains v9's explicit owner-keyed Cluster gizmo centers and v10 endpoint transform
ownership, and adds a compact owner dictionary plus exact Base/End/Domain/Strand
tool pivots and weights.
Cluster centers use the same live-member visual centroid as desktop Move/Rotate rather
than trusting a potentially stale stored pivot. The reader rejects duplicate,
unknown, or pose-mismatched identities, aliases, handles, and transform owners,
allowing numeric
regression diffs and controller tools to address geometry without draw order or
delimiter-sensitive ID parsing. A boundary bond or crossover can therefore move its
selected endpoint while leaving the opposite Cluster endpoint fixed. Fractional
weights continuously skin crossover inserts, flexible ssDNA runs, and ss-linker
bead/slab/backbone paths between their two authoritative endpoint Clusters. The
v11+ atomistic identities use `(base key, chemical atom name)` rather than a draw
index, and atom-bond identities use the canonicalized pair of those semantic atom
references. This keeps exact atom targets stable across rebuilds and reversed bond
enumeration without promoting them to persistent design selections. The reader
remains compatible with v4-v11 snapshots.
The snapshot also carries explicit crossover/forced-ligation links,
canonical crossover-insert bead/slab chains, 0.25 nm chemistry-colored extension
markers, per-domain axis gaps, and closed half-cylinder overhang domains in the
Cylinders representation.

The controllers pulse when an interaction begins. Press Escape in the companion
window, close that window, or select Help → Exit VR in NADOC to end the session.
