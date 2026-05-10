#!/usr/bin/env bash
# NADOC Periodic Cell NAMD Launch Script
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

if command -v namd3 &>/dev/null; then
    NAMD=namd3
elif [ -x "$HOME/Applications/NAMD_3.0.2/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2/namd3"
else
    echo "NAMD3 not found.  Downloading NAMD 3.0.2 (Linux/CUDA)..."
    wget -q "https://www.ks.uiuc.edu/Research/namd/3.0.2/download/NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz" -O /tmp/namd3.tar.gz
    tar -xzf /tmp/namd3.tar.gz -C "$HOME/Applications/"
    NAMD="$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"
fi

echo "Using NAMD: $NAMD"
N_THREADS=$(( $(nproc) > 8 ? 8 : $(nproc) ))

echo
echo "[1/3] Restrained NPT box discovery"
$NAMD +p$N_THREADS +devices 0 equilibrate_npt.conf 2>&1 | tee output/B_tube_periodic_1x_equilibrate_npt.log

echo
echo "[2/4] Averaging stable NPT tail and restoring locked Z"
python3 scripts/lock_box_from_xst.py \
    --xst output/B_tube_periodic_1x_equilibrate_npt.xst \
    --template relax_locked_nvt.template.conf \
    --out relax_locked_nvt.conf \
    --z-angstrom 70.140
python3 scripts/lock_box_from_xst.py \
    --xst output/B_tube_periodic_1x_equilibrate_npt.xst \
    --template production_locked_nvt.template.conf \
    --out production_locked_nvt.conf \
    --z-angstrom 70.140
for f in ramp_locked_nvt_*.template.conf; do
    out="${f%.template.conf}.conf"
    python3 scripts/lock_box_from_xst.py \
        --xst output/B_tube_periodic_1x_equilibrate_npt.xst \
        --template "$f" \
        --out "$out" \
        --z-angstrom 70.140
done

echo
echo "[3/4] Locked-Z restrained NVT relaxation"
$NAMD +p$N_THREADS +devices 0 relax_locked_nvt.conf 2>&1 | tee output/B_tube_periodic_1x_relax_locked_nvt.log

echo
echo "[4/4] Locked-Z restraint ramp and unrestrained NVT production"
for conf in ramp_locked_nvt_*.conf; do
    tag="${conf%.conf}"
    $NAMD +p$N_THREADS +devices 0 "$conf" 2>&1 | tee "output/B_tube_periodic_1x_${tag}.log"
done
$NAMD +p$N_THREADS +devices 0 production_locked_nvt.conf 2>&1 | tee output/B_tube_periodic_1x_production_locked_nvt.log

echo "Done. Trajectory: output/B_tube_periodic_1x_production_locked_nvt.dcd"
