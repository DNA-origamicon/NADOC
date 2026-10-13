# VR trajectory loop controls — 2026-10-12

The focused simulation playback menu now has **Loop On/Off** beside Smooth.
Loop Off preserves the previous stop-at-end behaviour. Loop On repeats only the
selected Start/End/Every samples, without interpolating across the wrap. The
choice survives range changes and reloads within a job, resets Off on another
job, and is disabled for a single-frame selection. Loading/progress and the
16-frame/two-page memory bound are unchanged. Native component previews share
this control. Snapshot protocol 3 carries the flag; the native reader also accepts
protocol 2 as Loop Off. `main.js` remains 7,363 lines: task delta **0**.

The live check also exposed ISSUE-74: disabled transport rows intercepted digits
in the source-frame popup. Modal controls now precede their background in hit
testing; actual rays to all ten digit centres are covered by a native regression.

## Verification

- Frontend: **7,893 passed, 1 skipped**, all 669 files. Includes exact sampled
  wraps, Loop Off at the end, toggling during play, pause, reload/job reset,
  singleton ranges, evicted first-page reload, no wrap interpolation and native
  event deduplication.
- Backend snapshot/event tests: **4 passed**.
- Native trajectory and simulation panel tests: **2 passed**, including protocol
  compatibility, button state and popup ray ownership.
- App smoke: **23 passed**, with isolated workspaces and teardown.
- Initial steady-fast live pass: `initial-coalesced/result.json`.
- Final four-profile campaign: **steady-fast, steady-deliberate and variable-fast passed**.
  Variable-deliberate hit a 155 ms input-timing stall during initial Simulations-tab
  setup, before the loop controls were exercised. It remains unverified; thresholds
  were not relaxed. See `focused-final/result.json` and `review.json` below.

The reusable test uses the real completed `2hb_1xT` P1 RunPod job `7d5937e569c6`,
1,226 source frames sampled every 7 (176 selected). The focused
loop campaign plays the selection to its end, requires stopping on the final sample
with Loop Off, enables Loop, verifies a return into the selected source range,
then pauses. The general tour still uses native exact-frame entry for very large
ranges. The final capture checks control pixels in both eyes, a displaced
negative control, actual model pixels, and delivery to the desktop window.
The menu snapshot transport coalesces updates during page loads, so this live
check verifies a wrap, not delivery of every sample. Player regressions separately
assert the exact first sample is rendered at each wrap. No continuous 90 FPS or
physical through-lens legibility claim is made by these checks.

Observation uses the existing tour's ordinary menu/model grips and enlarged
mirror. Motion profiles, timing thresholds, hit geometry and production defaults
were not changed to pass the checks. Physical hand/legibility review is tracked
as the trajectory-loop follow-up to MV-43.

## Retained failures and unrelated gates

- `build.log`: first compile found a test using `selected` instead of the actual
  `SidebarControl.active` field. Corrected; final native builds/tests pass.
- `initial/`: digit 2 failed acquisition because of ISSUE-74; not a noise-profile
  exception. The fixed popup passed the subsequent exact-entry checks.
- `initial-popup-fixed/`: an overly strict live oracle expected every ready-state
  snapshot at the wrap. The retained network trace shows repeated 175→1 menu
  updates while looping (frame 0 can be coalesced during the page load).
  `observed-frames.json` retains the extracted evidence. The revised live oracle
  verifies wrap direction and source/interval consistency, with exact rendering
  covered independently by the player tests.
- `final/`: both steady profiles passed the popup-assisted checks. Variable-fast
  missed numeric key 1; variable-deliberate missed the source-frame popup opener,
  each after the unchanged three attempts. These remain pointer-tolerance debt.
  `focused-final/` tests the requested loop control by letting the bounded default
  selection finish, without depending on numeric entry. Its wrap predicate also
  requires playback to be active on both sides, so manual restart is not counted
  as looping. No popup pass is inferred from this separate focused campaign.
- First broad backend run: 10,733 passed, 92 skipped, two Alpine socket-fixture
  failures and four existing CPD setup errors. The task's long Archive TMPDIR
  exceeded AF_UNIX path length; using `/media/jojo/Archive/nl` cleared both failures.
  All eight Alpine tests passed in 3.14 s. A 5.2 s peer test repeated at 0.61 s
  call time; no tests were reclassified or guard budgets changed.
- Backend rerun decision **FAST**: **10,735 passed, 92 skipped, 4 existing CPD
  setup errors** (`Incorrect preview stereochemistry: cis-anti-I`). No individual
  test exceeded its 5 s limit; aggregate runtime 105 s exceeded the 90 s backstop.
  The unrelated CPD chemistry and global test registry were preserved.
- `just lint`: the same five existing unused-import findings, outside this change.

The broad-suite selector reported verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

## Evidence and repeatability

Artifact root: `.development-artifacts/vr-trajectory-loop-20261012/` (Archive).
The failed attempts are retained alongside the final captures, playback traces,
unit/build logs, smoke inventory and timing evidence.

Discoverable route: **Debug → VR Tours & Tests → Left sidebar → Simulation jobs ·
representations + trajectory loops**. Set `NADOC_VR_SIM_LOOPS=1` for the focused
loop campaign; the standard tour also includes these checks. The source design,
job metadata and caches are copied into a disposable private workspace; only
immutable trajectory inputs are symlinked. No new simulation runs are launched.

The validated viewer was installed under the normal build lock at
`native/vr_viewer/build/nadoc-vr-viewer`; SHA-256
`2ac4d8fbae6d6b6f7d7b8de21640ff15f997c47ad6cf4dea18ef22605ce64915`.
The three completed focused profiles each passed both-eye loop-control pixels and
actual desktop-window delivery. Their ten-second quiet playback intervals reported
90 Hz with no dropped/reprojected compositor samples. Startup/loading/capture and
the failed input interval are not covered by that steady-playback observation.

Cleanup verified: both owned Archive scratch roots and private test workspaces
were removed; no `__e2e__` workspace designs, test-results link or owned viewer
remains. Existing SteamVR compositor, backend and Vite processes were preserved.
`cleanup.json` records 961 retained evidence files (676,753,549 bytes before this
final audit update).
