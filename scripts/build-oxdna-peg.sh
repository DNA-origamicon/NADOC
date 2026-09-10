#!/usr/bin/env bash
# Isolated experimental engine; does not replace the normal oxDNA/oxpy install.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PEG_ROOT="${NADOC_PEG_ENGINE_ROOT:-$HOME/.local/share/nadoc/engines/oxdna-peg}"
PEG_REV=8028cf33b3cba12992b771156085fa54879f50cd
PEG_SOURCE="$PEG_ROOT/source"
PEG_BUILD="$PEG_ROOT/build"
mkdir -p "$PEG_ROOT"
if [ ! -d "$PEG_SOURCE/.git" ]; then
  git clone https://github.com/lorenzo-rovigatti/oxDNA.git "$PEG_SOURCE"
  git -C "$PEG_SOURCE" checkout --detach "$PEG_REV"
fi
if [ "$(git -C "$PEG_SOURCE" rev-parse HEAD)" != "$PEG_REV" ]; then
  echo "PEG source revision mismatch; expected $PEG_REV" >&2
  exit 1
fi
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_engine.py" "$PEG_SOURCE"
cmake -S "$PEG_SOURCE" -B "$PEG_BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DCUDA=ON -DPython=OFF -DCUDA_COMMON_ARCH=OFF -DUSE_CXX17_FOR_CUDA=ON
cmake --build "$PEG_BUILD" -j"${NADOC_BUILD_JOBS:-4}" --target oxDNA DNAnalysis
ln -sfn "$PEG_BUILD" "$PEG_ROOT/current"
echo "DNA2PEG engine: $PEG_ROOT/current/bin/oxDNA"
