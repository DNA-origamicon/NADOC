#!/usr/bin/env bash
# exp37 watchdog: keep the FINE sweep alive until the full map is computed.
# - resumes (relaunches; sweep.py skips CSV rows already done) if the process dies with work left
# - flags a stalled heartbeat (no new solve in >8 min while a process is alive)
# - exits 0 when heartbeat reports done==total
set -u
cd /home/joshua/NADOC
RES=experiments/exp37_cando_skip_twist_map/results
HB=$RES/heartbeat.json
LOG=$RES/sweep.log
launch() {
  echo "[watchdog $(date +%T)] launching sweep"
  nohup env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. \
    "$HOME/.local/bin/uv" run python experiments/exp37_cando_skip_twist_map/sweep.py \
    >> "$LOG" 2>&1 &
  echo $!
}
# adopt the already-running instance if present, else start one
PID=$(pgrep -f "exp37_cando_skip_twist_map/sweep.py" | head -1)
[ -z "$PID" ] && PID=$(launch)
while true; do
  sleep 60
  # completion?
  if [ -f "$HB" ]; then
    done=$(python3 -c "import json;d=json.load(open('$HB'));print(d.get('done',0))" 2>/dev/null || echo 0)
    total=$(python3 -c "import json;d=json.load(open('$HB'));print(d.get('total',0))" 2>/dev/null || echo 0)
    if [ "$total" != "0" ] && [ "$done" = "$total" ]; then
      echo "[watchdog $(date +%T)] DONE $done/$total"; exit 0
    fi
  fi
  alive=$(pgrep -f "exp37_cando_skip_twist_map/sweep.py" | head -1)
  if [ -z "$alive" ]; then
    # process gone — is the map complete? if grep says so, stop; else resume
    if grep -q "SWEEP COMPLETE\|nothing to do" "$LOG" 2>/dev/null; then
      echo "[watchdog $(date +%T)] sweep finished per log"; exit 0
    fi
    echo "[watchdog $(date +%T)] process died with work left — resuming"
    PID=$(launch)
    continue
  fi
  # stall check: heartbeat older than 8 min while alive
  if [ -f "$HB" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$HB") ))
    if [ "$age" -gt 480 ]; then
      echo "[watchdog $(date +%T)] STALL: heartbeat ${age}s old, killing+resuming"
      pkill -f "exp37_cando_skip_twist_map/sweep.py"
      sleep 5
      PID=$(launch)
    fi
  fi
done
