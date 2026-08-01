---
name: tech-debt-ledger-archive
description: Resolved tech-debt entries (history only). Never read in a routine loop — mine it only for a specific past resolution.
metadata:
  node_type: memory
  type: project
---

History for [[tech-debt-ledger]] (`memory/project_tech_debt.md`). Closed entries land here with
their resolution intact. **Do not read this file in a routine `/audit-debt` pass** — the head
carries everything an open item needs. Open it only to mine one named past resolution.

---

### ~~Advanced/seamless scaffold routing is hash-seed non-deterministic~~ — FIXED 2026-07-13
- **Resolution (verified 2026-07-13):** the `(len(adj[n]), n)` lex tiebreaker is now applied to
  **both** the starter sort and the neighbor key handed to `_ham_path_search`
  ([seamed_router.py:296](backend/core/seamed_router.py#L296)); the in-code
  `FIXME(advanced-routing-nondeterminism)` is gone. `test_seamless_router.py::
  test_teeth_closing_zig` passes **8/8 fresh `PYTHONHASHSEED` values** (was ~4/8).
  Routing is deterministic run-to-run again. **Invariant: keep the tiebreaker on BOTH keys** —
  dropping either silently reintroduces run-to-run scaffold-strand-count drift (this
  regressed once already, via the 2026-06-01 budgeted-DFS refactor).
- **Historical detail (why it happened)** — kept because it regressed once and could again:
- **Where it was:** [seamed_router.py](backend/core/seamed_router.py) `_ham_path_ending`
  (~line 291) + the neighbor key it hands to `_ham_path_search`. Both sorted by
  `len(adj[n])` with **no secondary `n` tiebreaker**, so equal-degree nodes kept
  their set-derived (hash-seed-dependent) order.
- **Why it was debt:** the Hamiltonian path → scaffold routing came out differently
  run-to-run. `auto_scaffold_seamless` / `auto_scaffold_advanced_seamed` emitted a
  **different scaffold-strand count** depending on `PYTHONHASHSEED`. Real-app impact:
  the same design routed differently on different backend runs (not just tests).
- **Repro (2026-06-04, now stale):** `tests/test_seamless_router.py::test_teeth_closing_zig`
  (asserts exact `bridge_xovers==6`, `scaf_strands==4`) was **flaky ~50%** — 4 pass /
  4 fail across 8 fresh processes. Also varied `advanced_seamed` on teeth between 1
  and 4 scaffolds (originally misattributed to the live app rewriting the fixture).
- **History:** `seamless_router._ham_path_ending` (its OWN copy) deliberately used
  `(len(adj[n]), n)` WITH the `n` tiebreaker to avoid exactly this (documented in
  [[seamless-scaffold-router-architecture-and-hard-won-lessons]]). The
  2026-06-01 budgeted-DFS refactor that delegated the search to the shared
  `seamed_router._ham_path_search` dropped the tiebreaker → regression. The fix
  restored it on both keys.
- **Topology check on the fix:** teeth routing topology is unchanged
  (`bridge_xovers==6`, `scaf_strands==4`) — that is exactly what the now-deterministic
  test asserts, so the tiebreaker picked the same path the good seeds always picked.
  It de-flaked the test without moving the route.

### ~~Overhang Bind/Unbind button (legacy OverhangBinding pair model)~~ — REMOVED 2026-06-30
- **Where:** [overhang_sequences_panel.js](frontend/src/ui/overhang_sequences_panel.js).
- **Resolution (2026-06-30, final):** the per-row Bind/Unbind toggle was **removed entirely**
  — user feedback: mixing bind/relax actions between the Overhangs list and the Overhang
  Connections section was a bad idea; keep each section's job separate. (A short-lived
  intermediate version rewired the toggle to the unified relax; that was scrapped.)
- **Replaced by a LINK ICON:** for any overhang that participates in a connection (a
  `overhang_bindings` / `overhang_connections` / `connection_versions` entry — see pure
  `connectionPairForOverhang(design, ovhgId)`), the last column shows a chain-link button.
  Click → `openConnectionForPair(a, b)` (new export from
  [overhang_connections_panel.js](frontend/src/ui/overhang_connections_panel.js)) which
  expands the Connections section, sets the A/B dropdowns to the pair, and selects the
  pair's **applied** ConnectionVersion (falling back to the live linker/binding row).
  Imported directly (singleton entry point) → **no main.js change**. All bind/unbind /
  relax lives in the Connections section only.
- **Keystone backend fix (kept):** `crud.patch_overhang_binding` passes `driver_side`
  (from `target.driver_oh_id`) into `compute_bind_topology`, so toggling a UNIFIED
  same-rigid-body root-to-root binding's `bound` flag no longer 422s on the same-cluster
  guard. This now serves the Connections section's **Bound checkbox** (the proper home of
  bind/unbind), NOT the removed sidebar button. Legacy bindings (`driver_oh_id=None`)
  unchanged. Pin: `test_direct_connection_unified.py::
  test_unbind_then_rebind_roundtrips_same_body_unified_binding` (proven red without it).
- **Note:** the OverhangBinding model is NOT abandoned — it IS the current unified direct
  connection record (see [[overhang-connections-panel]]). The old "superseded by oh_binder"
  framing was stale.
- **NOT hand-driven in-app** (manual-validation debt): the link icon (appears for connected
  overhangs, click opens the Connections section on the applied version) is pinned by jsdom
  but not exercised against a real overhang-bearing design in the running app.


### TD-01 — `just lint` is RED, so it cannot act as a gate — CLOSED 2026-07-31 (`/audit-debt` pass 1)

**Outcome: `just lint` exits 0.** 6 bullets, all terminal: 5 FIXED + 1 ACCEPTED-and-neutralized.
Probe reproduced all 11 ruff findings exactly as the entry claimed — no stale anchors.

- ~~`backend/api/routes_oxdna.py:1892` — `oxdna_health.composite_trajectory_atomistic`~~ —
  **FIXED 2026-07-31.** Probe: `export_oxdna_trajectory` was converted from the batch builder to the
  streaming `iter_composite_trajectory_atomistic` (imported at `:1918`, used `:1940`); the batch name
  survived the conversion. Its co-import `composite_trajectory_meta` IS live (`:1900`), so only the
  one name was dropped. The function itself is alive with 3 other callers
  (`routes_export_structure.py:351`, `routes_oxdna.py:1748`, 2 test files) — not dead code.
- ~~`tests/test_atomistic_display_split.py:20` — `models.StrandType`, `models.Direction` (×2)~~ —
  **FIXED 2026-07-31.** Probe: `grep -n 'StrandType\|Direction'` returns the import line and nothing
  else. Never referenced in the file's body; leftover from a copied import block. Model enums, not
  helpers — nothing to under-exercise.
- ~~`tests/test_cg_seed_ssdna_collapse.py:42` — `oxdna_health._ssdna_frame_override`~~ —
  **FIXED 2026-07-31.** This was the entry's flagged trap ("may mean the test stopped exercising it").
  **It didn't.** The two tests exercise the helper *by design through the production path*:
  `build_atomistic_model_from_cg_spline` calls it internally (`cg_to_atomistic.py:319-320`), and the
  controls `_build_no_fix` (`:122`) / `_build_a3_no_ssdna` (`:134`) exist precisely to build the same
  design **without** it and diff. Direct unit coverage also lives at
  `tests/test_oxdna_relaxation.py:2505,2513`. The import was a docstring-era leftover (the helper is
  still named in the module docstring `:15`, correctly). No coverage hole.
- ~~`tests/test_oxdna_surface_strands.py:278` — `oxdna_interface._strand_nucleotide_order`~~ —
  **FIXED 2026-07-31.** Probe: `test_headless_setup_build_validate` computes
  `n_origami_strands = len(design.strands)` — a **strand** count, which is what
  `validate_capture_build(n_origami_strands=…)` wants. `_strand_nucleotide_order` returns
  **nucleotide** keys, so it was the wrong tool for that line, not a dropped one. The very next test
  (`:321,:327`) imports and uses it correctly, and the helper has ~100 call sites repo-wide. No hole.
- ~~"Check each test import first — deleting may be hiding a coverage hole"~~ — **FIXED 2026-07-31**
  (discharged): all three test imports probed above; none was the mechanism by which its test
  exercised the helper. This check was the real work of the item and it came back clean.
- ~~"Do NOT fix the other 6 (`backend/ml/propagator/`)"~~ — **ACCEPTED, and neutralized 2026-07-31**
  via the entry's own prescribed path: a `[tool.ruff.lint.per-file-ignores]` entry for
  `"backend/ml/propagator/*.py" = ["F401","F541","F841"]` in `pyproject.toml`. **No dormant code was
  edited** (the 2026-07-31 user decision). The ignore carries a comment telling any future reviver to
  delete the entry first. The ACCEPTED bullet in the head was updated to say the ignore now exists.

**Gate:** `just lint` → `All checks passed!` (exit 0, was exit 1). `just test-smart` → `decision: FAST`,
**6108 passed, 41 skipped, 71s**; `DEFERRED` heavy group parked in `.nadoc-slow-pending` (correct —
no test-dedicated session open). No behavior changed: 4 unused-import deletions + 1 config entry.

**New debt found while resolving:** the gate's *scope* (`just lint` = `backend/ tests/` only) hides
193 findings under `scripts/` + repo root. Logged as **TD-25**, not fixed in this pass.

---

### ~~TD-02~~ — `STAPLE_PALETTE` copies + sync comments + index agreement — **CLOSED 2026-07-31**
- ~~**Agreeing three-way invariant**~~ — **STALE 2026-07-31:** the invariant is **five-way**, not
  three. Repo-wide grep for palette definitions found four more, and **all agree colour-for-colour**:
  `backend/core/surface.py` `_STAPLE_PALETTE_HEX`, `scene/color_util.js` `ATOM_STAPLE_PALETTE`,
  `scene/selection_manager.js` `PICKER_COLORS`, plus the three already listed. Line numbers in the
  original bullet were also wrong (`helix_renderer/palette.js` is `:28-31`, not `:23-26`).
  **The ledger's own parenthetical that `ATOM_STAPLE_PALETTE` is "a separate, intentionally different
  atomistic palette" is FALSE — it is byte-identical.** See DECISIONS.
- ~~**Every one of the three "keep in sync with…" comments names a file that no longer holds the
  constant**~~ — **FIXED 2026-07-31.** Half-stale as written: `helix_renderer/palette.js:21` was
  already corrected on 2026-07-30, and two *unlisted* offenders existed (`pathview/palette.js:6-9`
  file header, `backend/core/surface.py:44`). All four stale pointers to `helix_renderer.js` (which
  only *imports* it, `:33`) rewritten; the single authoritative copy list now lives in the comment
  above `STAPLE_PALETTE` in `backend/core/constants.py`, and every other comment points there.
  `.claude/rules/cadnano-editor.md` + `rendering.md` updated to match.
- ~~**A fourth copy that is NOT in sync:** `frontend/src/ui/spreadsheet.js:54-60`~~ — **FIXED 2026-07-30.**
  It declared a module-private `STAPLE_PALETTE` with **completely different colours**
  (`#e06c75 #98c379 #d19a66 #61afef …` — an editor syntax theme) under the false comment
  `// Staple palette (mirrors helix_renderer.js)`. Because `paletteColor` is the last-resort fallback in
  `effectiveColor`, every staple arriving with `color === null` (the normal case — **Full Autostaple
  stamps no colour**; only `POST /design/strands` and `_build_nick` do) was painted one hue in the panel
  and another in 3D (index 1 green vs yellow, index 3 blue vs orange) — and via `getStapleColorOrder` →
  `exportSequenceXlsx`, the wrong hues reached the **exported oligo order sheet**. Now imports the
  canonical `STAPLE_PALETTE` from `scene/helix_renderer/palette.js` and formats int→`'#rrggbb'`.
  Pinned by 3 tests in `ui/spreadsheet.test.js` ("Staple colour fallback uses the canonical shared
  palette"). The sync-pointer comment in `helix_renderer/palette.js` was corrected at the same time.
  (`scene/color_util.js:35 ATOM_STAPLE_PALETTE` is a separate, intentionally different atomistic palette.)
- ~~**STILL OPEN — the two remaining stale sync-pointer comments**~~ — folded into the FIXED bullet
  above (four offenders, not two).
- ~~**STILL OPEN — index agreement, not just palette agreement.**~~ — **FIXED 2026-07-31.** The claim
  was under-stated, not over-stated. `buildStapleColorMap` (`palette.js:180`, union-find `:190-208`)
  pins a slot per `strand.id` in a module-level `_pinnedByDesign`; its own comment (`:166-177`) spells
  out the exact bug — *"re-derived from the strand's array position on every rebuild, so any edit that
  reshuffles design.strands … silently recoloured untouched staples"* — and `ui/spreadsheet.js` was
  still doing precisely that. Worse: it did so at **three call sites with three DIFFERENT indexings**
  (staples-only array position `:276`, `design.strands` position `:313`, sorted-row position `:685`),
  so the row swatch, the colour *sort key* and the exported .xlsx could each show a different hue for
  the same staple even before any mutation. Fixed by threading the renderer's pinned map through
  `effectiveColor`/`sortedStrands` (cached on design+geometry **reference** identity — the union-find
  does a `findIndex` per crossover and must not run per re-render). The renderer route was
  unavailable: `design_renderer.js` builds the map into a local and exposes no getter, so the
  spreadsheet imports `buildStapleColorMap` directly — same module-level pins, so both agree.
  Pinned by 3 new tests in `ui/spreadsheet.test.js` ("Staple palette ASSIGNMENT follows the 3D view");
  the drift test was **proven** by re-running it against the pin-lookup removed (got slot 2 `#6bcb77`
  where the pin says slot 1 `#ffd93d`).
- **NEW, found while probing — the server-side .xlsx export had the retired palette all along.**
  `backend/api/routes_sequences.py:183-187` hard-coded a local `_PALETTE` holding the **exact editor
  syntax theme** (`#e06c75 #98c379 #d19a66 #61afef …`) that `spreadsheet.test.js:183` asserts is dead,
  and indexed it by *sorted row position*. The UI always sends `strand_colors`, which is why the
  2026-07-30 pass never saw it — but every **headless / API-driven** oligo-order sheet came out in
  colours that match nothing in the app. **FIXED 2026-07-31**: imports `STAPLE_PALETTE` from
  `constants.py`, indexed by `design.strands` position to match the panel. Pinned by
  `tests/test_sequence_xlsx_palette.py` (3 tests, **proven** failing against the old code).
  *Lesson for the next pass: a "canonical constant" fix is not done until you grep for the values of
  the REJECTED palette, not just the name of the canonical one.*

**Pass 2 (2026-07-31) tally: 1 STALE / 4 FIXED / 1 DECIDE (DEC-01, still open in the head).**

**Gate:** `just test-smart` → `decision: FAST`, **6111 passed / 41 skipped** (76 s), one `DEFERRED`
group parked in `.nadoc-slow-pending`. `npx vitest run` → **3712 passed / 248 files**.
Both fixes proven-failing against the pre-fix code before being kept.

**Files touched:** `backend/api/routes_sequences.py` · `backend/core/constants.py` ·
`backend/core/surface.py` · `frontend/src/scene/helix_renderer/palette.js` ·
`frontend/src/cadnano-editor/pathview/palette.js` · `frontend/src/ui/spreadsheet.js` (+ its test) ·
new `tests/test_sequence_xlsx_palette.py` · `.claude/rules/cadnano-editor.md` + `rendering.md`.

**NOT VERIFIED IN APP** — the spreadsheet change was gated on tests only. Vite was up but the live
backend held no design, and `feedback_no_live_server_mutation_for_verify` forbids loading one to
verify. The visible check still owed: open a design with unstapled/uncoloured staples, confirm the
Sequence panel swatches match the 3D staple colours, nick a strand, confirm untouched staples keep
their colour in **both** views.


---

### ~~TD-03~~ — Cadnano-editor app stragglers — **CLOSED 2026-07-31** (5 FIXED / 1 PROMOTED / 1 DECIDE / 2 ACCEPTED / 1 STALE)
Small, each a live trap; all documented in `.claude/rules/cadnano-editor.md`.
- ~~**`unligatedCrossoverIds` is written but never declared**~~ — **FIXED 2026-07-31**: added
  `unligatedCrossoverIds: new Set()` to `store.js` `_initialState`. Probe: writer is `api.js:124`
  (not :120); absent from `_initialState` — confirmed. **The "a second reader would crash" framing
  was wrong**: all 5 readers are safe (`cadnano-editor/main.js:2280` and `frontend/src/main.js:1766`
  reference-compare, so `undefined !== undefined` never fires; `pathview.js:4901` does `new Set(ids
  ?? [])`; `pathview.js:2254` reads a module-local Set; and the two apparently-undefended sites
  `frontend/src/main.js:1778` + `scene/response_delta.js:106` pass into
  `unligated_crossover_markers.js:103`, which *also* does `new Set(unligatedIds ?? [])`). So this was
  a shape/hygiene fix, not a crash fix. **New debt found**: the *3D* store
  (`frontend/src/state/store.js`) has the identical undeclared key, written by `api/client.js:428,743`
  → logged as **TD-26**.
- ~~**`Ctrl+Shift+L` is case-sensitive**~~ — **FIXED 2026-07-31**: `ligation_debug.js:403` now tests
  `(e.key === 'l' || e.key === 'L')`. Probe confirmed the anchor verbatim. Note the convention is
  split 2-and-2, not uniform — `main.js:1369` (Save As) is uppercase-only too, and `:1349` (redo) is
  both-case. Left `:1369` alone: it is out of this bullet's scope, and Shift always yields uppercase
  under a standard layout, so both are robustness fixes rather than live bugs.
- ~~**Codec logic outside the codec**~~ — **FIXED 2026-07-31**: `cadnano-editor/main.js:2070` now
  calls `parseForcedLigKey(key)?.id` (import added at `:51`). Probe: the site sits in an
  `else if (key.startsWith('fl:'))` branch whose sibling already uses `parseXoverKey`, and
  `parseForcedLigKey` (`element_keys.js:109-111`) is `key.slice(3)` behind the same guard — a
  byte-equivalent drop-in. No other `.slice(3)` on an fl key exists repo-wide.
- ~~**`const DEBUG = true` is shipping**~~ — **FIXED 2026-07-31**: flipped to `false` at
  `overhang_pathview.js:57` and given the editor's flip-then-revert comment. Probe softened the
  severity: it gates `console.debug` (browser *verbose* level, hidden by default) with a
  `[DD-pathview]` tag, at 9 call sites — noisy, not user-visible.
- ~~**`ui/overhang_pathview.js:60-63` re-declares `RULER_H/LABEL_R/TOP_PAD` locally**~~ —
  **FIXED 2026-07-31, and the root cause with it.** Probe found the real numbers: `RULER_H` 26 = 26
  (**equal**), `LABEL_R` 12 vs 16 and `TOP_PAD` 12 vs 18 (**differ**), `BOTTOM_PAD` has no editor
  counterpart — so the `// mirror cadnano-editor` comment was false for 2 of 3. Root cause: the
  editor's `pathview.js:256` exported only 4 of its 7 layout constants, so the fork had to
  re-declare the rest and drifted. Fix: extracted the 9 drawing-grid constants **verbatim** into a
  new leaf module `cadnano-editor/pathview/layout.js` (zero imports); `pathview.js` imports them;
  `overhang_pathview.js` imports the 5 it shares (incl. `RULER_H`) and keeps `LABEL_R`/`TOP_PAD`/
  `BOTTOM_PAD` local with `// editor: 16` / `// editor: 18` markers. Pinned by
  `pathview/layout.test.js` (4 tests). **This also closes TD-14's reverse-coupling bullet** — nothing
  now imports `pathview.js` for constants, so the 4977-LOC module no longer enters the main-app
  bundle (only `main.js:41` `initPathview` imports it).
- ~~**All 3 editor e2e specs `goto('/cadnano-editor')` with no `?doc=`**~~ — **PROMOTED 2026-07-31**
  → `manual_validation_debt.md` **MV-EDITORDOC**. Substance confirmed (zero multi-doc coverage), count
  corrected: **2 specs, 3 `goto` calls** (`cadnano_sliceview_positions.spec.js:86`,
  `autobreak_edges.spec.js:194` **and** `:257`). `cadnano_crosssection.spec.js` is NOT an editor spec
  — it drives the 3D app at a hardcoded `http://localhost:8000`. Writing an e2e spec is not this
  loop's job (Playwright is non-routine per `CLAUDE.md`); the manual op is the cheaper oracle.

Added 2026-07-30 by the `project_cadnano_overhaul` plan audit (that plan is now deleted; its
architecture content lives in the rule):
- ~~**`experiments/exp0{2,3,4}/run.py` still construct `LatticeType.FREE`**~~ — **DECIDE 2026-07-31
  → DEC-02.** Probe: `LatticeType` is exactly `{HONEYCOMB, SQUARE}` (`models.py:30-33`), zero `FREE`
  anywhere in `backend/`. But the entry is wrong twice over: it is **four** files, not three
  (`exp01_bond_integrity/run.py:40` was missed; 6 construction sites total), and
  **`LatticeType.FREE` is not the first failure** — every one of them imports
  `from backend.physics.xpbd import build_simulation, xpbd_step, …`, and `backend/physics/xpbd.py`
  **does not exist** (retired with the FEM/XPBD code), plus `_geometry_for_design` moved from
  `backend/api/crud.py` to `backend/core/design_geometry.py:567`. So "fix to HC/SQ" is not available:
  the physics these experiments measure is gone. Deletion vs revival is the user's call.
- ~~**`slice_plane.js` deformed-mode helix labels can mis-label at close range**~~ —
  **ACCEPTED 2026-07-31** (known since 2026-05, deliberately unfixed). Anchors re-verified verbatim:
  `TOL = 0.6` at `:840` used `:844-845` in the `_deformedFrame` label branch; separate `TOL = 0.5`
  at `:647` used `:654` in `_cellStateDeformed`. Extra detail for the next sweep so it stops
  re-deriving it: both run the **identical** start/end proximity test against
  `_cellWorldPosDeformed(row, col)` with different thresholds, so there is a 0.5–0.6 nm annulus where
  a cell reads `'free'` yet still resolves to a helix label. Only `:647` carries the `// nm` unit.
- ~~**Default helix length is not user-configurable**~~ — **ACCEPTED 2026-07-31.** Confirmed: no
  setting exists (zero hits for `defaultHelixLength`/`default_helix_length` repo-wide), and the 42 is
  **duplicated** — `crud.py:490` (`HelixAtCellRequest.length_bp = 42`) and `api.js:163`
  (`addHelixAtCell(row, col, length_bp = 42)`), whose only caller `main.js:1945` passes no length. The
  entry's own caveat holds and defuses it: a new helix inherits its neighbour's `bp_start`/`length_bp`
  (`crud.py:1907-1919`), so 42 only ever applies to the first helix on an empty design. Nice-to-have.
- ~~**`paletteColor` was cited for years and never existed**~~ — **STALE 2026-07-31: the claim is
  FALSE. `paletteColor` exists.** `rg paletteColor` → `frontend/src/ui/spreadsheet.js:62` (defined),
  `:142` (called, the last-resort fallback inside `effectiveColor`), `spreadsheet.test.js:162`, and
  named in `backend/api/routes_sequences.py:204`. The original probe searched
  `frontend/src/ui/strands_spreadsheet.js` — **a path that does not exist**. There are two
  same-named panels: `ui/spreadsheet.js` (3D app; has *both* `paletteColor` and `effectiveColor` :129)
  and `cadnano-editor/strands_spreadsheet.js` (editor; `effectiveColor` at :72 — the "~line 72"
  anchor). Their `effectiveColor`s take different arguments. **Also corrected**:
  `plan_audit_ledger.md:84` carried the same false claim, and its `:427` lesson ("a doc's own paired
  anchors are a cheap lie detector") was built on this false negative — both amended 2026-07-31.
