# Chasing carve + GPUresident: CLOSED, don't reopen without new information — supporting detail

[Topic head](../../project_water_shell_carve.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Chasing carve + GPUresident: CLOSED, don't reopen without new information

Two leads chased 2026-07-12, both dead:

1. `CudaComputeNonbonded.C:743-750` (the other un-patched `(n-1)/32+1`) — **not on the
   GPU-resident path at all.** `updatePatches()` branches on
   `CUDASOAintegrate && useDeviceMigration`, and that branch already uses the correct
   `computeNumTiles`/`computeAtomPad`. Line 743 is the offload branch. Dead.
2. **The empty-patch mechanism itself is REFUTED for the exclusion bug.** `twoAwayX/Y/Z yes`
   *halves* patch size (⇒ many MORE empty patches) yet the deficit **collapses**:

   | patch grid | patch edge | found / 276956 | deficit |
   |---|---|---|---|
   | 15×4×15 (1-away, margin 4) | ~19 Å | 241,926 | 35,030 |
   | 31×9×31 (twoAway) | ~9.3 Å | 272,177 | 4,779 |
   | 37×10×37 (twoAway, margin 1) | ~7.8 Å | 274,761 | 2,195 |
   | 39×11×39 (twoAway, margin 0) | ~7.4 Å | 275,310 | 1,646 |

   So the deficit is a smooth monotonic function of **atoms-per-patch**, asymptotic to but
   never reaching zero — a capacity/indexing bug in the tile-list build under high patch
   occupancy, NOT empty patches. (`numCalcFullExclusions` = 276,956 is *correct*: it is
   exactly the 1-2 + 1-3 pair count, verified independently = 276,954 ±2. Under
   `exclude scaled1-4` the 1-4 pairs are "modified", not "full".)

**⚠️ Never tune this to "nearly zero" and ship it.** A missed exclusion is NOT a harmless
skip: under PME the reciprocal sum includes excluded pairs, so their real-space correction
must be subtracted — a pair that never lands in a tile list never gets cancelled, leaving an
uncancelled reciprocal-space interaction between bonded atoms. NAMD is right to make it
fatal. A config that gets the deficit to 1,646 would RUN and be silently wrong. Offload is
the only safe answer; the remaining fix is upstream in NAMD's CUDA tile-list kernels.

**Shell evaporation is NOT a problem** (measured over a 240 ps soak): the carved shell
relaxes, it does not evaporate. Waters past 20 Å from DNA stay flat at ~0.03%, past 25 Å at
~0, and the median hydration distance is dead flat (5.40 → 5.37 Å). Only the 15–20 Å band
grows, as the sharp 12 Å carve edge softens to a diffuse ~13 Å edge (carved water expanding
from 1-atm to liquid–vapour coexistence density). Water's 300 K vapour pressure (0.035 atm)
means the vacuum can hold only a handful of molecules; surface tension holds the rest. **No
boundary potential needed.**

The 90° bent 6hbx100 that surfaced all this had a healthy structure (bonds ≤1.73 Å,
exclusions ≤4.24 Å, mgh restraints correct).

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
