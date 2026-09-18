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
# Same NADOC physics/thermostat corrections as scripts/build-oxdna.sh's
# adaptive-memory flavor, so this binary also carries the "NADOC physics
# corrections v3" signature the runner requires
# (backend/core/oxdna_runner.py:oxdna_supports_physics_v3). physics-corrections
# references _d_particle_ids, which only adaptive-neighbor-lists.patch declares
# (MD_CUDABackend.h), so that patch must land first even though this build
# does not otherwise use adaptive neighbor lists. None of these four overlap
# the DNA2PEG patch's files, so order relative to it doesn't matter.
for patch in oxdna_memory/adaptive-neighbor-lists oxdna_thermostat/rigid-body-bussi \
             oxdna_thermostat/cuda-bussi-rng oxdna_thermostat/physics-corrections; do
  PATCH="$PROJECT_ROOT/tools/$patch.patch"
  if git -C "$PEG_SOURCE" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    echo "==> $patch patch already applied"
  else
    git -C "$PEG_SOURCE" apply --check "$PATCH"
    git -C "$PEG_SOURCE" apply "$PATCH"
    echo "==> applied $patch patch"
  fi
done
python3 "$PROJECT_ROOT/tools/oxdna_peg/patch_engine.py" "$PEG_SOURCE"
cmake -S "$PEG_SOURCE" -B "$PEG_BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DCUDA=ON -DPython=OFF -DCUDA_COMMON_ARCH=OFF -DUSE_CXX17_FOR_CUDA=ON
cmake --build "$PEG_BUILD" -j"${NADOC_BUILD_JOBS:-4}" --target oxDNA DNAnalysis
ln -sfn "$PEG_BUILD" "$PEG_ROOT/current"
echo "DNA2PEG engine: $PEG_ROOT/current/bin/oxDNA"
