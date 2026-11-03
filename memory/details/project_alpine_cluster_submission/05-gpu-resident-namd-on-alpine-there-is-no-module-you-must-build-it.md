# GPU-resident NAMD on Alpine: there is no module, you must build it (2026-08-07) — supporting detail

[Topic head](../../project_alpine_cluster_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### GPU-resident NAMD on Alpine: there is no module, you must build it (2026-08-07)

**The failure.** SLURM 30948986 (24hb_0xT) died instantly: `Lmod ... The following
module(s) are unknown: "namd/3.0.1_gpu"`. That string was never real — the profile comment
said outright it was a guess from the `_cpu`→`_gpu` convention. July's jobs worked because
they were CPU; this was the first GPU submission, so the guess was exercised for the first
time. Cost: an 814 MB upload and a queue wait to learn about a typo.

**Live cluster facts (probed 2026-08-07 — do not re-derive):**

| | |
|---|---|
| NAMD modules | `namd/2.14`, `namd/3.0.1_cpu` — **no CUDA build exists** |
| OS / glibc | RHEL 8.10, **glibc 2.28** |
| CUDA modules | 11.2, 11.3, 11.4, 11.8, **12.1.1** (newest) |
| GCC modules | 10.3.0, 11.2.0, 13.2.0, 14.2.0 |
| FFTW | 3.3.8 / 3.3.9 / 3.3.10 |

**Three consequences, each load-bearing:**
1. **A desktop binary cannot be uploaded.** The local Dec-2025 build needs GLIBC_2.38 vs
   Alpine's 2.28. Not a near miss — building on the cluster is mandatory.
2. **CUDA 12.1.1 caps the targets.** sm_80 (aa100) ✓, sm_89 (al40) ✓, **sm_90 (ah200) ✓**,
   but **sm_120 (artxpro6000, Blackwell) needs CUDA ≥ 12.8 → cannot be targeted at all**.
   ah200 is therefore the GPU target, which is also the fastest and least contended.
3. **nvcc 12.1 rejects GCC > 12.2**, so the profile's `gcc/14.2.0` cannot build CUDA. Use
   **`gcc/11.2.0` + `cuda/12.1.1`** — and per CURC's own rule the sbatch must load the same
   set, so `gpu_module_loads` must match the build exactly.

**CURC endorses building** ("begin a compile job by using the `acompile` command"); nothing
discourages user-built software. `acompile` has no GPUs (4 cores/12 h) — fine, `nvcc`
cross-compiles — so NADOC submits the build as a normal `acpu` batch job instead, which
survives disconnection and logs.

**What was built for this** (all tested, `main.js` untouched):
- `ClusterProfile.namd_bin` / `gpu_namd_bin` + `namd_command(gpu)` — a private build is
  addressed by absolute path since it is on no module's PATH. Reaches both the real sbatch
  and the wizard preview; the "CPU-looking module" warning self-suppresses for private paths.
- **Submit pre-flight** (`md_executor.submit_job`): `module load … && command -v <namd>` on
  the LOGIN node before staging. Catches both a bad module and a module set that loads fine
  while leaving no `namd3` — Alpine's normal state for GPU. Fails in ~2 s with nothing uploaded.
- `list_namd_modules` now loads a compiler first and falls back to `module spider`: Alpine's
  Lmod is **hierarchical**, so the old bare `module avail namd` returned EMPTY precisely when
  it was needed.
- `GET /cluster/probe` — read-only, a **named registry** (`os`, `modules`, `cuda-compilers`,
  `gpu`, `squeue-mine`, `job`, `sinfo`), not an allowlist over free text; `arg` validated to
  `[A-Za-z0-9_.+/-]{1,64}`. A test asserts every probe is non-mutating.
- `backend/core/cluster_build.py` + `POST|GET /cluster/build/namd` — packs the source
  (dropping the local build tree and `.git`: 618 MB → 89 MB), uploads, and submits a
  generated build script. Also not a shell: every module/gencode/name is validated and
  writes are confined to `<project_base>/nadoc_builds/<name>`.

**When the build lands**, it is a two-line `workspace/clusters.json` edit:
`"gpu_namd_bin": "<build_dir>/<src>/Linux-x86_64-g++/namd3"` and
`"gpu_module_loads": ["gcc/11.2.0", "cuda/12.1.1"]`.
