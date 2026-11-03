# Mixed-frame compatibility (2026-10-06) — supporting detail

[Topic head](../../project_extrude_preview.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Mixed-frame compatibility (2026-10-06)

Editor `.nadoc` open/import now repairs missing lattice-frame IDs only when canonical
rest coordinates and rigid placement match exactly one existing frame. Desktop
fresh segment construction uses the same repair. `lattice_frame_compatibility.py`
changes metadata only: clusters, bends, strand topology and coordinates are kept.
Ambiguous frames, moved/nested/domain-scoped placements and off-grid helices stay
unresolved. The native painter labels absent mapping `SOURCE UNRESOLVED`, rather
than claiming `0 EXISTING`. Reopen older parts to apply the repair; normal Save
persists it. Original files are not rewritten merely by opening. Raw JSON/history/simulation
snapshot deserialization preserves original metadata to retain content hashes.

The Benchy reproduction has eight framed platform helices and two unframed bent
segment helices. Repair exports all ten occupied addresses with identical
nucleotide coordinates. Reusable check: Debug → VR Tours & Tests → Tools · Authoring
→ Extrude · older part compatibility. It runs without a headset; the CLI also
accepts `--part path/to/part.nadoc` and operates only on an isolated copy.

## Native VR painter and length controls (2026-10-05)

Accepted native Confirm now closes the painter and right-hand Extrude menu
immediately and stops preview/wheel input. The submitted draft stays frozen while
the browser commits it. Success clears that draft and retains the feature identity
for Undo; failure/refusal restores the same draft and settings page for retry.
Regression coverage lives in `extrude_viewer_test.cpp`, `native_confirm_probe.py`
and the existing Extrude tours.

The native Extrude sidebar owns two identical pinned thumbwheels beside its length
readout: coarse uses the lattice period (HC 7 / SQ 8 bp), fine uses 1 bp. The
painter now uses the shared frosted surface with separately bounded header, grid,
legend and footer. Gray double rings mark existing cells from the selected source
plane; Center Paint fits occupied and selected cells without editing addresses.
Optional `L` scene metadata carries occupied addresses and the source-to-scene nm
basis/origin. Native model preview and committed cells share imported offsets,
explicit frame placement and launch camera rotation. Painter pose/zoom is view-only.
Existing preflight rejects ambiguous independent frames sharing the selected plane.
Implementation: `lattice_painter.hpp`, `extrude_wheels.hpp`, `lattice_context.hpp`,
`backend/core/vr_lattice_context.py`. Reusable regression: Debug → VR Tours & Tests
→ Extrude beside an existing 1x8 platform. Through-headset comfort remains MV-38.

## Lattice cells colour-coded FORWARD/REVERSE + polarity legend (2026-07-10)

The extrude grid now colours **free selectable cells by caDNAno2 parity** so the user can read a
cell's polarity before picking: even `(row+col)%2==0` = **FORWARD → blue `#29b6f6`**, odd =
**REVERSE → red `#ef5350`** — the exact convention + colours as the cadnano-editor sliceview
(`frontend/src/cadnano-editor/sliceview.js` `hcIsForward`/`CLR_FORWARD_STROKE`/`CLR_REVERSE_STROKE`)
and backend `core/lattice.py cell_direction`. Continuable=amber, occupied=grey, selected=blue,
hover=white are unchanged (only the old gold "free" `C_CELL` was replaced).
- Pure helper `isForwardCell(row,col)` added to `slice_plane/lattice_math.js` (+`lattice_math.test.js`,
  6 cases incl. negative coords). `slice_plane.js` gained `C_FWD`/`C_REV` + `_freeColor(row,col)`,
  used in `_addCell` and `_updateCircleColors` (both replaced `C_CELL`).
- **Legend** `#extrude-legend` (index.html, in `#canvas-area`, top-center pill, `display:none`) shows
  "Lattice position ▪Forward ▪Reverse". Toggled by `slice_plane.js _setLegendVisible()` — ON in
  `show()` (non-readOnly) and `showDeformed()`, OFF in `show()` readOnly + `hide()`.
- Verified live (throwaway Playwright, `?open=2hb.nadoc` → Tools→Extrude): legend visible, all
  even-parity free cells `#29b6f6` / odd `#ef5350` (65/65), 0 console errors. Frontend suite 2563 green.
  main.js untouched (HTML + slice_plane + lattice_math only).

## Extrude-entry rework — sidebar panel + plane dropdown + origin axes (2026-06-11)

The extrude **entry UX** was reworked (the preview machinery below is unchanged). What moved:
- The floating `#slice-ctx-menu` is **gone**; its controls (same child IDs: `#slice-length`,
  `#slice-unit`, `#slice-dir-fwd/bwd`, `slice-strand-filter`, `#slice-ligate-adjacent`,
  `#slice-preview-toggle`, `#slice-extrude-btn`, `#slice-cancel-btn`, `.ctx-count`) now live in a
  **right-sidebar panel `#extrude-panel`** plus a new **`#extrude-from` origin-plane dropdown** (XY/XZ/YZ).
- New factory **`frontend/src/ui/extrude_panel.js`** (`initExtrudePanel({store, slicePlane, expandedSpacing})
  → {activate(mode,ctx), hide, isActive}`) owns the panel visibility + dropdown state machine + tool
  lifecycle. Pure helpers in `extrude_panel_logic.js` (`resolveDefaultPlane`, `dropdownStateForMode`,
  `axesVisibleForDesign`). Modes: `newBundle` (dropdown interactive, drives `slicePlane.show(...,{newBundle})`)
  vs `continuation`/`deformed`/`segment` (dropdown disabled = geometry-locked plane; the caller drives
  `showAtEnd`/`showDeformed`).
- **`slice_plane.js` decoupled from the floating menu**: `_ctxEl` now points at `#extrude-panel`; the old
  `_showContextMenu`/`_hideContextMenu` + the outside-click `pointerdown` closer + the `_onPointerUp`
  hide are GONE. New `setExtrudeUiOpen(bool)` gates the preview (replaces the `_ctxEl.style.display==='block'`
  check) and `_refreshExtrudeUi()` updates the live count/total/preview on every selection change. A new
  `onCancel` init opt fires the panel's `hide()`.
- **`workspace.js` (the XY/XZ/YZ plane-picker) is RETIRED/deleted.** New file → empty scene + the
  world-origin `THREE.AxesHelper` triad (now default-ON for empty designs; `axesVisibleForDesign` + a
  helix-count store subscriber + `_resetForNewDesign` keep it synced; assembly mode turns it off). Extrude
  starts explicitly via **Tools → Extrude** (`#menu-tools-extrude` → `_startEmptySpaceExtrude` →
  `_extrudePanel.activate('newBundle')`, with the destructive-replace confirm on a populated part) or the
  empty-space right-click. The blunt-end flows (`blunt_end_menus.js`) now `extrudePanel.activate('continuation'|
  'deformed',{plane})` before `slicePlane.showAtEnd/showDeformed`. Esc (keyboard_shortcuts) also calls
  `extrudePanel.hide()`. All `workspace.*` callers (main.js, new_design_modal, keyboard_shortcuts,
  script_runner, import_menu) were removed.
**Follow-up (same day 2026-06-11):**
- **Extrude ghost preview is now LENGTH-GATED** (user iteration: the always-on ghosts "got in the way
  when selecting cells"). The "Show preview" checkbox is gone; instead the **default length is 0** and the
  ghost appears ONLY once a non-zero length is entered. Mechanics (slice_plane.js): `_previewLengthBp()`
  returns the TRUE magnitude (dropped the `|| 1`, so 0 stays 0); `_updatePreview()` is purely
  length-gated `(cells selected × length>0)` — the `_previewEnabled`/checkbox gate was REMOVED so it's
  decoupled from the overhang dialog's `setPreviewEnabled` (the overhang `#ovhg-preview-toggle` toggle at
  main.js:1071 calls `slicePlane.setPreviewEnabled`, which would otherwise have killed the extrude ghost
  too). `setExtrudeUiOpen(true)` resets `#slice-length` to '0' on EVERY tool open (not just first load),
  so "no preview while selecting" holds each session. `_doExtrude` blocks a 0-length build with a toast;
  `_updateSliceTotalBp` shows "Set a length…" at 0 but still renders the scaffold recs. HTML
  `#slice-length` default `value="0" min="0"`. The overlap GUARD (`_anySelectedConflict`, red ghost) is
  unchanged. Verified by an e2e probe (0→0 ghosts, 0-length blocked, 42→ghost appears, build OK).
- The sidebar keeps **all** old popup controls incl. the **scaffold-length recommendations**
  (`#slice-scaffold-rec`: M13 7249 / p8064 8064 chips, `_SCAFFOLD_TARGETS` in slice_plane.js, computed in
  `_updateSliceTotalBp`, clickable to set length) + `#slice-total-bp`. These update live via
  `_refreshExtrudeUi` on every selection change.
- **Headless audit** (`backend/api/headless_build.py`, the programmatic/AI build surface): added
  `extrude_segment()` (POST /design/bundle-segment — the "append fresh segment" mode that had no headless
  wrapper; `extrude()` is continuation-only). The `plane` param (XY/XZ/YZ, = the new dropdown) was already
  threaded through `create_bundle`/`extrude`. New tests in `test_headless_build.py`:
  `test_extrude_segment_appends_fresh_disconnected_helices` + `test_build_on_non_default_plane` (XZ). 1951
  backend tests pass. Deformed-continuation (`bundle-deformed-continuation`) is intentionally NOT exposed
  headlessly (niche — needs a bend/twist frame).

- Tests: `extrude_panel_logic.test.js` (3 pure fns) + `extrude_panel.test.js` (factory wiring) = 15;
  full frontend suite 1152 green; smoke + assembly-exit gates green; one throwaway e2e confirmed the live
  flow (axes on boot/new-part, Tools→Extrude opens panel + dropdown, plane switch, Cancel teardown, zero
  console errors). Live **cell-pick → ghost → build** and **blunt-end ring right-click → panel** are
  MV-EXT (canvas-raycast, human-eye only). main.js +48 LOC (wiring: 2 imports + factory init + Tools
  handler + origin-axes subscriber glue; the cohesive logic is in extrude_panel.js).
