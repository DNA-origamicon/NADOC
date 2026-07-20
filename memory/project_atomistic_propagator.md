---
name: atomistic_propagator
description: Loop head + handoff for the learned atomistic-propagator MVP (NAMD-surrogate + uncertainty). Resume from HANDOFF.
metadata:
  type: project
---

# Atomistic Propagator MVP — Loop Head & Handoff

**This file IS the loop head — read the HANDOFF section to resume; any session can pick up from there.**
Detailed design lives in the plan `~/.claude/plans/minimum-viable-atomistic-mellow-manatee.md`
(machine-local, not committed) + the full spec the user pasted. This head is the shared, tracked state.

## OVERARCHING GOAL (user spec, 2026-07-18) — the north star
A **machine-learned atomistic simulation engine for DNA origami**: generate FULL atomistic trajectories
(DNA + water + ions) substantially faster than conventional MD, **while explicitly reporting where its
predictions are trustworthy**. Learn a time-propagation operator on coordinates AND velocities. NAMD stays
the reference + fallback. **Must remain fully atomistic at all times** — NOT coarse-grained, NOT a relaxation
predictor, NOT a force-field replacement, NOT backmapping, NOT a static classifier, NOT next-structure-only.

**Two MVP capabilities (co-equal):**
1. **Atomistic time propagation** — train on canonical solvated duplexes; achieve STABLE short
   autoregressive trajectories faster than NAMD (conservative intervals OK; large speedup not required
   initially). Measure where error accumulates.
2. **Calibrated uncertainty** — train with a motif (e.g. DNA bulge) WITHHELD; on a duplex containing it,
   stay confident on ordinary duplex, raise uncertainty LOCALIZED to the bulge + its neighboring
   DNA/water/ions, don't flag the whole box, and emit a proposed region for local NAMD verification.
   (So the withheld bulge is BACK — as the uncertainty test motif, not a scientific target.)

**Long-term:** global ML propagator + uncertainty-triggered LOCAL conventional MD correction →
active-learning loop (propagate → detect uncertainty → local MD → learn → less future fallback).

**Development order (prioritize):** (1) auto NAMD system gen [DONE], (2) reference trajectory storage +
preprocessing [DONE: windows.py], (3) simple atomistic propagation baseline [DONE: baseline.py], (4) STABLE
AUTOREGRESSIVE ROLLOUT [next], (5) quantitative vs NAMD [speed benchmark in progress], (6) ensemble/
multi-signal uncertainty, (7) calibrate predicted vs measured error, (8) spatial uncertainty viz, (9) auto
local-MD region selection, (10) short NAMD verification windows, (11) local correction + motif learning.

**Validation must eventually reproduce MD STATISTICS** (bp/backbone geometry, bend/twist, solvent+ion
distributions, thermal fluctuations, relaxation, time-correlation, free energy of CVs) — distinguish
short-time coordinate / long-time ensemble / dynamical / observable-specific accuracy. A visually plausible
trajectory is NOT sufficient.

**Reconciliation with current work:** the immediate "predict next standard step faster than MD" question
below is exactly MVP-1's propagation kernel at conservative interval. "Full atomistic incl. water+ions" means
the DNA-only export was a shortcut — the real model propagates all atoms. Rollout stability (dev #4) + the
uncertainty track (dev #6-8) are the two big pieces NOT yet built.

## What it is (immediate framing)
A learned time-propagation operator that advances a fully-atomistic DNA–water–ion system. In-repo at
`backend/ml/propagator/`.

**IMMEDIATE QUESTION (MVP-1 kernel; conservative interval):**

> **Can we build a propagator that predicts the next STANDARD MD timestep (1–4 fs) FASTER than full MD?**

NOT large steps. The propagator does ordinary-size steps (4 fs is fine; MD runs 1–2 fs) but **skips the
per-atom force calculation**, instead mapping each atom's LOCAL ENVIRONMENT → a probability distribution of
where it lands next step. Win = COMPUTE per step, not step size.

Why this is the right framing: staying at a native/near-native step **sidesteps the aliasing wall** that
killed the 20 fs deterministic map (fast vibrations are RESOLVED at 4 fs, especially with rigidBonds/rigid
water already on) → next-step prediction is tractable. So the problem splits cleanly:
- **Accuracy half (easy-ish):** can a local model predict the next 4 fs step well? (skill should rise sharply
  vs the 20 fs case — the in-progress 4 fs run + subsample-down sweep quantifies this.)
- **Speed half (the CRUX):** can the learned local predictor be CHEAPER than a classical FF force eval?
  Classical MD force eval is already very cheap; ML force fields (MACE/Allegro/NequIP) typically run MD
  10–100× SLOWER than classical FF (their win is replacing ab-initio, not classical FF). The literature's
  per-step speed wins come from LARGER steps (rejected here) or expensive reference FFs. **Plausible
  real-win regimes to target/measure: (a) avoiding PME/global electrostatics on huge solvated ORIGAMI
  (10^5–10^6 atoms) with a local-cutoff GNN; (b) predicting Δx DIRECTLY (skip both force eval AND
  integration); (c) GPU-batched amortization.** Must be BENCHMARKED, not assumed — get real per-step
  wall-clock: learned local predictor vs the NAMD force+integrate cost, on this system and extrapolated.

The eventual scientific payoff is still duplex fluctuations → crossovers → origami, but the immediate,
testable deliverable is the accuracy+speed feasibility of a native-timestep learned integrator.

## Locked decisions / invariants (don't drift without sign-off)
- **ML code is in-repo** (`backend/ml/propagator/`); torch/e3nn stay an OPTIONAL dep — the core app +
  fast test suite must never import them.
- **Reference trajectories capture positions + velocities + forces** per frame.
- `capture_vel_force` defaults **False** everywhere; only `prepare_propagator_reference` turns it on.
  Ordinary MD jobs must stay byte-identical. **velDCD/forceDCD cadence == position dcdFreq** (frame
  alignment) — an invariant; never let them diverge.
- **Reference protocol = 2 fs, NO HMR, full topology** — HMR + rigidBonds/4 fs distort the microscopic
  dynamics the model learns.
- **Split assigned per system / motif family at generation** (`systems.py`), written into `system.json`,
  **never re-sampled downstream** — frames from one duplex must not straddle train/test.
- **Progression: short duplex → crossovers → origami.** Start on a short duplex (fluctuation MVP), then
  add crossovers (the actual scientific interest), then scale to 6hb/18hb origami. Prove each rung before
  the next.
- **MD substrate = explicit water + ions, run LOCALLY on the GPU** (user decision 2026-07-18). NAMD3 CUDA
  build; capture path already wired via `prepare_propagator_reference`. (Implicit GBIS was the alternative
  — rejected: artificial Langevin damping.)
- **Bulges DEPRIORITIZED** — rare in origami; `bulge_duplex()` stays an unimplemented stub. Not the driver.
- **First propagator has NO torch dep** — torch is not installed; start with a numpy inertial/ridge
  baseline to get a real "how well" number, add torch (equivariant net) only once the loop is proven.

## Current state (2026-07-18)
- **1a DONE + tested** — gated per-frame velocity/force output. Helper
  `namd_helpers.vel_force_dcd_block`; threaded through `_render_namd_conf`,
  `namd_solvate._render_solvated_fast_namd_conf`, `md_protocols._segment_conf` →
  `prepare_mgh_slow_release(capture_vel_force=…)`. New `PROPAGATOR_REFERENCE_PROTOCOL` +
  `prepare_propagator_reference()`. Manifest records `capture_vel_force` + `files.velocities/forces`
  globs. Test: `tests/test_propagator_vel_force_capture.py` (9). NOTE: only render/alignment-verified —
  a real short run must still confirm `.veldcd`/`.forcedcd` are written + MDAnalysis frame-matched.
- **1b DONE + tested** — motif generator `backend/ml/propagator/systems.py`: `canonical_duplex`,
  `nicked_duplex` (staple nick, stays single-scaffold), `mismatch_duplex` (one non-WC pair). Provenance
  metadata → `system.json`, deterministic ids, `default_catalog()`, `write_catalog()`. Every design gated
  through `assert_roundtrip_stable`. Test: `tests/test_propagator_systems.py` (8).
- **Bulge DEFERRED** — awaiting user's construction (see invariants).
- **1c / 1d / 1e / 1f NOT STARTED.**

## Key entry points (reuse, don't rebuild)
- Capture: `backend/core/md_protocols.py` → `prepare_propagator_reference`, `PROPAGATOR_REFERENCE_PROTOCOL`;
  `backend/core/namd_helpers.py` → `vel_force_dcd_block`.
- Generator: `backend/ml/propagator/systems.py`.
- Solvate (1 call → zip): `backend/core/namd_solvate.build_namd_solvated_package(design, …)`.
- Job/run: `backend/core/md_job.new_job`, `namd_runner.start_job`; outputs in `package_dir/output/`.
  Route multi-GB output to the Archive drive via the job `run_dir` (`routes_md._apply_run_dir`).
- Trajectory read: `backend/core/md_trajectory._build_md_nadoc_ctx` (MDAnalysis PSF+DCD;
  `with_atoms=True` gives heavy-atom index+elements); `dcd_fast` for raw reads.
- Analysis (1e reuses): `md_rmsf`, `md_metric_series` (twist/curvature/base-pairing per frame),
  `bp_analysis` (C1′–C1′), `shape_metrics`.
- Oracles: `tests/automation_harness.py` (`assert_roundtrip_stable`, `geometric_nucleotide_count`).
- Existing 6hb/18hb builders (for the later scale-up): `tests/conftest.py` `make_6hb_design`,
  `make_18hb_design` → both delegate to `headless_build.build_bundle`.

## Pilot RESULT (2026-07-18) — local duplex-fluctuation propagator loop CLOSED end-to-end
A 20 bp explicit-solvent duplex (150 mM NaCl, TIP3P, ~17.8k atoms) ran locally on the GPU
(job `f6b191b31c33`, all 12 trimmed segments completed), capturing pos+vel+force at 20 fs on the 3
unrestrained production chunks → 1800 frames, 1266 DNA atoms exported to
`workspace/propagator_pilot/duplex_20bp.npz` + `dataset_manifest.json`.
Basic propagator (Δx ≈ a·v + b·f/m, per-element scalars; numpy, no torch) one-step results:
- mean true 20 fs displacement 0.164 Å; **zero-motion 0.164, inertial v·dt 0.316 (OVERSHOOTS), fitted
  global 0.148, per-element 0.143 Å** (skill vs zero-motion: global 0.10, per-element 0.13).
- **Key physics:** v·dt overshoots because stiff-bond vibration (C–H ~10 fs) reverses motion within a
  20 fs step → velocity poorly predicts net displacement. Per-element fitted vel coeff a: **H 0.011** (most
  vibrational), C 0.085, N 0.139, P 0.123, **O 0.197** — clean decorrelation ordering. velDCD units
  confirmed NAMD-internal (0.718 × 20.45 = 14.7 Å/ps ✓ physical). Teacher-forced 50-step rollout: 0.91 Å RMSD.
- **Takeaway:** a global/per-element *linear* propagator barely beats "nothing moves" at 20 fs — most
  per-atom motion is fast local vibration a scalar model can't resolve. This is the honest MVP floor and
  motivates: (a) an equivariant GNN that sees local bonding, (b) a shorter macrostep (10 fs), and/or
  (c) heavy-atom / rigid-H treatment. NEXT rung = crossovers, then origami.
- **4 fs run (job 95d4b7d8fa46) — ACCURACY HALF ANSWERED.** Captured at 4 fs (dcd_freq=2); sweep 4→20 fs:
  dt=4 fs → per-element velocity-Verlet one-step RMSE **0.004 Å vs 0.059 Å displacement, skill 0.929**
  (even pure inertial v·dt 0.025 beats zero 0.059 — velocity is predictive again). 8 fs skill 0.72, 12 fs
  0.46, 20 fs 0.13. So **at a native/near-native step the next step is nearly trivially predictable** (it's
  essentially the integrator). The reframe (predict next STANDARD step, not a large step) works.
  CAVEAT: the 0.004 Å model uses the TRUE force in b·(f/m). Velocity ALONE (no force) gives 0.025 Å — the
  learnable/expensive part is the FORCE correction (0.025→0.004). The propagator must predict that local
  force-correction from GEOMETRY, cheaper than computing it. → that is the actual model to build + benchmark.
- **Speed baseline (real, from NAMD logs, job f6b191b31c33):** full step (force+PME+integrate) = **~7.5 ms/step
  for 17,827 atoms** on the RTX 2080 (16 CPU + standard CUDA), PME grid 32×32×64 (~0.42 µs/atom/step). This
  is the number to beat. Honest read: beating a CLASSICAL FF per-step is hard (accurate NNPs like MACE run
  MD 10–100× slower than classical FF); the clear win regime is ORIGAMI SCALE where PME/global electrostatics
  dominate and a local-cutoff GNN avoids them. MUST benchmark GNN forward-pass vs 7.5 ms + extrapolate vs N.
- **Macrostep sweep** (coarsen existing 20 fs data by subsampling — `baseline.macrostep_sweep`):
  per-element linear skill vs zero-motion COLLAPSES as the step grows — 0.126 (20 fs) → 0.082 (40) →
  0.055 (60) → 0.033 (100) → 0.017 (200 fs); inertial v·dt RMSE blows up 0.32→2.93 Å. Central tension:
  a learned propagator wants LARGE steps, but at large steps velocity carries ~no info about net
  displacement → a large-step atom-level propagator MUST be nonlinear + see local structure (GNN), or the
  framing needs rethinking (→ open research on slow-manifold / transfer-operator / generative approaches).

## Literature verdict (2026-07-18) — reframes the approach
Focused web research (agent). Key findings + implications:
- Our 20 fs deterministic-linear-Cartesian result is the KNOWN wall: aliasing of fast bonded DOF (Nyquist:
  ~10 fs C–H stretch needs <5 fs step). A deterministic map's conditional-mean displacement given velocity
  is provably ≈0 past the fastest resolved period → "barely beats nothing moves" is expected, not a bug.
  **A deterministic large-step Cartesian per-atom map is the ONE target the field shows cannot work.**
- Closest published: **FlashMD** (arXiv:2505.19350) — all-atom flexible-H GNN, predicts positions+momenta,
  strides 1–2 orders of magnitude; solvated alanine dipeptide only **8–16 fs** (below our 20 fs). Even SOTA
  flexible-H stepping tops ~16 fs for a peptide. Names chaoticity as the hard ceiling.
- Three escape routes: (1) **constrain fast DOF** (rigid H / rigid water) so fastest resolved period rises
  above the macrostep; (2) **reduced/internal coords** (torsion space — MDGen); (3) **probabilistic
  propagator** — predict the DISTRIBUTION not the mean (conditional diffusion/flow — ITO arXiv:2305.18046,
  Timewarp arXiv:2302.01170). Genuinely large strides always trade determinism for ensemble/stochastic.
- **No published learned atomistic PROPAGATOR for DNA/RNA exists** — this is novel territory. (DNA ML work
  to date = force-field correction / generative ensembles, not integrators.)
- Small-system verdict for DNA: single NUCLEOTIDE = ideal integrator/vibration sandbox (same aliasing, max
  sampling) but ZERO DNA physics (no pairing/stacking/helix). Isolated base PAIR = worst (frays, no
  stacking). Short duplex (Drew–Dickerson **12 bp dodecamer**) = smallest system where DNA physics
  (breathing, stacking, bend/twist) appears. **Crossovers need ≥2 helices — categorically absent below a
  duplex.** Alanine dipeptide (22 atoms) is the canonical peptide testbed; there is no DNA analog yet.
- NOTE: our captured production segments already use rigidBonds=all (H-stretch constrained via SHAKE) +
  rigid water — yet 20 fs still fails, because angle libration (~20–30 fs) + H libration remain aliased.
  → the fix is a SHORTER step and/or a probabilistic target, not more constraints.

### Literature UPDATE (2026-07-19, fresh search) — confirms the speed verdict + finds the open niche
- **No published learned method beats GPU MD in wall-clock for a solvated, >1e5-atom,
  atomistically-faithful biomolecule.** The 2026 AI-for-protein-dynamics SURVEY
  (arXiv:2604.25244) states this explicitly; even SO3LR (stable >200k-atom explicit solvent)
  is per-step SLOWER than classical FF. Independently corroborates this session's scaling verdict.
- **"Avoid PME with a local cutoff" is a MULTI-NODE win only** — PME's reciprocal FFT is
  all-to-all-comms-bound across ranks (GROMACS-FMM JCTC 2020; Tinker-HP 2011.01207); on ONE
  GPU it's a well-tuned minority of the step. Confirms our N^0.34 single-GPU measurement.
- **Rollout stability under distribution shift is an OPEN problem** (survey: propagators
  proposed w/o long-term stability metrics; "small errors accumulate"). Our stable-but-wrong
  347×-RMSF result is the field frontier, not a local bug.
- **DNA-specific learned energy/force: essentially nonexistent.** Only KMMD (arXiv:2203.15525,
  QM *correction* to AMBER, ~600-atom 2-bp explicit solvent, one observable) and an E3NN
  solvated-DNA *density* predictor (PLOS ONE pone.0297502, STATIC — no forces/dynamics). No
  explicit-solvent DNA MLIP drives MD. General MLIPs (MACE/NequIP/SO3LR) 10-100× slower/step.
- **Non-GNN trend:** transformers (Point-Edge Transformer in FlashMD, Equiformer) are displacing
  MPNNs — help STRIDE/accuracy, not per-step cost. Koopman/VAMPnet best capture origami's slow
  collective modes but are reduced-KINETICS analysis (need an atomistic decoder). Latent-space
  dynamics (LED, arXiv:2509.02196) = the atom-faithful slow-mode route (protein-scale so far).
- **Explicit water+ions at scale is the gap EVERY propagator paper sidesteps** (implicit/vacuum
  small peptides). Nearest with real water: Score Dynamics (arXiv:2310.01678, 10 ps generative
  steps, dipeptide-scale); fs→ns bridge (arXiv:2510.07589). **A learned dynamics engine for DNA
  ORIGAMI does not exist — niche unoccupied.** → Novel target = STABLE long rollout reproducing
  MD statistics (RMSF/free energy) for a solvated DNA duplex-with-crossovers (our 6hb capture is
  the substrate), via a learned-energy/force head (real basin) — NOT the displacement-regressor.

### Revised direction (supersedes the earlier "just add a GNN" handoff)
Split the goal: **(A) beat the integrator/macrostep barrier** and **(B) capture DNA slow physics**.
- Do NOT keep pushing a deterministic 20 fs Cartesian map. Instead: (i) locate the aliasing floor with a
  finer-step sweep (4 fs capture run IN PROGRESS, job via pilot_4fs_jobid.txt — subsample 4→20 fs); and
  (ii) move the model to a probabilistic target (predict Δx mean+variance / small conditional flow) and/or
  work at ≤10 fs. (B) jump to the 12 bp dodecamer for real DNA physics; SKIP the isolated base pair.
- Single nucleotide = optional cheap sandbox for (A) only. Design for per-nucleotide transferability so the
  local operator composes onto multi-helix origami (crossovers) later.
Sources: FlashMD 2505.19350; Timewarp 2302.01170; ITO 2305.18046; MDGen 2409.17808; Boltzmann generators
2406.14426; DNA timescales Nat.Commun. 5:6152, base-pair fraying JCTC ct500120v.

## GNN SPEED BENCHMARK (2026-07-18) — the per-step-speed verdict
Built a compact local equivariant GNN (`backend/ml/propagator/gnn.py`, PaiNN-lite, torch+CUDA on the 2080)
predicting per-atom Δx from local geometry (radius cutoff 5 Å = NO PME). Timed forward pass vs NAMD's
measured 7.5 ms/step @ 17,827 atoms. **Verdict: an accuracy-capable GNN is ~1–2 orders of magnitude SLOWER
per step than classical MD** — h128/L3: 26× (13× crediting the 4 fs interval = 2 native steps); memory-bound
past ~20k atoms on 8 GB. Optimization sweep @ N=5000 (× NAMD per-4fs-step): h64/L2 4.8×, h32/L2 2.7×,
h32/L1 1.4×, **h16/L1 0.9× (break-even)**. So break-even needs a model so tiny (~16 hidden, 1 layer) it
cannot plausibly be accurate enough for stable atomistic rollout; accuracy-capable sizes are 5–26× too slow.
fp16+torch.compile ≈ another 2–3× (not enough to flip it). **Confirms the literature: you do NOT beat a
classical FF per-step with an accurate neural net.** The field's speedups come from LARGER steps (aliasing
wall) or expensive reference FFs (not classical CHARMM).

**Strategic reconciliation (IMPORTANT — reshapes near-term work):**
- Raw per-step speedup over classical MD is NOT the near-term win. The overarching-goal MVP AGREES: "large
  speedups not required initially; establish STABLE AUTOREGRESSIVE PROPAGATION and measure error accumulation."
- Realistic eventual speed story (set expectations): moderate step increase (8–16 fs, FlashMD-style, 4–8×
  fewer force evals, accepting some aliasing) × heavy model optimization (fp16/compile/distillation) ×
  the uncertainty-gated HYBRID (full MD only on uncertain regions) — targeting break-even-to-modest, at
  ORIGAMI SCALE where MD is expensive in aggregate. NOT 10× per-step wins.
- **Therefore pivot near-term to dev-order #4 (stable autoregressive rollout) + #6–8 (calibrated
  uncertainty)** — what the MVP actually prioritizes and what IS achievable/valuable — and treat per-step
  speed as a later, expectations-managed optimization problem.

## GPU acceleration note (user asked)
The GNN benchmark ALREADY ran on the RTX 2080 (device=cuda) — the 13–26× vs NAMD is GPU-vs-GPU (NAMD also
GPU). Under-exploited headroom, worth banking when scaling: (1) fp16 (Turing has fp16 tensor cores; my
autocast errored on index_add_ dtype — fixable, ~2× + half memory); (2) torch.compile (~1.5–3×); (3) BIG
ONE = a fused scatter — the current impl materialises a `[E,3,H]` tensor per layer (the memory-bound cause
at ≥18k atoms + OOM ≥50k); `torch_scatter`/custom kernel avoids it. Combined ~3–8×. Does NOT flip to faster
than classical MD, but makes the model fast + memory-frugal enough to run rollout/uncertainty at scale.

## Dev-order #4 — autoregressive rollout (IN PROGRESS)
Built: `gnn.py` now dual-head (predicts Δx AND Δv, both equivariant); `windows.export_rollout_data`
(one continuous segment, FIXED all-atom set incl. water/ions, pos+vel — full-atomistic, not DNA-only);
`rollout.py` (train one-step (Δx,Δv) std-normalised loss, autoregressive `rollout` feeding predictions back
+ rebuilding the neighbour list every N steps, `ballistic_reference` frozen-atom baseline, `report`).
First run: 4 fs all-atom data `workspace/propagator_pilot/duplex_rollout_allatom.npz` (1500 frames, 17,827
atoms, 1266 DNA); training h48/L2 cutoff 4.5 (522k edges, 5.9 GB, fits) on frames 0–749, rollout on the
held-out tail (start 750), horizon 100 steps (0.4 ps). Metric = RMSD growth vs true NAMD, split DNA/solvent,
vs the frozen-atom reference the model must beat.

**RESULT (one-step training, honest first cut):** step-1 RMSD **0.008 Å** (vs frozen 0.066 → one-step
accuracy is GOOD, model learns the step). But autoregressive error grows ~linearly: 0.31 Å @ step 10,
crosses the frozen-atom baseline at **~step 16 (~64 fs)** (after which the model is WORSE than doing
nothing), reaches 0.89 Å @ step 32, and **diverges to NaN at step ~33–34 (~0.13 ps)**. **Error accumulates
much faster in SOLVENT than DNA** (step 10: DNA 0.15 Å vs solvent 0.32) — the structured duplex is more
predictable than bulk water (encouraging for the DNA-focused goal). So: good one-step, unstable rollout,
useful horizon ~10–16 steps. Classic one-step-training instability → the fix (multi-step BPTT + noise) is
now coded in `train(rollout_steps=, noise=)` but needs memory tuning (K× activations OOMs at 17.8k atoms;
reduce hidden/atoms or add gradient checkpointing). **NEXT: multi-step-trained rollout to extend the stable
horizon; then compare ensemble-of-models rollouts → dev #6 uncertainty.**

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

## TIME-TO-EQUILIBRATE BENCHMARK — harness BUILT + validated on duplex (2026-07-20)
The definitive seeding test: does a BLADE-relaxed solute, solvated + handed to NAMD, reach
equilibrium in fewer NAMD ps than a cold idealized build? Two arms, IDENTICAL solvation+NAMD,
differ ONLY in solute start coords: (cold) ideal B-DNA vs (seed) BLADE-implicit-relaxed.
- **New reusable infra (committed to core — BLADE-seeds-NAMD is a stated goal):**
  `build_namd_solvated_package(..., solute_coords=(N,3))` overwrites the built solute PDB's x/y/z
  in psfgen atom order before water is placed (fresh water around the seeded conformation), leaving
  topology columns untouched — `namd_solvate._overwrite_solute_coords`. Threaded through
  `prepare_mgh_slow_release` → `prepare_propagator_reference` (**kwargs) → `local_run.prepare_local_
  reference(solute_coords=)`. Pins: exact all-atom order == the `export_windows` npz order, so a
  BLADE-relaxed seed indexes 1:1 against the same PSF. Tested: `tests/test_namd_solute_coords.py` (5).
- **Harness** (`scratchpad/blade_equil_benchmark.py`, dry|full): builds design →
  `build_charmm_psfgen_topology` (ideal all-atom) → BLADE relax in the gpu env (`blade_relax.py`,
  subprocess: OpenMM CHARMM+OBC2 minimize + short constrained Langevin) → solvate both arms → run
  both NAMD ladders local → slice solute DCD → `equil_metric.benchmark`. Metric (`equil_metric.py`,
  self-tested): solute Kabsch-RMSD to a COMMON equilibrium (pooled last-third of both arms); τ = last
  time still outside the plateau band. Runs in uv env, shells to gpu env for OpenMM (two-env split).
- **Duplex result (20 bp, smoke — expected ~0 savings, CONFIRMED): τ_cold = τ_seed = 0 ps.** Both
  arms at plateau from frame 0 (rmsd0 1.00/0.91, plateau 0.929/0.928 — same equilibrium). A duplex
  equilibrates instantly and its ideal build is already ~1 Å from eq → nothing to save. BLADE relax
  moved the solute 1.25 Å; injection verified (seed arm solvates with a different solute Rg 20.72 vs
  cold 20.22). **The harness is proven end-to-end; the duplex simply has no settling time to detect.**
- **CURVED 6hb WIRED + BLADE-relax STABLE (2026-07-20).** Harness now takes a `.nadoc` path (arg1)
  → `Design.model_validate_json` → same build→relax→(solvate→NAMD) path; new `relax` mode does
  build + BLADE relax + trajectory capture ONLY (no heavy solvate/NAMD — the local stability gate
  before the RunPod arms). `workspace/6hbx100_90deg.nadoc` = 6 helices, 40,087 solute atoms; the
  90° curve is a DEFORMATION (+1 cluster_transform) and `build_atomistic_model` APPLIES it, so the
  idealized all-atom build is already curved (correct cold-seed geometry). **BLADE relax verdict:
  STABLE** — finite, rmsd_moved 1.78 Å, Rg 100.37→100.49, bbox-diag 385→389 Å (curve HELD, no
  straighten/collapse), 72 s on CUDA. **Perf fix (important):** OBC2 GBSA must use
  `CutoffNonPeriodic` (18 Å) not `NoCutoff` at origami scale — NoCutoff is O(N²) and silently fell
  to the CPU platform → glacial; `blade_relax.py` now sets the cutoff + logs the platform (raises
  the CUDA error instead of silent CPU). Artifacts in `workspace/propagator_pilot/blade_view/`
  (`6hbx100_90deg_solute.psf` + `_relax.dcd` (~60 frames) + `_relaxed.pdb`) — viewable in Windows
  VMD via `\\wsl.localhost\Ubuntu\...` UNC paths (harness `emit_vmd`).
- **NEXT = the FULL curved showcase (RunPod).** Solvating the curved 6hb at 1.2 nm padding around a
  ~385 Å bbox → ~1.5-3 M atoms — RunPod-bound. Run `blade_equil_benchmark.py <nadoc> full` with a
  showcase trim: production ~100-500k steps (200 ps-1 ns @ 2 fs), `production_dcd_freq` ~1000-2000
  (matches real dcdfreq), so the metric can watch the solute settle. That is where τ_cold >> τ_seed
  should appear (idealized curve vs MD-equilibrium curve). Metric discrimination already proven on
  synthetic data (cold 70 ps vs seed 39 ps); the duplex proved the pipeline; the curved-6hb relax
  proves BLADE can produce the seed. Only the RunPod NAMD arms remain.

## UNIFIED duplex+ssDNA correction + SEEDING verdict (2026-07-20)
- **ONE ForceNet handles BOTH duplex + ssDNA — no negative transfer.** Trained a single ForceNet on
  the POOLED residuals of both systems (each residual = its own captured F_true − its own CHARMM+GBSA
  baseline; system-homogeneous batches, epoch mixes both). Unified R²: **duplex 0.711 (vs 0.72 separate),
  ssDNA 0.668 (vs 0.66 separate)** — matches the specialists, slight positive transfer on ssDNA. ⇒ BLADE
  does NOT need a per-motif model zoo; one correction spans paired + single-stranded environments. Model
  `energy/forcenet_unified.pt`; driver `scratchpad/unify_train.py`. This is the general recipe: pool any
  new motif's residual into the same net.
- **SEEDING verdict: the BASELINE seeds NAMD; the NN correction does NOT help (and doesn't need to).**
  Test (`scratchpad/seed_test.py`): perturb the duplex explicit-mean by ~1 Å, OpenMM-minimize (both start
  identical), then Langevin-relax under (a) baseline-only vs (b) baseline+unified-correction; measure
  tail RMSD to the explicit-MD mean. Result over 2 seeds: baseline 1.075/0.977 Å, corrected 1.107/0.942 Å
  — **Δ = −0.03/+0.03, a wash** (both within ~2× the explicit ensemble's own 0.53 Å thermal spread; Rg
  matched to <1%). WHY: the delta-force net reproduces 71% of a correction that is only ~6% of the total
  force, and it is NON-conservative (not a gradient) → it cannot cleanly relocate an equilibrium; its 29%
  residual error injects ≈ the tiny systematic shift it could offer. ⇒ **BLADE's seeding value is the
  training-free CHARMM+GBSA baseline alone** — it lands the solute ~1 Å from the explicit basin with NO
  training data, a STRONGER result for arbitrary standard structures (no per-design training to seed NAMD).
  The learned correction's payoff is elsewhere: dynamics / invariant-measure fidelity (the 6% solvent-PMF
  that shifts *fluctuation* statistics), not the mean structure. NEXT (heavy, needs a run): the full
  BLADE-baseline→solvate→NAMD leg to time the equilibration actually saved vs a cold water ladder.

**NOTE (stability):** the custom BAOAB `langevin_rollout` has NO H-bond constraints → dt=2 fs blows up
(X–H stretch ~10 fs); use **dt ≤ 0.5 fs** for unconstrained all-atom rollouts (or add RATTLE). The NAMD
reference used HMR+RATTLE at 2 fs; our implicit rollout does not.

## ssDNA basic training + the BLADE-relaxer both VALIDATED (2026-07-20)
- **BLADE-baseline as a RELAXER (training-free) — WORKS + robust.** Perturbed 6hb (σ=0.3-0.6 Å,
  even E=5.6e13 clashes) → OpenMM minimize + short implicit Langevin → stable, folded (Rg within
  0.7%), ~1 Å RMSD to the explicit reference (the GBSA-vs-explicit gap the NN correction would
  tighten). Confirms the SEED path: BLADE relaxes rough/clashing structures fast → can seed NAMD
  (skip the water-equilibration ladder) AND accept oxDNA/SNUPI backmaps as starts. Driver
  `scratchpad/relaxer_test.py`. NEXT: full BLADE→solvate→NAMD leg to measure equilibration saved.
- **Basic ssDNA reference RAN + correction TRAINED (local, ~15 min end-to-end).** Built a lone
  ssDNA strand via `create_bundle([[0,0]], N, strand_filter="scaffold")` + `assign_scaffold_
  sequence(custom_sequence=…)` (no staples) — a sanctioned single-strand build (green regression
  test `test_namd_topology.py:63`). 24 nt → solvated 20,220 atoms (job 67fa301eade0) → propagator-
  reference capture (2 fs, capture_vel_force, 3 unrestrained MGHH chunks) → 6000 frames / 761 DNA
  atoms (`ssdna24_dna_forces.npz`). RESULTS: **baseline explains 0.949 (== duplex 0.94 — bonded-
  dominated, pairing-independent), ForceNet residual R² 0.66 (vs duplex 0.72 — modestly harder:
  the solvent residual is less predictable when the conformation is floppier), total ~98% force
  accuracy.** Model `energy/forcenet_ssdna.pt`. ⇒ REVISES the earlier caveat: ssDNA is NOT harder
  at the per-frame FORCE level (baseline fine); the real ssDNA challenge is CONFORMATIONAL SAMPLING
  (floppy ensemble — this short-production reference samples ideal-B→partially-coiled only) + the
  modestly-lower correction learnability. The build→capture→export→baseline→train loop is now the
  general recipe for ANY new motif. [DONE: unified duplex+ssDNA correction — see section above.]

## BLADE — the method has a name + the curved-origami test case (2026-07-19)
**BLADE = Box-Less Atomistic Dynamics Engine.** The A2 + delta-learning + Langevin + CUDA
propagator: `E = CHARMM+GBSA(DNA-only) baseline + learned solvent correction (ForceNet)`,
implicit solvent, NO periodic box / NO PME. Chosen because box-free is the differentiator.
**Strategic thesis (user, correct):** BLADE's biggest win is CURVED / EXTENDED origami — where
explicit MD needs a huge, mostly-empty, water-dominated periodic box (+PME, +periodic-image
padding around the curve), while BLADE's cost is DNA-atom-count only, box- and curvature-
INDEPENDENT. Speedup ≈ water:DNA ratio, which grows from ~10× (compact) to 20-100× (extended).
Plain implicit solvent (GBIS) failed before (artificial damping) — BLADE differs by LEARNING the
correction to GBSA from explicit-solvent forces = implicit COST, explicit-corrected ACCURACY.
- **Test case: `workspace/6hbx100_90deg.nadoc`** — a 6hb bent 90° via Dietz insertion/deletion
  `loop_skips` (+32 inserts / −22 deletions). **CORRECTED counts (other computer, authoritative
  from PSF):** 1244 nt / **39,661 DNA atoms**; the relaxed box's 42,125 "DNA" = 39,661 DNA +
  2,464 explicit ions (1225 Na + 118 Cl + 1121 Mg-hexahydrate). My earlier 1264/42,125 folded
  ions into DNA + over-counted nt by 20 (subagent/stale report.json). Design has NO overhangs/
  extensions (arrays empty) → no newer revision; BLADE trains against this design as-is. NOTE:
  `workspace/` is GITIGNORED → the `.nadoc` does NOT sync across machines; each uses its local copy.
  **CORRECTION (from other computer's disk, commit 0073923):** the CURRENT relaxed FULL box =
  job `6d3b1a440ace` = **770,219 atoms** (DNA 42,125 + 728,094 bulk water), at
  `/media/jojo/Archive/NADOC_archive/6d3b1a440ace/package/6hbx100_90deg_namd_solvated/`. This
  does NOT fit the local 8 GB → **RunPod IS needed** (my earlier "197,107 fits local" was WRONG:
  197,107 is a water-CARVED subset (DNA + ~1.5 nm hydration shell ≈ 51.6k waters) that is NOT on
  disk — it must be carved from the 770 k box via `water_shell_carve` for a shell reference; the
  full box goes to RunPod). The old local build `workspace/md_jobs/8553cf4fa9a0/` is a stale
  earlier revision — do not use.
- **Skip/loop handling (investigated):** INSERTIONS built INLINE axially-stacked in the duplex
  column (`geometry.nucleotide_positions` delta≥1 → n=delta+1 copies offset ±½·rise, same
  twist/radius — NOT looped-out bulges) → near-duplex local env → M3 correction likely transfers.
  DELETIONS omit the pair, bridge O3′→P (~5-8 Å) via `_minimize_backbone_bridge` (atomistic.py
  ~1617) → strained, NOVEL env → the part the correction must learn. TOPOLOGY is VALID (197k PSF
  runs in NAMD; OpenMM CharmmPsfFile should accept it). CAVEATS: residual skip-site strain +
  UNRESOLVED o3prime template angle (C3′-O3′-P 94° vs 119°) bias backbone geometry → **SEED BLADE
  + force-capture from a NAMD-RELAXED restart frame (`output/*.restart.coor`), NOT the raw PDB**
  (CHARMM EM fixes the geometry). Refs: `project_atomistic_skip_backbone`, `skip_site_gromacs_fix`
  (GROMACS LINCS blow-ups FIXED via constraints=h-bonds+annealing), `o3prime_investigation`.
  ⇒ GNN-on-skips answer: representationally fine; inline-inserts near-duplex; deletion/strain
  sites novel → TRAIN the correction on the curved reference's own forces (learns skip solvation
  locally, transfers to future curves).
- **Two-computer + RunPod plan (2026-07-19):** relaxed curved 6hb is on the other computer.
  Transfer = **RunPod persistent volume as the hub** (production runs there anyway). Send the
  MINIMAL restart bundle (psf+hmr-psf + latest restart.coor/vel/xsc + forcefield/ + prod .conf +
  ENM files ≈ 50-100 MB) via `runpodctl send`→`receive` (machine→pod P2P; NOT git — workspace
  isn't versioned, GitHub 100 MB limit). sha256 both ends; verify atom count 197107/1264 nt vs
  current design (build was 1 day older than .nadoc). **REQUIREMENT: the RunPod production must
  CAPTURE FORCES** — run the propagator-reference protocol (2 fs, capture_vel_force) for ≥1
  segment seeded from the relaxed restart, else no BLADE training data. Return only the compact
  DNA-force npz (`windows.export_windows dna_only`) → Archive drive (`/media/jojo/Archive`), not
  raw DCDs. This box does BLADE dev/rollout locally (needs only psf + a relaxed .coor for the GBSA
  baseline). Follow RUNPOD_RUNBOOK (preflight, babysitter kills on failure, judge $/ns AND ns/day).

## ForceNet — CHEAPER NN (2.7×), INVARIANT MEASURE PRESERVED (2026-07-19)
**Key architectural insight: since the CHARMM+GBSA baseline supplies the energy BASIN, the NN
correction does NOT need to be conservative** → output the force DIRECTLY (one equivariant
forward, no autograd backward). `energy.ForceNet` (same PaiNN message passing as EnergyNet, a
vector readout instead of scalar-energy+autograd). Measured (duplex, gpu env):
- **2.7× faster:** compiled 5.3 ms (EnergyNet) → **2.0 ms** (ForceNet); eager 13.6 → 4.9 ms.
  Also ~2-3× cheaper to TRAIN (first-order loss, no second-order autograd).
- **Same accuracy:** force R² 0.72 (=EnergyNet). Rollout + GBSA baseline = STABLE INVARIANT
  MEASURE: Rg ratio **1.001**, RMSF corr **0.65** / ratio **1.22** (≥ EnergyNet's 0.67/1.38),
  drift 0.12/30 ps. The Langevin THERMOSTAT absorbs the small non-conservativeness — confirmed.
- `test_propagator_energy.py` +1 (ForceNet equivariance, 5 green). ROLLOUT GOTCHA: ForceNet
  doesn't detach internally (EnergyNet.forces does) → wrap the rollout NN call in `torch.no_grad()`
  or x's graph chains across steps and OOMs.
- **⇒ NEW DEFAULT for the correction: ForceNet.** Strict win: 2.7× cheaper per step + cheaper
  training + invariant measure preserved. This is the NN-cost lever that cashes the implicit-
  solvent atom-skip toward beating MD (below).

## BEAT-MD LEVER EXPLORATION (2026-07-19) — implicit-solvent equilibrium sampling
UPDATED with ForceNet: full-step (duplex) GBSA-CUDA 0.46 + ForceNet-compiled 2.0 + transfers
≈ 3.5 ms (was 7.6 with EnergyNet). Ensemble-sampling throughput at dt=8 fs (constrained):
duplex **~197 ns/day vs MD ~26 → ~7.6×**; 6hb ForceNet-step ~20 ms → **~35 ns/day vs MD ~26 →
~1.3×** (crosses into a win). The implicit-solvent advantage GROWS with origami size (MD's water
fraction rises), so the margin should widen at larger origami. Levers stack: ForceNet (2.7×) ×
GBSA-CUDA (118×) × dt=8 fs (2×) × implicit-solvent (skip ~90% atoms). REMAINS ensemble-only
(not kinetics). Force-injection loop + angle-limited dt are the residual bottlenecks.
User lead: sims save every 1000-4000 steps → only the COARSE ensemble matters. Langevin's
equilibrium is dt-INDEPENDENT, so any STABLE dt gives correct Rg/RMSF/twist stats → beat MD
on ns/day for ENSEMBLE properties (not kinetics). Levers measured (duplex, M2 model, gpu env):
- **dt ceiling:** unconstrained CHARMM+GBSA blows up at dt≥8 fs (stiff bonds); RIGID BONDS
  (`constraints=AllBonds`+HMR, OpenMM `LangevinMiddleIntegrator`) → stable to **8 fs** (Rg 21.1,
  drift 0.32); dt≥12 fs diverges (ANGLE modes ~20-30 fs are the next wall, not easily constrained).
  So dt lever ≈ 2× over unconstrained, ~2× over production MD's 4 fs.
- **Implicit solvent** = the structural win: propagate DNA only (1.3k duplex / 12k 6hb atoms) vs
  MD's full solvated box (17.8k / 136k). ~10× fewer atoms — BUT partly eaten by the expensive NN.
- **Throughput (duplex):** MD ~26 ns/day (2 fs) / ~53 (4 fs HMR). Ours at dt=4 fs + compiled NN
  ~45 ns/day (1.7× vs 2fs-MD); dt=8 fs constrained + optimized ~77 ns/day (~3× vs 2fs-MD, ~1.5×
  vs 4fs-MD). REAL but MODEST win, and ENSEMBLE-ONLY (large-dt Langevin ≠ MD kinetics).
- **HONEST verdict:** a genuine lead for EQUILIBRIUM/ensemble sampling (~1.5-3×), NOT a 10×
  blowout — the "10× fewer atoms" advantage is largely cancelled by the NN's per-atom cost
  (325k-edge message passing at 6hb = 35 ms, dominates). **Path to a BIG win: cheaper NN**
  (fused-scatter/smaller model) → then skipping water actually cashes out to ~10×. Also the
  constrained rollout's per-step OpenMM force-injection (`setParticleParameters` Python loop,
  1266 calls/step) is slow — a FIXABLE engineering bottleneck (torch-RATTLE or batched update),
  separate from the stability science. **CUDA-context gotcha:** OpenMM-CUDA Context + torch
  `torch.compile`(triton) in one process → "invalid device context"; use eager NN, or warm the
  compile before creating the OpenMM context. Drivers: `scratchpad/dt_sweep.py`, `constr_dt.py`.

## M3 — THE ENGINE TRANSFERS TO A CROSSOVER ORIGAMI (2026-07-19)
Applied the A2 + learned-energy + GBSA + CUDA pipeline to the 6hb CROSSOVER capture (job
f716e1f42b9b): the first MULTI-HELIX system (11,973 DNA atoms, 5 strands, 15 crossovers,
900 frames @ 20 fs — cadence irrelevant for force-matching). Exported DNA forces via
`export_windows` → `origami6hb_dna_forces.npz`.
- **M3a de-risk:** CHARMM+GBSA baseline explains **94.4%** of the 6hb forces (crossovers
  included); baseline-only rollout holds the bundle FOLDED (Rg 43.4 flat over 6 ps). GBSA on
  **CUDA = 5.28 ms/eval for 11,973 atoms** — on CPU this O(N²) is ~5 s, so **~900× — the CUDA
  foundation earns out exactly at origami scale as predicted.**
- **M3b:** delta-trained NN (h48/L3, cutoff 4.5, B=1, 325k edges) → resid R² **0.72** (same as
  the duplex M2's 0.74 → transfers cleanly). Rollout E_total (GBSA-CUDA + compiled NN + force-
  cache), 30 ps: **STABLE, FOLDED, INVARIANT MEASURE.** Rg ratio **1.00**, drift **0.033**,
  RMSF corr **0.60**, RMSF ratio **1.045** (within 5% — even better magnitude than the duplex).
  **The local-cutoff learned-energy engine transfers from a single duplex to a crossover-linked
  6-helix origami with NO architectural change.** Model `energy_dna_m3.pt`, log `m3b_log.jsonl`,
  drivers `scratchpad/m3a_baseline.py`, `m3b_train.py`. Run in the `gpu` micromamba env.
  HONEST CAVEATS: 30 ps (not ns); RMSF corr 0.60 (good, not perfect); per-step **43.7 ms**
  (NN's 325k-edge message-passing dominates — SLOWER than NAMD's explicit 6hb ~13 ms/step, as
  the scaling verdict predicted; the value is implicit-solvent MODELING, not per-step speed).
  Crossover-SPECIFIC validation (inter-helix distances, junction angles) not yet done — RMSF+Rg
  only. NEXT: crossover geometry metrics; ns rollout; then scale toward larger origami / the
  uncertainty (dev #6) track.

## HARDWARE ACCELERATION — OpenMM-CUDA works on WSL → 9× full step (2026-07-19)
User directive: pure HARDWARE acceleration (real CUDA), not algorithmic shortcuts. Result:
- **OpenMM CUDA platform RUNS on this WSL box** (driver 596.49 supports CUDA ≤13.2). The pip
  openmm wheel ships NO CUDA plugin; conda-forge does. Gotcha: default conda pull grabs
  CUDA 13.3 nvrtc → `CUDA_ERROR_UNSUPPORTED_PTX_VERSION`; **pin `cuda-version=12.4`**.
- **GBSA baseline: 54 ms CPU → 0.46-0.61 ms CUDA (~90-118×)** — the rollout bottleneck is now
  ~free on the GPU (no RESPA approximation needed). NN compiled 6.05 ms (triton required — pip
  install into the conda env; conda-forge pytorch omits it). **FULL step 69 ms → 7.64 ms (9×)**,
  purely hardware. 200 ps rollout ~115 min → ~13 min; 1 ns invariant-measure run now feasible.
- **UNIFIED GPU ENV (the durable foundation)** — OpenMM-CUDA + torch-CUDA must share one process,
  so both must be cuda12 builds. Setup (micromamba, isolated from the app's uv venv):
  ```
  micromamba create -n gpu -c conda-forge "cuda-version=12.4" openmm "pytorch=*=cuda12*" parmed scipy mdanalysis python=3.12
  micromamba run -n gpu pip install triton==3.1.0   # for torch.compile
  ```
  Run propagator GPU work with `MAMBA_ROOT_PREFIX=/home/joshua/micromamba ~/bin/micromamba run
  -n gpu python <driver>` (use `Platform.getPlatformByName("CUDA")` for the baseline). The uv
  venv still has cpu-OpenMM+torch (fine for training/CPU); the `gpu` env is for fast rollouts.
- RULED OUT: OpenCL (NVIDIA Linux ICD can't reach GPU via WSL dxg); torch-native FF (buggy —
  missing CHARMM impropers/Urey-Bradley in separate force objects — and not faster than OpenMM).
  RESPA GBSA-subsampling WORKS (k=8 → 3.1×, invariant measure preserved) but is algorithmic, not
  hardware — kept as a fallback, not needed now that GBSA-CUDA is 0.46 ms. Speedups also landed
  in `energy.langevin_rollout` (force-cached BAOAB, 2×, tested).
- **FURTHER CUDA push (NN is now the step floor at ~6 ms, memory-bound on the [E,3,H] scatter):**
  CUDA graphs (`compile(mode="reduce-overhead")`) only 6.4→5.7 ms (NN is NOT launch-bound → graphs
  don't help). **Trajectory BATCHING is out** — GBSA is O(N²) + NoCutoff computes all cross-copy
  pairs, so B copies in one system is O(B²): B=4 best (0.29 ms/traj), B=16 WORSE (0.79). **bf16
  needs invasive forward surgery** (cast RBF linspace + einsum weights) + risks force precision;
  deferred. **KEY INSIGHT: the 1266-atom duplex UNDER-utilizes the GPU — micro-opts don't help at
  this scale. The CUDA foundation pays off at ORIGAMI scale (M3, ~1e5 atoms) where the system
  fills the GPU.** Remaining NN lever if ever needed: fused-scatter kernel (torch_scatter/triton)
  for the memory-bound index_add_. Net: full step 7.64 ms (9× over M2) is the working foundation.

## M2 — GBSA IMPLICIT-SOLVENT BASELINE = STABLE INVARIANT MEASURE (2026-07-19)
Swapped the M1d vacuum baseline for **GBSA (OpenMM OBC2, 0.15 M salt)** — implicit solvent
adds the cohesion/screening vacuum lacked (and implicit ions via the salt term = the A2 "bath").
E_total = CHARMM+GBSA(DNA-only) + NN(residual). Baseline now explains **95.0%** of |F| (vacuum
94.1%). 60 ps rollout (γ=147, HMR, force-cached BAOAB + torch.compile NN):
- **SWELLING FIXED → invariant measure achieved.** Rg ratio **0.998** (was 1.16 vacuum),
  **drift +0.09 Å/60 ps ≈ 0** (M1d was +3 Å/200 ps). Rg sits dead-on true, flat.
- twist **35.67°/bp** (true 35.14, near-exact); **RMSF corr 0.672** (best yet: M1b 0.57, M1d
  0.085), RMSF ratio **1.38** (was 4.9 — slightly too floppy, the remaining imperfection).
- Stable, folded, physical speeds. Model `energy_dna_m2.pt`, log `m2_log.jsonl`, driver
  `scratchpad/m2_train.py`.
**NET (the A2+energy engine now works for a solvated DNA duplex):** stable invariant measure
reproducing size (Rg 0.998), shape, and twist (near-exact) with good local flexibility
(RMSF corr 0.67). This IS the unoccupied-niche target (stable rollout matching MD statistics
for explicit-solvent DNA — realized here via CHARMM+GBSA baseline + learned solvent correction).
COST CAVEAT: **GBSA on CPU ≈ 60 ms/step** (O(N²) Born radii) dominates the rollout (compiled NN
is only 4.8 ms) → capped at 60 ps here; ns-scale needs GPU OpenMM (conda; pip wheel has no CUDA)
or a torch-native implicit term. Remaining accuracy gap: RMSF ratio 1.38 (a bit floppy) →
higher NN residual-R² + more/longer training data.
NEXT: (a) tighten RMSF (more data/epochs, energy-matching); (b) faster GBSA (GPU) for ns
invariant-measure confirmation; (c) M3 = 6hb CROSSOVER capture (job f716e1f42b9b, ion typing
fixed) — the first multi-helix test; the CHARMM+GBSA baseline + local NN should transfer.

## 6HB ORIGAMI RUNG + SPEED-SCALING VERDICT (2026-07-19, user away — autonomous block)
User directive this session: **atomistic-only** propagator; **both in parallel** (duplex
conservation-training in the GPU background + 6hb origami infra/analysis foreground);
**launching local reference runs is authorized**. Main goal: does DNA-origami's simplicity
let SOME atomistic propagator beat MD at large scale?

- **6hb generator SHIPPED + tested** — `systems.origami_6hb(length_bp=42, …)` builds the
  honeycomb 6hb and runs the real app pipeline (auto_scaffold→auto_crossover→auto_break→
  M13 scaffold + WC staples), returns a `GeneratedSystem` with `topology_stats`
  (helices/strands/**crossovers**/nt/est_atoms). `length_bp=21`→378 nt, 15 crossovers,
  6 helices; solvates to **136,413 atoms**. Deterministic id, roundtrip-stable. Tests in
  `test_propagator_systems.py` (2 new, 10 total green). Added `topology_stats` field to
  `GeneratedSystem`. This is the crossover rung the whole project was building toward.
- **Speed-scaling cost model SHIPPED + tested** — `backend/ml/propagator/scaling.py`
  (`test_propagator_scaling.py`, 6 green). Models NAMD/step = a·N (O(N)) + b·N·log2N (PME,
  the term a local-cutoff propagator avoids) vs GNN/step = c·N (O(N), no PME). Levers:
  larger stride k, uncertainty-hybrid fraction f. Computes crossover N* per accuracy tier.
- **CONTROLLED 6hb NAMD reference RAN — TWO clean scaling points now measured** (same
  machine, 16 CPU, standard CUDA offload, propagator-reference protocol at BOTH sizes):
  **17,827 atoms → ~6.5 ms/step; 136,413 atoms → ~13.5 ms/step** (job `f716e1f42b9b`,
  21 bp solvated 6hb, 15 crossovers). 7.65× atoms → only 2.1× time ⇒ per-step scales
  ∝ N^0.34 — strongly SUB-LINEAR. A two-term a·N+b·N·log2N fit on this gives a spurious
  NEGATIVE b (nonsense extrapolation): we are BELOW GPU saturation, in a fixed-overhead
  regime, NOT the asymptotic PME regime. Correct model (`scaling.fit_namd_overhead`):
  **MD/step = 5.45 ms fixed + 5.9e-5 ms/atom** (→ 1e6 atoms ≈ 65 ms, 1e7 ≈ 596 ms).
- **VERDICT (honest, decisive — now anchored on two controlled measurements): a fully-
  atomistic per-atom propagator CANNOT beat single-GPU NAMD3 at any reachable scale.**
  Crux number: NAMD3 asymptotic cost is **~0.06 µs/atom/step**; an accuracy-capable local
  GNN forward pass (h64_L2) is **~3.5 µs/atom → ~60× more expensive PER ATOM** (h32_L2 34×,
  even too-small h16_L1 11×). speedup(h64_L2) ≈ 0.02–0.15 across 1e5–1e6 atoms, k=1–8.
  **PME-avoidance does NOT help: single-GPU PME is nearly free** (buried under GPU
  parallelism; measured scaling is sub-linear/overhead-bound, no O(N log N) wall to
  undercut below ≥1e6 atoms). The ONLY atomistic lever that could flip it is a ~60× larger
  STRIDE for an accuracy-capable model — ~15–30× past the all-atom aliasing wall (FlashMD
  tops ~8–16 fs). ⇒ **Within "atomistic-only," faster-than-MD is not achievable on this
  hardware.** Honest forward paths: (a) reframe the propagator as an ACCURACY/UNCERTAINTY
  tool, not a speed tool, at single-GPU scale; (b) the MULTI-NODE PME-communication regime
  (≥1e6 atoms, many GPUs) where MD strong-scaling collapses — the one place avoiding PME
  wins; (c) relax atomistic-only toward reduced/collective coordinates where large strides
  are physical (user has ruled out for now). MINED confounded logs agree qualitatively
  (17.8k→225k barely moved per-step). Modules: `scaling.py` (+`fit_namd_overhead`, `c0`
  term), report saved `workspace/propagator_pilot/scaling_report.json`.
  TODO when GPU free: live GNN-benchmark refresh (`scaling.refresh_gnn_tiers`) to replace
  the 2026-07-18 tier constants; add a saturated-regime (>1e6 atom, multi-GPU) NAMD point
  if ever on such hardware.
- **Conservation-training result (this session, bounded ~2500-step run, K=3+noise+vel_reg+
  ckpt, model `conservation/model_main2.pt`): STABILITY is solved, ACCURACY is not.** With
  the inference velocity-clamp the rollout does NOT diverge over the full 300 steps (1.2 ps);
  WITHOUT the clamp it blows up at step ~125 (vs the earlier one-step model's ~54 — the
  conservation recipe alone already helps). BUT the stable clamped rollout is a WRONG
  attractor: DNA RMSD drifts to ~18 Å by 1.2 ps and the per-atom DNA **RMSF match is
  corr ≈ 0, ratio ≈ 347×** (predicted fluctuations ~350× true, no spatial correspondence).
  → Confirms + quantifies the handoff hypothesis: non-divergence is trivial (clamp), but a
  displacement-regressor + thin data reproduces NO MD statistics. **The accuracy/statistics
  wall — not stability — is now the sole blocker for the propagation MVP.** Next real lever
  is force/energy-based (learned-energy head + symplectic step, the physically-guaranteed
  basin) and/or vastly more data; loss-trick stability is a dead end for ACCURACY.

## HANDOFF — DATA-SCALING toward unbounded stability (current focus)
Fixes so far took the horizon 23→54 steps. Diminishing returns from loss tricks → **pivot to DATA**.
1. **Generate more extensive reference data** (the biggest root-cause lever). Longer NAMD production (more
   frames per trajectory) + more sequences/seeds. Reuse `local_run.run_local_reference` /
   `prepare_local_reference` with a large `production_steps`; capture at 4 fs (dcd_freq=2). The 3 unrestrained
   MGHH chunks are CONTINUATIONS → one continuous trajectory; `windows.export_rollout_data` currently exports
   one segment — extend to concatenate all 3 (≈4500 frames already available) or export a longer new run.
2. **Data-scaling study — estimate frames needed for stability.** Train the SAME recipe (multi-step K,
   noise, vel_reg, checkpoint) on N ∈ {250, 500, 1000, 2000, 4000, …} frames; measure stable horizon H(N)
   (steps to divergence on a held-out rollout). Fit H(N): does it grow (→ extrapolate frames for target
   horizon / unbounded) or SATURATE (→ data alone insufficient; add conservation)? This directly answers
   the user's "how many frames to avoid divergence altogether."
3. **Metric of true stability:** beyond H(N), check whether long rollouts reproduce MD STATISTICS (RMSF,
   twist, bp geometry) — a rollout can be non-diverging yet wrong (drift to a wrong attractor). Unbounded
   stability must mean stable AND distribution-matching.
4. Every result ships with a VMD load command (see driver pattern below); topology = duplex.pdb (PSF bug).
Later rungs (unchanged): crossovers (2-helix + auto_crossover) → origami (6hb/18hb conftest builders);
ensemble → uncertainty (dev #6, the withheld-bulge test).
**ORIGAMI CAPTURE NOW EXISTS (2026-07-19):** job `f716e1f42b9b` (21 bp solvated 6hb, 136,413 atoms,
15 crossovers) COMPLETED and captured pos+vel+force on 3 unrestrained MGHH production chunks
(`.../6hb_namd_solvated/output/6hb_04_300K_NPT_MGHH_only_p{10,50,100}.{dcd,veldcd,forcedcd}`).
This is the first CROSSOVER-bearing reference set — export it with `windows.export_rollout_data`
(the DNA-atom subset now spans two helices joined by crossovers) to start the crossover propagator
rung. Build the 6hb design with `systems.origami_6hb(length_bp=…)`.

**Driver pattern (reuse):** train → `rollout` (horizon) → `propagate_trajectory` → `write_dcd` →
copy to `/mnt/c/Users/joshu/Desktop/gnn_vmd/` → print VMD cmd. See scratchpad/rollout_fixed.py.
VMD: `"/mnt/c/Program Files/VMD/vmd.exe" "C:\Users\joshu\Desktop\gnn_vmd\duplex.pdb" "...\<traj>.dcd"`.

## Process notes for any session
- Fast loop only: `just test-smart`. **Never** `just test` / `just test-slow` (test-dedicated only) —
  ask the user to open the session. Heavy sims (GROMACS/NAMD) are not for a coding session.
- Uncommitted work may be present; concurrent sessions possible — check `git status`, never
  `stash`/`reset`/`restore`. Forbid git in every subagent prompt.
- Pre-existing `just test-smart` noise unrelated to this work: WSL `/mnt/c/DumpStack.log.tmp` permission
  failure in `test_disk_guard`/`test_run_dir`; budget violators in `test_mrdna_extensions` /
  `test_snupi_hydro_coarse`.

## Open decisions
- **Bulge internal-unpaired representation** — USER to advise. [[atomistic_propagator]]
- **rigidBonds/SHAKE vs H velocities** — does the propagator predict H atoms, or are constrained DOF
  handled specially? Affects the 1d feature spec.
- **Dataset serialization** — npz vs zarr shards for the window store.
