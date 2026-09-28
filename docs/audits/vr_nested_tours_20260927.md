# Nested Debug tours and visible representation demos

Debug → VR Tours & Tests → Right sidebar → Visualization demo directly launches
representation switching for a read-only snapshot of the active individual document,
including unsaved edits. The document header selects the session; there is no UI
fallback to the fixed benchmark file. Empty documents and assembly mode produce
an actionable error. The CLI still defaults to 24hb_0xT for repeatable benchmarks.

Categories and demo/validation entries are nested flyouts; descriptions are
standard tooltips. No modal or clipboard step. Stop and status remain available.
Leaf flyouts scroll within the viewport. The legacy authoring workflow remains
disabled because it requires its established owned idle viewer.

The viewer waits for its normal stable tracked-eye placement, uses an isometric
view at scale 3 / distance 1.3 m, explicitly closes the left menu, and moves the
right panel 0.35 m along its own horizontal axis with normal controller grip input.
Framing checks require design pixels in both submitted eyes, no edge clipping,
and a horizontal gap from the menu. Negative unit cases cover missing, clipped,
and menu-overlapping designs. These changes affect tour observation settings,
not motion profiles, production defaults, or physical head tracking.

Evidence is under `.development-artifacts/vr-representations/`:

- `nested-menu-steady`: 12 directed transitions passed, submitted-eye captures
  visibly show the origami separate from the menu; desktop pixel check passed.
- `nested-menu-validation`: preserved failed attempt, stopped on loss of OpenXR
  focus during the second controller profile. VSCode also crashed during this
  period; the available logs do not establish the cause. All test processes had
  exited on resume. Subsequent VR validation runs separately from other tests.
- `nested-menu-validation-isolated`: all 48 transitions passed across four
  controller profiles, at least 162,189 design pixels per eye and a minimum
  16 px gap from the right menu. Desktop pixel comparison passed (1.0 matching
  fraction). Owned viewer closed cleanly; no remaining test runners.
- `nested-browser-fixed.log`: real Chromium flyout navigation, tooltip and launch
  request passed. Earlier browser attempt exposed a bottom-of-viewport leaf;
  viewport positioning and scrollable leaf menus corrected it.
- `nested-backend-fixed.log`: 7 tests passed, including document-header binding,
  snapshot contents, no-design/assembly errors, fixed commands and owned stop.
- `nested-framing-tests.log`: 3 tests passed.
- `nested-frontend.log`: 546 files, 7,085 passed / 1 skipped. Subsequent focused UI
  rerun passed after keyboard semantics and polling changes (`nested-ui-final.log`).
- `nested-smoke.log`: 23 passed; teardown removed test workspace artifacts.
- `nested-smart.log`: 9,290 passed / 92 skipped; pre-existing failure in
  `test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree` persists.
- Ruff and whitespace checks passed. Browser reports/traces cleaned by the
  existing reporter; no remaining `__e2e__` workspace files.

Broad-suite deferral reported by test-smart:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Stereo evidence establishes application-submitted rendering, not through-lens
headset comfort. Native timing still excludes browser polling delay. The tour does not write
to user source files; run snapshots and screenshots are retained as evidence.
Physical regression runs reuse the earlier exported 24hb_0xT snapshot. The
active-document selection and unsaved snapshot path are separately covered by
launcher tests.
