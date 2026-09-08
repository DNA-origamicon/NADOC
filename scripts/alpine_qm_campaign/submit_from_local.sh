#!/usr/bin/env bash
set -euo pipefail

host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
control_socket=${ALPINE_CONTROL_SOCKET:-/tmp/nadoc-alpine-$(id -u)/control.sock}
archive_root=${1:-/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-campaign-policy-2.1.0-v1}
archive="$archive_root/alpine-qm-campaign-policy-2.1.0-v1.tar.gz"
checksum="$archive.sha256"
remote_root=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-policy-2.1.0-v1

if [[ ! -f "$archive" || ! -f "$checksum" ]]; then
  echo "Campaign archive or checksum is missing under $archive_root" >&2
  exit 2
fi
if ! ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1; then
  echo "Reusable Alpine SSH connection is unavailable: $control_socket" >&2
  exit 3
fi

ssh -S "$control_socket" "$host" "
  set -e
  if [ -e '$remote_root/bundle' ] || [ -e '$remote_root/submission.json' ]; then
    echo 'Refusing to overwrite existing remote campaign' >&2
    exit 4
  fi
  mkdir -p '$remote_root/logs'
"
scp -o ControlPath="$control_socket" "$archive" "$checksum" "$host:$remote_root/"

submission=$(ssh -S "$control_socket" "$host" "
  set -euo pipefail
  cd '$remote_root'
  sha256sum -c '$(basename "$checksum")'
  tar -xzf '$(basename "$archive")'
  cd bundle
  sha256sum -c MANIFEST.sha256 >/dev/null
  sbatch --test-only campaign_64.sbatch
  sbatch --parsable campaign_64.sbatch
")
job_id=$(printf '%s\n' "$submission" | tail -n 1 | cut -d';' -f1)
if [[ ! "$job_id" =~ ^[0-9]+$ ]]; then
  echo "Could not parse Slurm job ID from: $submission" >&2
  exit 5
fi

python3 - "$archive_root" "$job_id" "$remote_root" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
record = {
    "schema": "nadoc.photoproduct-alpine-qm-submission.v1",
    "status": "submitted",
    "gate_effect": "none",
    "simulation_ready": False,
    "submitted_at": datetime.now(timezone.utc).isoformat(),
    "slurm_job_id": sys.argv[2],
    "slurm_array": "0-23",
    "remote_root": sys.argv[3],
}
(root / "submission.json").write_text(json.dumps(record, indent=2) + "\n")
PY

printf '%s\n' "$submission"
ssh -S "$control_socket" "$host" \
  "squeue -j '$job_id' -o '%i|%P|%j|%T|%M|%L|%R'"
