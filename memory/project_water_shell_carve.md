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
