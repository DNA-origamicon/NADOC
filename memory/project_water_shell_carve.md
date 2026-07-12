---
name: water-shell-carve
description: NAMD water-shell carve to fit large origami (VoltronCore) on a 12 GB GPU
metadata: 
  node_type: memory
  type: project
  originSessionId: 3e50f67f-227e-4e31-8f9b-c16fbe3f92d1
---

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

## ⚡ SUPERSEDED 2026-07-11: native `gmx solvate -shell` (the carve OOM-crashed WSL)
The fill-then-carve above still **fills the whole box first** — for a 121 nm plate
(GT_corner_v2) that's ~6M waters generated just to keep the shell. Two multi-GB peaks
result: gmx tiling the box, then **Python `_parse_gro` loading the entire full-box
`.gro` → the backend hit 22 GB RSS and OOM-**crashed WSL** twice** (`_carve_water_shell`
runs only after the whole box is already in memory, so it can't prevent the peak).
**Fix:** `_gmx_solvate` now passes `gmx solvate -shell {water_shell_nm}` when a shell is
requested, so GROMACS places ONLY the hydration layer around the DNA — the empty box is
never materialised. The Python carve is skipped on that path (`_carve_water_shell` kept
only for its unit tests + the no-shell fallback). Box/PME/cellOrigin unchanged; the DNA
frame is still the recentred `[0,L]` from `_recenter_pdb_in_padded_box`. Verified: 1hbx300
60,447→15,856 waters (3.8×, `.gro` 8.7→2.7 MB); 2x3x100_Sq 72,797→28,814 (2.2×). The
`.gro` (→ the Python parse) shrinks by the shell/box emptiness ratio — that's the spike
that was killing WSL. NOTE: gmx's OWN peak is dominated by tiling the box and is roughly
UNCHANGED by `-shell` (moderate-box test: 42 MB either way); on a 121 nm box gmx alone
peaked ~15 GB, which SURVIVED before — the crash was the *compounding* Python parse on
top. So `-shell` removes the compound peak; the residual gmx tiling peak on a huge box is
inherent to GROMACS and would need chunked solvation to cut further (not done). Min-image
constraint unchanged (2·shell ≥ 12 Å cutoff → shell ≥ 6 Å). See [[namd-solvate]].

Key knobs:
- `water_shell_nm` (nm) threads: routes_md `CreateJobRequest` → `prepare_mgh_slow_release`
  → `build_namd_solvated_package` / `get_solvation_stats`. Default 0 = off. Use 1.5
  (15 Å); need 2·shell ≥ 12 Å cutoff for valid minimum image.
- Carved cell has **vacuum corners → must run NVT**. `mgh_slow_release_segments(nvt_only=True)`
  is auto-set when `water_shell_nm>0` (an NPT piston would collapse the cell onto
  the DNA image). Stage names keep their `NPT` label for manifest/resume continuity.
- Ion count uses carved **solvent** volume (water_count ÷ 33.4 /nm³), not box
  volume, so molarity stays correct (else ~2× over-salted).

## Follow-up: first-dynamics-stage stability (RATTLE crash)

After the carve let it past minimization, segment 01 crashed at timestep 140:
`Margin is too small for 1 atoms` → `Constraint failure in RATTLE algorithm for
atom N` (a DNA C5'). Cause: a residual local strain in the ideal-B-DNA build that
ENM-restrained minimisation can't fully relieve; 2 fs + `rigidBonds all` explodes
it. NOT carve-related (failing atom is interior, fully solvated).

Fix (implemented): **soft start** — `mgh_slow_release_segments` now marks the FIRST
segment `soft=True` (rigidBonds none + 1 fs) even on the non-declash path; later
segments stay 2 fs rigid. No RATTLE ⇒ no crash; structure relaxes then speed
resumes. Confirmed: VoltronCore reached step 9600 at 298.6 K, stable.

GOTCHA — do NOT add a large `margin`: I tried `margin 3.0` as insurance for the
"Margin is too small" warning; it crashed NAMD's GPU tile-list kernel at startup
(`CUDA error cudaStreamSynchronize in CudaTileListKernel.cu buildTileLists`).
Removed it — default margin 0 + soft start is the working combo. The margin
warning is benign once the soft start removes the instability that caused it.

To reuse a completed minimisation after a mid-ladder fix: regenerate the package
`.conf` files (mgh_slow_release_segments + _segment_conf/_min_conf, **nvt_only=True
for carved jobs**) in place, then POST /api/md/jobs/{id}/start — the runner skips
min when `output/{min}.coor` exists and re-runs from the failed segment.

## VRAM "Fix" button (auto-downsize on OOM)

`backend/core/md_vram.py` detects CUDA OOM in a NAMD log (`log_indicates_oom` =
"out of memory"), reads the card's VRAM (`detect_vram_mb` via nvidia-smi), and
recommends the largest water-shell carve that fits (`recommend_downsize`). VRAM
model: ~3.3 GB/M atoms, 0.85 usable (12 GB ⇒ ~3.16 M atoms max). Carved-atom
estimate = full_water × (shell_volume/box_volume), shell_volume from a coarse KDTree
grid over the DNA — no gmx needed (~1-2 s).

### Generalized (size-aware + multi-case fix)

**Proactive auto-sizing** (`md_vram.auto_water_shell`): at job creation, if the user
left water shell on auto (0), `_prepare_job_bg` estimates the dry system size
(`estimate_profile_from_design`, no gmx — bbox+padding, ~30 waters/nm³) vs detected
VRAM and auto-enables a carve if it won't fit. Stored on `prep_params.auto_water_shell_*`.
So large origami runs first time. Combined with the always-on soft first segment,
most jobs no longer hit OOM/RATTLE.

**Multi-case failure classifier** (`classify_failure_log`): vram_oom ("out of memory")
/ instability ("Constraint failure|Margin is too small|atoms moving") / gpu_error
("buildTileLists|cudaStreamSynchronize|CUDA error", non-OOM) / other. OOM matched
first (it's also a CUDA error). Runner + list-backfill use it.

**Fix endpoint/remedies**: `GET /md/jobs/{id}/fix-advice` → {failure_kind, remedy,
log_excerpt, +downsize recommendation for vram_oom}. Remedy map: vram_oom→downsize
(refit water_shell), instability→gentle (refit `force_soft`=whole-ladder soft),
gpu_error→retry (POST /start resume), other→none (show log). `POST /md/jobs/{id}/refit`
takes optional {water_shell_nm, force_soft, minimize_steps}; `force_soft` threads to
`prepare_mgh_slow_release`→`mgh_slow_release_segments(soft=...)`. CreateJobRequest gained
`force_soft`.

Frontend: `frontend/src/ui/md_vram_fix.js` — `shouldShowFixButton` now shows for ANY
failed job with a failure_kind; `fixMessage`/`openVramFixModal` branch by remedy
(shell input only for downsize; retry→/start; log-tail `<details>`). Tests:
tests/test_md_vram.py (16), frontend md_vram_fix.test.js (25), e2e/md_vram_fix.spec.js.
Real check: 8.86 M-atom job → recommends 18 Å (~3.15 M, ~10.4 GB) on the 12 GB card.

Tests: tests/test_md_water_shell.py, tests/test_md_declash.py. Caveat: under NVT the water beads as a shell
around the (ENM-restrained) DNA with a water–vacuum interface — fine for restrained
equilibration; revisit before long *unrestrained* production (DNA could drift toward
a vacuum corner). See [[md-job-system]] [[exp30-18hb-production]].

## Shell → NVT PRODUCTION path (in progress 2026-07-02)

Goal: long *unrestrained* production on a carved shell to clear >16 ns/day on a
CURVED origami (box mostly empty water; carve follows the molecular surface). Chosen
over full-box NpT (tops out ~12.6 ns/day at 4fs HMR on ~1M atoms / one 3080 Ti — see
[[md-job-system]] production-speed work). Production params also aligned to the
Aksimentiev reference (300 K, langevinDamping 5, piston 200/100, cutoff12/switch10/
pairlist14, PME 1.0, fullElect every 4 fs = fullElectFrequency 1 at a 4 fs HMR step).

**KEY CORRECTION — do NOT delete water in place.** Carved cell can't run NpT (vacuum
corners collapse under the piston) → production must be NVT + a weak DNA COM
restraint. And **re-solvate the RELAXED DNA** through the tested pipeline, NOT delete
far water from the equilibrated ionated box: bulk Cl- (repelled from DNA) + excess
Mg2+ live in that far water, so deleting it strands charged ions in vacuum / breaks
neutrality. `build_namd_solvated_package` re-ionises from the carved solvent volume
(neutrality exact) and already accepts `atomistic_model=` (seed relaxed DNA) +
`water_shell_nm=`. Maps 1:1 onto the paper's pre-production recipe: relax DNA (done)
→ re-solvate w/ shell → minimize → 1 ns solvent equil (DNA position-restrained, NVT,
1 fs) → NVT production + COM restraint.

Build steps:
1. DONE — `backend/core/md_shell_reprep.py` (+ tests/test_md_shell_reprep.py, 5):
   `read_namd_coor(path)` (NAMD binary .coor, endian-auto) + `com_restraint_colvars(
   n_dna_atoms, center, force_constant=1.0)` (3× distanceZ pinning DNA COM over
   serials 1..n_dna — DNA is first in every NADOC PSF; internal DOF free). Colvars was
   NOT previously in the codebase.
2. TODO — `stamp_relaxed_dna_model`: build_atomistic_model(design) then overwrite the
   first n_dna atoms' xyz from the checkpoint .coor (PSF DNA order == model order).
3. TODO — re-solvate: build_namd_solvated_package(atomistic_model=stamped,
   water_shell_nm=1.5, + source job's prep_params; job c89a67841933 = 12.5 mM MgCl2
   screening, no NaCl, padding 1.2).
4. TODO — segment protocol: min → solvent-equil(DNA-restrained, NVT, 1 fs, ~1 ns) →
   COM-NVT production (`colvars on` + `colvarsConfig`), HMR 4 fs.
5. TODO — endpoint (POST /md/jobs/{id}/shell-production or refit variant) + FE button.

Reference: 3x6x200_test, job `c89a67841933` (relaxed to 04_300K_NPT_MGHH_only;
~1.03M atoms full box, 156×89×768 Å).

### Findings + BLOCKER (2026-07-02 build/run)

Built `backend/core/md_shell_reprep.py`: `read_namd_coor`, `com_restraint_colvars`
(3× distanceZ pinning DNA COM by leading serial range), `stamp_relaxed_dna_model`,
`prepare_shell_nvt_production` (orchestrator). Added optional `colvars_file` to
`md_protocols._segment_conf`. Tests: tests/test_md_shell_reprep.py (8, green).

**Reversals learned the hard way:**
1. **Do NOT seed re-solvation from the checkpoint's relaxed coords.** (a) The MD PSF
   is psfgen → hydrogens interleaved, so `build_atomistic_model` HEAVY order (149,750)
   ≠ checkpoint row order (232,109 DNA atoms w/ H): `checkpoint[:n_heavy]` maps garbage.
   (b) The relaxed coords have DRIFTED/spread in the periodic cell → bigger bbox →
   bigger re-solvation box → carve WORSE (745k) than the compact design build (668k).
   → Orchestrator now seeds the **design build** (no stamp); design-strain is relieved
   by the restrained equil, not by coord reuse.
2. **Neutrality needs `require_full_topology=True` + `protocol=EQUILIBRIUM_AWARE`.** The
   default (heavy-atom Python PSF) path left net −11438 e (DA/DC naming, no psfgen
   neutralising Na). With full topology → psfgen (ADE/CYT), netQ **+0.00**. ✓
3. **This structure is COMPACT, not sparse-curved.** 47% bbox occupancy, ~straight
   flat 3×6 bundle (PCA spread 200/38/19 Å). 15 Å shell → 668k atoms = only **1.55×**
   vs 1.03M (NOT the 2.5-5× of a hollow/curved design). Projected ~19.5 ns/day
   (clears 16, modest). n_dna for the colvars range = ATOM-record count in the built
   PDB (232,109 w/ H), NOT the heavy model count.

**BLOCKER — carved min crashes the GPU:** `FATAL ... CudaTileListKernel.cu
buildTileLists ... illegal memory access` at minimize step 1 (both +p8 and +p1).
NOT the margin gotcha (no margin set) and NOT atoms-outside-box (the ORIG full-box
build has MORE atoms outside — 71,874 vs 60,744 — and minimised fine). Specific to
the carved cell's vacuum regions × GPU tile list. VoltronCore reportedly ran carved
(step 9600) so it's structure/config-specific — unresolved; needs dedicated GPU
debugging (try: no-ENM-extrabonds min to isolate; CPU-only min then GPU dynamics;
patch/twoAway settings; or a thin bulk-water margin instead of hard vacuum).

Net: shell is NOT a quick win for a compact bundle. The shipped **full-box 4 fs HMR**
production (12.6 ns/day, paper-faithful) is the reliable path; >16 needs the shell
(blocked) or a 2nd GPU. Scratch build/run scripts under the session scratchpad.

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
