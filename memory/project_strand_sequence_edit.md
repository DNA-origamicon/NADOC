---
name: project_strand_sequence_edit
description: Hand-edit a strand's sequence from the right-click menu in 3D / cadnano / either spreadsheet, with the paired scaffold shown above the field and mismatches flagged. Shipped 2026-07-27.
metadata:
  node_type: memory
  type: project
---

# Edit strand sequences by hand (2026-07-27)

User ask: no path existed to type a strand's sequence anywhere. Add "Edit sequence…"
to the strand right-click menu in BOTH editors; for a staple whose scaffold is
sequenced, show the paired scaffold bases above the input and highlight incorrect
base pairing — but still allow any bases.

## What shipped

**Backend**
- `PATCH /design/strand/{id}` now **accepts a real sequence string**. It previously
  declared a `sequence` field but honoured only `null` — a client sending
  `{"sequence":"ACGT"}` got HTTP 200 and no change (silent-success trap).
  Normalizes (strip whitespace, uppercase), 422 on non-ACGTN or wrong length.
  Recorded as a **`strand-sequence` feature-log** step (new `SnapshotOpKind`), not a
  minor log — a sequence is a build-fingerprint field, so a seek must reproduce it
  or an oxDNA job's stale ⚠ never clears (same reasoning as `overhang-sequence`).
- **Overhang write-back**: bases falling in an `overhang_id` domain are sliced out
  and written to that `OverhangSpec.sequence` **directly** (`model_copy`), NOT via
  `_build_overhang_patch` — that helper resizes the overhang domain to
  `len(sequence)`. Skipped for an overhang carrying sub-domain `sequence_override`s
  (those bases are owned per sub-domain; the UI marks the span read-only).
- **NEW `GET /design/strand/{id}/sequence-context`** (`routes_assign_sequences.py`) →
  `{length, sequence, derived, partner, segments}`, all index-aligned.
- **`sequences.strand_partner_bases(design, strand)`** — the pairing walk extracted
  out of `assign_staple_sequences`, which now consumes it. **ONE implementation** of
  "what does position i pair with": antiparallel scaffold base for a duplex domain,
  overhang base for a binder domain, `None` for an ssDNA overhang tip.
  Proven byte-identical to the old inline walk across 44 real designs + synthetic
  binder / loop-under-overhang / skip-under-overhang cases.
- `strand_sequence_length` + `_domain_seq_span`: the length `strand.sequence` must
  have. Differs from `strand_nucleotide_count` **only** when a loop/skip sits under
  an overhang or binder domain (those use the raw bp span, as the derivation always
  has). **Sequence editors must validate against `strand_sequence_length`**, or a
  hand-typed sequence could be rejected at exactly the length the derivation emits.

**Frontend**
- `ui/strand_sequence_pairing.js` — pure core (mismatch flags with N-as-wildcard,
  validation, overhang splice, run-length decoration, read-only-span preservation).
- `ui/strand_sequence_dialog.js` — `initStrandSequenceDialog({api, showToast})`.
  Three monospace rows in one scroll-synced track: partner / editable field / ruler.
  **api is INJECTED** because the two editors have different api modules
  (`api/client.js` vs `cadnano-editor/api.js`), each already refreshing its own store.
- Item added on **all four surfaces**: 3D `_showColorMenu`, cadnano
  `_showStrandCtxMenu`, and both spreadsheets' Sequence-cell menus. The scaffold
  item was renamed "Assign sequence…" → **"Edit sequence…"** in both editors
  (behaviour unchanged — it still opens the preset/custom scaffold modal).
- `main.js` Δ **+6 lines** (1 import, 1 factory init, 2 one-line handlers): pure wiring.

## Invariants / gotchas

- **The partner row reads 3'→5' left-to-right** — it is laid out in the edited
  strand's 5'→3' index order and pairs antiparallel to it. The row label says so;
  don't "fix" it.
- **Mismatches never block Apply.** Only bad characters and wrong length do. `N` on
  either side is a wildcard (matches backend `is_watson_crick_complement(allow_n=True)`).
- Mismatch colouring lands on the **partner row**, not the input — a `<textarea>`
  cannot colour individual characters.
- A hand-set sequence is deliberately **not** protected from `assign-staple-sequences`
  / `full-autostaple` (user's call: they should override, and both are undoable).
  Only the *implicit* hooks were narrowed — see [[overhang-sequence-display]] §3.

## Menu unification (2nd commit)

`ui/strand_menu_items.js` — pure `buildStrandMenuItems(ctx, handlers)` is now the ONE
definition of the items both editors share (Make Reference/Active, Convert to OH
binding strand, Convert to scaffold, Edit sequence…, Edit extensions…). A handler you
don't pass hides its item, so each editor opts in to what it implements.

- **cadnano** `_showStrandCtxMenu` now renders that list through
  `ui/primitives/context_menu.js` — its bespoke `<div>` + `mkItem` + hand-rolled
  outside-click/Escape listeners are gone.
- **3D** `_showColorMenu` builds the same shared list but still renders it with its own
  `_menuItem`/`_menuSep`, because that menu also carries a colour grid, an RGB input, a
  representation flyout and a `_dismissMenu` singleton shared with six sibling builders
  (`_showNickMenu`, `_showLoopSkipMenu`, …). Swapping its *renderer* is a much larger
  change with no user-visible gain, and the 3D strand right-click **cannot be driven
  headlessly** (LESSONS H7), so it could not be verified. The duplication that actually
  mattered — two copies of the labels/visibility rules, which had already drifted — is gone.
- `placeMenu()` extracted as a pure export from `context_menu.js` (flip-up when it would
  overflow the bottom, cap + scroll when taller than the viewport). The primitive only
  clamped before; the 3D `_placeMenu` had these rules and the primitive didn't.
- **Order change in the 3D menu**: Make Reference/Active now sits above Isolate (it was
  below), matching cadnano.

## Bug found + fixed while verifying

The strand spreadsheet's context menu armed
`document.addEventListener('pointerdown', _removeCtxMenu, {once:true})` with **no
containment check**, so a real pointerdown on an item detached the menu before
mouseup and the item's `click` never fired. **Every item in that menu was dead to a
real mouse** ("Clear sequence", "Set binder sequence…", "Go to strand"). Fixed to
dismiss only on an outside press. See LESSONS for why jsdom can't catch this.

## Tests

- Backend: `tests/test_strand_sequence_edit.py` (24), `tests/test_targeted_reassign.py` (9).
  `just test-smart` → **FAST, 5522 passed**; DEFERRED `FULL` parked in `.nadoc-slow-pending`.
  (2 pre-existing failures in `test_atomistic_geometry_lock.py` — stale goldens, byte-identical
  to HEAD, unrelated.)
- Frontend: `strand_sequence_pairing.test.js` (32), `strand_sequence_dialog.test.js` (27),
  `spreadsheet.test.js` (6), `strand_menu_items.test.js` (17), `context_menu.test.js` (+7
  for `placeMenu`). `just test-frontend` **3335 passed**.
- In-app: verified in a real browser in BOTH editors (dialog renders character-aligned,
  mismatch highlighting, Apply persists + feature-logs, reset-to-derived, overhang
  shading + write-back, no console errors). The throwaway 6hb fixture and its
  Playwright spec were **deleted after verification** per the E2E policy.

Related: [[overhang-sequence-display]], [[overhang_connections]], [[oh_binder]].
