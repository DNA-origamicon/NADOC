#!/usr/bin/env bash
# Isolated CUDA-only engine. Never replaces the normal DNA/PEG installations.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GOLD_ROOT="${NADOC_GOLD_ENGINE_ROOT:-$HOME/.local/share/nadoc/engines/oxdna-mobile-gold}"
GOLD_REV=8028cf33b3cba12992b771156085fa54879f50cd
command -v nvcc >/dev/null
if [ ! -d "$GOLD_ROOT/source/.git" ]; then
  git clone https://github.com/lorenzo-rovigatti/oxDNA.git "$GOLD_ROOT/source"
fi
# Refuse modified source: rebuilding must not destroy local changes.
if [ -n "$(git -C "$GOLD_ROOT/source" status --porcelain)" ]; then
  echo 'Source is modified; choose a new NADOC_GOLD_ENGINE_ROOT for a fresh build.' >&2
  exit 1
fi
git -C "$GOLD_ROOT/source" checkout --detach "$GOLD_REV"
git -C "$GOLD_ROOT/source" apply "$PROJECT_ROOT/tools/oxdna_memory/adaptive-neighbor-lists.patch"
git -C "$GOLD_ROOT/source" apply "$PROJECT_ROOT/tools/oxdna_live/oxpy-field-steering.patch"
for patch in rigid-body-bussi.patch cuda-bussi-rng.patch physics-corrections.patch; do
  git -C "$GOLD_ROOT/source" apply "$PROJECT_ROOT/tools/oxdna_thermostat/$patch"
done
python3 "$PROJECT_ROOT/tools/oxdna_mobile_gold/patch_engine.py" "$GOLD_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_mobile_gold/patch_mixed.py" "$GOLD_ROOT/source"
cmake -S "$GOLD_ROOT/source" -B "$GOLD_ROOT/build" -DCMAKE_BUILD_TYPE=Release -DCUDA=ON -DPython=OFF -DCUDA_COMMON_ARCH=OFF -DCMAKE_CUDA_ARCHITECTURES="${OXDNA_CUDA_ARCH:-75}" -DUSE_CXX17_FOR_CUDA=ON
cmake --build "$GOLD_ROOT/build" -j"${NADOC_BUILD_JOBS:-4}" --target oxDNA
ln -sfn "$GOLD_ROOT/build" "$GOLD_ROOT/current"
