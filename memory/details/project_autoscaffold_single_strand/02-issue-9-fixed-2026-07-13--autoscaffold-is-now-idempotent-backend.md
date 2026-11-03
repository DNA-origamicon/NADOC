# ✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`) — supporting detail

[Topic head](../../project_autoscaffold_single_strand.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

**⚠ CRITICAL CORRECTION (2026-06-08, build session 5) — THE FIXTURE WAS CORRUPT. Read this before anything below.**
The whole ISSUE-8 saga (fragmentation, ragged faces, "gap stagger", continuous-routing redesign, the 172-bp
gap-fill) was an artifact of a BAD TEST FIXTURE. The old `tests/fixtures/teeth.nadoc` was ALREADY seamless-
autoscaffold-routed (34 `auto_scaffold_seamless:*` crossovers, 4 strands) — its tooth faces had been pushed from
the clean `[0,41] [84,125] [168,209]` out to ragged `[-3,47] [72,132] [157,218]`. Every measurement of "nominal
faces" was against that corruption. User caught it; replaced the fixture with the clean `workspace/preroute_teeth.nadoc`
(0 crossovers, 32 per-domain scaffold strands, uniform faces). **On the CLEAN fixture: plain `auto_scaffold_seamed`
AND `auto_scaffold_seamless` both route teeth to 1 strand, 0 fragmentation warnings** (so ISSUE-8 fragmentation was
mostly the fixture too). The **section router** routes clean teeth to 1 strand, full coverage, worst gap dip 9 bp,
gap clearance 32 bp, 0 violations — it BEATS the hand reference (13 bp). Plain seamed bridges a gap (clearance 0),
so the section router still adds value. Everything below this line was reasoning against the corrupt baseline —
treat as historical. The real follow-up was **ISSUE-9: autoscaffold is not idempotent** (re-running on a routed
design re-extends faces → that's how the fixture got corrupted) — ✅ **FIXED 2026-07-13**, see below.
`tests/test_section_router.py` now green (8 tests,
gap invariants); `test_seamless_router.py::test_teeth_closing_zig` re-pinned to 1 strand. Full suite 1845 pass.
Dumbbell fixture `10-6-10hb_seamed.nadoc` is ALSO pre-routed (latent same corruption). **GATE FLIPPED DEFAULT-ON
(2026-06-08):** `auto_scaffold_seamed` now routes any multi-section design through the section router by default
(removed the `NADOC_SECTION_ROUTER` env requirement; kept `has_multisection_helix` + `not forced_ligations` +
None-fallback). The in-app seamed Auto-scaffold (crud.py:7340 → auto_scaffold_seamed) now keeps teeth gaps clear;
the per-helix seamed path used to bridge a gap (min_clear=0). Test `test_seamed_autoscaffold_keeps_teeth_gaps_open`
pins the PUBLIC entry. **User must restart servers** to pick it up. Eyeball still owed.
**FINAL ROUTING SHAPE (section_router, 2026-06-09):** TRUNK (continuous helices) routes `matched=True` → `auto_scaffold_seamed`
= MATCHED ends (far = near + P, P=288 default; +33 outer extension is the deliberate periodic-boundary spacing) so the two
farthest faces puzzle-fit for end-to-end polymerization via periodic-boundary staples (user decision).
**Far crossovers sit on the LEFT of their junction (user rule 2026-06-02 — do not "fix" the off-by-one):** after
`far = near + P` (P a whole multiple of HC 21 / SQ 32, so the translate stays lattice-valid and in integer-turn helical
register), a far crossover whose `bp % period` lands in `_HC_SCAF_BOW_RIGHT`/`_SQ_SCAF_BOW_RIGHT`
([seamed_router.py:40](../../../backend/core/seamed_router.py#L40), applied at `:550`) is stepped one bp left to its bow partner.
So copy N's far crossover and copy N+1's near crossover form an adjacent `(bp-1, bp)` HJ pair at the polymer seam, and
far−near deltas are `{P, P-1}`, not a clean `P`. Pinned by `test_matched_ends_far_is_left_side_translate_of_near`
([tests/test_seamed_router.py:60](../../../tests/test_seamed_router.py#L60)) on a fresh 18HB — a plain 3×6 block does NOT
reproduce the bow-left near-crossover bug. Related: matched-ends does NOT close a circle (the serpentine stays one linear
strand — the closing nick is gated on `is_circular`), and faces stay RAGGED by ~4-6 bp (lattice-phase-forced), so
far = near + P gives per-helix tessellation, not a flush face. WINDOWS (teeth) route
bounded → per-helix-face turns at each tooth's own face (gaps clear, ≤9bp dip, ≥32bp clearance). Trunk↔tooth connection
double-crossovers placed at the tooth MIDPOINT (`_adj_pair_in_domain` picks valid pair nearest `(lo+hi)/2` → 23/24, 108/109,
183/184). NOTE teeth tile every 84bp but matched P=288 isn't a multiple of 84, so the TEETH don't tile across the polymer seam
(user accepted: only the trunk backbone connects). tests/test_section_router.py = 14 tests. Full suite 1851 pass.
**SEAMLESS ROUTER (2026-06-09):** `auto_scaffold_seamless` now dispatches multi-section designs through the section router
in SEAMLESS MODE (`route_sections(design, seamless=True)` returns a `SeamlessResult`). Windows route seamless
(`auto_scaffold_seamless` per sub-bundle); the TRUNK routes bounded-SEAMED so it closes into a circle and the single nick
buries mid-bundle (`_1_2[124]` teeth / `_1_2[82]` dumbbell). Tradeoff the USER CHOSE: pure seamless makes only LINEAR paths
(nick stuck at outer face), so a buried nick needs a circular scaffold = the backbone gets 4-6 seam crossovers; teeth stay
fully seamless. Fixes the robustness gap: the HC dumbbell fragmented into 8 pieces under native seamless → now 1 strand,
clean gaps (teeth 11/24, dumbbell 5/76), full coverage. `_route_subbundle(seamless=)` + `route_sections(seamless=)` params.
Falls back to native seamless if `route_sections` returns None. Tests: `test_seamless_autoscaffold_single_strand_buried_nick`.
**REFERENCE = CORRECT, fully-seamless target (2026-06-09):** `workspace/Scaffold routing/teeth_seamless_route1.nadoc` is the
hand-routed GOLD standard: 1 strand, **0 seam crossovers** (fully seamless — every xover an end/bridge), PROPER nick
(5'/3' on the SAME helix `_0_0[125]/[126]` adjacent bp = a circle opened at one phosphate, buried), full coverage, gaps 13/24.
It routes the trunk as a seamless Hamiltonian **CYCLE** (nick helix split into two domains, route closes through it) — NO seamed
backbone. My current section-router seamless mode falls short: the bounded-SEAMED trunk costs **~6 seam crossovers** (the user
flagged this). Test pins it: `test_reference_seamless_route_is_golden` (PASSES, validates the gold) +
`test_seamless_autoscaffold_is_fully_seamless_like_reference` (XFAIL strict, asserts router has 0 seams — the target).
Helpers: `nick_is_proper` (same-helix adjacent-bp), `seam_crossover_count` (process_id `auto_scaffold_seamed:seam`).
**FIXED (2026-06-09):** `auto_scaffold_seamless(seed, close_cycle=True)` routes a uniform bundle along a Hamiltonian path with
ADJACENT endpoints (`_closeable_path`) + adds a closing zig → circular scaffold → `_linearize_circular_scaffolds` buries the
nick. Section-router trunk (seamless mode) uses it; teeth now route FULLY SEAMLESS (0 seams, proper buried nick `_0_1[123/124]`),
matching the reference. Test `test_seamless_autoscaffold_is_fully_seamless_like_reference` now PASSES (xfail removed).
**Resolved 2026-09-10:** the HC dumbbell trunk's degree-2 6-RING now closes seamlessly.
The closing edge follows `(path[-1], path[0])`, so it uses the final helix's free
3′ face. Public seamless routing also defaults to a cycle with a buried nick and
warns for unclosed output; see `project_seamless_router.md`.
Historical limit: closing the full cycle created a face conflict at the endpoints
(free-face mismatch → 3 fragments), so it FALLS BACK to the bounded-seamed trunk (1 strand, buried nick, ~4 backbone seams).
SQ teeth close cleanly. Fixing HC-ring closure (place the closing zig at the endpoints' actual FREE faces, not the FORWARD-hA
heuristic) is the remaining follow-up if a seam-free HC dumbbell is wanted. Full suite 1853 pass.

**SEAMED ROUTABILITY GUARD (2026-07-05) — asymmetric SQ sections that silently fragment now 422.**
The seamed router fragments a connected design into a DISJOINT scaffold on two shape classes; instead of
emitting the broken scaffold (which fed garbage duplex coverage to the CanDo FEM — see [[project_cando_fem]]
G3), the seamed+matched endpoints now refuse (422 → frontend toast). Two causes, both reproduced headless:
(A) **odd helix group** — `_auto_scaffold_seamed_impl` pairs the Ham path in steps of two from both ends
(`seam (1,2)(3,4)…` + `near (0,1)(2,3)…`), so `path[n-1]` is never paired → orphan singleton (3×3→8+1, L→6+1).
A Ham path EXISTS; it's a parity bug. (B) **no Hamiltonian path** in the *scaffold-crossover* adjacency
graph (`_build_adj`) — staircase triangle (`brute_ham=False`) → the whole component is skipped at
seamed_router.py `if not path or len(path)<4: continue` → every helix its own scaffold. Predictor =
Hamiltonicity of the **crossover** graph (NOT the raw cell grid) + helix-count parity; cell-grid
cut-vertices do NOT predict it (L has 5 but its xover graph is a clean path — fails on parity). **SEAMLESS
handles odd counts fine** (zig-zag pairing routes 3×3/L to 1 strand) → the guard is seamed/matched-ONLY.
Impl: pure `seamed_router.seamed_routability_errors(design)` (returns [] for forced-ligation + multisection
designs = out of scope; those route via hinge/section routers) called by
`routes_scaffold_routing._guard_seamed_routable` → `HTTPException(422, detail=…)` BEFORE any state mutation.
Frontend needed NO change: `_request` maps `detail`→`lastError.message`, `autoscaffold_picker` already
toasts it. Tests: `test_seamed_router.py::test_guard_*` (6). Full suite 4072 pass (1 pre-existing NAMD
benchmark fail, unrelated). NOT fixed — the underlying router; odd/no-Ham sections still can't be seamed-
routed to one strand (that's the ISSUE-8 continuous-routing rework). Guard just makes the failure LOUD.

ISSUE-8 (issues_ledger.md): a connected multi-section "teeth" design must route to ONE scaffold
strand but the seamed router fragments (teeth.nadoc → 11 strands). Investigation + build session 1
done 2026-06-08. Full design + status: plan file `~/.claude/plans/floating-crunching-widget.md`.

**Hard-won finding — you CANNOT merge scaffold fragments by adding crossovers** (the dossier said
so; now reproduced empirically): the reference's exact 62 crossovers placed on a clean per-section
seed → 55 strands; the existing `_auto_scaffold_seamed_impl` on a clean teeth seed → 26 strands.
`_ligate_xover` only fires when a crossover bp exactly equals a domain terminus, an alignment the
existing nick math achieves for uniform prisms but NOT for offset multi-section helices. So both
the originally-planned Euler-merge (A) and per-section seam/end (B) approaches are DEAD. The
scaffold must be **constructed as one strand**, not merged.

**Validated approach (= the dossier's "2-opt cycle reconnection"):** decompose the design into
uniform sub-bundles (continuous-helix cap; each segmented bp-window), raster each as an explicit
serpentine, then **2-opt splice** each window cycle into the trunk (nearest continuous helix
grid-adjacent to the window) via a reciprocal double-crossover done by DOMAIN-LIST SURGERY (not
ligation). Reference structure decoded: cap serpentine (rows 0–1) + per-window tooth serpentine
(rows 2–3) joined ONLY at `1_0↔2_0`; single buried nick `0_0` 103/104; 62 xovers = seamed 2-domain
raster. Prototype `/tmp/teeth_v3.py` achieves **1 strand, 0 bad transitions, no gap-scaffold, no
double-cover** — only FULL COVERAGE remains (the 1-domain serpentine loses ragged helix-end bits;
need the seamed 2-domain face→seam→face structure, extending ONLY at outer bundle ends not into
gaps).

**SHIPPED 2026-06-08 (separate from the rework) — circular-scaffold de-circularization nick.**
When seamed/matched routing closes the scaffold into a loop (5'/3' joined by a crossover; the NADOC
model can't store a true circle so it's a linear strand + an unligated end-join crossover, which
trips the UI circular warning), `_linearize_circular_scaffolds` (seamed_router.py) now reopens it:
nick at a buried non-crossover bp nearest the bundle bp-center (`_choose_buried_nick`) → `make_nick`
splits it → `_ligate_xover(closing)` re-merges into ONE linear strand re-rooted at the nick (open
5'/3' buried mid-bundle). Replaces the old `if matched_ends` block that was gated on the never-set
`getattr(s,"is_circular")` (Strand has no such field → never fired). Runs every mode at the end of
`_auto_scaffold_seamed_impl`. Test `test_circular_scaffold_is_linearized_at_buried_noncrossover_nick`;
1836 pass. NOT yet added to seamless_router (a circular seamless route would still warn). The
overlap/extension-into-gaps defect (seamless extends teeth hi-ends into gaps, even merging teeth)
is still part of the deferred rework.

**SHIPPED-IN-HARNESS 2026-06-08 (build session 2) — FULL COVERAGE + GENERALIZED, not yet codified.**
The single-strand construction now WORKS on BOTH teeth (square) and the 10-6-10 dumbbell (honeycomb):
**1 scaffold strand, 0 bad transitions, full coverage, no double-coverage**, 5'/3' buried mid-bundle.
Path = decompose (continuous helices = TRUNK; segmented helices grouped by bp-overlap = WINDOWS) →
route each sub-bundle with the EXISTING `auto_scaffold_seamed` (trunk → 1 linear full-cov strand; each
window → a single loop nicked at one bp on one helix = a near-free cycle) → 2-opt domain-surgery splice
each window cycle into the trunk at a grid-adjacent helix double-pair (X,X+1). Prototype lives in repo:
`scripts/section_router_prototype.py` + `scripts/section_router_harness.py` (superseded `/tmp/teeth_v3.py`).
GOTCHA: collect ALL crossovers from the routed sub-seed (near/far TURNS use `create_near_ends`/
`create_far_ends`, NOT an `auto_scaffold_` prefix — dropping them = phantom broken junctions).

**FIXTURE CORRECTION (2026-06-08, user caught it) — `teeth_unrouted.nadoc` is NOT the real design.**
`tests/fixtures/teeth.nadoc` IS the same base design as `workspace/Scaffold routing/teeth_seamed_route1.nadoc`
(the validated reference) PRE-fine-routing: identical grid + `bp_start` + `axis_start` origin for all 16
helices; the ONLY diff is `length_bp` (the reference extended helices ~40 bp for blunt ends). The real
design has RAGGED faces (`bp_start ∈ {-11,-8,-5,-3}`, per-helix section ends differ). `teeth_unrouted.nadoc`
is an IDEALIZED, origin-reset (`bp_start=0`), UNIFORM-FACE block — convenient but NOT representative. Always
validate the section router on `teeth.nadoc` (or the reference base), NOT teeth_unrouted.
