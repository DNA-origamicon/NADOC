#!/usr/bin/env bash
# Build PEG's Python bindings separately; never replace the normal oxpy package
# or the batch engine currently used by running jobs.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PEG_ROOT="${NADOC_PEG_ENGINE_ROOT:-$HOME/.local/share/nadoc/engines/oxdna-peg}"
PEG_SOURCE="$PEG_ROOT/source"
PEG_LIVE_BUILD="$PEG_ROOT/build-live"
if [ ! -d "$PEG_SOURCE/.git" ]; then
  echo 'Build the PEG source first: bash scripts/build-oxdna-peg.sh' >&2
  exit 1
fi
if [ "$(git -C "$PEG_SOURCE" rev-parse HEAD)" != 8028cf33b3cba12992b771156085fa54879f50cd ]; then
  echo 'PEG source revision mismatch' >&2
  exit 1
fi
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_engine.py" "$PEG_SOURCE"
PATCH="$PROJECT_ROOT/tools/oxdna_live/oxpy-field-steering.patch"
if git -C "$PEG_SOURCE" apply --check "$PATCH" 2>/dev/null; then
  git -C "$PEG_SOURCE" apply "$PATCH"
else
  git -C "$PEG_SOURCE" apply --reverse --check "$PATCH"
fi
env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS cmake -S "$PEG_SOURCE" -B "$PEG_LIVE_BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DCUDA=ON -DPython=ON -DCUDA_COMMON_ARCH=OFF -DUSE_CXX17_FOR_CUDA=ON \
  -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++ -DCMAKE_C_FLAGS= -DCMAKE_CXX_FLAGS= \
  -DDEFAULT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
cmake --build "$PEG_LIVE_BUILD" -j"${NADOC_BUILD_JOBS:-2}" --target core
printf '%s\n' "PEG Live bindings: $PEG_LIVE_BUILD/python"
