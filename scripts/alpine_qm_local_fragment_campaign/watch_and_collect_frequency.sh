#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/../.." && pwd)
host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
control_socket=${ALPINE_CONTROL_SOCKET:-/tmp/nadoc-alpine-$(id -u)/control.sock}
campaign_root=${1:?campaign root is required}
job_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["slurm_job_id"])' "$campaign_root/submission.json")
remote_root=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote_root"])' "$campaign_root/submission.json")
log="$campaign_root/watch-and-collect.log"
while true; do
  if ! ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1; then
    printf '%s Alpine control connection unavailable\n' "$(date --iso-8601=seconds)" >> "$log"
    sleep 60
    continue
  fi
  active=$(ssh -S "$control_socket" "$host" "squeue -h -j '$job_id' | wc -l")
  printf '%s active Slurm records: %s\n' "$(date --iso-8601=seconds)" "$active" >> "$log"
  if [[ "$active" == "0" ]]; then
    mkdir -p "$campaign_root/remote-results"
    rsync -a -e "ssh -S $control_socket" "$host:$remote_root/results/" "$campaign_root/remote-results/" || true
    (cd "$repository_root" && uv run python scripts/alpine_qm_local_fragment_campaign/collect_frequency_campaign.py \
      --campaign-root "$campaign_root" \
      --remote-results "$campaign_root/remote-results") >> "$log" 2>&1
    if [[ -f "$campaign_root/bundle/offload_plan.json" ]]; then
      (cd "$repository_root" && uv run python scripts/alpine_qm_local_fragment_campaign/evaluate_handoff.py \
        "$campaign_root") >> "$log" 2>&1
    fi
    exit 0
  fi
  sleep 60
done
