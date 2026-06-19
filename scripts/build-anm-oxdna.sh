#!/usr/bin/env bash
# Build the ANM-oxDNA fork (sulcgroup/anm-oxdna) — the protein-DNA hybrid (DNANM) oxDNA engine
# NADOC uses for including imported proteins in oxDNA simulations.
#
# The fork is ~2021-era and does NOT compile out-of-the-box on a modern toolchain (CUDA 13 /
# g++ 13). This script clones it, applies scripts/anm-oxdna-cuda13.patch (all the portability +
# CUDA-13 fixes), regenerates the one version-specific CUB-header shadow, and builds BOTH the CPU
# and CUDA binaries.
#
# Result:
#   CPU  binary: ~/anm-oxdna/oxDNA/build/bin/oxDNA       (always)
#   CUDA binary: ~/anm-oxdna/oxDNA/build_cuda/bin/oxDNA  (if a CUDA toolkit + GPU are present)
# Point NADOC's OXDNA_ANM_BIN at the CUDA binary (falls back to CPU).
#
# Idempotent: re-running re-clones only if missing, re-applies the patch only if not already applied.
# Validated 2026-06-19 on WSL2 Ubuntu, CUDA 13.3, g++ 13, RTX 2080 Super (sm_75).
set -euo pipefail

REPO="${ANM_OXDNA_DIR:-$HOME/anm-oxdna}"
SRC="$REPO/oxDNA"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$SCRIPT_DIR/anm-oxdna-cuda13.patch"
ARCH="${OXDNA_CUDA_ARCH:-75}"   # RTX 2080 Super = 75; override for other GPUs
JOBS="$(nproc)"

echo "==> ANM-oxDNA build  (repo=$REPO  arch=sm_$ARCH  jobs=$JOBS)"

# 1. Clone (shallow) if absent
if [ ! -d "$SRC/src" ]; then
  echo "==> cloning sulcgroup/anm-oxdna"
  git clone --depth 1 https://github.com/sulcgroup/anm-oxdna.git "$REPO"
else
  echo "==> reusing existing clone at $REPO"
fi

# 2. Apply the CUDA-13/g++-13 portability patch (paths are relative to the repo root, prefixed oxDNA/)
cd "$REPO"
if git apply --reverse --check "$PATCH" >/dev/null 2>&1; then
  echo "==> patch already applied"
elif git apply --check "$PATCH" >/dev/null 2>&1; then
  echo "==> applying $PATCH"
  git apply "$PATCH"
else
  echo "!!  patch does not apply cleanly against this checkout — inspect $PATCH" >&2
  exit 1
fi

# 3. Regenerate the CUB-header shadow (CUDA 13.3 CCCL + libstdc++13 make CUB's free data()/size()
#    calls on cuda::std::span ambiguous; we ship a copy with those calls qualified to ::cuda::std::).
#    The CUB header is CUDA-version-specific and root-owned, so we copy+patch a LOCAL shadow that the
#    build prepends to nvcc's include path (CMakeLists adds -I oxDNA/cuda_compat). Skip if absent.
CUB_HDR="$(ls /usr/local/cuda*/targets/*/include/cccl/cub/block/block_load_to_shared.cuh 2>/dev/null | head -1 || true)"
if [ -n "$CUB_HDR" ]; then
  echo "==> regenerating CUB shadow from $CUB_HDR"
  mkdir -p "$SRC/cuda_compat/cub/block"
  cp "$CUB_HDR" "$SRC/cuda_compat/cub/block/block_load_to_shared.cuh"
  # qualify free-function data()/size() (NOT .data()/.size() members) to ::cuda::std::
  sed -i -E 's/([^._:>a-zA-Z0-9])(data|size)\(/\1::cuda::std::\2(/g' \
    "$SRC/cuda_compat/cub/block/block_load_to_shared.cuh"
else
  echo "==> no CCCL CUB block_load_to_shared.cuh found — skipping shadow (older CUDA, not needed)"
fi

# 4. CPU build (always — sufficient for all NADOC development; protocol is backend-agnostic)
echo "==> building CPU binary"
mkdir -p "$SRC/build" && cd "$SRC/build"
cmake .. >/dev/null
make oxDNA DNAnalysis -j"$JOBS"
echo "==> CPU binary: $SRC/build/bin/oxDNA"

# 5. CUDA build (only if a CUDA toolkit is installed)
if command -v nvcc >/dev/null 2>&1 || ls /usr/local/cuda*/bin/nvcc >/dev/null 2>&1; then
  echo "==> building CUDA binary (sm_$ARCH)"
  mkdir -p "$SRC/build_cuda" && cd "$SRC/build_cuda"
  cmake .. -DCUDA=ON -DOXDNA_CUDA_ARCH="$ARCH" >/dev/null
  make oxDNA DNAnalysis -j"$JOBS"
  echo "==> CUDA binary: $SRC/build_cuda/bin/oxDNA"
  echo "==> set OXDNA_ANM_BIN=$SRC/build_cuda/bin/oxDNA"
else
  echo "==> no nvcc found — skipped CUDA build (CPU binary is sufficient for development)"
  echo "==> set OXDNA_ANM_BIN=$SRC/build/bin/oxDNA"
fi
echo "==> done."
