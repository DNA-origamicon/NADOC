# Rough PEG throughput from saved run history

Machine: AMD Ryzen 9 9950X (16 cores/32 threads), NVIDIA RTX 3080 Ti (12 GB). No new simulations or cloud spend.

The expected column is a CPU-time-derived reference for these exact CPU workloads at observed execution efficiency: sweeps / native process CPU seconds. It estimates removal of off-CPU delay only. It is not a measured idle-machine result and cannot remove cache, memory-bandwidth, clock or thermal contention. Wall time includes startup/I/O overhead; ratios cannot uniquely attribute delays to QM. Native timer uses clock() in Utilities/Timings.cpp. Selected runs do not cross the suspension boundary.

| Workload | Runs | Observed sweeps/s | CPU-time reference sweeps/s | Wall time / run | CPU time / run | Wall/CPU |
|---|---:|---:|---:|---:|---:|---:|
| CPU pivot N795, 320 K (serial) | 3 | 59.25 | 62.13 | 28.1 min | 26.8 min | 1.05× |
| CPU pivot N455, 347 K (serial) | 3 | 123.82 | 135.44 | 13.5 min | 12.3 min | 1.09× |
| CPU pivot N455, 320 K (earlier concurrent; seeds 201–202) | 2 | 91.64 | 100.65 | 18.2 min | 16.6 min | 1.10× |
| CPU NPT 108 × N135, 294 K, P10 (earlier concurrent) | 3 | 3.49 | 3.57 | 9.6 min | 9.3 min | 1.02× |
| CPU NPT 108 × N455, 294 K, P1 (earlier concurrent) | 3 | 0.78 | 0.79 | 42.7 min | 42.0 min | 1.02× |
| CPU NPT 108 × N455, 371 K, P1 (earlier concurrent) | 1 | 0.27 | 0.28 | 121.6 min | 120.0 min | 1.01× |

GPU history: N36, 381 K, 20 ns replicas took 668–742 s (2,329–2,586 ns/day); N135, 396 K, 20 ns replicas took 720–741 s (2,332–2,399 ns/day). These are historical shared-machine measurements, not idle references. Extrapolating N135 at this rate gives 4.0–4.1 hours per 400 ns, or 12.0–12.4 hours for three replicas, excluding queue suspension. Short dilute-solution NVT pilot (14,580 beads): 0.2 ns / 46.899 s = 368 ns/day; startup and output overhead make long-run extrapolation weak. GPU CPU timers are not a valid GPU ideal-speed reference.

The queued GPU continuation is intentionally SIGSTOP-suspended; its current simulation throughput is zero until admitted. Similarly, other stopped jobs make no progress irrespective of QM contention. MC sweeps cannot be converted to physical nanoseconds; finishing a scheduled run does not establish statistical convergence.

Current serial N795 320 K mean wall time implies about 84 minutes for three 100,000-sweep replicas. Large NPT extensions of 20,000 sweeps would cost roughly 7.1 hours per replica at N455/294 K/P1 and 20.3 hours at N455/371 K/P1 if per-sweep cost stays unchanged; concentration and equilibration can change that cost.

No clean QM-off matched control exists in this estimate. Do not interpret differences between chain lengths, temperatures, densities, samplers, or pre/post serial cohorts as a controlled QM slowdown measurement.
