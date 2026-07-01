---
name: project_md_twist_validation
description: "exp33 — atomistic NAMD MD validation of oxDNA twist (3 structures), auto-triggered after exp32; + the exp31→32→33 autonomous chain"
metadata: 
  node_type: memory
  type: project
  originSessionId: dbfe337c-0487-4baa-aff7-14ee31e09249
---

# exp33 — atomistic-MD twist validation (auto-triggered after exp32)

Validates whether oxDNA's (coarse-grained) twist conclusions (exp31/exp32) hold under FULL
atomistic NAMD MD. `experiments/exp33_md_twist_validation/` (run.py, md_compare.py, hypothesis.md).
Set up 2026-06-28; runs AFTER exp32 completes. Extends [[project_skip_twist_curvature_sweep]].

## Pipeline (3 structures: baseline p48, exp31 incremental-best/222, exp32-converged)
Per structure: SEED the atomistic model from that design's oxDNA-relaxed mean
(`build_atomistic_model(design, nuc_pos_override={(helix,bp,dir):xyz})` from
`read_flexibility_map(ox_job, exp31_ws)`) — so a FEW-NS run tests whether CHARMM holds oxDNA's
structure, not a from-ideal equilibration → `prepare_equilibrium_aware_namd(design, job_dir,
atomistic_model=seeded, water_shell_nm=1.0, ion_conc_mM=50, mg_conc_mM=12.5, salt_mode="custom",
minimize_steps=24000)` → cap segments to ~3 ns (11 ENM-release segs ×100k + final k=0 prod 1.5M
steps) → `run_job` → `md_trajectory.md_rmsf(psf, [(name,'',dcd)…], pdb, design)` mean →
`measure_bundle_twist_profile` (differential, via exp31 `profile.compute_twist_profile`) → compare
to the oxDNA profile CSV (overlay PNG + RMSD via md_compare). Archive the MD job, free disk.

## Feasibility (probed 2026-06-28)
3×6×400 atomistic = **294,880 DNA atoms**; full solvation 1.81M atoms (too big for 12 GB); carved
to **1.0 nm shell = 1.09M atoms** (1.5 nm = 1.17M) → fits the RTX 3080 Ti (12 GB), ~exp30 18hb
scale. Box 15.7×8.9×143.5 nm. ~1–2 days/structure. seed-from-oxDNA build = 10 s (14386/14386 keys).

## CRITICAL — carved shell auto-runs NVT (do not "fix" the NPT labels)
`water_shell_nm>0` ⇒ `md_protocols`: `carve_shell=True` → `mgh_slow_release_segments(nvt_only=True)`
→ barostat OFF on every stage (an NPT piston would collapse the vacuum-cornered carved cell onto
the DNA image). **Stage NAMES keep their "NPT" label** for manifest/resume continuity — so the
segments printed as "300K_NPT…" actually run NVT. Confirmed `prepare_equilibrium_aware_namd` works
on a seeded skipped 14k-nt design (12 segments, 190 s prep). See [[water-shell-carve]].

## Autonomous chain (exp31 → exp32 → exp33)
- exp32 driver+watchdog running; writes `results/COMPLETE` at convergence/max-rounds.
- `scripts/trigger_md_after_exp32.sh` (ARMED, nohup) polls for exp32 COMPLETE → launches +
  babysits exp33 (relaunch-on-death, resume-safe, holds if root <15 GB). exp33 archives each MD
  job → /media/jojo/Archive/NADOC_archive/exp33_md_twist_validation, keeping disk bounded.
- Monitor any experiment with `EXP_DIR=<exp dir> python3 scripts/monitor_skip_sweep.py` (now
  EXP_DIR-parametrized); watchdog_skip_sweep.sh likewise (EXP_DIR env).

## Predictions / what to look for
oxDNA2 is a validated forward twist predictor → expect atomistic twist to track oxDNA in SIGN +
rough magnitude and reproduce the back-loaded PROFILE shape. If the atomistic profile is NOT
back-loaded, that flags an oxDNA-specific artifact (disproven expectation → LESSONS). Trust
direction + profile shape over absolute degrees (CG vs all-atom force fields differ).

## Next session
Check `experiments/exp32.../results/profile_refine.png` (convergence + twist + curvature profiles
per round) and, once exp32 COMPLETE + exp33 ran, `experiments/exp33.../results/compare_*.png`
(MD vs oxDNA twist profiles) + `results.json` (profile_rmsd_vs_oxdna). Write exp32 + exp33
conclusion.md. Reusable: `backend/core/profile_guided_refine.py` (controller), the EXP_DIR
monitor/watchdog, the seed-from-oxDNA→atomistic→twist comparison.
