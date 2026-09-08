#!/usr/bin/env bash
set -euo pipefail

remote_root=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-water-v1}
bundle="$remote_root/bundle"
psi4=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/nadoc-qm-1.11/bin/psi4
parallel=16

if [[ ! -x "$psi4" ]]; then
  echo "Pinned Alpine Psi4 is absent: $psi4" >&2
  exit 3
fi
line=$(awk -F '\t' -v target="${SLURM_ARRAY_TASK_ID:?}" '$1 == target {print; found=1} END {if (!found) exit 1}' "$bundle/cases.tsv")
IFS=$'\t' read -r index product job_count expected_case_sha <<< "$line"
source_case="$bundle/cases/$product"
work_root="$SLURM_SCRATCH/nadoc-cpd-water-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
case_root="$work_root/case"
result_root="$remote_root/results/$product/${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"

if [[ -e "$result_root" ]]; then
  echo "Refusing to overwrite result root: $result_root" >&2
  exit 4
fi
mkdir -p "$work_root" "$result_root"
rsync -a "$source_case/" "$case_root/"
observed_case_sha=$(sha256sum "$case_root/case_manifest.json" | awk '{print $1}')
if [[ "$observed_case_sha" != "$expected_case_sha" ]]; then
  echo "Case manifest hash changed for $product" >&2
  exit 5
fi

sync_results() {
  rsync -a "$case_root/" "$result_root/case/" 2>/dev/null || true
}
trap sync_results EXIT

mapfile -t jobs < <(find "$case_root/series" -mindepth 3 -maxdepth 3 -name job_manifest.json -printf '%h\n' | sort)
if [[ ${#jobs[@]} -ne "$job_count" ]]; then
  echo "Expected $job_count jobs, found ${#jobs[@]}" >&2
  exit 6
fi
export psi4
run_one() {
  job_dir=$1
  scratch="$SLURM_SCRATCH/psi4-water-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}-$(basename "$(dirname "$job_dir")")-$(basename "$job_dir")"
  mkdir -p "$scratch"
  export PSI_SCRATCH="$scratch"
  cd "$job_dir"
  "$psi4" input.dat output.dat
  grep -q 'NADOC_WATER_INTERACTION_KCAL_MOL' output.dat
  grep -q 'Psi4 exiting successfully' output.dat
}
export -f run_one

started_epoch=$(date +%s)
printf '%s\0' "${jobs[@]}" | xargs -0 -n 1 -P "$parallel" bash -c 'run_one "$1"' _
finished_epoch=$(date +%s)
sync_results

export result_root product job_count expected_case_sha started_epoch finished_epoch
python3 - <<'PY'
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["result_root"])
case = root / "case"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
source = json.loads((case / "case_manifest.json").read_text())
records = []
for job in source["jobs"]:
    job_dir = case / job["relative_job_dir"]
    manifest = job_dir / "job_manifest.json"
    input_path = job_dir / "input.dat"
    output = job_dir / "output.dat"
    if sha(manifest) != job["job_manifest_sha256"] or sha(input_path) != job["input_sha256"]:
        raise SystemExit("input provenance changed: %s" % job["relative_job_dir"])
    text = output.read_text(errors="replace") if output.is_file() else ""
    if "Psi4 exiting successfully" not in text or "NADOC_WATER_INTERACTION_KCAL_MOL" not in text:
        raise SystemExit("incomplete water result: %s" % job["relative_job_dir"])
    records.append({"relative_job_dir": job["relative_job_dir"], "output_sha256": sha(output)})
report = {
    "schema": "nadoc.photoproduct-alpine-water-case-completion.v1",
    "status": "completed_unreviewed",
    "gate_effect": "none",
    "simulation_ready": False,
    "product_id": os.environ["product"],
    "job_count": int(os.environ["job_count"]),
    "case_manifest_sha256": os.environ["expected_case_sha"],
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "node": os.environ.get("SLURMD_NODENAME"),
        "cpus_per_task": int(os.environ.get("SLURM_CPUS_PER_TASK", "0")),
    },
    "started_epoch": int(os.environ["started_epoch"]),
    "finished_epoch": int(os.environ["finished_epoch"]),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "outputs": records,
}
(root / "case_completion.json").write_text(json.dumps(report, indent=2) + "\n")
PY

sync_results
trap - EXIT
echo "Completed $product at $result_root"
