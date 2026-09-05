#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
case "${1:-baseline}" in
  baseline|margin4|margin6|offload|relax2fs|enm_control) variant="${1:-baseline}" ;;
  *) echo 'Unknown replay variant' >&2; exit 2 ;;
esac
run_dir="experiments/namd_32089399_diagnosis/$variant"
if [[ -e "$run_dir/replay.xst" ]]; then
  echo 'Replay output already exists; preserve it before preparing another trial.' >&2
  exit 2
fi
bash scripts/test_guard.sh "namd-exclusion-$variant" 0 1 -- \
  /home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3 \
  +p4 +devices 0 "$run_dir/replay.conf" > "$run_dir/run.log" 2>&1
