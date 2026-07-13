---
name: Scaffold Router — implementation status
description: New CSP scaffold routing system in backend/core/scaffold_router.py
type: project
originSessionId: 9f602024-1a47-4924-9d3a-bebeb724cea3
---
`backend/core/scaffold_router.py` — constraint-satisfaction scaffold router (written 2026-04-27 on kinematics-cleanup branch).

**Why:** Old autoscaffold deleted (greedy raster scan, didn't handle irregular structures). New spec from user's collaborator: CSP-based, domain-level, seam/end alternation, bulge decomposition.

**Architecture:**
- `RouterDomain` (frozen dataclass): contiguous scaffold segment. `start_bp=5' end`, `end_bp=3' end` (NADOC convention — REVERSE has start>end).
- `CandidateXover` (frozen dataclass): undirected; `dom_a_id/dom_b_id/bp/tag`.
- `Routing` dataclass: `domains, xovers, path_order`.
- `ValidationResult`: `valid, errors, warnings`.

**Key functions:**
- `extract_router_domains(design)` — nick-merging from scaffold strands; gap ≥1bp → separate domains.
- `build_candidate_graph(domains, design, seam_tol, end_tol)` — uses `HC_SCAFFOLD_CROSSOVER_OFFSETS` / `SQ_SCAFFOLD_CROSSOVER_OFFSETS`; tags "seam" (near midpoint of BOTH domains) or "end" (near extremum of BOTH domains).
- `validate_routing(design, domains, candidates)` — V1–V8 pre-conditions.
- `_csp_backtrack(...)` — recursive backtracking; MCV heuristic; alternation hard constraint; steric exclusion per helix.
- `_solve_routing(domains, candidates, fixed)` — runs CSP from each start domain.
- `_route_bulge(...)` — stub recursive bulge router (needs completion for dumbbell/gear designs).
- `apply_routing_to_design(routing, design)` — atomic strand/crossover replacement.
- `auto_scaffold(design, seam_tol, end_tol, preserve_manual, max_backtracks)` — top-level entry; BCC decompose, route each component, apply.

**API endpoint:** `POST /design/auto-scaffold` in crud.py (body: seam_tol, end_tol, preserve_manual, max_backtracks).

**Tests:** `tests/test_scaffold_router.py` — 27 tests, all passing (2026-04-27). Covers 2HB, 4HB HC, 6HB HC, 4HB SQ, domain extraction, nick merging, tagging, validator, coverage preservation, total-bases check, crossover topology, valid bp positions.

**6HB routing architecture (post-2026-04-27):**
- 84bp helices are split at midpoint (bp 42) into L-half [0..42] and R-half [42..83].
- The 12 half-domains form 4 disconnected components of 3 nodes each (bp 42 mod 21 = 0 is not a valid HC crossover, so L↔R intra-helix bridges are impossible).
- Routes produce 4 separate scaffold strands (L-halves of each triangle and R-halves of each triangle). Together they cover all 84bp on all 6 helices.
- `_domain_segment` extends each domain to its physical end (ssDNA scaffold loop) and to its seam boundary using `end_tol` and `seam_tol`.

**Hamiltonian DFS now budgeted + pruned (2026-06-01):** `seamed_router._hamiltonian_path` / `_advanced_hamiltonian_path` and `seamless_router._ham_path_ending` previously had NO budget/pruning → hung forever on large bundles (66-helix Shaft). Now route through shared `seamed_router._ham_path_search` (visit-budget `_HAM_PATH_BUDGET = 1e6` + admissible connectivity/degree pruning). Solvable graphs return the identical first path (golden tests unchanged); hopeless graphs give up instead of hanging. See LESSONS J1 — and note the `len(remaining)==1` terminal special-case is load-bearing. (This is the seamed/seamless path, separate from the CSP `auto_scaffold` which already had `max_backtracks`.)

**Matched-ends variant (2026-06-02):** `seamed_router.auto_scaffold_matched(design)` — new autoscaffold mode for blunt-end end-to-end polymerization. Shares `_auto_scaffold_seamed_impl(matched_ends=bool)` with classic seamed; Phases 1-2 identical, Phase 3 re-orchestrated: caps EVERY near pair at the far face (no lowest-helix skip) at `far_xover_bp = near_xover_bp + P`, where `P = ceil((max_hi-min_near+1)/period)*period` (whole multiple of HC 21 / SQ 32 → translate stays lattice-valid + faces in integer-turn helical register). Endpoint `POST /design/auto-scaffold-matched`; op_kind `'auto-scaffold-matched'` (added to `SnapshotLogEntry` Literal in models.py); UI radio `value="matched"` ("Matched Ends") in both autoscaffold pickers. **Far crossovers forced to the LEFT side (user rule 2026-06-02):** after computing `far_xover = near+P`, step bow-right-phase far crossovers to their left bow partner (`xover_bp -= 1 if xover_bp%period in _HC_SCAF_BOW_RIGHT`); non-bow-right ones already sit left. So copy N's far crossover + copy N+1's near crossover form an adjacent (bp-1, bp) HJ pair at the polymer seam (was on the wrong side before). far-near deltas become {P, P-1}. Regression test `test_matched_ends_far_is_left_side_translate_of_near` (fresh 18HB) asserts: 1 strand, `validate_design().passed`, every far crossover `%period not in bow_right`, deltas `%period in (0, period-1)`. Verified on fresh 6HB/18HB and the fresh 66-helix Shaft (`Shaft_v1_fresh.nadoc`, 6x11 block, length 105=5*21): 1 strand, validation passes. **Corrections to the original plan's premises:** (1) capping both faces does NOT close a circle — the serpentine stays ONE LINEAR strand, so the closing nick is gated on `is_circular` (an unconditional nick over-split 1→2); (2) faces are RAGGED by ~4-6 bp (lattice-phase-forced), so far=near+P gives per-helix tessellation, NOT a flat face / `span = k*period` flush — the global cadnano seam-gap readout won't trivially show 0. (3) The `workspace/Robot Arm/Shaft_v1.nadoc` test file is ALREADY fully scaffold-routed (1 strand, 129 xovers) — re-running autoscaffold on it collides; test matched on FRESH `make_bundle_design` bundles. **~~Pre-existing flake noted~~ — FIXED (verified 2026-07-13):** `test_seamless_router.py::test_teeth_closing_zig` used to pass only ~5/16 hash seeds because the shared Hamiltonian search ordered equal-degree nodes by set-iteration (hash-seed) order. Both the starter sort and the neighbor key now carry the `(len(adj[n]), n)` lex tiebreaker ([seamed_router.py:296](../backend/core/seamed_router.py#L296)); the test passes 8/8 fresh seeds. See [[seamless-scaffold-router-architecture-and-hard-won-lessons]].

**Known gaps / TODO:**
- Bulge subroutine is a best-effort stub — dumbbell/gear designs need full recursive implementation.
- 2-opt cycle merging not implemented (disconnected cycles fall back to separate components).
- seam_tol/end_tol defaults (5 bp) may need tuning for very short helices.

**How to apply:** Call `auto_scaffold()` on a design with scaffold strands (one per helix from `make_bundle_design`). Multi-component routing is atomic — all strands applied in one pass to avoid sequential-apply conflicts between components sharing helix IDs.
