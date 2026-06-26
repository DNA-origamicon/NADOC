---
name: massive-cadnano-overhaul-2d-editor-assembly-model
description: "Full cadnano2-style 2D editor in a separate browser window, synced bidirectionally with the 3D view. Multi-part assembly model. Project layer over Designs."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9ac097d7-4b99-419f-8753-a7c212c71496
---

# Massive caDNAno Overhaul

Branch: `feature/massive-cadnano-overhaul`

## Goal
Replace the read-only K-key cadnano view with a true interactive 2D editor in a
separate browser window/tab. Each "Part" gets its own 2D editor tab. Multiple
Parts compose an Assembly in 3D. Scaffold continuity is tracked across Parts via
a new Connection element.

## Locked Decisions (all confirmed)

| Decision | Choice |
|----------|--------|
| 2D window model | Separate browser tab, one per Origami |
| Communication | BroadcastChannel + shared FastAPI backend (backend is ground truth) |
| Multi-file data model | Assembly > Origami hierarchy |
| Phase 1 scope | Scaffold drawing only (no staple painting yet) |
| Lattice types | HC and SQ only — FREE lattice DELETED with extreme prejudice |
| Pathview renderer | HTML5 Canvas 2D API |
| Sliceview renderer | SVG |
| K-key mode | Unchanged, kept as-is |
| Origami positioning in 3D | Option C — prompted dialog on creation |
| Scaffold model | Scaffold-per-origami (Option A); auto-routable; Connections link across origami |
| Scaffold length display | Properties panel when scaffold selected (3D); hover → bottom-left corner (2D editor) |
| Group | Existing concept — color-coding for spreadsheet organisation. No new model needed. |

## Confirmed Hierarchy Vocabulary

```
Assembly
 └─ Origami          (one per 2D editor tab; internally still called Design)
     ├─ Cluster       (ClusterRigidTransform — intra-origami rigid group, unchanged)
     └─ Group         (named color/label set for spreadsheet sorting — unchanged)
Connection           (cross-origami strand link — scaffold OR staple/overhang)
```

- **Assembly**: top-level container. Owns N Origami. Shown in the 3D window.
- **Origami**: one HC or SQ design. Gets its own 2D editor browser tab. Has its
  own scaffold strand(s). Positioned in 3D space by a transform relative to the
  Assembly origin. Internally still the `Design` class (rename deferred to Phase 3).
- **Cluster**: unchanged. Rigid subgroup within one Origami.
- **Group**: unchanged. Named color/label set for spreadsheet use. No topology role.
- **Connection**: NEW model. A cross-origami strand link. Can be scaffold→scaffold or
  staple→overhang (any strand type). Shown in the 2D editor as a labelled terminal
  arrow: "→ Origami X". In 3D shown as a flexible arc/tube. Contributes to total
  cross-origami strand length. Implementation of user interaction TBD (Phase 3).

## Phase Plan

### Phase 1 — 2D Editor Shell + Scaffold Drawing
Scope:
- Remove FREE lattice from backend + frontend (pre-req)
- Serve 2D editor HTML from existing FastAPI server at `/cadnano`
- Sliceview (SVG): HC/SQ lattice grid; click cell → activate/deactivate helix
  (calls existing add-helices / delete-helices API)
- Pathview (Canvas 2D): activated helices as horizontal double tracks;
  click+drag to draw scaffold path; auto-scaffold button calls existing API
- BroadcastChannel "nadoc-design" channel:
    2D editor mutation → POST API → sends BC message → 3D window re-fetches
    3D mutation → sends BC message → 2D editor re-fetches and redraws
- Scaffold length shown in pathview hover tooltip (bottom-left)
- No Assembly/Connection/multi-origami in Phase 1 — single Design only

Validation gate:
1. Open NADOC 3D, open /cadnano tab
2. Click hex cells → helices appear in 3D immediately
3. Click 3D context-menu → add helix → appears in sliceview
4. Draw scaffold in pathview → scaffold strand visible in 3D
5. Hover scaffold in pathview → nt count shown bottom-left

## Phase 1 Tactical Decisions (all locked)

| # | Decision | Choice |
|---|---|---|
| T1 | Design vs Origami rename | Keep `Design` internally; UI labels say "Origami" |
| T2 | FREE lattice removal | Isolated first commit before any feature code |
| T3 | 2D editor serving | Vite multi-page app (second entry point in same config) |
| T4 | Connection model | Skip entirely — add only in Phase 3 |

### Multi-tab note (T3)
BroadcastChannel + backend-as-ground-truth means multiple `/cadnano` tabs open
simultaneously will all stay in sync automatically — each tab re-fetches on any
BC "design-changed" message. No extra work. Two `/cadnano` tabs open side-by-side
is explicitly supported and free by design. In Phase 3 each tab adds
`?origami_id=X` query param to scope to a specific Origami.

## All Phase 1 UX Decisions Locked

| # | Decision | Choice |
|---|---|---|
| P1-A | Default helix length on sliceview click | 42 bp fixed default |
| P1-B | Scaffold drawing UX | cadnano2-style cell-by-cell pencil tool |

### Pencil tool model (Phase 1)
Click-drag on FORWARD or REVERSE track → creates a scaffold domain on that helix
covering the dragged bp range. Each painted segment is initially disconnected. User can also run
auto-scaffold to route/connect painted segments.
New endpoint: `POST /design/scaffold-domain-paint`
  body: `{helix_id, direction, bp_start, bp_end}`

### Phase 2 — Full Strand Toolkit
- Manual staple painting per cell
- Nick tool, erase tool
- Color picker per staple

### Phase 3 — Multi-Part Assembly
- Assembly/Part/Connection fully implemented
- Multiple 2D editor tabs, one per Part
- Assembly 3D view positions each Part via Part transform
- Connection shown as 3D arc with editable length (base count)
- Total scaffold length counter in assembly panel

### Phase 4 — Advanced 2D Tools
- Loop/skip insertion from 2D (cadnano2 insertion tool)
- Sequence assignment panel in 2D editor
- Strand properties sidebar (color, length, sequence, notes)
- scadnano/cadnano2 JSON import → opens in 2D editor

### Phase 5 — Deep Integration
- Bidirectional selection: select strand in 3D → highlighted in 2D, vice versa
- FEM RMSF heatmap overlay in pathview (color gradient on double tracks)
- Export active Part to cadnano2 / scadnano JSON

## Known Architecture Risks

1. **BroadcastChannel edit conflicts**: Two tabs can simultaneously mutate the same
   Part. Need a last-write-wins strategy or optimistic versioning on the backend
   (design version counter). May need to disable editing in 3D when 2D editor for
   that Part is open.

2. **FREE lattice ripple removal**: `LatticeType.FREE` is used in models, geometry,
   lattice.py, crud.py, frontend constants. Audit required — any existing saved
   designs with FREE lattice must be handled (error on load, or offer conversion).

3. **Canvas 2D hit-testing accuracy**: bp_start offset means helix rows don't start
   at column 0. Click → (helix_id, bp_index) requires careful coord math. Off-by-one
   in bp_start causes strand drawing at wrong position.

4. **Scaffold direction in pathview**: FORWARD strands draw 5′→3′ left→right;
   REVERSE strands draw 5′→3′ right→left. The pathview must render the direction
   arrows correctly or scaffold routing will be ambiguous to the user.

5. **Part ↔ Design ID mapping**: The 3D window currently has ONE active design.
   Multi-Part means N concurrent active designs. The existing `state.py` singleton
   must become a per-Part store. This is the highest-risk backend change.
   Interim: each Part is its own FastAPI app instance? Or a design registry keyed
   by part_id? Must be decided before Phase 3.

6. **BroadcastChannel message format**: Must include part_id + design version so
   recipients can ignore stale updates for other Parts.

7. **undo/redo cross-window**: Ctrl-Z in 2D editor undoes the last mutation on that
   Part's undo stack. The 3D window's Ctrl-Z does the same (same backend stack). If
   both windows are open and user alternates, undo order may be surprising.

8. **sliceview hit region**: HC hex grid — each cell is a hexagon, not a circle.
   Must implement point-in-hexagon hit test, not radial distance, to avoid
   mis-activating adjacent cells at hex edges.

## Development Log

Format: `[YYYY-MM-DD] [Phase N] CATEGORY: description`
Categories: BUG, GOTCHA, DESIGN, PERF, FIXED, DEFERRED

- [2026-04-06] [Planning] DESIGN: FREE lattice removal triggered by user decision.
  All backend FREE lattice handling must be audited before pathview can assume HC/SQ.
- [2026-04-06] [Planning] DESIGN: Origami ↔ Design mapping is the highest-risk
  architectural change. Current state.py is a singleton. Phase 3 needs a registry.
- [2026-04-06] [Phase1/C0] FIXED: FREE lattice removed from models, routes, tests,
  frontend. 5 files, 0 test regressions.
- [2026-04-06] [Phase1/C1] DESIGN: Vite multi-page — two /cadnano tabs open
  simultaneously sync for free via BroadcastChannel + backend ground truth.
- [2026-04-06] [Phase1/C3] GOTCHA: HC cell value formula needs safe modulo for
  negative col indices: `(col%2+2)%2` not `col%2`. Negative col→ wrong cell type.
- [2026-04-06] [Phase1/C3] DESIGN: Added POST /design/helix-at-cell to keep all
  lattice coordinate math server-side. Frontend passes only (row, col).
- [2026-04-06] [Phase1/C4] GOTCHA: pencil mouseup fires after mouseleave if user
  releases mouse outside canvas — cancel paint state in mouseleave.
- [2026-04-06] [Phase1/C4] GOTCHA: zoom _scrollX update must keep the bp under
  the cursor stationary, not the left edge.
- [2026-04-06] [Phase1/C4] DESIGN: gutter drawn twice (pre-strands + overlay) to
  clip strand rects under gutter without clipping helix labels.
- [2026-04-06] [Phase1/C5] GOTCHA: StrandType serialises as lowercase ('scaffold',
  'staple'), NOT uppercase. Test filters must use lowercase string literals.
- [2026-04-06] [Phase1/C5] BUG: BDNA_RISE_PER_BP missing from add_helix_at_cell
  scope — fixed with local import alias `_RISE`.
- [2026-04-07] [Phase1/C5] FIXED: Removed all boustrophedon/geometric sorting from
  helix label assignment. Labels now reflect design.helices index (user creation order).
  Changed files: sliceview.js (helixIdx map), pathview.js (sortedHelices), slice_plane.js
  (_buildLattice sort block + normal-mode ID lookup). e2e test rewritten to verify
  creation-order labels.
- [2026-04-07] [Phase1/C5] GOTCHA: slice_plane.js normal-mode lookup was using
  `h_${_plane}_${row}_${col}` synthetic ID which breaks for UUID-ID helices created
  via helix-at-cell API. Fixed: iterate design.helices, match by grid_pos first,
  then h_PLANE_row_col regex, then axis_start fallback.
- [2026-05-23] [Phase1] FIXED: editor now AUTOSAVES every local edit to the open
  file instead of only flipping a yellow "unsaved" badge. main.js: `_runAutosave` +
  `_scheduleAutosave` (600 ms debounce, in-flight + pending guards) called from the
  editorStore `design`-change subscriber. Gated on `_hasSaveTarget()` (workspace
  path in localStorage OR File System Access handle) — a never-saved design keeps
  the "unsaved" badge until the first manual Save establishes a target (user choice).
  Prefers workspace-path save (shared w/ 3D via localStorage), else file handle.
  Suppressed on initial load + `forceResync` (loading backend state ≠ a local edit).
  Only the originating tab autosaves (BC-driven re-fetch sets `_suppressUnsavedBadge`)
  → no two-tab write race; last-write-wins for two editors on one design.
- [2026-05-24] [Phase1] FEAT: editor tool hotkeys `N`=Nick, `P`=Paint (main.js keydown,
  after the input/ctrl guards, alongside `R`-cycle). Pressing `P` while ALREADY on Paint
  nudges the active paint colour up one hex unit (`#RRGGBB`+1, wraps at #ffffff) via
  `paintCustomColor` — each press yields a distinct colour so strands can be grouped by
  colour afterwards. The store subscriber already propagates `paintCustomColor` →
  `pathview.setPaintColor` + swatch sync. Help-modal rows added in cadnano-editor.html.
- [2026-05-24] [Phase1] FIXED: right-button-drag pan no longer pops a context menu
  when the drag ends on a right-clickable element (crossover arc / overhang / strand).
  Right-button release fires a native `contextmenu`; `pathview.js` now tracks
  `_rightDragMoved` (set when a right/middle pan moves past `DRAG_THRESHOLD`=4px, reset
  on each pan-start pointerdown) and the contextmenu handler swallows the event when it
  is the tail of a pan drag. A stationary right-click leaves the flag false → menu still
  opens. Robust to event ordering because the pan branch is the first thing in
  `pointerdown`, so every right-press resets the flag before its following contextmenu.
- [2026-05-24] [Phase1] FIXED: staple colours reshuffled on nick/ligation. Both the
  pathview canvas (`pathview.js` `strandColor`) and the strands spreadsheet
  (`strands_spreadsheet.js` `effectiveColor`/`paletteColor`) coloured a no-explicit-colour
  staple by `STAPLE_PALETTE[arrayIndex % 12]`. A nick adds a strand / ligation removes
  one → every later strand's array index shifts → untouched strands silently recolour
  (the spreadsheet was worse: it used the SORTED index, and its sort-colour ≠ display-colour).
  FIX: one shared stable resolver in `pathview/palette.js` — `ensureStapleColors(design)`
  pins `strandId → hex` (first-encounter slot = array index, so load-time colours are
  unchanged) + `stapleColorOf(strand)`. Map resets on `design.id` change. Mirrors the 3D
  renderer's per-strand-id `stapleColorMap` (helix_renderer.js:2152). Both editor views
  now import it → only strands an op actually creates/removes change colour, and canvas +
  spreadsheet agree. GOTCHA/LESSON: palette colour must key on a STABLE per-strand id, never
  the strand's position in `design.strands` — that array reorders on every topology edit.
- [2026-05-24] [Phase1] FIXED: editor undo/redo were silently broken in
  multi-document mode. `undoDesign`/`redoDesign` (and the 3 export fns) in
  `cadnano-editor/api.js` used a raw `fetch` with NO `X-NADOC-Doc` header, so they
  hit the DEFAULT doc while the edit lived on the editor's own doc → undo popped
  the wrong (empty) stack and reverted nothing. Pre-existing since multi-doc shipped
  (2026-05-23); surfaced when testing the crossover-perf work on VoltronCore (which
  loads into a NAMED doc). FIX: spread `docHeaders()` into the undo/redo/export
  fetches. Backend undo stack was already per-doc — only the frontend header was
  missing. Regression: `test_undo_redo_are_document_scoped` in
  test_part_edit_doc_isolation.py. GOTCHA: any new editor call using a bare `fetch`
  (not the `_request` helper) MUST include `docHeaders()` or it leaks to the default doc.
- [2026-05-24] [Phase1] PERF: editor mutations now send `X-NADOC-Skip-Geometry: 1`
  so the backend omits embedded 3D geometry from responses the 2D editor discards.
  ROOT CAUSE: every editor edit hit `_design_response_with_geometry` which (for
  `place_crossover` etc., with no `changed_helix_ids`) recomputed the FULL design
  geometry — measured 829 ms / 23.4 MB JSON for VoltronCore (71 helices, 31k nucs) —
  that the editor's `mutate()` parses and throws away (it draws from topology).
  The 583 ms autosave in the console log was that compute bleeding into the
  queued `save-workspace` request. FIX (single choke point, header-gated, no
  topology reasoning): new `_skip_geometry` ContextVar in `doc_context.py` (read
  by `DocContextMiddleware` from the header, mirrors `X-NADOC-Doc`); when set,
  `_design_response_with_geometry` returns the geometry-free `_design_response`.
  Editor's `api.js` `_request` (+ undo/redo fetches) send the header. 3D view never
  sends it → unchanged (and it re-fetches its own geometry on the design-changed
  broadcast anyway, so correctness is untouched). VoltronCore place: ~829 ms→~9 ms
  server-side + drops a 23 MB parse off the editor main thread. Regression tests:
  `TestSkipGeometryHeader` in test_cadnano_editor_api.py (3 tests). NOTE: only
  changes editor-originated responses; the shared `place_crossover` route still uses
  FULL geometry for the 3D caller (switching IT to the partial `changed_helix_ids`
  path needs a topology check — does a cross-helix strand merge dirty a 3rd helix? —
  so deferred, not guessed).
- [2026-05-25] [Phase1] FEAT: path-view upper-right hover readout. `pathview.js`
  appends an absolutely-positioned `#pathview-hover-readout` div to the
  (position:relative) `#pathview-container`; updated in the pointermove normal-hover
  block (`_updateHoverReadout(e)`, right after `onStrandHover`) and hidden on
  `pointerleave`. Line 1 = `${info.label ?? info.idx}:${bp}` for the cell under the
  cursor (helix from `_hoverHelixId`/`_helixAtWY`, bp from `_screenToRealWorld`→`_xToBp`
  so the periodic-boundary mirror folds correctly); gated to the helix's own span
  `[bp_start, bp_start+length_bp)`. Line 2 `Length: <nt>` only when an UNFILTERED
  `_hitTest` finds a strand (independent of the select-filter so length shows over any
  strand type). DOM overlay (not canvas) so it's decoupled from `_draw()` and stays put
  under pan/zoom. NOTE: distinct from the existing status-bar length display
  (`statusStrandEl`/`statusRightEl` fed by `onStrandHover`→`editorStore.hoveredStrand`).
- [2026-05-23] [Phase1] FIXED: sync gap — feature-log panel ops (`_flMutate`: seek/
  delete/revert/edit feature) updated only the editor's own store and never emitted
  `design-changed`, so they didn't reach the 3D view or sibling tabs. Now broadcasts
  like the main `mutate()` path (which also triggers the new autosave).

- [2026-05-24] [Phase1] FIXED: sliceview cell-click now creates an EMPTY helix (no
  auto scaffold+staple) AND places it ADJACENT to its neighbours in 3D. Two changes:
  (1) `cadnano-editor/api.js` `addHelixAtCell` sends `populate_strands: false` (was
  true) → bare track, user pens strands. (2) `crud.py` `add_helix_at_cell` no longer
  uses the RAW `_lattice_position(row,col)` (z=0..L, bp_start=0). It now picks the
  NEAREST existing lattice helix (Manhattan grid distance, linker helices excluded),
  offsets XY from that helix's REAL axis via `_overhang_neighbor_xy` (HC formula / SQ
  step+negation), and copies its axis Z-span + `bp_start` + `length_bp`. So on
  re-centered / imported designs (helices NOT at the lattice formula, e.g. caDNAno
  with bp_start≠0) the new helix lands beside its neighbour and a later-penned strand
  maps the same path-view bp column to the same 3D Z. Empty design (first helix) →
  unchanged fall-back (raw lattice pos, 42 bp, bp_start 0). ROOT CAUSE: helix-at-cell
  was the ONLY add-helix path that skipped the physical-offset derivation that
  make_bundle continuation + overhang-extrude already do. Regression tests:
  `test_adjacent_helix_no_offset_matches_lattice` + `test_adjacent_to_offset_neighbor`
  in test_cadnano_editor_api.py (25 pass). Verified on real SQUARE `workspace/teeth.nadoc`
  (bp_start=-3, z=-1.002): click (18,28) → x=4.50 = neighbour(18,27).x + SQ_COL_PITCH,
  co-extensive Z, inherits bp_start/len, 0 strands. Legacy `populate_strands=true` path
  kept + generalised to GLOBAL bp (lo=bp_start..hi) so it stays correct with inherited
  bp_start. NOT visually confirmed in browser (backend :8000 was a hung/unreachable
  process this session; logic is fully backend-driven + test-covered).

- [2026-05-25] [Phase1] PERF: editor "ligate takes ~1s / edits revert" — measured the
  real costs on VoltronCore (346 strands, 73 helices, 1252 xovers). Two findings:
  (1) **Render** (`pathview.js`): the algorithmic hot spots were NOT the ~1s but were real
  waste. `_findStrandIdxAt` was O(strands×domains), called 2×/xover/frame (~2504 calls) —
  now backed by a design-keyed bucket index (`_ensureStrandIndex`, keyed on `_design` ref;
  rebuilt only on design change, so pan/zoom reuse it): 9.5 ms→0.85 ms/re-render, 0
  mismatches vs the old scan. Added `_helixById` Map (built in `_rebuildLayout`) replacing 5
  `_helices.find(h=>h.id===…)` O(h) lookups in the crossover-draw loops. `_buildComponents()`
  (2504-entry xover-slot set + `ensureStapleColors`) now cached via `_ensureComponents()`
  keyed on `_design` ref → not rebuilt on pan/zoom. NOTE: the double-`_draw()` only fires on
  the FIRST load (`_fitDone` gate), not per edit.
  (2) **The actual dominant cost** = the **response payload**, not render: every editor
  response was **1.93 MB** for VoltronCore, of which **~1.2 MB is feature_log payload blobs**
  (1.1 MB pre/post-state snapshots [pre-existing from the feature-log overhaul] + 0.1 MB the
  new per-step diffs) that the 2D editor renders NOTHING from. FIX: `_design_response` now
  calls `_strip_feature_log_payloads(design_dict)` when `should_skip_geometry()` (editor) —
  snapshot pre/post blobs → "", per-child diff blobs → "1" sentinel (panel only checks
  `evicted`/`diffs_evicted` + diff PRESENCE, never decodes). Backend keeps the real blobs
  (revert/seek/`save_design_to_workspace` all run server-side on the full design), so revert
  still works (verified 200). Editor response 1.93 MB→**0.71 MB (−63%)**. SAFETY PARTNER:
  the editor's restart-recovery (backend-empty branch) now reloads from the workspace FILE
  (full blobs via `getLibraryFileContent`+`importDesign`) instead of re-importing its
  STRIPPED in-memory design — else a restart would permanently lose fine-routing revert
  history. 3D path unchanged (not skip-geometry → keeps full blobs for its localStorage
  recovery). Full suite 1446 green; skip-geometry + doc-isolation tests pass. NOT browser-
  verified (can't drive the 2D canvas headless); measurements are HTTP + Node micro-bench.

## Remaining Work — Phase 1

### Must run before merge
- [ ] `just test-file tests/test_cadnano_editor_api.py` — confirm all 17 API tests pass
- [ ] `npx playwright test e2e/cadnano_sliceview_positions.spec.js` — confirm new
      creation-order label test passes (requires `just dev` running)

### Known deferred items (Phase 1, not yet started)
- [~] **Helix-at-cell default length UX**: PARTLY ADDRESSED (2026-05-24). A cell-click
      next to existing helices now INHERITS the nearest neighbour's length + bp range
      (so tracks line up). The hardcoded 42 bp now only applies to the FIRST helix on an
      empty design. A user-configurable default is still unbuilt.
- [ ] **Pathview helix label badge**: the left-gutter badge number must also use
      design.helices index (same as sliceview) — verify `sortedHelices()` in pathview.js
      propagates correctly to badge rendering.
- [ ] **slice_plane.js deformed-mode label accuracy**: when _deformedFrame is set,
      labels are found by proximity to helix axis endpoints. If two helices have
      endpoints within TOL=0.6 nm this can mis-label. No fix yet — low priority.
- [ ] **Playwright e2e baseline**: none of the existing e2e tests cover pathview strand drawing. Phase 2 work should add these.
