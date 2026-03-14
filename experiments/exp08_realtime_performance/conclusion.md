# Exp08 — Real-Time Autostaple Performance: PASS

## Result: PASS — all designs well under 100ms real-time threshold

| Design | Helices | bp | Plan | Apply | Nick | Total | RT? |
|---|---|---|---|---|---|---|---|
| 2HX  42bp  |  2 |  42 | <0.1ms |  0.1ms |  0.0ms |  0.1ms | ✓ |
| 2HX 126bp  |  2 | 126 | <0.1ms |  0.2ms |  0.2ms |  0.3ms | ✓ |
| 18HB  42bp | 18 |  42 |  0.2ms |  2.9ms |  1.1ms |  4.0ms | ✓ |
| 18HB 126bp | 18 | 126 |  0.3ms |  3.9ms |  3.5ms |  7.4ms | ✓ |
| 18HB 252bp | 18 | 252 |  0.8ms |  5.3ms | 10.5ms | 15.8ms | ✓ |
| 72HB  42bp | 72 |  42 |  1.6ms | 19.9ms |  6.7ms | 26.6ms | ✓ |
| 72HB 126bp | 72 | 126 |  2.6ms | 25.4ms | 28.1ms | 53.4ms | ✓ |

## Key findings

**18HB at any typical length: 4–16ms** — 6–25× faster than the 100ms real-time threshold.
Real-time autostaple-on-edit is fully feasible.

**72HB 126bp: 53ms** — fast enough for real-time feel even at 4× the standard 18HB layout.

**Dominant bottleneck shifts with design size:**
- Small designs (<18HB 84bp): `apply` (crossover placement) dominates
- Larger designs: `nick` placement dominates (O(N_strands × H) strand walk)
- `plan` computation is always fast (<3ms) thanks to `valid_crossover_positions` cache

**The crossover apply stage (`make_autostaple`) is O(N_pairs × calls_to_make_staple_crossover)**
where each call is O(N_strands × domains). This is the hardest to parallelize since each call
mutates the design. For the immediate near-term it's fast enough.

## Actionable conclusions

1. **Trigger autostaple on every design edit** — debounced at ~50ms → total pipeline ≤ 70ms.
2. **Cache `valid_crossover_positions`** per helix pair (already done) — do NOT recompute on
   strand-only edits (crossovers, nicks). Recompute only on extrusion/helix adds.
3. For designs >72HB or >252bp, consider computing the plan in a background worker and
   applying incrementally. Not needed for current 18HB workflows.
4. **Real-time autostaple architecture**: debounce on design change event → run full pipeline
   (plan + apply + nick) → if same plan as previous, skip apply. Cache last plan for comparison.
