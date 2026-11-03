# SNUPI convergence checker — auto-detect "enough frames", auto-terminate (2026-07-18) — supporting detail

[Topic head](../../project_extra_base_4fs_geometric_fixb.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
