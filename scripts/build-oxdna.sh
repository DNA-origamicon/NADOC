#!/usr/bin/env bash
# Build the pinned upstream oxDNA used by NADOC for DNA, RNA, and DNANM
# protein-DNA simulations. The pin includes upstream PR #192 (CUDA DNANM).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

OXDNA_URL="${NADOC_OXDNA_URL:-https://github.com/lorenzo-rovigatti/oxDNA.git}"
OXDNA_REV="${NADOC_OXDNA_REV:-8028cf33b3cba12992b771156085fa54879f50cd}"
ENGINE_ROOT="${NADOC_OXDNA_ROOT:-$HOME/.local/share/nadoc/engines/oxdna}"
SOURCE_DIR="${NADOC_OXDNA_SOURCE:-$ENGINE_ROOT/source}"
BUILD_FLAVOR="upstream"
if [ "${NADOC_OXDNA_ADAPTIVE_MEMORY:-0}" = "1" ]; then
  BUILD_FLAVOR="adaptive-memory"
fi
INSTALL_DIR="$ENGINE_ROOT/$OXDNA_REV-$BUILD_FLAVOR"
CURRENT="$ENGINE_ROOT/current"
BUILD_DIR="$SOURCE_DIR/build-nadoc-$BUILD_FLAVOR"
JOBS="${NADOC_BUILD_JOBS:-$(nproc)}"
OXPY_PYTHON="${NADOC_OXPY_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

echo "==> upstream oxDNA $OXDNA_REV"
echo "    source:  $OXDNA_URL"
echo "    install: $INSTALL_DIR"

mkdir -p "$ENGINE_ROOT"
if [ ! -d "$SOURCE_DIR/.git" ]; then
  git clone "$OXDNA_URL" "$SOURCE_DIR"
fi
git -C "$SOURCE_DIR" remote set-url origin "$OXDNA_URL"
git -C "$SOURCE_DIR" fetch --depth 1 origin "$OXDNA_REV"
git -C "$SOURCE_DIR" checkout --detach "$OXDNA_REV"

if [ "${NADOC_OXDNA_ADAPTIVE_MEMORY:-0}" = "1" ]; then
  ADAPTIVE_PATCH="$SCRIPT_DIR/../tools/oxdna_memory/adaptive-neighbor-lists.patch"
  if git -C "$SOURCE_DIR" apply --reverse --check "$ADAPTIVE_PATCH" >/dev/null 2>&1; then
    echo "==> adaptive-memory patch already applied"
  else
    git -C "$SOURCE_DIR" apply --check "$ADAPTIVE_PATCH"
    git -C "$SOURCE_DIR" apply "$ADAPTIVE_PATCH"
    echo "==> applied adaptive-memory patch"
  fi
else
  ADAPTIVE_PATCH="$SCRIPT_DIR/../tools/oxdna_memory/adaptive-neighbor-lists.patch"
  if git -C "$SOURCE_DIR" apply --reverse --check "$ADAPTIVE_PATCH" >/dev/null 2>&1; then
    git -C "$SOURCE_DIR" apply --reverse "$ADAPTIVE_PATCH"
    echo "==> removed adaptive-memory patch for upstream build"
  fi
fi

OXPY_PATCH="$SCRIPT_DIR/../tools/oxdna_live/oxpy-field-steering.patch"
if git -C "$SOURCE_DIR" apply --reverse --check "$OXPY_PATCH" >/dev/null 2>&1; then
  echo "==> oxpy live-steering patch already applied"
else
  git -C "$SOURCE_DIR" apply --check "$OXPY_PATCH"
  git -C "$SOURCE_DIR" apply "$OXPY_PATCH"
  echo "==> applied oxpy live-steering bindings"
fi

if [ ! -x "$OXPY_PYTHON" ]; then
  echo "ERROR: NADOC Python not found at $OXPY_PYTHON" >&2
  echo "Run 'uv sync', or set NADOC_OXPY_PYTHON to the backend interpreter." >&2
  exit 2
fi

cmake_args=(-S "$SOURCE_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release -DPython=ON)
if [ "${NADOC_OXDNA_CPU_ONLY:-0}" != "1" ]; then
  if ! command -v nvcc >/dev/null 2>&1; then
    echo "ERROR: CUDA build requested but nvcc is not on PATH." >&2
    echo "Set NADOC_OXDNA_CPU_ONLY=1 to explicitly build CPU-only." >&2
    exit 2
  fi
  cmake_args+=(-DCUDA=ON)
  if [ -n "${OXDNA_CUDA_ARCH:-}" ]; then
    cmake_args+=("-DCMAKE_CUDA_ARCHITECTURES=${OXDNA_CUDA_ARCH}")
  fi
fi

PATH="$(dirname "$OXPY_PYTHON"):$PATH" cmake "${cmake_args[@]}"
cmake --build "$BUILD_DIR" -j"$JOBS" --target oxDNA DNAnalysis core

mkdir -p "$INSTALL_DIR/bin" "$INSTALL_DIR/lib"
install -m 0755 "$BUILD_DIR/bin/oxDNA" "$INSTALL_DIR/bin/oxDNA"
install -m 0755 "$BUILD_DIR/bin/DNAnalysis" "$INSTALL_DIR/bin/DNAnalysis"
install -m 0755 "$BUILD_DIR/src/liboxdna_common.so" "$INSTALL_DIR/lib/liboxdna_common.so"
cmake -D "BINARY=$INSTALL_DIR/bin/oxDNA" \
      -D "OLD_RPATH=$BUILD_DIR/src" -P "$SCRIPT_DIR/set-relative-rpath.cmake"
cmake -D "BINARY=$INSTALL_DIR/bin/DNAnalysis" \
      -D "OLD_RPATH=$BUILD_DIR/src" -P "$SCRIPT_DIR/set-relative-rpath.cmake"
printf '%s\n' "$OXDNA_URL" > "$INSTALL_DIR/source-url"
printf '%s\n' "$OXDNA_REV" > "$INSTALL_DIR/source-revision"
printf '%s\n' "$BUILD_FLAVOR" > "$INSTALL_DIR/build-flavor"
ln -sfn "$INSTALL_DIR" "$CURRENT"

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$OXPY_PYTHON" --reinstall "$BUILD_DIR/python"
else
  "$OXPY_PYTHON" -m pip install --reinstall "$BUILD_DIR/python"
fi

echo "==> installed: $CURRENT/bin/oxDNA"
echo "==> installed: oxpy into $OXPY_PYTHON"
echo "==> source revision: $OXDNA_REV"
