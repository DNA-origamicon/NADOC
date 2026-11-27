# Periodic-image-safe VMMC

The pinned upstream VMMC code reuses all internal cluster pair energies during
rigid moves. A rotation can change minimum-image separations in a finite periodic
box, so internal energies need not be invariant. The confirmed witness is an
8-particle rotation with DNA2 Debye–Hückel energy between particles 0 and 7 changing
from 3.8718403385678773e-8 to zero while the cache remains unchanged. A native
diagnostic stopped at the first affected accepted move (sweep 1,056,435); the
observed separation residual is exactly one box length, not floating-point noise.
The original user attempts failed the accumulated-energy guard at sweeps 8,637,171
and 22,655,761. Smaller clusters/displacements do not guarantee image consistency.

`periodic-clusters.patch` checks **every internal pair** of a proposed rotation.
Bonded pairs use unwrapped separation; nonbonded pairs use minimum images. It
requires `r_new = R r_old`, within roundoff tolerance, before accepting a cluster.
A violation uses the existing rejection/rollback path (positions, cells, order
parameters); weights, concentration and interaction parameters are unchanged.

For the inverse move, the residual is `r_old - R^T r_new`, whose norm equals the
forward residual for an orthogonal rotation. The criterion is therefore symmetric.
The standard VMMC rigid-energy assumption remains true for admitted proposals;
rejected proposals contribute self transitions. Single-particle moves remain
available. This restricts proposals, not configurations or the target Boltzmann
ensemble. It can affect mixing, which must be assessed separately. We do not
add an unproven Metropolis factor to compensate for stale internal energies.

The existing energy check now tests the **absolute** discrepancy at its unchanged
1e-4 threshold. Inputs keep checks every 10 sweeps. The old check was one-sided and
could miss negative discrepancies. The earlier `preserve_topology=true` mitigation
is removed: it is not an image-consistency guarantee, and its unwrapped-displacement
limit can unnecessarily suppress moves across strand image offsets. The guide's
12-particle cap remains a proposal setting, not a correctness requirement.

`scripts/build-oxdna.sh` applies this patch and copies `periodic_geometry.h` into
the pinned source before building. Its separate `-vmmc-v1` install retains the old
engine. The backend emits `NADOC VMMC periodic-image guard v1`; the controller checks
that signature in the executable/linked library before running VMMC. It records
`periodic-image-v1` in each completed-stage receipt. Resuming a job with incompatible
receipts rewinds the affected suffix, archives previous outputs, and runs the
corrected protocol. Old histograms are not silently combined with new sampling.

## Validation

- `just test-focused tests/test_oxdna_vmmc_periodic.py` compiles the actual predicate
  and checks the recorded failing move, its inverse, and 1,000 rigid rotations with
  roundoff and image shifts. This is a software invariant test, not a production run.
- `just test-focused tests/test_oxdna_vmmc.py` covers capability rejection, immutable
  failed attempts, receipt migration, stage resume, and analysis qualifications.
- Native diagnostic/build scripts and compact evidence for the observed job live
  under `.development-artifacts/vmmc-root-cause/`. They read existing exported
  simulation inputs; they do not author or alter NADOC molecular documents.

A numerically correct sampler is not a convergence certificate. Production needs
reversible bound/unbound sampling, adequate state coverage, independently seeded
replicas, and checks of temperature reweighting. The fixed stage budgets are not
extended automatically. Native histogram reweighting and its finite-size correction
remain the analysis method; no calibrated melting accuracy is claimed by this fix.

Sources: https://github.com/lorenzo-rovigatti/oxDNA/blob/8028cf33b3cba12992b771156085fa54879f50cd/src/Backends/VMMC_CPUBackend.cpp
and https://lorenzo-rovigatti.github.io/oxDNA/umbrella_sampling.html

Observed validation on the failing 8-bp duplex inputs (12,000 µM total strands,
0.3 M salt, 70°C): three independent two-million-sweep native audits completed
with no accepted-move cached/fresh pair discrepancy above 1e-8. These exercised
the rejection path with maxclust16 and preserve_topology=false. The installed
candidate also completed a 14-stage short workflow (four tuning rounds and five
independent equilibration/production pairs); analysis correctly remained
inconclusive at that budget. These are numerical/workflow checks, not a claim that
the full production protocol has completed or converged.

The explicit disposable native workflow can be repeated with:

```sh
python -m tools.oxdna_vmmc.validate_native \
  --job-dir /path/to/existing/exported/job \
  --binary /path/to/patched/oxDNA \
  --report .development-artifacts/vmmc-workflow.json
```

It honors `NADOC_TEST_SCRATCH_ROOT` and `NADOC_TEST_SCRATCH_MOUNT`, cleans its
scratch job, and never changes the supplied job or molecular document.

## Precision and wall-time benchmark

`python -m tools.oxdna_vmmc.benchmark --help` runs a bounded, four-core CPU
VMMC melting campaign from existing native duplex inputs. This is a research
workflow separate from the wizard's saved fixed-step protocols. It requires an
existing bound configuration and a saved unbound configuration with the same
topology and box; it never authors a molecular structure. The campaign performs
fresh tuning, freezes the weights, equilibrates four independently seeded replicas
(two from each start), and advances them through equal fixed-size production blocks.
The default wall budget is 55 minutes, including tuning/equilibration; 60 minutes
is the maximum accepted budget. Native waits have a deadline, and incomplete
blocks are excluded. Native failures terminate the campaign's own children.

```sh
python -m tools.oxdna_vmmc.benchmark \
  --job-dir /path/to/existing/duplex/job \
  --unbound-conf /path/to/existing/unbound/checkpoint.dat \
  --binary /path/to/periodic-image-safe/oxDNA \
  --output .development-artifacts/new-vmmc-benchmark \
  --minutes 55 --target-halfwidth .7
```

The present benchmark protocol samples at 70°C, reweights native histograms over
64–78°C at 0.5°C spacing, and preserves the source salt concentration and box.
These temperatures bracket the current 8-bp reference, not every sequence.
Fresh tuning uses eight 200k-sweep rounds, followed by 1M equilibration sweeps
per replica. Production advances in 2.5M-sweep blocks. Histograms every 10k
sweeps preserve time-resolved native temperature reweighting, including its
temperature-dependent stacking treatment. Seeds, inputs, engine hashes, all
attempts, and checkpoint decisions are retained in an immutable output directory.

`backend/core/oxdna_vmmc_precision.py` differences cumulative histograms before
resampling time batches. It checks two batch lengths based on estimated
autocorrelation; unbracketed resamples are not discarded to make intervals narrow.
The reported approximate 95% interval encloses both block-bootstrap intervals
and a between-replica Student-t interval. Starting-state disagreement, temporal
drift, insufficient long batches, or sparse recorded transitions prevent acceptance.
Stopping uses a separate, more conservative interval with a correction for the
prespecified maximum number of checkpoint looks. Diagnostics are necessary
checks, not proof of equilibrium or model accuracy. The engine's energy guard
is retained; energy stabilization does not determine production progression.

For two independent designs with comparable uncertainty, ±0.7°C per-design
95% half-width corresponds approximately to ±1°C on their difference. The
benchmark tests the reference duplex only; it cannot certify CPD interactions
or the error in a not-yet-simulated modified design. Compare time to precision,
not MD step rate against VMMC sweeps. An exhausted budget is an inconclusive
outcome when diagnostics or the target have not been met; it is not permission
to certify an uncertain result.

When a reliable prior histogram already exists, its learned sampling bias can
be reused without including its production samples in the new estimate:

```sh
python -m tools.oxdna_vmmc.train_weights \
  --histogram /path/to/previous/last_hist.dat \
  --weights /path/to/previous/weights.txt \
  --output .development-artifacts/trained-weights.txt
# Add --frozen-weights .development-artifacts/trained-weights.txt to benchmark.
```

The update is `w_new(q) ∝ w_old(q)/count(q)`, targeting equal estimated occupancy.
Every state must have been observed; missing states are not filled with guessed
weights. `--frozen-weights` skips fresh tuning and records the supplied weights'
source/hash. Always report this as a **warm-start** campaign and account separately
for the prior training cost. Bad estimated weights reduce sampling efficiency,
but do not change the physical target distribution when the bias is correctly
removed. New configurations still undergo independent equilibration and use
new random seeds.

`python -m tools.oxdna_vmmc.report_benchmark CAMPAIGN` exports a CSV, JSON summary,
and PDF/PNG figure of precision versus elapsed time. An optional
`--prior-attempt-seconds` accounts for discarded preparation/diagnostic attempts
in the end-to-end timeline. Approximate runtime projections are omitted when
sampling diagnostics remain unresolved.

`--continue-campaign PREVIOUS --frozen-weights PREVIOUS/frozen_weights.txt
--seed NEW_SEED` continues the four saved native checkpoints without retuning or
discarding prior production. The driver checks model inputs, temperature, salt,
native library, block size, weights, and completed-stage receipts. Use a fresh
output directory and a different seed. The wall cap is incremental; reports must
also account for prior campaign time. Previously recorded production directories
remain dependencies and must not be removed. Repeated precision looks are counted
across campaigns for the stopping correction.

`python -m tools.oxdna_vmmc.sampling_trend CAMPAIGN --output NEW_DIRECTORY` analyses
cumulative replica variability, non-overlapping time windows (including failures
to bracket Tm), correlation, bound/unbound dwell lengths, and sensitivity to time
batch size. It exports JSON/CSV/PDF/PNG. Any inverse-square runtime projection is
explicitly conditional: cumulative prefixes are correlated observations, and
their fitted slope or envelope is not a convergence certificate or forecast CI.

`binding_states` can independently recompute all hydrogen-bond pairs from existing
saved trajectories with the matching `DNAnalysis` library. It verifies native-pair
counts against the saved energy stream and reports whether zero native pairs
contains non-native interstrand binding. Its frame counts describe the biased
sample, not equilibrium populations; it never changes configurations or the
melting definition.
