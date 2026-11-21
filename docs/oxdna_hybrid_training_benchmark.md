# Hybrid oxDNA: increased training benchmark (2026-11-21)

**Closed research attempt; not implemented as a production feature.** Raw data
and isolated builds were deleted at the user's request on 2026-11-21. References
below to their retention describe the experiment at completion, before cleanup.
Preserved [metrics and plot](benchmarks/oxdna_hybrid/training-duration-20261121/)
support the reported summaries; rerunning raw-data analysis requires new runs.
See [research status and handoff](oxdna_equilibrium_tm_research.md).

Follow-up to [the hybrid pilot](oxdna_hybrid_benchmark.md). Question: can more
well-tempered metadynamics training improve *fixed-budget* frozen-bias production?

## Protocol

Compare the existing 2M-step training baseline with new 6M and 12M training
campaigns. All use the final v3 native engine, mixed coordinate (70% HB proxy,
30% base-site contact term), contact radius 0.5, four walkers, 70 C, 0.3 M salt,
and the unchanged 8-bp DNA2 export at approximately 12 mM total strand
concentration. Each production replica restarts from the original bound or
separated configuration, discards 200k equilibration steps, and samples 2M steps.
Training frames are excluded from equilibrium estimates. Hill parameters,
training/production seed schedules, inputs and physical settings are unchanged.
CUDA trajectories do not reproduce bit-for-bit even with matching seeds; these
are exploratory single campaigns at each budget, not replicated method rankings.

Measure one-direction passages between q=0 and q>=6, additionally q=0 and q=8,
where q is the number of native base pairs. Count round trips within each replica,
never by combining opposite passages from different replicas. Counts use the
saved 1,000-step cadence. Compare total wall time including training, starting-
state disagreement and correlation-adjusted importance-weighted sample estimates.
The latter are unstable diagnostics in poorly mixed trajectories, not a certified
number of independent equilibrium samples. Aggregated probabilities can conceal
large disagreement between individual replicas.

Training drift is compared over the same final 500k steps for every campaign,
after removing an irrelevant additive energy offset. The full ordered hill
history is replayed and checked against the frozen table. Saved native output
hashes and observed bias energies are checked. Temperature reevaluation uses the
full temperature-dependent DNA2 Hamiltonian and the finite-size heterodimer
correction, as in the pilot.

Raw inputs, manifests, driver snapshot, native output, execution events and
analysis are retained under
`.development-artifacts/oxdna-hybrid/training-duration-20261121/`.
The 2M baseline remains in `contact-refinement/radius_0.5/`; no historical raw
outputs are replaced. No application behavior, wizard defaults, engine symlink,
CPD parameters or authored molecular documents are changed.

## Results

Both new campaigns completed without errors: 89.6M total MD steps across the
four walkers, approximately 21.7 minutes of sampling on the RTX 3080 Ti.
Production itself took about 1.94–1.95 minutes in each campaign; extra cost was
training. The baseline is the existing final-engine 2M campaign.

| Training steps per walker | Total minutes | q=0 crossings | q=0 ↔ q>=6 passages | Passages / total minute | p(bound), bound / separated starts |
|---|---:|---:|---:|---:|---:|
| 2M baseline | 4.11 | 42 | 1 | 0.243 | 1.000 / 0.00583 |
| 6M (3×) | 7.95 | 122 | 5 | 0.629 | 0.310 / 0.0830 |
| 12M (6×) | 13.73 | 43 | 4 | 0.291 | 0.999 / 0.318 |

The 6M trial yielded 2.6× as many q=0 ↔ q>=6 passages per elapsed minute as
baseline; the 12M trial yielded only 1.2×. Counts are too small, and campaigns
too few, to establish a statistically reliable efficiency advantage.

Stricter q=0 ↔ q=8 passage counts were 1, 1 and 2 respectively. **No replica
completed a full q=0 ↔ q=8 round trip at any budget.** The smaller starting-state
gap at 6M (0.227 versus baseline 0.994) conceals considerable replica disagreement:
its individual box binding probabilities were 0.123, 0.043, 1.000 and 0.102.
At 12M the aggregated gap grew again to 0.681. No monotonic convergence trend
was demonstrated.

| Training | Final 500k bias-shape RMS change (kBT) | Correlation-adjusted weighted sample estimate per replica | Replicas with bracketed Tm, 60–80 C |
|---|---:|---:|---:|
| 2M | 0.623 | 0.88–18.50 | 0/4 |
| 6M | 0.267 | 0.51–3.64 | 0/4 |
| 12M | 0.129 | 1.05–6.00 | 0/4 |

Bias-shape drift decreases with training, but a slower-changing bias does not
establish equilibrium production sampling. These effective-sample diagnostics
remain low and are particularly unreliable for trapped trajectories; their
numerical ordering must not be interpreted as a precise efficiency ranking.
No Tm interval, including +/-1 C, is supported.

All-pair audits reproduced the recorded native-pair counts. Non-native
interstrand bonds occurred in 7/315 saved q=0 frames at 6M and 2/67 at 12M.
These biased counts are not equilibrium populations, but do not suggest that
most nominally unpaired frames are actually incorrectly bonded duplexes.

**Interpretation:** additional training improved some excursions and reduced
late bias drift, but training alone did not consistently improve equilibrium
mixing within the fixed 2M production budget. This does not rule out the hybrid;
it rules out claiming that this training increase achieved faster reliable Tm.
A subsequent experiment should test production mixing with a fixed trained bias
and independent repetitions, rather than assume still more training is sufficient.

## Evidence and cleanup

The artifact directory contains `metrics.csv`, `metrics.json`,
`training_comparison.png`/`.pdf`, the exact orchestration and summary scripts,
and both complete native campaigns. Input and engine hashes match baseline;
protocol comparison permits only training length, timeout and destination to
differ. Output hashes, exact hill replay and native bias consistency checks pass.
The comparison figure was visually inspected. All owned workers and private MPS
processes exited; the application engine is unchanged. Approximately 61 MB of
scientific evidence is retained outside the user workspace. No software behavior
changed, so no broad regression suite was rerun. Feature `main.js` LOC delta: 0.
