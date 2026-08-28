# NAMD RTX Pro 6000 MIG benchmark

## Observed production benchmark: `2hb_2xT` (2026-08-27)

The first wizard-submitted MIG production run is live on Alpine and provides a
useful in-workload benchmark point. This is not the controlled three-minute run
described below: it includes normal trajectory/checkpoint output and therefore
measures the real NADOC production path.

| field | RTX Pro 6000 MIG 2g.48gb | whole RTX Pro 6000 reference |
|---|---:|---:|
| NADOC job | `da4af0483372` | `029a76c6a59f` |
| Slurm job | `31729706` | `30964837` |
| atoms | 32,868 | 32,868 |
| CPUs | 8 | 8 |
| actual timestep | 4 fs, HMR, GPU-resident | 4 fs, HMR, GPU-resident |
| observed NAMD rate | **316.521 ns/day** | **498.802 ns/day** |
| seconds/step | 0.00109187 | 0.00069286 |
| relative throughput | **63.46%** | 100% |
| projected 500 ns compute time | **37.91 h** | **24.06 h** |

The MIG observation was captured after 2 h 46 min of scheduler runtime at step
9,955,000 (39.82 ns), not during startup. The same `316.521 ns/day` timing value
persisted across repeated live-metric collections; a final verification at step
10,075,000 extended the stable window to 205,000 steps. Slurm reported both requested
and allocated TRES as
`gres/gpu:rtx_pro_6000_2g.48gb=1`, on node `c3gpu-e7-u9`.

This slice therefore delivers 1.85x the conservative 171.139 ns/day planning
estimate and 63.46% of the measured whole-card rate. For this small 32.9k-atom
system, a nominal half-card slice loses only 36.5% of throughput. Treat the point
as provisional until the production run completes; completion will add the final
measurement to NADOC's learned throughput store under the MIG-specific GRES key.

Machine-readable provenance and derived comparisons are in
[`results/2hb_2xT_rtx_pro_6000_2g48_2026-08-27.json`](results/2hb_2xT_rtx_pro_6000_2g48_2026-08-27.json).

## Prepared controlled benchmark

This stages the completed `2hb_1-0xT` production system (62,673 atoms) as a
three-minute NAMD 3 GPU-resident benchmark on Alpine's RTX Pro 6000
`2g.48gb` MIG profile.

The input starts from the production replica's velocity-reseed checkpoint and keeps
its HMR, 4 fs timestep, Mg-H extra bonds, periodic cell, and anchor restraints. DCD
and frequent restart output are omitted so the result measures dynamics rather than
filesystem throughput. NAMD's `--benchmarkTime 180` stops the oversized `run`
directive at the next 500-step timing boundary.

Prepare from the repository root:

```bash
uv run python experiments/exp56_namd_mig_benchmark/prepare.py
```

The ignored staging tree is written to:

```text
workspace/mig_benchmarks/exp56_2hb_1-0xT_rtx_2g48/
```

After copying that directory to Alpine, submit from inside it with:

```bash
sbatch benchmark.sbatch
```

The prepared request is intentionally explicit:

```text
partition = artxpro6000
GRES     = gpu:rtx_pro_6000_2g.48gb:1
cores    = 8
memory   = 16 GB
walltime = 10 minutes
```

The result to record is the final `PERFORMANCE:` line in `benchmark.log`, together
with the `nvidia-smi` identity printed to `slurm-<jobid>.out`. This controlled package
remains prepared but not submitted; submission consumes Alpine SUs. The production
observation above came from the normal NADOC Job Wizard and is independent of it.
