# Bounded VR touchpad navigation — 2026-09-27

The old sidebar used a circular flattened target list for up/down and changed
tabs immediately on left/right. The tour also depended on walking that list.

Sidebars now navigate by their visible columns. Up/down clamps within the tab
strip or content; only left/right crosses the scrollbar. Left-hand layout is
mirrored. Scrollbar up/down still pages without losing focus, and lateral exit
uses the entry height. Same-row icon/footer controls are reachable laterally.
Tabs require Trigger. Gray controls stay focusable and inert. Initial focus
uses the pointed-at control, falling back to the active tab. Center-click and
deliberate pointer dwell retain their existing handoff behavior. Detailed-menu
lists also stop at their ends.

Validation:
- Native build and all 41 CTest tests passed, including mirrored boundary,
  lateral crossing, gray control, scrolling and pointer arbitration regressions.
- Existing Debug → VR Tours & Tests → Controls & layout → Trackpad, pointer,
  cards & scrollbars now uses lateral navigation and checks bounded columns.
- All four unchanged human-motion profiles passed, steady_fast first.
- 40 stereo menu pixel reports passed; actual X11 mirror check passed
  with matching_fraction 1.0 at the unchanged required_fraction 0.95.
- Inspected retained mirror images: focused footer and right scrollbar are
  visibly highlighted with menus docked side by side below the tracked eye.
  These are rendered-eye/desktop checks, not physical through-lens comfort tests.
- Viewer exited cleanly after validation.

Evidence: [.development-artifacts/vr-bounded-focus/validation-2](../../.development-artifacts/vr-bounded-focus/validation-2).
The retained validation-1 attempt stopped on a stale test assumption that
Visualization had an unavailable first-page representation. That page is now
implemented. The gray-control test now uses Assembly; no thresholds or motion
profiles changed.

Replay:

```sh
uv run python -m tools.vr_workflows.menu_tour --focus-checks --validate
```
