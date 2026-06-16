#!/usr/bin/env bash
# Cycle 4 — NaCl dose-response ladder (0 / 50 / 150 / 300 mM) on 2hb_2xT.
#
# Tests whether electrostatic screening is the DOMINANT melt lever (k=0 C1' keeps
# climbing with salt) or ONE OF TWO global contributors (k=0 plateaus near ~44).
# All arms share the canonical baseline recipe so [NaCl] is the only variable:
#   min 24000, ladder 0.5,0.1,0.01,0, 0.3 ns/stage, 12.5 mM Mg held constant.
#
# Already in RESULTS.tsv — do NOT rerun:
#   0   mM = longmin_24000   (k=0 C1' = 20.0)
#   150 mM = salt150_min24k  (k=0 C1' = 44.2)
# This script fills the two missing points: 50 and 300 mM.
#
# Runs SEQUENTIALLY — keep one NAMD on the GPU at a time (RTX 3080 Ti). Launch
# with:  nohup bash experiments/exp29_md_prep_relaxation/scripts/run_salt_ladder.sh \
#          > experiments/exp29_md_prep_relaxation/runs/salt_ladder.console.log 2>&1 &
set -euo pipefail
cd /home/jojo/Work/NADOC
export PATH="$HOME/.local/bin:$PATH"

RUN=experiments/exp29_md_prep_relaxation/run_cycle.py
OUT=experiments/exp29_md_prep_relaxation/runs

run_arm () {
  local mM="$1" label="$2"
  echo "=== salt ladder arm: ${mM} mM NaCl  (label=${label}) ==="
  # Guard: don't relaunch onto a busy GPU.
  until ! nvidia-smi --query-compute-apps=process_name --format=csv,noheader 2>/dev/null | grep -qi namd; do
    echo "  GPU busy with a NAMD job; waiting 30s..."; sleep 30
  done
  python3 "$RUN" --label "$label" \
    --minimize-steps 24000 --stage-ns 0.3 --k-ladder 0.5,0.1,0.01,0 \
    --ion-conc-mM "$mM" \
    --notes "Cycle 4 salt ladder: ${mM} mM NaCl on 12.5 mM Mg; baseline recipe; decision=C1' at k=0 dose-response" \
    > "${OUT}/${label}.console.log" 2>&1
  echo "  --> ${label} done:"
  tail -1 "${OUT}/${label}.console.log"
}

run_arm 50  salt050_min24k
run_arm 300 salt300_min24k

echo "=== salt ladder complete — full dose-response ==="
grep -E "longmin_24000|salt050|salt150|salt300" experiments/exp29_md_prep_relaxation/RESULTS.tsv
