# VR Confirm dismissal and menu formatting — 2026-10-05

Accepted Extrude Confirm closes the painter and right-hand menu immediately,
stops wheel motion, and hides the draft preview. The asynchronous commit retains
its original configuration and target. Success clears the draft while preserving
the committed feature for Undo. Failure/refusal restores the same settings page
and draft, requests fresh validation, and allows a safe retry. Subsequent selection
changes cannot redirect that retry or the feature-bound Undo.

The formatting pass covers Part and Assembly sidebars, all scroll pages and
collapsed sections, Extrude/Move/Bend/Twist, saved dimensions/volumes, simulation
jobs/results, legacy Options/Tools/settings/jobs/trajectory/desktop, radial menus,
desktop chrome, View Tools, loading panels, and the three component galleries.

Changes include padded shared text regions, bounded wrapping and explicit ellipses
for long dynamic content, progress-bar separation, readable vertical tabs, larger
legacy frame clearance, separate Options subtitle/heading rows, bounded settings
columns, and separation between radial labels and hover markers. The View Tools
footer now limits long errors and unbroken identifiers to its reserved area.
The native View Tools grip frame has a separate outer bound, leaving 20 mm
between its inner rails and the browser texture. Its icon size, UV mapping and
click targets are unchanged; local and remote grip handling share the new frame
bounds. Combined rendering caught this collision after the browser canvas alone
passed, so the native regression also checks frame/content separation.

Rendered inspection also found two cache problems: transparent text lost contrast
when its antialiased color was multiplied by alpha a second time, and first-time
menu texture allocation failed to restore the caller's framebuffer. Transparent
ink is now normalized before frost/blending; texture updates retain the original
draw/read framebuffer across first allocation and resizing.
Wide menu caches also preserve their aspect ratio after the texture-width cap,
preventing excess filtering of thin desktop-header text.

## Verification and review routes

- Shared native audit: **12,001 layout states** passed, including long labels,
  disabled/active states, all five simulation engines, and scrolling transitions.
  It checks text against text, unrelated controls, progress tracks, bounds and
  the minimum font scale. Nine focused native panel/layout tests passed.
- Full frontend suite: **7,375 passed, 1 skipped** across 596 files.
- Real browser checks: View Tools normal/long/unbroken status rendering passes;
  the browser Extrude commit test passes draft clearing, deduplication and Undo.
- Native/browser OpenXR `steady_fast`: accepted Confirm immediately dismisses
  both windows; successful acknowledgement clears the editor/configuration/draft
  while leaving Undo available. Six 48 bp helices are committed at rows 1–2 next
  to an existing 1×8 square platform, with the expected 2.25 nm lattice pitch.
- Native lifecycle regressions cover rejected/refused/stale feedback, frozen
  selection targets, fresh validation on retry, and feature-bound Undo.
- Final production render atlas: **425 states passed**, with no layout, missing
  image or pixel failures. Initial texture allocation and actual texture resizing
  both preserve the caller's framebuffer; an offscreen negative control fails
  visibility as expected. Desktop title/help/Close each remain visible at normal
  and wide aspect ratios, including the default 0.75 panel scale.
- The final viewer and lifecycle test binary were rebuilt after the rendering and
  retry/Undo fixes; all four focused native tests passed (Extrude panel/lifecycle,
  ScryWrite live interaction and GL object IDs). The live interaction test includes
  both wheel locators/ownership and View Tools icon clicks/border dragging.
  The actual live commit
  predates the final Undo-target and texture-cache refinements; those are covered
  by the final native regressions and rendered atlas respectively. The later View
  Tools frame correction has separate eight-icon and grip regressions.
- Initial live menu tour on the final binary: **13 visible Part tabs, 92 controls**
  passed both-eye layout/pixel checks, disabled inputs, menu actions and native
  desktop interactions. The delivered desktop image matched the captured mirror
  with 23,356 visible feature pixels. Assembly-only coverage is in the separate
  140-state rendered group.
- All four motion presets have a passing individual tour on the same final
  binary: `steady_fast`, `steady_deliberate`, `variable_fast` and
  `variable_deliberate`. Each covers 13 pages/92 controls and delivered desktop
  agreement of 100%. **The combined final matrix did not pass**: its two
  steady-fast attempts hit the retained scheduling limits described below.
  This establishes functional/render coverage across profiles, not reliable
  timing acceptance. The workflow regression suite passed 42 tests.

The reusable **Debug → VR Tours & Tests → Controls & layout → Menu formatting
review** produces full-resolution images, contact sheets and a browsable atlas:
`uv run python -m tools.vr_workflows.menu_render_audit --validate`.
An optional `--viewtools-stream` file/directory renders actual browser-produced
icon textures, including the retained normal and long-error cases.

Evidence roots:

- Final browsable atlas: [current-07/index.html](../../.development-artifacts/vr-menu-formatting-20261005/current-07/index.html)
- Atlas verdict: [current-07/summary.json](../../.development-artifacts/vr-menu-formatting-20261005/current-07/summary.json)
- Confirm lifecycle and cleanup: [confirm-validation.json](../../.development-artifacts/vr-extrude-confirm-close-20261005/confirm-validation.json)
- Live profile results: [live-menus/summary.json](../../.development-artifacts/vr-menu-formatting-20261005/live-menus/summary.json)
- Cleanup and retained artifact inventory: [cleanup-summary.json](../../.development-artifacts/vr-menu-formatting-20261005/cleanup-summary.json)
- `.development-artifacts/vr-menu-formatting-20261005/`
- `.development-artifacts/vr-extrude-confirm-close-20261005/`
- Shared layout log: `.development-artifacts/vr-extrude-window/menu-formatting/`

## Observation limits and retained failures

The initial live menu attempts exposed two stale test-driver assumptions: an
Assembly-only tab was expected in Part mode, and active blue outlines were
measured only inside their borders. Context-only skips are now explicit; all
other missing tabs still fail. Active outlines have a separate pixel region with
a negative case that erases the outline. Existing text checks, motion profiles,
and timing thresholds are unchanged. Original failed captures remain retained.

The first final motion matrix stopped during `steady_fast` at the detached
desktop Close reach: playback was 0.153 s late against the existing 0.150 s limit.
Twelve of thirteen sidebar pages had passed; the earlier complete initial tour
also covered Share and desktop Close. This attempt overlapped the final native
test build/run, a possible contributor rather than an established cause. One
retry was started after that work ended; any recurring failed preset remains a
failure, with remaining unattempted presets run separately. The retry again
hit the guard during Grip playback (0.155 s); its timing result remains failed,
with no further retry. No timing limit was
relaxed and no production motion change was made for this observation failure.

The initial native Confirm attempt opened its menu before startup finished and
therefore found no controls. The probe now uses the existing startup-readiness
wait. The subsequent actual commit passed; the initial failure remains retained.

Early atlas attempts exposed an X11 size clamp and framebuffer restoration issue;
their metadata is retained, but their cropped pixels are not final coverage.
The corrected atlas uses a dedicated 1200×1200 framebuffer and records an
offscreen negative control. Colored radial ink is measured separately from neutral
text. Desktop title/help/Close each have their own text-pixel region, so visible
frame borders cannot stand in for readable text.

The retained source comparison predates the legacy/frame/radial corrections;
it already contains the first shared-text audit edits and is not a pristine
before-image of the entire task. Final layout images use explicit front-facing
panel poses for observation. Actual OpenXR/controller evidence is separate.
Neither establishes human through-lens legibility or physical reach comfort;
those remain under MV-38. Frontend `main.js` LOC delta: **0**.

All eight owned live-menu viewer processes, sockets and temporary workspaces
were verified absent after testing. Browser Confirm teardown removed its isolated
test project and document. Atlas fixture copies were removed and its renderer
exited. Useful images, failed attempts, source comparisons and test logs remain
under the development-artifact roots; user workspace designs were not changed.

## Publication integration

Merged the newer desktop pattern-tool commits `e4521d7c` and `68fd350f` in an
isolated checkout before publishing. Both issue-log histories were preserved.
Regenerated the sidebar catalog against their updated desktop source: obsolete
unsupported Properties copies of floating Extrude/Twist controls are removed,
and the new cluster-repair button is listed with its existing unsupported status.
The native Extrude/Bend/Twist editing panels are unchanged.

The combined tree passes 7,408 frontend tests (1 skipped), 26 lattice-context and
3 empty-scene backend tests, all four focused native sidebar/layout/spacing/Extrude
panel tests, and the generated-catalog check. The earlier 425-state atlas and
live tours describe the pre-integration catalog; the refreshed catalog was checked
by the native geometry tests, without repeating the entire live matrix. Logs are
retained as `publish-*` under the menu-formatting evidence root.
