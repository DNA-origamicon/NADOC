# bp REALIZER — SHIPPED & WIRED 2026-06-26 (2x routes live; the user's goal) — supporting detail

[Topic head](../../project_hinge_autoscaffold.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
