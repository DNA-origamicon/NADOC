#!/usr/bin/env bash
set -euo pipefail

host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
control_socket=${ALPINE_CONTROL_SOCKET:-/tmp/nadoc-alpine-$(id -u)/control.sock}
campaign_root=${1:?campaign root is required}
submission="$campaign_root/submission.json"
remote_results="$campaign_root/remote-results"
log="$campaign_root/watch-and-collect.log"
job_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["slurm_job_id"])' "$submission")
remote_root=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote_root"])' "$submission")

while true; do
  if ! ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1; then
    printf '%s Alpine control connection unavailable\n' "$(date --iso-8601=seconds)" >> "$log"
    sleep 60
    continue
  fi
  active=$(ssh -S "$control_socket" "$host" "squeue -h -j '$job_id' | wc -l")
  printf '%s active Slurm records: %s\n' "$(date --iso-8601=seconds)" "$active" >> "$log"
  if [[ "$active" == "0" ]]; then
    mkdir -p "$remote_results"
    rsync -a -e "ssh -S $control_socket" "$host:$remote_root/results/" "$remote_results/"
    uv run python scripts/alpine_qm_water_campaign/collect_campaign.py \
      --campaign-root "$campaign_root" \
      --remote-results "$remote_results" >> "$log" 2>&1
    exit 0
  fi
  sleep 60
done
