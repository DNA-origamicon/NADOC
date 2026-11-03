# Helical Axis Lines toggle (2026-07-16, out-of-session work) — supporting detail

[Topic head](../../project_reference_geometry.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Helical Axis Lines toggle (2026-07-16, out-of-session work)

View ▸ **Helical Axis Lines** (`#menu-view-helical-axes`, default ON) + the `/` hotkey hide/show the
helix axis arrows via `designRenderer.setAxisArrowsVisible`. Shortcut is `blockedInInput: true` (no
firing while typing). **Caveat worth knowing before touching it:** `setAxisArrowsVisible` is a SHARED
setter — `scene/cadnano_view.js` forces it false on entry / true on exit, and `scene/photo_mode.js`
drives it too. The new `_helicalAxisLinesVisible` flag is module-local to `main.js` and is **not**
reconciled with those, so a cadnano round-trip can silently re-show axes the menu thinks are hidden.

Shipped 2026-05-23. Lets the user build a new origami against an existing one:
mark strands `is_reference=True` and every generative/auto feature ignores them
while they stay visible (translucent) and manually editable. Single-design editor
(3D scene + cadnano-editor window) shows reference geometry; the **assembly view
EXCLUDES it entirely** (2026-05-24, see "Assembly exclusion" below) — a part used
as a backdrop reference inside an assembly renders only its active strands.

`Strand.is_reference: bool = False` (models.py, no migration — default-safe load).
Helpers `Design.active_strands()` / `reference_strands()`.
