#!/usr/bin/env bash
# Fires the exp33 atomistic-MD twist-validation AFTER exp32 finishes (its results/COMPLETE
# sentinel), then babysits exp33 to completion: relaunches it if it dies (resume-safe — it skips
# completed structures), holds off if root disk would drop below 15 GB, and exits when exp33
# writes its own COMPLETE.  exp33 archives each ~1.1M-atom MD job to the external drive on finish
# so disk stays bounded.  Run detached:
#   nohup bash scripts/trigger_md_after_exp32.sh > experiments/exp33_md_twist_validation/trigger.log 2>&1 &
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$PATH"
EXP32=experiments/exp32_profile_guided_refine
EXP33=experiments/exp33_md_twist_validation
INTERVAL=300

echo "$(date '+%F %T') trigger: armed — waiting for exp32 COMPLETE…"
until [ -f "$EXP32/results/COMPLETE" ]; do
  [ -f "$EXP33/results/COMPLETE" ] && { echo "$(date '+%F %T') exp33 already complete; exiting"; exit 0; }
  sleep "$INTERVAL"
done
echo "$(date '+%F %T') trigger: exp32 COMPLETE detected → starting exp33 MD validation"

while [ ! -f "$EXP33/results/COMPLETE" ]; do
  if ! pgrep -f "$EXP33/run.py" >/dev/null; then
    free_gb=$(df -P . | awk 'NR==2{printf "%d",$4/1024/1024}')
    if [ "${free_gb:-99}" -lt 15 ]; then
      echo "$(date '+%F %T') trigger: DISK <15G free — NOT (re)launching exp33; agent must intervene"
    else
      echo "$(date '+%F %T') trigger: (re)launching exp33/run.py (${free_gb}G free, resume-safe)"
      nohup uv run python "$EXP33/run.py" >> "$EXP33/driver.log" 2>&1 &
    fi
  fi
  sleep "$INTERVAL"
done
echo "$(date '+%F %T') trigger: exp33 COMPLETE — done"
