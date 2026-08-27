# oxDNA Setup Guide (incl. WSL + GPU)

This document covers getting **oxDNA** installed so NADOC's **Dynamics** sidebar
can run coarse-grained relaxation, E-field, and protein-DNA jobs. It also covers
the WSL2 + NVIDIA GPU story (shared with NAMD).

NADOC uses one pinned build of upstream `lorenzo-rovigatti/oxDNA`. Upstream merged
CUDA DNANM protein-DNA support in February 2026 (PR #192), so a separate ANM fork
is no longer required. The latest tagged release predates that merge; use NADOC's
build script instead of an older release package.

---

## TL;DR

1. **GPU under WSL2** = keep only the **Windows** NVIDIA driver; verify with
   `nvidia-smi` *inside* WSL. (Same rule as NAMD — see below.)
2. Install build tools: `sudo apt-get install -y build-essential cmake git`.
   For a GPU build, also install the CUDA toolkit (provides `nvcc`).
3. Run `scripts/build-oxdna.sh`. It pins a reviewed upstream revision, builds
   `oxDNA` and `DNAnalysis`, and installs them under NADOC's engine directory.

---

## How NADOC finds oxDNA

`find_oxdna()` in [backend/core/oxdna_runner.py](../backend/core/oxdna_runner.py)
resolves the binary like this:

1. **`$OXDNA_BIN`** — explicit override (absolute path or a name on `$PATH`). Always wins.
2. Otherwise, among these candidates it **prefers a CUDA-capable binary**:
   - `~/.local/share/nadoc/engines/oxdna/current/bin/oxDNA`
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
> `just oxdna-doctor --fix` auto-builds the pinned CUDA-enabled upstream oxDNA.

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

## Install upstream oxDNA (`DNANM` included)

The script checks out NADOC's pinned upstream revision and builds one engine for
DNA-only and protein-DNA jobs:

```bash
scripts/build-oxdna.sh
```

For the NADOC adaptive-memory CUDA flavor, which uses measured-capacity neighbor
and edge lists plus compact cell storage:

```bash
NADOC_OXDNA_ADAPTIVE_MEMORY=1 scripts/build-oxdna.sh
```

The flavors install side by side. The `current` symlink selects the most recently
built flavor, and NADOC automatically enables its guarded compact-list settings
for CUDA stages. The adaptive flavor also uses a linear histogram/scan/scatter
cell builder, defers the redundant step-zero CPU energy calculation, avoids
recomputing energy solely for restart-file headers, and changes the default
`verlet_skin = 0.20` to the measured BigO optimum of `0.40`. Explicit non-default
skin values remain untouched.

On an RTX 2080 Super, the fully sequenced 14,112-nt BigO repeat scales from 11.37
ms/step at 16 repeats to 22.04 ms/step at 32 repeats. See
[`tools/oxdna_memory/README.md`](../tools/oxdna_memory/README.md) for the benchmark
table, memory projections, and the current 22-bit CUDA particle-index ceiling.

It is idempotent and prints the installed binary and source revision. NADOC finds
the `current` symlink automatically; `OXDNA_BIN` remains an optional override.

Optional knobs for the script:
- `OXDNA_CUDA_ARCH` — optional compute capability override (for example `75`).
- `NADOC_OXDNA_ROOT` — managed install root.
- `NADOC_OXDNA_CPU_ONLY=1` — explicitly request a CPU-only build.

Validated on WSL2 Ubuntu, CUDA 13.3, g++ 13, RTX 2080 Super (`sm_75`).

---

## Verify

```bash
# Mainline — prints usage and exits non-zero with no input file (that's fine;
# you only care that it starts and reports a CUDA-enabled build if you built one)
~/oxDNA/build/bin/oxDNA 2>&1 | head

# One-shot: GPU, toolchain, resolved binary, and CUDA-capability in one report:
just oxdna-doctor

# Or the raw resolution:
uv run python -c "
from backend.core.oxdna_runner import find_oxdna, find_dnanalysis, oxdna_supports_cuda
ox = find_oxdna()
print('oxDNA     ', ox or '(not found)', '[CUDA]' if ox and oxdna_supports_cuda(ox) else '[CPU-only]')
print('DNAnalysis', find_dnanalysis() or '(not found)')
"
```

Then restart the NADOC backend (`just dev`) and open the **Dynamics** sidebar —
the "oxDNA missing" warning should be gone.

---

## Surface deposition

Surface deposition is available from **Dynamics → Anchors** when the hard surface is
enabled. Structure anchors are fixed traps used during ordinary force experiments;
surface anchors are a separate designation used to bring selected nucleotides into
contact with the hard plane.

The deposition run is staged:

1. A gentle approach starts the structure moving toward the plane.
2. The full approach applies a normal attraction to surface anchors. If they do not
   arrive together, NADOC automatically continues in short adaptive windows: anchors
   already within the capture gap receive a soft normal-only restraint, while only the
   remaining anchors continue to feel the ramped attraction.
3. Settle replaces attraction with soft normal-only restraints at the plane.
4. Equilibration retains those restraints while the anchors remain free to translate
   within the plane.

The hard-floor repulsion excludes the designated surface-anchor beads, preventing it
from competing with their attraction. Contact is gated before settle; a run fails
clearly if the configured window/force limits are exhausted. The defaults use a
1.0 nm capture gap, a 0.75 nm settle gate, 50,000-step adaptive windows, a 20 pN
force ceiling, and surface-restraint stiffness 1.0 oxDNA units. These parameters are
available through the surface-deposition API for unusually large or compliant designs.

After obtaining a good deposited frame, surface anchors can be copied into Structure
Anchors before a subsequent electric-field run. Structure anchors then hold those same
elements fixed; the surface deposition designation remains independently editable.

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
| Protein job fails / "DNANM not available" | The resolved binary predates upstream PR #192. Run `scripts/build-oxdna.sh`; do not use the older v3.7.0 release package. |
| Health check shows no H-bond count | `DNAnalysis` not found. It builds with `make … DNAnalysis`; ensure it sits next to the oxDNA binary, or set `$DNANALYSIS_BIN`. |
| Surface deposition never reaches settle | Inspect the reported remaining-anchor count and maximum gap. The runner automatically captures arrivals and ramps the remaining anchors up to the configured ceiling; increase the window count or force ceiling only if the structure remains healthy. |
| Deposited anchors stretch nearby backbone bonds | Use the surface-specific normal restraint (default stiffness `1.0`), not the generic immobile structure-anchor stiffness. Restart settle from the last healthy approach checkpoint if an older run used stiff traps. |
| Override ignored | `$OXDNA_BIN` must point at an **executable** file (or PATH-resolvable name). A bad path is silently skipped and resolution falls through. |
