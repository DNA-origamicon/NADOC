# Exp05 — Staple Length Distribution

## Hypothesis

After `make_autostaple()` with default parameters (min_pair_spacing=21, min_helix_spacing=7),
the resulting staple strand length distribution will contain strands **outside the canonical
18–50 nt window**.

Specifically:
- For **42 bp** helices: ~21 bp crossover period → single crossover per pair → zigzag strands
  likely 20–30 nt (marginal, some may pass).
- For **126 bp** helices: 6 crossover positions per pair → zigzag strands spanning 2–4 helix
  halves per strand → many strands will be **>50 nt** (too long for clean synthesis).

The issue is that `make_autostaple` only places crossovers (topological reconnection).
It does NOT add nicks to break the resulting long zigzag strands. This is Stage 1 of the
two-stage pipeline described in the literature; Stage 2 (nick placement) is missing.

## Metric

For each helix length tested (42, 84, 126 bp):
- Measure: min, max, mean, std of staple strand nt counts after autostaple
- Count: strands below 18 nt, above 50 nt, in-range 18–50 nt
- Plot: histogram of strand lengths vs. [18, 50] window

## Expected figure

Three histograms (42/84/126 bp), each showing a distribution that shifts right (longer strands)
as helix length increases, with the 50 nt cutoff being violated increasingly.

## Conclusion goal

Quantify the gap, then design the nick placement algorithm in exp07.
