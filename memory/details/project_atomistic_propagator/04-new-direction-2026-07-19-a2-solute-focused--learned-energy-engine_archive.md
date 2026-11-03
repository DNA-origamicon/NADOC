# NEW DIRECTION (2026-07-19): A2 solute-focused + learned-energy engine (local side project, no git) — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## NEW DIRECTION (2026-07-19): A2 solute-focused + learned-energy engine (local side project, no git)
Reframed after the speed verdict + literature: the goal is NOT faster-than-MD on one GPU
(impossible; see verdicts below) but the UNOCCUPIED niche — a STABLE long rollout reproducing
MD statistics for a SOLVATED DNA duplex/origami. User decisions (2026-07-19, with evidence):
- **Fork A = A2 "solute-focused"** (chosen over full-atom A1). Predict DNA + condensed ion
  shell + first hydration shell EXPLICITLY; bulk water/ions as a Langevin bath w/ correct
  screening. NOT strictly fully-atomistic (implicit bulk) — a deliberate, evidence-based
  relaxation of the earlier north-star.
- **Fork C = learned-energy/force head** (chosen over displacement-regressor + generative).
- **EVIDENCE (species/timescale characterization, `scratchpad/characterize_solvent.py` on the
  20bp duplex 4fs data):** DNA mean|Δx| 0.136 Å/step, VACF τ=8 fs (stiff/vibrational); water
  0.243 Å/step, τ=16 fs; Na+ 18.5% first-shell + **13/54 persistently condensed (<6Å)**; Cl-
  Donnan-excluded (0% first-shell). ⇒ structured DOF (DNA + ~13-40 condensed ions + ~17%
  first-shell water) ≈ **~15% of atoms**; the other ~80% is a fast bath. A2 concentrates
  capacity on the ~15% that carries origami physics. Even more favorable at origami scale.
- **DATA BUG FIXED:** the window export mis-typed CHARMM ions — Na+ ("SOD") → z=16 (sulfur)
  via atom-name guessing (SOD→S; POT→P; CAL→C). Fixed in `windows._element_of` with a
  resname-first `_ION_RESNAME_EL` map (SOD→NA, CLA→CL, POT→K, MG/MGH→MG, CAL→CA). Masses were
  always correct (read from PSF), so the f/m baseline was never corrupted — only the z
  embedding index. `test_propagator_windows.py` 3 green. Now safe for Mg2+ origami (M3).
- **BUILT + TESTED: `backend/ml/propagator/energy.py`** — `EnergyNet` (PaiNN-style SCALAR
  energy → autograd forces F=-∇E, so E invariant / F equivariant to 3.6e-7 = a GUARANTEED
  restoring basin, the fix for the 347× drift), `force_match_loss` (learns the PMF: matching
  E's grad to captured solvent-instantaneous forces recovers -∇W), `langevin_step` (BAOAB,
  unit-correct kcal/mol/Å + amu → Å/fs²). `test_propagator_energy.py` 3 green (invariance/
  equivariance, force-match trains, Langevin stable). This is a machine-learned
  IMPLICIT-SOLVENT DNA force field — the theoretically-correct A2 engine.
- **M1 DONE — PROOF-OF-CONCEPT VALIDATED (2026-07-19).** Force-matched `EnergyNet` on the
  DNA solute (`duplex_dna_forces.npz`, exported via `export_windows` dna_only), Langevin-
  rolled, RMSF vs true. Deliberately TINY model (h32/L2, cutoff 4.5, ~700 frames, 8 epochs)
  → **force-R² 0.92**. Rollout (4000 steps, 2 fs, no clamp): **STABLE, no divergence, physical
  speeds** at both γ=10 and 50. **RMSF ratio 347× (regressor) → 1.45× (energy head, γ=50);
  corr ~0 → 0.38.** So: stability is FREE (energy basin), DNA fluctuation magnitude within
  ~45% of true, spatial flexibility pattern emerging — the A2+energy thesis works; accuracy is
  now a capacity/training problem, not the no-basin wall. Model `energy/energy_dna.pt`, log
  `energy/m1_log.jsonl`, driver `scratchpad/m1_train.py`.
  NUANCE: RMSF is γ-DEPENDENT (γ=10 → ratio 3.8/corr 0.16; γ=50 → 1.45/0.38) ⇒ the learned PMF
  is imperfect (8% force variance unexplained); a perfect PMF would be γ-independent. Next:
  fit γ from bulk-water drag (not hand-pick); bigger model + more data + higher R²; add
  energy-matching/relative-entropy; twist/curvature validation (not just RMSF).
  MEMORY: force-training second-order autograd is memory/compute-heavy — batch×edges is the
  cost driver (B=16 cut6 OOM-thrashed; B=4 cut4.5 peak 0.46 GB, ~43 s/epoch after warmup).
- **M1b DONE — NEAR-QUANTITATIVE at the PHYSICAL friction (2026-07-19).** Scaled the model
  (h48/L3, cutoff 5.0, ~1750 frames, 7 epochs → **force-R² 0.956**), estimated γ from
  Stokes-Einstein (**~147/ps mass-weighted**, NOT hand-picked; DNA-in-water is OVERDAMPED),
  swept γ, added shape validation (Rg + PCA long-axis span). γ-sweep vs true (RMSF 0.379 Å,
  Rg 21.05 Å, span 72.7 Å):
  | γ | RMSF ratio | RMSF corr | Rg ratio | span ratio | stable |
  |10| EXPLODED (1.3e5) |0.05|1564|9471| NO |
  |100| 1.03 |0.50|0.994|0.977| yes |
  |**147 (physical)**| **0.93** |**0.57**|**0.993**|**0.980**| yes |
  |200| 0.84 |0.59|0.994|0.987| yes |
  ⇒ across the PHYSICAL range (100-200/ps): stable, RMSF within ~15% (0.93 at physical γ),
  **Rg within 1%, long-axis span within 2%**, spatial RMSF corr ~0.5-0.6. Only unphysical
  γ=10 explodes (underdamped + imperfect potential). Progression: displacement-regressor
  (corr~0, ratio 347, diverges) → M1 (0.38/1.45, small model γ=50) → **M1b (0.57/0.93 + shape
  ~1% at physical γ)**. The A2+energy+Langevin thesis is now STRONGLY validated for a solvated
  DNA duplex. Model `energy/energy_dna_m1b.pt`, log `m1b_log.jsonl`, driver `scratchpad/
  m1b_train.py`. MEMORY GOTCHA fixed: the val-R² batch (B=64) OOMs the 8GB card via the
  [E,3,H] backward — CHUNK val into B=8, use PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True.
  HONEST CAVEATS: γ-dependence remains (perfect PMF would be γ-independent+stable everywhere),
  so potential still imperfect (physical γ masks it); short-time (4-8 ps) equilibrium only —
  ns slow modes / global bending untested; per-bp TWIST not yet (only global span); ONE
  sequence (transferability untested).
- **M1c DONE — KEY NEGATIVE RESULT: the M1b model is NOT a stable invariant measure; it
  slowly UNFOLDS over tens of ps (2026-07-19).** Ran a long rollout at physical γ=147 with
  drift tracking + a robust twist metric (strand-A C1' cumulative winding around the PCA axis,
  validated on true frames = 35.1°/bp, 3.51 Å rise — textbook B-DNA). Result: **Rg 21 → 119
  (60 ps) → 1852 Å (120 ps)** — MONOTONIC, UNBOUNDED expansion; rise 3.5→7→37; max_speed stays
  physical (~0.06) throughout. So the energy basin stops velocity EXPLOSION but NOT slow
  structural DISSOCIATION. The M1b 8 ps near-quantitative success was REAL but short-time-only.
  ROOT CAUSE: pure force-matching on NEAR-EQUILIBRIUM data never shows the model stretched/
  off-eq configs → its restoring force out there is unconstrained (extrapolation → too soft) →
  the molecule slowly sublimates apart. This is the distribution-shift wall from the original
  (displacement-regressor) handoff, re-appearing in the energy formulation — the basin is real
  but too shallow/wide far from equilibrium. Twist VALIDATION of the model is blocked until it
  stays folded (the metric works; the model doesn't hold structure). Driver `scratchpad/
  m1c_rollout.py`, log `m1c_log.jsonl`. PERF NOTE: single-frame BAOAB rollout is ~5-15 ms/step
  (2 force evals + GPU↔CPU sync for KDTree edge rebuild) → 1 ns ≈ 2 h; rebuild every 100 (not
  25) steps helps. Overdamped Brownian (1 force eval) is the right integrator here (γ high).
- **NEXT = M1d (fix the unfolding): DELTA-LEARNING on a physical baseline.** E = E_baseline +
  NN_correction so the structure physically CANNOT dissociate. Options: (a) harmonic BONDS from
  the PSF `bonds` array (already exported) — light, guarantees each strand stays a chain, but
  inter-strand (base-pairing) still learned; (b) full classical CHARMM FF (bonds+angles+
  dihedrals+LJ+elec, no PME for the 1266-atom solute) as baseline → inherits ALL classical DNA
  stability, NN learns only the solvent-PMF correction (needs OpenMM-style eval wired). Then
  re-run the M1c ns/twist validation. AFTER M1d: M2 (condensed ion + hydration shell) → M3 (6hb
  crossover, job f716e1f42b9b, ion typing FIXED for Mg2+). Multi-sequence transferability is
  DATA-BLOCKED (needs new short MD on other sequences — cheap, ~15 min GPU each via local_run).

## M1d — DELTA-LEARNING (CHARMM baseline + NN) FIXES UNFOLDING (2026-07-19)
E_total = classical CHARMM(vacuum DNA-only) + NN(solvent-PMF correction), force-matched to
the RESIDUAL (F_true_solvated − F_baseline). Baseline via OpenMM+ParmEd (`duplex.psf` sliced
`@1-1266`, `par_all36_na`), rollout = BAOAB Langevin at physical γ=147 with HMR (H→3 amu).
- **Baseline explains 94% of |F|**; NN learns 74% of the residual → ~98% total force accuracy.
- **Baseline-only rollout STAYS FOLDED** (Rg 21→21.7/12 ps) — supplies the confinement pure-NN
  lacked. This is the KMMD approach (learned correction to classical FF).
- **E_total rollout 200 ps: STABLE + FOLDED + twist 35.07°/bp (true 35.14 — EXACT).** Fixes the
  M1c catastrophe (pure-NN unfolded to Rg 1852). BUT residual slow SWELLING: Rg ratio 1.16,
  drift +3 Å/200 ps; that slow drift inflates long-window RMSF (ratio 4.9, corr 0.09 — NOT the
  8 ps equilibrium RMSF). So folded+twist-correct+stable, but NOT yet a perfect invariant
  measure. CAUSE: vacuum baseline has no solvent cohesion → gently expands; NN under-corrects.
  FIX (next): **GBSA implicit solvent in the OpenMM baseline** (`implicitSolvent=OBC2`, one flag
  — adds cohesion/screening classically) and/or higher-R² NN. Model `energy_dna_m1d.pt`, log
  `m1d_log.jsonl`, driver `scratchpad/m1d_train.py`, baseline test `m1d_baseline_test.py`.
- **BENCHMARK (DNA-only 1266-atom solute, RTX 2080): the NN — not OpenMM — is the bottleneck.**
  OpenMM CHARMM baseline **3.85 ms/call on CPU** (fast! GPU-OpenMM would save ~nothing; pip
  openmm wheel has NO CUDA platform anyway, only CPU/Reference). NN force eval (fwd+autograd)
  **13.7 ms**; radius_edges 1.2 ms; full BAOAB step (2×base+2×NN) 29.6 ms; **force-cached step
  (1×each) 14.8 ms = free 2×**; training step (B=4 2nd-order) 137 ms. → speedup work = (a)
  BAOAB force-caching 2×, (b) NN opt (torch.compile/fp16/fused-scatter of the memory-bound
  [E,3,H] tensor). OpenMM stays CPU. torch, openmm, parmed all now installed in the venv.

## UNCERTAINTY TRACK (dev #6) STARTED — deep-ensemble uncertainty is CALIBRATED (2026-07-19)
The 2nd co-equal MVP capability. BLADE's baseline (CHARMM+GBSA) is EXACT → all epistemic
uncertainty lives in the ~6% ForceNet correction. A DEEP ENSEMBLE of K independently-seeded
ForceNets gives per-atom uncertainty = RMS spread of members' force vectors. Machinery:
`backend/ml/propagator/uncertainty.py` (`EnsembleForceNet` → (mean, per-atom unc);
`calibration_score`, `reliability_curve`), `test_propagator_uncertainty.py` (4, slow-marked).
- **RESULT (K=5, duplex): uncertainty IS calibrated.** Per-atom Pearson(unc,err) **0.45**,
  Spearman 0.36, reliability curve MONOTONE (0.78 per-atom / 1.0 pooled): uncertainty bins
  0.41→0.95 map to error 1.8→4.8 (**2.6× error spread** low→high uncertainty). Ensemble-std
  genuinely predicts where the correction is wrong. Ensembling barely improves accuracy (+2%)
  — the value is the SIGNAL, not accuracy. Driver `scratchpad/ens_calib.py`.
- HONEST: moderate (0.45) because the duplex is HOMOGENEOUS = the hard case (no novel sites to
  disagree about; signal from ends/rare configs only). The MVP payoff is LOCALIZATION on
  HETEROGENEOUS structures — uncertainty should spike at crossovers / skip-junctions, not smear.
  NEXT: 6hb localization (uncertainty at crossovers vs interior), then the curved-6hb skip sites
  (the demo: BLADE says "I don't trust the junctions" and is right → propose local-MD region, dev #9-11).
- **NOVELTY DETECTION works (2026-07-19):** duplex-trained ensemble evaluated on the 6hb is
  **1.55× more uncertain** (mean 0.86 vs 0.55; p95 1.73 vs 1.06; max 5.7× median) → it correctly
  flags the crossover structure as out-of-distribution. Driver `scratchpad/localize.py`.
  NUANCE: my spatial-COMPACTNESS metric said "not clustered" — but that's the WRONG test for the
  6hb: its 15 crossovers are DISTRIBUTED along the ~100 bp length, so the uncertainty is correctly
  spread to them, not compact. A "localize to a COMPACT region" demo needs a structure whose
  novelty is compact = the CURVED 6hb skip-junction bend (localized + has a real reference). The
  straight 6hb was never the right localization target. Proper crossover-atom localization (map
  crossovers→atoms, unc at crossover vs interior) deferred — the curved case is the real payoff.
- **STATUS of uncertainty track: machinery built+tested, calibration proven, novelty-detection
  proven.** Awaiting the curved-6hb force dataset (other computer / RunPod) for the localization
  demo + dev #9 (propose local-MD region at the uncertain junction).
