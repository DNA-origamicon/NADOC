#!/usr/bin/env bash
# Run the v2 restraint-ramp chain then anisotropic NPT production.
# Each stage uses velocity continuation — no reinitvels, no minimize.
# Stages: ramp_v2_00 (k=0.50, 200 ps) → 01 (k=0.25) → 02 (k=0.10) → 03 (k=0.03)
#         → production_aniso_npt (no restraints, anisotropic NPT, 50 ns)

set -euo pipefail

RUNDIR=/home/jojo/Work/NADOC/experiments/exp23_periodic_cell_benchmark/results/periodic_cell_run
LOGDIR=/home/jojo/Work/NADOC/experiments/exp23_periodic_cell_benchmark/results
NAMD="namd3 +p16 +devices 0"

run_stage() {
    local conf="$1"
    local log="$2"
    echo "$(date '+%H:%M:%S')  Starting $conf"
    cd "$RUNDIR"
    $NAMD "$conf" > "$log" 2>&1
    local rc=$?
    if [ $rc -ne 0 ]; then
        echo "$(date '+%H:%M:%S')  FAILED: $conf (exit $rc) — stopping chain." >&2
        exit $rc
    fi
    echo "$(date '+%H:%M:%S')  Done: $conf"
}

run_stage ramp_v2_00.conf             "$LOGDIR/ramp_v2_00.log"
run_stage ramp_v2_01.conf             "$LOGDIR/ramp_v2_01.log"
run_stage ramp_v2_02.conf             "$LOGDIR/ramp_v2_02.log"
run_stage ramp_v2_03.conf             "$LOGDIR/ramp_v2_03.log"
run_stage production_iso_npt.conf     "$LOGDIR/production_iso_npt.log"

echo "$(date '+%H:%M:%S')  Chain complete."
