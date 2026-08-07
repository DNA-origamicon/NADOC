# NAMD 3 Setup Guide (incl. WSL + GPU)

This document covers getting **NAMD 3** installed so NADOC's Molecular Dynamics
sidebar stops reporting "NAMD 3 is missing" and can run atomistic jobs. It also
covers the WSL2 + NVIDIA GPU story, which is the most common point of confusion.

NADOC runs NAMD as the production MD engine. It does **not** ship NAMD (the
license requires each user to register and accept it), so every user installs
it once on their own machine.

---

## TL;DR

1. **GPU under WSL2** = install/keep the **Windows** NVIDIA driver only. Do not
   install a Linux NVIDIA driver inside WSL — it breaks the passthrough. Verify
   with `nvidia-smi` *inside* WSL.
2. Download the prebuilt **`Linux-x86_64-multicore-CUDA`** build of NAMD 3
   (license-gated — see below). This is the GPU build NADOC's launch flags expect.
3. Extract to `~/Applications/` and NADOC auto-detects it (the folder name is
   already a recognized path). Or point `$NADOC_NAMD_BIN` at any `namd3` binary.

---

## How NADOC finds NAMD

`find_namd()` in [backend/core/namd_runner.py](../backend/core/namd_runner.py)
resolves the binary in this order:

1. **`$NADOC_NAMD_BIN`** — explicit override. Absolute path to a `namd3` binary,
   or a name resolvable on `$PATH`. Use this for non-standard install locations.
2. **`namd3`** on `$PATH`.
3. Conventional installs under `~/Applications/`. The path is **globbed**
   (`~/Applications/NAMD_*/namd3`), so any NAMD version matches — no code change
   needed to upgrade — and a CUDA/GPU build sorts ahead of a CPU-only build:
   - `~/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3`  ← GPU build (preferred)
   - `~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3`        ← CPU build
   - …a newer `~/Applications/NAMD_3.0.3…/namd3` would be picked up automatically.

If none resolve, the MD sidebar reports NAMD missing and job creation refuses
early (before the expensive solvation step).

See [external_tools.md](external_tools.md) for the full environment-variable
reference shared across all simulation back-ends.

### Which build do I need?

NADOC launches NAMD as:

```
namd3 +p<threads> +setcpuaffinity +devices <gpu_ids> <segment>.conf
```

- The **`Linux-x86_64-multicore-CUDA`** build uses `+devices` for GPU offload.
  **This is the build you want** — origami atomistic systems are large and the
  GPU is ~1–2 orders of magnitude faster than CPU.
- The plain **`Linux-x86_64-multicore`** (CPU-only) build also works with NADOC:
  it simply prints `WARNING: +devices ... was not parsed by the RTS` and runs on
  CPU. Fine for tiny test systems or smoke-testing the pipeline; impractically
  slow for real production runs.

---

## WSL2 + GPU: the one thing people get wrong

On WSL2, the GPU is projected into Linux by the **Windows-side NVIDIA driver**
through `/usr/lib/wsl/lib/libcuda.so`. The rules:

- ✅ Install/update the **NVIDIA driver on Windows**.
- ❌ Do **not** `apt install` a Linux NVIDIA driver inside WSL. It overwrites the
  WSL stub and breaks `nvidia-smi`.
- ❌ You do **not** need the CUDA toolkit (`nvcc`) for prebuilt NAMD — the
  binary bundles its own CUDA runtime. (`nvcc` is only needed if you compile
  NAMD or Charm++ from source.)

Verify the GPU is visible from inside WSL:

```bash
nvidia-smi                       # must list your GPU
ls /usr/lib/wsl/lib/libcuda.so   # the WSL CUDA stub must exist
```

If `nvidia-smi` works in WSL, GPU access is already done — no further setup.

**VRAM note:** fully-solvated origami boxes can be large. An 8 GB card (e.g. a
GeForce RTX 2080) handles modest explicit-solvent systems but a big box can
exceed VRAM and NAMD will fail to allocate on the GPU. Keep the solvent padding
tight, or fall back to the CPU build for oversized systems.

---

## Install (prebuilt CUDA binary — recommended)

1. Get the binary from the NAMD download page
   (https://www.ks.uiuc.edu/Research/namd/) — register (free) and accept the
   license, then download **NAMD 3.0.2, Linux-x86_64 (multicore CUDA)**. The
   download is license-gated, so it can't be a blind `wget`.

2. Extract into `~/Applications/`:

   ```bash
   mkdir -p ~/Applications
   tar xf NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz -C ~/Applications/
   ```

   The tarball unpacks to a folder named exactly
   `NAMD_3.0.2_Linux-x86_64-multicore-CUDA/`, which matches a recognized NADOC
   path — no further config needed.

3. Smoke-test (prints the banner and reports the GPU it sees):

   ```bash
   ~/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3 +p4 +devices 0
   ```

   (It exits non-zero because no `.conf` was given — that's expected; you only
   care that it starts and lists your GPU.)

4. Restart the NADOC backend (`just dev`) and reopen the MD sidebar — the
   "missing" warning should be gone.

### Let NADOC finish the install for you

You still have to do the license-gated download by hand, but NADOC can take it
from there. In the app, **Help ▸ MD Engines** → NAMD row → **Download…** → after
you've downloaded the tarball, click **Check download & install**: NADOC scans
`~/Downloads`, verifies the file is the right package (correct build, and that it
actually contains `namd3`), extracts it to `~/Applications/`, and confirms
detection — no manual `tar`/path setup. psfgen comes with it. A freshly-installed
NAMD is detected without restarting the backend.

### Non-standard location

If you keep NAMD somewhere else, set the override before launching the backend:

```bash
export NADOC_NAMD_BIN=/path/to/namd3
just dev
```

To persist it, add the `export` to your shell profile (e.g. `~/.bashrc`) so the
backend process inherits it.

### psfgen (topology builder) comes free

NADOC builds all-hydrogen CHARMM topology with **`psfgen`**, which ships *inside*
the NAMD tarball (top level, next to `namd3`). Once you extract NAMD to
`~/Applications/...`, NADOC finds `psfgen` there automatically — no separate
install. For a non-standard location, set `$NADOC_PSFGEN_BIN=/path/to/psfgen`.
If a job fails with "psfgen not found", it's the same missing-NAMD situation as
above.

### Thread / core control

- `+p<threads>` is chosen by NADOC from the job config.
- `NADOC_NAMD_CORES` (e.g. `0-7`) pins NAMD to specific CPU cores via `taskset`.
  Leave unset to auto-bind to the first N cores.

---

## Building from source (only if you can't use a prebuilt binary)

The prebuilt CUDA binary is strongly preferred. Building NAMD 3 from the
`NAMD_3.0.2_Source.tar.gz` for GPU is a multi-step compile (build Charm++, then
configure NAMD `--with-cuda` against an installed CUDA toolkit with `nvcc`) and
takes a long time. Only go this route if no prebuilt binary fits your platform.
The output `namd3` then goes in any recognized path or is pointed at via
`$NADOC_NAMD_BIN`.

### On the Alpine cluster you have no choice — there is no CUDA NAMD module

CURC ships only CPU NAMD modules, and the local binary cannot be uploaded (Alpine is
glibc 2.28, our desktop build is 2.38). So NADOC builds its own GPU-resident NAMD 3 on
the cluster. `backend/core/cluster_build.py` drives it end to end — tarball the source,
submit an `acompile` job, verify the binary — via `POST /api/cluster/build/namd`.

The settings that are not obvious, each of which cost a failed build:

| Setting | Why |
|---|---|
| `--with-single-node-cuda` | The only flag that sets `-DNODEGROUP_FORCE_REGISTER`. Without it you get a CUDA build with **no** GPU-resident mode, which is the entire point. |
| `--with-tcl` + `tcltk/8.6.11` | `run` and `minimize` are **Tcl** commands, not native NAMD ones. Every conf ends in `run N`, so `--without-tcl` produces a binary that dies with `NOT VALID / run`. |
| `-ltcl8.6 -lz` | Alpine ships a *static* `libtcl8.6.a`, which does not pull zlib in transitively the way Ubuntu's `.so` does. |
| `cmake/3.27.7` | Absent from the default environment; without it the build silently falls back to `buildold`. |
| default gencodes | Leave NAMD's curated arch list alone. The sm_90 binary PTX-JITs onto sm_89 (al40) — measured — so one build covers the fleet. |

Modules: `gcc/11.2.0 cuda/12.1.1 cmake/3.27.7 fftw/3.3.10 tcltk/8.6.11`. Point the
cluster profile's `gpu_namd_bin` at the result.

**Probe with `module spider`, never `module load`.** Alpine's Lmod is hierarchical, so a
login node refuses loads that succeed on a compute node — a pre-flight built on `module
load` reports confident false negatives. See LESSON L14.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Sidebar: "NAMD 3 is missing" | Binary not on any recognized path. Set `$NADOC_NAMD_BIN` or install to `~/Applications/...`. Restart the backend after. |
| `nvidia-smi` fails inside WSL | Windows NVIDIA driver missing/old, or a Linux driver was installed inside WSL. Fix on the Windows side; never install a Linux GPU driver in WSL. |
| `WARNING: +devices ... not parsed by the RTS` | You're running the **CPU-only** build. It still runs (on CPU). Install the `multicore-CUDA` build for GPU. |
| NAMD aborts allocating GPU memory | System too large for the card's VRAM. Reduce solvent padding or use the CPU build. |
| Override ignored | `$NADOC_NAMD_BIN` must point at an **executable** file (or PATH-resolvable name). A bad path is silently skipped and resolution falls through. |
