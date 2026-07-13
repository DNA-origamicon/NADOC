---
name: project_autoscaffold_single_strand
description: ISSUE-8 autoscaffold single-strand rework — why crossover-merging fails and the validated decompose+2-opt-splice approach
metadata: 
  node_type: memory
  type: project
  originSessionId: e8eafa48-297e-4c65-8397-7de37a254477
---

## ✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`)

**Re-routing an already-routed design no longer re-extends anything.** `reset_scaffold_to_structure()` runs at the
top of `auto_scaffold_seamed` / `auto_scaffold_matched` / `auto_scaffold_seamless` and retracts the design to its
structural seed first, so N routes ≡ 1 route. The routing algorithm itself is UNCHANGED — only its input is
normalised. Pinned by `tests/test_scaffold_idempotence.py` (12 tests).

**It was never teeth-specific.** A plain 4HB bundle (no teeth, no sections) ratcheted `168 → 189 → 199 → 210` bp
and `6 → 9 → 12` crossovers over three routes, on BOTH routers. Teeth is just where it was *visible*.

**The oracle: STAPLES ARE THE STRUCTURE.** Autoscaffold never touches staple strands, so a helix's true extent is
the bp span of its staple domains (including staple overhangs running past the scaffold). Verified: staple spans
held at `[0,167]` across three re-routes while the helices ratcheted to `[-30,179]`. And in the real multi-section
fixtures the staple intervals ARE the scaffold sections, gaps and all — teeth `[(0,41),(84,125),(168,209)]`,
dumbbell `[(0,41),(126,167)]` — i.e. exactly the "clean per-domain seed" that was wanted. **The scaffold is route
output; the staples are the design.** Reset clamps INTO the staple intervals and never grows the scaffold to fill
them; forced ligations bail out (their fixed-edge topology isn't derivable from the staples).

Second bug fixed alongside: the seamed router stamps three `process_id`s on its crossovers
(`auto_scaffold_seamed:seam`, bare `create_near_ends`, `create_far_ends`) but the old clear matched only the
`auto_scaffold_` prefix — so the end-turn crossovers survived every "clear" (hence the accumulation), and
`_clear_auto_scaffold_route_for_seamed` (used by `auto_scaffold_matched`) had never actually worked.

**Retired concern:** `10-6-10hb_seamed.nadoc` being pre-routed is no longer "latent corruption" — a re-route now
resets to the structural seed first, so a pre-routed fixture can't poison a measurement any more.

**Owed:** user eyeball — run Auto-scaffold twice on a teeth design and confirm the faces don't move.

---

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
farthest faces puzzle-fit for end-to-end polymerization via periodic-boundary staples (user decision). WINDOWS (teeth) route
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
KNOWN LIMIT: the HC dumbbell trunk is a degree-2 6-RING; closing the full cycle creates a face conflict at the endpoints
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

**BUILD SESSION 4 (2026-06-08) — the visual metric + the real root cause + continuous-routing redesign.**
Plan file `~/.claude/plans/floating-crunching-widget.md` "BUILD SESSION 4" block has the full decode — read it.
TL;DR: the metric that matters is **inter-tooth GAP OCCUPANCY**, not "extension past nominal" (the old
per-domain checks gave false green). Now measured in `tests/test_section_router.py`: total in-gap scaffold
ref=91 bp vs ours=172 bp (~2×); min per-gap empty clearance ref=18 vs ours=11. **ROOT CAUSE:** decompose+splice
routes each window as an INDEPENDENT CYCLE → every tooth helix turns at both ends → dips into every gap; the
reference threads helices straight through the trunk → staggered → gaps stay open. **The fix is CONTINUOUS
(thread-through) routing**, not the bounded-extension tweak. **USER REFRAME (banked):** route on (helix,section)
DOMAIN nodes (same-helix different-section = separate nodes, both traversed); extend each end only to its
co-existing-neighbour crossover; faces = co-termination planes; gaps empty *emergently*; teeth gaps are
physically functional (must be open); if extend-to-face ever overlaps strands → new ledger invariant. SHIPPED
(kept, tested, 1841 pass, gated default-off): gap regression tests + `seamed_router` `bounded_ends` (per-helix-
face near/far + one-group ragged-window path) + `auto_scaffold_seamed_bounded`; cut worst per-domain dip 16→13
but total occupancy still 172 (every window still an independent cycle). NEXT: build continuous routing.

**RAGGED-FACE FIX (required for the real design):** the seamed router fragments a RAGGED sub-bundle (the
trunk splits, coverage lost), so `_route_subbundle` now squares each sub-bundle's faces to the common
[min lo,max hi] before routing (`_uniformize` — same blunt-end squaring the hand-route did). With it,
`teeth.nadoc` → **1 strand, full coverage, 0 bad transitions, 0 overflow** (was: falls back / 11 fragments).
Dumbbell + idealized fixture also pass.

**REMAINING GAP (this is why it's NOT visually done):** the reuse approach inherently over-extends —
uniformization + the router's end-search +3…+period floor push ~34 bp/window/helix (822 bp total on teeth)
of SCAFFOLD INTO THE GAPS. Topologically a valid single strand, but it would render with BLOATED teeth, NOT
the reference's clean no-gap routing (reference keeps each tooth's domains within [tooth_lo,tooth_hi]). The
benign part (266 bp trunk-outer blunt ends) is fine. **Closing the gap needs NON-EXTENDING window end-turns
(turns at/just-past the true faces) — the harder construct path the reuse approach can't reach.** This is
the real next step, ahead of any "done" claim. Gated default-OFF (`NADOC_SECTION_ROUTER`) so production is
untouched meanwhile; falls back safely (`route_sections → None`) on any un-cleanly-routable input.

**THE ORIGINAL "tradeoff" framing (still relevant for the non-extending build):** sub-bundle routing extends helix geometry +
scaffold past faces (+3…+period). Fine for the TRUNK (blunt-end, propagate). For WINDOWS it pushes
helix+scaffold into the physical GAPS (all 16 teeth helices overflow their seed extents). Lossless
suppression is impossible when no valid crossover sits exactly at a window face (measured: raw seed ≤6 bp
off, production `teeth.nadoc` ≤1 bp, HC dumbbell ≤4). So window end-turns go either just-inside (≤6 bp
tooth-TIP gap) or just-outside (≤ few bp MINIMAL extension, full coverage). **Pending USER tradeoff
decision** before codifying `section_router.py` (gate `_has_multisection_helix`, dispatch from
`auto_scaffold_seamed`, DEFAULT-OFF flag first, then eyeball, then flip). Plan file has the full session-3
checklist incl. trunk-helix-extension propagation (mechanical) as a separate productionization step.

User decisions banked: fully-general router target; trunk = nearest-continuous-helix-per-window;
free weave / existence-proof (don't byte-match the 4 reference routes in `workspace/Scaffold
routing/`); gate the new path to multi-section designs so uniform-prism + matched-ends behavior is
untouched. This is the area `LESSONS`/dossier flag as tests-pass-but-visually-wrong — verify in-app
(load teeth.nadoc, trace single strand) before claiming done.
