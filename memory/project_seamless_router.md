---
name: Seamless Scaffold Router — architecture and hard-won lessons
description: backend/core/seamless_router.py — zig-zag end crossovers, closing zig, non-deterministic DFS fix, coverage boundary mismatch
type: project
originSessionId: 4a5f87b3-ab49-4bcb-84bb-6252b80892b0
---
## What it does
`auto_scaffold_seamless(design)` places one scaffold crossover per adjacent helix pair at a **helix end** (hi face if hA is FORWARD/even-parity, lo face if REVERSE/odd-parity). Each helix is visited once. For multi-section designs, groups are stitched by HJ bridges (same as seamed Phase 1). Returns `(updated_design, SeamlessResult)`.

**File:** `backend/core/seamless_router.py`
**API endpoint:** `POST /design/auto-scaffold-seamless` (crud.py)
**Tests:** `tests/test_seamless_router.py` — 10 tests, all passing (2026-04-28)
**Fixture:** `tests/fixtures/teeth.nadoc` — 16-helix SQ (8 spine + 8 teeth, 3 intervals/tooth)

## Key architectural difference from seamed router
- **Seamed**: visits each helix twice (two half-domains); HJ crossovers at midpoints + lo+hi ends.
- **Seamless**: visits each helix once; one crossover per adjacent pair at hi or lo end only. Hamiltonian path endpoints become the scaffold 5'/3' termini — no open-end skipping.

## Closing zig (CRITICAL insight)
In a multi-section design, path[0] and path[-1] of a non-last group are both adjacent to the bridge helix. After the bridge HJ connects group G to group G+1, the resulting topology is **not circular** — the bridge breaks any loop. Therefore the closing zig crossover (path[0] ↔ path[-1] at hi face) is safe to place within non-last groups.

This is what enables teeth.nadoc to route to 4 scaffold strands instead of 7.

**Implementation:** `zig_pairs.append((h_fwd, h_rev))` for `(path[group_starts[gi]], path[group_boundaries[gi]])` when `first_hid in adj.get(last_hid, set())`.

## Budgeted + pruned DFS (2026-06-01)
`_ham_path_ending` now delegates per-start to the shared `seamed_router._ham_path_search` (visit budget + admissible connectivity/degree pruning), keeping the original "first path per start, check `path[-1]==target_end`" rule but sharing ONE budget across starts. Before this, the unbudgeted DFS hung forever on large bundles (66-helix Shaft). Pruning is admissible so teeth's closing-zig path is unchanged. See LESSONS J1; the `len(remaining)==1` terminal special-case in `_ham_path_search._can_complete` is load-bearing (without it every search wrongly reports "no path").

> ⚠ **REGRESSION (discovered 2026-06-04): this delegation REINTRODUCED the non-determinism the section below was written to fix.** `seamed_router._ham_path_ending` (~line 291) sorts starters by `len(adj[n])` with NO secondary `n` tiebreaker, and passes the same tiebreaker-less key to `_ham_path_search` for neighbor ordering. So the determinism the seamless `_ham_path_ending` carefully provides via `(len(adj[n]), n)` is LOST once the search runs in the shared seamed code. Result: `test_teeth_closing_zig` is now **flaky ~50% across PYTHONHASHSEED** (the "all passing" / "verified result, scaffold strands=4, warnings=[]" claims below are only ~50%-true). Tracked in the tech-debt ledger ([[tech-debt-ledger]]); in-code `FIXME(advanced-routing-nondeterminism)` at the spot. NOT yet fixed (topology-sensitive).

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
