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

Controls on the original HTC Vive wands:

- Hold the right grip/squeeze button for Expanded Quick View; releasing it
  restores natural helix spacing without changing the design.
- Click the right trackpad while a cyan hit marker is visible to select that
  element through NADOC's active selection level and canonical selection controller.
- Hold either trigger to grab, move, and rotate the structure.
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

The native renderer uses the Photo-mode Full lighting balance: a camera-pinned
directional key, low ambient fill, and one 2048² soft self-shadow map shared by
both eyes. Full representation geometry mirrors the editor's physical display
primitives: 0.10 nm backbone beads, 0.18 nm 5′ cubes, oriented
0.30 × 0.06 × 0.70 nm base slabs, 0.025 nm slab connectors, and 0.075 nm
same-helix strand connectors.
Scene format v8 pairs natural and Expanded Quick View poses by the URL-safe
semantic identities introduced in v6 and explicitly attaches bounded canonical-owner
aliases to selectable primitives. It rejects duplicate, unknown, or pose-mismatched
identities and aliases, allowing numeric regression diffs and controller picking to
address geometry without relying on draw order or parsing delimiter-sensitive IDs.
The reader remains compatible with v4/v5/v6/v7 snapshots.
The snapshot also carries explicit crossover/forced-ligation links,
canonical crossover-insert bead/slab chains, 0.25 nm chemistry-colored extension
markers, per-domain axis gaps, and closed half-cylinder overhang domains in the
Cylinders representation.

The controllers pulse when an interaction begins. Press Escape in the companion
window, close that window, or select Help → Exit VR in NADOC to end the session.
