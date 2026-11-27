# KIMMDY CPD-pair scoring: 2hb_1xT, created 2026-11-11 09:56 MST

Applied KIMMDY's published geometric scoring expression through NADOC's existing PSF/DCD adapter, using all **18 thymines, 153 unordered pairs and 10,000 frames (200 ns)**. Both same-strand and cross-strand candidates are included, without a proximity prefilter, frame cap, or structural-pairing gate. This is pair scoring on the saved unwelded trajectory, not a KIMMDY reactive-MD run or stochastic reaction selection.

The original upstream score is the primary ranking. The separately labeled periodic-angle correction is also retained. The full score matrix was independently evaluated using the pure scalar function extracted from official upstream commit `bc86e974da16d1b2a26cd6baa64399fd20b40f8c`: all **1,530,000 evaluations agree**. The four parameters also match its configuration defaults. Independent MDAnalysis geometry checks passed, and the intended-pair distances agree with the preceding eight-isomer analysis.

[Ranked pair table](pairs.tsv) · [Plots](pair_scores.png) · [Full summary](summary.json) · [Verification and 50 ns blocks](verification.json)

| Rank | Pair | Relationship | Mean upstream score | Mean periodic score | Minimum midpoint distance (Å) | Close/aligned frames |
|---|---|---|---:|---:|---:|---:|
| 1 | D000:4~D002:46 | cross-strand | 0.14860 | 0.14860 | 4.63 | 0 |
| 2 | D000:12~D002:5 | cross-strand | 0.14499 | 0.14499 | 5.10 | 0 |
| 3 | D001:2~D002:23 | cross-strand | 0.08631 | 0.08631 | 5.53 | 0 |
| 4 | D000:9~D001:15 | cross-strand | 0.07983 | 0.07983 | 4.67 | 0 |
| 5 | D000:4~D002:48 | cross-strand | 0.07481 | 0.07481 | 7.84 | 0 |
| 6 | D001:4~D002:23 | cross-strand | 0.06929 | 0.06929 | 10.19 | 0 |
| 7 | D001:28~D002:30 | cross-strand | 0.06844 | 0.06844 | 3.99 | 1 |
| 8 | D001:26~D001:28 | same strand | 0.06758 | 0.06758 | 6.89 | 0 |
| 9 | D001:11~D001:13 | same strand | 0.05460 | 0.05460 | 6.83 | 0 |
| 10 | D001:17~D001:19 | same strand | 0.05262 | 0.05262 | 6.80 | 0 |

The intended inserted-T pair **D000:8~D001:15** ranks **20/153** by mean upstream score: mean **0.016220**, maximum **0.198113**, periodic mean **0.016229**, minimum midpoint separation **6.204 Å**, **0 close/aligned frames**. Its score is ≥0.1 in 1.79% of frames. That percentage is a score-threshold statistic, not a reaction probability.

The highest-scoring cross-strand pair is **D000:4~D002:46** (overall rank 1); its mean upstream score is 0.148603, minimum midpoint distance 4.631 Å, and close/aligned count 0.

Across all pairs, **1 pairs** have any close/aligned frames, totaling **1 pair-frame observations** in **1 distinct saved frames**. These are correlated observations, not independent reactions. The close/aligned diagnostic uses NADOC's existing `midpoint distance <4.5 Å` and circular angular offset from 16.74365° `<45°`; it is not the preceding eight-isomer classifier, and is not asserted to be the paper's quantum-yield calibration threshold.

## What this score means

The upstream function is `exp[-2.017017 |d_nm−0.157177| −0.03003003 |eta_deg−16.743652|]`. It has no hard distance cutoff, so even well-separated bases have a nonzero score. A high rank or a score above 0.1 alone does not demonstrate two feasible forming C–C bonds. Distances, close/aligned occupancy and stereochemical feasibility must be read alongside the score.

The earlier screen requires both proposed bonds to lie between 2.5 and 4 Å, plus face and torsional compatibility with a specified CPD stereoisomer. Its zero encounters therefore need not imply zero KIMMDY scores. This KIMMDY expression does not supply an eight-isomer branching model; it cannot settle cis-anti-I versus cis-syn-II from pair rankings. The KIMMDY study specifically notes that anti and 6–4 products are outside the implemented plugin's scope. [Hartmann et al., 2026](https://doi.org/10.1038/s41467-026-71955-2)

The model/source is pinned at [the official dimerization plugin](https://github.com/graeter-group/kimmdy-dimerization/tree/bc86e974da16d1b2a26cd6baa64399fd20b40f8c). NADOC supplies segment-safe atom mapping, CHARMM thymine names and local periodic imaging for the NAMD trajectory; no topology mutation, KMC selection, new MD or product formation was run. No absolute yield or kinetic rate is inferred.

## Reproduce

From the repository root, run `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261112/kimmdy/run.py`, then the same interpreter on `assess.py`. The exact CLI argument list is retained in `command.json`. The upstream source and schema are pinned and retained beside these scripts. Original molecular structures and trajectories were unchanged.

<!-- close-pair follow-up -->
## The one close/aligned frame

**D001:28~D002:30 at 90.04 ns** (frame 4501, zero-based) has midpoint separation 4.403 Å and dihedral 49.48°. It is a native/native staple–scaffold pair on the same helix at bp indices 26 and 27, not the intended crossover-insert pair. Its upstream score is 0.2114. The closest midpoint observed for this pair at any time is 3.985 Å, but that minimum-distance frame is not the same as this jointly close/aligned frame.

In the jointly qualifying frame, the two proposed syn C–C distances are **3.82 and 5.06 Å**. It fails the earlier 4 Å two-bond requirement; no channel passes the full eight-isomer screen. This single saved-frame hit is a possible pair to monitor, not a demonstrated formation event or robust product prediction. [Detailed descriptors](close_pair_stereochemistry.json)

The strongest extra/native competitor by mean upstream score is D000:9–D001:15 (rank 4, mean 0.07983, minimum midpoint 4.675 Å); it has no close/aligned frames. The two highest-scoring pairs are native/native staggered staple–scaffold pairs at neighboring bp indices within their respective helices. Their ranks should not be interpreted as eight-isomer yield rankings.

Run `check_close_pair.py` after `assess.py` to reproduce this additional comparison.
