#!/usr/bin/env bash
set -euo pipefail

job_id=${1:?Slurm array job ID required}
repository=${2:-/home/jojo/Work/NADOC}
host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
control_socket=${ALPINE_CONTROL_SOCKET:-/tmp/nadoc-alpine-$(id -u)/control.sock}
storage=/media/jojo/Archive/NADOC_archive
campaign_root="$storage/photoproduct_evidence/alpine-qm-campaign-policy-2.1.0-v1"
remote_root=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-policy-2.1.0-v1
download_root="$campaign_root/remote-results"
work_root="$storage/photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/fixed-geometry-qm-v2.1.0"
scratch_root="$storage/photoproduct_evidence/tt-cpd-work-v1-completions/qm-scratch-policy-2.1.0"
qm_python=/home/jojo/miniforge3/envs/nadoc-qm/bin/python
log="$campaign_root/watch-and-collect.log"

exec >>"$log" 2>&1
echo "watch started $(date --iso-8601=seconds) job=$job_id"

while true; do
  if ! ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1; then
    echo "Alpine control connection unavailable at $(date --iso-8601=seconds)"
    exit 3
  fi
  active=$(ssh -S "$control_socket" "$host" "squeue -h -j '$job_id' | wc -l")
  echo "$(date --iso-8601=seconds) active_squeue_rows=$active"
  if [[ "$active" -eq 0 ]]; then
    accounting=$(ssh -S "$control_socket" "$host" \
      "sacct -X -n -P -j '$job_id' -o JobID,State,ExitCode")
    printf '%s\n' "$accounting" > "$campaign_root/slurm-accounting.txt"
    if python3 - "$job_id" "$campaign_root/slurm-accounting.txt" <<'PY'
import re
import sys

job = sys.argv[1]
rows = []
for line in open(sys.argv[2]):
    fields = line.strip().split("|")
    if len(fields) >= 3 and re.fullmatch(re.escape(job) + r"_\d+", fields[0]):
        rows.append(fields)
if len(rows) != 24:
    raise SystemExit(2)
bad = [row for row in rows if not row[1].startswith("COMPLETED") or row[2] != "0:0"]
if bad:
    print("non-complete array elements:", bad)
    raise SystemExit(1)
PY
    then
      break
    else
      status=$?
      if [[ "$status" -eq 1 ]]; then
        echo "array has terminal failures; fetching results for strict task-pair recovery"
        break
      fi
    fi
  fi
  sleep 60
done

echo "all 24 array elements are terminal; fetching results"
mkdir -p "$download_root"
rsync -az --partial -e "ssh -S $control_socket" \
  "$host:$remote_root/results/" "$download_root/"

"$repository/.venv/bin/python" \
  "$repository/scripts/alpine_qm_campaign/repair_case_completions.py" \
  --campaign-manifest "$campaign_root/bundle/campaign_manifest.json" \
  --results-root "$download_root" \
  --output "$campaign_root/receipt-repair-report.json"

"$repository/.venv/bin/python" "$repository/scripts/alpine_qm_campaign/collect_campaign.py" \
  --campaign-manifest "$campaign_root/bundle/campaign_manifest.json" \
  --remote-results-root "$download_root" \
  --work-root "$work_root" \
  --output "$campaign_root/import-report.json"

products=(
  tt-cpd-cis-syn-ii
  tt-cpd-trans-syn-ii
  tt-cpd-cis-anti-i
  tt-cpd-cis-anti-ii
  tt-cpd-trans-anti-i
  tt-cpd-trans-anti-ii
)
for product in "${products[@]}"; do
  for conformer in 001 002 003 004; do
    case_dir="$work_root/$product/conformer-$conformer"
    "$qm_python" "$repository/scripts/run_local_photoproduct_response.py" \
      --plan "$case_dir/distributed/distributed_hessian_plan.json" \
      --job-dir "$case_dir/job" \
      --scratch-root "$scratch_root/$product-$conformer" \
      --output "$case_dir/local-batch-report-v2.1.0.json" \
      --qm-python "$qm_python" --max-parallel 1 --threads 2 --memory-gib 3 \
      --storage-root "$storage"
  done
done

python3 - "$work_root" "$campaign_root/assembled-campaign-report.json" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
output = Path(sys.argv[2])
products = [
    "tt-cpd-cis-syn-ii", "tt-cpd-trans-syn-ii", "tt-cpd-cis-anti-i",
    "tt-cpd-cis-anti-ii", "tt-cpd-trans-anti-i", "tt-cpd-trans-anti-ii",
]
records = []
for product in products:
    conformers = []
    for suffix in ("001", "002", "003", "004"):
        path = root / product / f"conformer-{suffix}/local-batch-report-v2.1.0.json"
        payload = json.loads(path.read_text())
        if payload.get("status") != "passed":
            raise SystemExit(f"response assembly did not pass: {path}")
        conformers.append({
            "conformer_id": f"conformer-{suffix}",
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    records.append({"product_id": product, "conformers": conformers})
report = {
    "schema": "nadoc.photoproduct-alpine-qm-assembled-campaign.v1",
    "status": "passed",
    "gate_effect": "none",
    "simulation_ready": False,
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "product_count": len(records),
    "conformer_count": sum(len(item["conformers"]) for item in records),
    "products": records,
}
output.write_text(json.dumps(report, indent=2) + "\n")
PY

echo "watch completed $(date --iso-8601=seconds)"
