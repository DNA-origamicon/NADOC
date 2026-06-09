# F028 B-tube Performance Optimization Research

Date: 2026-05-22

## Current Run

- Run: `experiments/exp25_full_origami_relaxation/results/runs/F028_aksimentiev_exact_btube/B_tube_namd_solvated`
- Stage: `equil_k0.5`
- Current command before launcher patch: `namd3 +p12 equil_k0.5.namd`
- Live affinity before intervention: all CPUs `0-31`
- Live affinity after intervention: all NAMD threads constrained to physical CPUs `0-15`
- Recent observed throughput: about `1.7-1.85 ns/day`

## Evidence

- NAMD 3.0.2 CPU affinity docs explicitly state that `+setcpuaffinity` can improve
  performance and that `+pemap` is useful when NAMD uses fewer threads than the
  machine has CPU threads, especially where adjacent CPU IDs share resources or
  are hardware threads.
- NAMD 3 GPU-offload docs state that GPU-offload mode still performs integration,
  constraints, and other work on CPU, so performance may be CPU-limited and all
  available CPU cores should be used with affinity set.
- NAMD 3 GPU-resident mode can more than double speed by keeping dynamics on GPU,
  but feature compatibility and CPU count must be benchmarked per system. It can
  slow down with too many CPU cores.
- The local `exp26_hardware_benchmark` full-system B_tube benchmark found:
  - `+p4`: `0.738 ns/day`
  - `+p8`: `0.966 ns/day`
  - `+p16`: `0.950 ns/day`
  - `+p32`: `0.838 ns/day`
- F028 with 2 fs, `fullElectFrequency 2`, and tutorial-like cut=8 ENM is already
  faster than F026, at roughly `~1.8 ns/day`.

## Optimization Levers

1. CPU affinity
   - Mandatory for long runs.
   - Use physical cores first, avoiding SMT siblings.
   - Current best default for F028: `+p12 +setcpuaffinity +pemap 0-15`.

2. Thread count
   - Prior full-system benchmark favored `+p8` or `+p16`, with `+p32` worse.
   - F028 currently appears good at `+p12`, but that was not benchmarked with
     startup-time affinity.
   - Need controlled sweep from the same restart: `p8`, `p12`, `p16`, and one SMT
     check.

3. Output cadence
   - Already good: energies, pressure, DCD, XST, and restart every `9600` steps.
   - No urgent change.

4. PME and electrostatics
   - F028 uses `fullElectFrequency 2`, matching the fast path that helped reach
     `~1.8 ns/day`.
   - Keep `PMEGridSpacing 1.5` for this stability-oriented Aksimentiev-style run
     unless a separate validation benchmark shows acceptable structural behavior.

5. GPU-resident mode
   - Worth retesting only as a benchmark branch.
   - Treat as non-production until extraBonds/ENM/MgHH compatibility and health
     checks pass from a restart.

## Benchmark Harness

Created:

`experiments/exp25_full_origami_relaxation/scripts/benchmark_f028_performance.py`

Dry run output:

`experiments/exp25_full_origami_relaxation/results/runs/F028_aksimentiev_exact_btube/B_tube_namd_solvated/performance_benchmarks/20260522_123356/manifest.json`

The harness benchmarks from the latest restart and refuses to run while the
production F028 process is active unless `--allow-concurrent` is given.

Recommended command after checkpoint/pause:

```bash
python experiments/exp25_full_origami_relaxation/scripts/benchmark_f028_performance.py --execute
```

If deliberately benchmarking concurrently, use:

```bash
python experiments/exp25_full_origami_relaxation/scripts/benchmark_f028_performance.py --execute --allow-concurrent
```

Concurrent benchmarking is not recommended because it contaminates CPU/GPU
performance measurements and slows the production job.

## Next Decision Rule

- If `p12_phys_0_15` wins or ties within 3%, keep the current patched launcher.
- If `p8_ccd0` or `p8_ccd1` wins, restart future stages with a single-CCD map.
- If `p16_phys` wins by more than 5%, switch F028 future stages to `NAMD_THREADS=16`.
- If `p24_phys_smt` wins, run a confirmation benchmark before using SMT for a
  multi-day production stage.

## Completed Benchmark: 2026-05-22

Completed full F028 affinity/thread sweep:

`experiments/exp25_full_origami_relaxation/results/runs/F028_aksimentiev_exact_btube/B_tube_namd_solvated/performance_benchmarks/20260522_130530/`

Mean results from six benchmark lines per variant:

- `p16_phys`: `1.7672 ns/day`
- `p12_phys_0_15`: `1.7656 ns/day`
- `p12_phys_0_11`: `1.7461 ns/day`
- `p24_phys_smt`: `1.7111 ns/day`
- `p8_ccd0`: `1.6729 ns/day`
- `p8_ccd1`: `1.6254 ns/day`

Conclusion: keep `+p12 +setcpuaffinity +pemap 0-15` as the default production
setting. `p16_phys` was numerically fastest by only `0.0016 ns/day`, which is
below practical noise and uses four more CPU cores. SMT is slower.

## Protocol Resume: 2026-05-22

Patched F028 and related exp25 NAMD launch generators to carry forward the
default production settings:

`+p12 +setcpuaffinity +pemap 0-15`

Resumed the interrupted F028 `equil_k0.5` ladder stage from
`output/equil_k0.5.restart` using:

`equil_k0.5_resume.namd`

The restart was at step `124800`, so the resume config runs the remaining
`2275200` steps and writes final coordinates to `output/equil_k0.5.*` for the
next Aksimentiev ladder stage. A continuation supervisor was launched:

`continue_f028_after_k0.5_resume.sh 1036045`

It waits for `equil_k0.5_resume` to complete, verifies
`output/equil_k0.5.coor`, then continues `equil_k0.1`, `equil_k0.01`, and
`equil_k0` through the patched F028 runner.
