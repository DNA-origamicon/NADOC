---
name: extra-base-4fs-geometric-fixb
description: "24hb extra-crossover-base 4 fs NAMD: the winning seed is the GEOMETRIC build + Fix B (heavy bases), NOT the oxDNA position-seed. oxDNA seeding was the blocker."
metadata: 
  node_type: memory
  type: project
  originSessionId: 4f290b8b-2035-48ed-882d-40180304acb5
---

# Extra-crossover-base 4 fs NAMD — geometric build + Fix B is the answer (oxDNA seed was the blocker)

**Proven locally end-to-end on the RTX 3080 Ti (2026-07-15), free.** For DNA-origami with
unpaired "extra" bases at crossovers (24hb_1xT: 338 extra T), a stable **4 fs** production step
needs TWO independent things, and the prior oxDNA-seed pipeline got exactly one of them while
*introducing* a fatal problem:

| build | inter-residue ring clash | heavy extra bases (Fix B) | 4 fs result |
|---|---|---|---|
| oxDNA-seeded (`build_ideal_duplex_seeded_model`) | ✗ 0.3 A ring overlaps | ✓ | k=0.1 catastrophe (70× vel) |
| geometric only (`prep_24hb.py --pre-declashed`) | ✓ 0 clashes | ✗ HMR lightens C5' to 8 amu | RATTLE fails at 4 fs hand-off |
| **geometric + Fix B (`prep_24hb_seeded.py --geometric`)** | ✓ 0 clashes | ✓ ×8 heavy | ✅ full ladder + unrestrained MGHH 4 fs |

**Generalizes to ANY declash stem — not just the 24hb.** `prep_24hb_seeded.py <stem> --geometric`
takes the design stem as an argument; `--geometric` ignores the oxDNA-job arg and runs the
geometric build + Fix-B path for whatever stem you pass. Proven 2026-07-19 on **6hb_2xT** (178 k
atoms): the seeded package came back `declash=False, fast_relaxation.enabled=True,
production_timestep_fs=4.0, gpu_resident=True`, Fix-B applied to 48 extra-base residues (×8), gate
clean. This is the sanctioned rescue for any design RunPod would otherwise force to 1 fs (see
`REFERENCE_RUNPOD_RUNBOOK` §0). Small-bundle designs still carry the *separate* exp29 cohesion risk
(`project_md_prep_relaxation`) — geometric+Fix-B fixes the 4 fs integrator, not bundle cohesion; probe
unrestrained-MGHH before committing a production run. **CONFIRMED 2026-07-19:** the 6hb_2xT ladder
ran 4 fs stably to completion (no crash/NaN) but melted at k=0 (C1' → 84 %, delocalized) — 4 fs fix ✓,
bundle cohesion ✗. A valid 4fs build, but NOT a usable free-dynamics validation target.

## ✅ 2026-07-29 — 4 fs runs STABLY on a 1xT design straight off the DECLASH relax (no Fix B, no re-prep)

`2hb_1xT` (32,566 atoms solvated, ONE extra T per crossover), produced directly from the ordinary
**declash** relaxation — no geometric+Fix-B re-prep:

| | ms/step | ns/day |
|---|---|---|
| 1 fs, `rigidBonds none`, offload | 1.086 | 79.6 |
| 2 fs, `rigidBonds all`, GPUresident | 1.365 | 126.6 |
| **4 fs, `rigidBonds all` + HMR, resident OFF** | **0.960** | **~360** |

**COMPLETED 2026-07-29 — all 50M steps = 200 ns, ZERO RATTLE / constraint / fast-atom
failures**, 360.7 ns/day sustained (0.958 ms/step, sd 9e-6), T flat 297.4 → 297.3 K, 13.3 h
wall. Job `29c5b267380f`, 20 000-frame DCD (10 ps) on Archive.
The HMR PSF was **built on demand at production time** from the declash package's own PSF (1086
hydrogens repartitioned) — the relax never made one.
It has since been mined for the equilibrium extra-base pose — see [[crossover-catenation]]
§2026-07-29 and `experiments/exp46_xb_placement/REPORT.md`; note the caveat there that NPT
shrank the carved-shell box **below the solute width** (DNA within 2–3 Å of its own periodic
image for part of the run).

**What this does and does not say.** It does NOT overturn the Fix-B finding above: that was
established on **24hb_1xT (338 extra T)** and **6hb_2xT (48 extra-base residues)**, where HMR
lightening C5' on unpaired inserts broke 4 fs. It BOUNDS it — at *one* extra T per crossover the
unpaired population is too sparse to destabilise the constraint solver, so a small 1xT design needs
no Fix B. Treat Fix B as required above some extra-base density, not for extra bases per se; the
threshold between 1xT/2hb and 2xT/6hb is unmeasured.

**Also note the 4 fs win here is larger than the naive 2×** over 2 fs (2.8×), because the 4 fs conf
also dropped GPU-resident — which is a LOSS below ~100k atoms (see [[project_water_shell_carve]]).
Per-step cost actually fell (1.365 → 0.960 ms) while the step doubled.

> **2026-07-28 — a THIRD, independent defect was found in the same seed geometry.**
> Reciprocal crossover pairs carrying extra bases were built **topologically catenated**
> (Gauss `Lk = ±1`), invisible to every health check here, and unfixable by relaxation.
> The 4 fs work above is unaffected (it is about masses and ring clashes, not topology) but
> **any stiffness number extracted from a pre-2026-07-28 extra-base ensemble is suspect** —
> a pinned junction mimics a soft hinge. See [[crossover-catenation]].
> Also recorded there: the standard prep path calls `write_hmr_psf` WITHOUT `heavy_residues`,
> so **Fix B is applied only by `prep_24hb_seeded.py`** — a job prepped through the UI does
> not get it.

## The two causes (both must be fixed)
1. **Ring clashes.** The oxDNA POSITION seed (`xb_pos_override`) drops each extra base's CM into
   an IDEAL-lattice duplex whose neighbours are NOT at oxDNA positions → the ~6 A aromatic ring
   interpenetrates a neighbour ring at 0.3–2.0 A (10 residue pairs in 1xT, ALL involving a THY).
   Topologically locked: no-ENM minimize opens it only to ~2.0 A; 25 ps soft doesn't move it.
   **The oxDNA CG beads are NOT overlapping** (min CM–CM 2.05 A) — it is a pure BACKMAP artifact.
   Orientation is NOT the cause: forcing the ring to oxDNA's relaxed a1/a3 (verified normal·a3=0.99)
   still leaves 132 clashes; the plain GEOMETRIC bow-out build has **0**. So: drop the position seed.
2. **Fast extra-base modes.** Even clash-free, the extra bases' fast sugar-pucker / thymine-methyl
   heavy-atom modes blow a 4 fs RATTLE step; standard HMR **lightens** those carbons (C5' → 7.98 amu)
   making it worse. **Fix B** = scale the extra-base masses UP (×8, thermodynamically free — Z_config
   is mass-independent, so the measured inter-helix stiffness is unchanged). Without it the geometric
   build RATTLE-fails on an extra-base C5' at the 4 fs hand-off.

## What ships
- `prep_24hb_seeded.py --geometric` — builds the geometric model (no oxDNA override) + reorient +
  separate, then keeps the seeded prep's Fix B (`write_hmr_psf(heavy_residues=extra_base_segid_resids,
  heavy_factor=8)`) + mass-consistent soft + fast 4 fs `pre_declashed=True` ladder. Gate PASS
  (0 coincident, min heavy 0.30 A). Job `83a8ed8ded0e` = the validated 1xT package.
- Supporting (uncommitted): `_min_conf(no_enm=)`, `rebuild_enm_from_min` flag + runner reorder,
  ENM 2.8 A clash floor (`rebuild_declashed_references(min_ang=)`), `atomistic.xb_orient_override`
  + `_oxdna_rigid_frame` a1/a3 path (works but NOT needed — orientation wasn't the problem),
  `prep_24hb.py --pre-declashed`.

## Local probe recipe (free, ~35 min, no RunPod)
Truncated ladder off the fast confs: minimize(no-ENM) → `rebuild_declashed_references` → soft 25 ps →
4 fs k0.5/k0.1/k0.01 → unrestrained MGHH 6k steps. Survival of MGHH (TEMP stays 298 K, TOTAL flat) =
4 fs-production-stable. ⚠ blow-up grep must NOT include bare `inf`/`nan` (matches "Info:").
⚠ GPUresident on the 3080 Ti throws "Low global CUDA exclusion count" (host-specific); the runner's
`gpu_resident_probe` auto-downgrades — a manual probe hits it but it is not a physics failure.

## Open
- 2xT (676 extra, TWO per crossover) — VALIDATED 2026-07-16 (job `336a067ba241`). The geometric
  build DOES have extra-base clashes here (150 inter-res ring + 203 sugar pairs <2.2 A, unlike 1xT's
  0) because the two inserts per crossover stack — BUT the pipeline handles it: both clashing
  partners are FREE ssDNA, so the no-ENM minimise + 25 ps soft relax them apart (unlike the 1xT
  oxDNA case where the partner was a FIXED ideal-lattice duplex base), and Fix B holds the modes.
  Full local 4 fs probe CLEAN through unrestrained MGHH (TEMP 298 K, TOTAL flat). So all three
  variants (0/1/2 xT) reach stable 4 fs via geometric+FixB.
- Supersedes the oxDNA-seed rationale in `experiments/exp43_runpod_bench/PIPELINE_4FS_EXTRA_BASES.md`
  (that doc says seeding is REQUIRED; it is actually counterproductive — update it).
- 0xT NAMD ladder is complete on the volume (job `383f7dcc4a5d`); production not yet run.
- Also delivered: SNUPI FEM + mrDNA CG both ran all three 24hb variants (local, free) — see report.

## SNUPI convergence checker — auto-detect "enough frames", auto-terminate (2026-07-18)
Answers "has the post-equilibration ensemble collected enough decorrelated frames to re-estimate
SNUPI elastic params, and if so stop paying?" Three new files in `experiments/exp43_runpod_bench/`:
- `snupi_bp_observable.py` — DESIGN-FREE per-bp-STEP twist(→GJ)/rise(→EA) from C1' geometry.
  `build_recipe(psf,pdb,ref_coor)` pairs bases (`md_health.build_c1_pairs`), chains consecutive bp
  by midpoint proximity (cKDTree, 2.5–4.5 Å = rise; no cross-helix edges), filters to clean dsDNA
  steps (twist 20–50°, rise 2.9–4.3 Å on a ref frame). **No design.json needed** (these jobs lack one).
  2xT→676 clean steps, 1xT→415. `step_twist_rise` is pure numpy (rotation/translation invariant).
- `snupi_worker.py` — self-contained (numpy + `dcd_fast.py` only, NO MDAnalysis/scipy/repo) so it
  scp's to a bare pod. Reads the GROWING DCD incrementally (persisted JSON state → only new frames),
  emits per-frame pooled |twist|/rise mean+var. `dcd_fast` n_frames from filesize (not header NSET),
  `--safe-back 2` drops the torn tail — works on a file NAMD is still writing.
- `snupi_convergence_watch.py` — periodic daemon. Pod mode: **reconnects per poll** (`_connect_pod`,
  survives 29 h of SSH drops), worker runs on the pod-local DCD (no 100 GB fetch). Local mode:
  subprocess. Convergence per DOF over the post-burn-in ensemble variance V (law of total variance,
  spatial+temporal), split into blocks: **drift** = |linear trend|·span/V < 5% (equilibration gate,
  the primary signal — rel-SEM looks precise while blocks are still marching) AND **rel-SEM** < 5%
  (frame-count sufficiency; ∝ stiffness precision). **Burn-in = max(mean-t0, VAR-t0)** — the variance
  (SNUPI's quantity) plateaus later than the mean; using the mean's t0 leaves the var transient in
  the window and drift stays spuriously high (41%→16% fix on 1xT). Needs `--stable-passes 2`
  consecutive converged polls (both twist AND rise) before acting.
- Running detached: 2xT pod (`en41ygcjicqpvz`/job `dab9e728433e`) with `--terminate` → reaps pod +
  closes ledger on convergence (billing safety; data safe on volume `77pnhye88p`, needs post-reap
  fetch). 1xT local (`f14e00b8cacf`) alert-only (free). Logs+sentinel `snupi_convergence.json` per
  job on Archive. At launch (2026-07-18): 2xT twist drift 1.8% OK / rise 13.3% not-yet; 1xT twist
  22% — its variance is STILL dropping in the last 200 frames (5 ns continuation under-equilibrated).

### ⚠ CRITICAL CAVEAT — the checker validates the WRONG DOF for the deliverable (2026-07-18)
A convergence-timescale investigation (workflow, adversary-verified vs the code) found the checker,
AS BUILT, measures the fast, ALREADY-KNOWN flanking-duplex diagonal — NOT the novel extra-base motif
this whole campaign exists to characterize. The 2xT hit "converged @1.5 ns" for exactly this reason;
**it was DISARMED (watcher 574171 killed) to prevent a premature reap.** Do NOT reap on the current
criterion. The deliverable (`project_snupi_mimic.md:36-41`) is the **Δbase extra-base motif's full
6 anisotropic rigidities + 15 couplings** (twist–stretch ≈ −277 pN·nm) to add as a SNUPI motif class.
Gaps in the current observable (`snupi_bp_observable.build_recipe`):
- **Extra bases are FILTERED OUT** (`exclude_residues=unpaired`; steps across an insert span a chain
  break; no cross-helix edges) → it measures pure B-DNA duplex ARMS, never the insert motif or junction.
- Only **2 of 6 diagonal DOF** (twist→GJ, rise→EA); shift/slide/tilt/roll (shear GAy/GAz, bend EIy/EIz) unmonitored.
- **0 of 15 couplings.** SNUPI k = kT·Cov⁻¹, so dropped twist–stretch (ρ≈0.3–0.5) corrupts even the
  GJ/EA it DOES watch by ~1/(1−ρ²) ≈ 10–25%. The diagonal isn't clean on its own terms.
- **Global pooling**, but SNUPI is per-motif → the (few) insert-context steps are drowned 10:1.
- Block-drift window = post-eq length (~0.8–1.5 ns) → **cannot resolve a τ~10–50 ns anneal** (production
  starts from a restrained ENM endpoint; a restraint-release transient is exactly this failure mode).
Fix: rebuild the observable to INCLUDE the insert + junction co-steps, all 6 DOF + key couplings,
PER-MOTIF pooling, min-post floor ≥ several ns. Expected run length ~10–30 ns (pooled motif 6×6),
NOT 1.5 ns and NOT 100 ns. The DATA in the current DCDs is fine (all atoms sampled) — only the
observable/recipe needs to change; no compute wasted. Machinery (incremental on-pod worker,
reconnect-per-poll, block drift+SEM, burn-in=max(mean-t0,var-t0), daemon/reap) is sound + reusable.
**User chose (2026-07-18) the MOST complete scope: full 6×6 + junction θ, keep both pods running.**

### Rebuild progress (2026-07-18)
- **`experiments/exp43_runpod_bench/snupi_step_params.py` — DONE + VALIDATED.** Full 6-parameter
  bp-step extractor {shift,slide,rise,tilt,roll,twist} via El Hassan–Calladine / CEHS **mid-step
  triad**, numpy-only (on-pod portable). Base frame per bp: ẑ = SVD plane-normal of the 6-membered
  ring (N1,C2,N3,C4,C5,C6 — same names purine & pyrimidine); ŷ = C1'–C1' long axis; symmetrised over
  the pair (flip antiparallel partner's normal). **KEY FIX**: SVD normal sign is arbitrary → orient
  each frame's ẑ along the step direction (o_j−o_i), flip x̂ too (180° about ŷ = bp pseudo-dyad); else
  rise/twist come out symmetric-about-0 (half negative) and only 222/1331 steps survive the clean
  filter. After fix: 870 clean steps, roll std (11°) > tilt (9.3°) = correct B-DNA ordering.
  Validation: analytic round-trip (forward∘inverse) max err **1.2e-13**; ideal B-DNA stack recovers
  rise 3.4/twist 34.3/rest≈0 exactly; real 2xT means all physical. `build_frame_recipe(psf,pdb,ref)`
  emits c1_a/c1_b + ring_a/ring_b (M,6) + steps (S,2). Frame is CONSISTENT (fine for convergence);
  exact 3DNA-standard-frame + SNUPI-convention conversion is a DOWNSTREAM step for final VALUES.
- Crossover-motif geometry RESOLVED (agent, fem_solver.py:483-502,894-925): a crossover motif is a
  bp-STEP-like beam between the TWO crossover-connected bp frames (one per helix), **axial = the
  inter-helix offset** (~1.9-2.25 nm), same 6-DOF schema. So my bp_frames+step machinery handles it.
  local_crossover_extract is NOT reusable (design-bound + GROMACS + 2 scalars only).
- Crossover recipe DONE (`build_crossover_recipe`, DESIGN-BASED): keys off the design's TRUE extra
  bases (`extra_base_insert_keys` → namd_topology.extra_base_segid_resids ordinal bridge), NOT
  all-unpaired (that swept in scaffold ssDNA + bulges → garbage). Finds 330/338 2xT crossovers,
  all len-2 inserts, inter-bp span 18.4 Å ✓. `crossover_params` gives SNUPI-convention 6-DOF: q in a
  fixed per-crossover BEAM frame (axial=ref offset) with **reference-anchored bp normals (z_ref)** for
  temporal sign consistency. Designs: `workspace/24hb_{0,1,2}xT.nadoc` (2xT = 384 xover, 338 w/ 2
  extra T = 676). ⚠ **KEY FINDING — the crossover ROTATIONAL 6-DOF (θ, torsion, bends) is INTRINSICALLY
  NOISY**: base normal from a 6-ring SVD is unstable at distorted junction bases (0.3 Å jitter → θ
  swings up to 100° on some crossovers; θ spans 8-169°). q_axial (stretch) IS robust (18.4±3.8 Å).
  This is the SAME hard/slow junction physics the adversary predicted + the codebase's prior crossover
  work hit (bundle_stiffness gimbal-lock, crossover_parameterization impractical τ). So the crossover
  ROTATIONAL stiffness may not converge at affordable ns; the checker will honestly report it slow.
  Convergence gate → drift-based (robust to the white per-frame normal noise; noise inflates variance
  but adds no drift). Downstream refinement for the noisy rotational DOF: PCA helix-axis frames over
  flanking-duplex windows (robust) or filter to well-formed crossovers via the SVD singular-value ratio.

### DEPLOYED full-DOF checker (2026-07-18) — replaces the wrong-DOF original
- `snupi_worker6.py` (numpy-only, on-pod): per frame emits, per motif, the spatial MEAN(6) + spatial
  COVARIANCE(upper-tri 21) for duplex (frame_step_params) and crossover (crossover_params) + θ.
- `snupi_convergence_watch6.py`: `assess6` accumulates ensemble cov = mean_f[spatial] + cov_f[mean]
  per motif, gates on **drift<5% AND rel-SEM<10% of all 6 eigenvalues** (eigenvalues fold in couplings;
  k=kT·Cov⁻¹). Terminate fires on the CROSSOVER motif (the deliverable); duplex is a sanity check.
  Reuses watch.py's reconnect-per-poll / reap / sentinel. Recipes: `<job>/{1xT,2xT}_recipe6.npz`
  (dup_* + xo_* arrays). Sentinel `snupi_convergence.json` (overwrites the old 2-DOF one).
- **The effective crossover gate is the PHYSICAL TRANSLATIONAL modes** (stretch/shear eigenvalues
  ~1 Å², the genuinely slow junction sampling); the noise-dominated rotational eigenvalues (~7900 deg²)
  pass trivially (low drift, low rel-SEM — the SVD-normal noise is CONSTANT, not decreasing with ns),
  so running longer will NOT fix the rotational stiffness — only the robust-frame refinement will.
  Hence terminating when the translational modes converge is CORRECT (no point paying for rotational
  sampling that can't help). Rotational VALUES need the PCA-helix-axis refinement offline on saved DCD.
- Live (2026-07-18): 2xT pod `en41ygcjicqpvz` --terminate @3.49ns duplex maxdrift 8% / xover 144%
  not-yet; 1xT local alert @3.05ns. PIDs 734812/734813. Old 2-DOF watchers retired. Reap was disarmed
  at 1.5ns "converged" (wrong DOF) — the full-DOF checker correctly reads not-converged.

### Stiffness EXTRACTION findings (2026-07-18) — 2xT pod REAPED @6ns (user call), $0 billing
6ns 2xT trajectory on volume `77pnhye88p` (needs fetch). At reap: duplex translational eigs converged,
rotational 11-15% drift; crossover 5/6 eigs converged, 1 translational @15.6% — CLOSE. Extracted first
6x6 (1xT local, 248 post-eq frames). TWO corrections found beyond the frame:
1. **TEMPORAL, not ensemble, covariance.** SNUPI k=kT·Cov⁻¹ uses the per-STEP fluctuation over time,
   pooled over equivalent steps — NOT the ensemble (spatial+temporal) cov, which conflates fluctuation
   with real step-to-step HETEROGENEITY (crossover-adjacent steps have different equilibrium geometry)
   and over-softens ~4x. Extract = per-step Welford temporal 6x6, then mean over steps. This was the
   BIG fix (duplex twist Lp 14→44 nm; twist std → 5.4°, rise std 0.32 Å, EA 1277-1609 pN — all B-DNA-correct).
2. **Frame for BENDING.** helix-axis ẑ (PCA over ±3 bp window, `bp_frames_h`) fixes twist noise BUT
   over-smooths bending (axis follows curvature → roll/tilt collapse to 0.9°, bend Lp 1307 nm absurd).
   base-normal ẑ (`bp_frames`, 6-ring SVD) CAPTURES bending (roll 7.4/tilt 6.2° realistic) but has
   ~4-5° per-frame noise → rotational Lp 21-29 nm (~2x soft) + couplings noise-corrupted (twist-stretch
   +65, wrong sign vs SNUPI −277). **NEITHER frame is right for all 6 DOF.**
   → **The proper fix is the 3DNA STANDARD reference frame**: Kabsch-fit the idealized base ring geometry
   (Olson 2001 tables, per A/T/G/C) to the actual atoms per base per frame — de-noised (~1-2° residual)
   AND local (captures bending). NOT YET BUILT. Translational stiffness (EA, rise; from precise C1'
   centers) is already ROBUST and frame-independent; only the rotational DOF + couplings need the 3DNA frame.
New geometry: `snupi_step_params.helix_axes/bp_frames_h/build_recipe_full` (helix-axis path);
`bp_frames` (base-normal, has bending but noisy). Recipes `1xT_recipe6.npz` (base-normal), `1xT_recipe6h.npz` (helix).

### 3DNA Kabsch frame attempt + the CONVENTION WALL (2026-07-18)
Built `kabsch_frame_test.py`: rigid Kabsch fit of Olson-2001 idealized base ring coords to actual atoms
(full bp frame = geodesic-average of base I + FLIPPED base II, `_FLIP=diag(1,-1,-1)`). Results on 1xT
duplex (248 post-eq frames, TEMPORAL cov): **twist 5.5° ✓ (Lp 39-43nm), tilt 5.5-6.1° ✓, EA 1071-1210 pN
✓, rise 0.36 Å ✓** — twist + translational RECOVERED. BUT **roll persistently 10-11° (Lp 9nm, ~5x too
soft)** across ALL frame variants (base-normal 7.4°, kabsch-hybrid 10.4°, kabsch-full 11.4°, helix-axis
0.9° over-smoothed), and **twist-stretch coupling keeps WRONG SIGN** (+72..+185 vs SNUPI −277).
**Diagnosis — the analytic self-validation (round-trip 1e-13, ideal B-DNA) proved SELF-CONSISTENCY but
NOT CONVENTION AGREEMENT with 3DNA/SNUPI.** The roll inflation + coupling-sign are a convention/leakage
issue (likely intra-bp propeller/buckle contaminating inter-bp roll, and/or my idealized frame axes vs
3DNA), unresolvable by more frame tinkering. **NEXT: install barnaba (pip, +mdtraj) or real 3DNA to
CROSS-CHECK per-step params on the same frames — the definitive calibration I skipped.** Also: extract
on the FRESH 2xT (better equilibrated than the 1xT reseeded continuation). WHAT'S TRUSTWORTHY NOW: the
TRANSLATIONAL stiffness (EA, shear, rise — from precise C1' centers, convention-independent) + twist;
the extra-base junction EA/shear is a solid first estimate. Roll/tilt couplings await the barnaba cross-check.

### Curves+ CALIBRATION — verdict: use Curves+ as the per-frame engine (2026-07-19)
Installed **Curves+ 3.0.3 from bioconda** (`mamba create -n curves -c bioconda curves`, NO sudo, NO
registration — 3DNA needs a forum download; Curves+ = same Olson/Cambridge step-param convention, is
what Lankáš/Lavery/ABC use per-frame). Binary `~/miniforge3/envs/curves/bin/Cur+`, libs
`~/miniforge3/envs/curves/.curvesplus/standard`. Cur+ input gotchas (worked out): CHARMM prime atom
names → STAR names (C1'→C1*) required (no auto-convert); strand selection lines use SUBUNIT ORDER not
PDB resid (`1:12` / `24:13`); dir flags `2 1 -1 0 0` = 2 strands, +1/-1 = 5'-3'/3'-5'. Helpers:
`extract_duplex_fragment.py` (cut a 12-bp fragment PDB + matching step recipe), `kabsch_frame_test.py`.
DIFF (my base-normal extractor vs Curves+, 1xT 12-bp fragment frame 1128, over the 7 non-broken steps):
**tilt corr 0.85 slope 1.06 ✓, roll corr 0.82 slope 1.17 ✓** (bending convention CORRECT — the roll
"softness" was NOT convention, it was broken steps + frame noise inflating the TEMPORAL variance);
**slide corr −0.41 (SIGN FLIPPED — my ŷ=C1'-C1' opposes Curves+ base-frame y), twist corr −0.22
(UNRELIABLE — base-normal in-plane axis fails on distorted bases), 4/11 steps outright broke**
(twist 76° vs Curves+ 27°). ⇒ **My numpy extractor is NOT accurate enough per-step for quantitative
stiffness; Curves+ is.** PLAN: (1) duplex/regular_bp + nicked stiffness → run Curves+ PER FRAME on the
fetched trajectory (field-standard, clean). (2) Keep my numpy extractor ONLY for the on-pod LIVE checker
(relative convergence, no per-step precision needed) + the crossover TRANSLATIONAL (EA/shear, robust from
C1' centers). (3) Crossover ROTATIONAL: test Curves+ on a 2-bp pseudo-duplex of the two crossover bp
(its cross-helix step) — Curves+ can't do cross-helix natively but may handle a 2-bp fragment. Fragment
was distorted/mispaired (~4/12 WC — build_c1_pairs geometric pairing in a strained origami region);
pick a cleaner fragment next time.
SNUPI itself ran almost NO new MD (reused Bathe-2012 32hb trajectories + 3DNA values); the "100 ns"
is the atomistic-origami VALIDATION lineage (Yoo–Aksimentiev 140 ns, Pan–Bathe 150–500 ns) for GLOBAL
shape/RMSF/collective modes + the slow crossover interhelical angle θ (Pan–Bathe: NOT converged at
100 ns) — a different statistical object than local per-motif stiffness, which does converge fast.

### REFINED 2xT extra_base_co — all 1159 post-eq frames (2026-07-19)
Transfer to home is ~0.9 MB/s (22.85 GB ≈ 7 h — impractical), so `crossover_worker.py` (self-contained
numpy: dcd_fast + snupi_step_params + kabsch_frame_test + recipe npz) runs ON the pod over the volume-
local full 6 ns DCD (1535 frames), returns only the 6×6. `run_xover_on_pod.py` uploads+runs it on the
replica pod. **Result (1159 post-eq frames, frame 375→, vs the earlier thin 168): EA 965 GAy 700 GAz 378 pN
| GJ 27 EIy 27 EIz 13 pN·nm² (wired into snupi_params.json — replaced the 168-frame EA 1439/1032/593).**
KEY: the **ROTATIONAL was ALREADY converged** (GJ 27, EI 13-27 unchanged 168→1159 fr — its variance is
well-sampled: 330 xover × frames; the "slow rotational" worry was overstated). The **TRANSLATIONAL was
the under-sampled part** (EA 1439→965 as the longer window caught more slow junction breathing). Insert-
count trend now clear: **more inserts → softer AXIAL** (1-insert 1xT EA 1664 → 2-insert 2xT EA 965),
rotational similar (both soft hinges ~5-10× under SNUPI single_co). ⚠ Fetch mishap: a fetch process died
leaving pod ou1vxof3z0wwnm orphaned+billing → caught + reaped via a finally-reap fetch. Replica pod
gcptdv331ilquk (5090) ran a 5 ns independent replica; at ~3 ns processed on-pod (`process_replica_and_reap.py`,
124 post-eq frames) then REAPED (finally-reap; nothing billing, all pods gone). **Independent replica
CROSS-CHECK: ROTATIONAL agrees (GJ 24 vs 27, EIz 12 vs 13 — robust, not a single-trajectory artifact).**
BUT it INVERTS the slow-DOF assumption: the **TRANSLATIONAL is the slow-converging one** — short windows
over-estimate EA (replica 124fr→1647, existing first 168fr→1439, full 1159fr→965); EA keeps softening as
the window grows, so **wired EA 965 is the best estimate but likely an UPPER bound** (the junction's slow
AXIAL breathing needs more ns, NOT the rotation). Rotational (GJ 27) is the solid part. Total campaign
billing this session ~$8-12 (2xT replica + fetch pods); ledger `spent()` still inflated from destroyed
pods (cosmetic). To tighten EA: longer 2xT (or pool the 1xT continuation @9ns for the 1-insert axial).

### ✅ Curves+ per-frame pipeline VALIDATED (2026-07-19) — regular_bp recovers B-DNA + correct couplings
`curves_stiffness.py`: pick a 12-bp duplex fragment (geometric pairs, NOT WC-filtered), per DCD frame
write a star-atom PDB + run Cur+ + parse (C) Inter-BP, accumulate per-step TEMPORAL 6x6 cov → k=kT·Cov⁻¹.
**1xT (148 frames): twist std 3.6° roll/tilt 4.9° rise 0.28Å (all B-DNA); twist Lp 103 / bend Lp 51 nm;
GJ 428 EIz 213 pN·nm² (SNUPI regular_bp ~314-400/~246); twist-stretch −205 pN·nm (SNUPI −277 — CORRECT
sign+magnitude).** The roll-soft/coupling-sign saga was MY numpy extractor, NOT the physics. GOTCHAS
(fixed): PDB needs altLoc col-17 space (else 3-char atom names merge into resname); prime→STAR names;
**clean cur* files before each Cur+ run** (Cur+ won't overwrite → failed re-run leaves prev .lis →
identical params every frame = zero variance); singular cov from Cur+ 0.1° rounding → pinv. **SEQUENCE
FINDING: the 24hb build used a NON-design (arbitrary) sequence** — build_c1_pairs pairs are geometrically
correct (WC dist 10.0Å = non-WC 9.9Å) but only 30% resname-complementary (longest WC run 5 bp), so
resname-WC filtering FAILS; pair geometrically → sequence-AVERAGED stiffness (fine for regular_bp family
mean; no per-dinucleotide without the design sequence). 2xT re-fetch running (subset py base64'd to dodge
shell-quoting). NEXT: Curves+ per-frame on 2xT duplex; crossover via Curves+ 2-bp pseudo-fragment OR my
extractor's robust translational.

### RESULTS — 2xT extra-base motif FIRST QUANTITATIVE ESTIMATE (2026-07-19)
2xT subset fetched: `dab9e728433e/2xT_subset.dcd` (2.9 GB, 168 frames, 1.6-3.6 ns window). Pod reaped, $0.
- **2xT regular_bp (Curves+, nbp=8 loosened filter — 2xT is strained, longest clean run ~9 bp):** twist
  34.2° rise 3.37Å; std tilt 5.9/roll 6.8/twist 4.8°; EA 1487 GJ 244 EIy 134 EIz 102 pN·nm²; twist Lp 59
  bend Lp 25 nm; twist-stretch −145 pN·nm (correct sign). **2xT duplex is SOFTER than 1xT (twist Lp
  59 vs 103, bend 25 vs 51)** — physically consistent with the 2× pre-twist strain.
- **2xT extra-base CROSSOVER motif — TRANSLATIONAL (robust, C1'-centers only, no frame noise):** span
  L=1.89 nm (= SNUPI CO axial ~1.9nm ✓); fluctuation std axial 0.64 / perp 0.82,1.06 Å; **EA(stretch)
  1885 pN, GAy(shear) 1167, GAz(shear) 698 pN.** This is the FIRST quantitative estimate of the novel
  motif and REPLACES fem_solver.py:490's placeholder (a translational-only WLC spring, k_rot=0).
- **Crossover ROTATIONAL (torsion/bend) — STILL A GAP.** Curves+ can't do a cross-helix step (fits
  stacked-duplex 3.4Å geometry, not an 18Å junction); my extractor's rotational is frame-noise-limited
  (Curves+ calib proved unreliable per-step). No existing tool does a clean cross-helix 6-DOF. Options:
  (a) build a Kabsch-3DNA-frame cross-helix extractor (started in kabsch_frame_test.py, imperfect);
  (b) accept translational + inherit rotational from nearest published single_co motif; (c) longer/
  better-equilibrated 2xT (won't fix the FRAME limitation, only sampling). TOOLS: `curves_stiffness.py`
  (regular_bp, VALIDATED), the inline crossover-translational extractor. To add the motif to SNUPI:
  new family block in snupi_params.json + classify extra_bases crossovers into it + extend MOTIF_FAMILIES
  (see the earlier fem_solver map). Sequence-averaged only (non-design build sequence).

### ✅✅ CROSS-HELIX EXTRACTOR BUILT + CALIBRATED — extra-base motif 6x6 DELIVERED (2026-07-19)
`kabsch_frame_test.bp_frames_kabsch` = a numpy Kabsch-3DNA base-frame extractor. **CALIBRATED against
Curves+ per-step on the 1xT duplex (`curves_kabsch_calib.py`): ALL 6 DOF corr ~1.0 slope ~1.0** (shift
1.00/1.00, slide 1.00/0.99, rise 0.99/1.01, tilt 0.99/1.01, roll 0.98/1.00, twist 0.99/0.98). KEY FIX:
bp origin = averaged 3DNA base-frame origins (Kabsch-fitted `_kabsch_R` now returns origin), NOT C1'
midpoint (that broke rise corr −0.18→0.99 + slide offset). Unlike Curves+ it works CROSS-HELIX.
`crossover_stiffness_kabsch.py` applies it to the 2xT crossover (330 xovers, 168 frames, L=2.29nm),
measuring the rotational FLUCTUATION relative to each crossover's reference orientation (Rrel_ref) so the
large cross-helix mean angle doesn't ill-condition the log-map. **RESULT — extra-base crossover 6x6:
TRANSLATIONAL EA 1439 GAy 1032 GAz 593 pN (in SNUPI crossover range, ~co_nick), ROTATIONAL GJ 27 EIy 31
EIz 13 pN·nm² (~5-10× SOFTER than SNUPI single_co GJ127/EIy177/EIz147).** THE NOVEL PHYSICS: the unpaired
inserts make the junction a FLEXIBLE ROTATIONAL HINGE (soft torsion+bend) while stretch/shear stay
crossover-typical — exactly what SNUPI's fixed 74-motif set cannot represent + why fem_solver:490's
k_rot=0 placeholder is qualitatively right (rot IS soft) but not zero. CAVEATS: rotational still 32-49°
std → first estimate, and the junction is the SLOW mode (168 frames/1.6-3.6ns may under-sample it, per
Pan-Bathe not-converged-at-100ns); sequence-averaged. NEXT: wire into snupi_params.json as a 6th family
`extra_base_co` + classify extra_bases crossovers into it (fem_solver `_classify_crossovers` + `motif_D`).
