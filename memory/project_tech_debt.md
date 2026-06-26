---
name: tech-debt-ledger
description: Running technical-debt ledger — code paths flagged for review/removal (with why + supersession). Check when touching a flagged area.
metadata: 
  node_type: memory
  type: project
  originSessionId: a42a916c-90da-4711-b831-59182e249f46
---

Running ledger of known technical debt — code that works today but is flagged for
review or removal. Each entry: location, why it's debt, what supersedes it. Append
new items; strike through (and date) when resolved.

## Open

### Advanced/seamless scaffold routing is hash-seed non-deterministic (TODO: fix)
- **Where:** [seamed_router.py](backend/core/seamed_router.py) `_ham_path_ending`
  (~line 291) + the neighbor key it hands to `_ham_path_search`. Both sort by
  `len(adj[n])` with **no secondary `n` tiebreaker**, so equal-degree nodes keep
  their set-derived (hash-seed-dependent) order. In-code `FIXME(advanced-routing-
  nondeterminism)` marks the exact spot.
- **Why it's debt:** the Hamiltonian path → scaffold routing comes out differently
  run-to-run. `auto_scaffold_seamless` / `auto_scaffold_advanced_seamed` emit a
  **different scaffold-strand count** depending on `PYTHONHASHSEED`. Real-app impact:
  the same design routes differently on different backend runs (not just tests).
- **Repro (2026-06-04):** `tests/test_seamless_router.py::test_teeth_closing_zig`
  (asserts exact `bridge_xovers==6`, `scaf_strands==4`) is **flaky ~50%** — 4 pass /
  4 fail across 8 fresh processes. Also varies `advanced_seamed` on teeth between 1
  and 4 scaffolds (originally misattributed to the live app rewriting the fixture).
- **History:** `seamless_router._ham_path_ending` (its OWN copy) deliberately uses
  `(len(adj[n]), n)` WITH the `n` tiebreaker to avoid exactly this (documented in
  [[seamless-scaffold-router-architecture-and-hard-won-lessons]] lines 29–32). The
  2026-06-01 budgeted-DFS refactor that delegated the search to the shared
  `seamed_router._ham_path_search` dropped the tiebreaker → regression.
- **Action (TODO, NOT done):** add a secondary `n` key to BOTH the starter sort
  (line 291) and the neighbor key passed to `_ham_path_search`, then verify teeth
  routing topology is unchanged (`bridge_xovers==6`, `scaf==4`) and de-flake the
  test. **TOPOLOGY-SENSITIVE — get user review before/after.** Marked by the user as
  work-to-be-done 2026-06-04; surfaced while committing CI fixtures for the router
  tests ([[seamless-scaffold-router-architecture-and-hard-won-lessons]]).

### Overhang Bind/Unbind button (legacy OverhangBinding pair model)
- **Where:** [overhang_sequences_panel.js](frontend/src/ui/overhang_sequences_panel.js)
  — the per-row Bind/Unbind button (last column of the Overhangs sidebar panel).
  Drives `api.patchOverhangBinding(id, { bound })` against the **OverhangBinding**
  pair model (`overhang_a_id`/`overhang_b_id` + `bound` flag).
- **Why it's debt:** this is an OLD, abandoned method of implementing overhang
  binding. User flagged it 2026-06-03 ("everything else works fine").
- **Superseded by:** oh_binder strands — `StrandType.OH_BINDER` +
  `Domain.binds_overhang_id` (the real binding oligo that hybridizes to the
  overhang). See [[oh-binder-strands-overhang-binding-oligos]] and the related
  OverhangBinding extensions / assembly bindings work.
- **Action:** do NOT extend the Bind/Unbind button or the OverhangBinding model.
  Slated for removal once the binder migration completes. Inline code comment marks
  the spot (search `TECH DEBT / FOR REVIEW`).
