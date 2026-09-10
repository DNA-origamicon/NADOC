#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
control_socket=${ALPINE_CONTROL_SOCKET:-/tmp/nadoc-alpine-$(id -u)/control.sock}
campaign_root=${1:?archive campaign root is required}
manifest="$campaign_root/campaign_manifest.json"
[[ -f "$manifest" ]] || exit 2
archive=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["archive"]["path"])' "$manifest")
remote_root=${2:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote_root"])' "$manifest")}
checksum="$archive.sha256"
cases="$campaign_root/bundle/frequency_cases.tsv"
[[ -f "$archive" && -f "$checksum" && -f "$cases" ]] || exit 2
[[ ! -e "$campaign_root/submission.json" ]] || exit 3
case_count=$(awk 'NF {count++} END {print count+0}' "$cases")
[[ "$case_count" -gt 0 ]] || exit 2
throttle=$((case_count < 3 ? case_count : 3))
array_range="0-$((case_count - 1))%$throttle"
ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1 || exit 4
ssh -S "$control_socket" "$host" "set -e; if [ -e '$remote_root/bundle' ] || [ -e '$remote_root/submission.json' ]; then exit 5; fi; mkdir -p '$remote_root/logs'"
scp -o ControlPath="$control_socket" "$archive" "$checksum" "$host:$remote_root/"
submission=$(ssh -S "$control_socket" "$host" "set -euo pipefail; cd '$remote_root'; sha256sum -c '$(basename "$checksum")'; tar -xzf '$(basename "$archive")'; cd bundle; sha256sum -c MANIFEST.sha256 >/dev/null; sbatch --test-only --array='$array_range' --export=ALL,NADOC_CAMPAIGN_REMOTE_ROOT='$remote_root' --output='$remote_root/logs/%A_%a.out' --error='$remote_root/logs/%A_%a.out' frequency.sbatch; sbatch --parsable --array='$array_range' --export=ALL,NADOC_CAMPAIGN_REMOTE_ROOT='$remote_root' --output='$remote_root/logs/%A_%a.out' --error='$remote_root/logs/%A_%a.out' frequency.sbatch")
job_id=$(printf '%s\n' "$submission" | tail -n 1 | cut -d';' -f1)
[[ "$job_id" =~ ^[0-9]+$ ]] || exit 6
python3 - "$campaign_root" "$job_id" "$remote_root" "$array_range" <<'PY'
from datetime import datetime,timezone
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); record={'schema':'nadoc.photoproduct-alpine-local-fragment-frequency-submission.v1','status':'submitted','gate_effect':'none','simulation_ready':False,'submitted_at':datetime.now(timezone.utc).isoformat(),'slurm_job_id':sys.argv[2],'slurm_array':sys.argv[4],'remote_root':sys.argv[3]}
(root/'submission.json').write_text(json.dumps(record,indent=2)+'\n')
PY
printf '%s\n' "$submission"
ssh -S "$control_socket" "$host" "squeue -j '$job_id' -o '%i|%P|%j|%T|%M|%L|%R'"
systemd-run --user --collect \
  --unit="nadoc-alpine-local-fragment-frequency-watch-$job_id" \
  --property=Restart=no \
  --setenv=ALPINE_HOST="$host" \
  --setenv=ALPINE_CONTROL_SOCKET="$control_socket" \
  "$script_dir/watch_and_collect_frequency.sh" "$campaign_root"
