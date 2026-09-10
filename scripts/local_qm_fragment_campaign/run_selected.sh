#!/usr/bin/env bash
set -euo pipefail

campaign_root="${1:-}"
action="${2:---list}"
case_id="${3:-}"

if [[ -z "$campaign_root" || ! -f "$campaign_root/campaign_manifest.json" ]]; then
  echo "usage: $0 CAMPAIGN_ROOT [--list | --run CASE_ID]" >&2
  exit 2
fi

if [[ "$action" == "--list" ]]; then
  python - "$campaign_root/campaign_manifest.json" <<'PY'
import json
import sys
manifest = json.load(open(sys.argv[1]))
from pathlib import Path
review = Path(sys.argv[1]).with_name('review_preparation.json')
if review.is_file():
    cases = json.loads(review.read_text())['jobs']
    extensions = review.with_name('review_extensions.json')
    if extensions.is_file():
        cases += json.loads(extensions.read_text())['jobs']
    for case in cases:
        print(f"{case['id']}\tstage-{case['stage']}\tbudget {case['wall_hours']:g} h")
    raise SystemExit(0)
for case in manifest["fragment_cases"]:
    hours = case["resources"]["estimated_local_wall_hours"]
    print(f"{case['id']}\t{case['tier']}\t{case['product_id']}\t{hours[0]:g}-{hours[1]:g} h")
PY
  exit 0
fi

if [[ "$action" != "--run" || -z "$case_id" ]]; then
  echo "an exact --run CASE_ID selection is required; no default job is started" >&2
  exit 2
fi

if [[ -f "$campaign_root/review_preparation.json" ]]; then
  exec /home/jojo/Work/NADOC/.venv/bin/python \
    /home/jojo/Work/NADOC/scripts/local_qm_fragment_campaign/run_case.py "$campaign_root" "$case_id"
fi

job_dir="$campaign_root/cases/$case_id/job"
if [[ ! -f "$job_dir/input.dat" || ! -f "$job_dir/job_manifest.json" ]]; then
  echo "unknown or incomplete case: $case_id" >&2
  exit 2
fi
if [[ -e "$job_dir/output.dat" || -e "$job_dir/run_manifest.json" ]]; then
  echo "refusing to overwrite an existing result for $case_id" >&2
  exit 3
fi

psi4_bin="/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4"
if [[ ! -x "$psi4_bin" ]]; then
  echo "Psi4 executable is unavailable at $psi4_bin" >&2
  exit 4
fi

scratch_root="$campaign_root/scratch/$case_id"
mkdir -p "$scratch_root"
nadoc_root="/home/jojo/Work/NADOC"
workflow="$nadoc_root/scripts/photoproduct_workflow.py"
if [[ ! -f "$workflow" ]]; then
  echo "NADOC QM workflow is unavailable at $workflow" >&2
  exit 5
fi
"/home/jojo/miniforge3/envs/nadoc-qm/bin/python" "$workflow" run-qm-job \
  --job-dir "$job_dir" \
  --psi4 "$psi4_bin" \
  --scratch-dir "$scratch_root"
