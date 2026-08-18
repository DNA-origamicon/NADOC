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

Ubuntu development packages:

```bash
sudo apt install build-essential cmake ninja-build libopenxr-dev \
  libopenxr-loader1 libglfw3-dev libglm-dev libgl1-mesa-dev libx11-dev
```

The backend selects SteamVR's `steamxr_linux64.json` automatically when it
launches the viewer. Press Escape in the companion window, close that window,
or select Help → Exit VR in NADOC to end the session.
