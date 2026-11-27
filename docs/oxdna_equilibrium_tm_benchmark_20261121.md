# Equilibrium Tm research — 2026-11-21

**The sub-hour ±1°C target was not achieved.** Six fresh CPU campaigns were run;
none supports a calibrated 95% interval of that width. The strongest follow-up
completed in **26.33 minutes**, including fresh training and full-energy/audit
analysis. Its provisional any-interstrand-bond Tm is **70.07°C**, but individual
replicas give **70.08, 66.69, 74.14 and 70.07°C**. A between-replica Student-t
interval alone is 65.40–75.09°C (half-width 4.85°C); long-batch analysis cannot
support a final interval. This is sampling failure, not a ±1°C result.

| Fresh workflow | Timed minutes | Provisional native-pair Tm, °C | Full q=0↔8 round trips | Defensible ±1°C CI |
|---|---:|---:|---:|---|
| Serial training, moves .1/.2, cap 12 | 4.60 | Unbracketed | 0 | No |
| Serial training, moves .5/1, cap 16 | 6.88 | 76.90 | 0 | No |
| Serial training, moves 1/2, cap 16 | 7.02 | Unbracketed | 0 | No |
| Four-walker q-only, moves .5/1, cap 12 | 6.47 | 63.11 | 0 | No |
| Four-walker q+distance pilot | 7.52 | 71.62 | 2 | No |
| Fresh q+distance confirmation, 8M sweeps/replica | 26.33 | 69.85 | 20 (17 at 10k cadence) | No |

The first five times include measured driver and temperature-analysis costs;
the last also includes all-pair, geometric and binding-definition audits.
Small startup/copy overheads are not separately timed. Total timed scientific
campaign work is about 58.8 minutes, excluding research/development time and
calibration/smoke checks. Method selection is **not** free: the q+distance pilot
plus its independent confirmation consumed about 33.85 timed minutes.

Historical comparators are not fresh trials. The retained GPU hybrid trials
cost 4.11/7.95/13.73 minutes and recorded zero full round trips; their raw data
were previously deleted. A read-only recount of the retained older VMMC
continuation gives 35 full round trips at 10k cadence in 55.10 minutes, **excluding
its prior 569M-sweep bias-learning cost**, with a previously reported provisional
±4.45°C replica interval and unresolved batching. At matched cadence, the new
confirmation's 17 trips/26.33 minutes and historical 35/55.10 minutes have nearly
the same observed traffic per minute; single campaigns cannot establish an
improvement in equilibrium precision.

[Metrics and reproducibility material](benchmarks/equilibrium_tm_20261121/),
[method comparison CSV](benchmarks/equilibrium_tm_20261121/comparison.csv),
[comparison traces](benchmarks/equilibrium_tm_20261121/pairing_traces.png), and
[separate confirmation traces](benchmarks/equilibrium_tm_20261121/confirmation_traces.png).
This remains isolated research: no production feature or CPD validation.

## Confirmation diagnostics and recommendation

Fresh confirmation training took 249.47 s, equilibration 29.66 s, production plus
native interim analysis 1211.01 s, and full-energy/pairing/geometric audits 89.47 s.
There were 8M production sweeps per replica, four replicas and independent seeds.
True-unbound↔native-eight-pair round trips were **6, 3, 7 and 4**; excluding
mispaired q=0 frames does not change these counts at the 1k sampling cadence.
The independently recomputed distance bins match all 32,000 saved production
frames; native q and source energies also match independent reevaluation.

Native-pair Tm values were 69.35/66.68/73.82/70.06°C. Pooled bound-start versus
unbound-start estimates differ by **3.13°C** (71.50 versus 68.37°C). Pooled first
and second halves differ by only 0.58°C, but individual half-run estimates shift
by as much as **5.39°C**. Aggregate stationarity masks replica drift. Weighted
influence autocorrelation factors are about 89–365 saved-frame intervals;
importance-weight ESS at 70°C is 2260–2843, while correlation-based effective
frame counts are only about 22–90. The conservative doubled batch size leaves
only two long batches per replica, insufficient for calibrated resampling.

In the longer run, **761/6755** native-q=0 frames contain non-native interstrand
bonds. These biased frame counts are not equilibrium populations. Including
those bonds changes pooled Tm by +0.227°C, from 69.847 to 70.074°C, and still
leaves a broad replica interval and unresolved batching. The any-interstrand
classification is the more inclusive association definition; the table retains
the native-pair definition for comparison with previous benchmarks. The sampled
mispaired states matter for a future sub-degree ΔTm workflow even though they do
not explain the present multi-degree sampling uncertainty.

**Recommendation:** do not promote the hybrid, larger VMMC proposals, or this
q+distance protocol as a sub-hour ±1°C solution. Four-walker training avoids some
catastrophic short-tuning failures, but the dominant remaining problem is slow,
correlated interconversion through partially paired/zippering states. Distance
biasing alone does not remove it. Keep the new harness as a reproducible research
baseline. The next justified algorithmic test is temperature or Hamiltonian
replica exchange with full cross-Hamiltonian energies, evaluated by configuration
round trips and independent campaign agreement; merely increasing training or
reporting more q=0↔1 contacts is not supported by these results. For eventual CPD
ΔTm, prioritize testing a bound/unbound free-energy cycle after validating lesion
parameters, rather than assuming independent absolute Tm estimates will be cheap.

## Models, methods and cost accounting

The native comparisons use unchanged existing exports of the complementary
8-bp duplex GCGTTGCG / CGCAACGC, sequence-dependent DNA2, 70°C sampling,
0.3 M salt and 12 mM total strands (cubic side 7.6505909078802 reduced length).
Four native CPU processes run on an AMD Ryzen 9 9950X; methods run sequentially.
No new structures, production engine changes or GPU builds were needed.

Three cold serial-training pilots compare translation/rotation/cluster-cap
0.1/0.2/12, 0.5/1/16, and 1/2/16. Each uses eight 200k-sweep tuning rounds,
200k discarded equilibration and 1M production sweeps in each of four fresh,
independently seeded replicas, alternating bound/separated initial states.
These are whole-workflow comparisons: their independently learned biases differ,
so they do not isolate proposal size as a causal factor.

Two further pilots use identical .5/1/12 proposals and four-walker training:
q-only versus q plus minimum native-partner base-site distance, split at one
reduced length unit. Near and far q=0 bins are both included in the unbound
partition sum. The distance coordinate targets approach/alignment without
changing interactions. Native biasing needs no new forces. A separate 10k-sweep
native smoke checked the two-coordinate pathway and is excluded from estimates.

The independent longer distance campaign uses new training/production seeds,
fresh opposing starts and a fixed 27-minute driver cap with three minutes
reserved for full-Hamiltonian analysis. Pilot data are excluded. Interim
precision checks do not stop the campaign. See the exact
[protocol and decision record](benchmarks/equilibrium_tm_20261121/protocol.md).

Reported method time includes measured tuning, equilibration, production, native
histogram analysis and full-energy analysis. Small process/input-copy and pairing-
audit overheads are reported separately where measured. Prior literature/code
inspection and algorithm development are not a per-estimate runtime. Historical
GPU results are labeled historical, not pooled or treated as fresh matched trials.
MD steps and VMMC sweeps are not compared as equivalent work.

## What the short pilots establish

Serial tuning is fragile: consecutive rounds trapped in q=0 caused the updater
to drive its relative weight to 3.06e-7 (small moves) and 2.95e-8 (largest moves).
The resulting frozen ensembles did not sample equilibrium binding. Opposing
starts can both become bound and still fail: the small-move pilot sampled no
unbound production frames at all. Larger moves also cost more per sweep and
produced no full round trips in these serial-training pilots.

Four-walker distance training visited every intended state and avoided that
extreme suppression. Its 7.34-minute pilot completed two full q=0↔q=8 round trips,
but only in two replicas. The others failed to bracket Tm. One trapped replica
had importance-weight ESS ≈472 yet never visited q=0. Kish ESS measures weight
concentration, not ergodicity. Partial contacts and pooled Tm near 70°C are not
substitutes for independent equilibrium agreement.

The all-pair audit reproduced recorded native q. In the distance pilot, 13 of
480 q=0 saved frames had non-native interstrand hydrogen bonds. These are biased
frame counts. Reweighting the alternative any-interstrand-bond definition changed
the provisional pooled crossing from 71.619 to 71.724°C, much less than replica
spread. This does not validate the sparse crossing itself.

## Temperature and concentration analysis

The pinned native histogram extrapolator treats stacking as linear in T but
keeps the remaining energy fixed. DNA2's Debye screening length also depends on
T. Therefore its histogram extrapolation is not an exact reevaluation of the
full temperature-dependent DNA2 Hamiltonian. The research analyzer reevaluates
all saved production frames with the matching DNAnalysis library at 41 target
points from 60–80°C, checks source energies against sampling output, and verifies
that stacking plus electrostatics accounts for the temperature-energy change.

On identical medium-pilot frames, full reevaluation moved the provisional Tm by
−0.063°C relative to stacking-only extrapolation. On distance-pilot frames the
shift was −0.016°C. These small observed corrections do not justify omitting
this term for other salt conditions, sequences or lesions. Differences between
sparse saved-frame estimates and native every-attempt histograms are a separate
sampling-cadence effect.

For two distinct strands at the simulated concentration, use
f_bulk = 2r/(2r+1+sqrt(4r+1)), where r is the unbiased box bound/unbound ratio;
f_bulk=1/2 requires r=2. The exact frozen bias is removed before applying this
correction. No biased-frame fraction is presented as equilibrium yield.

## Uncertainty and calibration limits

The estimator uses time-batch resampling at two batch lengths tied to the
weighted influence autocorrelation, plus a between-replica Student-t envelope.
It does not discard unbracketed bootstrap draws to manufacture narrow intervals.
Starting-state differences, early/late drift, insufficient long batches and sparse
endpoint traffic remain rejection criteria. Replica diagnostics are conditional
on the shared frozen training bias; an independent training campaign checks
whether favorable pilot behavior reproduces.

A synthetic two-state stress test used 200 campaigns per persistence setting,
four chains each and known Tm=70°C. For independent samples, 197/200 reported
intervals covered 70°C; 189 passed the target/diagnostic checks. With persistence
0.95, only 28 intervals were available (27 covered), and none passed the precision
target. With persistence 0.999, none were available. This checks conservative
failure handling in a known model; it does not calibrate molecular hidden-state
coverage. No independent equilibrated DNA2 reference or experimental validation
was generated in this session.

## Literature and alternatives

Collective VMMC moves have a detailed-balance basis in
[Whitelam & Geissler](https://arxiv.org/abs/cond-mat/0508100); native umbrella
inputs are documented in the [oxDNA guide](https://lorenzo-rovigatti.github.io/oxDNA/umbrella_sampling.html).
The concentration correction follows
[Ouldridge et al.](https://arxiv.org/abs/0910.1201).
Sequence-dependent thermodynamics and DNA2 electrostatics are described by
[Šulc et al.](https://arxiv.org/abs/1207.3391) and
[Snodin et al.](https://arxiv.org/abs/1504.00821).
Flat occupancy alone is not optimal mixing: the optimized-ensemble work of
[Trebst et al.](https://arxiv.org/abs/cond-mat/0401195) motivates measuring endpoint
round trips rather than only bias stability or histogram flatness.

A separate [SantaLucia nearest-neighbor](https://doi.org/10.1073/pnas.95.4.1460)
calculation gives 69.718°C at the same strand/sodium concentrations in milliseconds
including interpreter startup. It is the fastest undamaged-sequence screening
calculation tested, but it uses a different empirical model, supplies no calibrated
±1°C interval here, and cannot distinguish CPD isomers without validated parameters.
Agreement with a provisional oxDNA point is not independent validation: oxDNA
sequence thermodynamics were parameterized against nearest-neighbor behavior.

Temperature/replica exchange, optimized-ensemble feedback and alchemical methods
were considered but not implemented in these experiments. Temperature swaps
would require full cross-Hamiltonian energies; frequent swaps alone would not
prove configuration mixing. For CPD ΔTm, a bound/unbound alchemical cycle analyzed
with [BAR](https://doi.org/10.1016/0021-9991(76)90078-4) or
[MBAR](https://pmc.ncbi.nlm.nih.gov/articles/PMC2671659/) is a promising later
route to test, not a demonstrated speedup. It requires overlap, reversible end-state
sampling and a validated lesion Hamiltonian. Independent ±1°C design estimates
imply approximately ±1.41°C uncertainty on their difference; shared training
cannot be assumed to provide favorable covariance or model-error cancellation.

## Verification, retention and change disposition

Eleven distinct focused tests passed: two periodic-geometry checks, five existing
precision tests, and four new research tests. Scoped Ruff and whitespace checks
passed. All seven retained campaign statistics replayed successfully; the final
any-interstrand association analysis also reproduced exactly after cleanup.
These checks verify implementation and retained calculations, not molecular
confidence-interval coverage. Box-size effects and competing solution species
were not independently benchmarked.

The archive retains exact settings, seeds, native identities, ordered execution
receipts, source snapshots, compact time-resolved statistics, audits and figures.
Its [README](benchmarks/equilibrium_tm_20261121/README.md) gives statistical replay
and native rerun commands. In the trace figures, gray denotes training and yellow
denotes equilibration. After hash verification and replay, cleanup removed only
the owned experiment tree: **9,158 files / 550,640,103 logical bytes**. About 16 MB
of compact evidence remains. The raw-file hash inventory and cleanup receipt are
retained; new coordinate or Hamiltonian analyses require a native rerun.

The separate research commit should contain `tools/oxdna_tm_research/`,
`tests/test_oxdna_tm_research.py`, this report, its compact benchmark archive, and
the session link added to `docs/oxdna_equilibrium_tm_research.md`. These changes
merit retention as a negative-result benchmark and reusable analysis harness;
they do not justify production integration. Existing uncommitted dependencies
are recorded and snapshotted for reproducibility, not silently included in that
commit. No commit or push was made. User structures, managed jobs, production
engines and unrelated work were preserved; inspected dependency hashes and the
production engine target still match their initial records.
