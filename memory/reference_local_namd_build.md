---
name: reference_local_namd_build
description: "Which local NAMD build to use on this machine and why — the 3.0.2 release crashes GPU-resident; use the Dec-2025 git build (pinned via NADOC_NAMD_BIN)."
metadata:
  node_type: memory
  type: reference
---

# Local NAMD build on this machine (RTX 3080 Ti, 12 GB)

**Use the Dec-2025 git build, NOT the 3.0.2 release.** Pinned in `~/.bashrc`:
`NADOC_NAMD_BIN=$HOME/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3`
(find_namd's highest-precedence hook; the bashrc PATH entry also points here). Takes effect on
the next `just dev` restart.

**Why:** NAMD **3.0.2 release** hard-crashes in GPU-resident mode —
`CUDA error ... buildTileLists ... illegal memory access` (`CudaTileListKernel.cu:1141`) — and also
crashes in *offload* on relaxed/low-density geometries (`buildTileLists` + `cudaHostAlloc`
`reallocate_host_T`). It's a tile-list/host-buffer sizing bug. The **git build** has a
reallocation-retry (`CudaTileListKernel.cu:1126-1154`) that fixes it. Measured (VoltronCore 1.31M,
2 fs): git **resident 25.7 ms/step**, git **offload 66.6 ms/step** (resident 2.6× faster); 3.0.2
resident always crashes. Git strictly dominates — equal/faster on every config, runs configs 3.0.2
can't.

**No capability lost by using one CUDA build:** true CPU-only runs and GBIS implicit solvent need a
*non-CUDA* build that isn't installed here anyway; both are irrelevant (GBIS is a dead-end — it's
incompatible with GPU-resident, see [[project_voltroncore_fullbox_bench]] context). Full analysis +
build-off in `experiments/exp44_voltroncore_local/PLAN.md`.

**NADOC gap this papers over (not yet fixed in code):** NADOC's `namd_runner` probes detect the
crash but only *degrade* (resident→offload, or tile-list→CPU) — it never reaches for a build that
fixes it. With `NADOC_NAMD_BIN` pinned, that cascade never fires. Deferred code work: clearer
non-expert messaging, require-resident-by-default + diagnostic popup, ship the right build in
`docs/namd_setup.md`. See exp44 PLAN "GAP C RESOLVED".
