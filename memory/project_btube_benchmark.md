---
name: B_tube MD benchmark results
description: GROMACS vs NAMD timing for B_tube.nadoc (24 hx, 103 nm, ~14k nt) — completed 2026-05-07
type: project
originSessionId: 9c9be7c6-98b4-42c3-a595-eb7159ceae86
---
## Results summary

Design: B_tube.nadoc, 24 helices × ~300 bp, HONEYCOMB, ~14,420 nt, 103 nm tube.
Hardware: RTX 2080 SUPER (8 GB), Ryzen 9 9950X (16c/32t), NTOMP=8 for GROMACS.

| Variant | Engine | Atoms | ns/day |
|---------|--------|-------|--------|
| A1 nstlist=20 | GROMACS vacuum PME | 462,706 | 8.40 |
| A2 nstlist=40 | GROMACS vacuum PME | 462,706 | 8.20 |
| A3 nstlist=80 | GROMACS vacuum PME | 462,706 | 8.20 |
| GROMACS solvated (extrap.) | ~888k atoms | — | ~8.66 |
| B1 +p8 | NAMD3 GBIS | 289,470 | 2.19 |
| B2 +p16 | NAMD3 GBIS | 289,470 | 2.36 |
| B3 +p28 | NAMD3 GBIS | 289,470 | 2.36 |

GROMACS/NAMD ratio: **3.56×**. GROMACS is faster.

## Periodic cell result (exp23, old hardware RTX 2080 SUPER)

| D1 | NAMD3 periodic cell (21 bp, TIP3P, std CUDA) | 165,524 | 18.87 |

18.87 ns/day — 2.2× faster than GROMACS vacuum PME, 8× faster than NAMD GBIS. Explicit TIP3P solvent + PME, standard CUDA (not GPU-resident; see project_periodic_cell.md).

## RTX 3080 Ti comprehensive benchmark (exp26, 2026-05-17)

Hardware: AMD Ryzen 9 9950X (16c/32t) + RTX 3080 Ti 12 GB, NAMD 3.0.2 CUDA.
Benchmark script: `experiments/exp26_hardware_benchmark/run_benchmark.py`
Figure: `experiments/exp26_hardware_benchmark/namd_benchmark.png`

### Standard CUDA thread scaling (ns/day)

| System | atoms | +p4 | +p8 | +p16 | +p32 | Peak |
|--------|-------|-----|-----|------|------|------|
| Single helix periodic | 15,546 | 170.6 | 190.0 | **300.2** | 233.0 | 300 @ p16 |
| B-tube 1× periodic | 162,671 | 27.1 | 38.6 | **51.2** | 45.4 | 51 @ p16 |
| B-tube 2× periodic | 324,949 | 12.3 | 17.2 | **21.5** | 19.5 | 22 @ p16 |
| Full B-tube explicit | 2,314,212 | 0.74 | **0.97** | 0.95 | 0.84 | 0.97 @ p8 |

### GPU-resident thread scaling (ns/day)

| System | +p4 | +p8 | +p16 | +p32 | Notes |
|--------|-----|-----|------|------|-------|
| Single helix periodic | 275.5 | 272.0 | **378.0** | 312.9 | flat above p4 |
| B-tube 1× periodic | **72.2** | 71.6 | 71.9 | 67.5 | flat (GPU-bound) |
| B-tube 2× periodic | **36.5** | 36.4 | 36.6 | 35.6 | flat (GPU-bound) |
| Full B-tube explicit | FAIL | FAIL | FAIL | FAIL | OOM or elongated-box PME grid |

GPU-resident **works** on wrap-bond systems and is **1.4–2.7× faster** than standard CUDA on 3080 Ti (reversed from 2080 SUPER). Optimal thread count for GPU-resident is +p4 (GPU-bound, extra threads unused).

### GPU-resident / standard CUDA ratios at optimal

| System | Ratio | Best mode | Rec. setting |
|--------|-------|-----------|--------------|
| Single helix | 1.26× | GPU-resident | +p16 GPUresident |
| B-tube 1× | 1.41× | GPU-resident | +p4 GPUresident (flat) |
| B-tube 2× | 1.70× | GPU-resident | +p16 GPUresident (flat) |
| Full B-tube | N/A (GPU-res fails) | Std CUDA | +p8 StdCUDA |

### fullElectFrequency impact (B-tube 1×, standard CUDA)

| freq | p4 | p8 | p16 | p32 |
|------|----|----|-----|-----|
| 2 (default) | 27.1 | 38.6 | **51.2** | 45.4 |
| 1 | 23.5 | 33.6 | **42.3** | 33.6 |

freq=1 costs **~17% throughput**. Only justified if MTS resonance suspected.

### Hardware upgrade speedup (2080 SUPER → 3080 Ti)

| System | Old (ns/day) | New (ns/day) | Speedup |
|--------|-------------|-------------|---------|
| B-tube 1× std CUDA | 24.7 | 51.2 | **2.1×** |
| B-tube 2× std CUDA | 9.9 | 21.5 | **2.2×** |
| Full B-tube std CUDA | 0.40 | 0.97 | **2.4×** |
| B-tube 1× GPU-resident | slower (not used) | 72.2 | — |

## Production recommendation

**B-tube 1× periodic cell**: GPU-resident +p4 (or +p8), **72 ns/day**. 100 ns ≈ 1.4 days.
**B-tube 2× periodic cell**: GPU-resident +p16, **36.6 ns/day**. 100 ns ≈ 2.7 days.
**Full B-tube explicit**: standard CUDA +p8, **0.97 ns/day**. 100 ns ≈ 103 days.
**Full-length vacuum**: GROMACS vacuum PME, nstlist=20, ~8.4 ns/day. 1 µs ≈ 119 days.

## Technical notes / gotchas

**GPU PME disabled**: GPU PME crashes (CUDA error #700) on the 108 nm elongated box
(fourierspacing=0.20 → ~676 PME Z-cells exceeds GPU PME buffer limits).
Fix: `-nb gpu -pme cpu -bonded cpu`. GPU NB still used; PME on CPU.

**Benchmark dt trick**: Unminimized conf.gro has Fmax ~1e6 kJ/mol/nm on atom 88624
(skip-site backbone bridge strain). dt=2 fs causes GPU SIGSEGV at step 1.
Fix: dt=0.00001 ps (0.01 fs), measure steps/second, scale ns/day by ×200.
This is valid because force-computation cost per step is dt-independent.

**NAMD plateaus at +p16**: Adding more threads past 16 gives ~0 speedup for GBIS.

**EM needed but imperfect**: 2000-step steep EM from conf.gro reduces LJ from
9.5e11 to -6.3e5 kJ/mol but Fmax remains ~1e6 on atom 88624 (oscillating).

**Safe thread count**: NTOMP=28 causes VSCode crashes (CPU starvation on 32-thread system).
NTOMP=8 is safe; leaves ≥24 logical cores for OS+IDE.

## Files

- `experiments/exp22_btube_md_benchmark/run.py` — benchmark script
- `experiments/exp22_btube_md_benchmark/results/benchmark_results.json` — structured data
- `experiments/exp22_btube_md_benchmark/results/benchmark_summary.txt` — human-readable table
- `experiments/exp22_btube_md_benchmark/results/run_logs/` — per-variant mdrun logs (real-time)
- `experiments/exp22_btube_md_benchmark/results/gromacs_run/em.gro` — minimized starting structure

**Why:** B_tube is the primary production target. Benchmark was needed to choose engine
and set timeline expectations before committing to a 100+ day production run.
**How to apply:** Plan B_tube production as GROMACS vacuum PME, nstlist=20.
For 300 ns (sufficient for inter-helix stiffness convergence): ~36 days.
