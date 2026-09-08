#!/usr/bin/env bash
set -euo pipefail

remote_root=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-recovery-v2r1}
bundle="$remote_root/bundle"
psi4=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/nadoc-qm-1.11/bin/psi4

line=$(awk -F '\t' -v target="${SLURM_ARRAY_TASK_ID:?}" '$1 == target {print; found=1} END {if (!found) exit 1}' "$bundle/cases.tsv")
IFS=$'\t' read -r index product expected_case_sha <<< "$line"
source_case="$bundle/cases/$product"
work_root="$SLURM_SCRATCH/nadoc-cpd-recovery-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
case_root="$work_root/case"
job_dir="$case_root/job"
result_root="$remote_root/results/$product/${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
[[ -x "$psi4" ]] || { echo "Pinned Alpine Psi4 is absent: $psi4" >&2; exit 3; }
[[ ! -e "$result_root" ]] || { echo "Refusing to overwrite $result_root" >&2; exit 4; }
mkdir -p "$work_root" "$result_root"
rsync -a "$source_case/" "$case_root/"
[[ $(sha256sum "$case_root/case_manifest.json" | awk '{print $1}') == "$expected_case_sha" ]] || exit 5

readarray -t expected < <(python3 - "$case_root/case_manifest.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1])); print(p['job_manifest_sha256']); print(p['input_sha256'])
PY
)
[[ $(sha256sum "$job_dir/job_manifest.json" | awk '{print $1}') == "${expected[0]}" ]] || exit 6
[[ $(sha256sum "$job_dir/input.dat" | awk '{print $1}') == "${expected[1]}" ]] || exit 7

sync_results() {
  rsync -a --partial --inplace "$case_root/" "$result_root/case/" 2>/dev/null || true
}
checkpoint_and_sync() {
  if [[ -s "$job_dir/output.dat" ]]; then
    python3 "$bundle/extract_checkpoint.py" "$job_dir" 2>/dev/null || true
  fi
  sync_results
}
checkpoint_loop() {
  while sleep 600; do checkpoint_and_sync; done
}
on_signal() {
  checkpoint_and_sync
  if [[ -n "${psi_pid:-}" ]]; then kill -TERM "$psi_pid" 2>/dev/null || true; fi
}
on_exit() {
  if [[ -n "${checkpoint_pid:-}" ]]; then kill "$checkpoint_pid" 2>/dev/null || true; fi
  checkpoint_and_sync
}
trap on_exit EXIT
trap on_signal USR1 TERM
export PSI_SCRATCH="$SLURM_SCRATCH/psi4-recovery-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
mkdir -p "$PSI_SCRATCH"
started_epoch=$(date +%s)
checkpoint_loop &
checkpoint_pid=$!
set +e
(cd "$job_dir" && exec "$psi4" input.dat output.dat) &
psi_pid=$!
wait "$psi_pid"
returncode=$?
set -e
finished_epoch=$(date +%s)
kill "$checkpoint_pid" 2>/dev/null || true
checkpoint_pid=
checkpoint_and_sync

export result_root product expected_case_sha started_epoch finished_epoch returncode
python3 - <<'PY'
from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
root=Path(os.environ['result_root']); case=root/'case'; job=case/'job'
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
text=(job/'output.dat').read_text(errors='replace') if (job/'output.dat').is_file() else ''
complete=any(marker in text for marker in ('Optimization is complete','Optimizer: Optimization complete','Final optimized geometry and variables'))
success=(int(os.environ['returncode']) == 0 and 'Psi4 exiting successfully' in text and complete and (job/'optimized.xyz').is_file())
outputs={}
for name in ('output.dat','optimized.xyz','checkpoint_latest.xyz','checkpoint_latest.json'):
    path=job/name
    if path.is_file(): outputs[name]={'sha256':sha(path),'bytes':path.stat().st_size}
report={'schema':'nadoc.photoproduct-alpine-boundary-recovery-case-completion.v1','status':'completed_unreviewed' if success else 'failed_preserved','gate_effect':'none','simulation_ready':False,'product_id':os.environ['product'],'case_manifest_sha256':os.environ['expected_case_sha'],'returncode':int(os.environ['returncode']),'slurm':{'job_id':os.environ.get('SLURM_JOB_ID'),'array_task_id':os.environ.get('SLURM_ARRAY_TASK_ID'),'node':os.environ.get('SLURMD_NODENAME'),'cpus_per_task':int(os.environ.get('SLURM_CPUS_PER_TASK','0'))},'started_epoch':int(os.environ['started_epoch']),'finished_epoch':int(os.environ['finished_epoch']),'finished_at':datetime.now(timezone.utc).isoformat(),'outputs':outputs}
(root/'case_completion.json').write_text(json.dumps(report,indent=2)+'\n')
PY
sync_results
trap - EXIT
on_exit
if [[ "$returncode" -ne 0 ]]; then exit "$returncode"; fi
grep -q 'Psi4 exiting successfully' "$job_dir/output.dat"
grep -Eq 'Optimization is complete|Optimizer: Optimization complete|Final optimized geometry and variables' "$job_dir/output.dat"
[[ -f "$job_dir/optimized.xyz" ]]
echo "Completed $product at $result_root"
