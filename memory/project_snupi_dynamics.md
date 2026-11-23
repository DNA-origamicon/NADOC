---
name: project_snupi_dynamics
description: "Plan + build log — add Langevin structural DYNAMICS (Lee/Koh/Kim, Nat Commun 2023) on top of our static SNUPI mimic. Friction (RPY) + random force + GJF integrator + base-stacking Morse + trajectory analysis. Phase 1 = equilibrium-dynamics validator vs our own NMA."
metadata:
  node_type: memory
  type: project
---

# SNUPI dynamics — Langevin time-integration on top of the static mimic

## Managed RunPod CUDA campaign (2026-11-19–20)

User-requested end-to-end 2-, 10-, 30-mer campaign uses normal assembly loading,
resource admission, managed provisioning, worker submission and result collection.
All three native solver receipts confirm float64 CUDA, Torch 2.9.1+cu128, A100
80GB PCIe, 60,000 steps at 0.13 ps, 1,200 samples and 40 output frames. The
requested allocation is 80 GiB host RAM / 8 vCPUs, quoted $2.09/h, on the existing
EU-RO-1 volume. No force model, timestep, sampling schedule or source geometry
changed between sizes. The 30-mer has 30 instances / 29 joins, authored through
Add Part + Polymerize Periodic and independently replayed after publication and
reopening, including the source part's 70 commands. Its normal 75 GiB minimum
RAM admission passed against 80 GiB; no admission guard was weakened.

| Case | Job | FEM nodes | Setup (s)* | Integration (s)* | Analysis/save (s)* | Solver total (s) | Total / 2-mer |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2-mer | a2b747c76d72 | 14,112 | 14 | 10 | 17.75 | 41.75 | 1.00× |
| 10-mer | a038032742a4 | 70,560 | 28 | 23 | 128.84 | 179.84 | 4.31× |
| 30-mer | 8d9a3ca6a790 | 211,680 | 55 | 66 | 364.80 | 485.80 | 11.64× |

*Phase boundaries have one-second worker-log resolution. Solver time includes
setup, analysis/reconstruction and native cache serialization; it excludes input
preparation, worker startup/imports, provisioning and result transfer. From 10 to
30 monomers, total grows 2.70×, integration 2.87× and analysis/save 2.83× for
3× nodes. This is observed cloud scaling, not a controlled CPU-versus-GPU speedup.
The 2-mer CPU host is EPYC 9374F; successful 10/30-mer hosts are EPYC 7543.
One delivered run per size; host load and shared-volume caching are uncontrolled.
An earlier 30-mer on EPYC Genoa solved in 693.43 s but failed result packaging,
illustrating cloud variation; its timing is not silently discarded.

Live validation found and fixed two orchestration limits: cold dependency imports
needed more than 30 s (now bounded at 180 s), and multi-gigabyte result compression
exceeded 120 s (now bounded at 900 s). Archive format/compression, provenance
checks, staging and the paid-pod watchdog remain unchanged. Failed jobs
`53d8d2b83be8` and `f404d25df60e` auto-destroyed their pods and cost $0.05206 and
$0.65852 respectively; original receipts and volume outputs remain intact.

An on-pod 1,000-step, matched-NumPy-noise CPU/CUDA oracle also passes on the
deployed Torch 2.9.1+cu128: max state error 1.9984e-15, max velocity error
8.8818e-16 (53 sampled states). This is a numerical kernel control, not a
physical-equilibration claim; it runs after the measured production solve.

All three jobs completed normal collection and automatic pod destruction. All
40 frames, display values and RMSF values are finite; RMSF is nonnegative;
input snapshots and the five measured physics-source hashes match submission.
No timestep retries; transfer staging is removed. Provider inventory independently
confirms zero remaining benchmark pods. Paid pod lifetimes (startup through
cleanup): 6.74 / 10.81 / 37.53 min; successful compute costs $0.23491 / $0.37642 /
$1.30739. Total campaign compute including both failed attempts: $2.62930;
existing network-volume storage is separate. The 30-mer archive is 837,905,475
bytes; serial SFTP and local installation dominate its remaining wall time.
All nine Coarse/Flexibility/trajectory app checks pass, including frame 21/40
scrubbing and Off cleanup. The completed 30-mer has all stages Done, the spinner
cleared and Stop hidden. RunPod selection/help text are correct. Headless
software-renderer scrolling needed a longer action timeout at 30-mer scale;
controls were operated normally. Temporary documents, profiles and screenshots
are cleaned up; native managed results and the authored assembly are retained.
Evidence: `.development-artifacts/snupi-runpod-gpu-20261119/`.

Validation: 19 focused solver-cluster tests pass after both timeout fixes;
25 focused frontend checks pass. Live 10-mer timeline traverses preparation,
integration, analysis and download; 30-mer retry observes through analysis.
Both show actual step percentages, the activity spinner and selected RunPod
metadata. Completed 2/10/30-mer Coarse, Flexibility and trajectory views are lit,
opaque and colored, frame 21/40 scrubbing and Off cleanup pass. Temporary review
screenshots are inspected then deleted. Cosmetic terminal-job stale-sync wording
remains ISSUE-255; it does not change completion or stage status.

Fresh `test-smart`: FAST, 21,247 passed, 19 skipped, one known ISSUE-235 duplex
failure. The former ISSUE-252 ambient-memory/background-process failures did not
recur; their isolation debt remains open. Timing triage: 506.31 s pytest / 551 s
wrapper, no individual >5 s (maximum 4.88 s); aggregate suite-size drift, no
classification or guard changes. FULL remains deferred as recorded below.
Main.js LOC delta: 0.


## CUDA integration and cached output (2026-11-19; validated locally)

Managed predictions use `dynamics_backend="auto"`: linear/Stokes dynamics selects
`snupi_cuda.LinearGJF` when CUDA and memory headroom are available; unsupported
hydrodynamics, modified GJF, nonlinear forces and simulated tails retain CPU.
Explicit `cpu`/`cuda` calls are available; the managed worker can be overridden
with `NADOC_SNUPI_BACKEND`. CUDA admission leaves at least 512 MiB free and uses
at most half total VRAM for its conservative working-set estimate. All arithmetic
is float64. Anchors and uniform field forces are included. Retry semantics,
timestep, sampling schedule and force model are unchanged. GPU RNG is repeatable
within the same software/device environment, but differs from NumPy's sequence.
Job `execution` metadata records the actual backend, RNG, device and Torch version,
including CPU fallback reasons; remote collection preserves it.

The GPU retains all generalized coordinates/velocities, transferring only sampled
translations needed by this output path. Linear RMSF uses bounded batches and
merged population variance with the same rank-aware rigid-motion projection.
`ThermalReconstruction` now optionally returns transported normals; dynamics
reuses its immutable geometry for the 40 output frames. Passive terminal strands
retain their original offsets/normals. Simulated tails and unrecognized follower
layouts retain the full reconstruction path. No authored geometry changes.
Managed RunPod environments install pinned Torch 2.9.1 CUDA 12.8 wheels; other
local/Alpine environments need CUDA-enabled Torch to use auto acceleration.
Local numerical validation uses Torch 2.6.0+cu124 on RTX 2080 SUPER.

Evidence: `.development-artifacts/snupi-gpu-implementation-20261119/`.
`benchmark_snupi_acceleration.py` runs complete 60,000-step predictions on existing
prepared snapshots, including result caching, then deletes transient result files.
The baseline loads physics source from commit 27f978d8 in-process; both versions
run serially on the same host with one CPU BLAS thread. Ryzen 5 3600 / RTX 2080
SUPER 8 GiB, Torch 2.6.0+cu124, driver 610.88. One complete paired run per size
on a shared desktop: these are observed timings, not repeated-run confidence
intervals. GPU cold initialization is included; interpreter/snapshot loading,
remote provisioning and transfer are excluded. Same 60,000 steps at 0.13 ps
(7.8 ns), 12,000 equilibration steps, every-40 sampling (1,200 samples), 40 output
frames, 20 mM MgCl2, Stokes friction, no simulated tails, unchanged snapshots.

| Case | CPU total (s) | CUDA total (s) | Total speedup | Integration speedup | Analysis/reconstruction speedup |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2-mer, 14,112 nodes | 469.294 | 60.827 | 7.72× | 14.96× | 4.57× |
| 10-mer, 70,560 nodes | 2,537.728 | 280.310 | 9.05× | 20.58× | 4.59× |

For 5× nodes, total runtime grows 5.41× on the baseline and 4.61× on CUDA.
Integration times: 321.571→21.498 s (2-mer), 1,786.116→86.797 s (10-mer).
Analysis/reconstruction: 140.530→30.739 s and 713.711→155.464 s. Setup remains
CPU-based and includes optional CUDA initialization; file serialization is
unchanged. Host peak RSS: 1.412→1.505 GiB and 6.022→4.488 GiB. CUDA tensor
allocator peaks: 66.86 / 345.23 MiB, excluding context/driver/desktop allocations.
The unchanged 6 GiB soft / 8 GiB hard guard recorded 180 soft-limit events during
baseline 10-mer analysis, with 0.264 s observed memory-pressure stalls, no hard
limit/OOM events. CUDA cases had no soft/hard/OOM events. No integration retries.

Correctness: the full 60,000-step 2-mer CUDA control using the CPU's exact random
impulses agrees in every node's RMSF to 1.999e-15 nm maximum absolute difference
(relative L2 8.27e-16). Small matched-force state error is 4.00e-15; a coupled
oscillator ensemble's covariance differs from analytic kT*K^-1 by 1.01% (6% gate).
Cached XYZ and normals match full reconstruction, including passive terminals.
The production CUDA RNG uses an independent stream: average RMSF changes -0.058%
(2-mer) / -0.487% (10-mer), while sitewise relative L2 differences are 21.5% / 22.0%.
Do not interpret the close averages as spatial convergence; the matched-noise
control distinguishes arithmetic equivalence from this finite-sampling variation.
This benchmark does not establish long-assembly physical equilibration.

All five complete benchmark/control runs have finite trajectory/RMSF values and
no retries. Input SHA-256 and measured production-source hashes verified. Large
transient result files removed; compact metrics, RMSF arrays, comparison and
validation receipts retained. Main.js LOC delta: 0. Managed RunPod bootstrap is updated and unit-tested;
subsequent remote CUDA validation is recorded in the campaign section above.

Validation: 90 focused tests passed (CUDA, RMSF/admission, reconstruction,
job/collection, memory and environment setup); lint and diff check passed.
`just test-smart` decision FAST: 21,240 passed, 6 failed, 19 skipped. Five ambient
RAM/background-process failures pass in isolation (ISSUE-252 remains open);
known duplex-gesture ISSUE-235 remains. Fast-budget triage found no individual
>5 s test; aggregate suite duration 497.22 s exceeds its budget. No guard or timing
threshold changed. Broad-suite debt is retained verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

## Scientific contracts and navigation

Dynamics adds Langevin time integration to the SNUPI FEM structural model:
`M V̇ = F − Z V + R`, `U̇ = V`. Source: Lee, Koh & Kim, Nat Commun 14:7079
(2023), `Literature/SNUPI_dynamics.pdf`; model context: [[snupi-mimic]] and
[[project_snupi_gaps]]. Linear RMSF removes infinitesimal translations/rotations
with a rank-aware projection; nonlinear coordinates retain finite Kabsch alignment.
Trajectories are Physical/display-layer output and never change topology.
Short performance runs do not establish physical equilibration of large assemblies.
Static NMA remains the inexpensive equilibrium-shape/flexibility path; trajectories
add transient, responsive-design and dynamical information.

## Units (locked — get this wrong and it silently corrupts)
Integrate in a consistent **nm · pN · ns** system so the assembled K and displacement q keep their
NATURAL units (no per-block SI conversion of K). Derived mass unit = pN·ns²/nm = 1e-21 kg (a bp ≈
1.086e-3 of these) → the G6 mass matrix (SI kg / kg·nm²) is scaled by `MASS_G6_TO_DYN=1e21`. k_BT =
4.142 pN·nm @300 K. Stokes drag on σ=1.1 nm in water η=8.9e-4 Pa·s: `STOKES_TRANS=6πησ` → 18.45
pN·ns/nm (N·s/m ×1e12); `STOKES_ROT=8πησ³` → 29.8 pN·nm·ns (N·m·s ×1e30). Δt in ns (5 ps = 0.005).
(NB `fem_solver.KBT=4.11 pN·nm` is the 298 K NMA value; dynamics uses 300 K 4.142 — keep distinct.)
Implemented exactly this way in `snupi_dynamics.py`; validated by the 1-DOF `⟨x²⟩=k_BT/k` test.

Older timestep/memory benchmarks, linear-RMSF audit, phase implementation details,
hydrodynamics and electric-field links, references and handoffs are retained in
[the historical archive](project_snupi_dynamics_archive.md).
