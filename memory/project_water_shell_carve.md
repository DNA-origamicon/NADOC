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

GOTCHA — do NOT add an explicit `margin`. `margin 3.0` crashes NAMD's GPU tile-list
kernel at startup (`buildTileLists`). This is STILL LIVE and is pinned by
`test_no_explicit_margin_in_configs`. The K2 patch fixes the underlying crash, but the
**3080 Ti box does not have the patched `NAMD_3.0.2p1` built yet**, so an explicit margin
would break there. It is also not a measured win: the 18.8 ns/day carved-offload result
was obtained with NO margin. Tried and reverted 2026-07-12 — don't re-add it without first
building the patched NAMD on both machines.

Defaults raised in `_common_header` 2026-07-12 (margin deliberately NOT among them):
`stepspercycle` 12 → **20**, `pairlistdist` 12 → **13.5**. Carved/offload 16.7 → 18.8 ns/day.
⚠️ `stepspercycle` is duplicated as a constant in TWO places that MUST be kept in sync or
NAMD FATALs at startup on a non-multiple `minimize`/`run` count:
`md_protocols.AKSIMENTIEV_STEPS_PER_CYCLE` and `benchmark_runner.NAMD_STEPS_PER_CYCLE`
(+ `NAMD_BENCH_STEPS`, now 2000 = 100 × 20).

## ⚡ Optimize button (Advanced card) — `backend/core/md_optimize.py`

Automates the carve-vs-GPU-resident decision, because getting it wrong costs either ~35 %
throughput or a crash 40 min into a run. `GET /md/optimize-advanced` → `{recommended,
rationale, warnings, facts}`; the UI (`frontend/src/ui/md_advanced_optimize.js`) shows a
diff + caveat gate and applies only on Proceed.

**Flow:** pre-flight popup (opt out BEFORE the wait) → 3 staged calls with a progress bar
under the Advanced card title → proposal + caveat gate → apply only on Proceed.

**It runs NO simulation and NO benchmark** — say so in any UI copy. It (1) reads GPU/RAM/CPU
(~0.5 s, `GET /md/optimize-advanced/hardware`), (2) builds the design's heavy-atom model and
grid-measures its hydration volume (**~26 s** on a 6hb — the whole reason a pre-flight and a
progress bar exist; scales with design size), (3) scores candidate shells against the STORED
benchmarks above. The two backend calls are split precisely so the progress bar reports a
**real** stage boundary rather than a fabricated animation. The progress element lives
*outside* the collapsible drawer body so it stays visible when the drawer is shut.

⚠️ The busy latch must be set **synchronously, before the first `await`** — the pre-flight is
itself async, so a guard set after it lets rapid clicks stack up several pre-flight popups
(caught by a test; `rapid clicks cannot stack up multiple pre-flight popups`).

**The model.** Throughput ≈ K / N_atoms, with K per code path, anchored on two real
2080-Super runs: GPU-resident 12.8 ns/day @ 747,262 atoms; offload 18.8 ns/day @ 196,606.
⇒ GPU-resident is **~2.6× faster per atom**, so a carve only pays when it removes
> `CARVE_BREAKEVEN` (=K_gr/K_off ≈ 2.6×) the atoms. K is machine-specific; the RATIO — all
the decision depends on — is a property of NAMD, not the card. It reproduces both anchors
and picks correctly by shape: bent 6hbx100_90deg → 12 Å carve, offload, est 18.1 (measured
18.8); straight 6hb_sim_v2 → full box, GPU-resident, est 41.3 (measured 42).

**Shell thickness is PHYSICS, not a speed knob.** Throughput rises monotonically as the
shell thins, so an optimiser told to maximise ns/day will shave the hydration layer to
nothing. First cut of this module did exactly that (picked 8 Å every time). It now FIXES
the shell at `DEFAULT_SHELL_NM` = 1.2 nm and thins it *only* when memory forces it, never
below `MIN_SHELL_NM` = 0.8. Pinned by `test_never_thins_the_shell_for_speed_alone`.

**Audit of the Advanced card (what was missing).** `stepspercycle`/`pairlistdist` are the
knobs that mattered (+12 %) but are now correct defaults and are deliberately NOT exposed —
exposing them invites the `margin` footgun. What WAS missing and is now added: a read-only
**run-path readout** (`#md-jobs-path`, `describeRunPath()`) — GPU-resident on/off was the
single most consequential derived setting and was completely invisible; and the Threads
default was a hardcoded 16 on a 12-logical-core box.

**E2E gotcha (cost an hour).** Backend design state is **per-document**, keyed by the
`X-NADOC-Doc` header that `client.js` stamps on every call. A Playwright `request.post()`
carries no such header → lands in the `__default__` doc → the design loads fine and the
panel still sees *"No active design"* (404). Load the design **through the page** (`await
import('/src/api/client.js'); api.loadDesign(path)`), not via the `request` fixture. Several
existing e2e specs hardcode `:8000` (the user's server) instead of the throwaway `:8002` —
latent, works only because they don't need the design.

ROOT CAUSE — see [[LESSONS]] K2 / **K2b**. The `buildTileLists` illegal access IS fixed
by the patched `NAMD_3.0.2p1_*` build (`tools/namd_tilelist_fix/`, auto-preferred by
`find_namd()`). **But the patch does NOT make `GPUresident` usable on a carved cell.**

## ⚠️ 2026-07-12: A CARVE AND `GPUresident` ARE MUTUALLY EXCLUSIVE (enforced in code)

The p1 build no longer crashes, but the same empty-patch pathology still corrupts the
exclusion accounting: NAMD dies at step 0 with **"Low global CUDA exclusion count!"**
(241926 vs 276956 on the 12 Å-carved 6hbx100_90deg). The structure is *healthy* (all
377919 implicit exclusions ≤ 4.24 Å, max bond 1.7 Å), so the un-found pairs would have
been summed **without** their exclusion ⇒ wrong forces. **NAMD is right to abort; never
force it through** (the check is a `Controller.C` checksum, and `forgiving` mode would
just silently run bad physics).

Ruled out by experiment (RTX 2080 Super, 6hbx100_90deg): the ENM (no effect), HMR (fails
with the base PSF too), coordinates (`wrapAll on` → *identical* count; fails from minimised
coords), the local build (official 3.0.2 binary fails identically), and
cutoff/pairlistdist/margin/stepspercycle (the deficit only closes asymptotically —
pairlistdist 20 still short). **Only water fill fraction moves it:**

| shell | atoms | water fill | GPUresident |
|---|---|---|---|
| 1.2 nm | 196,606 | 22% | fail |
| 2.0 nm | 286,498 | 32% | fail |
| 3.5 nm | 440,965 | 52% | fail |
| 6.5 nm | 655,453 | 80% | **still fail** |
| none (full) | 747,262 | 92% | **pass**, 12.8 ns/day |

Control: `6hb_sim_v2` (uncarved, 90% fill, 225k atoms) runs GPU-resident at 42 ns/day on
the same GPU — so the GPU/driver/build are fine. A carve only ever *saves* atoms on a
**concave** design (a straight bundle already fills its bounding box), and that is exactly
when it creates the vacuum that breaks GPU-resident.

**Consequence (implemented):** `_segment_conf(carved=...)` omits `GPUresident` for any
carved package; it keeps HMR + `rigidBonds all` + 4 fs and runs the standard CUDA-offload
path (nonbonded + PME still on GPU). Because the carve removes ~3.8× the atoms, offload on
the carved cell (**18.8 ns/day**) still beats GPU-resident on the fully-solvated cell
(**12.8 ns/day**). `namd_solvate._render_solvated_fast_namd_conf` does the same for
`namd_fast.conf`.
(Later refined — the blanket "carved ⇒ offload" became `fill_fraction >= _RESIDENT_MIN_FILL`
(0.90), so a TIGHT carved box that the structure still fills keeps GPUresident.)

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
