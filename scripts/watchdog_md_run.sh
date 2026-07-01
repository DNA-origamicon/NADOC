#!/usr/bin/env bash
# Durable overnight monitor for a NADOC NAMD MD job. Runs monitor_md_run.py every
# INTERVAL seconds, appending to workspace/md_jobs/<job>/WATCHDOG.log. Read-only: it
# NEVER touches the run — it only observes and records. Stops itself on a terminal
# state (COMPLETED / FAILED / EXPLODED) so a dead run isn't polled all night and the
# morning verdict is unambiguous.
#
# Usage:  nohup ./scripts/watchdog_md_run.sh <job_id> [interval_sec] &>/dev/null &
set -uo pipefail

JOB="${1:?usage: watchdog_md_run.sh <job_id> [interval_sec]}"
INT="${2:-900}"                                   # default 15 min
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
export PATH="$HOME/.local/bin:$PATH"

JD="workspace/md_jobs/$JOB"
WLOG="$JD/WATCHDOG.log"
mkdir -p "$JD"
echo "$(date '+%F %T') watchdog START job=$JOB interval=${INT}s pid=$$" >> "$WLOG"

strikes=0                                          # consecutive terminal(3) reads
while true; do
  out="$(uv run python scripts/monitor_md_run.py "$JOB" 2>>"$WLOG")"
  code=$?
  echo "$out" >> "$WLOG"

  if printf '%s' "$out" | grep -q "VERDICT=COMPLETED"; then
    echo "$(date '+%F %T') COMPLETED — stopping watchdog." >> "$WLOG"; break
  fi

  if [ "$code" -eq 3 ]; then
    # EXPLODED is unambiguous (log-based) → stop now. FAILED needs 2 strikes so a brief
    # between-segment gap (process momentarily down) isn't mistaken for a real stop.
    if printf '%s' "$out" | grep -q "EXPLODED"; then
      echo "$(date '+%F %T') TERMINAL: EXPLODED — stopping. Inspect $JD/MONITOR_LOG.md + stage .log" >> "$WLOG"; break
    fi
    strikes=$((strikes + 1))
    if [ "$strikes" -ge 2 ]; then
      echo "$(date '+%F %T') TERMINAL: FAILED x2 (no live process) — stopping. Inspect $JD/MONITOR_LOG.md" >> "$WLOG"; break
    fi
    echo "$(date '+%F %T') FAILED strike $strikes/2 — re-checking in 60s before deciding" >> "$WLOG"
    sleep 60; continue
  fi

  strikes=0
  sleep "$INT"
done
