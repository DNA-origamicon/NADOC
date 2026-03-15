# Exp06 — Scaffold-Staple Crossover Exclusion Zone

## Hypothesis

The current `compute_autostaple_plan()` filters positions WHERE scaffold strands exist
(based on `scaffold_positions` set), but does NOT filter positions within **5 bp** of a
scaffold crossover on the same helix pair. The canonical caDNAno rule (from the paper) is:

> "Exclude staple crossover positions within 5 bp of a scaffold crossover between
>  the same two helices."

This is physically necessary to avoid over-constraining the local backbone geometry
(too many mechanical contacts between the same two helix pair within a short distance).

Hypothesis: some staple crossovers placed by autostaple will land within 5 bp of scaffold
crossovers on the same pair, violating the canonical rule.

## Metric

For each helix pair in the 18HB design:
1. Find all scaffold crossover positions between the pair (bp positions where scaffold
   transitions from helix A to helix B or vice versa).
2. Find all staple crossover positions placed by autostaple on the same pair.
3. Compute the minimum gap between any scaffold crossover and any staple crossover on the pair.
4. Report pairs where min_gap < 5 bp.

## Expected figure

Table showing helix pairs with:
- scaffold_xover_bp: [list of bp where scaffold crosses between this pair]
- staple_xover_bp: [list of bp placed by autostaple]
- min_gap: minimum gap (bp)
- violation: True if min_gap < 5

## Conclusion goal

If violations exist, determine the fix: add an exclusion-zone filter to
`compute_autostaple_plan()` that skips candidates within 5 bp of any scaffold
crossover on the same pair. Measure whether this reduces crossover count significantly.
