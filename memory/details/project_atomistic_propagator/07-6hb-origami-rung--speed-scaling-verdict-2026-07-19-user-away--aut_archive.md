# 6HB ORIGAMI RUNG + SPEED-SCALING VERDICT (2026-07-19, user away — autonomous block) — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
