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

Ubuntu development packages:

```bash
sudo apt install build-essential cmake ninja-build libopenxr-dev \
  libopenxr-loader1 libglfw3-dev libglm-dev libgl1-mesa-dev libx11-dev
```

The backend selects SteamVR's `steamxr_linux64.json` automatically when it
launches the viewer. Help → Open SteamVR / Desktop starts SteamVR independently,
so its Dashboard remains available before, during, and after a NADOC VR session.
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
scene ownership table before the green marker or Tools readiness appears, so the
target need not be reselected in VR and an absent owner cannot become a false match.

Controls on the original HTC Vive wands:

- Hold the right grip/squeeze button for Expanded Quick View; releasing it
  restores natural helix spacing without changing the design.
- Click the right trackpad while a cyan hit marker is visible to select that
  element through NADOC's active selection level and canonical selection controller.
- Hold either trigger to grab, move, and rotate the structure outside a tool
  preview. During Move/Rotate Preview, right trigger alone moves/rotates the
  pending Cluster handle while left trigger remains a structure grab.
- Hold both triggers and change the distance between the controllers to resize
  the structure around their midpoint.
- Press either application-menu button to open or close the in-headset menu.
  Point a wand and pull its trigger to select a representation (Cylinders,
  Full, Ball + Stick, or Stick Only), coloring (Strand, Base, Cluster, or CPK),
  selection level (Auto / Drill, Cluster, Strand, Domain, End, Crossover, or Base),
  Recenter, or Close. The active level is green and begins at the desktop's current
  level when VR launches.
- Select Tools in that panel to open the Phase 5 transaction shell. It exposes
  Inspect, Move/Rotate, Extrude, Twist, and Bend plus Preview, Confirm, Cancel,
  Undo, and Back. This first shell is visibly marked **READ ONLY**: it emits bounded
  browser-owned intents and status but cannot yet mutate geometry or create history.
  Confirm is reported as staged and Undo reports that no VR commit exists.
  Move/Rotate directly previews exact Cluster, Strand, Domain, End, and Base
  scopes. End-target Extrude and Cluster/End Twist or Bend are amber and report
  **CONFIG REQUIRED** until their length/direction/footprint or plane-pair/amount
  controls exist in-headset. Other pairings report **UNSUPPORTED TARGET** instead
  of silently widening the edit. Preview draws an
  RGB translation triad at the exact current visual centroid used by NADOC's desktop
  gizmo; its size is derived from owner-wide bounds and stays capped for reach.
  Right-trigger drags accumulate across re-grabs and Cancel returns the handle exactly
  to its activation position. Scene-v10 endpoint ownership drives the same pending
  pose through native geometry, picking, selection anchors, and shadows: internal
  primitives move rigidly while a boundary bond or crossover leaves its opposite
  endpoint fixed. The native companion also publishes the same rigid delta through
  the private event bridge. NADOC converts it from view/snapshot coordinates back to
  nanometres and mirrors it through the desktop Cluster gizmo or exact nucleotide
  transform adapter from one immutable baseline. This remains preview-only: Confirm
  is blocked, Cancel or native session exit restores desktop geometry, and no
  design/history entry is written.
  Every tool button event snapshots the exact acknowledged primitive, canonical kind,
  and bounded opaque owner aliases at controller-click time. The browser rejects a
  delayed event if that snapshot no longer names its current canonical selection, and
  Preview/Confirm must name the identical snapshot. Changing selection during a
  VR-origin desktop preview cancels and restores it instead of retargeting the gizmo;
  stale transform samples are discarded rather than queued for a later Preview.
- Cyan and orange pointers identify the left and right controllers. They turn
  green during a one-hand grab and magenta during a two-hand resize.
- When neither trigger is held, the right pointer extends to the nearest visible
  primitive and shows a small cyan hit marker. This read-only stable-identity hover
  cue does not change NADOC selection. After a trackpad click is accepted by the
  desktop selection controller, a larger green marker remains on the selected owner;
  rejected target/level combinations never produce a false green acknowledgement.
  When a representation has no exact copy of the clicked primitive, the marker uses
  the browser-confirmed canonical owner hierarchy (including exact End, Bond, or
  Crossover aliases where available, then Base, Domain, Strand, and Cluster), so
  switching representations does not silently lose canonical selection.
  Ordinary backbone cylinders and inter-residue atomistic bonds resolve through the
  same canonical bond ownership as desktop connector picks. Intra-residue atom bonds
  and sampled flexible/linker curve edges resolve to their owning or nearest Base;
  display-only ds-linker connector arcs remain non-selecting. Overhang half-cylinder
  picking follows its curved wall, flat face, and caps rather than an enclosing full
  capsule, so the missing half cannot steal hits from geometry behind it.
- Press the Vive System button (not the application-menu button) to open the
  SteamVR Dashboard, then select Desktop to operate NADOC's normal interface.

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
