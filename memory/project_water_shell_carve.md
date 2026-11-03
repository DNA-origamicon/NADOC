---
name: water-shell-carve
description: NAMD water-shell carve to fit large origami (VoltronCore) on a 12 GB GPU
metadata: 
  node_type: memory
  type: project
  originSessionId: 3e50f67f-227e-4e31-8f9b-c16fbe3f92d1
---

# Water-shell preparation and GPU compatibility

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

VoltronCore NAMD failed with `cudaMalloc ... out of memory` on the RTX 3080 Ti
(12 GB) — the solvated system was 8.86M atoms (vs ~3M for the 18hb that fit).

Diagnosis: the box is NOT oversized — it's exactly DNA bbox + 1.2 nm padding on
every face. PCA reorientation makes it *worse* (shape is a thin plate in X–Z, not
a diagonal rod). The waste is that the box is ~82% empty: DNA fills 18%, a 20 Å
shell needs ~41%. So ~half the atoms are bulk water in empty corners.

Fix (implemented): **water-shell carve**. After `gmx solvate`, drop water whose
oxygen is > `water_shell_nm` from any DNA atom (`_carve_water_shell`, cKDTree).
Box dims / PME grid unchanged; only particle count drops. Real result on
VoltronCore (ideal B-DNA build, shell 1.5 nm): **5.52M → 1.15M atoms (4.8×)**.

<a id="-superseded-2026-07-11-native-gmx-solvate--shell-the-carve-oom-crashed-wsl"></a>
- [⚡ SUPERSEDED 2026-07-11: native `gmx solvate -shell` (the carve OOM-crashed WSL)](details/project_water_shell_carve/01-superseded-2026-07-11-native-gmx-solvate--shell-the-carve-oom-cr.md#-superseded-2026-07-11-native-gmx-solvate--shell-the-carve-oom-crashed-wsl)

- [Follow-up: first-dynamics-stage stability (RATTLE crash) — continued detail](details/project_water_shell_carve/01-superseded-2026-07-11-native-gmx-solvate--shell-the-carve-oom-cr.md)

<a id="follow-up-first-dynamics-stage-stability-rattle-crash"></a>
- [Follow-up: first-dynamics-stage stability (RATTLE crash)](details/project_water_shell_carve/01-superseded-2026-07-11-native-gmx-solvate--shell-the-carve-oom-cr.md#follow-up-first-dynamics-stage-stability-rattle-crash)

<a id="-optimize-button-advanced-card--backendcoremd_optimizepy"></a>
- [⚡ Optimize button (Advanced card) — `backend/core/md_optimize.py`](details/project_water_shell_carve/02-optimize-button-advanced-card--backendcoremd_optimizepy.md#-optimize-button-advanced-card--backendcoremd_optimizepy)

<a id="-2026-07-12-a-carve-and-gpuresident-are-mutually-exclusive-enforced-in-code"></a>
- [⚠️ 2026-07-12: A CARVE AND `GPUresident` ARE MUTUALLY EXCLUSIVE (enforced in code)](details/project_water_shell_carve/02-optimize-button-advanced-card--backendcoremd_optimizepy.md#-2026-07-12-a-carve-and-gpuresident-are-mutually-exclusive-enforced-in-code)

## 2026-07-28: `GPUresident` DECOUPLED FROM `fast` — soft/declash ladders are resident too

The gate was `gpu_resident = fast and (not carved or fill_fraction >= _RESIDENT_MIN_FILL)`.
`fast` is killed by `soft_ladder = declash or force_soft`, so **every declash package ran its
entire relaxation ladder on CUDA-offload** — not by choice, just as collateral of the soft
integrator disabling `fast`.

**The win scales UP with system size.** (A first pass through this reasoned the opposite —
that small systems were latency-bound and would gain most — and measurement refuted it.
`utilization.memory 7%` alongside `utilization.gpu 84%` is NOT evidence of host round-trip
stalling; it just reflects a small working set, and both modes pay the same fixed per-step
kernel-launch cost.) Measured on the RTX 3080 Ti, soft integrator (1 fs, `rigidBonds none`,
NPT, ENM + Mg extrabonds), free GPU, startup excluded via `outputTiming`:

| atoms | offload ms/step | resident ms/step | speedup |
|---|---|---|---|
| 32.5k (`2hb_1xT`, relax) | 0.840 | 0.862 | **0.97× — resident LOSES** |
| 32.5k (`2hb_1xT`, k=0 production) | 1.116 | 1.266 | **0.88× — resident LOSES** |
| 111k (`6hbS21_2xT`) | 1.749 | 1.544 | 1.13× |
| 181k (`6hbS42_2xT`) | 3.338 | 2.507 | 1.33× |
| 770k (`6hbx100_90deg`) | 32.10 | 16.16 | 1.99× |
| 3.14M (`VoltronCore`) | 125.6 | 39.0 | **3.22×** (0.69 → 2.21 ns/day) |

**GPU-resident is a LARGE-system optimisation, not a universal default.** Below ~100k atoms
it is a measured *loss*: both modes bottom out at a fixed per-step kernel-launch cost
(~0.84 ms/step at 32.5k) and resident's extra setup is pure overhead there.

**Gate: `_RESIDENT_MIN_ATOMS = 100_000`**, from `psf_atom_count(<stem>.psf)` (streaming
`!NATOM` read — `!NATOM` can sit past 64 KB because psfgen emits one REMARKS line per
patch). Crossover is bracketed by measurement (32.5k loses, 111k wins); 100k sits inside
that bracket near the top, so nothing under-sized regresses and the real win — which only
gets large well above 111k — is fully captured. `n_atoms=None` means *unknown*, not
*small*, and does not block resident.

**PE-independence (a real, separate benefit).** Resident throughput barely moves with core
count; offload needs every core to reach the same floor. 32.5k, ms/step:

| +p | offload | resident |
|---|---|---|
| 2 | 1.576 | **0.838** |
| 4 | 1.132 | 0.852 |
| 8 | 1.002 | 0.871 |
| 16 | **0.840** | 0.862 |

So resident hits the floor on 2 cores and frees ~14 of 16 (Charm++ PEs busy-wait, so the old
path pegged all 16 for the whole ladder). The `+p16` default costs resident ~2.6% at 32.5k —
**retuning thread count per mode is an open, unmeasured lever**, not done here.

Also settled: 3.14M atoms runs resident fine on this native-Linux box (no `cudaMallocHost`,
no exclusion-count failure), so the ~800k pinned-pool ceiling in LESSONS K6 is a **WSL**
property, not a NAMD or GPU one.

**Nothing about the soft integrator forbids resident mode.** One cycle of that exact conf
with `GPUresident on` (`rigidBonds none` + `langevinHydrogen off` + NPT + extraBonds, git
Dec-2025 build) runs clean: `Info: Running with GPU-resident mode`, exit 0, energies
conserved, T flat at 299–301 K, and per-step load balancing gone (2297 LDB lines → 3).

New gate — `fast` no longer appears in it:
```python
gpu_resident = (not gbis) and (not carved or fill_fraction >= _RESIDENT_MIN_FILL)
```
Only two real incompatibilities remain: **GBIS** (no implicit-solvent path in resident mode)
and a **sparse carved cell** (the exclusion-count death above). Minimisation stays offload by
construction — the resident pre-flight probe seeds from its output, so it must run first.

**Companion fix:** `downgrade_gpu_resident` used to always halve the timestep (insurance for
the 4 fs fast path, where 4 fs rides on GPUresident's constraint solver). Applied to a *soft*
resident conf that would give **0.5 fs and double the wall clock of the fallback**. It now
picks the factor from the conf: `rigidBonds all` → 2, `rigidBonds none` → 1 (drop the
directive, change nothing else). Override with an explicit `factor=`.

**Gotcha when hand-writing a probe conf:** `GPUresident` must come **before** `run`. After it,
NAMD treats it as a runtime parameter change and dies with
`FATAL ERROR: Can't modify CUDASOAintegrate when that mode was never enabled`
(already pinned by `tests/test_runpod_bench.py`).

**Not changed: `build_production_conf`'s 1 fs branch still hard-codes offload** — and the
measurement now *supports* that for small designs (32.5k k=0 production: resident 1.266 vs
offload 1.116 ms/step, 13% slower). A LARGE design run at 1 fs production would benefit, but
1 fs production is the rare conservative escape hatch (see `feedback_namd_4fs_production_only`
— 4 fs is the production dt), so it is left alone. Reopen only with a large-system 1 fs
production case in hand.

**Verified end-to-end 2026-07-28:** a conf generated by the real `_segment_conf` gate for the
111k package (not hand-edited) ran on the pinned git build — `Info: Running with GPU-resident
mode`, exit 0, T 298.6 K, no FATAL. Gate decisions on real PSFs: 32.5k → off, 111k / 770k /
3.14M → on.

**Also corrected:** `downgrade_gpu_resident`'s claim that dropping `GPUresident` from a 4 fs
conf gives "instant Constraint failure in RATTLE" is **false when the HMR PSF is in play** —
a 240 ps soak (60k steps, HMR + `rigidBonds all` + 4 fs + offload) ran with T stable at
298–299 K and zero RATTLE failures. Carved confs are therefore written at 4 fs directly.

<a id="chasing-carve--gpuresident-closed-dont-reopen-without-new-information"></a>
- [Chasing carve + GPUresident: CLOSED, don't reopen without new information](details/project_water_shell_carve/03-chasing-carve--gpuresident-closed-dont-reopen-without-new-informa.md#chasing-carve--gpuresident-closed-dont-reopen-without-new-information)

<a id="vram-fix-button-auto-downsize-on-oom"></a>
- [VRAM "Fix" button (auto-downsize on OOM)](details/project_water_shell_carve/03-chasing-carve--gpuresident-closed-dont-reopen-without-new-informa.md#vram-fix-button-auto-downsize-on-oom)

<a id="generalized-size-aware--multi-case-fix"></a>
- [Generalized (size-aware + multi-case fix)](details/project_water_shell_carve/03-chasing-carve--gpuresident-closed-dont-reopen-without-new-informa.md#generalized-size-aware--multi-case-fix)

<a id="shell--nvt-production-path-in-progress-2026-07-02"></a>
- [Shell → NVT PRODUCTION path (in progress 2026-07-02)](details/project_water_shell_carve/03-chasing-carve--gpuresident-closed-dont-reopen-without-new-informa.md#shell--nvt-production-path-in-progress-2026-07-02)

<a id="findings--blocker-2026-07-02-buildrun"></a>
- [Findings + BLOCKER (2026-07-02 build/run)](details/project_water_shell_carve/04-findings--blocker-2026-07-02-buildrun.md#findings--blocker-2026-07-02-buildrun)

## host_oom (pinned CPU RAM) vs vram_oom — 2026-07-07

A NAMD `cudaHostAlloc ... out of memory` (in `ComputeBondedCUDA::copyTupleDataSN`, the bonded-CUDA
tuple staging) is a **host** page-locked-RAM failure, NOT device VRAM — a water carve won't reliably
fix it. `md_vram.classify_failure_log` now disambiguates: `_HOST_OOM_PAT` (cudaHostAlloc|cudaMallocHost|
reallocate_host|allocate_host|copyTupleData) → new `FAILURE_HOST_OOM`; a plain device `cudaMalloc` OOM
stays `vram_oom`. Remedy map: `host_oom → retry` (free RAM + resume, not downsize). Frontend
`md_vram_fix.js` has a dedicated "host (CPU) memory — not GPU" popup. It is usually TRANSIENT (same
alloc succeeded on the prior segment), so `namd_runner` bounded-auto-resumes it (see [[md-job-system]]).

**Host-RAM preflight (2026-07-07):** `md_vram.detect_host_ram_mb()` (/proc/meminfo MemAvailable) +
`max_atoms_for_host_ram` (`_HOST_MB_PER_MATOM=2500`, `_HOST_USABLE_FRACTION=0.6` — COARSE, conservative
toward NOT carving). `auto_water_shell` now sizes the carve to `min(vram_cap, host_cap)` and names the
binding constraint ("host RAM" vs "GPU") in the note; `recommend_downsize` gained a `max_atoms` override.
Only carves genuinely low-RAM machines; adequate boxes unaffected. Tests: `test_auto_water_shell_carves_when_host_ram_tight`,
`test_recommend_downsize_honours_max_atoms_override`, `test_detect_host_ram_mb_*`.
