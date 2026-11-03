# Dev-#4 rollout — divergence diagnosis + fixes (RESULT) — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Dev-#4 rollout — divergence diagnosis + fixes (RESULT)
Diagnosed the one-step model's blow-up: NOT global heating (mean speed flat ~0.52→0.62) but a **single-atom
velocity runaway** — one light/terminal DNA atom's speed grows multiplicatively (5→13→56→1e16→NaN over the
last ~4 steps), invisible until the final doublings (hence "looks great until the last frame"). Cause:
off-distribution positive feedback with no energy conservation / restoring force. `rollout.propagate_trajectory`
+ `write_dcd` (MemoryReader) export VMD-loadable DCDs.
**Fixes applied** (`train(rollout_steps=, noise=, vel_reg=, checkpoint=)`): multi-step BPTT (K=3) + noise
(0.02) + velocity-regularization (penalise speed > 1.5× max true = v_cap 5.94) + gradient checkpointing
(fits full 17,827-atom system in 6.4 GB). **Result: stable horizon 23 → 54 steps (92 → 216 fs, ~2.3×)**,
one-step accuracy preserved (0.010 Å). Still diverges at 54 — same mode, delayed. Remaining levers: longer
K / curriculum on K, stronger vel_reg, more epochs+frames, explicit energy/momentum conservation
(FlashMD-style rescaling), per-atom-type velocity caps. Models saved: `workspace/propagator_pilot/vmd/
model.pt` (one-step), `model_fixed.pt` (fixed). Trajectories on Windows Desktop `gnn_vmd/`
(gnn_traj.dcd = one-step, gnn_traj_fixed.dcd = fixed); load with duplex.pdb (NOT the psf — VMD PSF bug).

## KNOWN BUG (NADOC, flagged): solvated PSF fails in VMD / fixed-column parsers
`namd_solvate._extend_psf` appends water/ion atoms in wider (EXT) columns than the psfgen DNA block while the
PSF header says plain `PSF` (not `PSF EXT`). NAMD reads whitespace-delimited so never noticed; VMD/fixed-column
parsers die at the first solvent atom ("couldn't read atom <n_dna>"). Affects EVERY solvated .nadoc PSF.
Fix: emit `PSF EXT` + consistent column widths. Workaround: use the .pdb as topology.

## New pipeline modules (this session)
- `backend/ml/propagator/local_run.py` — prepare_local_reference (solvate + TRIM the 57 ns ladder to a
  short pilot) / run_prepared_job / captured_outputs. Trim keeps ladder semantics, capture on scale=None
  chunks only.
- `backend/ml/propagator/windows.py` — export_windows: reads pos/vel/force DCDs (force format="DCD" for the
  .veldcd/.forcedcd), DNA-only, min-image-safe, → npz + dataset_manifest. NAMD vel units documented.
- `backend/ml/propagator/baseline.py` — per-element velocity-Verlet fit + zero/inertial baselines,
  temporal split, teacher-forced rollout, report().
- Tests: test_propagator_baseline.py, test_propagator_local_run.py (pure logic; export_windows is
  integration-validated by the pilot run itself). Driver scripts in the session scratchpad.

## Local environment (this machine)
- NAMD3: `~/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3` (CUDA) and
  `.../NAMD_3.0.2_Linux-x86_64-multicore/namd3` (CPU, for GBIS). `namd_runner.find_namd()` resolves them.
- GROMACS `gmx` on PATH (solvation). GPU: RTX 2080 SUPER (8 GB). torch NOT installed.
- Explicit solvent + fast=False → standard CUDA offload (GPU-accelerated, not GPU-resident).

## ROOT CAUSE OF DIVERGENCE + STABILITY STRATEGY (2026-07-19) — governs the current plan
Divergence = **distribution shift**: accumulated per-step error carries the rollout into configs the GNN
never trained on, where it EXTRAPOLATES and error compounds (single-atom runaway is the visible symptom).
Key physics: the true force field is a CONSERVATIVE, attracting vector field with a basin around
equilibrium (base stacking/pairing pull strays back). A displacement-REGRESSOR has NO inherent basin — small
regression errors make a non-conservative field with nothing pulling back. BUT the restoring behavior is
LEARNABLE (implicit in near-equilibrium fluctuation statistics); the model just hasn't seen the off-eq
regime the rollout reaches. **Our training data is absurdly thin (~1 short segment of 1 duplex) — the
dominant limiter.**
**Definition of the goal — "infinite stability" = the model's self-generated rollout is a STABLE INVARIANT
MEASURE matching the training distribution** (it wanders within the trained manifold forever, like true MD).
Achievable in principle (the true propagator has this property); the path is enough data + accuracy that
rollouts stay in-distribution, likely combined with stability-training (multi-step/noise/vel-reg) and
possibly explicit energy/momentum conservation. Pure displacement-regressor + finite data may SATURATE —
that's the empirical question below. (The physically-guaranteed-stable alternative = learn energy/force +
symplectic integrate = the NNP route, but that's the ~25× speed regime we benchmarked.)

## DATA-SCALING STUDY RESULT (2026-07-19) — surprising: more data did NOT help (this regime)
Trained fixed-budget (1200 steps, K=2, noise+vel_reg+checkpoint) on N ∈ {250,500,1000,2000,4000} frames of
the 4 fs data; measured stable horizon H on a held-out rollout (frames 4200+). **H(N): 84, 49, 65, 59, 72
steps — FLAT/NOISY ~50–85, NO clear growth with N.** N=250 gave the *longest* horizon (84). Linear-fit slope
~0 (the script's "GROWS" label is a noise artifact; the 263k-frame extrapolation is meaningless). So in this
regime **the stable horizon is NOT limited by data quantity** — it plateaus ~50–85 steps (200–340 fs)
regardless of 16× more frames. Partially CONTRADICTS the "more fluctuations → stability" hypothesis.
CONFOUNDS (why this is suggestive, not conclusive): (1) fixed 1200-step budget may UNDERTRAIN all models so
none can exploit extra data — need train-to-CONVERGENCE per N; (2) single seed per N → H is noisy (the
50–85 spread may be mostly variance); (3) N range too small (4000 frames ≈ 18 ps is still tiny; plateau may
break at 10^4–10^5); (4) anchor-edge approximation (frame-0/500-step neighbour lists) may degrade training on
later frames. **Implication:** naive "collect more frames" is NOT clearly the silver bullet at this scale →
the limiter is likely model capacity/training AND/OR the fundamental no-basin instability → **explicit
energy/momentum conservation (a learned basin) may be REQUIRED for unbounded stability, not optional.**
NEXT (clean confirmation before concluding): train-to-convergence + multiple seeds + larger N → real H(N).
If still flat → pivot to conservation / force-based. Models saved `workspace/propagator_pilot/vmd/model_N*.pt`;
traj gnn_traj_scaled.dcd (N=4000).
**Longer data READY: job `dbd8ad3b7d4f` (propagator_20bp_long) = 22,500 frames @ 4 fs, 3 continuation
segments (4.8 GB pos DCDs).** MEMORY NOTE: full all-atom export of 22.5k frames × 17,827 atoms × pos+vel ≈
10 GB RAM → the clean-confirmation loader must SUBSAMPLE frames or load in chunks (don't concat all at once).

### QUICK CONSERVATION TEST (2026-07-19) — path (b) VALIDATED, big result
Inference-time physical velocity cap (clamp each atom's speed to 1.2× max-true ≈ 5.07, on the EXISTING
`model_fixed.pt`, no retraining; `rollout(v_clamp=)` + `propagate_trajectory(v_clamp=)`):
**horizon 54 → 200+ steps (216 → 800 fs), NO blow-up.** RMSD@50 identical (0.950) with/without cap → the cap
only fires on the runaway, doesn't touch normal dynamics. **CONFIRMS the single-atom velocity runaway WAS the
divergence mechanism, and a conservation/restoring constraint eliminates catastrophic divergence.** BUT
stability ≠ accuracy: RMSD drifts to 8.2 Å by 800 fs → not exploding, but wandered far from truth. New
frontier = accuracy / MD-statistics matching (the true "stable invariant measure"), not blow-up. Traj:
`gnn_traj_vcap.dcd`.

### NEXT SESSION — START WITH (A), then build trained (B) [user directive]
(A) **Clean data-scaling confirmation** on the 22.5k-frame data (`dbd8ad3b7d4f`): train-to-CONVERGENCE +
multiple seeds + N up to ~20k (subsample/stream loader — 10 GB RAM caveat above), re-measure H(N) to settle
whether the plateau is real or a budget/noise artifact. THEN
(B) **Build conservation INTO training** (not just inference clamp): energy/momentum-conserving velocity
update or a learned-energy/force head + symplectic step, and evaluate on BOTH horizon AND MD-statistics
(RMSF/twist/bp geometry), since the clamp already shows non-divergence is easy but ACCURACY is the real bar.
