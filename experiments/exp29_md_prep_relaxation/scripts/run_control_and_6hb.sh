#!/usr/bin/env bash
# Cycle 5 — (1) non-strained control discriminator, (2) 6hb "based on learnings".
#
# Arm 1 — control_50mM: 2hb_control.nadoc (NO forced ligation, NO 2xT — strain
#   sources removed, replaced by a normal crossover) through the same ladder at
#   50 mM NaCl. Discriminator:
#     k=0 C1' clears ~0.90  -> residual melt is SPECIFIC to the strain sources
#     k=0 C1' also plateaus  -> residual is GENERIC ENM-template-vs-CHARMM36 mismatch
#   NB: control has no ss bases -> declash does NOT auto-enable (standard 2 fs
#   integrator). That is the correct/natural path for a non-strained design.
#
# Arm 2 — 6hb_salt50_min24k: the real strained 6hb_2xT.nadoc with the only settled
#   win folded in (+50 mM NaCl) + the free defaults (min 24k, robust 0.5->0.01 ENM
#   range, declash auto-on, NO expansion). Confirms whether the electrostatic fix
#   transfers from the 2hb proxy to the real structure. (Fast 0.3 ns/stage harness
#   read; full 4.8 ns production validation is a separate longer run.)
#
# Sequential — one NAMD on the GPU at a time. Launch:
#   nohup bash experiments/exp29_md_prep_relaxation/scripts/run_control_and_6hb.sh \
#     > experiments/exp29_md_prep_relaxation/runs/control_and_6hb.console.log 2>&1 &
set -euo pipefail
cd /home/jojo/Work/NADOC
export PATH="$HOME/.local/bin:$PATH"

RUN=experiments/exp29_md_prep_relaxation/run_cycle.py
OUT=experiments/exp29_md_prep_relaxation/runs

run_arm () {
  local label="$1" design="$2" notes="$3"
  echo "=== ${label} (design=${design}) ==="
  until ! nvidia-smi --query-compute-apps=process_name --format=csv,noheader 2>/dev/null | grep -qi namd; do
    echo "  GPU busy with NAMD; waiting 30s..."; sleep 30
  done
  python3 "$RUN" --label "$label" --design "workspace/${design}" \
    --minimize-steps 24000 --stage-ns 0.3 --k-ladder 0.5,0.1,0.01,0 \
    --ion-conc-mM 50 \
    --notes "$notes" \
    > "${OUT}/${label}.console.log" 2>&1
  echo "  --> ${label} done:"; tail -1 "${OUT}/${label}.console.log"
}

run_arm control_50mM 2hb_control.nadoc \
  "Cycle 5 control: non-strained 2hb (no FL, no 2xT) @50mM NaCl; discriminator for the non-electrostatic residual"

run_arm 6hb_salt50_min24k 6hb_2xT.nadoc \
  "Cycle 5 6hb 'based on learnings': real strained 6hb_2xT @50mM NaCl, min24k, declash auto, no expansion; does the electrostatic fix transfer"

echo "=== Cycle 5 complete ==="
grep -E "control_50mM|6hb_salt50_min24k|longmin_24000|salt050" experiments/exp29_md_prep_relaxation/RESULTS.tsv
