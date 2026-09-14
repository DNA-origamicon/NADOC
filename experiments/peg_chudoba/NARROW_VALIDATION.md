# First bulk PEG validation and matched scheduling benchmarks

Scope fixed 2026-09-10, before new timing or validation allocations. User
authorized serial/parallel benchmarks followed by validation with the best
measured configuration. This supersedes the earlier serial-only preference
for this campaign. No cloud resources or unrelated QM processes are involved.

## Claim and acceptance

Neutral, methyl-capped, free PEG in implicit water at **294 K**, using the
documented Chudoba zero-tail reconstruction. Chain dimensions cover the nine
published lengths N=9,18,27,36,76,135,275,455,795. The solution test covers all
seven published N135 pressure states, 1,10,20,50,100,200,1000 kPa, with 108 chains.
This is validation against the preprint benchmarks and final SI; the final
journal main text and authors' simulation tables remain unverified. It is
not an independent experimental validation, salt-dependent model, surface/DNA
interaction validation, or kinetic calibration.

Predefined engineering bounds: radius and concentration within 10% of the
published marker, with the entire simulation estimate +/- 2 conservative SEM
inside that band after adding only the recorded digitization bound. Simulation
relative SEM must be <=2.5%. Require three independent origins, rank/folded
split R-hat <1.01 and minimum per-origin effective sample size >=100.
Published error bars of unknown meaning are not used as confidence intervals.
Chain analysis retains the established 10% discard and sqrt(mean(Rg^2)).
Solution analysis retains the established 50% discard and mass/mean(volume).
Volume and chain shape both must mix; also inspect intermolecular contact
statistics, retained-half drift, and starting-state dependence before a pass.
Sampling agreement alone cannot establish the correctness of every model term.

GPU equilibrium checks use N36 and N795 at 294 K from three independent CPU
origins, at 2 fs and 1 fs. Require each cohort to pass sampling/precision tests
and CPU/GPU and timestep differences to fit within a 5% equivalence band,
including two combined SEM. Physical diffusion and relaxation are excluded.

## Matched scheduling experiment

Five workload classes:

| Class | Source state | Work per trial | Concurrency |
|---|---|---:|---|
| CPU pivot | N795, 294 K | 5,000 sweeps | 1,2,4 |
| CPU NPT, dilute | 108 x N135, 294 K, 10 kPa | 200 sweeps | 1,2,4 |
| CPU NPT, concentrated | 108 x N135, 294 K, 1000 kPa | 200 sweeps | 1,2,4 |
| CUDA Langevin | N36, 294 K, 2 fs | 500,000 steps | 1,2 |
| CUDA Langevin | N795, 294 K, 2 fs | 500,000 steps | 1,2 |

Each condition processes the same four tasks, with the same frozen endpoint
hashes, seeds, steps and output cadence. Two timing rounds reverse strategy
order to reduce ordering bias. Comparisons concern parallel independent
simulations, not domain decomposition or extra threads within one simulation.
No CPU/GPU overlap is inferred from these separate measurements.

Record end-to-end batch makespan, native process timing, per-task latency,
steps/s, effective samples/s (explicitly provisional for short traces), engine
and input hashes, native failures, and background CPU/GPU activity. The 2 fs
GPU work is 1 ns per trial, not a convergence allocation. Timing trajectories
are excluded from scientific production comparisons.

Select the lowest-concurrency strategy within 5% of the best geometric-mean
matched speedup, requiring improvement in both rounds and no failed tasks.
For CPU NPT use both dilute and concentrated workloads in the decision. CPU
pivot and GPU may choose different concurrency. Assess effective-sample rates
as a diagnostic; do not rank different samplers on short ESS estimates.

## Execution and provenance

The existing serial controller and its process trees must be parked with
PID/start-time validation before timing. Preserve RAM state and record every
signal. Restore the preexisting schedule on errors or completion. Never
overwrite its live serial_schedule.json with an earlier snapshot. A separate
lease and recovery record protects this temporary takeover.

After benchmarking, finish the already allocated N135/294 K EOS continuations
before creating further generations. Preserve replica ancestry. Use the chosen
NPT concurrency for independent replicas and extend only failing sampling
cohorts. Adequately sampled disagreement triggers diagnosis, not endless
extensions or parameter fitting. GPU checks use the selected GPU concurrency.
Publish explicit pass/fail/incomplete verdicts and uncertainties for every
required state; completing allocations is not a pass.

The user explicitly clarified on 2026-09-10 that `just test-session` gates long
regression tests, not directly requested experiments/simulations. This campaign
runs under that direct authorization; regression tests retain their normal guard.
No session marker or guard escape hatch is changed.
