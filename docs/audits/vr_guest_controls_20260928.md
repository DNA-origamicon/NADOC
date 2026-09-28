# VR menus and tools in guest presentation — 2026-09-28

The guest receives the actual native sidebar/menu pixels and tracking-space tool
line vertices with VR presence. Both controller sidebar menus, the two-column view
icon tablet, legacy/desktop panels, pointing rays, selection volumes, radius wheel,
scissors, nick glow, ligation and resize guides share the avatar's exact inverse
model transform. Their source is the existing XR renderer; there is no duplicate
menu implementation or guest action handler. Closing a panel removes it; the Show
VR model toggle and tracking/session expiry hide the whole presence group.

Panel PNGs retain alpha where appropriate; X11 desktop's unused alpha byte is
explicitly made opaque. Native texture readback/encoding is cached by content
version. Readback uses a pixel-pack buffer with a nonblocking fence poll, followed
by background PNG encoding; each panel has at most one job in flight. Guest textures are reused/disposed as panels change or close. Room SSE
sends unchanged image data only once per connection, with full images on a fresh
connection. A captured left Share menu packet measured 181 KB before texture reuse;
exact full/delta payload measurements are in `transport-metrics.json` beneath the
evidence root. These are payload measurements, not an internet latency benchmark.

All input remains local to the presenter. Guest geometry lives outside scientific
scene exports, topology and history. Authenticated host management uses the existing
room/revision-bound presence path; inline PNGs and vertex arrays are bounded and
validated. Desktop pixels are included only while that native desktop panel is open.
No new share/link creation path was added. `frontend/src/main.js` LOC change for this
task is **0** (its existing uncommitted Share integration predates this task).

## Observation and retained diagnostic attempts

Evidence root: `.development-artifacts/vr-presence-ui/`.

- `initial`: the existing SSE writer treated Node's `write(false)` as failure and
  disconnected immediately on the first large menu packet. Fixed with a bounded
  latest-state pending slot and drain handling, with a five-second stall timeout.
  Host regression tests cover coalescing, including retaining required images.
- `drain-fixed`: launch timed out because a just-edited native header caused an
  implicit rebuild. Subsequent campaigns explicitly waited for the native build.
- `stream-fixed`: menu text was visibly present, but at the whole-avatar framing
  its small antialiased strokes did not meet exact color sampling. The guest review
  was reframed closer and at 1920×1080; input paths and the 60% coverage threshold
  were unchanged. `framed` passed all then-existing stages.
- `final`: the slower profile's wheel pixels passed, but the test's held input lease
  expired during guest review, so its later Nick-selection assertion failed. Review
  now renews the lease at the actual measured endpoint; this is outside the measured
  profile reach. It does not snap to a target or change acquisition thresholds.
- `final2`: a view-tablet reach missed the existing timing budget (159 ms late, limit
  150 ms) while other browser checks were running. That attempt is retained. The
  later campaigns run without concurrent browser tests; timing limits are unchanged.
- `final3` completed every stage for steady_fast, including the desktop panel. Its
  steady_deliberate run stalled during a later reach (317 ms). A 750 ms pause
  between capture stages did not eliminate the timing problem: `settled-steady-deliberate`
  stalled at 244 ms; `variable-fast` passed all stages except the final desktop-menu
  reach, which stalled at 526 ms.
- Synchronous texture readback/PNG work was an avoidable blocking operation, so the
  final native exporter uses asynchronous GPU readback and background compression.
  `async-final` passed menu, tablet, close, wheel and scissors pixels, then the input
  driver stalled at 520 ms after the VR model had been disabled. This demonstrates
  that texture encoding does not explain all remaining timing failures. No motion
  threshold was relaxed, and the four-profile campaign must not be reported as green.

The review camera faces each panel and retains normal geometry occlusion. Positive
checks compare native text/icon or guide colors to actual guest canvas pixels at
projected positions. Offscreen negative controls must fail. Off checks require the
presence hidden and fewer than 100 avatar-colored pixels. Submitted stereo eyes,
native mirror, real guest screenshots, endpoint poses and motion profiles are saved.
These checks do not establish physical through-lens comfort or readability from
arbitrary guest viewpoints; see `manual_validation_debt.md`.

## Software checks

- Native build passed with no new warnings; frontend production build passed with
  the existing large-chunk advisory.
- `just test-frontend`: **7,160 passed, one skipped**, 554 files passed.
- `just smoke`: **23 passed**, isolated temporary workspace removed.
- Prepared host/presence tests: **15 passed**. Local backend feed tests: **4 passed**.
  Debug tour catalog/launcher tests: **27 passed**.
- `just test-smart`: **decision FAST**, **9,357 passed, 93 skipped, one failed**.
  The existing failure is `tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`;
  geometry sources were not changed. Runtime budget passed: `test time: 49s / 60s ok`.
  `DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.`
- `just lint` reports the unrelated unused `pathlib.Path` import in
  `tests/test_cpd_shape_revision_v2.py`. Focused lint of changed backend/tour tests
  passes; the unrelated file was left untouched.

The discoverable review route is Debug → VR Tours & Tests → Left sidebar →
**VR menus and tools in guest view** (demo or four-profile validation).

## Final evidence and cleanup

The **final asynchronous exporter** completed the entire variable-deliberate run:
`.development-artifacts/vr-presence-ui/variable-deliberate/result.json` is passed.
All nine stages passed: left menu, right menu, view tablet, closing, wheel, scissors,
hide, show and desktop panel. Positive guest-pixel coverage ranged from **82.8% to
99.5%**; the hidden stage contained **zero** avatar-colored pixels. Every offscreen
negative control failed as intended. The final share-end guest assertion also passed.
Earlier steady-fast completed the full sequence before asynchronous readback was
introduced. Other campaigns were interrupted by the documented timing stalls;
**four-profile validation remains incomplete**, not a pass with relaxed tolerances.
All four profiles were attempted. `guest-pixel-summary.json` records every retained
stage verdict by run/profile without conflating partial runs with complete passes.

No native viewer, temporary test workspace/host fixture, or frontend test output
remains. The three preexisting host control/status files were preserved. The cleanup
inventory is `cleanup-verification.json`. About 9.7 GB of unused raw native depth,
picking-ID and class buffers were removed only after verifying that these guest/menu
pixel checks do not consume them. PNGs, native metadata/object inventories, motion
samples, trace archives and all failed-attempt evidence remain. Future captures in
this workflow copy that narrower evidence inventory. Logs are retained under `logs/`.
