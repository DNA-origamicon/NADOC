# Exp05 — Staple Length Distribution: FAIL (as hypothesised)

## Result: FAIL — confirms missing Stage 2

| helix length | n strands | min | max | mean | <18 nt | >50 nt | in-range |
|---|---|---|---|---|---|---|---|
| 42 bp | 20 | 8 | 132 | 38 | 7 | 5 | 40% |
| 84 bp | 21 | 8 | 168 | 72 | 7 | 13 | 5% |
| 126 bp | 21 | 8 | 252 | 108 | 7 | 13 | 5% |
| 252 bp | 21 | 8 | 504 | 216 | 7 | 13 | 5% |

## Root cause: two bugs

### Bug 1: `min_end_margin=3` creates tiny stub strands
A crossover at bp=4 (FORWARD helix) creates an outer strand of 2×(4+1)=10 nt — far below the
18 nt canonical minimum. The 7 strands < 18 nt all come from crossovers placed at bp 3–5.

**Fix**: increase `min_end_margin` from 3 → **9**. At bp=9, outer stub = 2×10=20 nt ✓.

### Bug 2: No nick placement (Stage 2 missing)
`make_autostaple()` only places crossovers (Stage 1). The resulting zigzag strands span
2–4+ helices (22–504 nt). Stage 2 — breaking these into 18–50 nt fragments — is absent.

**Fix**: add `make_nicks_for_autostaple(design, target_length=30, min_length=18)`.
See exp07 for the algorithm and validation.

## Actionable conclusion

1. Change `min_end_margin` default from 3 to 9 in `compute_autostaple_plan` and `make_autostaple`.
2. Implement and integrate nick placement (exp07).
3. The `/design/autostaple` endpoint should run BOTH stages.
