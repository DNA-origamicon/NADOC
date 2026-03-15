# Exp19 — Hypothesis: CG-XPBD Loop/Skip Convergence on 6HB

## Context

Exp18 demonstrated that the per-nucleotide full XPBD model shows **zero
convergence** when starting from a straight initial geometry with deformed
(bent) rest lengths on a 2HB.  The root cause was identified: backbone bond
strain between straight and deformed positions is < 0.1% for a gentle 90°
bend over 42 nm (bend radius ~27 nm >> bond length ~0.68 nm), so the
simulation starts effectively at rest regardless of the target geometry.

The coarse-grained (CG) helix-level physics model (introduced in branch
`coarse-grain-physics`) encodes loop/skip modifications **differently** from
the full XPBD:

- **Full XPBD**: rest lengths = distances in deformed geometry (nearly
  identical to straight for smooth bends → zero strain → zero convergence).
- **CG model**: rest lengths = topological bp count × BDNA_RISE_PER_BP,
  modified directly by Helix.loop_skips.  A loop (+1) at bp k sets
  rest[k→k+1] = **2 × BDNA_RISE_PER_BP = 0.668 nm**.  Starting positions
  have bond length = 1 × BDNA_RISE_PER_BP = 0.334 nm → **100% compression
  strain** at each loop site from frame 0.

The compressed loop bonds push outer-helix CPs outward.  Crossover bonds
(coupling inner and outer helices) transmit this strain across the bundle
cross-section.  Inner-helix skip bonds (rest = 0) simultaneously pull inner
CPs together.  The combined effect drives the bundle to bend.

## System

A 6-helix bundle (cells [(0,0),(0,1),(1,0),(0,2),(1,2),(2,1)]), 168 bp long,
with a 90° bend between bp 21 and bp 147 in the +Y direction.

Full pipeline:
1. `make_bundle_design` — bare straight bundle
2. `make_prebreak` — break scaffold at crossover boundaries
3. `make_auto_crossover` — ligate all valid staple crossovers
4. Compute `bend_loop_skips` at clamped radius (avoid exceeding ±3 bp/cell)
5. `apply_loop_skips` — encode mods into Helix.loop_skips

Two simulation conditions:
- **Full XPBD** (baseline): per-nucleotide, deformed geometry rest lengths.
  Expected: zero convergence (same failure mode as exp18).
- **CG-XPBD** (new): helix-axis control points, topological rest lengths.
  Expected: genuine convergence driven by loop/skip strain.

## Predictions

### Full XPBD baseline

1. RMSD from straight initial positions will remain < 0.5 nm throughout
   200 frames (essentially unmoved — zero convergence, same as exp18).
2. RMSD from target (deformed geometry) will remain ≥ 15 nm (no approach
   to target).

### CG-XPBD model

1. **Displacement from straight**: RMSD from initial straight positions will
   grow to ≥ 2 nm within 100 frames, indicating the bundle has moved
   significantly from its starting configuration.

2. **Approach to target**: RMSD from target deformed axis positions will
   decrease from its initial value (~17 nm) by ≥ 30% within 200 frames for
   crossover_weight ≥ 20.

3. **Crossover weight scaling**: higher `crossover_weight` → faster initial
   convergence.  Prediction: crossover_weight=50 converges 3–5× faster than
   crossover_weight=5 (measured as frames to reach 50% of initial RMSD).

4. **Overshoot at high weight**: very high crossover_weight (≥ 100) may cause
   oscillation or overshoot past the equilibrium, visible as RMSD dip then
   recovery, because the aggressive crossover correction can over-correct
   backbone bonds.

5. **6HB vs 2HB**: the 6HB has many more inter-helix crossover bonds per unit
   length (~6 adjacent pairs vs 1 pair in 2HB) → the collective crossover
   strain signal is stronger → more pronounced bending.

### Qualitative conclusion expected

The experiment will demonstrate that:
- The CG model **correctly encodes** loop/skip mods as genuine mechanical
  strain (not just geometric reference positions).
- The crossover_weight parameter provides practical control over convergence
  speed vs stability.
- A 6HB design with loop/skip mods placed by `bend_loop_skips` will bend in
  the correct direction under the CG model, providing **qualitative visual
  feedback** on loop/skip-driven shape changes.

## Pass/Fail

The experiment **passes** if:
1. Full XPBD RMSD displacement from straight < 0.5 nm at frame 200.
2. CG-XPBD (crossover_weight=30) RMSD displacement from straight ≥ 2 nm
   by frame 200.
3. CG-XPBD RMSD from target decreases by ≥ 20% over 200 frames for at least
   one crossover_weight value.
4. Convergence is monotonically faster with increasing crossover_weight (for
   values 5, 10, 30 — before overshoot regime).
