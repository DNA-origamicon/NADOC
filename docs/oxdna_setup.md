# oxDNA Setup Guide (incl. WSL + GPU)

This document covers getting **oxDNA** installed so NADOC's **Dynamics** sidebar
can run coarse-grained relaxation, E-field, and protein-DNA jobs. It also covers
the WSL2 + NVIDIA GPU story (shared with NAMD).

NADOC runs oxDNA as its coarse-grained MD engine. It does **not** ship oxDNA — you
build it once on your own machine. There are **two** flavors, and which you need
depends on what you simulate:

| Flavor | Repo | When NADOC uses it | Built by |
|---|---|---|---|
| **Mainline oxDNA** | `lorenzo-rovigatti/oxDNA` | DNA-only relax / E-field / health | you (CMake, steps below) |
| **ANM-oxDNA fork** (`DNANM`) | `sulcgroup/anm-oxdna` | designs that include **proteins** | `scripts/build-anm-oxdna.sh` |

You can install just the mainline build and have full DNA-only MD; the fork is
only needed once you put imported proteins into an oxDNA job.

---

## TL;DR

1. **GPU under WSL2** = keep only the **Windows** NVIDIA driver; verify with
   `nvidia-smi` *inside* WSL. (Same rule as NAMD — see below.)
2. Install build tools: `sudo apt-get install -y build-essential cmake git`.
   For a GPU build, also install the CUDA toolkit (provides `nvcc`).
3. **Mainline oxDNA:** clone to `~/oxDNA`, `cmake` + `make`, and NADOC
   auto-detects `~/oxDNA/build/bin/oxDNA`.
4. **Protein-DNA fork:** run `scripts/build-anm-oxdna.sh`; point
   `OXDNA_ANM_BIN` at the binary it prints.

---

## How NADOC finds oxDNA

`find_oxdna()` in [backend/core/oxdna_runner.py](../backend/core/oxdna_runner.py)
resolves the mainline binary in this order:

1. **`$OXDNA_BIN`** — explicit override (absolute path or a name on `$PATH`).
2. **`oxDNA`** on `$PATH`.
3. Conventional builds:
   - `~/oxDNA/build/bin/oxDNA`
   - `~/Applications/oxDNA/build/bin/oxDNA`

The ANM fork is resolved separately by `find_oxdna_anm()`: **`$OXDNA_ANM_BIN`** →
`~/anm-oxdna/oxDNA/build_cuda/bin/oxDNA` (CUDA) → `…/build/bin/oxDNA` (CPU).

`DNAnalysis` — the ground-truth H-bond counter used by the health check — builds
alongside oxDNA and is found **next to** the resolved oxDNA binary (or via
`$DNANALYSIS_BIN` / `$PATH`). No separate install.

See [external_tools.md](external_tools.md) for the full environment-variable
reference shared across all simulation back-ends.

---

## Prerequisites

```bash
# Build toolchain (Ubuntu / WSL2)
sudo apt-get update
sudo apt-get install -y build-essential cmake git

# Check versions (oxDNA needs a C++14 compiler + CMake 3.x)
cmake --version
g++ --version
```

A **GPU build is optional** but strongly recommended for real systems — oxDNA on
the GPU is ~1–2 orders of magnitude faster. The GPU build additionally needs the
**CUDA toolkit** (`nvcc`):

```bash
nvcc --version       # only required for the CUDA build
nvidia-smi           # GPU must be visible (inside WSL too)
```

> **WSL2 + GPU — the one thing people get wrong** (identical to NAMD): install the
> NVIDIA driver on **Windows only**; never `apt install` a Linux NVIDIA driver
> inside WSL (it breaks the `/usr/lib/wsl/lib/libcuda.so` passthrough). If
> `nvidia-smi` works inside WSL, GPU access is done. The **CUDA toolkit**
> (`nvcc`), however, *is* installed inside WSL when you want to compile the CUDA
> build — that's the compiler, separate from the driver.

---

## Install mainline oxDNA (DNA-only MD)

### CPU build (always works, no GPU needed)

```bash
git clone https://github.com/lorenzo-rovigatti/oxDNA.git ~/oxDNA
cd ~/oxDNA
mkdir -p build && cd build
cmake ..
make -j$(nproc) oxDNA DNAnalysis
```

This produces:
- `~/oxDNA/build/bin/oxDNA`        ← the engine NADOC auto-detects
- `~/oxDNA/build/bin/DNAnalysis`   ← the H-bond health oracle (found next to it)

### CUDA / GPU build (recommended for real systems)

Add `-DCUDA=ON` and set your GPU's compute architecture. Build into a **separate**
directory so the CPU binary stays available as a fallback:

```bash
cd ~/oxDNA
mkdir -p build_cuda && cd build_cuda
cmake .. -DCUDA=ON -DCUDA_COMMON_ARCH=OFF -DCMAKE_CUDA_ARCHITECTURES=75
make -j$(nproc) oxDNA DNAnalysis
```

`75` is the compute capability for an RTX 2080 / 2080 Super. Use the value for
your card (e.g. `86` for RTX 30-series, `89` for RTX 40-series — see
https://developer.nvidia.com/cuda-gpus). Then point NADOC at the GPU binary:

```bash
export OXDNA_BIN=$HOME/oxDNA/build_cuda/bin/oxDNA   # add to ~/.bashrc to persist
```

(If you only keep the CPU build at the conventional `~/oxDNA/build/bin/oxDNA`,
no env var is needed — NADOC finds it automatically.)

### Which GPU does oxDNA use?

By default device `0`. To pick a different GPU, set `OXDNA_DEVICE` (e.g. `1`) —
the value NADOC reports as the recommended device.

---

## Install the ANM-oxDNA fork (protein-DNA, `DNANM`)

Only needed for designs that include imported proteins (mainline oxDNA has no
`DNANM` interaction). The fork is a ~2021 codebase that does **not** compile on a
modern toolchain unaided, so NADOC ships a build script that clones it, applies a
CUDA-13/g++-13 portability patch, and builds both CPU and (if available) CUDA
binaries:

```bash
scripts/build-anm-oxdna.sh
```

It is idempotent (safe to re-run) and prints the binary path at the end. Persist
the override it tells you:

```bash
# CUDA binary if a toolkit + GPU were present, else the CPU binary
export OXDNA_ANM_BIN=$HOME/anm-oxdna/oxDNA/build_cuda/bin/oxDNA
```

Optional knobs for the script:
- `OXDNA_CUDA_ARCH` — compute capability (default `75`; set to match your card).
- `ANM_OXDNA_DIR` — clone/build location (default `~/anm-oxdna`).

Validated on WSL2 Ubuntu, CUDA 13.3, g++ 13, RTX 2080 Super (`sm_75`).

---

## Verify

```bash
# Mainline — prints usage and exits non-zero with no input file (that's fine;
# you only care that it starts and reports a CUDA-enabled build if you built one)
~/oxDNA/build/bin/oxDNA 2>&1 | head

# What NADOC currently resolves (mainline + fork + DNAnalysis):
uv run python -c "
from backend.core.oxdna_runner import find_oxdna, find_oxdna_anm, find_dnanalysis
print('oxDNA     ', find_oxdna()      or '(not found)')
print('oxDNA-ANM ', find_oxdna_anm()  or '(not found)')
print('DNAnalysis', find_dnanalysis() or '(not found)')
"
```

Then restart the NADOC backend (`just dev`) and open the **Dynamics** sidebar —
the "oxDNA missing" warning should be gone.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Dynamics sidebar: "oxDNA not found" | No binary on any recognized path. Build to `~/oxDNA/build/bin/oxDNA`, or set `$OXDNA_BIN`. Restart the backend after. |
| `cmake -DCUDA=ON` can't find CUDA | The CUDA **toolkit** (`nvcc`) isn't installed (driver alone isn't enough). Install it inside WSL/Linux; confirm `nvcc --version`. |
| oxDNA runs but won't use the GPU | You're pointing at the CPU build. Set `$OXDNA_BIN` to the `build_cuda` binary. |
| `nvidia-smi` fails inside WSL | Windows NVIDIA driver missing/old, or a Linux driver was installed inside WSL. Fix on the Windows side; never install a Linux GPU driver in WSL. |
| Wrong GPU selected on a multi-GPU box | Set `OXDNA_DEVICE` to the device index you want. |
| Protein job fails / "DNANM not available" | The mainline binary doesn't support proteins. Build the fork (`scripts/build-anm-oxdna.sh`) and set `$OXDNA_ANM_BIN`. |
| `scripts/build-anm-oxdna.sh`: "patch does not apply" | The upstream checkout drifted from the shipped patch. Inspect `scripts/anm-oxdna-cuda13.patch`. |
| Health check shows no H-bond count | `DNAnalysis` not found. It builds with `make … DNAnalysis`; ensure it sits next to the oxDNA binary, or set `$DNANALYSIS_BIN`. |
| Override ignored | `$OXDNA_BIN` must point at an **executable** file (or PATH-resolvable name). A bad path is silently skipped and resolution falls through. |
