# VR representation switching on 24hb_0xT — 2026-09-27

## Scope and method

Source: `workspace/24hb_0xT.nadoc`, SHA-256
`9fe594c8b12e6733e5afa9a376ba4c8c505482b7ee05d298354996953e0eb46a`.
The source is read-only. A single 697,442,501-byte native snapshot was reused for
paired native renderer runs. Export took 26.23 seconds; baseline parsing took
5.90 seconds. These are real-design measurements, not the earlier synthetic
serialization benchmark.

The maintained workflow is `tools.vr_workflows.representation_tour`, available at
**Debug → VR Tours & Tests → Right sidebar → Representation switching · 24hb_0xT**.
It exercises all 12 directed transitions among Cylinders, Full, Ball & Stick and
Stick through normal sidebar controls using ScryWrite hand poses/triggers, on the
physical OpenXR runtime. Each transition asserts the applied representation and
captures submitted stereo images. Final checks require visible design-class pixels
in both eyes and agreement with the actual X11 desktop mirror.

A private responder acknowledges native style requests through the production
visualization-file protocol. This isolates native geometry/upload latency: the
benchmark does **not** measure browser event polling or desktop renderer rebuilding.
`interaction_ms` includes human-profile controller approach, trigger and polling;
`style_apply total_ms` measures CPU-side native style preparation/OpenGL submission.
It is not a GPU fence measurement or a claim about every compositor frame.

## Measured results

All **48 transitions passed**: twelve directed pairs × four unchanged controller
profiles, with at least **42,198 model pixels per eye** in every capture. Actual
X11 desktop matching was **100%**. Median CPU-side style application changed from
**245.54 ms** (baseline matrix) to **0.0178 ms** (four-profile optimized matrix);
maximum changed from **574.81 ms** to **3.21 ms**, below this headset's 11.11 ms
frame interval. This measures native CPU/OpenGL submission, not total user latency.

| From | To | Baseline ms | Optimized median ms | Optimized max ms |
|---|---|---:|---:|---:|
| cylinders | full | 24.2298 | 0.0238 | 0.0268 |
| cylinders | ballstick | 482.6700 | 0.0164 | 3.2128 |
| cylinders | stick | 226.8890 | 0.0137 | 0.5428 |
| full | cylinders | 9.3399 | 0.0153 | 0.0173 |
| full | ballstick | 428.2340 | 0.0200 | 0.0231 |
| full | stick | 241.1300 | 0.0193 | 0.0236 |
| ballstick | cylinders | 253.6640 | 0.0173 | 0.0182 |
| ballstick | full | 278.6780 | 0.0234 | 0.9209 |
| ballstick | stick | 0.0008 | 0.0153 | 0.0178 |
| stick | cylinders | 249.9580 | 0.0160 | 0.0178 |
| stick | full | 186.0010 | 0.0203 | 0.0226 |
| stick | ballstick | 574.8110 | 0.0151 | 0.0164 |

Ball-and-Stick → Stick previously used a count-only switch; its approximately
0.015 ms cached-copy result is slightly slower than that sub-microsecond baseline,
but still well within budget. Other pairs avoid their expensive rebuilds.

The final reused-snapshot launch reached live ScryWrite readiness in **10.18 s**.
Export remains **26.23 s** and native parse approximately **5.9 s**; the change
moves about one second of preparation ahead of interaction rather than claiming
that initial loading is eliminated. The private responder excludes browser polling
and desktop rebuild latency from this comparison.

## Optimization

Four bounded GPU buffer slots retain one coloring per representation. Static styles
are prepared before interactive rendering, and later switches use GPU-local buffer
copies rather than reconstructing instance arrays and ownership maps. Matching
ownership indexes are retained for immutable natural/expanded sources, preserving
ScryWrite object IDs. Interpolated geometry retains its separate rebuilt index.

The static GPU cache is bypassed for live positions/colors/slab frames, expansion,
edit transforms and selection highlights. Baked edits invalidate caches; scene
replacement creates a new cache. Existing trajectory update paths remain available.
The tradeoff is additional GPU/index memory and roughly one second of eager style
preparation at startup. The original snapshot export and parse costs remain.

## Verification and observations

- SteamVR's earlier compositor had aborted in DoSwapchainPresent. Only the stale
  VR monitor/server were closed, then the existing NADOC startup path was used.
  Fresh logs show display acquisition, direct mode and Startup Complete at 18:50.
  No SteamVR/GPU/display settings were replaced.
- Initial controller-menu placement overlapped part of the design. The final
  workflow uses the real grip path to move the menu 0.12 m along its right axis,
  outside timed switches. Head pose, scene framing and motion profiles are unchanged.
- Native CTest: 41/41, including GPU buffer byte/metadata restoration, cache color
  keys/invalidation, object-ID ownership and selection/highlight rendering.
- An initial cache attempt failed the ownership-table test. The ownership-index
  cache correction above resolves it; earlier failure logs are retained.
- Failed workflow attempts are retained: the grip helper required a list rather
  than a NumPy vector, and the private responder initially rejected a transient
  partial event-file read. The final reader retries those reads rather than
  weakening control, pixel or desktop checks.
- Through-lens comfort, browser-to-headset latency, expanded/dynamic trajectory
  switching and other designs are not established by this static-design matrix.

Evidence: `.development-artifacts/vr-representations/` contains the common snapshot,
export metadata, baseline, intermediate attempts, final validation, logs and tests.

## Software regression and cleanup

- Focused workflow tests: 2 passed; the supported representation set is checked
  against the production launch schema, all directed pairs are unique, and the
  Debug catalog exposes both demo and four-profile validation commands.
- Frontend suite: 546 files, 7,085 passed, one skipped. Chromium exercised the
  new real catalog entry, validation command and its launch request/error path.
- `just test-smart` selected FAST. Final isolated run: 9,288 passed, 92 skipped,
  one existing failure in `test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`;
  24 seconds, no per-test budget violations. No geometry constants were changed.
- The preceding run flagged the mocked peer-sync test at 5.14 s. Inspection found
  only small local revision-store work and mocked HTTP. Isolated rerun: 0.02 s test
  body (1.13 s including setup). The final fast run had no violators; no test was
  reclassified and no guard was relaxed.
- Changed-file Ruff and whitespace checks passed. Each owned native viewer/socket
  was closed; SteamVR remains running. The source design hash is unchanged.
- Browser tests created no workspace designs or tour runs. Playwright report/trace
  cleanup is verified. Useful benchmark snapshots, captures and failure logs remain
  only under `.development-artifacts/vr-representations/` (approximately 1.2 GiB).

DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
