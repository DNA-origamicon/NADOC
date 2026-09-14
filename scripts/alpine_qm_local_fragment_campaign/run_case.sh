#!/usr/bin/env bash
set -euo pipefail

remote_root=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-local-fragment-continuation-v1}
bundle="$remote_root/bundle"
psi4=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/nadoc-qm-1.11/bin/psi4
line=$(awk -F '\t' -v target="${SLURM_ARRAY_TASK_ID:?}" '$1 == target {print; found=1} END {if (!found) exit 1}' "$bundle/frequency_cases.tsv")
IFS=$'\t' read -r index case_id expected_case_sha <<< "$line"
source_case="$bundle/frequency-cases/$case_id"
work_root="$SLURM_SCRATCH/nadoc-local-fragment-frequency-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
case_root="$work_root/case"
job_dir="$case_root/job"
result_root="$remote_root/results/$case_id/${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
[[ -x "$psi4" ]] || { echo "Pinned Alpine Psi4 is absent: $psi4" >&2; exit 3; }
[[ ! -e "$result_root" ]] || { echo "Refusing to overwrite $result_root" >&2; exit 4; }
mkdir -p "$work_root" "$result_root"
rsync -a "$source_case/" "$case_root/"
[[ $(sha256sum "$case_root/case_manifest.json" | awk '{print $1}') == "$expected_case_sha" ]] || exit 5
readarray -t expected < <(python3 - "$case_root/case_manifest.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
print(p['job_manifest_sha256'])
print(p['input_sha256'])
print(p['provenance_sha256'])
PY
)
[[ $(sha256sum "$job_dir/job_manifest.json" | awk '{print $1}') == "${expected[0]}" ]] || exit 6
[[ $(sha256sum "$job_dir/input.dat" | awk '{print $1}') == "${expected[1]}" ]] || exit 7
[[ $(sha256sum "$job_dir/frequency_job_provenance.json" | awk '{print $1}') == "${expected[2]}" ]] || exit 8

sync_results() { rsync -a "$case_root/" "$result_root/case/" 2>/dev/null || true; }
sync_loop() { while true; do sleep 600; sync_results; done; }
sync_results
sync_loop &
sync_pid=$!
cleanup() { kill "$sync_pid" 2>/dev/null || true; wait "$sync_pid" 2>/dev/null || true; sync_results; }
trap cleanup EXIT
trap sync_results USR1
export PSI_SCRATCH="$SLURM_SCRATCH/psi4-local-fragment-frequency-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
mkdir -p "$PSI_SCRATCH"
started_epoch=$(date +%s)
set +e
(cd "$job_dir" && "$psi4" input.dat output.dat)
returncode=$?
set -e
finished_epoch=$(date +%s)
cleanup
trap - EXIT USR1
export result_root case_id expected_case_sha started_epoch finished_epoch returncode
python3 - <<'PY'
from datetime import datetime, timezone
import hashlib,json,os
from pathlib import Path
root=Path(os.environ['result_root']); job=root/'case/job'; sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
text=(job/'output.dat').read_text(errors='replace') if (job/'output.dat').is_file() else ''
required=('output.dat','hessian_hartree_per_bohr2.txt')
success=int(os.environ['returncode'])==0 and 'Psi4 exiting successfully' in text and all((job/x).is_file() for x in required)
outputs={name:{'sha256':sha(job/name),'bytes':(job/name).stat().st_size} for name in required if (job/name).is_file()}
report={'schema':'nadoc.photoproduct-alpine-local-fragment-frequency-case-completion.v1','status':'completed_unreviewed' if success else 'failed_preserved','gate_effect':'none','simulation_ready':False,'id':os.environ['case_id'],'case_manifest_sha256':os.environ['expected_case_sha'],'returncode':int(os.environ['returncode']),'slurm':{'job_id':os.environ.get('SLURM_JOB_ID'),'array_task_id':os.environ.get('SLURM_ARRAY_TASK_ID'),'node':os.environ.get('SLURMD_NODENAME'),'cpus_per_task':int(os.environ.get('SLURM_CPUS_PER_TASK','0'))},'started_epoch':int(os.environ['started_epoch']),'finished_epoch':int(os.environ['finished_epoch']),'finished_at':datetime.now(timezone.utc).isoformat(),'outputs':outputs}
(root/'case_completion.json').write_text(json.dumps(report,indent=2)+'\n')
PY
sync_results
if [[ "$returncode" -ne 0 ]]; then exit "$returncode"; fi
grep -q 'Psi4 exiting successfully' "$job_dir/output.dat"
[[ -f "$job_dir/hessian_hartree_per_bohr2.txt" ]]
echo "Completed $case_id at $result_root"
