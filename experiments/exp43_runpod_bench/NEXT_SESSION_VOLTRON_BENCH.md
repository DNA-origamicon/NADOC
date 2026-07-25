# Kickoff — VoltronCore full-box GPU-resident RunPod benchmark

Paste the block below to start the next session. All context/decisions from the prior
session are baked in.

---

Benchmark the **VoltronCore** DNA-origami full-box explicit-solvent NAMD relaxation on
RunPod GPUs — **H100 PCIe, H100 SXM, H200** — in **GPU-resident** mode. For each card
report **ns/day, $/ns, and projected wall-clock + $ for the full relaxation ladder**, then
**reap every pod to zero**. Hard budget **$20**.

## Mandatory RunPod discipline — do this FIRST (all free)
- **Read `memory/REFERENCE_RUNPOD_RUNBOOK.md` in full before renting anything.** 11 bugs, 9 silent.
- `RUNPOD_API_KEY=$(cat ~/.runpod_key) python experiments/exp43_runpod_bench/balance.py --require 20`
- Start `experiments/exp43_runpod_bench/pod_watchdog.py --budget 20` in the background BEFORE renting.
- End with `experiments/exp43_runpod_bench/reap.py --kill` and confirm **0 pods**. A pod is the meter; the on-pod kill-switch cannot stop billing. NEVER leave a billing pod (`feedback_runpod_babysitter_must_act`).
- Downloads/scratch → `/media/jojo/Archive`, never the ~92%-full system disk (`feedback_runpod_downloads_to_archive`).
- Judge cards on BOTH `$/ns` AND `ns/day` (`feedback_gpu_value_is_two_axes`).

## Why full box (decided last session)
- `workspace/VoltronCore.nadoc` = 14,774 nt, SQUARE lattice, 59 helices — a **flat plate**, periodic box **830 × 168 × 826 Å**.
- **Full explicit-solvent box = ~11.8 M atoms** (NOT 48.5 M — the auto-sizer's cubic estimate was ~4× high; verified from the real box dims). **Fits an H100 80 GB in GPU-resident mode.**
- The 15 Å water-shell carve (2.85 M atoms) CANNOT use GPU-resident (vacuum corners → "Low global CUDA exclusion count!"), so it runs the slow offload path. Full box is the only way to get the GPU-resident fast path.
- Local build is **RAM-blocked** (11.8 M solvation peaks ~12 GB; the WSL box has ~15 GB free shared + no swap headroom → OOM). **Build on a pod** (ample RAM).

## Build-on-pod plan
1. **Rent one pod with RAM ≥ 32 GB AND a target GPU** (an H100 or H200 — reuse it as the first benchmark card). Prefer a network volume in an H100/H200 region so the 4–5 GB package is written once and the other two cards mount it (no per-pod re-upload). Else container-disk per `bench_anypod`.
2. **Get build inputs onto the pod** (rsync/sftp): `backend/core/` (+ its imports) from the NADOC repo, the CHARMM **forcefield dir**, `workspace/VoltronCore.nadoc`, the oxDNA seed conf at `/media/jojo/Archive/nadoc_oxdna_jobs/5ce768ef2acf/**/last_conf.dat`, and `/media/jojo/Archive/nadoc_bench_pkg/build_voltron_fullbox.py`. Install **GROMACS** (`conda install -c conda-forge gromacs`), **psfgen** (bundled with NADOC's NAMD / in the multi-arch namd tar), and python deps (numpy pydantic scipy …).
3. **Run `build_voltron_fullbox.py` on the pod** → `VoltronCore_fullbox.zip` (~4–5 GB, 11.8 M atoms). It seeds from the oxDNA-relaxed DNA (ssDNA-collapse fix is in `cg_to_atomistic.py` → 0 coincident atoms), full-solvates (`water_shell_nm=None`), 12.5 mM Mg-hexahydrate. **The `write_hmr_psf` >10 M-atom PSF fix is REQUIRED** (added last session in `md_protocols.py` — `_iter_packed_psf_pairs`; without it the HMR PSF step IndexErrors at 8-digit atom indices).
4. **Write `bench.conf`**: derive the header (params / box CRYST1 / PME / cutoffs) from the package's own `*_min_*.conf`, then set **`rigidBonds all` + `timestep 4` + `GPUresident on`**, structure = `VoltronCore_hmr.psf`. Do `minimize 4800` then `run 2000` so NAMD's `Benchmark time:` lines come from the 4 fs dynamics.
   - **⚠ Stability:** a fresh full-box 4 fs run may RATTLE-blow-up on VoltronCore's strain (it did in the shell relaxation). Robust fallback: **benchmark at 2 fs** (`rigidBonds all` + GPUresident, very stable) and report **4 fs ns/day = 2 × measured 2 fs ns/day** — ms/step is timestep-independent (per-step force cost is the same), so this projection is valid. Prefer this if 4 fs is flaky.
5. **Benchmark ms/step** on the build pod's card, then the other two cards. `experiments/exp43_runpod_bench/bench_anypod.py` is the sweep tool — repoint `PKG_TAR` → the VoltronCore bench tar, `WORKDIR=/root/VoltronCore_fullbox`, run `--only "H100 PCIe,H100 SXM,H200 SXM" --budget 20`. It arch-gates before upload (H100/H200 = sm_90 ✓, covered by the staged `namd_cuda.tar.gz`), self-reaps each pod, `pod_watchdog` backstops.
6. **Report** per card: ms/step, ns/day (4 fs), $/ns = 24·$/hr / ns_day, and projected full-ladder wall-clock + $ (ladder ≈ 4 stages × 3 chunks; pull step counts from the package manifest). **Reap → 0 pods**, close the spend ledger, note results in memory.

## Staged artifacts (on `/media/jojo/Archive/nadoc_bench_pkg/`)
- `build_voltron_fullbox.py` — the full-box build script (runs the NADOC solvation pipeline; seed + full solvate + HMR + zip).
- `namd_cuda.tar.gz` (252 MB) — multi-arch NAMD covering **sm_80/89/90/120** (H100/H200 = sm_90 ✓).
- `24hb_0xT_bench.tar.gz` — the existing (different-design) bench package, for reference on the tar layout `bench_anypod` expects.

## GPU prices (bench_anypod `CARDS`, $/hr secure, confirm live at run time)
H100 PCIe **$1.99** · H100 SXM (`NVIDIA H100 80GB HBM3`) **$2.69** · H200 **$3.59**. Balance last checked **$73.45**.

## Prior-session fixes now in the tree (context)
1. oxDNA→NAMD seed **ssDNA-collapse** fix (`cg_to_atomistic.py`, `test_cg_seed_ssdna_collapse.py`) — was the "Bad global angle count" abort.
2. Live-status **`progress_fraction` on the MD status WS** (`ws.py`, `test_md_ws_progress.py`).
3. **RATTLE auto-soften-and-resume** in the runner (`md_protocols.soften_conf_for_stability`, `namd_runner.py`, `test_md_gpu_resident.py`, `test_md_runner_proceeds.py`) — a strained-seed relaxation now self-heals to the 1 fs soft integrator.
4. **`write_hmr_psf` >10 M-atom PSF** fix (`md_protocols._iter_packed_psf_pairs`, `test_psf_packed_bonds.py`).

All four are tested + `just test-smart` green (the 2 `test_atomistic_geometry_lock` failures are pre-existing golden drift, unrelated). No pods are currently billing.
