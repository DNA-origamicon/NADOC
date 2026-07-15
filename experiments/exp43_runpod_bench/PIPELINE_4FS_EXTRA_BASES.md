# Robust 4 fs pipeline for DNA-origami with extra crossover bases

**Goal.** Run stable **4 fs** NAMD production (HMR + `rigidBonds all`) on designs that carry
unpaired single-stranded "extra" bases at crossovers. 4 fs is the **only** acceptable
production timestep (`memory/feedback_namd_4fs_production_only.md`) — every step below fixes a
real cause so the timestep never has to drop.

## Why 4 fs is hard for extra-base designs (three distinct causes, each fixed)

1. **Bad initial geometry (catastrophic).** The geometric build stacks neighbouring extra-base
   sugars; a declash minimiser relieves the overlap by stretching a backbone bond to ~3–6 Å →
   a 240×-over, deterministic step-0 blow-up.
   **Fix A — oxDNA seed + phosphate placement.** Relax the design in oxDNA, backmap, and — the
   bug this campaign found — rotate each extra base's phosphate group rigidly with its own sugar
   (`atomistic._build_extra_base_atoms`, the `_xb_sim` branch). Result: 430 → 0 catastrophic
   intra-residue stretches; the seed is now *below* the 4 fs-proven 0xT control (which has 384
   benign ~3.5 Å crossover-junction stretches and runs 4 fs fine). Gated mechanically by
   `preflight.py` (refuses any >5 Å intra-residue backbone bond).

2. **HMR-lightened, under-caged dangling bases (the deep cause).** Even with a perfectly clean,
   equilibrated seed, the extra bases STILL blow a 4 fs step at step 0. Their fast heavy-atom
   torsional/librational modes (sugar pucker, glycosidic libration, thymine-methyl rotation) are
   **not** frozen by `rigidBonds` (only X–H stretches are), and HMR **lightens** those carbons
   (thymine C5M CH3 → ~6 amu), so the failure gets *worse* with more HMR. Ruled out as fixes:
   longer equilibration (8→30 ps), selective-physical HMR (moves the failure to fast physical H),
   and velocity re-init. 0xT (no dangling bases) survives the identical transition.
   **Fix B — heavy dangling bases.** Scale ONLY the extra-base masses UP (`write_hmr_psf(
   heavy_residues=…, heavy_factor=8)`; residues identified exactly by
   `namd_topology.extra_base_segid_resids`, an ordinal map — geometric ss-detection misses the
   crossover-sandwiched ones). A heavy-atom mode has ω = √(k/m), so raising the mass slows it
   below the 4 fs limit. **Thermodynamically FREE**: Z_config is mass-independent, so every
   equilibrium/fluctuation observable — the inter-helix 6-DOF stiffness the campaign measures —
   is UNCHANGED; only the extra bases' kinetics slow (a minor sampling-rate cost, and they are
   not the measured DOF). Empirically converts the deterministic step-0 blow-up into survival,
   with the failure moving off the extra bases entirely.

3. **Soft→4 fs mass hand-off.** The relaxation ladder's soft (`rigidBonds none`, 1 fs) segment
   ran the extra bases at PHYSICAL mass; the first 4 fs segment reading those velocities into the
   8×-heavier atoms would give 8× kinetic energy → instant "atoms moving too fast".
   **Fix C — mass-consistent soft segment.** The soft segment now uses the heavy-HMR PSF too
   (`prep_24hb_seeded.make_soft_confs_mass_consistent`); it only reads the minimiser's ~0
   velocities and heats to 300 K under Langevin with the correct heavy masses, so the hand-off is
   seamless. (Minimise confs keep the base PSF — their velocities are ~0.)

## The pipeline (what a seeded extra-base prep now does)

```
oxdna_relax_design.py <stem>                     # CG relax (removes overlaps/overstretch)
prep_24hb_seeded.py <stem> <oxdna_job> --padding 1.0
  ├─ build_ideal_duplex_seeded_model              # Fix A: clean extra-base geometry
  ├─ prepare_equilibrium_aware_namd(pre_declashed=True, fast=True)   # fast 4 fs ladder (like 0xT)
  ├─ write_hmr_psf(heavy_residues=extra_base_segid_resids(...), heavy_factor=8)  # Fix B
  └─ make_soft_confs_mass_consistent              # Fix C
preflight.py <job>                                # seed-health + 4 fs-only + fast-path gates
# ladder: minimize → 120 ps soft (heavy-HMR, 1 fs) → 4 fs ENM k0.5→0.1→0.01 → MGHH → 4 fs production
```

## What is proven vs what the full-ladder run must confirm

- **Proven (local + tests):** Fix A geometry (430→0), exact extra-base identification (338, incl.
  the crossover-sandwiched failing one), heavy PSF masses (extra-base C ×8, bulk normal HMR),
  mass-consistent soft conf, preflight gates, all `just test-smart` green. Fix B converts the
  deterministic extra-base step-0 blow-up into survival (extra bases stable).
- **Needs the full ladder (RunPod) to confirm/tune:** end-to-end 4 fs stability over the real
  120 ps+ graded-ENM ladder, and the `HEAVY_XB_FACTOR` value (8 is the locally-evidenced floor;
  the residual marginal trips in truncated local tests are ordinary duplex/junction atoms — the
  same general 4 fs marginality the full ladder resolves and 0xT survives — not the extra bases).
  **Validate with a short 4 fs probe (a few hundred steps off the equilibrated ladder) BEFORE
  committing to 50 ns.**

## Key files
`backend/core/atomistic.py` (`_build_extra_base_atoms` phosphate fix) ·
`backend/core/oxdna_seed.py` · `backend/core/namd_topology.py` (`extra_base_segid_resids`) ·
`backend/core/md_protocols.py` (`write_hmr_psf(heavy_residues, heavy_factor)`,
`require_sanctioned_production_timestep`) · `experiments/exp43_runpod_bench/prep_24hb_seeded.py`
(`HEAVY_XB_FACTOR`, `make_soft_confs_mass_consistent`) · `preflight.py` (seed-health + dt gates) ·
`NAMD_4FS_RATTLE_RESEARCH.md` (the literature backing).
