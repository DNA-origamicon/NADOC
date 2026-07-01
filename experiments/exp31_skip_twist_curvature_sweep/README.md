# exp31 — skip count vs twist & curvature sweep

See [hypothesis.md](hypothesis.md) for the scientific question and predictions; `conclusion.md`
is written after the series completes.

## What it does

Builds a fresh 3×6×400 square-lattice bundle at the analytical skip baseline (period 48), then
sweeps the total skip count by ±18 (one deletion per helix) per step, ±4 steps each way, under
three placement strategies (uniform restagger / incremental largest-gap / deviation-guided).
Each grid point runs a full oxDNA relaxation + 8M-step production and measures differential
global twist and integrated curvature vs the design's own analytic geometry. 25 sims total.

## Pieces

- `run.py` — the driver (build → relax → 8M production → measure → log → regen PNG → next).
  Resume-safe: completed grid points are reloaded from `results/results.json` and skipped.
- `plot.py` — regenerates `results/skip_twist_curvature.png` (twist + curvature vs skip count,
  one series per strategy). Runnable standalone to refresh the PNG.
- `../../backend/core/skip_sweep_strategies.py` — the three placement strategies (pure, tested).
- `../../backend/core/oxdna_health.py::measure_bundle_curvature` — the integrated-curvature guard.
- `../../scripts/monitor_skip_sweep.py` — read-only watchdog snapshot (VERDICT + MONITOR_LOG row).
- `../../scripts/watchdog_skip_sweep.sh` — durable OS-level loop that polls the monitor and
  relaunches a dead driver (lossless resume).

## Launch (real series)

The hardware benchmark's synthetic proxy fails on CUDA on this host (it mis-recommends CPU), but
real CUDA runs fine — so force the backend and inject the measured rate:

```bash
export PATH="$HOME/.local/bin:$PATH"
nohup uv run python experiments/exp31_skip_twist_curvature_sweep/run.py \
      --backend CUDA --device 0 --skip-benchmark --steps-per-s <RATE> \
      > experiments/exp31_skip_twist_curvature_sweep/driver.log 2>&1 &

# durable watchdog (same args), independent of any agent session:
nohup bash scripts/watchdog_skip_sweep.sh --backend CUDA --device 0 \
      --skip-benchmark --steps-per-s <RATE> \
      > experiments/exp31_skip_twist_curvature_sweep/watchdog.log 2>&1 &
```

## Archiving (disk management)

Each oxDNA run writes a ~2.5 GB job folder (trajectory). After a run's metrics are extracted
and saved, the driver MOVES its job folder to the archive drive
(`--archive-root`, default `/media/jojo/Archive/NADOC_archive/exp31_skip_twist_curvature_sweep/<job_id>`)
via the tested job-archive system (`backend/core/job_archive.archive_job` — copy-then-delete,
updates the archive index so the run stays loadable/unarchivable). This keeps the workspace from
filling the root disk over a 25-sim series. `--no-archive` keeps everything in `ws/`. If the
archive mount is absent at startup the driver warns and continues (runs stay in `ws/`).

## Monitor

- Live plot: `results/skip_twist_curvature.png` (updates after each sim).
- Progress: `results/results.csv`, `MONITOR_LOG.md`, `driver.log`.
- One-shot health check: `python scripts/monitor_skip_sweep.py` (prints a VERDICT; exit 0 healthy /
  idle / done, 2 stalled, 3 exploded / failed).
- Stop: `pkill -f exp31_skip_twist_curvature_sweep/run.py` and the watchdog. Re-launch resumes.

## Output

`results/COMPLETE` is written when all points finish (the watchdog exits on it).
