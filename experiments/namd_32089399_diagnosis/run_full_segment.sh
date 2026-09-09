#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
experiment="$PWD/experiments/namd_32089399_diagnosis"
segment=small_plate_03_300K_NPT_ENM_k0p01_p10
if [[ -e "$experiment/recovery_package/output/$segment.xst" ]]; then
  echo 'Existing continuation output must be preserved before another run.' >&2
  exit 2
fi
bash scripts/test_guard.sh namd-wall-full-segment 0 1 -- bash -c \
  'cd "$1"; exec "$2" +p4 +devices 0 "$3"' _ \
  "$experiment/recovery_package" \
  /home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3 \
  "$segment.conf" > "$experiment/recovery_package/output/$segment.log" 2>&1
