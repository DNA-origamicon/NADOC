# The hinge router (compliant retry) — supporting detail

[Topic head](../../project_hinge_autoscaffold.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## The hinge router (compliant retry)
`backend/core/hinge_router.py` — `route_hinge(design) -> (Design, SeamedResult)|None`,
dispatched from `auto_scaffold_seamed` when `design.forced_ligations` present.
Reuses the PROVEN seamed pipeline so seams + extended ends come for free, and is
**SELF-GATED**: returns None unless its output is exactly 1 strand AND passes
`scaffold_routing_invariants` — so it can NEVER regress (worst case → classic fallback).
Steps: (1) the primitive's cross-gap bridges are 2-domain scaffold SEED strands; DROP
the FL records (seeds still bridge) and run `auto_scaffold_seamed` → with bridges
carried by the seeds it routes to one seamed strand. (2) Re-derive a ForcedLigation
for each in-strand junction crossing the gap (helices NOT lattice-adjacent). (3)
Self-gate. Declines (→ fallback) for: no FLs, FL between lattice-adjacent helices
(one-off manual anchor), bridges not all coalesced, or any invariant violation.

## Status (honest)
- **Single-link hinge (2x2): routes compliantly** — 1 strand, full coverage, 4 seams,
  extended ends, validator + gate pass, FLs re-derived.
- **Multi-link hinges (2x4/2x6): FALL BACK** (None) — their multi-bridge seeds don't
  coalesce in-place yet. Safe (no regression), pinned as **xfail** in
  `tests/test_hinge_router.py::test_multi_link_hinge_routes` so the goal stays visible.
  The open problem: a robust multi-bridge MERGE (per-leaf seamed routes joined via FL
  nick+ligate fragments — order-dependent; needs proper domain-surgery splice at the
  reciprocal FL pairs). The self-gate makes solving it safe to iterate.
- NOT verified live in-app (headless localhost unreachable under WSL).

## CAUTION: `workspace/Hinge_route_test.nadoc` was OVERWRITTEN
During the first (reverted) attempt the user's gold reference got overwritten with the
bad `:hinge` raster output (17 `:hinge` crossovers, 0 seams). It is NOT git-tracked.
The ORIGINAL gold (session-start) was 1 strand / 41 domains / `:seam`+`create_near/far_ends`
+`manual` crossovers / 6 FLs — the compliant hand-routed existence proof. If restored,
it's the target structure for the multi-link merge. The gate's regression-pin test
auto-skips if the file is restored to non-`:hinge` content.

## Why earlier approaches failed (don't retry)
- Single-pass raster (the reverted v1): no seams, no end-extension → regression.
- Route each leaf independently + naive splice: fragments (small inner FL loop).
- Generic collapse-and-route: ragged hinge-link faces → fragments.
See [[project_forced_ligation]] (the manual-anchor feature this builds on) and
[[project_primitive_library]] (hinge primitives).

## Automation ledger (design-automation loop, intake 2026-06-26)
Full auto-generation of an autoscaffold hinge design is tracked in `design_automation_backlog.md`
(Tier 4 "Hinge auto-generation", G1–G6 gap map):
- **AF-32** — `hb.force_ligate` (place cross-gap FL links headlessly). Prereq for AF-33.
- **AF-33** — headless hinge BUILDER (recreate `2x2/2x4/2x6` from scratch), golden-equal to the saved
  `workspace/Primitives/*.nadoc` (oracle = `canonical_topology` + FL-endpoint-set + round-trip + validator).
  **P1 (2x2) SHIPPED 2026-06-26:** `backend/api/headless_hinge_build.py::build_hinge_primitive("2x2_single_hinge_link")`
  replays the golden's OWN feature-log recipe (`create_bundle(40)` → +8 duplex shift → 2 gap-bridge resize+force_ligate)
  through the shipped wrappers; pinned by `assert_matches_primitive` (in `tests/automation_harness.py`). P2 (2x4/2x6)
  open — decode the sibling goldens' `RoutingClusterLogEntry.children` params the same way; ASK-FIRST the multi-link gap
  geometry. NB the bridge trims are asymmetric (`scaf_1_0` 3p −3, `scaf_1_1` 5p −16) hand-authored gap routing.
- **AF-34** — reusable `assert_scaffold_routing_compliant` oracle (wraps `scaffold_routing_invariants`) +
  hinge autoscaffold route validation. **SHIPPED 2026-06-26:** oracle in `tests/automation_harness.py`
  (non-vacuity guard = design HAS a non-ref scaffold; then the gate, `require_seams` as the caller's flag),
  driven end-to-end `build_hinge_primitive("2x2_single_hinge_link")` → `hb.auto_scaffold` → single seamed
  invariant-clean scaffold + `validate_design` (no golden file needed — builds from scratch). 2x2 GREEN;
  2x4/2x6 ride the `test_hinge_router` xfail (G6). GOTCHA: a plain `create_bundle` routed seamed is NOT
  compliant (blunt staples bury end crossovers) — the oracle's non-hinge green example is a SEAMLESS route at
  `require_seams=False`, the same route at `require_seams=True` is the load-bearing red (LESSONS H8).
- **AF-35** — headless multi-op primitive PLACEMENT (feature-log replay) to compose a hinge into a larger design.
- **G6 (this file's open problem)** — multi-link 2x4/2x6 routing is the algorithm blocker, NOT an AF item;
  the `test_hinge_router::test_multi_link_hinge_routes` xfail keeps it visible.

## DECODED gold weave (2x6 Hinge_route_test, restored 2026-06-26) — the routing target
Leaf A = rows {0(outer),1(inner)}, leaf B = rows {4(inner),5(outer)}; N cols; FLs bridge inner rows 1_c↔4_c at the gap face (bp ~-8..8).
- **Outer rows 0 & 5**: standard seamed double-pass serpentine (create_near_ends + create_far_ends + :seam). Exactly what auto_scaffold_seamed emits for a 1-row run.
- **Inner rows 1 & 4**: woven ACROSS the gap — `1_5→1_4→FL→4_4→4_3→FL→1_3→1_2→FL→4_2→4_1→FL→1_1→1_0→FL→4_0→[4_1..4_5 serpentine]`. Hop the gap at each FL; within-row crossovers between hops (row1 pairs at far=223, row4 serpentine at 95/96+218). All these inner connections are `manual` process_id in the gold.
- **Outer↔inner join at col 5**: double crossovers 5_5↔4_5 (98/99) and 1_5↔0_5 (98/99).
KEY FINDING: routing a 2-row leaf through the existing seamed router gives a DIFFERENT inner-row structure (near-caps+seams), NOT the gold's far-pairs+gap-bridges. So the gold is a genuine **B-graph route** (seamed serpentine threading FL edges). No post-hoc merge reproduces it (all fragment: nick+ligate 2→6/9, in-place tangles).

## GENERALIZATION INVESTIGATION (2026-06-26, arbitrary 2x(2n)) — methods tried + the REFRAMED correct model
User asked to generalize routing to arbitrary 2x(2n) hinges. **USER'S GOVERNING MODEL (load-bearing, decides everything):** forced ligations are *sacred* — autoscaffold must NOT drop, move, or re-derive them (they encode unknown design intent). From autoscaffold's view an FL-merged strand is *just a pre-connected (multi-helix) scaffold strand*; autoscaffold must connect ALL scaffold strands into ONE via the established rules (seams + end crossovers), preserving the FL junctions. FL placement is irrelevant to autoscaffold — it just routes around them. (User: "as long as there are an even number of helices, there is a scaffold routing solution.")
- Primitive structure (probed): 2x(2n) = 4 rows {0,1,4,5} × 2n cols; n hinge links = 2n FLs, one bridge per column on inner rows 1↔4. Each bridge is a 2-domain scaffold strand spanning 1_c+4_c, with the inner-helix scaffold **gap-extended** (bp ~−8/8, the hand-authored asymmetric trims).
- **Methods empirically TRIED and why they FAIL:**
  1. *Naive adjacency-augment* (add FL gap edges to `_build_adj`, run stock `_hamiltonian_path`): the path uses only ~3 of 2n FL edges (a Hamiltonian path needs only n−1 edges) → unused bridge seeds stay as separate strands → multi-strand. FAIL.
  2. *Route-leaves-then-splice*: gap-extended seeds don't split into clean full-helix leaves (split+route → 5–8 strands); bridge endpoints sit at strand TERMINI so `make_nick` raises ("bp is the 3′ terminus"); naive ligation circularizes (same-strand). FAIL. (Confirms the old "splice fragments" note.)
  3. *Collapse-the-gap* (relabel rows 4,5→2,3 → contiguous 4×2n bundle, which the stock seamed router DOES route to 1 compliant strand ∀n=2,3,4): mechanically works BUT it drops+re-derives FLs at the route's natural gap crossings (only ~3 cols: 0 + a seam at the top 2), relocating them → **violates FL-sacredness → DISQUALIFIED.** NB the current shipped 2x2 `route_hinge` ALSO drops+re-derives FLs — works only because the re-derived endpoints happen to coincide; by the user's rule that's luck, not design.
- **FL-preserving hybrid — BUILT 2026-06-26 and EMPIRICALLY FAILS (then reverted; tree green).** Implemented in seamed_router (opt-in `fl_edges` param: don't exclude FL strands, augment adjacency with FL edges, `_fl_aware_hamiltonian_path` weaves the path through ALL 2n FL edges, skip placement at FL edges) + route_hinge calling it FL-aware. The path part WORKS (the woven backbone traverses every bridge — e.g. 2x2 main strand `10 40 50 51 41 11 01 00` uses both FLs). **But it fragments into multiple strands** (2x2→3, 2x4→5): the seamed router's UNIFORM double-pass requires the inner connection to be a mid-helix SEAM (a double crossover), whereas a forced ligation connects at the helix END (the gap-extended bp). Skipping the FL-edge crossover therefore breaks the seam/far-end double-pass CLOSURE, so the second passes split off as separate strands. Suppressing seams on FL helices (tried) over-suppresses (2x2→0 seams). **ROOT CAUSE (decisive):** the END-vs-SEAM mismatch — the gold avoids it with an ASYMMETRIC inner structure (row1 single-pass full-length domains + END/FL connections, row4 double-pass), which the uniform seamed machinery cannot express. Enabling fact (still true): a single-visit Hamiltonian path using ALL 2n FL edges exists (2x4 e.g. `00 10 40 50 51 41 11 01 02 03 13 43 53 52 42 12`); the path is NOT the blocker — the double-pass closure is.
- **STRUCTURAL ANALYSIS (why any valid single-strand solution is gold-LIKE, 2026-06-26).** User confirmed: not all helices have seams (some MUST be seamless — the gate only requires seams to EXIST, not per-helix; modify gate/tests if they assume per-helix), from-scratch is authorized, and **the gold is NOT unique** (many valid solutions; gold is just the cleanest) → acceptance = single strand + gate + validator, NOT gold-exact. Preserve-mode (`_auto_scaffold_seamed_impl` with FLs present) gives for free: outer row 0 seamed strand + outer row 5 seamed strand + 2n FL U-bridges (each U = a 1_c+4_c 2-domain strand; rows 1,4 are ENTIRELY the FL strands, single-pass). To make ONE strand you must weave the inner "ladder" (rows 1,4 = 2 rails, FL bridges = 2n rungs) using ALL rungs (an unused rung = an orphan strand). **Combinatorial fact:** a Hamiltonian path on a 2×(2n) ladder using ALL 2n rungs has BOTH endpoints in the SAME rail (even rung count) → both connect to ONE outer row; the OTHER outer row can only attach mid-weave (a forbidden 3-way branch) UNLESS one inner row is DOUBLE-passed (a serpentine return giving extra endpoints). So every valid single-strand hinge route is forced into the gold's asymmetric shape: one inner row single-pass (in the rung weave) + the other inner row double-passed (weave + serpentine return) + both outer rows seamed double-pass. There is no simpler topology.
- **FROM-SCRATCH GENERATOR PLAN (the build):** (1) outer rows 0,5: reuse seamed double-pass (seams + extended ssDNA ends for margin) — preserve-mode already emits these; (2) inner ladder: boustrophedon through rows 1↔4 using every FL rung + row-1/row-4 lattice crossovers; (3) one inner row double-passed (serpentine return) to expose a row-4 endpoint for the row-5 connection; (4) connect outer↔inner at the weave endpoints (lattice crossovers); (5) preserve FL records verbatim; (6) self-gate (single strand + `scaffold_routing_invariants` + `validate_design`), fall back on miss. Reuse seamed primitives (`_place_xover`, `_nick_bp`, `_extend_helix_lo`, seam-bp helpers); generate the inner weave explicitly. Validate vs gate+validator for 2x2/2x4/2x6/2x8 (NOT gold-exact). Convert `test_hinge_router::test_multi_link_hinge_routes` xfail → real pins.
- **CONCLUSION: all reuse-of-seamed-machinery methods fail; the from-scratch weave generator is the ONLY path** (must produce the gold's asymmetric single/double-pass inner structure with END-FL connections; reuse the seamed bp-helpers only for the OUTER rows + seam-bp math, generate the inner weave explicitly; validate vs the 2x6 gold + the gate; self-gated). Acceptance bar (user-chosen): single scaffold strand + `scaffold_routing_invariants` clean + `validate_design`. Current shipped state: 2x2 single-link works (drop-and-rederive route_hinge — re-derives IDENTICAL FLs, which technically touches them but the user noted that's the luck-not-design path); 2x4/2x6 fall back (xfail). The drop-and-rederive 2x2 path remains because FL-preserving doesn't yet yield one strand for ANY n.
- **Universal-algorithm / more-examples assessment (user asked):** the algorithm is NOT hinge-specific — it's "autoscaffold a design with some pre-connected scaffold strands → one strand preserving those junctions." More HINGE examples at other n WON'T help (the n=3 gold fully specifies the regular ladder pattern). Examples of DIFFERENT FL topologies WOULD help (FL strands spanning 3+ helices, non-gap anchors, multi-section + bridges, honeycomb) — they stress the general connect-preserving-fixed-edges rule beyond the regular ladder.
NB the OLD "do NOT modify shared `_auto_scaffold_seamed_impl`" constraint is necessarily relaxed for the FL-preserving hybrid (it needs an opt-in FL-aware path+placement); keep it byte-identical for non-FL designs.

## NEW REFERENCE SET + LADDER-CORE PROTOTYPE (2026-06-26)
User added 5 gate-clean hand-routed solutions in `workspace/Scaffold routing/`:
`2x2/2x4/2x6_single_hinge_link_routed` + **`3x2_hinge_routed` + `3x4_hinge_routed`**
(the 3x = NEW **3-row-per-leaf** topology — leaves rows {0,1,2}&{5,6,7}, gap rows 3,4).
All 5 verified: **1 scaffold strand, seams present, `scaffold_routing_invariants`
clean, FLs IDENTICAL to the primitive** (the "single/double/triple" vs "single_routed"
filenames are loose/misnamed — trust the designs, not the names; FLs are preserved,
not re-derived). Naming decoded = `(rows-per-leaf)x(cols)`, 2 leaves, **FLs = cols**
(one rung per column at the inner rows' LO end, orientation alternating by col parity).

**DECISIVE GENERALIZATION (the 3-row examples unlock it):** the route ALWAYS
decomposes into (a) leaf **bodies** = every row except the gap-facing inner one →
plain seamed double-pass raster (SOLVED, reuse `auto_scaffold_seamed`); (b) the
**gap ladder** = the 2 inner rails + N rungs → the entire hard core, and it is the
SAME 2×N ladder regardless of leaf thickness. So **the irreducible problem is never
bigger than a 2×N rung-ladder**; leaf thickness adds only standard raster.

Universal weave pattern (extracted quantitatively from all 5, identical up to a
column reflection): every rung used exactly once; **spine rail** (leaf-A inner)
double-passed at all cols except one end (HI sweep + LO re-entry in the weave);
**single rail** (leaf-B inner) single-passed except double at the OPPOSITE end
(body turnaround); both body ports at the far end column, one per rail (even N →
both trail ends land on the spine rail = leaf A — matches the parity proof above).

**SHIPPED: isolated combinatorial core** `backend/core/hinge_ladder.py` ::
`weave_gap_ladder(n_cols:even≥2) -> LadderWeave` — pure, no geometry/`Design`.
Emits the ordered inner-rail visit trail (rail/col/half + rung|rail|body junctions)
+ body ports. Tests `tests/test_hinge_ladder.py` (27, green; full suite 3271 pass):
invariants (all rungs once, the asymmetric coverage, single connected trail, ports)
for N=2..10 + **coverage-signature reproduction against all 5 reference designs**.
This is the "from-scratch weave generator" core the GENERALIZATION INVESTIGATION
concluded was the ONLY path — now built & proven in isolation.

**ALSO SHIPPED: the FULL abstract weave** `weave_hinge_full(leaf_a_rows, leaf_b_rows,
n_cols) -> HingeWeave` (same module) — composes the ladder core with boustrophedon
rasters of the OUTER rows spliced at the ladder body ports (leaf-A outer descends
into the rail-A spine + returns double-passed = both trail ends in leaf A = the
scaffold nick; leaf-B outer = a mid-trail excursion off the rail-B port). Returns
`HingeWeave.trail` = ordered `(row,col)` grid-visit list; each helix appears once
(single-pass) or twice (double-pass→seam), never more. Geometry-free. Validated
(14 more tests, 41 total green): single connected trail + ≤2 coverage + all rungs
once + both ends in leaf A, for k=2/3/4 × n=2/4/6; and **trail length EXACTLY equals
each reference's scaffold-domain count (13/27/41/21/43)** — strong correctness pin.
Helper `_leaf_raster` = the boustrophedon. The reference k=2 vs k=3 differ only in
WHEN leaf B is rastered vs the rung weave (both valid; non-unique) — the generator
picks the gold/2x6 ordering uniformly for all k.

**The abstract algorithm is COMPLETE & verified.**
