---
name: Native .nadoc files preserve absolute positions on load
description: Recentering is reserved for non-native imports (caDNAno / scadnano) only. /design/load and /design/import must NOT call _recenter_design.
type: feedback
originSessionId: 9f1bf930-958e-498b-bcf5-3b65f7fbdd52
---
Native `.nadoc` loads — both `POST /design/load` (server-side path) and `POST /design/import` (browser-uploaded JSON) — must preserve the design's absolute helix positions byte-for-byte. Do NOT call `_recenter_design` from these endpoints.

**Why:** Saved camera framing, multi-design assembly placement, animation keyframes, and user-curated viewports all assume positions are stable across reload. The original implementation called `_recenter_design` on every load (commit 998b63f, "design re-centering pipeline"), which silently shifted XY coordinates so the bounding-box centre snapped to the origin — destroying any of the above. User reported this as a "minor bug" but it was a recurring source of confusion.

**How to apply:** When adding or modifying any endpoint that produces a `Design` from a native `.nadoc` source (file load, browser upload, copy-paste import, restore-from-cache), do not pipe the result through `_recenter_design`. Recentering remains correct (and the default) ONLY for non-native importers where source coordinates are arbitrary:

- `POST /design/import/cadnano` — keeps `_recenter_design`
- `POST /design/import/scadnano` — keeps `_recenter_design`
- `POST /design/center` — explicit user-initiated recentering, always available

Regression test: `tests/test_crud.py::test_load_preserves_native_absolute_positions` asserts that a design built at (100, 50) round-trips through both `/design/load` and `/design/import` with `axis_start.x == 100.0` and `axis_start.y == 50.0` exactly. Keep the test green.

Fixed in branch `feature-log-update`, commit 873f3e6 (2026-05-02).
