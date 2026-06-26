---
name: connection-types-tab
description: "Overhangs Manager → Connection Types tab — icon-driven CT picker, selected-linker model, bridge_sequence on OverhangConnection, live-computed Sequence column, mixed-attach variants, dsDNA strand selection."
metadata: 
  node_type: memory
  type: project
  originSessionId: d44c6f6a-0587-4ad7-870b-b63171ba6b9b
---

Major reworks shipped 2026-05-13 against the **Connection Types** tab of the
Overhangs Manager. Pairs tightly with [[overhang_connections]] (data model)
and [[overhang_subdomains]] (OH spec internals).

**2026-05-13 extension** — [[overhang_binding_extensions]]: the CT table now
also lists Phase-5 OverhangBindings (direct WC pairs) alongside the linker
rows. New 7th column **Bound** with a checkbox on binding rows (`—` on
linker rows). The two direct tiles' "Make complementary" button now also
calls `createOverhangBinding` at the tip sub-domains derived from the
tile's attach combo, so the pair persists and the Bound toggle becomes
available immediately. Backend: bound-toggle now also moves the driven
cluster (0/1/N-DOF). See the binding-extensions topic file for the full
cluster-pose-move semantics.

## Tab structure
- **Linker Generator tab** — DELETED 2026-05-13. The CT tab is the only
  authoring surface now; Domain Designer is the other CT-tab sibling. JS
  refs (`_listA`, `_listB`, `_genBtn`, `_errorEl`, `_lengthEl`, `_tableBody`,
  `_state`, `_renderLists`, `_makeListRow`, `_onPickRow`, `_validate`,
  `_setError`, `_clearError`, `_onGenerate`, `_checkRules`, `_compFirst`)
  and the LG pane in `index.html` were all removed.
- Default tab on first open: `connection-types`. `_OHC_TABS = ['domain-designer', 'connection-types']`.

## Selected-linker model (the core mental model)
A linker row in the table is the unit of "what the bridge editor edits."
Module var `_ctSelectedConnId` tracks the currently-selected row.

- **No selection** → bridge input + Gen are `disabled`, both bridge boxes empty.
- **Row click** → highlights row (`.ohc-link-row-selected` cyan/blue), pulls
  `conn.bridge_sequence` into the input, enables Gen, scrolls + highlights the
  bound overhangs in side lists.
- **Generate Linker** → snapshots conn ids before/after; the new id becomes
  `_ctSelectedConnId` (no longer clears `_ctSelectedA/B`).
- **Delete selected row** → `_ctSelectedConnId` clears, input clears + disables.
- **Stale-selection guard** in `_refreshCtBridgeBoxFromSelection`: any time
  `_ctSelectedConnId` references a missing conn, it's nulled out and the
  inputs are disabled. Covers external mutations (undo / file load).

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
  [backend/api/crud.py](backend/api/crud.py) `random_sequence`.

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
[overhangs_manager_popup.js](frontend/src/ui/overhangs_manager_popup.js).

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
[frontend/e2e/dsdna_linker_selection.spec.js](frontend/e2e/dsdna_linker_selection.spec.js)
to inspect arc tags / drive `setHighlightedStrands` / verify hitTest
without simulating 3D mouse events. Leave these in.

## Forbidden-combination tooltip
`#ct-rule-tooltip` — singleton red-text floating tooltip; positioned `fixed`
near the cursor; shown on `mouseenter` over the CT button-box or any
popover tile when `_ctForbiddenReason(type, L, R)` returns non-null.
Suppresses the native `title` attribute while visible (saves it to
`dataset.ctSavedTitle`, restores on `mouseleave`).

## Playwright tests
- [frontend/e2e/ct_tab_layout.spec.js](frontend/e2e/ct_tab_layout.spec.js)
  — 9 tests covering layout, sequence-input round-trip, Gen, forbidden
  tooltip, Make-complementary direct, Generate-Linker round-trip,
  row-click autopopulate, bridge box, Sequence-column refresh.
  Every test has `test.setTimeout(60_000)` so a hung test fails fast.
- [frontend/e2e/dsdna_linker_selection.spec.js](frontend/e2e/dsdna_linker_selection.spec.js)
  — 3 tests for per-strand ds selection.
- [frontend/e2e/dsdna_linker_icon.spec.js](frontend/e2e/dsdna_linker_icon.spec.js)
  — screenshots covering the same-attach icons (matrix). Mixed-attach
  icons aren't in the matrix yet — add when extending the visual regression set.

Cross-test backend state pollution: when the full suite chains tests
serially, the uvicorn `--reload` server retains in-memory state across
`POST /design/load` calls, and a different test fails per run. Each test
passes in isolation. This is the known stale-state pattern documented in
`.claude/rules/api-and-state.md`.

## Race we hit + fix (don't regress)
**Race**: user types into a `#ct-seq-input-{a,b}` side input, doesn't Tab
out, clicks **Generate Linker**. Browser fires `blur` (which starts an
async `patchOverhang`) and then the `click` handler (which starts an
async `createOverhangConnection`). Both are in-flight simultaneously;
depending on response ordering, the new linker can be created against
NOT-YET-COMMITTED overhang sequences. Symptom: the Sequence column
complement portion renders as N's even though the side input shows the
correct value.

**Fix**: in `_onCtGenerateLinker`, before calling `createOverhangConnection`,
diff each side input's value against `_overhangs().find(o => o.id === id).sequence`
and `await patchOverhang(...)` for any that differ. Synchronous-equivalent
commit eliminates the race. See `_onCtGenerateLinker` in
[overhangs_manager_popup.js](frontend/src/ui/overhangs_manager_popup.js).

## Things not to break
1. `_linkerStrandSegments` walks domains in 5'→3' order and emits one
   segment per non-zero-length domain; the bridge detection is
   `dom.helix_id.startsWith('__lnk__')`. The strand may be comp-first
   `[comp, bridge]` or bridge-first `[bridge, comp]` depending on the
   `_is_comp_first` derivation in lattice.py — never assume an order.
2. `_renderTable` is called from BOTH `_refreshConnectionTypesUI` AND the
   `subscribeSlice('design', …)` subscriber. Don't call `_refreshConnectionTypesUI`
   from inside an inline-edit commit on the table — it would destroy the
   active input mid-typing. The current commit callbacks call `_renderTable()`
   directly.
3. `_ctSelectedConnId` is module-level. `open()` resets it to null on
   modal-open. `_refreshCtBridgeBoxFromSelection` nulls it if the conn
   disappears. Don't set it from any other path.
4. `OverhangConnection.bridge_sequence` is `Optional[str]` — older
   `.nadoc` files load with `bridge_sequence=None` (backward compat). The
   Sequence column renders N's for the bridge portion of legacy linkers
   until the user assigns one via the bridge box.
