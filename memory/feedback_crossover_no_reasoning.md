---
name: Crossover placement — trust simple rules, no geometric reasoning
description: Any attempt to reason about crossover geometry or topology produces wrong results; mechanical rule application is correct.
type: feedback
---

Trust simple, mechanical rules for crossover placement. Do not reason about geometry, topology, directionality, or polarity.

**Why:** Every time geometric or topological reasoning was applied to crossover placement — figuring out which end is 5' vs 3', computing which bp to nick based on strand direction, swapping half_a/half_b based on bow direction — the result was wrong. The correct solution was:
1. Nick both helices at the N|N+1 boundary encoded in the sprite (lower of pair: 6|7, 13|14, 20|21)
2. Register the crossover record using the sprite's bp directly — no adjustment, no direction math
3. Let the backend store the record without touching strands

The old `_splice_strands_for_crossover` + `_split_domain` code and the `add_crossover` route are marked `# TODO: DELETE` as examples of what goes wrong when geometry is reasoned about.

**How to apply:** When crossover, nick, or strand-join code produces incorrect results, the fix is almost certainly to remove reasoning and apply the rule more mechanically, not to add more logic. If something seems wrong about crossover positioning, ask the user first — do not attempt a geometric fix.
