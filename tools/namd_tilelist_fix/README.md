# NAMD CUDA `buildTileLists` crash — root cause and fix

Stock **NAMD 3.0.2 CUDA** dies on the **first** integration step (minimize *or* dynamics) with:

```
FATAL ERROR: CUDA error cudaStreamSynchronize(stream) in file src/CudaTileListKernel.cu,
function buildTileLists, line 1141 ... an illegal memory access was encountered
```

on large solvent-carved DNA-origami boxes. This directory holds the **one-line source fix**, a
build script, and the evidence.

## Root cause

NAMD counts nonbonded tile-lists **twice** — once on the CPU to size the kernel's loop, once on the
GPU to actually fill the array — and the two formulas disagree for an **empty patch**:

| | file | formula | patch with 0 atoms |
|---|---|---|---|
| **host** | `CudaComputeNonbonded.C:1596` (`calcNumTileLists`) | `(numAtoms-1)/32 + 1` | **1** |
| **device** | `CudaTileListKernel.cu:351` (`calcTileListPosKernel`), `:385` (`updatePatchesKernel`) | `computeNumTiles()` = `(numAtoms+31)/32` | **0** |

They agree for every patch with ≥1 atom. They differ only at `numAtoms == 0`, because C truncates
`-1/32` toward zero.

So **every compute whose i-patch is empty makes the host over-count `numTileLists` by one.**
`updatePatchesKernel` never writes those trailing entries, but `buildTileListsBBKernel` still loops
over them (`itileList < numTileLists`). It reads the **uninitialized tail**, gets `icompute = 0` and
`patchInd = (0,0)`, hence `i = itileList - tileListPos[0] = itileList`, and then reads
`boundingBoxes[itileList]` — an index of ~184,000 into a 13,166-entry array. `boundingBoxes` has **no
bounds check** in that kernel (only `tileJatomStart` does). → `cudaErrorIllegalAddress`.

### Why this hits DNA origami specifically

Empty patches only exist where there is **vacuum**. A carved water shell (0.5 nm) around a flat plate
in a rectangular periodic box leaves vacuum at the **box corners** — measured empty patches sit at
exactly `(0|25, 2, 0|33)`. Fill the vacuum (1.0 nm shell → 0 empty patches) and the identical patch
grid runs fine. This is the same "correlates with high vacuum content" observation posted to namd-l in
2017 and never diagnosed.

### Why it looked non-deterministic / "banded"

The uninitialized tail exists in *every* carved case, but `cudaMalloc` does not zero memory — whether
the leftover garbage indexes out of bounds depends on allocation history. Hence: deterministic for a
given system, erratic across system sizes (a 380k-atom plate crashes while a 707k one runs).

## The fix

Make the host use the same helper the device uses (`namd302_tilelist.patch`). This is exactly what
upstream's development branch already does — they centralized every tile count onto `computeNumTiles()`
and thereby fixed this, apparently without noticing.

## Validation

| binary | 13 packages that crash 100% on stock | 3 known-good controls |
|---|---|---|
| stock 3.0.2 (ks.uiuc.edu binary) | 13 CRASH | 3 RUN |
| rebuilt from source, **unpatched** (same CUDA 12.6 toolchain) | **13 CRASH** | 3 RUN |
| rebuilt from source, **patched** | **13 RUN** | 3 RUN |

The unpatched control isolates the one line: it is not the toolchain, not CUDA 12 vs 11.8, not the
rebuild. Patched GPU also **agrees with the CPU build to ~0.02%** on total energy for a system stock
NAMD cannot run at all — so it is correct, not merely non-crashing.

## Build

Needs the NAMD 3.0.2 **source** tarball (free account at ks.uiuc.edu) and a **CUDA 12.x** toolkit.
CUDA 13 will *not* compile 3.0.2 (`cub::Min`/`cub::Max`/`ShuffleDown`/`TransformInputIterator` were
removed in CCCL 3).

```bash
sudo apt install cuda-toolkit-12-6          # NVIDIA repo is already configured on both boxes
./build_patched_namd.sh /path/to/NAMD_3.0.2_Source.tar.gz /usr/local/cuda-12.6 sm_75
```

Pass the right arch: `sm_75` (RTX 2080 SUPER, Turing) or `sm_86` (RTX 3080 Ti, Ampere).

Installs to `~/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/`, which NADOC's `find_namd()`
prefers automatically (it reverse-sorts `~/Applications/NAMD_*`, and `3.0.2p1` sorts above `3.0.2_`).
No code change needed.

**The second computer still runs stock NAMD until you run this there.** Until then its GPU jobs are
protected by the pre-flight probe (`namd_runner.gpu_tilelist_probe`), which detects the crash in
~10 s and routes that job to the CPU build.
