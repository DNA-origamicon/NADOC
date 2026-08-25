# Full-origami atomistic MD in VR

This is the reproducible troubleshooting and validation record for the latest
downloaded Alpine frame of `24hb_2xT.nadoc`. It covers every atomistic
representation exposed by the native Vive menu: **Ball + Stick** and **Stick
Only**. Desktop VDW currently maps to the native Ball + Stick representation;
there is no separate VDW choice in the native menu.

## Validated result (2026-08-24)

The workstation can render this assembly. The failure was an application-side
style-switch algorithm, not insufficient GPU capacity.

- Fixture: Alpine job `fc12195d0636`, one downloaded production frame from
  `24hb_2xT_01_production_400ns_k0.dcd`.
- Full solvated trajectory topology: 1,354,425 atoms. The VR DNA-heavy subset is
  151,013 atoms and 169,124 rendered bonds (the backend topology report varied by
  50 bonds before native endpoint filtering).
- Hardware: Ryzen 9 9950X, 30 GiB RAM, RTX 3080 Ti with 12 GiB VRAM. The automated
  headroom gate passes. Full swap is a warning and unrelated memory-heavy programs
  should be closed before a run.
- Exact native scene: 4,744,221 records, 82 MiB gzip / about 726 MiB expanded,
  roughly 6.5–7.1 seconds to parse, and about 2.9 GiB resident after parse.
- First Ball + Stick construction: 0.70–0.82 seconds. Ball + Stick ↔ Stick changes
  then take about 0.001 ms and allocate no replacement geometry.
- Current submitted-eye rendering: scene CPU p50 about 0.22 ms and p95 about
  1.6 ms against an 11.11 ms 90 Hz period.
- A clean physical-HMD left-eye submission showed the entire assembly as CPK-colored
  atoms and bonds. The final local capture was
  `/tmp/24hb_2xT-optimized-final.png`; regenerate it rather than relying on `/tmp`.
- ScryWrite opened the production Options menu and asserted the complete boundary
  chain Ball + Stick → Full → Ball + Stick → Stick Only → Full → Ball + Stick.
  It captured all six semantic states and passed at virtual frame 514. On the exact
  scene, Ball + Stick → Full took 309 ms, Full → Ball + Stick took 798–815 ms,
  Ball + Stick → Stick took 0.0005 ms, and Stick → Full took 321 ms; every transition
  completed without a crash and left the asserted representation active.

An earlier active-headset SteamVR compositor sample reported 3.19 ms application CPU,
3.76 ms application GPU, zero reprojected frames, and five startup-only drops over
902 presents. A later unattended sample was deliberately rejected: the Vive had timed
out, which throttled submissions and inflated CPU/dropped-frame counters. Always run
the compositor gate while the headset is active or worn.

## Root cause and fixes

`GlScene::setStyle` repeatedly performed linear ownership, alias, and tool-handle
searches for each of hundreds of thousands of primitives. On the full origami this
became effectively quadratic, then repeated large source copies and GPU uploads on
each atomistic switch. That explains the long pause and eventual memory/process
failure even though the GPU had ample capacity.

The native viewer now:

- builds hash indexes for ownership, aliases, and tool handles;
- keeps pointers to immutable natural/expanded sources instead of copying them unless
  interpolation is genuinely needed;
- indexes encoded atom-owner tokens directly;
- validates Ball + Stick and Stick bond geometry once, then shares the resident
  buffers and only changes the sphere draw count;
- emits bounded process start/progress/end, scene-load RSS, style timing, and 240-frame
  p50/p95/p99 timing records;
- uses sphere impostors, atomistic line-bond LOD, and skips the 2048² shadow pass and
  nine-tap PCF for dense atomistic views.

The browser atomistic renderer now also keeps topology-stable MD GPU buffers. Later
frames update instance matrices in place (`geometryPath: "coordinates"`) rather than
disposing and recreating every sphere, bond, color buffer, and shader state. Ball +
Stick ↔ Stick toggles attach/detach the existing sphere instances. A changed topology
fails safely to `geometryPath: "rebuild"`.

Do not treat the whole OpenXR loop duration as render time. OpenXR intentionally
throttles the application at frame synchronization points; the Khronos specification
states that `xrWaitFrame` blocks according to runtime scheduling. The viewer therefore
reports `loop_*`, `input_*`, `scene_*`, and `xr_end_*` separately and judges only
`scene_p95_within_budget`. Use SteamVR compositor statistics for authoritative CPU,
GPU, drop, and reprojection results. See the
[OpenXR frame-rate contract](https://registry.khronos.org/OpenXR/specs/1.1-khr/html/xrspec.html#frame-rate)
and Valve's
[Compositor_FrameTiming reference](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming).

## Repeatable workflow

Run NADOC locally first. These commands read the already-downloaded job and do not
connect to Alpine.

```bash
# 1. Fail early if the workstation lacks headroom.
just vr-atomistic-system

# 2. Ask the local MD websocket to load the downloaded config and write the latest
#    DNA-heavy atom positions in the native visualization format.
just vr-atomistic-capture

# 3. Obtain a current scene snapshot by launching View in VR once. The backend log
#    prints VR_SNAPSHOT process_start/progress/end records. Record the returned
#    /tmp/nadoc-vr-*.nadocvr.gz path; do not guess when several exist.

# 4. Parser/style benchmark without starting OpenXR.
native/vr_viewer/build/nadoc-vr-viewer \
  --benchmark-atomistic /tmp/nadoc-vr-XXXXXX.nadocvr.gz \
  /tmp/24hb_2xT-latest.visualization.txt

# 5. With SteamVR and the Vive active, run the bounded menu replay.
just scrywrite-atomistic-24hb /tmp/nadoc-vr-XXXXXX.nadocvr.gz

# 6. While the viewer and active HMD are rendering, capture compositor statistics.
just vr-atomistic-steamvr-stats
```

The capture command defaults to:

```text
job id: fc12195d0636
config: /media/jojo/Archive/NADOC_archive/fc12195d0636/package/24hb_2xT_namd_solvated/nadoc_md_run.json
visualization: /tmp/24hb_2xT-latest.visualization.txt
metrics: /tmp/24hb_2xT-vr-diagnostics.jsonl
```

Override `--job-id`, `--config`, `--ws-url`, `--visualization`, or `--metrics` when
the downloaded fixture changes. The tool writes private mode-0600 data and replaces
the visualization atomically.

## What constitutes a pass

1. `system` returns `status: capable`; swap warnings are actionable but not failure.
2. `capture-md` ends `status: ok`, reports 151,013 points for this fixture, and writes
   a nonempty visualization file.
3. `--benchmark-atomistic` ends `status=ok`; initial atomistic build is bounded and
   both return switches report `fast_path=shared_atomistic_buffers`.
4. ScryWrite prints `Witness PASSED`, and its six semantic snapshots exist. The trace
   must explicitly contain successful Full → Ball + Stick and Stick → Full changes.
5. The mirror says `SUBMITTED EYE`, `TRACKED`, and `DESIGN ONLY` (or `DESIGN+GRID`
   when deliberately using the grid). It must not say spectator fallback.
6. The submitted-eye image contains the full expected assembly and visibly distinct
   atom/bond structure. This is the application eye accepted by the physical runtime,
   not a lens-warped through-lens camera photograph.
7. An active-headset `steamvr-stats` sample has CPU and GPU below 11.11 ms, zero
   reprojection, and no `timed_out` counters. The diagnostic fails closed if the app
   is absent, the HMD is inactive, or those conditions are false.

## Troubleshooting map

- Long pause before the viewer window: inspect `VR_SNAPSHOT` and `scene_load`
  progress. Snapshot generation remains the largest startup cost (about 58 seconds
  on this exact design); native parsing is about seven seconds.
- Pause on the first atomistic display only: inspect `style_apply`; about 0.75 seconds
  and about 3.3 GiB final RSS are expected for this scene.
- Pause on every Ball + Stick/Stick change: the shared-buffer fast path regressed.
  Run the benchmark and native tests before testing the headset.
- Browser playback rebuilds every frame: `nadoc:md-display-process` will show
  `geometryPath: "rebuild"`; stable frames must report `coordinates` after the first.
- `loop_p95_ms` near 22 ms but `scene_p95_ms` below budget: runtime scheduling or an
  idle/throttled HMD, not slow application rendering.
- High SteamVR CPU plus `dropped_frames_timed_out`: wake/wear the HMD, ensure SteamVR's
  idle-pause behavior is disabled for the test, restart the sample, and do not compare
  it with an active-headset baseline.
- `SPECTATOR FALLBACK`: the runtime did not accept a current HMD frame; visual evidence
  is diagnostic only and cannot close the physical submission gate.
- Out of memory: close unrelated programs, verify at least 6 GiB available RAM and
  4 GiB available VRAM, and address full swap before retrying.

## Regression commands

```bash
env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  cmake --build native/vr_viewer/build -j2
ctest --test-dir native/vr_viewer/build --output-on-failure

cd frontend
npm test -- --run src/scene/atomistic_renderer.test.js src/ui/md_panel.test.js

cd ..
uv run pytest -q tests/test_vr_routes.py tests/test_vr_scene_contract.py \
  tests/test_vr_scene_projection.py
```

The ScryWrite scripts are
`native/vr_viewer/examples/scrywrite_witness_atomistic_24hb.scry` (bounded exit) and
`scrywrite_witness_atomistic_24hb_hold.scry` (leave the final view visible for manual
inspection). Witness Mode is read-only: it refuses an event output path and cannot
publish a browser design mutation.

## Remaining optimization boundary

The crash and interactive switching costs are fixed. The dominant remaining delay is
building and compressing a snapshot that contains natural and Expanded geometry for
all representations. A future format revision could deduplicate the identical
Ball + Stick/Stick bond and ownership records, but it must preserve v12 semantic
identity, selection, tool-scope, and Expanded-pose parity. Do not remove those records
without adding a versioned native alias contract and matching corruption tests.
