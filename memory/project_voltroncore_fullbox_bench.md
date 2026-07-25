---
name: project_voltroncore_fullbox_bench
description: "VoltronCore full-box (11.3M atom) explicit-solvent NAMD GPU-resident benchmark on RunPod H100 PCIe/SXM + H200 — results, the 4 methodological traps, and the >10M-atom PSF bug."
metadata: 
  node_type: memory
  type: project
  originSessionId: f638e987-fcd7-43c4-9cdf-020a15a790c4
---

# VoltronCore full-box NAMD GPU-resident benchmark (2026-07-21)

Benchmarked `workspace/VoltronCore.nadoc` (14,774 nt, square lattice, 59 helices) as a
**full explicit-solvent box = 11,305,826 atoms**, box **830.1 × 168.4 × 826.7 Å**, 3.60M
waters, 12.5 mM Mg-hexahydrate. Fits an H100/H200 80 GB in **GPU-resident** mode.
Campaign cost **$13.78 of $20** (0 pods left; `feedback_runpod_babysitter_must_act` honored).

## Results — DIRECT dynamics, +p16, 2 fs measured → 4 fs projected (×2)

| Card | $/hr (secure) | ms/step | 2fs ns/day | **4fs ns/day** | **$/ns (4fs)** |
|---|---|---|---|---|---|
| **H200** | 4.39 | 86.3 | 2.00 | **4.00** | $26.3 |
| **H100 SXM** | 2.99 | 93.5 | 1.85 | **3.70** | **$19.4** |
| **H100 PCIe** | 2.89 | 123 | 1.40 | **2.79** | $24.9 |

**Two-axis verdict** (`feedback_gpu_value_is_two_axes`): **H100 SXM is the sweet spot** —
best $/ns AND 2nd-fastest. H200 is fastest wall-clock but priciest per ns (only worth it
if wall-clock is critical). H100 PCIe is *dominated* by SXM (slower AND worse $/ns).
Live secure prices ran higher than the runbook's estimates (H100 PCIe billed $2.89, not $1.99).

## Full-ladder projection (4 stages × 3 chunks = 4.8M steps @ 4fs = 19.2 ns; + 4800-step min)

| | full ladder (19.2 ns) | Tier-A early-stop (~10×, 1.92 ns) |
|---|---|---|
| H200 | 4.8 d, ~$506 | ~11.5 h, ~$51 |
| H100 SXM | 5.2 d, ~$372 | ~12.5 h, ~$37 |
| H100 PCIe | 6.9 d, ~$477 | ~16.5 h, ~$48 |

A full-box 11.3M-atom relaxation is **expensive** (~$400–500 without early-stop). **Tier-A
early-stop is essential** (~10× cheaper). Best combo: **H100 SXM + Tier-A ≈ 12.5 h, ~$37.**

## The 4 methodological traps (each cost real pod-time here)

1. **4 fs DYNAMICS blows up on the fresh box** — `FATAL ERROR: SequencerCUDA: Atoms moving
   too fast`, at the FIRST dynamics step after `minimize 1000`. 2 fs (rigidBonds all +
   GPUresident) is stable. **Benchmark at 2 fs, project 4 fs = 2×** (ms/step is
   timestep-independent — per-step force cost identical). 4 fs is stable only *post*-equilibration
   (needs the ladder's 1 fs soft-start / RATTLE auto-soften on a fresh box). See `namd_4fs_production_only`.
2. **Minimization ms/step ≠ dynamics ms/step — off by ~2.7×.** NAMD's `Benchmark time:`
   lines during `minimize` report ~2.66× the true dynamics per-step, because the CG
   line-search does ~2.7 force evals per reported step. Believing the minimize numbers gave
   ns/day ~2.7× too pessimistic (0.95 vs the real 2.79 for PCIe). **Get the real number from
   `outputTiming 200` → `TIMING: <step> ... Wall: <w>, <wps>/step` during EQUILIBRIUM DYNAMICS
   (step > minimize count).** NAMD only prints `Benchmark time` in each command's early steps,
   so a short `run` after `minimize` prints none — `outputTiming` is the reliable path.
3. **+p16 is the GPU-resident optimum.** +p64 was **4.3× SLOWER** (1.55 vs 0.36 s/step) —
   oversubscription. Use `namd_threads(vcpus)` (=16), matching bench_anypod.
4. **>10M-atom PSF is unreadable by NAMD** (and by psfgen re-reading it): psfgen/NADOC's
   `writepsf` (non-EXT) uses I8 8-char integer columns; at 8-digit atom indices adjacent
   fields merge with no space, and NAMD's free-format connectivity reader desyncs →
   `FATAL ERROR: ALPHA CHARCTER ENCOUNTERED WHILE READING BONDS FROM PSF FILE`. The
   `write_hmr_psf` >10M fix (`_iter_packed_psf_pairs`) only stopped the Python IndexError, NOT
   this. **CODE BUG to fix in NADOC: emit EXT-format PSF (`writepsf ext` / I10 columns) for
   >~10M atoms.** Workaround used here: `scratchpad/fix_psf.py` respaces the connectivity
   sections (every field is a fixed 8-char column → re-emit whitespace-separated). Applied on
   the pod; header stays `PSF`, atom section untouched (parses fine), only bond/angle/etc. grids
   respaced. See [[project_tech_debt]].

## Build-on-pod recipe (local build is RAM-blocked; pod has 2TB RAM / 128 core)

Rent an H100 pod (comes with ~2TB RAM). `apt-get install -y gromacs` (gmx), upload the local
`~/Applications/NAMD_3.0.2/psfgen` (statically-ish linked, runs on any Ubuntu) + set
`NADOC_PSFGEN_BIN`, `pip install --break-system-packages scipy pydantic` (numpy present).
Rsync `backend/` + `workspace/VoltronCore.nadoc` + oxDNA seed `5ce768ef2acf/1_production/last_conf.dat`.
Run `scratchpad/build_on_pod.py` → 11.3M-atom package in **~7 min**. Bench tars staged on
`/media/jojo/Archive/nadoc_bench_pkg/`: `VoltronCore_bench.tar.gz` (4fs), `VoltronCore_bench_dyn.tar.gz`
(2fs + outputTiming). Seed conf `5ce768ef2acf`.

## Ledger note

The campaign ledger (`/media/jojo/Archive/nadoc_bench_campaign/spend.json`) had a **phantom
open row** (`ou1vxof3z0wwnm`, ~35 h old, `ended:null`) inflating `spent()` to $21.79 while the
account was clean — would have made pod_watchdog instakill every new pod. Archived to
`spend.pre_voltron.json` (real historical $7.83 preserved) and started fresh. Watch for stale
open rows; `close_pod` all pods on reap. See `REFERENCE_RUNPOD_RUNBOOK` §L9/#11.

## Session-loop gotcha (mine)

`pod.py bg 'rm -f X.log && namd ...'` with the bg wrapper redirecting to `X.log` **unlinks the
just-opened log** → namd writes to a deleted inode (recoverable only via `/proc/<pid>/fd/1`).
Never `rm` the bg log path inside the command.
