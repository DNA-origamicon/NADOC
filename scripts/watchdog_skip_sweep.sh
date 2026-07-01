#!/usr/bin/env bash
# Durable OS-level watchdog for the exp31 skip-sweep series.
#
# Every INTERVAL seconds it takes a read-only monitor snapshot (which appends a
# MONITOR_LOG row + prints a VERDICT) and, IF the driver process has died while
# work remains, relaunches `run.py` (resume-safe: completed grid points are
# reloaded from results.json and skipped, so a relaunch is lossless).
#
# Because each sim runs ~30–90 min, a fixed ~5–10 min interval naturally polls
# every sim several times — covering the requested 10% and 50% progress marks —
# and the monitor's stall-grace + NaN check catch a hung or exploded run.
# Independent of any Claude session, so the series survives a process/host hiccup.
# It does NOT auto-handle EXPLODED/FAILED (exit 3): the driver already records a
# blown-up point and moves on, and a code/hardware failure needs agent judgement.
#
# Run detached (pass the same backend flags the series was launched with):
#   nohup bash scripts/watchdog_skip_sweep.sh --backend CUDA --device 0 \
#         --skip-benchmark --steps-per-s <RATE> \
#     > experiments/exp31_skip_twist_curvature_sweep/watchdog.log 2>&1 &
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$PATH"
# Overridable so the same watchdog serves exp31, exp32, …: set EXP_DIR (repo-relative) to the
# experiment dir; its run.py is the driver.  Defaults to exp31.
EXP=${EXP_DIR:-experiments/exp31_skip_twist_curvature_sweep}
export EXP_DIR="$EXP"     # the monitor reads this too
INTERVAL=420
RUN_ARGS="$*"        # forwarded verbatim to run.py on relaunch

echo "$(date '+%F %T') watchdog: started (interval=${INTERVAL}s, run args='${RUN_ARGS}')"
while true; do
  ts=$(date '+%F %T')
  if [ -f "$EXP/results/COMPLETE" ]; then
    echo "$ts watchdog: series COMPLETE sentinel present — exiting watchdog"
    break
  fi
  python3 scripts/monitor_skip_sweep.py >> "$EXP/watchdog.monitor.log" 2>&1
  code=$?
  free_gb=$(df -P . | awk 'NR==2{printf "%d", $4/1024/1024}')
  # The sweep is "all points done" when current.json reports idle AND no driver is
  # alive AND the monitor said IDLE (code 0). Relaunch only when the driver is dead
  # but the run is plausibly incomplete (the resume path is a no-op if truly done).
  if ! pgrep -f "$EXP/run.py" >/dev/null \
     && ! pgrep -f "run.py --dry-run" >/dev/null; then
    if [ "${free_gb:-99}" -lt 8 ]; then
      echo "$ts watchdog: DISK CRITICAL (${free_gb}G free < 8G) — NOT relaunching; agent must intervene"
    else
      echo "$ts watchdog: driver process not alive (${free_gb}G free) → relaunch run.py ${RUN_ARGS}"
      nohup uv run python "$EXP/run.py" $RUN_ARGS >> "$EXP/launcher.console.log" 2>&1 &
    fi
  fi
  [ "$code" -eq 3 ] && echo "$ts watchdog: monitor verdict EXPLODED/FAILED — driver handles per-point; noting"
  sleep "$INTERVAL"
done
