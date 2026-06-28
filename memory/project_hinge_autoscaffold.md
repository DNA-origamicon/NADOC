---
name: project_hinge_autoscaffold
description: "Hinge scaffold routing — route ONE seamed strand through forced-ligation gap-bridges (hinge primitives), self-gated against the scaffold-routing invariants. + the regression gate that now guards ALL autoscaffold paths."
metadata: 
  node_type: memory
  type: project
  originSessionId: 7cfe31c9-8568-42d1-a022-298315c1bd8f
---

# Hinge autoscaffold + scaffold-routing regression gate (2026-06-26)

Hinge primitives (`2x2_single` / `2x4_double` / `2x6_triple_hinge_link` in
`workspace/Primitives/`) are two rigid leaves bridged across a gap by **forced
ligations** (cross-gap scaffold links). Autoscaffold must route ONE strand through
the bridges. A forced ligation here is a *structural bridge to route through*, NOT a
one-off manual anchor to route around.

## The regression gate (the durable, critical deliverable)
`backend/core/scaffold_invariants.py` — `scaffold_routing_invariants(design, *,
require_seams) -> list[str]` (empty == compliant). Two invariants every autoscaffold
output must satisfy:
1. **Seams present** (`require_seams=True` for seamed/matched/section; False for
   seamless): `scaffold_seam_positions(design)` non-empty (real mid-helix double
   crossovers, not a seamless raster).
2. **≥3-base ssDNA margin**: every *non-seam* scaffold crossover (end/turn cap) sits
   ≥`MIN_SSDNA_MARGIN`(=3) bp clear of any staple domain on its helix (the hard-won
   "scaffold crossovers live in extended ssDNA, never buried in a staple"). Seam
   crossovers are exempt (intentionally mid-duplex). Vacuous on helices w/o staples.
Why it exists: `validate_design` encodes NONE of this; the first hinge attempt shipped
a seamless raster (no seams, crossovers buried in staples) tests-green. See [[LESSONS]] H8.

Tests `tests/test_scaffold_invariants.py`: checker unit tests + a **property test
parametrized over EVERY autoscaffold entry point** (`ROUTING_ENTRY_POINTS` =
seamed/matched/seamless) asserting compliance, a stapled-margin test, and a
regression pin on the known-bad output. **MERGE RULE: a new autoscaffold return path
must be added to `ROUTING_ENTRY_POINTS`.**

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

## bp REALIZER — SHIPPED & WIRED 2026-06-26 (2x routes live; the user's goal)
`backend/core/hinge_weave_router.py` :: `realize_hinge_weave(design) -> (Design,
SeamedResult)|None`. Walks `weave_hinge_full`'s trail and places crossovers via the
PROVEN seamed bp-helpers; RUNGS are NOT placed (the FL bridge seeds already carry
them → FLs preserved verbatim). **Dispatched FIRST from `route_hinge`** (which
`auto_scaffold_seamed` calls) → falls through to the old drop-rederive path, then
classic, on any miss. Self-gated: returns None unless 1 scaffold strand + FLs
preserved + no skipped placements + `scaffold_routing_invariants` clean +
`validate_design` passes. **LIVE-VERIFIED through `auto_scaffold_seamed`: 2x2/2x4/2x6
→ ONE gate-clean validated strand, FLs preserved.** Full suite green; `test_hinge_
router::test_multi_link_hinge_routes` xfail → REAL PIN. Tests: `test_hinge_weave_
router.py` (+ updated `test_hinge_router.py`). NOT yet exercised in the browser app
(headless); user re-runs autoscaffold on the 2x4 to see the single strand.

KEY REALIZER MECHANICS (load-bearing, hard-won):
1. **Crossover face = helix scaffold direction** (NOT a free choice): junction X→Y
   sits at X's 3′ end → HI/far if `_is_forward(X)` else LO/near. Adjacent helices
   always have opposite parity, so X & Y agree. So near/far is forced.
2. **Seams split double-passed helices.** Every helix visited twice EXCEPT turn/nick
   helices (a U-turn `trail[i-1]==trail[i+1]`, or the two trail ends) must be split
   ONCE by a mid-helix double crossover. That is a **maximum-cardinality matching**
   (networkx `max_weight_matching`, a declared dep) over the to-seam helices using
   actual trail-junction edges — greedy leaves helices uncovered where max-matching
   doesn't. ≥1 seam satisfies the gate's seams-present rule.
3. **Faces are relative to the scaffold DUPLEX (seed coverage), not helix geometry**
   (which may be pre-extended past the duplex). Use `_scaffold_coverage` for lo/hi;
   getting this wrong = crossovers land where no seed strand exists → no ligation →
   multi-strand (the bug that cost the most). `_extend_*` then pushes faces ≥3bp clear.
4. The placed route is a CLOSED loop; `_linearize_circular_scaffolds` reopens it with
   a buried mid-structure nick (else validate fails "terminus on crossover").
5. Decline (None) unless every FL is a gap rung (railA↔railB same col) — an FL between
   lattice-adjacent helices is a manual anchor → classic preserve path handles it.
NB do NOT reuse the seamed impl's uniform path→seam/end machinery (END-vs-SEAM
mismatch breaks it, proven 3×); place crossovers DIRECTLY from the trail.

## STATUS: k≥2 ALL WORK (2x2/2x4/2x6 + 3x2/3x4) — 2026-06-27
- **k=2 (2x2/2x4/2x6): WORKS live** through `auto_scaffold_seamed` — 1 strand,
  gate+validator clean, FLs preserved.
- **k=3 (3x2/3x4): NOW WORKS** — 1 strand, seams (4/9), gate+validator clean, FLs
  preserved, full coverage. No real 3x primitive fixtures exist (only the user's
  routed REFERENCES), so tested via reconstruction (`_strip_to_primitive` in
  `tests/test_hinge_weave_router.py`: strip scaffold → per-helix duplex seeds +
  2-domain gap-bridge seeds from FLs; faithful — k=2 reconstruction also routes).
- **THE k=3 FIX (rail-fold-face, the 6th load-bearing mechanic):** a rail helix is
  entered/exited via its RUNG (forced ligation) at the GAP end, so EVERY other
  crossover on it must sit at the OPPOSITE (outer) end — the direction-determined
  face is OVERRIDDEN for any fold touching a rail helix (`rail_fold_face`). Why k=2
  hid this: there the rung FL sits DEEP (bp −8, extended past the duplex), so a
  same-end fold at bp ~5 still lands inside the bridge domain and ligates. For k=3
  the FL sits at the duplex EDGE (bp 8), so a same-end fold at bp ~5 falls OUTSIDE
  the seed → can't ligate without moving the FL terminus → that column's bridge
  orphans (the old 2-strand result). The reference confirms it: 3x rail crossovers
  `(5,0)-(5,1)@84` / `(2,0)-(2,1)@90` are at the HI (outer) end, opposite the LO rung.
  Gap end is derived from the FL bp vs the rail's duplex midpoint (not assumed LO).
- Odd N rejected (falls back); all hinges seen are even N. Full suite green.

## FULL PIPELINE AUTOMATED 2026-06-27 — build kxN → route → verify
`backend/api/headless_hinge_build.py::build_hinge(rows_per_leaf=k, n_cols=N, *,
lattice=SQUARE, length_bp=40)` — generalizes the 2x2-only spec builder to ANY k≥2,
even N, from scratch. Two k-row SQUARE leaves + the standard 2-row gap (leaf A rows
0..k-1, leaf B rows k+2..2k+1; rails k-1 & k+2) via `create_bundle` (serpentine cells)
+ `_shift_duplexes`, then ONE `force_ligate` rung per column. **The gap-trim geometry
the old note feared turned out NOT to need hand-authoring:** rail A & rail B always
have OPPOSITE polarity (rows differ by 3), so the REVERSE rail's 3′ is the LO (gap)
terminus → pass it as `force_ligate`'s three-prime side and EVERY rung lands on the
same LO face uniformly (no per-column trims). (Why this matters: alternating gap ends
would make adjacent rail-rail folds unsatisfiable — see the rail-fold-face mechanic.)
The realizer is k-agnostic, so it routes the result directly.
- **VERIFIED build→`hb.auto_scaffold`→compliant for 2x2/2x4/2x6, 3x2/3x4/3x6, 4x4**
  (1 strand, seams, gate clean, validates, FLs preserved, full coverage). Tests:
  `tests/test_headless_hinge_build.py::test_build_kxn_hinge_routes_compliantly` +
  bad-dim rejection. Full suite green. NOT exercised in the browser app (headless).
- The old name-based `build_hinge_primitive("2x2_single_hinge_link")` stays (it
  byte-matches the SAVED golden via the hand-authored spec; `build_hinge` instead
  picks a uniform routable geometry, not golden-equal). `_strip_to_primitive` (in the
  weave-router test) still serves the reconstruct-from-routed-reference path.
- REMAINING (not blocking): odd N (reciprocal pairs ⇒ even only); HONEYCOMB lattice
  (only SQUARE exercised); browser-app exercise; a UI entry point if desired.

## SEAMLESS hinge routing — SHIPPED & WIRED 2026-06-27 (k≥2 all work, BURIED NICK)
`backend/core/hinge_weave_router.py::realize_hinge_weave_seamless(design)` —
dispatched FIRST from `auto_scaffold_seamless` when FLs present (self-gated → falls
through on miss). Single-pass (NO seams). **The route is a Hamiltonian CYCLE** (a
closed loop), so `_linearize_circular_scaffolds` reopens it with a BURIED mid-bundle
nick — exactly like the seamed route, NO dangling ends. (v1 used an OPEN vertical
serpentine → left one pair of ends unextended/uncrossed with no buried nick — the
user's reported bug; the cycle fixes it.)
- **Construction:** a horizontal SPINE along one outer row + a boustrophedon SNAKE
  over the remaining rows, every column sweep crossing the gap once via its rung.
  Edges iterated WITH wraparound (`trail[1:]+[trail[0]]`) so the loop closes; the
  closing crossover stays unligated → linearize buries the nick. Rail-fold-face
  override IS used here (same as seamed).
- **TWO load-bearing parities (decoded from `workspace/3x2_hinge_seamless.nadoc`):**
  (1) **spine row by k-parity** — TOP outer row for EVEN k, BOTTOM for ODD k; this
  flips column 0's sweep direction so each rail is entered from its rung end (rail
  fold lands outer). Required because at each rail `col-sweep-down ⟺ c ≡ k (mod 2)`
  and the cycle's closure fixes col 0's direction. (2) rail-fold-face → outer end.
  Get the spine parity wrong and odd-k fragments (4/8/12 strands).
- Existence first confirmed by graph search (single-pass Ham path + closeable + full
  Ham CYCLE using all rungs exists ∀ even k×N); the user's 3x2 example gave the
  realizable structure — no further proof needed.
- **VERIFIED via `auto_scaffold_seamless`: 2x2/2x4/2x6, 3x2/3x4/3x6, 4x4** → ONE
  seamless strand, validated, FLs preserved, full coverage, **nick buried mid-helix**
  (5'/3' on the same helix at adjacent interior bp — pinned in the test). Tests:
  `test_headless_hinge_build.py::test_build_kxn_hinge_routes_seamless` (asserts buried
  nick) + `test_hinge_weave_router.py` seamless tests. NOT browser-exercised.
- Circular import: `SeamlessResult` is imported LAZILY inside the function (top-level
  caused a cycle); keep lazy.

## STAPLE/OVERHANG FLs NO LONGER DERAIL ROUTING (2026-06-27) — `bound end to root`
Reopened bug: `workspace/3x6_hinge_bound_end_to_root.nadoc` (a 3x6 hinge + an in-app
"bound end to root" OVERHANG BINDING B1) had autoscaffold OVERRIDE the binding +
fragment the scaffold into 8 strands. **Root cause:** the design's 8 forced ligations
were two kinds — 6 genuine scaffold rungs (both endpoints SCAFFOLD) + **2 staple-level
FLs from the overhang duplex** (both endpoints on STAPLE strands, into a staple-ONLY
helix `h_XY_3_0` = the "root"). The realizers assumed ALL `forced_ligations` are
scaffold rungs: (a) `_analyze_leaves` demanded a rectangular grid → the lone staple-only
root helix made it non-rectangular → decline; (b) the gate required EVERY FL to be a
rail↔rail rung → the 2 staple FLs failed → decline. Both declined → classic fallback
preserved the 6 rung seeds but couldn't consolidate (8 strands) and ignored the binding.
**Fix (user-chosen "router-side filter"):** scaffold routing now owns ONLY FLs whose
BOTH endpoints are scaffold-covered (`_scaffold_fls(forced_ligations, coverage)`), and
`_analyze_leaves(design, scaffold_hids)` builds the leaf grid from scaffold-covered
helices only (staple-only helices excluded). Staple/overhang FLs are carried through
VERBATIM (the self-gate's `orig==new` over ALL FLs enforces it). Applied in BOTH
`realize_hinge_weave` + `realize_hinge_weave_seamless` (+ `route_hinge`'s drop-rederive
fallback splits `scaf_fls`/`other_fls`, keeping `other_fls` through the seed and output).
**VERIFIED on the real file: seamed AND seamless → 1 strand, all 8 FLs preserved, gate
clean, validates, full 36-scaffold-helix coverage, 6 rungs honored as in-strand junctions.**
Tests in `test_headless_hinge_build.py`: `_scaffold_fls` filter pin, self-contained
staple-only-helix-doesn't-fragment pin, + guarded real-file end-to-end (skips if .nadoc
absent). `test_hinge_weave_router::test_declines_non_hinge_bundle` updated for the new
`_analyze_leaves` arity. Full suite green (3340 pass). NB the per-helix coverage filter
classifies by helix, not per-endpoint-strand-type — correct for the staple-ONLY-helix
case; a staple FL sitting on a scaffold-covered helix would still be seen as scaffold
(not the reported scenario; revisit if it arises).

## ⚠️ WORKSPACE FIXTURE CORRUPTION (2026-06-27) — `2x6_triple_hinge_link.nadoc`
The 2x6 PRIMITIVE file (`workspace/Primitives/`) got OVERWRITTEN with a ROUTED design
(1 scaffold strand + 17 crossovers, vs the original 18 seed strands + 0 crossovers) —
mtime today, NOT by any session script (they only read it; likely the user's running
app saved over it). These workspace `.nadoc` files are NOT git-tracked, so no restore.
The realizer correctly DECLINES a routed input → `test_realizes_single_gate_clean_
strand[2x6]` + `test_multi_link_hinge_routes[triple]` now SKIP (guarded:
`design.crossovers or ≤1 scaffold strand` ⇒ not a primitive). Self-contained build→
route coverage (`test_build_kxn_*`) is unaffected. To restore a valid 2x6 primitive:
`build_hinge(2, 6)` (the generator) → save to the path — ASK the user first (don't
overwrite their .nadoc unprompted).
