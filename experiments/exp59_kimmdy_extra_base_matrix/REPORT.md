# exp59 report — extra-base KIMMDY matrix

> This is the original canonical-geometry-gated sensitivity analysis. `REPORT_UNGATED.md` is the primary analysis after review established that the gates reject deliberately single-stranded and visually intact 2hb conformations.

## Inventory

The scan found **673 DCD files** (1.431 TiB): 119 local (9.90 GiB) and 554 on Archive (1.421 TiB). There are 488 managed NAMD jobs, 54 extra-base-relevant job records, and 20 production jobs with at least two frames, a PSF, an exact design mapping, and one or more reciprocal extra-T pairs.

The legacy `Archive/NAMD/CPD_1xT` (23 DCDs, 54.16 GiB) and `CPD_2xT` (16 DCDs, 317.17 GiB) replicas are inventoried but excluded from the primary matrix because no NADOC design snapshot or audited mapping from topology residues to crossover inserts survives. Restrained, SMD/umbrella, vacuum/probe, and incomplete trajectories are likewise audit-only.

### Managed production matrix

| size | inserts per reciprocal side | production jobs | analyzable jobs | stored production frames |
|---|---:|---:|---:|---:|
| 2hb | 0-1 | 5 | 0 | 154,200 |
| 2hb | 1-1 | 6 | 4 | 61,429 |
| 2hb | 1-2 | 4 | 4 | 250,000 |
| 2hb | 2-2 | 4 | 4 | 102,000 |
| larger_origami | 0-0 | 4 | 0 | 1,172 |
| larger_origami | 1-1 | 4 | 4 | 11,338 |
| larger_origami | 2-2 | 4 | 4 | 22,547 |

KIMMDY was run on every eligible production job above (7,654 frames total, with at most 500 frames spread across each job). The frame cap represents every trajectory while keeping the multi-terabyte scan tractable; it is not an every-stored-frame calculation.

## Claim being tested

Gerling, Kube, Kick, and Dietz ([Science Advances 2018](https://doi.org/10.1126/sciadv.aau1157)) demonstrated that placing unpaired thymidines at DNA-origami crossover positions can create UV-induced covalent bonds; their experiments used 310 nm irradiation. The paper establishes feasibility, but it does not report a controlled comparison of one versus two inserts on each reciprocal strand and does not establish that two total thymidines (the 1+1 arrangement here) are globally optimal. Consequently, this analysis tests the later *optimality extrapolation*, not whether the published crosslinking experiment occurred.

## Lineage-level KIMMDY comparison

The metric is the per-frame maximum corrected periodic KIMMDY propensity among all extra-T pair combinations at one reciprocal crossover. Frames must retain at least 90% global duplex pairing, both flanking C1′ pairs at 8–13 Å, and both backbone links for each insert at 1.2–2.2 Å. `Reactive %` is the fraction of structurally valid frames meeting both the midpoint-distance and dihedral criteria. CIs bootstrap independent production lineages; they are descriptive when lineage counts are small.

| size | reciprocal inserts per side | lineages | structurally valid % | mean best k (95% CI) | reactive % (95% CI) |
|---|---:|---:|---:|---:|---:|
| 2hb | 1-1 | 2 | 64.1 | 0.0367 (0.0104–0.0629) | 0.000 (0.000–0.000) |
| 2hb | 1-2 | 4 | 35.5 | 0.0627 (0.0437–0.0851) | 1.043 (0.000–2.679) |
| 2hb | 2-2 | 4 | 45.4 | 0.1201 (0.0444–0.1958) | 4.440 (0.100–12.550) |
| larger_origami | 1-1 | 4 | 97.1 | 0.0243 (0.0171–0.0370) | 0.029 (0.000–0.087) |
| larger_origami | 2-2 | 4 | 96.9 | 0.0795 (0.0580–0.1038) | 1.655 (0.034–3.825) |

## Interpretation

In the controlled 2hb runs, the Dietz-style 1+1 arrangement has mean best propensity 0.0367, versus 0.1201 for 2+2 (0.31×; equivalently 2+2 is 3.28× higher). Reactive-corner occupancy is 0.000% versus 4.440%. These values are retained only to quantify sensitivity to the canonical-geometry gate; low gate passage is not evidence that the structures are unstable.
Across all mapped 1+1 runs, mean best propensity is 0.0367 in 2hb and 0.0243 in larger origami (-33.9%). The larger-origami mean combines one long 24hb lineage with three 0.5 ns 6hbx100 replicas, so this is not strong evidence of a size effect.
For 2+2, the corresponding 2hb versus larger-origami values are 0.1201 and 0.0795 (-33.8%). Both size comparisons point in the same direction but remain confounded by trajectory length, construct geometry, and small lineage counts.
Restricting the comparison to the two mature 24hb lineages gives the same qualitative result: 1+1 has mean best propensity 0.0435 and reactive occupancy 0.117%, whereas 2+2 has 0.0690 and 1.474%. This removes the short 6hb runs but still leaves only one long lineage per condition.

## Position and orientation context

The independent exp55 orientation analysis reinforces the context dependence seen here. The two long 2hb 1+1 lineages occupied markedly different coupled basins: their reciprocal face-normal separations were 72.3 ± 16.8° and 146.7 ± 27.4°. In 24hb, individual sites were usually concentrated (median resultant lengths 0.876 and 0.883 for the two reciprocal sides), yet different crossovers selected different basins; the traversal-aligned population means were separated by 61.7°. Thus a minimal 2hb system is mechanistically useful but not a reliable stand-in for the full distribution of origami environments. See [`../exp55_2hb_extra_base_orientation/REPORT.md`](../exp55_2hb_extra_base_orientation/REPORT.md).

The canonical-geometry gate-pass difference is large: the mapped 2hb groups pass only 35.5–64.1% of frames, compared with 96.9–97.1% in larger origami. Because the 2hb designs contain deliberately single-stranded bases and exhibit expected terminal fraying, this difference must not be interpreted as structural instability. The ungated analysis is therefore primary.

## Scientific conclusion

This gated sensitivity analysis is not used for the primary scientific conclusion. Refer to `REPORT_UNGATED.md`, which includes every finite sampled frame and avoids treating expected single-stranded behavior or terminal fraying as a disqualifying event.

## Matrix gaps

The 2hb set covers 0+1 (both polarities), 1+1, 1+2 (both polarities), and 2+2. It lacks unrestrained 0+0 and 0+2/2+0 production controls. The larger-origami set contains only symmetric 1+1 and 2+2 designs; asymmetric controls are absent. Only one long 24hb production lineage exists for each symmetric condition, while the 6hb/6hbx100 data are short bring-up runs.


Asymmetric 0+1 and 1+0 constructs contain only one crossover-insert thymine and therefore have zero possible interstrand extra-T pair by definition. They are structural controls, not zero-valued KIMMDY observations.

A favorable classical-MD geometry is necessary but not sufficient for a 305 nm CPD. The score is dimensionless, the reactive corner is a screening threshold, and neither supplies absorption, excited-state dynamics, quantum yield, or an absolute crosslink probability. The [KIMMDY method paper](https://doi.org/10.1038/s41467-026-71955-2) likewise describes its distance/angle photodimerization model as heuristic and cautions that heuristic models have limited predictive power. Accordingly, these simulations can challenge a universal geometric-optimality claim but cannot by themselves refute the reported experimental crosslinking result.

## Outputs

- `inventory.json`: every DCD plus managed-job eligibility and matrix coverage
- `crossover_summary.csv`: one row per reciprocal crossover per production job
- `lineage_summary.csv`: independent-lineage statistical units
- `results/jobs/<job_id>/`: KIMMDY summary, pair table, and sampled time series
