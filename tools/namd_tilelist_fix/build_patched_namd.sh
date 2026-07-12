#!/bin/bash
# Build a NADOC-patched NAMD 3.0.2 CUDA binary that fixes the buildTileLists crash.
#
# WHY: stock NAMD 3.0.2 CUDA dies on the FIRST step with
#   "CUDA error cudaStreamSynchronize(stream) ... CudaTileListKernel.cu, buildTileLists,
#    line 1141 ... an illegal memory access was encountered"
# on solvent-carved DNA-origami boxes.  Root cause + validation: see README.md and LESSONS K2.
#
# USAGE:
#   1. Download NAMD_3.0.2_Source.tar.gz from ks.uiuc.edu (needs a free account) and
#      pass its path as $1.  Expected sha256 0916700dec3342165b7ba2c3b5f99dcff767879d2a4931b5028dba47acd68bd5
#   2. Needs a CUDA 12.x toolkit.  CUDA 13 will NOT work: NAMD 3.0.2 uses cub::Min/cub::Max/
#      ShuffleDown/TransformInputIterator, all removed in CCCL 3.
#        sudo apt install cuda-toolkit-12-6
#   3. ./build_patched_namd.sh /path/to/NAMD_3.0.2_Source.tar.gz [/usr/local/cuda-12.6] [sm_75]
#
# Installs to ~/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/, which NADOC's
# find_namd() prefers automatically (it reverse-sorts ~/Applications/NAMD_*, and
# "3.0.2p1" sorts above "3.0.2_").
set -euo pipefail

TARBALL=${1:?usage: build_patched_namd.sh <NAMD_3.0.2_Source.tar.gz> [cuda-prefix] [sm_arch]}
CUDA_PREFIX=${2:-/usr/local/cuda-12.6}
SM=${3:-sm_75}                     # RTX 2080 SUPER = Turing sm_75; 3080 Ti = Ampere sm_86
CC=${SM#sm_}
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
DEST=$HOME/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA

echo "==> unpacking into $WORK"
tar xzf "$TARBALL" -C "$WORK"
cd "$WORK"/NAMD_3.0.2_Source

echo "==> applying the one-line tile-list fix"
patch -p0 --forward src/CudaComputeNonbonded.C < "$HERE/namd302_tilelist.patch" \
  || { echo "PATCH FAILED — source may not be 3.0.2"; exit 1; }

echo "==> building bundled charm++ (~15 min)"
tar xf charm-8.0.0.tar
( cd charm-8.0.0 && ./build charm++ multicore-linux-x86_64 --with-production -j"$(nproc)" )

echo "==> fetching FFTW + Tcl (anonymous)"
for f in fftw-linux-x86_64.tar.gz tcl8.6.13-linux-x86_64.tar.gz tcl8.6.13-linux-x86_64-threaded.tar.gz; do
  wget -q "http://www.ks.uiuc.edu/Research/namd/libraries/$f"
done
tar xzf fftw-linux-x86_64.tar.gz && mv linux-x86_64 fftw
tar xzf tcl8.6.13-linux-x86_64.tar.gz && mv tcl8.6.13-linux-x86_64 tcl
tar xzf tcl8.6.13-linux-x86_64-threaded.tar.gz && mv tcl8.6.13-linux-x86_64-threaded tcl-threaded

echo "==> restricting codegen to $SM (single arch: ~4x faster nvcc pass)"
python3 - "$CC" <<'PY'
import sys
from pathlib import Path
cc = sys.argv[1]
p = Path("arch/Linux-x86_64.cuda11")
out, skip = [], False
for ln in p.read_text().splitlines():
    if ln.startswith("CUDAGENCODE"):
        out.append(f"CUDAGENCODE = -gencode arch=compute_{cc},code=sm_{cc}")
        skip = True
        continue
    if skip:
        if ln.strip().startswith("-gencode"):
            continue
        skip = False
    out.append(ln)
p.write_text("\n".join(out) + "\n")
PY

echo "==> configuring"
./config Linux-x86_64-g++ --charm-arch multicore-linux-x86_64 \
         --with-single-node-cuda --cuda-prefix "$CUDA_PREFIX"

# NAMD ships a prebuilt NON-PIC static FFTW2; modern g++ defaults to PIE, so the final
# link fails with "relocation R_X86_64_32 ... can not be used when making a PIE object".
# charmc swallows -no-pie inside its quoted -ld++-option, so inject it via a g++ shim.
echo "==> installing g++ shim that adds -no-pie on link steps"
mkdir -p "$WORK/shim"
cat > "$WORK/shim/g++" <<'SHIM'
#!/bin/bash
for a in "$@"; do
  case "$a" in -c|-E|-S) exec /usr/bin/g++ "$@";; esac
done
exec /usr/bin/g++ -no-pie "$@"
SHIM
chmod +x "$WORK/shim/g++"

echo "==> building NAMD (~30 min)"
( cd Linux-x86_64-g++ && PATH="$WORK/shim:$PATH" make -j"$(nproc)" )

echo "==> installing to $DEST"
rm -rf "$DEST"
cp -r "$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA" "$DEST" 2>/dev/null \
  || mkdir -p "$DEST"
cp "$WORK/NAMD_3.0.2_Source/Linux-x86_64-g++/namd3" "$DEST/namd3"
chmod +x "$DEST/namd3"
cp "$HERE/namd302_tilelist.patch" "$HERE/README.md" "$DEST/" 2>/dev/null || true

echo
echo "DONE.  $DEST/namd3"
echo "NADOC's find_namd() will now prefer it automatically."
echo "Verify:  python -c 'from backend.core.namd_runner import find_namd; print(find_namd())'"
rm -rf "$WORK"
