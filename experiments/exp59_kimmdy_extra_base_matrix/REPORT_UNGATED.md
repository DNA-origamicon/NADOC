# exp59 report — ungated extra-base KIMMDY matrix

## Primary analysis decision

All finite sampled KIMMDY frames are included. No global duplex-pairing, local flanking-C1′, or insert-backbone gate is applied. Those checks systematically reject expected conformations in these designs: deliberately single-stranded bases and terminal fraying in a small 2hb construct are not evidence that the modeled crossover or whole structure is unusable. The former gated output is retained in `REPORT.md` only as a sensitivity analysis.

The analysis contains 177,039 crossover-frame observations from the same 20 eligible production jobs and 18 independent lineages. The KIMMDY calculation itself is unchanged: only reciprocal designed extra-thymidine pairs are evaluated, and the per-frame statistic is the maximum corrected periodic propensity among pair combinations at a crossover.

## Ungated lineage-level comparison

| size | inserts per reciprocal side | lineages | frames included % | mean best k (95% CI) | reactive % (95% CI) |
|---|---:|---:|---:|---:|---:|
| 2hb | 1-1 | 2 | 100.0 | 0.0367 (0.0100–0.0634) | 0.000 (0.000–0.000) |
| 2hb | 1-2 | 4 | 100.0 | 0.0501 (0.0366–0.0637) | 1.300 (0.100–3.050) |
| 2hb | 2-2 | 4 | 100.0 | 0.1020 (0.0388–0.2176) | 4.350 (0.100–12.200) |
| larger_origami | 1-1 | 4 | 100.0 | 0.0246 (0.0172–0.0378) | 0.064 (0.000–0.192) |
| larger_origami | 2-2 | 4 | 100.0 | 0.0795 (0.0580–0.1049) | 1.586 (0.034–3.647) |

## Change caused by removing the gates

| size | inserts/side | gated k | ungated k | k change | gated reactive % | ungated reactive % |
|---|---:|---:|---:|---:|---:|---:|
| 2hb | 1-1 | 0.0367 | 0.0367 | +0.1% | 0.000 | 0.000 |
| 2hb | 1-2 | 0.0627 | 0.0501 | -20.0% | 1.043 | 1.300 |
| 2hb | 2-2 | 0.1201 | 0.1020 | -15.0% | 4.440 | 4.350 |
| larger_origami | 1-1 | 0.0243 | 0.0246 | +1.3% | 0.029 | 0.064 |
| larger_origami | 2-2 | 0.0795 | 0.0795 | -0.0% | 1.655 | 1.586 |

## Interpretation

In 2hb, removing the gates changes the absolute values and yields a monotonic arrangement ordering: 1+1 = 0.0367, 1+2 = 0.0501, and 2+2 = 0.1020. The 2+2 best-pair score is 2.78× the 1+1 score; reactive occupancy is 0.000% versus 4.350%.
The apparent size effect is now arrangement-dependent: larger-origami 1+1 is -33.1% relative to 2hb 1+1, while larger-origami 2+2 is -22.1% relative to 2hb 2+2. This is more informative than the gate-pass contrast, but it remains confounded by construct geometry, trajectory length, and limited independent long-run replication.
In the mature 24hb lineages alone, 1+1 gives k = 0.0446 and 0.257% reactive occupancy; 2+2 gives k = 0.0666 and 1.438%. There is still only one long lineage per condition.

## Revised conclusion

Removing the inappropriate structural filters does not rescue a unique 1+1 optimum. The qualitative result remains that 2+2 offers more frequent favorable extra-T geometry than 1+1 in both 2hb and mature 24hb. The magnitude changes, however, so the gated percentages must not be described as structural survival or stability.

This remains evidence about the probability that *any* reciprocal extra-T pairing reaches favorable ground-state geometry. Because 2+2 supplies four pair combinations while 1+1 supplies one, it does not establish higher intrinsic reactivity per thymine pair or higher experimental quantum yield. Small lineage counts and the absence of a balanced large-origami arrangement matrix still preclude a definitive optimal-design claim.

## Outputs

- `crossover_summary_ungated.csv`: ungated job/crossover observations
- `lineage_summary_ungated.csv`: ungated independent-lineage units
- `REPORT.md`: former gated analysis, retained as sensitivity only
- `inventory.json` and `results/jobs/`: unchanged inventory and raw KIMMDY outputs
