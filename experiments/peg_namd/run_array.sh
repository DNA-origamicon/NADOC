#!/usr/bin/env bash
# Submit with site-specific sbatch resource flags; this script never submits itself.
# JOB_LIST contains absolute paths to STAGED, BUILT and SEALED case directories.
set -euo pipefail
: "${JOB_LIST:?Set JOB_LIST to a text file with one package path per line}"
: "${NAMD_BIN:?Set NAMD_BIN to the target node binary}"
: "${SLURM_ARRAY_TASK_ID:?This entry point expects a Slurm array}"
[[ "$SLURM_ARRAY_TASK_ID" =~ ^[0-9]+$ ]] || exit 2
case_dir=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$JOB_LIST")
[[ -d "$case_dir" ]] || { echo "Missing package for array index" >&2; exit 1; }
# Prefer scheduler-visible device IDs; never hard-code a physical GPU outside allocation.
export NAMD_DEVICES=${NAMD_DEVICES:-0}
export NAMD_THREADS=${NAMD_THREADS:-4}
bash "$case_dir/run.sh" "${PEG_STAGE:-benchmark}"
