---
name: Seamless Scaffold Router — architecture and hard-won lessons
description: backend/core/seamless_router.py — zig-zag end crossovers, closing zig, non-deterministic DFS fix, coverage boundary mismatch
type: project
originSessionId: 4a5f87b3-ab49-4bcb-84bb-6252b80892b0
---
## What it does
`auto_scaffold_seamless(design)` now defaults to a **closed route with one buried nick**:
the 5′/3′ termini are adjacent bases on the same helix, inside the bundle. This is
the user-confirmed target (2026-09-10), not separated termini on an open raster.
Each helix is traversed once, with the nick helix split into two domains. Turns use
end crossovers only. Multi-section designs dispatch through the section router.
Returns `(updated_design, SeamlessResult)`; `close_cycle=False` explicitly retains
open paths for section windows that are closed during splicing.

### Cycle closure and warnings (2026-09-10)
- The public command previously left `close_cycle=False`; `cube_pore.nadoc` was one
  strand with 35 crossovers and separated ends, so the strand-count warning missed it.
  The default now produces 36 end crossovers, one scaffold, no seams, and a buried
  nick at `h_XY_0_0[19/20]` after resetting the saved route to its structural seed.
- `_closeable_path` uses shared `_ham_path_search(close_cycle=True)`: closure is
  required **inside** DFS, so an open full path triggers backtracking. One fixed
  start and one visit budget cover the whole cycle search; minimum-degree and
  bipartite-balance checks reject impossible shapes early.
- Closing zig is directed `(path[-1], path[0])`, using the last helix's free 3′ face.
  Forcing the FORWARD helix first reused the hi face for FORWARD-start paths. Fixing
  this also closes the HC ring used by the dumbbell trunk without backbone seams.
- Every public return checks actual terminal adjacency, including hinge/section
  dispatch. Failure yields a `[Seamless]` warning even for one open strand. It does
  **not** claim mathematical impossibility when bounded search merely failed.
  Section fallback to interior backbone seams also warns. Reset warnings survive
  specialized dispatch. The frontend displays returned warnings as a toast.
- Regression tests cover SQ 6×6/3×4, HC 6HB, saved cube rerouting/idempotence,
  coverage/transition continuity, odd/degree-one shapes, and search exhaustion.
- Validation: focused routing/hinge tests 75 passed, 1 skipped; final `test-smart`
  decision FAST, 7,721 passed / 35 skipped, FULL deferred without a test session.
  No per-test timing violations after BigO triage; aggregate 99 s timing notice
  remains (see `project_test_parallelization.md`). Browser regression exercised
  the public command and visible warning; inspected the 3D cube and warning.
  Final frontend unit suite: 400 files / 6,282 tests passed.
  The original workspace cube checksum is unchanged.

The dated architecture notes below describe the earlier open-path implementation.

**File:** `backend/core/seamless_router.py`
**API endpoint:** `POST /design/auto-scaffold-seamless` (crud.py)
**Tests:** `tests/test_seamless_router.py` — 10 tests, all passing (2026-04-28)
**Fixture:** `tests/fixtures/teeth.nadoc` — 16-helix SQ (8 spine + 8 teeth, 3 intervals/tooth)

## Key architectural difference from seamed router
- **Seamed**: visits each helix twice (two half-domains); HJ crossovers at midpoints + lo+hi ends.
- **Seamless**: traverses each helix once; end turns close a Hamiltonian cycle, then a single buried nick sets the scaffold 5′/3′ termini. An open-path fallback warns.

## Closing zig (CRITICAL insight)
In a multi-section design, path[0] and path[-1] of a non-last group are both adjacent to the bridge helix. After the bridge HJ connects group G to group G+1, the resulting topology is **not circular** — the bridge breaks any loop. Therefore the closing zig crossover (path[0] ↔ path[-1] at hi face) is safe to place within non-last groups.

This is what enables teeth.nadoc to route to 4 scaffold strands instead of 7.

**Implementation:** `zig_pairs.append((h_fwd, h_rev))` for `(path[group_starts[gi]], path[group_boundaries[gi]])` when `first_hid in adj.get(last_hid, set())`.

## Budgeted + pruned DFS (2026-06-01)
`_ham_path_ending` now delegates per-start to the shared `seamed_router._ham_path_search` (visit budget + admissible connectivity/degree pruning), keeping the original "first path per start, check `path[-1]==target_end`" rule but sharing ONE budget across starts. Before this, the unbudgeted DFS hung forever on large bundles (66-helix Shaft). Pruning is admissible so teeth's closing-zig path is unchanged. See LESSONS J1; the `len(remaining)==1` terminal special-case in `_ham_path_search._can_complete` is load-bearing (without it every search wrongly reports "no path").

> ✅ **RESOLVED (verified 2026-07-13).** The 2026-06-01 delegation briefly reintroduced the non-determinism this section exists to prevent: `seamed_router._ham_path_ending` sorted starters by `len(adj[n])` with no secondary `n` tiebreaker and passed that same tiebreaker-less key down to `_ham_path_search` for neighbor ordering, so the determinism seamless provides via `(len(adj[n]), n)` was lost inside the shared seamed code. `test_teeth_closing_zig` went flaky ~50% across `PYTHONHASHSEED`.
>
> The tiebreaker is now applied to **both** the starter sort and the neighbor key ([seamed_router.py:296](../backend/core/seamed_router.py#L296) — `key = lambda n: (len(adj[n]), n)`, passed into `_ham_path_search`). The in-code `FIXME(advanced-routing-nondeterminism)` is gone. Re-verified 2026-07-13: `test_teeth_closing_zig` passes **8/8 fresh `PYTHONHASHSEED` values** (was ~4/8). The "scaffold strands=4, warnings=[]" claims below are true again. Keep the tiebreaker on both keys — dropping either one silently reintroduces run-to-run scaffold-strand-count drift.

## `_ham_path_ending` — why it exists
`_hamiltonian_path` sorts neighbors by ascending degree only. Equal-degree neighbors use Python set iteration → **non-deterministic** across runs. This caused the closing-zig bridge selection to flip between valid and invalid bridge helices depending on run order.

Fix: `_ham_path_ending(ids, adj, target_end, start_from)` uses key `(-len(adj[n]), n)` — descending degree, secondary lexicographic. Low-degree vertices (the bridge helix is degree-2 in the local subgraph) are explored last and naturally land at `path[-1]`. Exhaustive over all starting nodes until it finds one where `path[-1] == target_end`.

## Coverage boundary mismatch (silent failure)
`_extend_scaf_domain_hi(current, helix_id, face_val, xover_bp)` searches for the scaffold domain on that helix whose `max(start_bp, end_bp) == face_val`. If the wrong helix is chosen as bridge, its domain hi may not equal `face_val` (e.g., h_2_1 with hi=47 when face_val=23 for the closing zig). Result: silent no-op → crossover placed with no domain extension → broken topology → MORE scaffold strands.

**Fix:** Bridge helix must be:
1. FORWARD parity (even row+col sum) — avoids overcrowding at hi face
2. Same row as path[0] and path[-1] — ensures interval boundaries match
3. Selected via `_ham_path_ending` with `start_from` = a neighbor of the bridge candidate

## Bridge helix selection strategy (group-0 in multi-section)
```python
nxt_set_0 = set(groups[1])
spine_adj_0 = [hid for hid in groups[0] if any(nb in nxt_set_0 for nb in adj[hid])]
spine_adj_0.sort(key=lambda h: (not _is_forward(*helix_by_id[h].grid_pos)))  # FORWARD first
for cand in spine_adj_0:
    for start in sorted(local_adjs[0].get(cand, set()), key=lambda n: (-len(local_adjs[0][n]), n)):
        raw0 = _ham_path_ending(groups[0], local_adjs[0], cand, start)
        if raw0 and raw0[-1] == cand:
            path = raw0; break
```

## teeth.nadoc verified result (2026-04-28)
- `bridge_xovers=6`, `end_xovers=31`, scaffold strands=4, `warnings=[]`
- Teeth group path: `[h_2_1, h_2_2, h_2_3, h_3_3, h_3_2, h_3_1, h_3_0, h_2_0]`
  - Closing zig: (h_2_0, h_2_1) hi face → xovers at bp 58, 143, 228
  - (h_2_2, h_2_3) hi face → xovers at bp 47, 132, 218 (user's requested "far facing ends of helices 10 and 11")
- Bridge: (h_2_0 ↔ h_1_0) HJ
