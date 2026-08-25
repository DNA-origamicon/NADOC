# Native VR interface comfort and timing

This is the durable audit and validation record for the native OpenXR interface.
It complements `scrywrite_atomistic_md.md`, which covers full-origami style changes.

## Comfort finding and implemented mitigation

The original Options tablet was stroke-only geometry in the same guide buffer as
controller rays. `GlScene::renderGuides` disabled depth testing, so the tablet was
always drawn over the molecular model while the model remained visible through its
empty area. Nausea persisted when the tablet was docked and when it moved slowly,
which rules out controller-follow speed as the sole cause and makes the conflicting
occlusion/depth presentation the primary implementation fault addressed here.

The main tablet now:

- has an opaque navy backing on every non-Desktop page;
- is submitted as ordinary world geometry with depth testing and depth writes;
- rasterizes its stroke UI into a 1536-pixel-high, up-to-4x-MSAA RGBA texture;
- hashes quantized panel-local geometry and rerasterizes only when content, hover,
  page, bounds, or backing mode changes;
- draws as one mipmapped, bilinear-filtered quad per eye instead of uploading and
  drawing thousands of line vertices per eye and frame.

The Desktop page remains a live X11 texture. It is now depth tested, and its cached
transparent control/border texture is drawn just in front of it. Other controller,
lattice, radial-tool, selection, and witness guides retain their existing behavior.

## Telemetry

The viewer emits bounded `VR_METRIC` records:

- `phase=menu_state`: open/closed, page, dock/follow placement, backing and depth
  mode, plus cache update/hit totals;
- `phase=menu_comfort` every 120 visible-menu frames: minimum and median nearest-eye
  distance, menu angular-velocity p95, controller per-frame pose delta, and 120 ms
  low-pass translation/orientation residuals. The residual is diagnostic and may
  include deliberate fast motion;
- `phase=menu_gpu_timing`: asynchronous OpenGL timer-query p50/p95/p99/max split by
  menu-open state. A 16-query nonblocking ring records skips rather than stalling VR;
- `phase=frame_timing`: existing CPU input/scene/runtime scheduling windows.

OpenXR does not expose compositor drop/reprojection counters. The authoritative
SteamVR gate therefore samples `vrcmd --stats` twice, three seconds apart by default,
and reports interval deltas for presents, submissions, drops, reprojection, timeouts,
loading, and startup counters:

```bash
just vr-atomistic-steamvr-stats
# or choose a longer active interval
uv run python scripts/vr_atomistic_diagnostics.py steamvr-stats --sample-seconds 10
```

Historical cumulative drops no longer poison a current test. The gate requires an
active interval with presents, no interval timeout, no drops, no reprojection, and
application CPU/GPU below the 11.11 ms 90 Hz period.

## Validation record (2026-08-24)

The deterministic OpenXR menu capture passed all semantic, framing, tracking, and
layout assertions at ScryWrite frame 284. It produced five actor-eye images and
reported:

- cache: 4 content updates and 116 hits over the first 120 open-menu frames;
- cached texture: 1159 x 1536, 4x MSAA, 4,740 guide vertices on the Tools page;
- cache refresh: 0.061 ms for the last page update;
- menu-open GPU: p50 0.186 ms, p95 0.730 ms, p99 8.98 ms, zero timer-query skips;
- application scene CPU: p50 0.249 ms, p95 1.094 ms against 11.11 ms.

The exact downloaded `24hb_2xT` scene then passed the six-snapshot atomistic replay
at frame 514 with the backed menu open throughout all representation changes. Across
three 120-frame open-menu GPU windows, p95 was 4.57, 2.84, and 3.33 ms; cache refresh
was 0.09-0.13 ms, 349 of the final 360 sampled frames were cache hits, and no timer
query was skipped. The style-transition/screenshot CPU windows remained under the
11.11 ms application-work gate (scene p95 10.19 and 9.24 ms).

An unattended three-second SteamVR interval was also deliberately tested and failed
closed: 110 presents, 164 drops (156 timeout-related), six timeout increments, zero
reprojection, 28.8 ms reported CPU, and 8.65 ms GPU. This confirms that interval
drop/reprojection telemetry works, but it is not a comfort-performance pass; the
headset must be worn for that gate.

The exact command is:

```bash
mkdir -p /tmp/nadoc-menu-comfort-captures
env -u LD_LIBRARY_PATH \
  XR_RUNTIME_JSON="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json" \
  native/vr_viewer/build/nadoc-vr-viewer \
  native/vr_viewer/examples/triangle.nadocvr \
  --mirror-eye left --reference-grid off \
  --scrywrite-witness native/vr_viewer/examples/scrywrite_witness_menu_capture.scry \
  --witness-captures /tmp/nadoc-menu-comfort-captures --witness-exit on
```

For comfort sign-off, repeat the bounded `24hb_2xT` atomistic replay with the headset
worn, leave Options open in Ball + Stick and Stick Only, capture the interval SteamVR
gate, and record whether symptoms persist. Automation can validate the image and
timings but cannot assert a person's comfort.

## Regression gates

```bash
env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  cmake --build native/vr_viewer/build -j2
ctest --test-dir native/vr_viewer/build --output-on-failure
uv run pytest -q tests/test_vr_atomistic_diagnostics.py
```
