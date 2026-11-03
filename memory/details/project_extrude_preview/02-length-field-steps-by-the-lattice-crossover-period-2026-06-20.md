# Length field steps by the lattice crossover period (2026-06-20) — supporting detail

[Topic head](../../project_extrude_preview.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
