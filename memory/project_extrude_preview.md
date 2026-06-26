---
name: project_extrude_preview
description: "Sidebar \"Extrude\" toggle showing translucent ghost cylinders for the extrude tool (slice-plane + overhang)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9242672e-6640-4491-bdd3-c5b7f01e77e6
---

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

## Length field steps by the lattice crossover period (2026-06-20)

The Extrude panel's `#slice-length` field increments by **7 bp (honeycomb) / 8 bp (square)** instead of
the HTML default of 1 — for BOTH the keyboard arrow keys AND the number-input spinner buttons. Mechanism:
the field's native **`step` attribute** is driven dynamically (NOT a keydown handler — a keydown handler
only catches keyboard arrows, so the mouse spinner kept stepping by 1; that was the first-attempt bug).
`slice_plane.js _applyLengthStep()` sets `_sliceLengthInput.step = latticeLengthStepBp(SQUARE?8:7)` (×RISE
in nm units), called from `show()` (after `_buildLattice`, lattice known), `setExtrudeUiOpen(true)`, and the
unit-select `change` listener. Lattice is read via the existing `_isSquareLattice()` (helix twist, falls back
to `_latticeType`). Pure helper `latticeLengthStepBp(latticeType)` in `extrude_panel_logic.js` (+test).
No `:invalid` CSS in the app, so non-multiple typed values aren't styled red. Verified live (throwaway e2e):
HC design → `step="7"`, ArrowUp 0→7→14, ArrowDown→7, spinner `stepUp()`→7.

---

A **"Show preview" checkbox in each extrude popup** — `#slice-preview-toggle` in the
slice extrude ctx-menu (`#slice-ctx-menu`) and `#ovhg-preview-toggle` in the "Add
Overhang" dialog. Shipped 2026-05-25. (Originally a right-sidebar button; moved into
the popups + default-ON per user request 2026-05-25 — there is no longer an
`#extrude-preview-panel`.) When ON, a translucent ghost shows where an extrude will
add DNA. State persists in `localStorage NADOC_EXTRUDE_PREVIEW` (default ON), single
source of truth `_extrudePreviewEnabled` in `main.js`, mirrored into slice_plane's
`_previewEnabled` via `setPreviewEnabled()` / the `onPreviewToggle` init callback.

Two ghost paths, both display-only (no topology/geometry writes — Three-Layer safe):

1. **Slice-plane** (covers new-bundle / segment / continuation / **blunt-end** —
   all route through `slice_plane.js`). One unit-height cylinder per selected cell,
   reused across updates (`scale.y` = length nm), positioned at the cell's world
   position (`_circleMeshes[i].fill.position`). **Direction is per-cell and must match
   the backend** (`_updatePreview` + `_backwardContinuationDir`). The backend
   `make_bundle_continuation` is subtle — get this right or the ghost mismatches:
   - free / new-bundle / segment / **FORWARD continuation** (helix `axis_end` at the
     offset; default non-inplace path builds `axis_end = offset + length_bp·rise`,
     **signed**) → `PLANE_CFG[_plane].normal × dirSign`. **The ± button flips these.**
   - **BACKWARD continuation only** (helix `axis_start` at the offset → in-place growth
     `axis_start − |length|·rise`, sign-IGNORED, can't extrude into the body) →
     `−normal`, ignores the ± button.
   - deformed → `_deformedFrame.axis_dir × dirSign`.
   Two bugs fixed here: (1) 2026-05-25 the ghost always used `normal × dirSign`, so a
   **near-end** (backward) blunt extrude showed flipped; (2) the first fix over-corrected
   — made ALL continuation ignore the sign, so the **minus button stopped flipping
   forward continuation**. Final rule: only backward ignores sign. API:
   `setPreviewEnabled()`/`isPreviewEnabled()`. Length/dir read from `#slice-ctx-menu`
   inputs. Group named `slice-extrude-preview`. Ghosts clear on `hide()`.

2. **Overhang dialog** (`main.js _showOverhangGhost`). Cyan cylinder at the neighbour
   cell (`entry.pos3D + entry.dir × 2.25 nm`), along the parent-helix axis × the
   `overhang_z_dir`. **The axial direction MIRRORS backend `make_overhang_extrude`
   exactly — do not re-derive geometrically** (see [[feedback_crossover_no_reasoning]]
   / [[feedback_overhang_definition]]): `zSign = sign(axis_end.z - axis_start.z)`;
   `strandZDir = direction==='FORWARD' ? zSign : -zSign`; `overhangZDir =
   isFivePrime ? strandZDir : -strandZDir`. Cluster pose applied via
   `design.cluster_transforms`. Design-mode only (skips assembly instances). Mesh named
   `overhang-extrude-preview`. Driven by the overhang dialog open/length-change/close.

Scene groups are `.name`-tagged (`slice-extrude-preview`, `overhang-extrude-preview`,
`overhang-locations`) for Playwright/debug locating via `__NADOC_DBG__.scene.getObjectByName`.

## Near-end blunt continuation + collision guard (2026-05-25)

Blunt-end "Extrude" had an off-by-one for **near-facing** ends. A helix's `axis_end` is
ONE rise PAST the last bp, so the far disk (`diskBp = hi+1`) lands exactly on `axis_end`
and continuation works; but `axis_start` is AT the first bp, so the near disk (`lo-1`)
landed one rise BELOW `axis_start` → backend `_find_continuation_helix` missed → a shifted,
overlapping fresh helix. Backend was correct; the offset handed to it was wrong.

Fix (frontend, `_bluntExtrude` + `blunt-extrude-btn-ctx` in `main.js`): anchor the
continuation on the helix axis endpoint via `continuationBp = info.bp + Math.max(0, info.openSide)`
(near→`bp`=`axis_start`, far→`bp+1`=`axis_end`), passed to BOTH `showAtEnd` and
`getDeformedFrame`. Backend then backward-continues in place and **merges** into the
existing domain (`[0,41]` → `[-21,41]`, one helix, ligated). No backend change.

Also added (`slice_plane.js`):
- **Default direction = away from body**: `showAtEnd`/`showDeformed` take `defaultDirSign`
  (= `openSide`: −1 near, +1 far); `show()` defaults +1 for new-bundle/segment. `_setDirSign()`
  is the single place that sets `_sliceDirSign` + syncs the `#slice-dir-*` buttons + preview.
- **Per-cell direction** is now just `normal × _sliceDirSign` (`_extrudeDirForCell`); the old
  `_backwardContinuationDir` was removed — the ± sign is honored everywhere and the conflict
  guard handles into-body extrudes.
- **Collision guard**: `_cellExtrudeConflict(row,col,dir,lengthNm)` (strict-interior axis
  overlap vs existing helices at the cell, ~0.4-bp end strip so the ligation touch isn't
  flagged). `_updatePreview` paints conflicting cells with `_previewConflictMat` (red, `0xf85149`)
  and sets `_previewHasConflict`; `_doExtrude` calls `_anySelectedConflict()` → if true, shows a
  `showToast` warning and aborts (leaves menu + red preview up). `showToast` imported from
  `ui/toast.js`. Adjacent EMPTY cells extrude freely (e.g. `+` → `[0,20]`).

Tests: `tests/test_lattice.py` `test_continuation_near_end_anchored_at_axis_start_extends_backward`
(offset=axis_start → merged `[-21,41]`, one helix) and
`test_continuation_near_end_off_by_one_offset_does_not_continue` (offset=axis_start−rise → 2
helices, the bug guard). 1483 backend tests pass. Frontend verified in-app via probe.

## Ligated extrudes adopt the connected strand's colour (2026-05-25)

Requirement: extrudes that continue/ligate strands (Ligate adjacent ON) must keep the colour
of the strand they connect to. Root issue: strand display colour is keyed on the strand **id
and its POSITION in `design.strands`** — palette = `STAPLE_PALETTE[index % 12]`
(`helix_renderer/palette.js buildStapleColorMap`), explicit = `store.strandColors[id]`
(synced from backend `Strand.color` in `client.js` `_syncFromDesignResponse`). The ligate-merge
(`ligate_new_strands` → `_ligate_and_merge`) kept **s1's** identity; for a 3′ ligation s1 is the
freshly-created strand, so the merged strand took the NEW id/colour and removing the existing
strand from mid-list reshuffled other staples' palette slots too.

Fix (backend only, no frontend change): `_ligate_and_merge(design, s1, s2, keep=None)` gained a
`keep` param selecting whose identity (id/colour/position) survives; the absorbed strand's
junction-side extension is dropped and its far-side extension + overhangs remap to the keeper
(backward-compatible when `keep=None`→s1). `ligate_new_strands` now passes `keep=<existing
strand>` for both the 3′ and 5′ merges and tracks `cur_id` across the 3′ merge so the 5′ step
still finds the (renamed) strand. Result: the continued strand keeps the EXISTING strand's
id+colour+palette slot, the freshly-created strand (appended at the end, no extensions/overhangs)
is absorbed, and no other staple's palette shifts. Forward continuation already extends the
existing strand in place (colour preserved); this fixes the segment-mode / 3′-ligation path.
Tests: `test_ligate_new_strand_adopts_existing_strand_color_and_id` (+ default still keeps s1).
Verified at the data level (Python: segment+ligate keeps `stpl_XY_0_0`/`#abcdef`, absorbs the new
strand); full suite 1483 pass. No `_ligate_and_merge` callers other than `ligate_new_strands`.

## Continuation on GAPPED helices — extend only the terminus interval (2026-05-25)

Symptom (teeth.nadoc): a −42 near-end extrude looked "connected to the far end" in 3D with a
different colour, while cadnano showed it at bp 0. Root cause: `make_bundle_continuation`'s
strand-extension loops added the new bps to **every** strand with a domain on the helix. On a
gapped helix (outer teeth helices have 3 scaffold intervals `[0,41],[84,125],[168,209]`), the new
near bps `[-42,-1]` got prepended to ALL three intervals → spurious strands `[-42,-1]+[84,125]` and
`[-42,-1]+[168,209]` (new ids → different palette colours) that bridge near↔far. Pre-existing in
the backward branch; the near-end anchor fix just made near extrudes reach it.

Fix (backend, `make_bundle_continuation`): all three extension branches (backward `:751`, forward
in-place `:829`, forward/fresh `:982`) now extend ONLY the strand whose domain on `cont_helix`
covers the terminus being continued — `min(d.start_bp,d.end_bp) <= terminus_bp <= max(...)`, where
terminus_bp = `cont_helix.bp_start` (near) or `cont_helix.bp_start+length_bp-1` (far). Verified on a
fresh gapped helix: near −42 extends only `[0,41]→[-42,41]`; far +42 extends only the `[168,209]`
interval; the other intervals are untouched. Tests:
`test_continuation_gapped_helix_near_extends_only_bp0_interval` /
`..._far_extends_only_far_interval` in `tests/test_lattice.py`.

NOTE: `tests/test_seamed_router.py::test_advanced_seamed_clears_existing_auto_route_before_teeth_reroute`
loads `workspace/teeth.nadoc` (an UNTRACKED scratch file). The user's pre-fix buggy extrude corrupted
that file with the spurious strands, so this test fails (near_end_xovers==0) until the file is
regenerated cleanly. It is NOT a code regression (fails with lattice changes stashed too). Deselecting
it → 1485 pass.

## Reopen-empty-part + empty-space "Extrude" menu (2026-05-26)

Two entry points to the new-bundle plane-picker (`workspace.show(lattice)` → `onPlanePicked('XY')`
→ slice plane in `newBundle` mode — the "initial extrude operation"):

1. **Empty part reopens into the plane-picker.** A part created but never extruded (0 helices),
   saved + closed, now reopens straight into the workspace grid instead of an empty scene.
   `main.js _revealWorkspaceForEmptyPart()` (defined just after the `workspace` init) replaces the
   bare `workspace.hide()` in the two part-load paths — `_openPartFromServer` (covers File>Open,
   library panel, and the `?open=` boot action) and the recent-file menu loader. It calls
   `workspace.show()` when `currentDesign.helices.length === 0 && !assemblyActive`, else `hide()`.
   Observable signal: `#mode-indicator` becomes `NEW BUNDLE — select cells · …`. (The existing
   non-empty→empty subscriber at ~`main.js:3319` already handles "deleted last helix"; this adds the
   "reopen already-empty" case it can't see, since prevCount is also 0.)

2. **Right-click empty 3D space → minimal "Extrude" menu.** New `#empty-space-ctx-menu` (one
   `#empty-extrude-btn`, in index.html next to `#slice-ctx-menu`). selection_manager gained an
   `onEmptyContextMenu(x,y)` opt, invoked at the END of its `contextmenu` handler — the
   `if (_mode === 'none' || !_strandId)` fall-through, i.e. the right-click hit NO pickable
   geometry (cone/bead/arc/overhang) AND nothing is selected. (A *selected* strand still shows its
   own color menu on empty right-click — unchanged.) main.js's callback guards: skip if
   `assemblyActive` or `slicePlane.isVisible()` or `workspace.isVisible()` (so it never doubles the
   slice/workspace flow). The menu's Extrude calls `_startEmptySpaceExtrude()` → `_extrudePanel.activate('newBundle')`.

   **ADDITIVE empty-space extrude (2026-06-20 — replaces the old destructive guard).** Empty-space /
   Tools→Extrude no longer wipes a populated part. The destructive `showConfirm` ("Start a new bundle? …
   replaces the current part") in `_startEmptySpaceExtrude` is GONE. The routing now lives in `onExtrude`
   (main.js): `freshBundle = newBundle && helices.length === 0`. Only an EMPTY workspace routes to
   `api.createBundle` (`POST /design/bundle`, which `clear_history()` + resets); with a part already present
   the new-bundle extrude falls through to `api.addBundleSegment` (`POST /design/bundle-segment`, append-only,
   reads lattice from the existing design) — a fresh, disconnected set of helices in the SAME design. The
   slice-plane's existing per-cell conflict guard (`_anySelectedConflict`, red ghost) still blocks cells that
   overlap existing DNA, so the user picks empty lattice cells. Post-processing: freshBundle resets
   `unfoldHelixOrder`; additive appends to it (the segment branch). The `newBundle` UI flag (clean lattice,
   no slab/handle) is unchanged — it's a UI affordance, decoupled from the reset semantics. Frontend-only;
   backend `bundle-segment` append path already tested (`test_extrude_segment_appends_fresh_disconnected_helices`).
   Live gesture (right-click empty space on a populated part → pick cells → build → existing structure intact +
   new bundle added) = **MV-EXT-ADD**, canvas-raycast / human-eye only.

## Minus-extrude backend bug (fixed 2026-05-25)

The preview surfaced a real **backend** bug: a minus (−axis) extrude created a helix
whose **axis pointed −Z but whose nucleotides rendered on the +Z side** ("axis arrows
right, helices wrong"). Root cause: `make_bundle_design` / `make_bundle_segment` /
`make_bundle_continuation` stored `length_bp` as the positive magnitude but baked the
sign only into `axis_end` (so `axis_end < axis_start`), while the geometry normalizer
`_normalize_helix_for_geometry` (deformation.py, the shared CG/atomistic/deform decision
point) derives bead z from `bp_start + length_bp` (canonical +) — so beads landed on the
+side, opposite the stored axis used for `helix_axes`/arrows.

Fix (user chose "canonical helix below the plane"): those three helix-creation sites now
store a **canonical** axis — `axis_start` = lower coordinate, `axis_end` = higher —
spanning `[offset+min(0,L·rise), offset+max(0,L·rise)]`. So −L places the helix in
`[offset−|L|, offset]` (below the plane) as an ordinary +axis helix; `bp_start` (from
`_helix_global_bp_start`) then comes out negative for a new bundle at offset 0
(e.g. −42 → bp_start=−42, beads z∈[−14,0]). Verified: `+42`→beads above, `−42`→beads
below; 1481 backend tests pass. Six negative-length tests in `tests/test_lattice.py`
were updated from the old `axis_end<axis_start` convention to the canonical one.
The arrow now points +Z (canonical) for a minus helix — the DNA region (not the arrow)
is what matters and it matches the preview.

Verification note: directions verified in-app via Playwright, including a cross-check
that the continuation ghost's sign equals the actual `addBundleContinuation` extrude
sign (new-bundle +dir→+Z; near-end continuation→away from body; far-end→away the other
way; ghosts cleared on hide). Overhang path earlier verified via a temporary
`window.__TEST_openOverhang` hook (the right-click→contextmenu arrow path doesn't
propagate through OrbitControls under headless — it is a shipped real-app interaction).
All temp probes/hooks removed after.
