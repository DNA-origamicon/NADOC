# API — supporting detail

[Topic head](../../project_overhang_connections.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## API

[backend/api/crud.py](../../../backend/api/crud.py) ~ line 4960:
- `POST   /design/overhang-connections` — body has overhang ids, attach, linker_type, length_value, length_unit, optional name; auto-generates topology.
- `PATCH  /design/overhang-connections/{id}` — name / length_value / length_unit only. Length change auto-rebuilds topology (`remove_linker_topology` then `generate_linker_topology`). Other fields immutable; delete & recreate.
- `DELETE /design/overhang-connections/{id}` — strips metadata + linker strands + virtual helix atomically.

`assign_overhang_connection_names(design)` fills `L{n}` to the smallest unused slot. Survives delete/re-add (preserves existing names).

## Frontend

[frontend/src/ui/overhang_connections_popup.js] (recorded path: `frontend/src/ui/overhang_connections_popup.js`) — three-column popup (overhang A list | controls | overhang B list) + linkers table below. Inline-editable name and length cells (click → input → blur/Enter saves; Esc cancels). Live rule validation disables Generate with inline error. Window stays open after Generate.

[frontend/src/scene/overhang_link_arcs.js](../../../frontend/src/scene/overhang_link_arcs.js) — white tube arc per connection. **Anchors on the LINKER complement strand**, not the OH strand. Two-step lookup:
1. Find OH attach nuc to learn `(helix_id, bp_index)` (5'/3'-flagged tip for `free_end`, farthest-bp nuc for `root`).
2. Find linker complement nuc at the same `(helix_id, bp_index)` on `__lnk__<conn_id>__a` / `__b` (opposite direction → antiparallel partner).

Falls back to OH bead if no linker partner in geometry (synthetic test seed without backing OH domain). Bezier control offset = chord × 0.30 perpendicular to chord. Tube radius 0.30 nm (visibly thicker than backbone beads). DEBUG flag at top of file for console logging.

[frontend/src/api/client.js](../../../frontend/src/api/client.js) — `createOverhangConnection`, `patchOverhangConnection`, `deleteOverhangConnection`.

[frontend/src/main.js](../../../frontend/src/main.js) — popup init + `menu-tools-overhang-connections` click handler. Arc renderer init (`initOverhangLinkArcs(scene)`) with **initial rebuild** after subscription registration (handles persisted designs that loaded before the listener was wired).

## Critical gotcha — `currentGeometry` shape

`store.currentGeometry` is the **bare nucleotides array** (assigned from `json.nucleotides` in [client.js:189](../../../frontend/src/api/client.js#L189)), NOT an object with a `.nucleotides` field. Initial bug: arc renderer read `geometry.nucleotides ?? []` → always empty → arcs never drew. Fix uses `Array.isArray(geometry) ? geometry : (geometry.nucleotides ?? [])`.

## Debug + tests

[scripts/debug_linker_pipeline.py](../../../scripts/debug_linker_pipeline.py) — end-to-end debugger. Run via `uv run python -m scripts.debug_linker_pipeline [fixture.nadoc]` (default `workspace/linker_test.nadoc`). Sections:
- Inspect overhang domains + 5p/3p tags
- Live ds creation → topology + complement validation + geometry emission + arc anchor probe
- Live ss creation → same
- USER-FLOW SIMULATION: load fixture verbatim and probe arc anchors (this is the path the user actually exercises)

The arc-anchor probe mirrors the frontend logic exactly: OH attach nuc → linker partner at same `(helix_id, bp_index)`.

[tests/test_overhang_connections.py](../../../tests/test_overhang_connections.py) — 39 tests covering: rules (8), per-end uniqueness (3), CRUD + name auto-assignment (10), patch (6), strand topology shape (4 — incl. the real-OH-domain seed `_seed_with_real_oh_domains` which mimics extruded overhangs), geometry emission (2), validator quietness (1).

## Files modified / created

**Backend:**
- [backend/core/models.py](../../../backend/core/models.py) — `StrandType.LINKER`, `OverhangConnection`, `Design.overhang_connections`
- [backend/core/lattice.py](../../../backend/core/lattice.py) — `_length_value_to_bp`, `_find_overhang_domain`, `_make_complement_domain`, `_make_virtual_linker_helix`, `generate_linker_topology`, `remove_linker_topology`, `assign_overhang_connection_names`
- [backend/api/crud.py](../../../backend/api/crud.py) — POST/PATCH/DELETE endpoints, `_overhang_end`, `_used_overhang_ends`, `_check_linker_compatibility`; `_geometry_for_helices` skips `__lnk__`; `_strand_nucleotide_info` does NOT skip LINKER
- [backend/core/validator.py](../../../backend/core/validator.py) — skip LINKER in 3 places

**Frontend:**
- [frontend/index.html](../../../frontend/index.html) — Tools menu item (`#menu-tools-overhangs-manager`), modal `#overhangs-manager-modal` with Root/Free-End SVG icons (duplex bundle + diagonal + base-pair rungs)
- [frontend/src/ui/overhangs_manager_popup.js](../../../frontend/src/ui/overhangs_manager_popup.js) — new (renamed from `overhang_connections_popup.js` on 2026-04-30); exports `initOverhangsManagerPopup`, `open(preselect?)`
- [frontend/src/scene/overhang_link_arcs.js](../../../frontend/src/scene/overhang_link_arcs.js) — new
- [frontend/src/scene/selection_manager.js](../../../frontend/src/scene/selection_manager.js) — ctrl+click overhang toggle in `_handleCtrlClickNuc`; cone hit-test hoisted above multi-overhang divert; `_showColorMenu` accepts `ovhgMultiIds` + `onOpenOverhangsManager` and injects the manager entry; new `onOpenOverhangsManager` opt on `initSelectionManager`
- [frontend/src/api/client.js](../../../frontend/src/api/client.js) — 3 client methods
- [frontend/src/main.js](../../../frontend/src/main.js) — popup + arc renderer wiring; `onOpenOverhangsManager` wired to `openOverhangsManager(ovhgIds)`

**Tooling:**
- [scripts/debug_linker_pipeline.py](../../../scripts/debug_linker_pipeline.py) — new
- [tests/test_overhang_connections.py](../../../tests/test_overhang_connections.py) — new

## Status

User-verified in app: ss linker on `linker_test.nadoc` (t1 + t2) shows white tube arc anchored on linker complement beads + complement nucleotides paired antiparallel with each overhang. Full backend suite 725 pass. Frontend builds clean.
