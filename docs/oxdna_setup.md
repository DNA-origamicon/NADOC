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
resolves the mainline binary like this:

1. **`$OXDNA_BIN`** — explicit override (absolute path or a name on `$PATH`). Always wins.
2. Otherwise, among these candidates it **prefers a CUDA-capable binary**:
   - `oxDNA` on `$PATH`
   - `~/oxDNA/build_cuda/bin/oxDNA`
   - `~/oxDNA/build/bin/oxDNA`
   - `~/Applications/oxDNA/build/bin/oxDNA`

**The CUDA preference is deliberate** and fixes the most common broken state: a
CPU-only `oxDNA` first on `$PATH` (a conda/apt install) silently shadowing a
perfectly good local GPU build, so every `backend = CUDA` MD stage aborts with
`ERROR: Backend 'CUDA' not supported`. NADOC now skips a CPU-only binary in
favour of a CUDA one when both are present (detected statically via `ldd` →
`libcudart`). A CUDA build also runs the CPU backend fine, so preferring it is
never wrong. So you usually do **not** need `$OXDNA_BIN` even with a CPU-only
oxDNA on `$PATH` — just build the CUDA engine into `~/oxDNA` and NADOC finds it.

> **Quick check / one-command fix:** `just oxdna-doctor` reports your GPU,
> toolchain, which binary NADOC resolves, and whether it is CUDA-capable.
> `just oxdna-doctor --fix` auto-builds a CUDA-enabled oxDNA into `~/oxDNA`.

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

The fastest path is `just oxdna-doctor --fix`, which runs exactly the commands
below. To do it by hand, add `-DCUDA=ON` and your GPU's compute architecture.
One CUDA-built binary runs **both** the GPU and CPU backends (oxDNA picks per the
input file), so a single build into `~/oxDNA/build` is enough — NADOC's
CUDA-preferring resolver will choose it over any CPU-only `oxDNA` on `$PATH`:

```bash
cd ~/oxDNA
mkdir -p build && cd build
cmake .. -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86
make -j$(nproc) oxDNA DNAnalysis
```

`86` is the compute capability for an RTX 30-series (e.g. RTX 3080 Ti). Use the
value for your card (`75` for RTX 2080/2080 Super, `89` for RTX 40-series — see
https://developer.nvidia.com/cuda-gpus). `just oxdna-doctor` prints your card's
value, or read it from `nvidia-smi --query-gpu=compute_cap --format=csv`.

If you prefer to keep a separate CPU fallback, build CUDA into `~/oxDNA/build_cuda`
instead — that path is also auto-detected and **preferred** for GPU runs, so you
still don't need `$OXDNA_BIN`.

> **The conda toolchain works.** A fully conda-forge toolchain (conda's `nvcc`
> + `gcc`, no system CUDA install) builds the CUDA engine cleanly on current
> upstream oxDNA — verified on native Ubuntu with conda CUDA 12.9 + g++ 14.3,
> RTX 3080 Ti (`sm_86`). An earlier "CCCL macro conflict with conda CUDA
> headers" failure is no longer reproducible. You do **not** need a system-wide
> CUDA toolkit; `conda install -c conda-forge cuda-nvcc cuda-cudart-dev` suffices
> if `nvcc` is missing.

> **`$OXDNA_BIN` is now rarely needed.** NADOC prefers a CUDA-capable binary
> automatically, so a leftover CPU-only `oxDNA` on `$PATH` no longer shadows your
> GPU build. Set `$OXDNA_BIN` only to force a *specific* binary.

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

# One-shot: GPU, toolchain, resolved binary, and CUDA-capability in one report:
just oxdna-doctor

# Or the raw resolution (mainline + fork + DNAnalysis):
uv run python -c "
from backend.core.oxdna_runner import find_oxdna, find_oxdna_anm, find_dnanalysis, oxdna_supports_cuda
ox = find_oxdna()
print('oxDNA     ', ox or '(not found)', '[CUDA]' if ox and oxdna_supports_cuda(ox) else '[CPU-only]')
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
| Job fails: `ERROR: Backend 'CUDA' not supported` | The resolved oxDNA is a **CPU-only build** (commonly a conda/apt `oxDNA` on `$PATH`). Run `just oxdna-doctor` to confirm, then `just oxdna-doctor --fix` to build the CUDA engine. NADOC then prefers it automatically. Starting a CUDA job now fails fast with this guidance instead of dying mid-run. |
| Dynamics sidebar: "oxDNA not found" | No binary on any recognized path. `just oxdna-doctor --fix`, or build to `~/oxDNA/build/bin/oxDNA`, or set `$OXDNA_BIN`. Restart the backend after. |
| `cmake -DCUDA=ON` can't find CUDA | The CUDA **toolkit** (`nvcc`) isn't installed (driver alone isn't enough). Install it (`conda install -c conda-forge cuda-nvcc cuda-cudart-dev`, or a system CUDA toolkit); confirm `nvcc --version`. |
| oxDNA runs but won't use the GPU | The resolved binary is CPU-only. `just oxdna-doctor` shows which one and whether it's CUDA-capable; `--fix` builds a CUDA one. NADOC prefers a CUDA binary automatically — no `$OXDNA_BIN` needed unless you must force a specific build. |
| `nvidia-smi` fails inside WSL | Windows NVIDIA driver missing/old, or a Linux driver was installed inside WSL. Fix on the Windows side; never install a Linux GPU driver in WSL. |
| Wrong GPU selected on a multi-GPU box | Set `OXDNA_DEVICE` to the device index you want. |
| Protein job fails / "DNANM not available" | The mainline binary doesn't support proteins. Build the fork (`scripts/build-anm-oxdna.sh`) and set `$OXDNA_ANM_BIN`. |
| `scripts/build-anm-oxdna.sh`: "patch does not apply" | The upstream checkout drifted from the shipped patch. Inspect `scripts/anm-oxdna-cuda13.patch`. |
| Health check shows no H-bond count | `DNAnalysis` not found. It builds with `make … DNAnalysis`; ensure it sits next to the oxDNA binary, or set `$DNANALYSIS_BIN`. |
| Override ignored | `$OXDNA_BIN` must point at an **executable** file (or PATH-resolvable name). A bad path is silently skipped and resolution falls through. |
