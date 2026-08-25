# Full-production MD trajectories in VR

## Decision

The 24hb_1xT production trajectory is feasible to view in VR, but **not** by loading
the DCD into memory or decoding/publishing coordinates on the OpenXR render thread.
The implemented design keeps the headset loop at 90 Hz and independently delivers MD
keyframes at roughly 5–15 Hz through a latest-complete bounded publication. The native
viewer currently applies the newest complete keyframe; optional two-frame interpolation
at OpenXR's predicted display time is a future smoothness enhancement, not a frame-rate
requirement.

As of 2026-08-25, topology/identity is sent once (JSON to the browser and the text
visualization feed to the native viewer), while every trajectory frame uses binary
coordinate-only transport. The backend-to-browser `NADOCMDA` stream decodes only the
displayed DNA prefix of each DCD frame; the browser-to-native `NVRCOORD` publication is
an atomic 1.73 MB revision. Playback state has an independent small feed, and the native
menu exposes synchronized Play/Pause,
Previous/Next, and a click-or-trigger-drag timeline slider. Dragging publishes a seek
only when the target frame changes. The remaining production limitations
are DCD extraction/cache throughput and optional interpolation—not native atomistic
rendering. Full playback remains correct through a coalesced coarse snapshot fallback;
it is intentionally not sent through the atom-XYZ-only protocol because its slabs also
need an orientation.

## Implemented coordinate-delivery contract

- The backend sends atom identity/topology once. A negotiated `NADOCMDA` version-1
  frame then carries a 36-byte header plus float32 `x[]`, `y[]`, and `z[]` columns.
  Legacy clients retain their JSON-frame behavior.
- For NAMD DCDs whose DNA is an early topology prefix, the server reads only through
  the highest displayed-heavy-atom index. It automatically falls back to MDAnalysis
  for solvent overlays, non-DCD trajectories, inefficient/interleaved layouts, or
  prefix-reader errors.
- The browser publishes native atom identity/topology once in stable `visitAtoms()` order.
- Each frame is `NVRCOORD`, version 1: a 36-byte little-endian header followed by
  `atom_count * 3` float32 coordinates. A 144,253-atom frame is 1,731,072 bytes
  including its header versus roughly 13.4 MB for the text snapshot.
- The backend validates bounds/finite values, applies the launch view rotation, and
  atomically replaces the mode-0600 coordinate file before its matching state file.
- `NADOCVR_TRAJECTORY 1` carries sequence, active/frame/count, playing, loop, live,
  speed, and stride separately, so menu state does not require a coordinate resend.
- Native polling uses file modification time and a latest-complete-revision policy.
  A slow producer cannot block `xrWaitFrame` or grow an unbounded queue.
- Desktop controls emit authoritative state; native menu requests return through the
  sequenced event channel and call the same desktop controller methods.

## Measured 24hb_1xT production data

Source inspected on 2026-08-24:

```text
/media/jojo/Archive/NADOC_archive/6950d3b79138/package/
  24hb_1xT_namd_solvated/output/24hb_1xT_01_production_500ns_k0.dcd
```

| Property | Measured value |
|---|---:|
| DCD size | 181,149,429,020 bytes (168.709 GiB) |
| Total atoms, including solvent | 1,350,001 |
| Complete frames | 11,182 |
| Bytes per raw frame | 16,200,092 |
| Saved-frame interval | 20 ps |
| Complete time currently present | 223.64 ns |
| Input-PDB DNA atoms, before PSF hydrogen addition | 144,481 |
| Hydrogenated PSF/DCD DNA prefix | 224,261 |
| DNA heavy atoms displayed | 144,253 |
| DNA-heavy float32 coordinate frame | 1,731,036 bytes |
| DNA-heavy cache for current 11,182 frames | 18.027 GiB |

The file name describes a 500 ns stage, but the file currently contains 223.64 ns of
complete saved frames. At the same 20 ps cadence, 500 ns would be 25,000 frames. An
uncompressed DNA-heavy coordinate cache for that target would be about 40.3 GiB;
chunk compression or quantization can reduce it further.

The archive filesystem has about 5.4 TiB free and can hold either cache. The system
SSD currently has only about 22 GiB free, so it lacks the required 20% safety margin
even for the present 18.0 GiB cache and cannot hold the 40.3 GiB target. Sequential
compact playback from the archive needs only 16.5 MiB/s at 10 updates/s, but an SSD
capacity upgrade remains preferable for responsive random scrubbing.

A 33-frame distributed cold-range probe reported 49.4 ms p50, 98.2 ms p95, and a
473.8 ms worst outlier—a theoretical 10.18 source frames/s at p95, with no safety
margin at 10 updates/s. Shorter trials varied substantially as archive-drive and
kernel caches changed, which is itself evidence against making random DCD reads a
realtime dependency. The committed command defaults to 33 samples and range-scoped
`POSIX_FADV_DONTNEED` before each one. It records every timing and never clears
system-wide caches. The compact cache should be built on SSD for playback.

These source rates are not headset rates. The HMD must continue receiving frames at
its runtime cadence even when the MD source has not advanced.

Production WebSocket benchmarks isolate the successive delivery changes:

| 24hb_1xT source path (16 sequential frames) | p50 | p95 | Result |
|---|---:|---:|---|
| Repeated JSON atom objects + full 1.35M-atom DCD decode | ~662 ms | ~707 ms | ~1 Hz |
| `NADOCMDA`, still decoding the full solvated frame | 103.0 ms | 121.5 ms | 8.2 Hz at p95 |
| `NADOCMDA` + 224,260-atom prefix reader | 69.2 ms | 71.7 ms | 13.9 Hz at p95 |
| Prefix reader + precomputed per-strand row lists | **61.0 ms** | **62.5 ms** | **16.0 Hz at p95** |

The current route is about 9.8× faster at p50 than the JSON baseline and has 37.5 ms
of p95 headroom inside the 100 ms / 10 Hz source cadence. Reusing the already-computed
Kabsch equilibrium map and deferring a diagnostic cold mid-DCD seek reduced topology
load from 35.3 s to 24.2 s cold and 5.23 s hot; the one-time ready JSON is 10.3 MB.
Neither blocks the OpenXR frame loop. `playback-md` primes a bounded three-frame source
window (the first cold archive read measured 136 ms), then starts the visible cadence.
In the final 16-frame run, requests were 58.7 ms p50 / 60.5 ms p95 and republishing each
144,253-atom frame as `NVRCOORD` was 0.94 ms p50 / 1.27 ms p95. It sustained 10 Hz with
zero misses outside the explicit 5 ms keyframe scheduling tolerance.

The native headless benchmark loaded the compatible full scene (4,744,221 records)
in 6.51–8.42 s at a 2.85 GiB RSS peak and accepted all 144,253 real-frame atom positions.
The first Ball + Stick preparation/upload took 806–827 ms, while subsequent resident
Ball + Stick ↔ Stick changes took less than 0.001 ms. This proves the existing
resident representation optimization works, but also shows why a new coordinate
frame must update persistent buffers directly instead of invoking the full style
preparation path.

Keeping those atomistic CPU buffers after a Full transition reduced the measured
Full → Ball + Stick return from 903 ms to 4.56–4.76 ms in headless benchmarks and
1.14–1.18 ms in repeated OpenXR/ScryWrite runs. Ball + Stick ↔ Stick remains
effectively free. Entering Full inside the
standalone witness still costs about 316–328 ms because the witness must synthesize a
coarse representation locally. The desktop-integrated viewer does not perform that
speculative rebuild: the menu emits a request and waits for one authoritative desktop
style+geometry revision.

The first incremental implementation still spent about 29.7 ms p50 on CPU because it
hashed every URL-encoded atom token and normalized each bond endpoint every frame.
Telemetry exposed that immediately. Retaining direct coordinate slots and normalizing
each atom once reduced real 24hb coordinate updates to:

| Incremental stage | p50 | p95 |
|---|---:|---:|
| CPU instance update | 1.28 ms | 1.89 ms |
| GL orphan/upload submission | 0.85 ms | 1.03 ms |
| CPU + completed GPU work (`glFinish`) | 2.09 ms | 2.81 ms |

Those final numbers are from 35 updates using the exact final 24hb_1xT topology and
coordinate artifacts; completed GPU work never exceeded 3.10 ms.

The final dummy-mounted-headset OpenXR/ScryWrite run passed every strict gate. Across
717 presented/submitted frames in its eight-second SteamVR interval, it recorded zero
drops, zero reprojection, zero timed-out frames, application CPU 4.21 ms, and application
GPU 5.39 ms. Eleven coordinate revisions arrived without a sequence gap. Native parse
was 0.236 ms p50 / 1.003 ms p95, apply/upload was 3.62 ms p50 / 4.51 ms p95, and total
coordinate work was 4.73 ms p95 / 5.01 ms max, all inside the 11.11 ms 90 Hz period.
Scene-render p95 was at most 1.55 ms. The final source run published all 24 requested
frames with zero cadence misses; reads were 61.03 ms p50 / 64.73 ms p95 and binary
publication was 0.963 ms p50 / 1.465 ms p95.

The final parser numbers include direct stream reads into a persistent 1.73 MB vector.
The previous byte-at-a-time parse and per-revision allocation produced rare 6.58 and
11.03 ms parse spikes and a failing 11.52 ms total p95 despite fast rendering. Buffer
reuse reduced that total p95 by 59% to 4.73 ms. ScryWrite also exercised the optimized
Full → Ball + Stick return. All four HMD-eye captures were opened and visually inspected:
Ball + Stick and Stick showed the full red/blue atomistic bundle, Full showed the coarse
multicolored bundle, and the return capture restored the atomistic bundle. This validates
the actual native headset render path while the HMD is on its dummy; only subjective
human comfort still requires a person wearing it.

## Architecture status and remaining production work

1. **Implemented:** parse topology/identity once and keep atom/bond buffers resident.
2. **Implemented for direct playback:** negotiated DCD prefix reads avoid solvent
   coordinates. A chunked DNA-heavy cache remains optional for low-latency distributed
   random scrubbing and repeated cold playback, not for sustaining sequential 10 Hz.
3. Read/decompress on a producer thread into a queue bounded to two frames. When the
   consumer falls behind, discard obsolete unpublished frames rather than increasing
   motion-to-photon latency.
4. **Implemented:** publish coordinate-only binary frames without repeated atom keys.
   Atom-only revisions received during a standalone Full hold are explicitly skipped;
   they cannot overwrite Full's coarse cylinder/slab buffers or create false gap counts.
5. Interpolate the two resident MD frames at `XrFrameState.predictedDisplayTime`.
   Continue `xrWaitFrame` / `xrBeginFrame` / `xrEndFrame` at 90 Hz independently.
6. **Implemented and headset-validated:** validate Full, Ball + Stick, Stick,
   Full → Ball + Stick, the trajectory submenu, and unobstructed HMD-eye captures.
   Subjective comfort can only be assessed by a person wearing the headset.

OpenXR requires the running application to continuously execute its synchronized
frame loop, and recommends a consistent predicted display time throughout the engine
pipeline. Microsoft identifies 90 FPS as the target for immersive Ultra-class PCs and
calls sustained frame rate a user-comfort requirement. SteamVR compositor counters
are the authoritative final check for dropped and reprojected frames.

Primary references:

- [Microsoft Mixed Reality app quality criteria](https://learn.microsoft.com/en-us/windows/mixed-reality/develop/advanced-concepts/app-quality-criteria-overview)
- [OpenXR 1.1 frame synchronization](https://registry.khronos.org/OpenXR/specs/1.1-khr/html/xrspec.html#frame-synchronization)
- [Valve compositor frame timing](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming)

## Tools

### Bounded source feasibility probe

This reads only a small, deterministic set of distributed frames, scans only the DNA
prefix of the PSF, samples system resources, and writes start/progress/end JSONL:

```bash
uv run python scripts/vr_atomistic_diagnostics.py trajectory-feasibility
```

Default artifacts:

```text
/tmp/24hb_1xT-vr-trajectory-feasibility.jsonl
/tmp/24hb_1xT-vr-trajectory-feasibility.json
```

Use `--cache-mode system` to characterize the current kernel cache instead of the
default cold-range advice. `--samples`, `--target-hmd-hz`,
`--target-trajectory-fps`, `--config`, and `--dcd` are explicit overrides. The cache
capacity check defaults to the DCD filesystem; use `--cache-dir /tmp` to audit the
system SSD instead.

### Real-frame producer

With the local backend running, this uses the same negotiated `/ws/md-run` binary path
as Display MD, publishes one topology revision plus atomic binary coordinate/state
revisions, and measures backend seek/extraction, binary receipt/repack, file publication,
cadence misses, RSS, RAM, and GPU state:

```bash
uv run python scripts/vr_atomistic_diagnostics.py playback-md \
  --coordinate /tmp/24hb_1xT.coordinates.bin \
  --trajectory-state /tmp/24hb_1xT.trajectory.txt \
  --start-frame 0 --frame-count 100 --stride 1 --fps 10
```

Each revision has a monotonically increasing sequence. The native viewer now stats
the feed each HMD frame, parses only changed publications, and emits:

```text
VR_METRIC event=process_progress phase=coordinate_update status=applied \
  sequence=... sequence_gap=... atoms=... source_bytes=... \
  parse_ms=... cpu_update_ms=... upload_ms=... total_ms=... rss_mib=...
```

This also fixes the previous behavior that reparsed an unchanged all-atom snapshot
every tenth HMD frame. The producer primes three source frames before cadence accounting;
override with `--warmup-frames`. A 5 ms late-keyframe tolerance absorbs ordinary host
scheduling jitter without weakening the independent 11.11 ms HMD render gate; override
with `--deadline-tolerance-ms` for stress tests.

### One-command real-headset validation

First obtain a current 24hb_1xT `.nadocvr` scene through **View in VR** and keep the
local backend, SteamVR, and the Vive active. Then run:

```bash
uv run python scripts/vr_atomistic_diagnostics.py validate-playback \
  /tmp/nadoc-vr-XXXXXX.nadocvr.gz
```

The command starts the bounded producer, waits for its first atomic frame, launches
the real viewer with
`native/vr_viewer/examples/scrywrite_witness_trajectory_24hb.scry`, samples SteamVR,
and combines all evidence. It only terminates child processes that it started.
Artifacts go to `/tmp/24hb_1xT-vr-validation/`.

The ScryWrite replay opens the trajectory submenu, exercises Play/Pause and the
timeline slider, holds playback in Ball + Stick, Stick, and Full, then crosses Full →
Ball + Stick. It asserts tracked/submitted display state and writes both menu-visible
and unobstructed actor-eye captures for the real native render path.

The actor eye is deliberately side-on and close enough to show the whole bundle length.
Assessment opens the four unobstructed PNGs and rejects missing or uniform/background-only
images. This caught a physical-head-placement dependency that produced black scripted-eye
captures while an idle headset still rendered. The corrected automation has visually
inspected, non-uniform Ball + Stick, Stick, Full, and return-to-Ball + Stick images. The
2026-08-25 final run also passed the active SteamVR interval gates while the HMD was on
its dummy. These results prove the headset render and timing path; they are not a
substitute for a person's comfort report.

The validator deliberately treats an idle headset as failure. If SteamVR is running
but the headset is asleep, `dropped_frames_timed_out` can rise rapidly and no useful
comfort conclusion is possible; wake/wear the headset and rerun instead of relaxing
the gate.

Existing logs can be reassessed without rerunning VR:

```bash
uv run python scripts/vr_atomistic_diagnostics.py assess-playback \
  --viewer-log /tmp/24hb_1xT-vr-validation/viewer.log \
  --producer-metrics /tmp/24hb_1xT-vr-validation/producer.jsonl \
  --steamvr-metrics /tmp/24hb_1xT-vr-validation/steamvr.jsonl
```

## Pass gates and troubleshooting

A real-headset pass requires all of the following:

- ScryWrite finishes successfully across all three representations.
- All four unobstructed actor-eye captures contain non-uniform visible geometry.
- At least ten coordinate publications reach the viewer with no sequence gaps.
- Every measured visualization parse/apply/upload update remains inside the runtime
  period (11.11 ms at 90 Hz).
- Native scene p95 remains inside the runtime period.
- The producer has no cadence deadline misses.
- SteamVR observes an active headset/application interval, application CPU and GPU
  below 11.11 ms, and zero dropped or reprojected frames in that interval.

Interpret failures by phase:

- `trajectory_frame_probe` slow: archive storage/seek bottleneck. Build the compact
  cache on SSD or increase source stride; do not lower the HMD rate.
- `playback_frame_published request_ms` above 100 ms p95: backend DCD/PBC/Kabsch
  extraction cannot sustain 10 Hz. Confirm `binary_atom_frames=true` and that
  `dcd_prefix_atoms` is substantially below `source_atom_count`; otherwise inspect the
  fallback cause or build the compact cache.
- `write_ms` or viewer `parse_ms` slow: profile JSON decoding and binary packing; atom
  identity must remain on the one-time topology path.
- `cpu_update_ms` or `upload_ms` slow: check that the coordinate fast path was accepted;
  tool transforms intentionally reject it rather than silently discard edits.
- `sequence_gap` nonzero: producer outpaced the render-thread consumer. A latest-only
  queue makes this acceptable only if it is explicit and interpolation remains
  bounded; the strict baseline test reports it as failure.
- Native timings pass but SteamVR drops/reprojects: investigate compositor/runtime,
  GPU contention, HMD idle state, and other applications.
- SteamVR reports no active sample: wake/wear the headset and rerun; it is not a pass.

The feasibility result is therefore **yes for native rendering and coordinate
delivery**. The production source now sustains the 10 Hz design target directly from
the 168.7 GiB trajectory while VR rendering remains independent at 90 Hz. A compact
DNA-heavy cache/background producer is still the next material gain for random scrub
latency and cold-storage variance, but it is no longer required for sequential cadence.
After the binary transport, prefix reader, cached segment indices, direct reusable-buffer
parsing, and persistent GPU updates, remaining micro-optimizations are in
diminishing-returns territory. The automated production-scale acceptance gates are all
closed; human comfort remains an explicitly manual assessment.
