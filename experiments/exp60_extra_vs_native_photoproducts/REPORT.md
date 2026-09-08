# exp60 report — extra versus native interstrand TT opportunity

## Question and scope

This analysis asks whether added crossover thymines supply the interstrand photoproduct opportunity themselves, alter nearby native-thymidine opportunity, or are unnecessary because native–native pairs elsewhere already account for the signal. It uses all finite sampled frames with no structural gates.

The observable is KIMMDY TT ground-state geometric propensity, not formed-product count or mechanical stability. Therefore the result decomposes *potential interstrand TT photoproduct opportunity*; it cannot assign a measured stability increase without experimental CPD yields and post-irradiation mechanics for the same constructs. Cytosine-containing CPDs are outside the currently implemented TT model.

The 24hb 0×T, 1×T, and 2×T designs have identical native topology after insert annotations are removed. The 6hbx100 0×T and 1×T designs are likewise matched; no matched 6hbx100 2×T production trajectory exists. Native sites within ±2 bp of an insert-bearing crossover endpoint are classified as nearby in every member of a family, including its 0×T control.

## Aggregate propensity partition

`Σk` sums each screened interstrand pair's ensemble-mean corrected periodic propensity. Intended pairs that never enter the common 6 Å discovery radius remain in the raw audit but are excluded from these sums, ensuring that extra and native pairs use the same inclusion rule. Shares are descriptive opportunity mass, not reaction probabilities.

| family | arrangement | native–native Σk | extra-involving Σk | extra share | native reactive events/100 frames | extra reactive events/100 frames |
|---|---:|---:|---:|---:|---:|---:|
| 24hb | 0-0 | 23.3534 | 0.0000 | 0.0% | 1873.534 | 0.000 |
| 24hb | 1-1 | 24.6257 | 16.2847 | 39.8% | 1262.400 | 170.400 |
| 24hb | 2-2 | 24.4221 | 24.2369 | 49.8% | 1305.000 | 350.800 |
| 6hbx100 | 0-0 | 4.4032 | 0.0000 | 0.0% | 653.083 | 0.000 |
| 6hbx100 | 1-1 | 3.6006 | 0.1714 | 4.5% | 649.359 | 0.000 |

## Increment relative to the no-insert control

The identity `total change = direct extra contribution + change in native–native contribution` is used below.

| family | arrangement | total Σk change | direct extra Σk | native–native Σk change |
|---|---:|---:|---:|---:|
| 24hb | 1-1 | +17.5570 | 16.2847 | +1.2723 |
| 24hb | 2-2 | +25.3056 | 24.2369 | +1.0687 |
| 6hbx100 | 1-1 | -0.6312 | 0.1714 | -0.8026 |

## Main findings

For 24hb 1+1, total screened opportunity rises by 17.5570 Σk above the 0×T control. Pairs containing an extra T contribute 16.2847 Σk, or 92.8% of that increase; native–native pairs contribute only the remaining 7.2%. For 2+2, extra-involving pairs account for 95.8% of the increase and the native–native change accounts for 4.2%.

The extra-T contribution is not limited to the intended reciprocal insert weld. In 24hb 1+1, designed extra–extra pairs contribute 2.5250 Σk (15.5% of extra-involving opportunity), while extra–native pairs contribute 13.7598 (84.5%). In 2+2 the split is 42.2% designed extra–extra and 57.6% extra–native (with the remainder from other extra–extra contacts). Thus inserted bases add many alternative interstrand contacts with native thymidines nearby.

The matched 6hbx100 1+1 ensemble does not show an aggregate gain: total Σk is 3.7719, compared with 4.4032 in 0×T. The direct extra contribution (0.1714) is offset by a -0.8026 change in native–native opportunity, and no extra-involving pair reaches the reactive corner in the three short 0.5 ns replicas. This family cannot establish a long-time effect because matched 1+1 production is short and matched 2+2 production is absent.

## Strict reactive-corner result

The stricter binary criterion gives a different but complementary picture. The 24hb 0×T control has 18.74 native reactive pair-events per frame. The 1+1 trajectory has 14.33 total events per frame, of which 11.9% involve an extra T; 2+2 has 16.56 events per frame, of which 21.2% involve an extra T. Every 24hb condition already has at least one native reactive candidate in essentially every sampled frame.

Thus the inserts do not raise the total strict reactive-event count above the no-insert trajectory. They create additional crossover-associated choices and shift some opportunity toward extra-involving sites. Any stability advantage would therefore have to depend on *where and which strands* are covalently linked, not simply on whether the structure contains any potentially reactive TT geometry.

## Nearby-native test

| family | arrangement | near-insert native Σk | far native Σk |
|---|---:|---:|---:|
| 24hb | 0-0 | 17.5508 | 5.8026 |
| 24hb | 1-1 | 17.2748 | 7.3509 |
| 24hb | 2-2 | 17.6508 | 6.7713 |
| 6hbx100 | 0-0 | 3.2103 | 1.1929 |
| 6hbx100 | 1-1 | 2.8355 | 0.7651 |

## Interpretation

There is no detectable enhancement of native–native propensity immediately around the 24hb insert sites: the nearby term changes by -1.6% in 1+1 and +0.6% in 2+2. In 6hbx100 it changes by -11.7%. The data therefore favor a direct-extra mechanism over the hypothesis that inserts stabilize the structure primarily by making neighboring native–native TT pairs more photoreactive.

Native–native pairs still supply a large absolute background: 60.2% of total 24hb 1+1 propensity and 50.2% of 2+2 propensity. But that background is already present in 0×T and explains only 7.2% and 4.2%, respectively, of the *increase* in aggregate propensity. Moreover, a native CPD elsewhere need not topologically bridge a crossover or reproduce the mechanical effect of a deliberately located weld.

Accordingly, the continuous Σk metric says extra bases account for nearly all of its 24hb increment, while the strict-corner metric shows that native bases already provide abundant background opportunities. These are not contradictory: the inserts add many moderate-propensity and strategically located candidates without increasing the global count of strict reactive events. A substantial portion of the insert-associated signal comes from extra–native alternatives rather than only the nominal extra–extra pair.

The simulations therefore do not support the claim that improved mechanical stability can be explained merely by an increased number of native-site photoproduct opportunities. They also cannot exclude native products as contributors. Quantifying stability causally requires irradiated 0×T/1×T/2×T product yields, product-site mapping, and a topology-aware mechanical analysis or simulations with the candidate CPD bonds actually installed. Each 24hb condition currently has only one long lineage.

Pair discovery retained every interstrand TT pair whose C5–C6 midpoint separation reached 6 Å in at least one sampled frame; no candidate list was truncated. KIMMDY also exported forced intended-weld records outside that radius, but they are marked `screen_hit=false` and excluded from the aggregate comparison. Pair identities and classifications are exported for audit.

## Outputs

- `pair_summary.csv`: 2,228 job-specific pair records
- `lineage_class_summary.csv`: independent-lineage class aggregates
- `group_summary.csv`: family/arrangement comparisons
- `results/jobs/<job_id>/`: all-T KIMMDY reports and time series
