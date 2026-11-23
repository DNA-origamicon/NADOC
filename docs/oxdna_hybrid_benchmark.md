# Hybrid oxDNA melting benchmark

**Closed research attempt; not implemented as a production feature.** On
2026-11-21 the user requested removal of experiment data. Raw trajectories,
checkpoints, logs and isolated source/build copies described below were deleted.
Historical artifact paths below no longer exist. Notes and compact metrics are
retained in [benchmarks/oxdna_hybrid](benchmarks/oxdna_hybrid/); see
[research status and handoff](oxdna_equilibrium_tm_research.md). Numerical
diagnostics do not establish equilibrium convergence or Tm precision.

Experimental implementation: [tools/oxdna_hybrid](../tools/oxdna_hybrid/README.md).
Raw evidence, source snapshots, isolated native builds and figures:
`.development-artifacts/oxdna-hybrid/`.

## Question and comparison

Does well-tempered metadynamics training followed by independent, frozen-bias
production reduce the starting-state dependence seen in distance-only GPU
umbrellas, and does it improve useful sampling per elapsed minute?

The matched-step ablation compares unbiased MD, COM-distance metadynamics,
orientation-sensitive hydrogen-bond-proxy metadynamics, and mixed pairing plus
base-site-distance metadynamics. Four workers run concurrently under a private
NVIDIA MPS service. Methods run sequentially. Each uses 4.2M MD steps per replica:
2M training +200k discarded fixed equilibration +2M production; the unbiased
control reallocates training to production (200k +4M) and disables external
forces. Different seeds are recorded. This is one campaign per method, not an
independently replicated estimate of method efficiency.

All start from the same unchanged exported 8-bp duplex configurations, split
equally between bound and separated states. Conditions are sequence-dependent
DNA2, 70 C, 0.3 M salt, inherited cubic box corresponding to approximately 12 mM
total DNA strand concentration, Brownian MD, dt .005, diffusion 2.5. The controller
checks loaded native-library identity, hashes the frozen bias, excludes training
and equilibration samples from equilibrium analysis, and rejects bias-energy
inconsistencies. Production restarts from fresh opposing initial states rather
than reusing favorable training endpoints.

## Numerical prerequisites

The installed source already supplies the continuous pairing coordinate and
CPU/GPU forces. Two issues were repaired only in isolated candidate builds:

* The GPU switching/mixed coordinate derivative used the nucleotide-center
  vector instead of the base-site vector used in its potential. Grid bounds
  were also incorrectly stored as integers.
* The upstream HB proxy omitted smoothed radial tails and could jump at the
  cutoffs. CPU and GPU proxy functions now use the native radial-tail form.

The final candidate passed numerical translational/rotational gradient checks
on three existing configurations and CPU/CUDA short-step comparisons. Maximum
gradient discrepancy was 6.87e-9; maximum velocity/angular-momentum discrepancy
was 2.49e-6. The radial boundary check resolves a maximum 8.03e-6 difference across
1e-8 offsets, within the native constants' rounding and the specified 1e-5
tolerance. These validate the tested bias mechanics, not thermodynamic convergence.

The first candidate pilot was intentionally stopped when the radial cutoff issue
was found. Its outputs are diagnostic only and are never pooled with the final
ablation. The application engine and managed user jobs were not changed.

## What counts as improvement

Report elapsed time including training; reweighted bound probabilities separately
for bound and separated starts; q=0/1 crossings; passages from q=0 to q>=6 or
back; weighted effective sample size and correlation diagnostics. Frequent q=0/1
flickering alone does not establish independent dissociation/reassociation.
Trapped trajectories cannot receive a zero-width interval.

Temperature analysis reevaluates the physical DNA2 energy of saved frames at
each target temperature and applies the bulk heterodimer concentration
correction. An unbracketed melting curve produces no Tm. Reported between-replica
intervals remain provisional: small-replica estimates, insufficient mixing,
temperature overlap and shared bias-learning history need further assessment.
No automatic +/-1 C certification is implemented.

## Completed results (2026-11-20)

Hardware: RTX 3080 Ti (12 GB), Ryzen 9 9950X, four GPU workers under MPS.
These are local measurements, not predictions for Alpine. Six bounded campaigns
completed approximately 100.8M total MD steps in 23 minutes of sampling runtime;
native builds, diagnostics and analysis are additional development costs.

| Method | Minutes, including training | q=0 crossings | q=0 ↔ q>=6 passages | Reweighted p(bound), bound / separated starts |
|---|---:|---:|---:|---:|
| No bias | 3.31 | 2 | 0 | 1.000 / 0.000125 |
| Distance-only hybrid | 3.34 | 1 | 1 | 0.993 / 0.000 |
| Pairing-only hybrid | 4.03 | 1 | 0 | 1.000 / 0.000000048 |
| Mixed, initial ablation | 4.09 | 84 | 0 | 1.000 / 0.00499 |
| Mixed, final engine, radius 0.5 | 4.11 | 42 | 1 | 1.000 / 0.00583 |
| Mixed, final engine, radius 1.5 | 4.10 | 1 | 0 | 1.000 / 0.0000746 |

A passage is one direction, not a complete round trip. Counts are recorded at
1,000-step cadence, not every microscopic event. More q=0/1 crossings did not
produce agreement between starting states. None of these trials establishes a
reliable equilibrium melting estimate, let alone +/-1 C. The broader contact
radius did not improve this short-budget comparison. Each method has only one
campaign; differences between methods are descriptive, not statistical rankings.

The initial four-method ablation used candidate v2. Additional checks for the
broader contact term exposed two further implementation issues: CUDA must apply
minimum images to base-site positions; CPU nonlinear-bias forces must not reuse
a coordination value cached before Verlet moves positions at the same step.
The final candidate v3 corrects both. The two contact-radius trials use that same
final engine, identical step budgets and matching seed schedules. The physical
DNA2 force field is unchanged. CPU/GPU validation now also covers a nonlinear
table, fractional grid boundaries and the broader contact term. Max short-step
parity discrepancy remains 2.49e-6. The CPU coordinate cache is deliberately
removed for correctness; CPU biased-MD performance has not been benchmarked.

Frozen-bias temperature reevaluation from 60–80 C yielded **no bracketed Tm for
any replica** in the initial mixed trial or either final-engine refinement.
Bound-start replicas stayed almost entirely bound; separated-start replicas
gave much lower reweighted binding probabilities. Therefore no Tm confidence
interval is reported. Importance-weighted effective samples were very small in
the initial mixed trial (roughly 2–13 per replica after the correlation estimate).
Do not use the pooled point estimate as an equilibrium result.

The final narrow/broad training histories reproduce their frozen tables exactly.
Their late-training bias-shape changes were respectively 0.62/0.59 kBT RMS and
0.94/1.06 kBT maximum over the final quarter, after removing a constant offset.
This is descriptive evidence of continuing training changes, not a proof that
any particular longer duration will converge. Frozen-bias reweighting remains
valid for an arbitrary bias if production samples equilibrium; it is the
observed insufficient production mixing that defeats precision here.

An all-pair audit of the initial mixed trial found a non-native interstrand bond
in only 1 of 288 saved q=0 frames. Those are biased-frame counts, not equilibrium
fractions. Audit inputs must inherit the exact native settings used for sampling;
an initial reduced-settings audit disagreed near a pairing threshold and was
superseded by the matched-input audit. The latter reproduces every recorded
native-pair count at the audited frames.

The distance observable prints only four decimals. Analyses therefore use the
recorded native bias energy for reweighting and check tabulated agreement against
an explicit coordinate-rounding error bound. Reconstructing weights from rounded
distance alone was caught by the consistency check; completed simulations were
retained and analyzed again after the fix.

**Conclusion:** the hybrid implementation is a usable research benchmark, but
these short pilots do not justify replacing VMMC or promoting this workflow to
wizard defaults. Partial-contact acceleration is not yet an acceleration of
reliable Tm estimation. Longer/better bias learning and improved sampling of the
association/zippering bottleneck require a separate measured follow-up.

Figures and exports:

* `.development-artifacts/oxdna-hybrid/ablation/comparison.{png,pdf,csv}`
* `.development-artifacts/oxdna-hybrid/ablation/pairing_traces.{png,pdf}`
* `.development-artifacts/oxdna-hybrid/contact-refinement/comparison.{png,pdf,csv}`
* Each campaign: `analysis.json`, `temperature_analysis.json` where evaluated,
  native trajectories/energies, frozen bias, input/source hashes and event history.

## Software validation and retention

Eight focused hybrid tests passed, as did repository lint and lint of the new
research tools. Native force validation passed 12 cases. An intentionally expired
campaign deadline wrote its failure receipt and terminated both owned workers;
no hybrid workers or private MPS processes remain. Scratch is empty. Approximately
499 MB of raw results, isolated builds, source snapshots and diagnostics are kept
on configured development storage. The application engine symlink is unchanged.
No frontend changes were made; feature `main.js` LOC delta is 0.

`just test-smart` selected FAST: 21,002 passed, 90 skipped, one unrelated VR
build-test failure. Its global subprocess mock captured a background trajectory
precompute call; the isolated VR recheck passed (1 test). This remains an open
test-isolation issue, not a clean broad-suite pass. Slow-test triage found one
5.46 s authoring test; isolated recheck was 1.17 s setup plus 0.57 s call. No
timing budget or slow marker was changed on this transient observation.

DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
