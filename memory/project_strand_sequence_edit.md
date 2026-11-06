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

## Staple temperature view (2026-11-05)

The Tm button beside Length cycles off/domain Tm/total staple Tfold in Full/Beads
part views and the standalone cadnano path editor. Both editors share the model,
Celsius palette and legend, with lower/upper numeric bounds, draggable handles and
full-data-range reset (shared flex-map range math). Bounds persist across modes
within each editor session and only recolor cached estimates. Cadnano caches estimates across pan/zoom and refreshes
them on sequence/routing changes. Read-only calculation uses assigned sequences and the existing
loop/skip projection; no structure or feature-history mutation. Domain mode uses
SantaLucia–Owczarzy; total uses the user-selected PNAS 2024 model with a circular
scaffold for every active scaffold molecule (including secondary scaffolds).
Each staple uses its own scaffold’s contour length; inter-scaffold staples remain
unavailable rather than being treated as intramolecular loops. Both assume 10 mM free Mg²⁺ and excess 200 nM staples. Missing
or unsupported cases are gray. See [model, sources and limits](../docs/staple_temperature.md).

## Selection latency (2026-11-05)

Open spreadsheets must not rebuild the full crossover/ligation index per strand.
`strandLength` and `strandSequenceDisplay` accept a caller-owned junction index;
both table builders and the selected-sequence projection share it within each
operation. The temperature estimator also reuses its existing index. No index
is cached across edits. Whole-strand highlights use each rendered row’s strand ID
without re-sorting or recomputing all lengths. Contiguous unselected sequence
uses one text node per run while selected bases keep their precise marks. Cadnano rows now carry the same
stable `data-strand-id` identity as the 3D sheet.

Regression: both spreadsheet tests bound junction reads independently of strand
count, preserve exact section highlights, and verify subsequent edits. The
read-only `e2e/staple_selection_latency.spec.js` exercises both open spreadsheets,
all temperature modes, and real cadnano canvas clicks. It defaults to U6hb;
`NADOC_TEMPERATURE_DESIGN` selects a local large design without copying it.
On VoltronCoreArmV2, 12 cadnano canvas clicks fell from 1,497–1,579 ms to
265–341 ms through redraw with the spreadsheet open (all three thermal modes).
A subsequent sub-200 ms pass updates only the changed sequence/overhang cells,
preserving rows and unrelated editors; unchanged base selections do no rebuilding.
The cadnano grid is cached in screen pixels per canvas context, with size,
transform, row-layout, grid-toggle and stroke-state invalidation. Translucent
periodic mirror passes paint directly. The opaque base layer preserves exact
pixels, including after wheel zoom and grid toggles. Four distinct staples per
thermal mode measured **143–198 ms** through redraw on VoltronCoreArmV2;
the browser regression now enforces <200 ms for every measured click. A later
color-scale validation measured one 216 ms outlier with the overlay off (other
clicks 129–193 ms), so a consistent sub-200 ms guarantee remains unverified.

## Sequence preservation during topology edits (2026-09-19)

`make_nick` slices an assigned sequence at the loop/skip-aware length of its first
fragment. `_ligate` concatenates ordinary assigned strand sequences as well as
native residues; a missing half is filled with unknown bases, while two unassigned
ordinary strands remain unassigned. Fourteen focused regressions pass for both
strand directions, loop/skip offsets, round trips and partial assignments.

## What shipped

### Exact scaffold availability (2026-10-10)

Readiness now includes `scaffold_length`: every active scaffold must exactly equal
7249, 7560 or 8064 nt, or its explicitly declared custom source length. It is not
a maximum-budget check, and assigned/truncated `Strand.sequence` never declares
an available source. `scaffold_length_checks` counts native loop/skip-aware domain
DNA, extra bases on realized crossover/forced-ligation transitions, and terminal
DNA sequences; terminal modifications contribute no nucleotides. The shared
readiness path supplies the same per-scaffold verdict and owning-instance targets
in assemblies, with reference/native-oligo exclusions unchanged.

`assign_custom_scaffold_sequence` persists the full cleaned input length on
`Strand.custom_scaffold_length`; preset assignment clears it. The declaration
survives normal native save/reload and assembly strand projection, is independent
of sequence completeness, and is excluded from simulation fingerprints. Older
custom designs without this declaration need their original custom source
reassigned; readiness reports that remedy rather than guessing from sequence or
feature-history ownership. No route, molecular placement or simulation is changed
by the readiness check. Regression files: `test_scaffold_length.py`,
`test_design_readiness.py`, `test_design_readiness_api.py`, and
`test_readiness_routing_workflow.py`.

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

## Spreadsheet sectional selection (2026-11-04)

Both spreadsheets now project base/end, domain, overhang, and crossover selections
through `ui/sequence_selection.js`. Junction highlights include their endpoints and
extra bases (including forced ligations); loop copies and skips use the existing
sequence identity projection. Cadnano's element-key adapter supplies exact refs
alongside its existing row-selection IDs. Terminal overhang columns show a marked
readout above the existing editable field. Unassigned selected sequence positions
show `N`; clearing selection removes marks. Cross-window selection transport still
uses the existing whole-strand protocol; section refs are local to each editor.
