> Latest fresh-session checkpoint: [HANDOFF.md](HANDOFF.md), 2026-09-10. The original summary and addenda below are historical; use the handoff and refreshed STATUS.md for current coverage and scheduling.

# PEG model port: progress checkpoint

Saved at 2026-09-10T00:30:07.189057+00:00 (September 9, evening, America/Denver). This is a user-requested stopping point for active intervention. **The scientific engine port is implemented; full published benchmark reproduction is not established.** Existing simulations and previously queued continuations were left running. No new allocations were made while preparing this checkpoint.

## What is implemented

The isolated oxDNA CPU/CUDA extension supports one chemical EO bead per PEG repeat, the published bond, angle and torsion terms, corrected Mie-plus-Gaussian interactions, temperature dependence, and direct-neighbor exclusions. It includes CPU equilibrium Monte Carlo/pivot sampling, GPU dynamics, and a GPU HMC sampler with molecular-volume moves. Inputs, seeds, source endpoints, engine hashes, trajectories and analyses are persisted.

The implementation is in `tools/oxdna_peg/`, with reproducible launch and analysis tools in this directory. The isolated engine is built by `scripts/build-oxdna-chudoba.sh` under `~/.local/share/nadoc/engines/oxdna-chudoba/`. The current shared-library hash matches the recorded **91-check validation build**. Additional focused NPT and trajectory-representation checks are also recorded. These checks validate implementation and selected sampler behavior, not the entire published benchmark suite.

The earlier NADOC PEG surface review file and playground use the earlier approximate model. They have not been silently relabeled as this chemical-repeat model. The paper-model workflows currently use the scientific CLI and isolated engine; this checkpoint is not a claim of completed playground integration.

## Benchmark results

| Benchmark | Published states | Three-replica states completed | Sampling assessment |
| --- | ---: | ---: | --- |
| Chain dimensions | 45 | 31 | 23 pass current screening; 8 need extension |
| Osmotic pressure | 15 | 4 | All four completed cohorts still fail convergence screening |

The completed pressure cohorts are N135 at 294 K and 1, 10, 20 and 50 kPa. Their pooled concentrations can be near the published values while individual replicas remain poorly mixed. Agreement of an unconverged average is not reproduction.

None of the 23 chain states passing sampling screening falls outside the current comparison intervals. Those intervals include simulation uncertainty, digitization bounds and the published plotted ranges where available; the paper's error-bar type remains unspecified. Simulated radii tend to lie above the published markers, so exact marker agreement and possible systematic offsets remain open issues.

The N36, 381 K GPU cohort agrees with CPU sampling: RMS radius 1.18093 ± 0.01344 nm versus 1.17493 ± 0.00783 nm (conservative SEMs). Its R-hat is 1.00475 and minimum squared-radius ESS is 112. The N135, 396 K GPU cohort at 20 ns per replica is **not converged**: minimum ESS about 9 and R-hat 1.088. Three sequential 400 ns endpoint continuations have been allocated, with the first running. The pilot rate suggests roughly 12 GPU-hours for that allocation, with substantial uncertainty in runtime and no guarantee of convergence.

## Important model-fidelity findings

- Figure 4(b)'s vector curves strongly support removing only the outer attractive tail after its zero crossing. That reconstructed `zero_tail` convention is the primary model; raw and globally shifted runs are retained as controls.
- Figure 7's density curves support reporting `sqrt(mean(Rg²))`. The analyses preserve both this RMS radius and mean instantaneous radius, rather than conflating them.
- Figure 5 curves differ slightly from rounded Table 2 coefficients. Reconstructing the plotted coefficients increases the pair excluded-volume integral; this does not straightforwardly explain the larger simulated radii. Running parameters were not refitted to benchmark outcomes.
- Independent minimum-image reconstruction agrees with direct-coordinate radius analysis in the selected CPU, GPU and solution trajectories. No wrapping error was found in those audited results.

The [preprint](https://arxiv.org/abs/1710.09191) and final [supporting information](https://ndownloader.figshare.com/files/9686908) are available and audited. The final journal main text and original simulation tables remain unavailable. Thus the reconstructed cutoff convention and full parameter precision have not received a final-source verification.

## Work left running

The checkpoint records **16 live oxDNA workers**. They cover the remaining base chain/pressure campaigns, longer CPU continuations, and the GPU continuation. Four additional delayed drivers wait for their predecessor campaigns to finish:

| Waiting allocation | Predecessor |
| --- | --- |
| N275, 381 K: 3 × 900,000 sweeps | Chain extension round8 |
| N275, 347 K: 3 × 300,000 sweeps | Chain extension round7 |
| N275, 371 K: 3 × 700,000 sweeps | Chain extension round5 |
| N135, 294 K, 50 kPa: 3 × 20,000 sweeps | 1 kPa pressure continuation campaign |

Those queued drivers were verified live during checkpoint preparation and can start their allocations automatically. PEG simulations run at nice19. Existing QM jobs were not stopped or modified. Hardware used is the local **RTX 3080 Ti**, not an RTX 6000. **Cloud spend: $0 of the authorized $3.**

## Remaining work

Finish the missing states, assess completed continuations, and extend or investigate states that remain unconverged or disagree with the paper. Dense pressure states are especially slow. Verify final publication details if the final main text or original tables become available. Once complete, perform a requirement-by-requirement audit before calling the benchmarks reproduced.

These are bulk-PEG benchmarks. Surface attachment, PEG–DNA cross-interactions and electric-field response remain separate unvalidated modeling assumptions. No calibrated field-modulated coating claim follows from this port.

## Evidence and restart context

- [Frozen checkpoint, including live PID/path snapshot](checkpoint_20260909.json)
- [Current generated status](STATUS.md)
- [Chain comparison](campaign_comparison.json), [pressure comparison](eos_comparison.json), [CPU/GPU comparison](sampler_comparison.json)
- [Validation provenance](verification_zero_tail_manifest.json)
- [Potential-curve audit](reference/potential_curve_audit.json), [radius-definition audit](reference/rg_definition_audit.json), [parameter-precision audit](parameter_precision_audit.md)
- [Periodic trajectory audit](periodic_analysis_audit.json), [GPU solution pilot](gpu_solution_pilot.md)
- [Detailed history and commands](README.md), [progress history](progress_history.md)

The persistent goal is intentionally not marked complete. Before intervening again, inspect actual processes and saved manifests; do not duplicate frozen allocations or infer a job stopped from a stale snapshot.

Scheduling correction after this checkpoint: the user specified serial execution.
The existing campaigns are now serialized with live process suspension; see
[serial scheduling and recovery](SERIAL_SCHEDULING.md) and `serial_schedule.json`.
The 16-worker snapshot above describes the earlier state, not the current policy.

Subsequent serial-queue result (2026-09-10 00:41 UTC): N275 at 320 K extension completed all three replicas. RMS Rg = 4.33802 ± 0.02418 nm (SEM), minimum effective sample count 631, rank/folded split R-hat 1.00089. It passes current sampling checks but exceeds the published marker (3.94832 nm) by 9.87% and fails the plotted-interval comparison including two simulation SEMs and digitization allowance. This is the first screened discrepancy; see [saved evidence](n275_t320_discrepancy.json). Coverage is now 32/45 chain states, 24 passing sampling checks, eight flagged; benchmark reproduction remains unproven. The controller advanced to the existing 294 K campaign with one unsuspended and 14 suspended native simulations.

N795 at 294 K subsequently completed all three 100,000-sweep replicas under the serial queue. RMS radius 8.87020 ± 0.06434 nm (SEM), minimum squared-radius ESS 323.49, rank/folded split R-hat 1.00231. The estimate is 6.45% above the published marker but within its plotted interval; this is a sampling-check pass and interval-screen pass, not exact-marker reproduction. See [cohort evidence](n795_t294_completed_comparison.json). The controller advanced to the existing 320/347 K campaign with one unsuspended native engine.

N455 at 320 K completed: RMS radius 5.81854 ± 0.04269 nm (SEM), minimum ESS 240.07, R-hat 1.00053; 0.945% below the published marker and within the marker comparison. This breaks the increasing discrepancy seen through N275 at 320 K. The plot and mapping-audit interpretation were updated. See [cohort evidence](n455_t320_completed_comparison.json). The existing N455/347 K cohort now runs serially.

N455 at 347 K completed all three 100,000-sweep replicas. RMS radius 4.88140 ± 0.11488 nm (SEM), minimum ESS 98.81, rank/folded split R-hat 1.02540. Although the estimate lies near the published marker, it fails sampling checks and needs additional sampling; no reproduction claim is justified. See [cohort evidence](n455_t347_completed_comparison.json). No new continuation was allocated. The existing N795/320 K cohort is now running serially.
