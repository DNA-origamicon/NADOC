---
name: connection-types-tab
description: "Overhangs Manager → Connection Types tab — icon-driven CT picker, selected-linker model, bridge_sequence on OverhangConnection, live-computed Sequence column, mixed-attach variants, dsDNA strand selection."
metadata: 
  node_type: memory
  type: project
  originSessionId: d44c6f6a-0587-4ad7-870b-b63171ba6b9b
---

# Connection Types tab

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

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

<a id="bridge-sequence--data--flow"></a>
- [Bridge sequence — data + flow](details/project_ct_tab/01-bridge-sequence--data--flow.md#bridge-sequence--data--flow)

<a id="sequence-column--live-computed-not-stored"></a>
- [Sequence column — live-computed, NOT stored](details/project_ct_tab/01-bridge-sequence--data--flow.md#sequence-column--live-computed-not-stored)

<a id="oh-shorter-than-domain--the-ns-gotcha"></a>
- [OH-shorter-than-domain — the N's gotcha](details/project_ct_tab/01-bridge-sequence--data--flow.md#oh-shorter-than-domain--the-ns-gotcha)

<a id="mixed-attach-linker-variants-end-to-root-root-to-end"></a>
- [Mixed-attach linker variants (end-to-root, root-to-end)](details/project_ct_tab/01-bridge-sequence--data--flow.md#mixed-attach-linker-variants-end-to-root-root-to-end)

<a id="dsdna-strand-selection-3d"></a>
- [dsDNA strand selection (3D)](details/project_ct_tab/01-bridge-sequence--data--flow.md#dsdna-strand-selection-3d)

<a id="test-surface-exposure"></a>
- [Test-surface exposure](details/project_ct_tab/01-bridge-sequence--data--flow.md#test-surface-exposure)

<a id="forbidden-combination-tooltip"></a>
- [Forbidden-combination tooltip](details/project_ct_tab/01-bridge-sequence--data--flow.md#forbidden-combination-tooltip)

<a id="playwright-tests"></a>
- [Playwright tests](details/project_ct_tab/01-bridge-sequence--data--flow.md#playwright-tests)

<a id="race-we-hit--fix-dont-regress"></a>
- [Race we hit + fix (don't regress)](details/project_ct_tab/02-race-we-hit--fix-dont-regress.md#race-we-hit--fix-dont-regress)

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
