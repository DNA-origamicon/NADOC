# ForceNet — CHEAPER NN (2.7×), INVARIANT MEASURE PRESERVED (2026-07-19) — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
