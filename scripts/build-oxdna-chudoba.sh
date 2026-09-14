#!/usr/bin/env bash
# Separate published-model engine while the existing review engine stays usable.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CHUDOBA_ROOT="${NADOC_CHUDOBA_ENGINE_ROOT:-$HOME/.local/share/nadoc/engines/oxdna-chudoba}"
CHUDOBA_REV=8028cf33b3cba12992b771156085fa54879f50cd
mkdir -p "$CHUDOBA_ROOT"
if [ ! -d "$CHUDOBA_ROOT/source/.git" ]; then
  git clone https://github.com/lorenzo-rovigatti/oxDNA.git "$CHUDOBA_ROOT/source"
  git -C "$CHUDOBA_ROOT/source" checkout --detach "$CHUDOBA_REV"
fi
if [ "$(git -C "$CHUDOBA_ROOT/source" rev-parse HEAD)" != "$CHUDOBA_REV" ]; then
  echo "Unexpected Chudoba engine source revision" >&2
  exit 1
fi
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_engine.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_cuda.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_observables.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_cutoff.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_pure.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_npt.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_hmc.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_shape.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_cells.py" "$CHUDOBA_ROOT/source"
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_chudoba_zero_tail.py" "$CHUDOBA_ROOT/source"
cmake -S "$CHUDOBA_ROOT/source" -B "$CHUDOBA_ROOT/build" -DCMAKE_BUILD_TYPE=Release \
  -DCUDA=ON -DPython=OFF -DCUDA_COMMON_ARCH=OFF -DUSE_CXX17_FOR_CUDA=ON
cmake --build "$CHUDOBA_ROOT/build" -j"${NADOC_BUILD_JOBS:-2}" --target oxDNA DNAnalysis
