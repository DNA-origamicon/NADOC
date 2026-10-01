# VR whole-model doubling investigation — 2026-09-30

A confirmed contributor is competing desktop GPU rendering. The residual physical
headset symptom remains unresolved. The user reports two copies of the whole
model, visible with one eye, especially Ball & Stick enlarged about 10×, broadside
with the whole structure in view, at particular fast movement speeds. After
minimizing the competing desktop window the user reported **reduced**, not gone.

## Retained fix

While native VR is active, the desktop viewer skips GPU draws when its document
is hidden or unfocused. Animation and synchronization callbacks continue. Drawing
resumes on browser focus or native-session exit. WebXR continues rendering.
This avoids unnecessarily sharing the GPU with an unattended molecular viewport.
The real browser launch test verifies a visible but unfocused page's draw counter
stays constant while callbacks increase; unit tests cover focus, visibility,
custom rendering, session exit and WebXR.

No native rendering, shader, quality, shadow, headset tracking or SteamVR setting
changes are retained. Temporary nonblocking GPU stage instrumentation was archived
and removed, and the native viewer rebuilt from the original native sources.

## Evidence and limits

Artifacts: `.development-artifacts/vr-split-20260930/` (workspace archive symlink).

- Controlled identical whole-model runs: `ballstick-whole-phases` had repeated
  presentation in all 354 sampled compositor frames; application GPU p50/p95 was
  7.28/13.23 ms. With the competing Firefox window minimized,
  `ballstick-browser-hidden` had zero repeats/drops in 718 samples and GPU
  p50/p95/max 7.02/7.56/8.11 ms. The runtime refresh was 90 Hz (11.11 ms).
  GPU process sampling independently showed substantial Firefox activity.
- Disabling the desktop mirror did not improve the repeated-frame behavior.
  `ballstick-mirror-off-20-retry` retains that negative result. Waiting after
  image capture also did not eliminate it (`ballstick-settled-20`).
- Physical review used the enlarged broadside view, all geometry in view, and
  real controllers/head tracking. The user reported reduction, then clarified
  that the remaining effect was two whole copies, not balls separating from
  bonds. These reports are stronger evidence of headset appearance than an
  automated screenshot.
- Physical review timing was already mostly fresh 90 Hz before minimizing:
  3,938 samples, zero repeats/drops, GPU p95 7.74 ms. Afterwards: 4,472 samples,
  four repeats and one drop, GPU p95 7.72 ms. Therefore the human A/B alone does
  **not** demonstrate that an improved frame rate caused the reported reduction.
  Sustained frame reuse does not explain all of the remaining symptom.
- Native code inspection found each eye cleared, one stereo projection layer,
  and current model transforms across scene passes. No model motion-blur effect
  was found. Static submitted-eye images did not show duplicated geometry.
  This does not establish what appears through the lenses during fast motion;
  no high-speed through-lens recording was available.
- Timing uses SteamVR's read-only compositor API. Interval membership uses
  polling wall timestamps with approximately 100 ms boundary uncertainty.
  See [Valve's field definitions](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming).

## Reproduction and validation

Debug → VR Tours & Tests → Representation motion now includes whole-model
broadside framing, enlargement through normal grip inputs, and additional
30/60/120 degrees/second peak yaw sweeps. Framing is an observation adjustment
outside measured intervals. All four existing human profiles and the 150 ms
replay deadline are unchanged. Captures occur outside motion intervals, with
settling time before the next measurement.

The new speed sweep initially attempted 60 Hz command input, but ScryWrite
missed the unchanged deadline at 158 ms. That failed run is retained under
`fixed-browser-real-focus`. The diagnostic sweep now uses the existing 20 Hz
transport cadence at the requested peak angular velocities. This can test
transport and rendering under faster model motion; it cannot validate the
smoothness of physical tracking at headset refresh rate. The initial harness
also incorrectly inherited Playwright's forced page focus. The motion harness
now disables that emulation to test actual desktop focus.

Other failed attempts, including old-format snapshots, a launch with missing
mirror-off view configuration, and menu-reach timing failures, remain in the
artifact directory. They are not counted as passing tests. Temporary test
sources/documents are isolated copies, with original-design equality checks.

Focused automated checks: 44 frontend tests and 36 Python motion/tour tests pass.

Final real-browser run: `fixed-browser-matrix` passed all four unchanged profiles
for Ball & Stick and all three speed sweeps. The model was broadside, scale 20
(10× initial scale), at 8 m, fully visible in the submitted eye capture. Across
these measured intervals, 2,477 compositor samples contained zero repeats/drops;
per-interval GPU p95 ranged from 7.57 to 7.80 ms. Speed-sweep maximum input lag
was below 30 ms. `matrix-timing-summary.json` retains the breakdown. The browser
reported no exceptions, four style acknowledgements and unchanged design;
`cleanup.json` confirms temporary source/cache removal and original preservation.
The frontend production build passes. Native build reports no pending work.

This is a successful frame-delivery and input validation, **not** a verified cure
for residual physical-headset doubling. The next useful evidence would be a
through-lens fast-motion recording correlated with compositor timing; another
static mirror capture cannot resolve that boundary.
