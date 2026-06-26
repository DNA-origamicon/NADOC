---
name: feedback_aksel_abandoned
description: Aksel thermodynamic staple routing was removed/abandoned — do not reintroduce scoring-based routing
metadata: 
  node_type: memory
  type: feedback
  originSessionId: acaf664e-e0fe-4774-97ed-e5607ee3793c
---

The "Aksel" staple-routing method (thermodynamic scoring + weighted-DAG / shortest-path breakpoint selection) was **removed on 2026-06-09**. It didn't work and the user doesn't like it. Experts disagree on whether it helps folding versus other design improvements, and it added a large, hard-to-reason-about subsystem.

**Why:** the best routing is the simplest. Do not reintroduce thermodynamic scoring, `staple_scoring.py`, precursor graphs, `apply_precursor_breaks`, `score_staples`, or any DAG/optimizer-based staple routing.

**How to apply — full-autostaple order is load-bearing (nick FIRST):**
1. Linearize staples to full-length precursors, then **nick every staple at all major tick marks FIRST** (bp % period in {0,7,14} HC / {0,8,16,24} SQ) — `nick_all_major_ticks` (lattice.py). Nicks are co-linear only (never on a crossover/overhang).
2. **Then** place all possible staple crossovers EXCEPT within 7 bp (HC) / 8 bp (SQ) of an internal scaffold **seam** (a double scaffold crossover — two scaffold crossovers on the same helix pair at consecutive bps; `scaffold_seam_positions` in crossover_positions.py). Full density INCLUDING the near/far end-cap termini (`_place_auto_crossovers` gates coverage on the staple's own span, not the helix range, so edge sites at bp 0 / len-1 are placed).
3. **Then** grow fragments back: `grow_staples` (lattice.py) = greedy co-linear merge ≤56, then `_absorb_short_staples` folds any staple below the **lattice minimum (21 nt HC / 24 nt SQ = 3 tick-segments)** into a co-linear neighbour. If a straight merge fits ≤56 it just ligates; otherwise it **rebalance-then-splits** — nick the neighbour at the co-linear major tick that puts `short + near` in [min, 56] and leaves `far ≥ min`, then ligate (no crossover is ever split; the nick is always a co-linear tick). **56 is a hard cap** — the absorb no longer exceeds it. This reproduces the hand-nick a careful router leaves on an over-long seam-bridging run (the SQ seam falls *between* ticks at 122/123, so the seam fragment can't be nicked exactly at the seam; the balancing tick nearby splits it). `grow_staples` derives the minimum from `design.lattice_type` when `min_length` is None.

**Why nick-first:** placing crossovers on a tick-fragmented substrate assembles them into open chains, so NO staple cycles form → every crossover stays traversed (no nick lands on a crossover) and nothing has to be pruned. Placing crossovers on full-length staples (the old order) created ~staple loops that `ligate_crossover_chains` left unligated → nicks-on-crossovers (standalone path) or pruned crossovers / missing density (full-autostaple's old prune steps). Both are now gone.

**Anti-sandwich rule:** a grow/merge that would leave a contiguous RUN of interior binding domains all strictly shorter than both flanking domains is prohibited (e.g. 14-7-7 → 14-7-14, or 14-7-7-7 → 14-7-7-14). `_has_sandwich` (lattice.py) detects runs (not just a single short domain); enforced consistently in `make_merge_short_staples` AND `_absorb_short_staples` (straight merge + rebalance tick selection). When a sub-min fragment can't grow either way without sandwiching and can't be split (e.g. 7-nt domains), it is **left sub-min** — anti-sandwich wins over the min-length preference (rare; valid, just short).

**Merge order = uniformity:** `make_merge_short_staples` sorts candidate merges ascending by (shorter member, combined) — grow the shortest segment via its shorter neighbour, not topping a 49 up to 56. Yields uniform lengths (e.g. 18hb → mostly 21/42, no 56s).

**Validation invariant:** a strand free 5'/3' terminus on a crossover half (same helix, bp, dir) = "Strand nicked at crossover location — non-physical" hard failure in `validator.py`. Always prohibited.

Core: `nick_all_major_ticks` + `grow_staples` + `_absorb_short_staples` + `make_merge_short_staples` (lattice.py); `_place_auto_crossovers` (crud.py); nick-at-crossover rule in `validator.py`. `make_autobreak` = `grow_staples(nick_all_major_ticks(design))` (no orphaning ligate cap). Endpoints unchanged: `/design/crossovers/auto`, `/design/auto-break`, `/design/full-autostaple`. The deleted Aksel endpoints were `/design/staples/score`, `/design/staples/precursor-graphs`, `/design/auto-break-aksel`, `/design/auto-route-aksel`. Note: `auto-break` and `full-autostaple` skip the post-mutation `retry_pending_ligations` (state.py). Caveat: the standalone two-button path (Auto-crossover then Auto-break) still places crossovers on full staples, so it can leave cycle nicks-on-crossovers on cyclic bundles (e.g. 18hb) — only full-autostaple is guaranteed clean. Pinned by `tests/test_simple_router.py`.
