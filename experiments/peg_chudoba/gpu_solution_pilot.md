# Zero-tail solution GPU sampler pilot

108 PEG chains × 135 EO beads = 14,580 beads; 294 K. All probes started from the same completed CPU NPT endpoint at 1 kPa. Local RTX 3080 Ti; no cloud spend. These short probes measure acceptance and elapsed wall time, not equilibrium mixing or published benchmark agreement.

| Verlet timestep (fs) | Steps/proposal | Accepted / 100 | Elapsed (s) | Accepted proposals/s |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 500 | 4 | 39.77 | 0.101 |
| 1 | 1000 | 11 | 40.52 | 0.271 |
| 0.5 | 2000 | 29 | 48.77 | 0.595 |

Each proposal integrates 1 ps, but the Metropolis sequence has no physical-time interpretation. The half-femtosecond probe has the best observed acceptance throughput of these three allocations. This does not establish optimal trajectory length or effective samples per second. The runs include CPU endpoint energies, CPU molecular-volume proposals and CPU/GPU synchronization; ordinary GPU NVT dynamics is being measured separately.

Decision: retain CPU NPT benchmark queues while measuring the GPU baseline. Do not replace the pressure campaign with HMC on acceptance alone. Do not extrapolate these measurements to RTX 6000 hardware.

Raw results: [pilot summary](runs/zero_tail_hmc_solution_pilot/summary.json); fixed allocations and source: [plan](runs/zero_tail_hmc_solution_pilot/plan.json).

## Ordinary GPU dynamics baseline

The same-sized warm solution completed 100,000 NVT steps at 2 fs (0.2 ns): 46.90 s wall time, 30.98 s engine time. Engine timers assign 21.08 s (68%) to observables and 4.68 s to forces. This short allocation writes 40 configurations and about 1,000 shape/thermodynamic records, so its diagnostic and startup overhead should not be extrapolated as a constant per-step production cost. It is not an equilibrated pressure result.

[Timing evidence](runs/zero_tail_gpu_solution_timing/n135_t294_s821/timing_analysis.json) and the adjacent engine log preserve the measurements. The measured wall throughput is 368.5 ns/day for this specific short run. Longer allocations are needed for a production-rate estimate.
