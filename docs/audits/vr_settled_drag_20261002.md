# Settled Move/Rotate drag reassessment — 2026-10-02

Continuous motion remains below 90 Hz after startup recovery. Two completed,
long held-trigger tests sustain only 77–78 application submissions per second;
the following stationary holds recover to 89.5 with no compositor repeats or
drops. This supports prioritizing recurring preview/update and presentation
costs over further first-grab work for the continuous-motion problem.

## Protocol and results

Existing full 24HB design, Ball & Stick, selected cluster, current optimized
native binary and established SteamVR path. Private copies preserve the original.
The unchanged controller profiles alternate translation and rotation endpoints
while holding the trigger: at least 5 seconds warm-up, at least 30 seconds
measured motion, 5 seconds stationary settling, then 10 seconds measured hold.
A reach finishes before the next stage, so durations exceed their minimums.
Captures, initial preview setup, commit, save/reopen and Undo are outside the
measured intervals. No rendering settings, acquisition thresholds or playback
deadlines were relaxed. No concurrent builds or tests ran during measurement.

| Profile | Drag seconds | Drag FPS | Last 10 s FPS | Hold FPS | Drag GPU span p95 | Hold GPU span p95 | Drag repeats / drops | Hold repeats / drops |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| steady_fast | 30.38 | 77.27 | 77.01 | 89.53 | 10.04 ms | 7.64 ms | 360 / 13 | 0 / 0 |
| steady_deliberate | 31.90 | 78.39 | 74.59 | 89.53 | 10.01 ms | 7.65 ms | 343 / 10 | 0 / 0 |

Both completed profiles pass edit, stereo evidence, save/reopen and Undo.
Both variable profiles fail the existing `grab was not remote` assertion before
trigger acquisition and before the long interval. They provide no settled-motion
measurement. Their failures and traces are retained; all-four-profile validation
is therefore **not passing**. No unchanged retries were made.

## Attribution and next priority

- Active packed-preview updates have p95 3.00–3.11 ms and maxima 4.14–4.47 ms.
  This scope includes CPU transformation, buffer uploads and bounds work. The
  source still orphans and uploads the full affected channel arrays on changes
  (`rigid_preview.hpp`, `Channel::upload`), including unchanged instance fields.
  No first-grab rebuild recurs in the measured drag.
- Non-runtime-wait application wall time has p95 5.07–5.10 ms during drag,
  versus 1.87–1.93 ms during the hold. Compositor GPU spans rise from p95 about
  7.64 ms to 10.0 ms, close to the 11.111 ms refresh budget. `xrEndFrame` p95 is
  about 20 ms during drag. These observations locate a sustained motion-related
  pipeline/pacing problem; they do not isolate pure shader cost or prove uploads
  alone cause every missed presentation.
- Mirror blit p99 is 4.71–4.76 ms, another possible synchronization contributor.
- Event-state publication shows rare 61.69 and 75.63 ms stalls, inside frames
  with 65.58 and 80.26 ms non-runtime-wait totals. Only one and two frames,
  respectively, exceed the fixed 11.111 ms non-runtime-wait budget. Those rare
  stalls cannot explain the hundreds of repeated compositor frames. The scope
  performs synchronous file publication on the XR thread; this trace alone
  cannot distinguish I/O latency from descheduling inside that scope.

Recommended next experiment: split the packed-preview scope into transform,
upload and bounds timing, then A/B reducing per-motion buffer traffic while
preserving endpoint weights, picking IDs and identical rendering. Retest with
this longer protocol. Handle synchronous event publication as a separate
worst-case-latency improvement, and isolate mirror synchronization if buffer
work does not restore sufficient headroom. No production renderer change was
made for this reassessment.

## Scope and reproducibility

FPS is application submission cadence, not physical headset scanout. GPU spans
come from the compositor and may include synchronization effects. CPU and GPU
work overlap; the reported percentiles must not be added. Input uses the existing
20 Hz synthetic profile reaches, with normal reaction/noise, not continuous
90 Hz wearer tracking. The hold resends an identical pose using the same live
observation path but approximate cadence; its fixed orientation differs from
the drag's range of orientations. It is a useful stationary control, not a
fully isolated upload experiment. Compositor interval boundaries have roughly
100 ms uncertainty. Instrumentation overhead remains included.

The post-measurement steady-fast left-eye capture was visually inspected:
molecular geometry and selected cluster bounds are clearly rendered. Stereo
checks also pass for the two completed tours. This does not establish physical
through-lens comfort.

Reusable entry: **Debug → VR Tours & Tests → Authoring → Move / Rotate cluster ·
settled drag**. CLI:

```sh
uv run python -m tools.vr_workflows.tool_frame_audit \
  --tools move_cluster --representations ballstick --settled-drag --validate \
  --profiles steady_fast steady_deliberate variable_fast variable_deliberate \
  --design workspace/24hb_0xT.nadoc --min-available-gib 5 --output <new-artifact-dir>
```

Artifacts: `.development-artifacts/vr-settled-drag-20261002/`, with the initial
steady-fast run in `smoke/` and the other three in `final-profiles/`.
`analysis.json` and `analyze.py` retain summaries and last-ten-second analysis;
each case retains native and compositor logs, explicit intervals, captures,
profile samples and tour outcome. No global runtime logs were used in analysis.

Validation: 3 settled-drag tests and 35 tour tests pass; `git diff --check` passes.
An initial focused-test command supplied two targets to the one-target wrapper
and was rejected before execution; both files were then run separately.
Cleanup removed four proven-owned empty socket directories. No owned viewer,
new bridge credentials or private workspaces remain. Original source SHA256 is
unchanged: `bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
