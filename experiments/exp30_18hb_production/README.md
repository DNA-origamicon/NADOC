# exp30 — 18hb production MD run (unattended)

Goal: take the full 18-helix-bundle origami `workspace/18hb.nadoc` through the
strict production ladder (psfgen full topology → GROMACS solvate → Aksimentiev
ENM slow-release k=0.5→0.1→0.01→**k=0**) to a passing health gate, while the user
is away. Self-healing; the supervising agent is re-invoked by cron to troubleshoot.

## Key facts

- Job id: see `JOB_ID`. Workspace job dir: `workspace/md_jobs/<JOB_ID>/`.
- Solvated system: **~2.98 M atoms** (290k DNA heavy → 450k all-H → +water/ions).
  The 4-stage ladder is ~19.2 ns.
- **GPU-resident enabled (2026-06-14).** Benchmarked `CUDASOAintegrate on` (NAMD
  warns it's now spelled `GPUresident`): **2.97 ns/day vs 1.38 baseline (2.2×)** —
  physics identical (temp 299.3 K, total E in the same −10.167 M band, no drift).
  Not 10× — the elongated box (Z≈1382 Å → huge PME grid) is the ceiling, not the
  integrator. ETA now **~6–7 days**. The `CUDASOAintegrate on` line lives in the 12
  dynamics-segment package confs (NOT in the conf generator — a package re-prep
  would drop it; this run won't re-prep).
- **Resume bug fixed (2026-06-14, `namd_runner._write_resume_conf`).** It emitted
  `run upto <total>`, which this NAMD build's Tcl `run` rejects (`first arg not
  norepeat`) — every checkpoint resume would have died. Now emits `run <remaining>`
  with `firsttimestep`. The first real resume (the benchmark restart) exposed it.
- Buffer: **50 mM NaCl + 12.5 mM Mg(hexahydrate)/CUFIX** (exp29 screening win).
- Minimisation: 24 000 steps (exp29 Cycle 1 default).
- 18hb has **no extra bases** → declash off; the forced-ligation/2xT strain that
  blocked smaller designs in exp29 is absent. Bundle size (18 helices) is the
  favourable lever (exp29 Cycle 5). This is the most favourable case yet for
  surviving true k=0.

## Processes (all under nohup, survive this shell)

- `run_18hb.py` — the launcher; runs prep then drives the whole ladder via
  `run_job` (sequential segments, health gates, checkpoint resume). One process
  for the entire run.
- `watchdog_18hb.sh` — OS-level watchdog (every 600 s): snapshots via
  `monitor_18hb.py` and relaunches `run_18hb.py --resume` **iff** the run process
  died and the job is still resumable. Independent of any Claude session.
- Agent crons (this Claude session): an active check-in every 2 h + a twice-daily
  backstop. They re-invoke the agent to interpret `monitor_18hb.py` and act.

## Files

- `MONITOR_LOG.md` — one row per snapshot (time, status, segment, xsc step, C1'/WC,
  process liveness, gpu, verdict).
- `launcher.console.log` — launcher + run_job + NAMD orchestration log.
- `watchdog.log` / `watchdog.monitor.log` — watchdog actions + its snapshots.
- `MONITOR_STATE.json` — last xsc step/segment (stall detection across snapshots).
- `REPORT.md` — written on terminal state (completed / k=0-handoff).

## Agent check-in procedure (what each cron fire does)

1. `cd /home/jojo/Work/NADOC; export PATH="$HOME/.local/bin:$PATH"`
2. `python3 scripts/monitor_18hb.py` → read the **VERDICT**.
3. Act on the verdict:

| VERDICT | Meaning | Action |
|---|---|---|
| PREPARING / RUNNING_PROGRESSING | Healthy | Confirm briefly, done. |
| RUNNING_STALLED / IDLE_RESUMABLE | Run process gone, job resumable | If no `run_18hb.py`/`namd3` alive: `nohup python3 scripts/run_18hb.py --resume >> experiments/exp30_18hb_production/launcher.console.log 2>&1 &` (the watchdog also does this). |
| FAILED | run_job marked it failed | Diagnose (below), then fix+relaunch or hand off. |
| COMPLETED | Ladder finished incl. k=0 | Write `REPORT.md`, delete the crons (`CronDelete`), stop. |

## Failure diagnosis (VERDICT=FAILED)

Read `job.error` (in `workspace/md_jobs/<JOB_ID>/job.json`) and the latest segment
log (`workspace/md_jobs/<JOB_ID>/package/18hb_namd_solvated/<seg>.log`, and any
`<seg>.resume*.log`).

- **Health gate fail at k>0** (`C1' paired …% < 90%` / `WC ref-relative …% < …`):
  the structure didn't hold under restraint. Inspect the C1'/WC curve in
  `MONITOR_LOG.md` and the health JSONL. Salt is already at 50 mM (exp29-saturated)
  — don't re-tune it. If it's the early k=0.1 WC symptom (exp29 6hb), investigate
  WC reference calibration; if a genuine melt, see the k=0 fallback below.
- **k=0 gate fail (final `*_MGHH_only_*` stage)** — the approved fallback: do NOT
  leave it `failed` silently. Record the **last passing k** (the deepest stage that
  passed in `MONITOR_LOG.md`), note that production hands off to long MD/CG at that
  low-but-nonzero k (HANDOFF NEXT #1), and write `REPORT.md`. The structure is
  usable at k=0.01 even if true-zero melts.
- **NAMD crash / no checkpoint** (`stopped with no usable checkpoint`, nonzero
  exit): read the NAMD log tail. If atoms-moving-too-fast / minimisation blow-up,
  the starting geometry may be bad (note: `atomistic.py` had uncommitted WIP that
  failed 3 round-trip tests — the build audit passed, but flag if geometry looks
  wrong). If OOM, confirm a single NAMD on the GPU (`nvidia-smi`). Relaunch
  `--resume` (resumes from the last good checkpoint).
- **GPU contention** (another `namd3`): wait; do not double-launch.

## Do NOT

- Call `reconcile_job_status` from a monitor/poller — it mutates+saves job state
  and falsely marks a live run `failed` during minimisation. The monitor is
  read-only by design; only `run_job`/`--resume` may reconcile.
- Re-run prep from scratch on a transient failure — always `--resume` (lossless
  from the NAMD checkpoint).
