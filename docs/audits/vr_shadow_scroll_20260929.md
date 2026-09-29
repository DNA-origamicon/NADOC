# VR shadows and sidebar scrolling — 2026-09-29

Stick and Ball & Stick used unlit constant-width GL lines in the color pass,
although their bonds already cast cylinder shadows in the depth pass. Both now
use the common lit cylinder geometry, shadow sampling, bias and light direction.
Other representations already use the common lit sphere/cylinder/triangle paths.
VDW intentionally omits bonds. Molecular coordinates and exported radii are unchanged.

Touchpad up/down follows adjacent logical rows instead of stopping at the current
page boundary. A newly revealed row slides into view over 200 ms using smoothstep;
scrollbar-focused clicks also advance one row. Simulation Jobs/Visualizations use
the same animation. A first directional click both establishes focus and moves it.
Graphics and controller hit rectangles share a clipped viewport. Fixed custom-panel
headers stay fixed; the existing pointer/page workflows remain available. Catalog
parents provide 22 mm of local panel indentation per category level.

The existing Debug → VR Tours & Tests → Browser-to-headset representation loading
workflow now includes the row-scroll check and before/after stereo/menu captures.
Its page helper intentionally makes eight one-row touchpad clicks. No-op selection
of an already-active representation no longer incorrectly requires a loading event.

## Evidence

Artifacts are under `.development-artifacts/vr-lazy/`:

- `shadow-scroll-matrix`: first down-click and smooth movement passed; the run
  then exposed the test's invalid 100% expectation for reselecting active Full.
- `shadow-scroll-matrix2`: Stick and Ball & Stick each reached 100% and passed
  identifiable model-pixel checks in both eyes. Subsequent Full reaches exceeded
  the unchanged 150 ms timing limit (198/175/174 ms lateness). This is a failed
  heavy-scene matrix, not a four-profile pass.
- `shadow-scroll-final-matrix` and `shadow-scroll-accepted`: the first three menu
  profiles passed; the variable-deliberate acquisition missed on its first reach.
  The latter run was already using the old in-memory probe when the retry fix was
  written, so it repeated that failure. The probe now uses the existing menu
  workflow's three-attempt acquisition policy, preserving misses; deadlines and
  acquisition dwell requirements are unchanged. The browser's final-style oracle
  also now reads the actual requested representation instead of assuming Cylinders.

The test copies the open 24HB into a private `__e2e__` document, launches through
actual browser View in VR, and uses actual browser style acknowledgements. The
observation adjustment centers the model in the tracked view and places the menu
using a simulated wrist; no timing thresholds or production hit geometry change.
Evidence includes submitted left/right images, the native desktop mirror at its
actual resolution, and sampled row positions. The original document is compared
before/after. Private documents/files/caches/viewers are removed in `finally`.

Native checks include all 954 catalog controls, collapse ancestry, positive and
negative line-clipping cases, interrupted/reversed easing, mid-animation hit boxes,
row-to-row focus, simulation lists, and real GL object IDs. Identical bond geometry
matches pixel-for-pixel across bond-bearing representations. Removing an occluder
brightens 36 receiver pixels, establishing an actual cast shadow rather than only
diffuse lighting. VDW uses Full's sphere shader and deliberately suppresses bonds.

No frontend main.js changes in this task (Δ 0). `just lint` retains the pre-existing
unused `pathlib.Path` import in `tests/test_cpd_shape_revision_v2.py`; no new lint
violation. Physical through-lens comfort remains MV-VR-SHADOW-SCROLL.

Application smoke: all 23 tests passed, including real-design render/console and
Close Session teardown. No new backend or browser application behavior changed,
so the native focused checks cover implementation; no broad backend/full sweep
was run for this native-only change.

## Accepted final checks

`shadow-scroll-hydrated/result.json` reports browser success, desktop Full,
zero uncaught browser exceptions and an unchanged private design. Its `native/`
folder records **all four controller profiles**, visible new-row text in both eyes,
and intermediate row positions during scrolling. Three missed acquisitions were
retained before successful retries; there were **zero timing retries** in this run.
The 24HB Full view was used for this final menu matrix. Heavy atomistic shadow
appearance is separately evidenced by the Stick/Ball & Stick captures and real GL
occluder test above; this does not clear dense-scene timing debt.

The preceding `shadow-scroll-four-profiles` also passed all four native profiles,
but its browser snapshot check found `before=null`. The diagnostic
`shadow-scroll-browser-snapshot` confirmed this was a test-startup race, not a
design mutation: geometry became available before `currentDesign`. The wrapper
now waits for the specific copied document's populated metadata before taking
its baseline. Full before/after snapshots are retained in the final run.

Final CTest: **5/5 passed** (sidebar, grips, menu layout, simulation panel, real GL).
Smoke: **23/23 passed**. Logs and explicit PID/sidecar/document/file/cache cleanup
checks for all seven isolated attempts are in `shadow-scroll-validation/`.
No private workspace artifacts remain; every run confirmed the original document
unchanged. No test viewer remains running. The rebuilt native viewer is ready for
normal launches. Submitted stereo/mirror pixels establish rendering; physical
headset comfort and OS-window occlusion are not established by these captures.
