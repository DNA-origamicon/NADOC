# Plates and tubes (IDT ordering layout)

Shipped 2026-05-25. A "Plates and tubes" left-sidebar tab in BOTH the 3D part editor
and the cadnano editor. Lays staple strands into a 96-well plate for IDT ordering and
segregates modified/long staples into an IDT-ready tube list.

## Interaction (added 2026-05-25)
- **Auto-fit on tab open / part load**: `plate_view` fits all plates into the canvas via
  `resetView`, and KEEPS re-fitting on every ResizeObserver tick until the user pans/zooms
  (`_userAdjusted` flag, set on wheel/pan, cleared by resetView + when the pane hides). This
  survives the 3D `#left-panel` width animation (0.15s) — a one-shot fit would lock to a
  mid-animation width. resetView no-ops while the canvas is 0-sized (hidden) and re-fits when
  it gets a real size. 3D MutationObserver(hidden) + cadnano `_setActiveTab` also call resetView.
- **Click a well → select the strand** everywhere: 3D `onStrandClick(sid)` →
  `selectionManager.selectStrand(sid)` (scene glow + sets `selectedObject`, which the 3D
  spreadsheet subscriber highlights + `scrollIntoView`). Cadnano → `pathview.setSelection([sid])`
  + `_spreadsheet.setSelectedStrands([sid])` (highlights + autoscrolls). Empty-well click clears.
  - **GOTCHA (cost ~hours to find)**: side-panel clicks were instantly DESELECTING the strand.
    Cause = the "orbit relay" in `main.js` (~6277): a document `pointerup` listener that
    forwards ANY off-`#canvas` left-release as a synthetic pointerup INTO `#canvas`, so
    OrbitControls can finish a drag that ended outside. That synthetic event hit the selection
    manager's canvas pointerup → raycast misses → `_clearAll()` → wiped the just-made selection.
    Fix: gate the relay with `_gestureStartedOnCanvas` (set from a capture-phase document
    pointerdown = `canvas.contains(e.target)`) so it only fires for gestures that began on the
    3D canvas. Any NEW side panel that sets `selectedObject` on click is subject to this — the
    gate now protects them all.

## Behavior (confirmed with user)
- **Group** = the 3D editor's `strandGroups` (frontend store; localStorage-only, NOT in
  .nadoc). Cadnano editor has no groups → orders by color→length only.
- Auto-fill order: **groupOrder asc (ungrouped last) → color asc → lengthNt asc → strandId**.
- **Orientation is a pure display rotation** — physical well addresses (A1..H12) and fill
  order are identical in both. 8×12 = standard landscape (A–H left, 1–12 top, A1 top-left).
  **12×8 = 90° CLOCKWISE rotation** of 8×12: A1 upper-right, A–H along the top (drawn H..A
  left→right via `_screenToRC` r=7-gc), 1–12 down the RIGHT side. `setOrientation` only sets
  the flag + resetView + save (does NOT re-pack wells). `_rcToWithin` is row-major and
  orientation-independent; `_rcToScreen` 12×8 = {gr:c, gc:7-r}; right-gutter holds the numbers.
  The plate frame (`frameW`) spans the full per-plate width incl. `_rightGutter()` so the
  12×8 right-side 1–12 labels sit INSIDE the perimeter (balanced left padding).
- **Tubes** = staple with ANY modification OR lengthNt > 60. reason ∈ modification|long|both.
  Tube list shows Name/Sequence/Len/Mod/Reason + fixed **250 nmol + HPLC** recommendation;
  per-row Copy + Copy-all (TSV). No plate file export in v1 (on-screen only).
- **Well colors match the editor's resolved staple color.** 3D `_buildRecords` resolves exactly
  like the scene's `nucColor`: `strandColors+group override (eff) ?? buildStapleColorMap(geometry,
  design) palette ?? STAPLE_PALETTE[strand_index]`. It computes `buildStapleColorMap` directly from
  `currentGeometry` (NOT `getHelixCtrl().getPaletteColors()`, which can be null/empty → every
  `color=None` staple fell through to grey #cccccc — the VoltronCore "all-grey wells" bug, fixed
  2026-05-25). Never flat grey. Cadnano uses `ensureStapleColors`+`stapleColorOf` (already pins a
  palette slot for `color=None`, so no grey bug there).
- **Manual moves**: drag wells. Mode cycle **Staple→Color→Group** (Group hidden in cadnano):
  staple = move-to-empty / swap; color/group = rigid translate of the whole unit by the
  drop delta, displaced occupants fall into vacated wells (the part to iterate on UX-wise).
- **Persisted in .nadoc** so layouts survive reload + sync across computers (groups are
  frontend-only so the computed assignments are the cross-machine record).

## Files
- Backend model: `backend/core/models.py` — `WellAssignment`/`TubeAssignment`/`PlateLayout`
  (after `StrandExtension`), `Design.plate_layout: Optional[PlateLayout] = None` (after
  `extensions`). Round-trips via to_json/from_json automatically; NOT in `design_diff` or
  `crud._diff_is_cluster_only` (display-only, no geometry rebuild).
- Backend routes: `backend/api/crud.py` — `PUT /design/plate-layout` (validates strand_ids,
  404 on unknown; plain `mutate_and_validate` + `_design_response`) and `DELETE`. Request
  models `PlateLayoutSaveRequest`/`PlateWellItem`/`PlateTubeItem`.
- Shared frontend module: `frontend/src/ui/plate_view.js` — self-contained Canvas-2D renderer
  (pan/zoom idiom forked from `overhang_pathview.js`, no pathview-internals import). API:
  `initPlateView(canvas, {wrapEl,toolbarEl,getTubesContainer,onSaveLayout,onStrandClick,
  enableGroupMode}) → {setData(strands,savedLayout),autoFill,setOrientation,setSelectionMode,
  resetView,destroy}`. Editors pass a normalized list
  `{strandId,color,lengthNt,groupId,groupOrder,hasMod,modName,sequence,name}`.
- 3D editor: `frontend/index.html` (`data-tab="plates"` btn + `#tab-content-plates` pane +
  CSS `#tab-content-plates:not([hidden]){display:flex}` so the `[hidden]` toggle still hides
  it). `frontend/src/main.js`: `'plates'` added to `TABS`; `initPlatesPanel` block after the
  left-sidebar controller (~10766) — builds records, `MutationObserver` on pane `hidden`
  refreshes on show + clears plate-driven `isolatedStrandId` on hide; store subscriber refresh
  guarded by an inputs-signature so our own plate_layout saves don't reset the view.
  `frontend/src/api/client.js`: `savePlateLayout()`.
- Cadnano editor: `frontend/cadnano-editor.html` (`#cadnano-plates-panel`, `.is-active`
  toggled in `_setActiveTab`). `frontend/src/cadnano-editor/main.js`: `_refreshPlates()` +
  `initPlateView(...,{enableGroupMode:false})`; guarded design-change subscriber.
  `frontend/src/cadnano-editor/api.js`: `savePlateLayout()` via `mutate()`.

## Key gotchas
- Inline `display:flex` on a `.tab-content` pane would BEAT the `[hidden]` hide rule — use a
  `:not([hidden])` CSS rule instead (3D editor).
- The 3D app boots to a welcome screen and locks the sidebar until a design opens through its
  own flow (auto-restore removed). For tests, open via `?open=<workspace-rel path>` (reads the
  `workspace/` library) — a backend `/design/load` into a doc is NOT enough.
- Colors are hex **ints** in the 3D renderer; convert to `#rrggbb` for the plate.
- Render the SAVED layout verbatim; only recompute on explicit Auto-fill (avoids cross-editor
  default-color divergence resetting assignments).

## Tests
- `tests/test_plate_layout_api.py` (8): model round-trip, missing→None, PUT happy/404×2,
  geometry-untouched, DELETE, import round-trip. Full suite green except 2 PRE-EXISTING
  scaffold-router failures (`test_seamed_router`/`test_seamless_router`) unrelated to this work.
- E2E verification (temp, deleted): cadnano + 3D editors against `Examples/NS_trans_fix.nadoc`
  (205 staples, 334 extensions) — auto-fill, tube segregation, persistence.

## Not built (future)
- IDT plate-spec file export (Well Position/Name/Sequence). 384-well plates. 3D-scene click
  highlight uses `isolatedStrandId` (ghosts others) — could be a gentler glow. Block-move
  displacement rule (translate+swap) is a first cut; revisit UX feel.
