# ✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`) — supporting detail

[Topic head](../../project_autoscaffold_single_strand.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
