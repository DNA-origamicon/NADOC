# ds-linker bridge — CG vs atomistic alignment (2026-05-05) — supporting detail

[Topic head](../../project_overhang_connections.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ds-linker bridge — CG vs atomistic alignment (2026-05-05)

**KEY:** the bridge has TWO separate placement formulas that MUST stay in lockstep:
- **CG path** (`_emit_bridge_nucs` in `crud.py`) → `bridge_axis_geometry(...)` in `linker_relax.py` — axis is **offset perpendicular to chord** by `−(radial_a + radial_b) / 2 * R` so boundary beads colocalize with OH anchors at native B-DNA radius.
- **Atomistic / stored helix path** (`_make_virtual_linker_helix` in `lattice.py`) — fixed 2026-05-05 to also call `bridge_axis_geometry(p_a, n_a, p_b, length_bp, comp_first_a, comp_first_b)` for `axis_start`/`axis_end`. Falls back to chord-midpoint on exception (legacy designs).

Before the fix: atomistic linker atoms placed ~1 nm off from CG bridge beads (chord-centred vs offset axis). User reported "linker bridge missing in atomistic mode" — it wasn't missing, it was just hovering nearby in the wrong spot.

**Don't break:** if you change the offset formula in `bridge_axis_geometry`, change `_emit_bridge_nucs`, `_bridge_boundary_radials`, AND `_make_virtual_linker_helix` together. The relax loss in `_arc_chord_lengths` is intentionally chord-magnitude-only (folding the perpendicular offset into the loss creates a degenerate minimum at chord ≈ 0).

**Three entry points:**
1. **Tools → Overhangs Manager…** — global menu (`#menu-tools-overhangs-manager`). Opens with whatever's in the current overhang selection.
2. **Right-click a strand while 1–2 overhangs are selected** — the strand color menu (`_showColorMenu` in [selection_manager.js](../../../frontend/src/scene/selection_manager.js)) injects an "Open Overhangs Manager (N selected)…" item at top. Wired via new `onOpenOverhangsManager(ovhgIds)` callback in `initSelectionManager`. Cone hit-test was hoisted above the multi-overhang divert so a strand-cone right-click reaches the strand menu instead of the OH context menu.
3. **Ctrl+click overhangs** when `selectableTypes.overhangs` is on — toggles in/out of `multiSelectedOverhangIds`, capped at 2 (oldest drops via `slice(-2)`). Implemented in `_handleCtrlClickNuc` early branch. Lasso multi-select unchanged.

The popup's `open(preselect?)` accepts an optional ids array (up to 2). With no arg it pulls from store: `multiSelectedOverhangIds` first, then `selectedObject?.data?.overhang_id`. Side A and Side B fill in array order. Validated against the live `currentDesign.overhangs` list — stale ids are dropped.

## Data model

`OverhangConnection` lives on `Design.overhang_connections` ([backend/core/models.py](../../../backend/core/models.py)):
- `id`, `name` (auto L1, L2, …), `overhang_a_id`, `overhang_a_attach`, `overhang_b_id`, `overhang_b_attach`, `linker_type` ("ss"|"ds"), `length_value`, `length_unit` ("bp"|"nm").
- `attach`: `"root"` = embedded end on bundle; `"free_end"` = protruding tip.

`StrandType.LINKER = "linker"` added to the enum. Linker strands are auto-generated; never user-created directly.
