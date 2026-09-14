#!/usr/bin/env bash
set -euo pipefail

remote_root=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-policy-2.1.0-v1
bundle="$remote_root/bundle"
qm_python=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/nadoc-qm-1.11/bin/python
parallel=32
threads=2
memory_gib=3

if [[ ! -x "$qm_python" ]]; then
  echo "Pinned Alpine QM environment is absent: $qm_python" >&2
  exit 3
fi
if [[ -z "${SLURM_ARRAY_TASK_ID:-}" || -z "${SLURM_JOB_ID:-}" ]]; then
  echo "This runner must be launched as a Slurm array task" >&2
  exit 4
fi

line=$(awk -F '\t' -v target="$SLURM_ARRAY_TASK_ID" '$1 == target {print; found=1} END {if (!found) exit 1}' "$bundle/cases.tsv")
IFS=$'\t' read -r index product conformer task_count expected_plan_sha <<< "$line"
source_case="$bundle/cases/$product/$conformer"
work_root="$SLURM_SCRATCH/nadoc-cpd-qm-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
case_root="$work_root/case"
result_root="$remote_root/results/$product/$conformer/${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
plan="$case_root/distributed/distributed_hessian_plan.json"

if [[ -e "$result_root" ]]; then
  echo "Refusing to overwrite result root: $result_root" >&2
  exit 5
fi
mkdir -p "$work_root" "$result_root"
rsync -a "$source_case/" "$case_root/"

observed_plan_sha=$(sha256sum "$plan" | awk '{print $1}')
if [[ "$observed_plan_sha" != "$expected_plan_sha" ]]; then
  echo "Plan hash changed for $product $conformer" >&2
  exit 6
fi

export PYTHONPATH="$bundle/nadoc"
export OMP_MAX_ACTIVE_LEVELS=1
export OPENBLAS_NUM_THREADS="$threads"

sync_results() {
  rsync -a "$case_root/" "$result_root/case/" 2>/dev/null || true
}
trap sync_results EXIT

mapfile -t tasks < <("$qm_python" -c \
  'import json,sys; p=json.load(open(sys.argv[1])); print("\n".join(x["id"] for x in p["tasks"]))' \
  "$plan")
if [[ ${#tasks[@]} -ne "$task_count" ]]; then
  echo "Expected $task_count tasks, found ${#tasks[@]}" >&2
  exit 7
fi

export qm_python plan case_root threads memory_gib
run_one() {
  task_id=$1
  task_scratch="$SLURM_SCRATCH/psi4-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}-$task_id"
  mkdir -p "$task_scratch"
  cd "$task_scratch"
  "$qm_python" -m backend.parameterization.photoproduct_distributed_hessian \
    run-task \
    --plan "$plan" \
    --task-id "$task_id" \
    --scratch-dir "$task_scratch" \
    --threads "$threads" \
    --memory-gib "$memory_gib"
}
export -f run_one

started_epoch=$(date +%s)
printf '%s\0' "${tasks[@]}" \
  | xargs -0 -n 1 -P "$parallel" bash -c 'run_one "$1"' _
finished_epoch=$(date +%s)

# The receipt reads the durable result copy, so synchronize the completed task tree
# before validating it.  The EXIT trap remains as a crash-safe fallback.
sync_results

export result_root product conformer task_count expected_plan_sha started_epoch finished_epoch
"$qm_python" - <<'PY'
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["result_root"])
case = root / "case"
plan_path = case / "distributed/distributed_hessian_plan.json"
plan = json.loads(plan_path.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
records = []
for task in plan["tasks"]:
    result = case / "distributed" / task["result"]["path"]
    run = case / "distributed" / task["run_record"]["path"]
    if not result.is_file() or not run.is_file():
        raise SystemExit(f"incomplete task pair: {task['id']}")
    payload = json.loads(run.read_text())
    if payload.get("status") != "completed_unreviewed" or payload.get("plan_sha256") != sha(plan_path):
        raise SystemExit(f"invalid task receipt: {task['id']}")
    records.append({"task_id": task["id"], "result_sha256": sha(result), "run_sha256": sha(run)})
report = {
    "schema": "nadoc.photoproduct-alpine-qm-case.v1",
    "status": "completed_unreviewed",
    "gate_effect": "none",
    "simulation_ready": False,
    "product_id": os.environ["product"],
    "conformer_id": os.environ["conformer"],
    "task_count": int(os.environ["task_count"]),
    "plan_sha256": os.environ["expected_plan_sha"],
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "node": os.environ.get("SLURMD_NODENAME"),
        "cpus_per_task": int(os.environ.get("SLURM_CPUS_PER_TASK", "0")),
    },
    "started_epoch": int(os.environ["started_epoch"]),
    "finished_epoch": int(os.environ["finished_epoch"]),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "tasks": records,
    "interpretation": "Complete unreviewed QCSchema task pairs; local assembly and scientific gates remain required.",
}
(root / "case_completion.json").write_text(json.dumps(report, indent=2) + "\n")
PY

sync_results
trap - EXIT
echo "Completed $product $conformer at $result_root"
