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
