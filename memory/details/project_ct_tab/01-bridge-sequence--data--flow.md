# Bridge sequence — data + flow — supporting detail

[Topic head](../../project_ct_tab.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Bridge sequence — data + flow
- **Model**: new optional field `OverhangConnection.bridge_sequence: str | None`.
  Carries the user's bridge (5'→3' on strand `__a` for ds, or `__s` for ss).
  For ds, strand `__b`'s bridge is the reverse complement.
- **Create**: `POST /design/overhang-connections` no longer accepts
  `bridge_sequence`. Linkers are always born with `bridge_sequence=None`;
  the user assigns the bridge afterwards via PATCH.
- **Edit**: `PATCH /design/overhang-connections/{id}` accepts
  `bridge_sequence` with sentinel semantics — omit = untouched, `""` = clear,
  ACGTN string = assign (uppercased, non-ACGTN stripped).
- **Random generation**: `POST /design/random-sequence` body
  `{length: int}` → `{sequence: str}`. Uses Johnson et al. via
  `generate_overhang_sequences(scaffold_seq, staple_seqs, length, count=1)`.
  Read-only — does NOT mutate the design. Backend lives at
  [backend/api/crud.py](../../../backend/api/crud.py) `random_sequence`.

## Sequence column — live-computed, NOT stored
The CT table's **Sequence** column is rebuilt every render from current state:
- Complement portions = RC of the bound overhang's `sequence` (pad-N to
  domain length first — see "OH-shorter-than-domain" below).
- Bridge portion = `conn.bridge_sequence` (RC on strand `__b` for ds).

Render entry point: `_renderLinkerSequenceCell(td, conn)` → builds colored
`<span>`s from `_linkerStrandSegments(conn)`. Colors match the connection-
type icon: cyan/magenta for the complement portions (paired overhang sides),
red/green for ds bridge halves, white for ss bridge.

Live updates flow through two channels:
1. `_refreshConnectionTypesUI()` already calls `_renderTable()` at the end,
   so any explicit UI handler refreshes the column.
2. `_store.subscribeSlice('design', …)` registered in `_initConnectionTypesTab`
   re-runs `_renderTable`, `_refreshCtBridgeBoxFromSelection`, and
   `_refreshCtSeqRows` on every design state change. This covers edits made
   outside the popup (spreadsheet, undo, file load) AND keeps the bridge
   input pulled-from-state after a Gen-button PATCH.

## OH-shorter-than-domain — the N's gotcha
**Symptom**: linker complement portion renders as N×L even when the bound
overhang clearly has a `sequence`. Took several iterations to track down.

**Root cause**: the overhang's `strand_domain.length` and `len(spec.sequence)`
can drift. In `hinge.nadoc` we observed OH1 with `strand_domain` spanning 10 bp
but `sequence="CACTAGCT"` (8 chars). `patch_overhang` resizes the sub-domain
when `len(sequence)` changes but doesn't shrink the strand domain endpoints,
so an OH "fills" only the first 8 of its 10 bp positions.

**Fix** (in `_linkerStrandSegments`): pad-then-RC. Don't gate on
`targetSeq.length >= length`; instead pad the OH sequence on its 3' end
(where unsequenced bp live, since `sub_domain.start_bp_offset=0` by convention)
with N's up to the domain length, then reverse-complement. The N's land at
the 5' end of the linker complement — the antiparallel side of the
unsequenced OH bases. See `_linkerStrandSegments` in
[overhangs_manager_popup.js](../../../frontend/src/ui/overhangs_manager_popup.js).

```js
const ohSeq = (targetSeq ?? '').slice(0, length).padEnd(length, 'N')
const text  = _reverseComplement(ohSeq)
```

If you ever fix the OH `sequence`/`domain` length-drift at the backend
(making them always equal), this padding becomes a no-op — keep it anyway
as a defensive fallback.

## Mixed-attach linker variants (end-to-root, root-to-end)
Added 2026-05-13. Eight tiles → twelve tiles. New ids:
- `end-to-root-ssdna-linker` (A=free, B=root)
- `root-to-end-ssdna-linker` (A=root, B=free)
- `end-to-root-dsdna-linker`
- `root-to-end-dsdna-linker`

**Polarity rule INVERSION** vs same-attach families — this is the key
subtlety. The unified Watson-Crick condition uses
`comp_first := (5p ∧ free_end) ∨ (3p ∧ root)`:
- ds needs `comp_first(A) == comp_first(B)`
- ss needs `comp_first(A) != comp_first(B)`

For **same-attach** (both root or both free), the side's `comp_first` is a
direct function of polarity, so the per-side `comp_first` collapse depends
only on whether `L == R`:
- ds same-attach: forbidden when `L != R`
- ss same-attach: forbidden when `L == R`

For **mixed-attach** (one root, one free), the two sides have OPPOSITE
attach so the `(5p ∧ free)` vs `(3p ∧ root)` mapping flips on one side:
- ds mixed-attach: forbidden when `L == R`  ← INVERTED
- ss mixed-attach: forbidden when `L != R`  ← INVERTED

Both inversions encoded in `_ctIsForbidden`; tooltip text in
`_ctForbiddenReason` calls out "(mixed attach)" explicitly so the user
isn't confused by the flip.

**Icon code is parameterized**: `_ctMixedSsdnaLinkerSvg(leftIsRoot, rightIsRoot, ...)`
and `_ctMixedDsdnaLinkerSvg(leftIsRoot, rightIsRoot, ...)`. Each side
independently picks stub position (root → INNER for ss / OUTER for ds;
free → OUTER for ss / INNER for ds — the dsDNA inversion convention from
the same-attach precedents carries through) and free-end marker
placement, then derives the linker-strand terminus polarities.

`_ctAttachPair` uses **longest-prefix** dispatch so the new
`end-to-root-*` and `root-to-end-*` linker ids don't collide with the
same-attach `end-to-end-*` / `root-to-root-*` families:
```js
if (id?.startsWith('end-to-root')) return ['free_end', 'root']
if (id?.startsWith('root-to-end')) return ['root', 'free_end']
if (id?.startsWith('root-to-root')) return ['root', 'root']
if (id?.startsWith('end-to-end'))   return ['free_end', 'free_end']
```

`_ctVariantForConnection` now resolves all 4 (attach_a, attach_b) combos,
so clicking an existing row created with any attach combo highlights its
matching tile in the popover.

## dsDNA strand selection (3D)
Single-click on a ds linker strand half in 3D selects only that half (not
both). See [[selection]] for the broader selection model.
- `frontend/src/scene/overhang_link_arcs.js` — each connector arc now
  carries `userData.strandId`; `hitTest` returns the strand id of the
  actually-hit pickable; `_applyHighlight` checks each object individually.
- `frontend/src/scene/selection_manager.js` — `_strandSelection`,
  `_highlightStrand`, `_applyMultiHighlight` no longer auto-expand ds
  linker halves. Right-click color picker / Delete still operate on the
  whole linker via the surviving `linkerComponentIds(strandId)` helper.
- Color highlight: `_LINKER_DS_A_COLOR = '#dc3545'`, `_LINKER_DS_B_COLOR = '#27ae60'`
  in the popup; selection highlight = `0xff4444`.

## Test-surface exposure
`frontend/src/main.js` exposes test-only handles on `window._nadocDebug`:
`selectionManager`, `overhangLinkArcs`, `scene`. Used by
[frontend/e2e/dsdna_linker_selection.spec.js](../../../frontend/e2e/dsdna_linker_selection.spec.js)
to inspect arc tags / drive `setHighlightedStrands` / verify hitTest
without simulating 3D mouse events. Leave these in.

## Forbidden-combination tooltip
`#ct-rule-tooltip` — singleton red-text floating tooltip; positioned `fixed`
near the cursor; shown on `mouseenter` over the CT button-box or any
popover tile when `_ctForbiddenReason(type, L, R)` returns non-null.
Suppresses the native `title` attribute while visible (saves it to
`dataset.ctSavedTitle`, restores on `mouseleave`).

## Playwright tests
- [frontend/e2e/ct_tab_layout.spec.js](../../../frontend/e2e/ct_tab_layout.spec.js)
  — 9 tests covering layout, sequence-input round-trip, Gen, forbidden
  tooltip, Make-complementary direct, Generate-Linker round-trip,
  row-click autopopulate, bridge box, Sequence-column refresh.
  Every test has `test.setTimeout(60_000)` so a hung test fails fast.
- [frontend/e2e/dsdna_linker_selection.spec.js](../../../frontend/e2e/dsdna_linker_selection.spec.js)
  — 3 tests for per-strand ds selection.
- [frontend/e2e/dsdna_linker_icon.spec.js](../../../frontend/e2e/dsdna_linker_icon.spec.js)
  — screenshots covering the same-attach icons (matrix). Mixed-attach
  icons aren't in the matrix yet — add when extending the visual regression set.

Cross-test backend state pollution: when the full suite chains tests
serially, the uvicorn `--reload` server retains in-memory state across
`POST /design/load` calls, and a different test fails per run. Each test
passes in isolation. This is the known stale-state pattern documented in
`.claude/rules/api-and-state.md`.
