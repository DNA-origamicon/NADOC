---
name: feedback-gpu-value-is-two-axes
description: "Judge rented GPUs on $/ns AND ns/day — a cheap, slow card is not a good deal. Wall-clock is a constraint, not a tiebreak."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9ceadb1d-c9a4-4568-b4c2-cb7412b69185
---

When benchmarking or choosing rented GPUs, **report and rank on BOTH `$/ns` and `ns/day`.**
A card with excellent `$/ns` but low `ns/day` is **not useful**.

**Why:** cost-efficiency alone ranks a cheap crawling card top. An RTX 4000 Ada at $0.26/hr
doing ~4 ns/day has fine `$/ns` — and a 5 ns production on it takes **30 hours**. The run
has to *finish*, inside a window a human will actually wait through. Wall-clock is a
first-class constraint, not a tiebreak.

**How to apply:** state a target (e.g. 5 ns) and a window (e.g. 12 h, an overnight) →
derive a **minimum usable ns/day** (5 × 24 / 12 = 10 ns/day). Cards below it are listed as
**TOO SLOW** no matter how good their `$/ns` looks. Among the cards that clear the bar,
*then* take the cheapest `$/ns`. Always print `ms/step`, `ns/day`, `$/ns`, and
`hours-for-target` together — never `$/ns` on its own.

Implemented in `experiments/exp43_runpod_bench/bench_gpus.py` (`TARGET_NS`, `MAX_WALL_H`,
`MIN_USEFUL_NS_DAY`). Related: [[runpod-submission]], [[REFERENCE_RUNPOD_RUNBOOK]].
