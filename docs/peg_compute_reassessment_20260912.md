# PEG compute reassessment — 2026-09-12

Read-only process/result inspection and analysis of existing Rg traces. No new
simulation, extension, scheduler action or engine rebuild was performed.

## Completion and capacity

The historical serial queue recorded its final exit at **09:03:31 MDT on September
12**. Its controller and all 20 queued process identities are no longer alive;
there is no live oxDNA process. GPU inspection found no simulation compute client
(only NoMachine), 9% instantaneous utilization and 1,149/12,288 MiB used.
The GPU is available for a small serial qualification, subject to rechecking at launch.

The final historical GPU cohort was **N135, 396 K, zero-tail, CUDA MD at 2 fs**:
`runs/zero_tail_gpu_n135_t396_extension1/s1721`, `s1722`, `s1723`.
Each completed **200,000,000 steps = 400 ns**, return code zero, with final
checkpoints and normal log termination. Three distinct replica origins
(201/202/203) give **1.2 microseconds of extension trajectories**. The final GPU
replica ended **02:46:35 MDT on September 12**; CPU queue work finished afterward.

## Newly assessed result

Recomputed `sqrt(mean(Rg^2))` using the existing `summarize_rms` implementation,
10% per-replica discard and equal weights across independent origins. The CPU
comparison uses the complete generation-1 N135/396 K pivot cohort in
`zero_tail_chain_extensions_round7`, with the same zero-tail convention.

| Quantity | GPU MD | CPU pivot MC |
| --- | ---: | ---: |
| RMS Rg (nm) | 1.97320 | 1.95537 |
| Conservative SEM (nm) | 0.02415 | 0.01708 |
| Minimum per-origin effective samples | 206.4 | 264.1 |
| Rank/folded split R-hat | 1.00467 | 1.00975 |

The mean difference is **+0.91%**. Applying the existing uncertainty-inclusive
5% equivalence rule gives `abs(delta) + 2*combined_SEM = 0.07699 nm`, below
the `0.09777 nm` limit. The equivalence classification is **equivalent**.
Both cohorts meet the existing ESS/R-hat checks. GPU relative SEM is 1.22%, below
2.5%, and its largest recorded bond is 0.43690 nm, below the 0.6 nm stability gate.

This supports equilibrium CPU/GPU consistency for **this chain length, temperature
and cutoff**, not atomistic PEG, physical kinetics, the EOS or brush compression.
The CPU R-hat is close to its threshold, and the largest per-origin half-window
RMS-Rg differences are 0.1403 nm (GPU) and 0.1593 nm (CPU); the aggregate pass should
not be presented as strong evidence of complete mixing across every observable.
The same CPU ancestry also makes post-discard loss of initialization dependence
an assumption of the sampler comparison.

Reassessment data and source-directory inventory:
`workspace/peg_wall_validation/oxdna_reassessment_20260912.json`.
Historical `serial_schedule.json` and raw trajectories were left unchanged.

## What remains unresolved

The separate bounded **294 K** validation retains its prior conclusions:
N36 passes CPU/GPU and 1-vs-2 fs comparisons; the recovered N135/1 fs cohort remains
inconclusive (minimum ESS 16.75), and the initial N135/2 fs cohort remains poorly
sampled. All seven bounded EOS states still lack the simultaneous sampling checks
required for a pass. Completion of the 396 K GPU extension does not close those gaps.

## Recommended order

1. **Run the prepared atomistic NAMD wall qualification next.** Its 9,092-atom,
   four-chain case directly tests the current development question: resident-mode
   dynamics with a repulsive barrier and native harmonic grafts. Minimize first,
   then run the 1 ps qualification and compare measured wall/graft energies,
   penetration, anchor motion and the resident-mode banner. Each engine stage has
   a 180-second cap; that is a limit, not a performance prediction.
2. If it passes, establish solvent density/thermalization and a longer PEG-only
   stability test, followed by a denser/longer-chain case and stiffness sensitivity.
   Measure Tcl-wall transfer overhead before selecting the scalable force path.
   Production HMR/4 fs needs its own qualification. Freeze the configuration
   contract and wire the frontend after those engine requirements are understood.
3. Keep the oxDNA equilibrium/EOS work separate. Do not automatically extend the
   now-passing 396 K cohort or restart blanket EOS allocations. Target the remaining
   294 K sampling and collective-move bottlenecks if quantitative brush mechanics
   becomes the next scientific deliverable.

The previous test session is still expired. Per CLAUDE.md's verification rule,
the user must open `just test-session` before native validation can run. Free GPU
capacity removes resource contention but does not open that session automatically.
Commands and parameter details: [NAMD PEG wall validation](namd_peg_wall_validation.md).
