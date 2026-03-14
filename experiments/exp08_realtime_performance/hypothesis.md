# Exp08 — Real-Time Autostaple Performance

## Hypothesis

The autostaple pipeline (plan → apply → nick) must complete in <100 ms for a design
to feel "real-time" during user editing. For NADOC's 18HB at 42–126 bp, this should
be achievable. For larger designs (72+ helices × 252 bp), we may need caching or
incremental updates.

Specific targets (via FastAPI endpoint timing):
- 18HB 42 bp:  <20 ms  (full pipeline: plan + apply + nick)
- 18HB 126 bp: <50 ms
- 18HB 252 bp: <100 ms
- 72HB 126 bp: <200 ms (stretch goal; real-time threshold for larger designs)

Bottleneck hypothesis: `make_staple_crossover` is called once per planned crossover
and each call does O(N_strands × domains) work. For 18 helices × 21 crossovers × 42bp,
the cumulative domain-traversal cost may dominate.

## Metric

Time (wall clock, μs) for each stage independently:
1. `compute_autostaple_plan()` — candidate collection + greedy sort
2. `make_autostaple()` minus plan — crossover application loop
3. Nick placement (future)

Report at design sizes: 2×42, 18×42, 18×126, 18×252, 72×126 bp.

## Expected figure

Bar chart: time per stage vs. design size. Each bar split into plan / apply / nick.
Horizontal line at 100 ms (real-time threshold).

## Conclusion goal

Identify the bottleneck stage and decide:
- If plan is slow: cache valid_crossover_positions per helix-pair (already done via _cache)
- If apply is slow: batch strand edits instead of one-at-a-time `make_staple_crossover` calls
- If 100 ms threshold not met for 18HB: must pre-compute plan on first design load,
  then incrementally update on strand edits only
