#!/usr/bin/env bash
# Durable OS-level watchdog for the 18hb production run.
#
# Every INTERVAL seconds it takes a monitor snapshot (which appends a MONITOR_LOG
# row) and, IF the run process has died while the job is still resumable,
# relaunches `run_18hb.py --resume` (lossless from the last NAMD checkpoint).
# It is independent of any Claude session, so the run survives a process/machine
# hiccup even with no agent attached. It deliberately does NOT auto-handle FAILED
# (exit 3) — health-gate / code failures need the agent's judgement.
#
# Run detached:
#   nohup bash scripts/watchdog_18hb.sh \
#     > experiments/exp30_18hb_production/watchdog.log 2>&1 &
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$PATH"
EXP=experiments/exp30_18hb_production
INTERVAL=600

echo "$(date '+%F %T') watchdog: started (interval=${INTERVAL}s)"
while true; do
  ts=$(date '+%F %T')
  python3 scripts/monitor_18hb.py >> "$EXP/watchdog.monitor.log" 2>&1
  code=$?
  # Disk guard: the full DCD trajectory is large (~35 MB/frame); a relaunch loop
  # that keeps writing cont*.dcd could fill the volume and corrupt a NAMD write.
  free_gb=$(df -P . | awk 'NR==2{printf "%d", $4/1024/1024}')
  # 2 = RUNNING_STALLED / IDLE_RESUMABLE → relaunch only if nothing is alive.
  if [ "$code" -eq 2 ]; then
    if [ "${free_gb:-99}" -lt 8 ]; then
      echo "$ts watchdog: DISK CRITICAL (${free_gb}G free < 8G) — NOT relaunching; agent must intervene"
    elif ! pgrep -f run_18hb.py >/dev/null && ! pgrep -x namd3 >/dev/null; then
      echo "$ts watchdog: run process DEAD and job resumable (${free_gb}G free) → relaunch --resume"
      nohup python3 scripts/run_18hb.py --resume >> "$EXP/launcher.console.log" 2>&1 &
    else
      echo "$ts watchdog: code=2 but a run/namd process is alive — not relaunching"
    fi
  elif [ "$code" -eq 3 ]; then
    echo "$ts watchdog: monitor verdict FAILED — leaving for the agent to diagnose"
  fi
  sleep "$INTERVAL"
done
