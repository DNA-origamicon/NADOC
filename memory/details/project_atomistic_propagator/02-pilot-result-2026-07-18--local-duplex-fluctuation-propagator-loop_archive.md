# Pilot RESULT (2026-07-18) — local duplex-fluctuation propagator loop CLOSED end-to-end — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
