---
name: extra-base-4fs-geometric-fixb
description: "24hb extra-crossover-base 4 fs NAMD: the winning seed is the GEOMETRIC build + Fix B (heavy bases), NOT the oxDNA position-seed. oxDNA seeding was the blocker."
metadata: 
  node_type: memory
  type: project
  originSessionId: 4f290b8b-2035-48ed-882d-40180304acb5
---

# Extra-crossover-base 4 fs NAMD — geometric build + Fix B is the answer (oxDNA seed was the blocker)

**Proven locally end-to-end on the RTX 3080 Ti (2026-07-15), free.** For DNA-origami with
unpaired "extra" bases at crossovers (24hb_1xT: 338 extra T), a stable **4 fs** production step
needs TWO independent things, and the prior oxDNA-seed pipeline got exactly one of them while
*introducing* a fatal problem:

| build | inter-residue ring clash | heavy extra bases (Fix B) | 4 fs result |
|---|---|---|---|
| oxDNA-seeded (`build_ideal_duplex_seeded_model`) | ✗ 0.3 A ring overlaps | ✓ | k=0.1 catastrophe (70× vel) |
| geometric only (`prep_24hb.py --pre-declashed`) | ✓ 0 clashes | ✗ HMR lightens C5' to 8 amu | RATTLE fails at 4 fs hand-off |
| **geometric + Fix B (`prep_24hb_seeded.py --geometric`)** | ✓ 0 clashes | ✓ ×8 heavy | ✅ full ladder + unrestrained MGHH 4 fs |

## The two causes (both must be fixed)
1. **Ring clashes.** The oxDNA POSITION seed (`xb_pos_override`) drops each extra base's CM into
   an IDEAL-lattice duplex whose neighbours are NOT at oxDNA positions → the ~6 A aromatic ring
   interpenetrates a neighbour ring at 0.3–2.0 A (10 residue pairs in 1xT, ALL involving a THY).
   Topologically locked: no-ENM minimize opens it only to ~2.0 A; 25 ps soft doesn't move it.
   **The oxDNA CG beads are NOT overlapping** (min CM–CM 2.05 A) — it is a pure BACKMAP artifact.
   Orientation is NOT the cause: forcing the ring to oxDNA's relaxed a1/a3 (verified normal·a3=0.99)
   still leaves 132 clashes; the plain GEOMETRIC bow-out build has **0**. So: drop the position seed.
2. **Fast extra-base modes.** Even clash-free, the extra bases' fast sugar-pucker / thymine-methyl
   heavy-atom modes blow a 4 fs RATTLE step; standard HMR **lightens** those carbons (C5' → 7.98 amu)
   making it worse. **Fix B** = scale the extra-base masses UP (×8, thermodynamically free — Z_config
   is mass-independent, so the measured inter-helix stiffness is unchanged). Without it the geometric
   build RATTLE-fails on an extra-base C5' at the 4 fs hand-off.

## What ships
- `prep_24hb_seeded.py --geometric` — builds the geometric model (no oxDNA override) + reorient +
  separate, then keeps the seeded prep's Fix B (`write_hmr_psf(heavy_residues=extra_base_segid_resids,
  heavy_factor=8)`) + mass-consistent soft + fast 4 fs `pre_declashed=True` ladder. Gate PASS
  (0 coincident, min heavy 0.30 A). Job `83a8ed8ded0e` = the validated 1xT package.
- Supporting (uncommitted): `_min_conf(no_enm=)`, `rebuild_enm_from_min` flag + runner reorder,
  ENM 2.8 A clash floor (`rebuild_declashed_references(min_ang=)`), `atomistic.xb_orient_override`
  + `_oxdna_rigid_frame` a1/a3 path (works but NOT needed — orientation wasn't the problem),
  `prep_24hb.py --pre-declashed`.

## Local probe recipe (free, ~35 min, no RunPod)
Truncated ladder off the fast confs: minimize(no-ENM) → `rebuild_declashed_references` → soft 25 ps →
4 fs k0.5/k0.1/k0.01 → unrestrained MGHH 6k steps. Survival of MGHH (TEMP stays 298 K, TOTAL flat) =
4 fs-production-stable. ⚠ blow-up grep must NOT include bare `inf`/`nan` (matches "Info:").
⚠ GPUresident on the 3080 Ti throws "Low global CUDA exclusion count" (host-specific); the runner's
`gpu_resident_probe` auto-downgrades — a manual probe hits it but it is not a physics failure.

## Open
- 2xT (676 extra, TWO per crossover → neighbouring-sugar stacking) NOT yet probed — may still bite.
- Supersedes the oxDNA-seed rationale in `experiments/exp43_runpod_bench/PIPELINE_4FS_EXTRA_BASES.md`
  (that doc says seeding is REQUIRED; it is actually counterproductive — update it).
- 0xT NAMD ladder is complete on the volume (job `383f7dcc4a5d`); production not yet run.
- Also delivered: SNUPI FEM + mrDNA CG both ran all three 24hb variants (local, free) — see report.
