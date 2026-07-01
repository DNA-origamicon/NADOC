---
name: oxDNA CPU benchmark results and recommended settings
description: Timing results for oxDNA MC on U6hb (5036 nucleotides, CPU-only build); recommended step counts and options
type: project
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---
oxDNA installed at `/home/jojo/miniforge3/bin/oxDNA` — CPU-only build (the original CUDA build failed with a CCCL macro conflict vs conda CUDA headers).

**UPDATE 2026-06-22 — CUDA build now WORKS.** Current upstream oxDNA (lorenzo-rovigatti, oxpy 3.7) builds clean with the fully conda toolchain (conda `nvcc` 12.9 + conda-forge g++ 14.3, no system CUDA) on native Ubuntu, RTX 3080 Ti (`sm_86`). The old CCCL conflict is no longer reproducible. CUDA binary at `~/oxDNA/build_cuda/bin/oxDNA` (CPU fallback at `~/oxDNA/build/bin/oxDNA`). VoltronCore (14,774 nt) runs MD on GPU at ~0.59 ms/step. Build: `cmake .. -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 && make -j oxDNA DNAnalysis`.

**The conda `oxDNA` on PATH is CPU-only and was silently shadowing the GPU build** — that's why VoltronCore's relax died at the MD stage with `ERROR: Backend 'CUDA' not supported` (MC stage is CPU so it passed). Fixed: `find_oxdna()` now prefers a CUDA-capable binary (ldd→libcudart probe) over a CPU-only one, so `$OXDNA_BIN` is no longer needed; `oxdna_supports_cuda()` is the probe; `create_oxdna_job` fast-fails a CUDA request against a CPU-only binary; `engines_status()` flags an installed-but-CPU-only-on-GPU engine as `degraded` with a rebuild plan. Diagnose/auto-fix from terminal: `just oxdna-doctor [--fix]` (scripts/oxdna_doctor.py).

**Benchmark: U6hb, 5036 nucleotides, CPU MC (sim_type=MC, interaction_type=DNA2)**

| Steps | Wall time | Time/step |
|-------|-----------|-----------|
| 100   | ~9 s      | 90 ms     |
| 500   | ~27 s     | 54 ms     |
| 1000  | ~49 s     | 49 ms     |
| 2000  | ~95 s     | 47 ms     |
| 10000 | ~437 s    | 44 ms     |

Energy converges by ~1000 steps (E≈0.044 vs final E≈0.042 at 10k steps for the 5036-nucleotide U6hb). Energy at step 0 is very high (backbone-force capped); decays rapidly in first 500 steps.

**Recommended defaults for pre-relax stage:**
- `steps = 1000` — good convergence, ~50 s for a ~5000-nt design; use 10000 for production quality
- `sim_type = MC`, `ensemble = NVT`, `T = 296K`
- `restart_step_counter = true`, `time_scale = linear` — REQUIRED; oxDNA 3.x errors without these
- `verlet_skin = 0.20` — must be > `delta_translation * sqrt(3)` ≈ 0.173; 0.15 errors out
- `max_backbone_force = 5`, `max_backbone_force_far = 10` — caps clash forces during initial relaxation
- `delta_translation = 0.1`, `delta_rotation = 0.1`
- `interaction_type = DNA2`, `salt_concentration = 0.5`

**Why:** `restart_step_counter` and `time_scale` are required by this oxDNA version (3.x); missing them causes immediate parse errors. `verlet_skin=0.20` avoids the "verlet_skin must be > delta_translation * sqrt(3)" error. `max_backbone_force` prevents infinite forces from close contacts at step 0.

**Box sizing:** Use actual backbone position extents + 20 nm margin. For U6hb (5.9 × 6.5 × 140 nm), box = 160 nm (in nm). Code: `max(50.0, extents.max() + 20.0)` from resolved backbone positions. Do NOT use helix axis × 2 — that gave 290 nm which caused oxDNA to segfault during cell init.

**Zero-position overhangs:** Domains that extend beyond `helix.length_bp` (e.g. h_XY_0_3 length=420 but domain goes to bp=422) get no geometry entries. Old fallback was position (0,0,0), which caused segfaults from zero-length backbone bonds. Fix: `_compute_nuc_geometry()` extrapolates along the helix axis for any bp outside the defined range.

**Centering issue:** oxDNA handles negative coordinates correctly via PBC. Do NOT center positions in the box — the CG output coordinate system must match the ideal design coordinate system for axis refitting to work. Applying a centering offset corrupts `_refit_helix_axes` by introducing a ~80 nm shift.

**GPU concurrency (RTX 3080 Ti, measured 2026-06-25 on a 14,386-nt 3x6x400 production):**
Running multiple oxDNA CUDA jobs at once needs NO launch-time setup — each process just grabs
`CUDA_device=0` (NVIDIA MPS would pack kernels tighter but is not required). But the gain is
MODEST, not Nx: oxDNA CUDA is **compute-bound, not memory-bound**. One 14k-nt job pins ~91–96%
SM utilization at only ~556 MiB VRAM (of 12 GB), so a 2nd concurrent job only scavenges the ~4–9%
idle + host↔GPU sync stalls. Measured (1 vs 2 identical concurrent jobs): per-job steps/s
1.7k→1.1k, **aggregate 1.7k→2.2k (~1.3×)**, GPU util 96%→99%. A 3rd job gives ~nothing (already
99%). VRAM headroom is irrelevant (compute is the limit). Unlike GROMACS here (parallel = strictly
worse, see feedback_no_parallel_gromacs), oxDNA does give a small concurrency win — but only worth
exploiting for INDEPENDENT candidates (e.g. a parallel knob/placement search), not a single run.
oxDNA CUDA is single-host-thread: one busy CPU core + the GPU is the saturated, optimal profile;
extra CPU cores do nothing for a CUDA run. The opposite fingerprint (GPU idle, one Python core at
100%) is the `production_rmsf` mean-structure/RMSF evaluation — single-threaded numpy reading the
whole trajectory, the only serial-CPU bottleneck in the autorefine loop.

**Production timing (14,386 nt, CUDA mixed precision, DNA2, dt=0.005, the autorefine full-scale):**
one 10M-step production round ≈ **20–22 min** on the 3080 Ti; a full relax (mc+md_relax+equil) +
4 pooled production rounds (→400 frames at print_every=100k) + evals ≈ **~1.5 h** per autorefine
iteration. Scales with nt × steps; budget accordingly for multi-iteration tunes.
