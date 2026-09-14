#!/usr/bin/env bash
set -euo pipefail

label=${1:?benchmark label required}
parallel=${2:?parallel worker count required}
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
bundle="$remote_root/bundle"
qm_python="$remote_root/envs/nadoc-qm-1.11/bin/python"
work_root="$SLURM_SCRATCH/nadoc-qm-$label"
case_root="$work_root/case"
result_root="$remote_root/results/$label/$SLURM_JOB_ID"
task_count=128
threads=2
memory_gib=3

if [[ ! -x "$qm_python" ]]; then
  echo "Pinned QM environment is absent; submit setup_env.sbatch first" >&2
  exit 3
fi
if [[ -e "$result_root" ]]; then
  echo "Refusing to overwrite result root: $result_root" >&2
  exit 4
fi

mkdir -p "$work_root" "$result_root"
rsync -a "$bundle/case/" "$case_root/"
plan="$case_root/distributed/distributed_hessian_plan.json"
export PYTHONPATH="$bundle/nadoc"
export OMP_MAX_ACTIVE_LEVELS=1
export OPENBLAS_NUM_THREADS="$threads"

sync_results() {
  rsync -a "$case_root/" "$result_root/case/" 2>/dev/null || true
}
trap sync_results EXIT

mapfile -t tasks < <("$qm_python" -c \
  'import json,sys; p=json.load(open(sys.argv[1])); print("\n".join(x["id"] for x in p["tasks"][:int(sys.argv[2])]))' \
  "$plan" "$task_count")
if [[ ${#tasks[@]} -ne $task_count ]]; then
  echo "Expected $task_count tasks, found ${#tasks[@]}" >&2
  exit 5
fi

export qm_python plan case_root threads memory_gib
run_one() {
  task_id=$1
  task_scratch="$SLURM_SCRATCH/psi4-$task_id"
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

started_ns=$(date +%s%N)
printf '%s\0' "${tasks[@]}" \
  | xargs -0 -n 1 -P "$parallel" bash -c 'run_one "$1"' _
finished_ns=$(date +%s%N)

"$qm_python" "$bundle/summarize_benchmark" \
  "$plan" "$result_root/benchmark_report.json" "$label" "$parallel" \
  "$task_count" "$started_ns" "$finished_ns"
sync_results
trap - EXIT
echo "Benchmark complete: $result_root/benchmark_report.json"
