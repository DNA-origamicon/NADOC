---
name: feedback_staples_are_user_intent
description: A staple's location is always the user's intent; scaffold with no staple opposite it is a deliberate ssDNA loop, never a gap to fill or route around.
metadata:
  type: feedback
---

**A staple's placement is ALWAYS the user's intention. Scaffold with no staple
opposite it is an intentional single-stranded scaffold loop — not a hole, not an
omission, not something to "fill in", "repair", or "complete".**

**Why.** ssDNA scaffold loops at duplex ends (and at internal edges — comb/"teeth"
cross-sections, tooth roots, tips) are a standard, deliberate origami design element:
they suppress aggregation from **blunt-end stacking**. Essentially every origami wants
them. A helix whose scaffold runs past its staples is *correct by construction*. Any
code that treats that as a defect will silently destroy the design's anti-aggregation
features — and the corruption is invisible until the sample aggregates on the bench.

**The line: LOCATION vs CONNECTIVITY.** A staple's *location* — the set of `(helix, bp,
direction)` it covers — is the user's intent and is inviolable. A staple's *connectivity* —
where it is nicked, which fragments are ligated into one oligo, which crossovers it traverses —
is exactly what autostaple exists to compute, and it is free to rewrite it. Adding a crossover
does not move a staple; it only changes how staples are connected. So:

- A **manual crossover** is just an ordinary crossover the user placed by hand. It must NOT lock
  the staple carrying it out of the rebuild — that starved 32 bp × 2 helices of crossovers in
  `teeth.nadoc`. Autostaple must only avoid *undoing* or *duplicating* it, which it already does
  three ways over (`nick_all_major_ticks` skips recorded crossover bps; the placer seeds
  `occupied` from every existing crossover half; its closing `ligate_crossover_chains` rebuilds
  the junction from the record). Fixed 2026-07-13 — locking is now **forced ligations only**,
  which are joins autostaple genuinely cannot re-derive.
- Corollary: any invariant check should compare staple **coverage** before/after, never strand
  identity or domain count.

**How to apply.**

- **Scaffold routers must NEVER create, extend, trim, split, or delete a staple strand
  or domain — ever.** They may extend helices and scaffold domains only. (`section_router`,
  `seamed_router`, seamless router: all currently clean — keep them that way.)
- **Never derive a staple footprint from the scaffold.** There is deliberately no code path
  that fills the staple slot to match scaffold coverage. Do not add one. If autostaple looks
  like it is "missing" staples somewhere, that region is an ssDNA loop and it is correct.
- **Do not infer terminus-vs-accident from position.** The specific bug this rule was written
  for: `_place_auto_crossovers._coverage_hole` decided whether an unstapled bp was a real
  5'/3' terminus or an accidental hole by asking whether it fell inside the slot's global
  `[min, max]` staple span. That only holds when every ssDNA loop is at a bundle cap. With
  *interior* loops (teeth), the span straddles them, every loop read as an accident, and the
  tooth-edge crossovers were starved — while the identical site at a bundle cap was allowed.
  **Every staple-interval boundary is a legitimate terminus, wherever it sits in the helix.**
  The correct question is the bow-side one manual placement already asks (`_build_place_crossover`):
  the bp the crossover's bow points toward must carry staple on both helices. Fixed 2026-07-13.
- **Staple-mutating stages (autostaple/break/merge) may only run under an explicit user
  invocation, and must not lay a staple domain across an unstapled region.** `grow_staples` /
  `_absorb_short_staples` merge only *co-linear, abutting* fragments, so they cannot bridge a
  loop — verify this still holds if you touch them.
- Diagnostic reflex: if you catch yourself writing "the scaffold covers X but the staples only
  cover Y, so something is missing" — **stop**. That is the design, and you are about to break it.

**Sibling law.** LESSONS **A10** — *"the scaffold is route OUTPUT; the STAPLES are the design"* (autoscaffold
ratcheted helices outward because it read its own prior output as the face to extend from; the fix was to
normalise against **staple spans**, the one thing it cannot touch). Same principle from the other direction:
staples are the fixed point everything else is derived from. If a rule needs an anchor, anchor it to the staples.

See [[feedback_crossover_no_reasoning]] (same family: stop reasoning, apply the mechanical rule),
[[REFERENCE_CROSSOVER_AUTOBREAK]], [[REFERENCE_DNA_TOPOLOGY]]. Worked example: `workspace/teeth.nadoc`.
Open items this law surfaced: ISSUE-17 (`polymer_router` synthesizes staples), ISSUE-18 (scaffold router can
nick/ligate a staple) — both in `issues_ledger.md`.
