# exp33 — atomistic-MD validation of oxDNA twist

**Date:** 2026-06-28. Follows exp31/exp32 (oxDNA coarse-grained). Auto-triggered after exp32 by
`scripts/trigger_md_after_exp32.sh`.

## Question
Our twist conclusions (exp31/exp32) come from oxDNA, a coarse-grained model. Does the predicted
twist — and its back-loaded *profile* — hold under FULL ATOMISTIC MD (CHARMM36, explicit solvent)?

## Method (3 structures)
The scientifically meaningful comparison set:
1. **baseline_p48** — analytical period-48 (oxDNA twist ~58°, back-loaded).
2. **incremental_222** — exp31 incremental-best (222 skips; oxDNA flat, max|profile| 5°).
3. **exp32_converged** — exp32 profile-guided converged design (read from exp32's last round).

For each: SEED the atomistic model from that design's oxDNA-relaxed mean (so a few-ns run tests
whether CHARMM HOLDS oxDNA's structure, not a from-ideal equilibration) → solvate with a 1.0 nm
carved water shell (~1.09M atoms, fits the 12 GB GPU) + 50 mM NaCl / 12.5 mM Mg → run the proven
equilibrium-aware NAMD ladder capped to ~3 ns production → measure the twist profile with the
IDENTICAL pipeline (`md_rmsf` mean → `measure_bundle_twist_profile`) → compare to the oxDNA profile
(overlay PNG + RMSD).

## Budget / safety
- ~1.1M atoms/structure, ~1–2 days each on the RTX 3080 Ti (the multi-day commitment).
- Disk: refuse to start a structure if root free-space < 15 GB; sparse DCD; archive each finished
  ~few-GB MD folder to `/media/jojo/Archive/NADOC_archive/exp33_md_twist_validation`. Resume-safe.

## Predictions
1. **Atomistic twist tracks oxDNA in SIGN and rough magnitude** (oxDNA2 is a validated forward
   twist predictor) — baseline strongly twisted, incremental_222 ~flat, exp32-converged flat.
2. **The back-loaded PROFILE shape is reproduced** atomistically (if it's a real structural BC
   asymmetry, not an oxDNA artifact). If the atomistic profile is NOT back-loaded, that flags an
   oxDNA-specific artifact — a notable disproven expectation.
3. Atomistic magnitudes may differ (CG vs all-atom force fields differ); we trust direction +
   profile shape over absolute degrees.

## Validated before arming
- Seed-from-oxDNA atomistic build (14386/14386 keys → 294,880 atoms), carved solvation sizing
  (1.0 nm → 1.09M atoms), prep kwargs, all imports. Run/extract reuse the production-proven
  `run_18hb` ladder + Display-MD `md_rmsf`.

## Disproven-expectation policy
Profile/sign mismatch vs oxDNA → `conclusion.md` + `LESSONS.md`.
