#!/usr/bin/env bash
# Compare standard CUDA and experimental GPU-resident periodic MD configs.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

if command -v namd3 &>/dev/null; then
    NAMD=namd3
elif [ -x "$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"
elif [ -x "$HOME/Applications/NAMD_3.0.2/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2/namd3"
else
    echo "namd3 not found" >&2
    exit 1
fi

N_THREADS=$(( $(nproc) > 16 ? 16 : $(nproc) ))
for conf in benchmark_standard_cuda.conf benchmark_gpu_resident.conf; do
    tag="${conf%.conf}"
    echo
    echo "=== $tag ==="
    "$NAMD" +p$N_THREADS +devices 0 "$conf" 2>&1 | tee "output/B_tube_periodic_1x_${tag}.log"
    if grep -qi "Low global CUDA exclusion\|FATAL\|ERROR" "output/B_tube_periodic_1x_${tag}.log"; then
        echo "WARNING: $tag logged exclusion/error warnings; inspect before trusting timing."
    fi
done
