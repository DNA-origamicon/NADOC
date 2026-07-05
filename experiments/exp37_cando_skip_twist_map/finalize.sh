#!/usr/bin/env bash
# exp37 trigger: fires when the stage-1 FINE map is complete, then
#   1. analyze.py  → SUMMARY.md, optimize.csv, optimized_marks.json (verified joint optimum)
#   2. plot.py     → results/exp37_summary.png
#   3. if the verified optimum still misses |twist|<1°, launch stage2.py (fine fractional map)
#      then re-plot; else stop.
#   4. write DECISION.md
set -u
cd /home/joshua/NADOC
DIR=experiments/exp37_cando_skip_twist_map
RES=$DIR/results
ENVV="OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=."
UV="$HOME/.local/bin/uv"
EXPECT=252

rows() {  # attempted rows across both CSVs (lines minus header), resume-proof
  python3 - "$RES" <<'PY'
import csv,os,sys
res=sys.argv[1]; n=0
for f in ("uniform.csv","axes.csv"):
    p=os.path.join(res,f)
    if os.path.isfile(p):
        with open(p) as fh: n+=max(0,sum(1 for _ in fh)-1)
print(n)
PY
}

echo "[finalize $(date +%T)] waiting for stage-1 map ($EXPECT solves)…"
while true; do
  r=$(rows 2>/dev/null || echo 0)
  if [ "$r" -ge "$EXPECT" ] || grep -q "SWEEP COMPLETE\|nothing to do" "$RES/sweep.log" 2>/dev/null; then
    if [ "$r" -ge "$EXPECT" ]; then break; fi
  fi
  sleep 30
done
echo "[finalize $(date +%T)] stage-1 complete ($r rows) — analyzing"

eval $ENVV "$UV" run python $DIR/analyze.py 2>&1 | tee $RES/analyze.log
eval $ENVV "$UV" run python $DIR/plot.py   2>&1 | tee -a $RES/analyze.log

TW=$(python3 -c "import json;print(abs(float(json.load(open('$RES/optimized_marks.json'))['twist_deg'])))" 2>/dev/null || echo 999)
echo "[finalize $(date +%T)] stage-1 optimum |twist| = ${TW}°"

STAGE2="not needed (stage-1 optimum already < 1°)"
if python3 -c "import sys;sys.exit(0 if float('$TW')>=1.0 else 1)"; then
  echo "[finalize $(date +%T)] |twist| >= 1° — launching stage-2 fine map"
  eval $ENVV "$UV" run python $DIR/stage2.py 2>&1 | tee $RES/stage2.log
  eval $ENVV "$UV" run python $DIR/plot.py   2>&1 | tee -a $RES/analyze.log
  TW2=$(python3 -c "import json;print(json.load(open('$RES/optimized_marks.json'))['twist_deg'])" 2>/dev/null)
  STAGE2="ran; post-stage2 optimum twist ${TW2}°"
fi

python3 - "$RES" "$STAGE2" <<'PY' > $RES/DECISION.md
import json,os,sys
res,stage2=sys.argv[1],sys.argv[2]
o=json.load(open(os.path.join(res,"optimized_marks.json")))
m=json.load(open(os.path.join(res,"metadata.json")))
print("# exp37 DECISION\n")
print(f"- Best-guess: {m['total_base_skips']} skips ({m['base_count'][list(m['base_count'])[0]]}/helix).")
print(f"- Verified optimum (`{o['candidate']}`): twist **{o['twist_deg']}°**, "
      f"bend {o.get('bend_deg')}°, rmsd {o['rmsd_nm']} nm, {o['total_skips']} skips.")
print(f"- Sub-1° twist reached: **{'YES' if abs(float(o['twist_deg']))<1.0 else 'NO'}**.")
print(f"- Stage-2 fine map: {stage2}.")
print(f"- Marks: `results/optimized_marks.json` (NOT applied to the design).")
print(f"- Graph: `results/exp37_summary.png`.")
PY
echo "[finalize $(date +%T)] DONE"
cat $RES/DECISION.md
