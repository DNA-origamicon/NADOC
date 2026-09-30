# VR post-loading motion regression — 2026-09-29

The user reports that steady-state Stick/Ball & Stick motion was satisfactory
before the loading-freeze changes. Treat this as a regression in that change set,
not authorization to change lighting, shadows, detail, or movement speeds.

The first investigation incorrectly concentrated on reducing shadow workload.
Depth-only shadow programs, room-fixed lighting, transform-aware shadow reuse,
and four-tap equivalent PCF were tested, but did not clear the motion matrix.
A conservative sphere-depth experiment also failed to show a useful improvement.
All these rendering experiments, including the earlier loading patch's shadow
reuse, have been removed. The original head-relative light, shaders and shadow
render pass are restored. Geometry, colors, radii and motion profiles stay intact.

Evidence is retained in `.development-artifacts/vr-motion-shadows/`:

- `run-motion`, `run-motion-pcf`, `run-motion-early` preserve the unsuccessful
  experiments, browser/native logs, submitted stereo images and motion failures.
- `motion-summary.json` correlates the latter two attempts with read-only SteamVR
  compositor measurements. Ball & Stick missed the unchanged 150 ms replay
  deadline, and GPU time reached/exceeded the 11.11 ms display interval. These
  measurements identify late delivery; they do not establish which loading
  change introduced it or demonstrate through-lens blur.
- All three private test documents, source files, caches and native companions
  were cleaned up; their `cleanup.json` files assert the original is unchanged.
- `reverted-shadow-experiments/` and `rejected-sphere-early-depth.hpp` retain
  rejected code for provenance, outside production sources.

The next isolation step compares the original synchronous upload and new staged
resident upload using the same saved Stick snapshot, shader programs, camera,
model transforms, framebuffer and shadow/eye workload. The standalone
`nadoc-vr-resident-render-test` reports CPU/GPU timing and exact final pixel
agreement. Blocking GPU queries are confined to this diagnostic executable.

## Controlled upload comparison

`resident-comparison.log` records identical final pixels (zero differing RGBA
bytes). Legacy/staged GPU medians were 5.511/5.485 ms; p95 7.411/6.182 ms.
CPU draw submission p95 was 0.045/0.050 ms. This test does not implicate staged
buffer residency in Stick's steady-state slowdown. It is an isolated 1024² GL
workload, not a headset comfort or compositor-delivery acceptance test.

`run-motion-restored` failed before native launch: Chromium attempted WebXR and
reported no supported runtime. The native-browser verification now launches
Chromium with WebXR disabled, exercising the existing native fallback directly;
production browser/session behavior is unchanged. Retry evidence is in
`run-motion-native`. The failed launch's private document/source/cache cleanup
passed and remains retained.

## Restored-renderer runtime check

`run-motion-native` reached 100% for Stick and Ball & Stick. Stick's two measured
motion intervals contained 71 and 81 compositor samples, with zero drops/reuses;
GPU p95 was 8.69/8.46 ms. Ball & Stick failed the unchanged replay deadline at
160 ms (18 samples, GPU p95 12.22 ms, one dropped frame, 17 reused frames).
This is an unresolved result, not a passing motion acceptance test. All private
source/cache/document cleanup passed. No thresholds were relaxed.

The automated path runs a local desktop browser renderer alongside native VR.
Its GPU contention and adjusted front-facing observation pose are possible
confounders relative to the user's original remote desktop/session. Do not infer
that the historically satisfactory renderer needs lower quality from this test.
The remaining regression has not been causally isolated.

Final checks: original shader functions, shadow pass, scene draw functions and
head-relative key-light expression match HEAD (`restored-renderer-check.json`).
Three focused native CTests pass; the standalone identical-pixel upload comparison
passes; seven focused Python motion/representation-tour tests pass. Earlier
31-test tour-catalog suite passed before the final renderer reversion, which does
not alter that catalog.

The user's original document is relaunched for review through its real browser
View in VR handler after GET-based resynchronization (no import/save/design edit).
A temporary companion browser stays alive to acknowledge native style changes.
Review launch enables ScryWrite transactions and places the part in front of the
current head direction; this is an explicit observation adjustment, not a change
to physical tracking or production defaults. `review-state.json` retains the PID
and launch timing. The owned browser/profile closes when that viewer exits.
