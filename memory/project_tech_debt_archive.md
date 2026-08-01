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
