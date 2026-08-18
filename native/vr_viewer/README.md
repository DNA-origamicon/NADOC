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

Controls on the original HTC Vive wands:

- Hold either trigger to grab, move, and rotate the structure.
- Hold both triggers and change the distance between the controllers to resize
  the structure around their midpoint.
- Press either application-menu button to open or close the in-headset menu.
  Point a wand and pull its trigger to select a representation (Cylinders,
  Full, Ball + Stick, or Stick Only), coloring (Strand, Base, Cluster, or CPK),
  Recenter, or Close.
- Cyan and orange pointers identify the left and right controllers. They turn
  green during a one-hand grab and magenta during a two-hand resize.
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
The snapshot format also carries explicit crossover/forced-ligation links,
canonical crossover-insert bead/slab chains, 0.25 nm chemistry-colored extension
markers, per-domain axis gaps, and closed half-cylinder overhang domains in the
Cylinders representation.

The controllers pulse when an interaction begins. Press Escape in the companion
window, close that window, or select Help → Exit VR in NADOC to end the session.
