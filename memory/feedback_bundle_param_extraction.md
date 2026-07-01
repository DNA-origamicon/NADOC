---
name: Bundle inter-helix parameter extraction — lessons learned
description: Helix assignment approaches (geometry vs topology), Euler gimbal lock, crossover centroid bias, convergence timescales
type: feedback
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
## Use topology-based helix assignment, not geometry

`build_p_gro_order` from `atomistic_to_nadoc.py` maps GROMACS P-atom order to
(helix_id, bp_index, direction) by walking the PDB file order (which pdb2gmx
preserves). This is the correct approach for extract_bundle_params.py.

**Why:** Geometry-based nearest-axis assignment fails after even moderate MD
simulation (> 10–20 ns) because:
1. GROMACS box offset: structure is not at the design origin in XY
2. Bundle rotational diffusion: outer helices (40 Å from centroid) displace >10 Å
   after a 15° rotation, causing helices at the same X but ±Y to be swapped

A centroid shift + 2D Kabsch rotation pass helped but was insufficient for the
most-affected pairs (same-X helices in the honeycomb lattice, like
h_XY_0_-1 / h_XY_1_-1 and h_XY_1_3 / h_XY_0_3).

**How to apply:** Any script that assigns GROMACS residues to NADOC helices should
use `build_p_gro_order` + `input_nadoc.pdb`. Never use nearest-axis geometry for
MD trajectories.

---

## PCA helix axis sign convention: always snap to +Z

`_helix_axis_from_c1prime` returns a ±Z axis from PCA. Without an explicit sign
convention, different helices get different signs. When two helices have opposite
signs, their relative rotation (Euler β) appears as ~180° instead of ~0°.

Fix: after computing the frame-0 reference axis, flip to +Z if `ax[2] < 0`:
```python
_, ax = _helix_axis_from_c1prime(c1p)
if ax[2] < 0:
    ax = -ax
ref_axes[h_id] = ax
```

**How to apply:** Any code computing per-helix PCA axes for a bundle where all
helices run along +Z must enforce this sign convention.

---

## Euler ZYZ parameterization is unreliable for near-parallel helices

`K_q3` (Euler α) and `K_q5` (Euler γ) are spuriously large (>1000 kJ/mol/rad²)
when the inter-helix tilt β < ~15°. This is gimbal lock at β ≈ 0 — α and γ
are degenerate and their variance collapses to near-zero, inverting to huge K.

**Why:** The Euler ZYZ decomposition has a coordinate singularity at β = 0. For
helices that are nearly parallel (β < 15°, which is almost always the case in a
bundle), the in-plane rotation α and twist γ are effectively undefined frame-to-frame.

**How to apply:** Never report or use K_q3, K_q5 from a Euler ZYZ fit of nearly-
parallel helices. Reliable DOFs are only q1, q2 (lateral), q0 (axial), and
q4 (tilt β). The fix is to use axis-angle or quaternion parameterization for
the rotational component.

---

## Crossover residues bias the helix axis centroid

In `_interhelix_q`, the helix origin is computed as the centroid of all C1'
positions assigned to that helix. Crossover residues physically sit at the
midpoint between two helix axes (~11 Å from each), pulling the centroid inward.
For pairs with many crossovers, this halves the apparent lateral separation
(seeing lat ≈ 8–11 Å instead of ~22 Å).

**Why it matters:** The compressed centroid means the 6-DOF q vector is biased
at equilibrium. The STIFFNESS (from fluctuations around the mean) may still be
approximately right if the fluctuations are symmetric, but is unreliable for
pairs with lat < 12 Å.

**How to apply:** Flag any pair with `lateral_sep_A < 12.0` as unreliable.
The fix is to exclude crossover-bp positions from the centroid computation
in `_interhelix_q`. Not yet implemented.

---

## Inter-helix autocorrelation is ~1.4 ns (first-lag estimate from 201 ns run)

From the 10hb bundle at 310 K, 201 ns trajectory, skip=5 (0.5 ns sampling):
τ_corr ≈ 1.4 ns for all DOFs and all contexts. Earlier estimate of 0.3–0.5 ns
was too short (from only 110 frames, undersampled estimate).

Convergence status at 201.4 ns (2026-04-28):
  - 2-2 context (6 pairs, 399 frames/pair): ESS 815–969 → CONVERGED ✓
  - 2-3 context (4 pairs, 399 frames/pair): ESS 545–636 → CONVERGED ✓
  - 3-3 context (1 pair,  399 frames/pair): ESS 138–164 → NOT converged (need ~289 ns)

Bottleneck is 3-3: only 1 pair means no cross-pair pooling.
ESS = 200 reached at ~289 ns total → ~88 more ns needed from current 201 ns.
At ~50 ns/day production rate: convergence achieved ~2026-04-30.
1000 ns run (GROMACS ETA 2026-05-14) is massively overkill — can stop at ~300 ns.

**How to apply:** Use skip=5 (500 ps between frames) for extraction. To reach
ESS = 200 per pair: need ~200 × τ_frames = 200 × 2.8 = 560 frames × 0.5 ns = 280 ns.
For multi-pair contexts, pooled ESS ≈ n_pairs × per_pair_ESS, so they converge faster.

10hb final result (2026-04-30, 304 ns): all contexts converged — ESS 208–1433.
Parameters saved to backend/data/parameters/bundle_stiffness.json.

## Pooled context q_mean has sign cancellation — use per-pair means for geometry

When multiple helix pairs are pooled into a context (e.g. all 6 "2-2" pairs into
one q-series), the q_mean vector is meaningless for geometry because pairs have
different reference-frame orientations. Pairs listed as (h_A, h_B) vs (h_B, h_A)
get opposite signs on axial and lateral components, causing the pooled mean to
collapse toward zero.

**Correct approach:** compute equilibrium geometry (center-to-center distance,
lateral separation, tilt angle) as the mean of per-pair individual means — read
from `all_pairs.json`, not from the pooled `context_params.json` q_mean.

The stiffness K (from fluctuations around the mean) is NOT affected — fluctuations
are always positive, and the covariance is symmetric regardless of orientation.

**How to apply:** The `bundle_stiffness.json` database already applies this fix.
Never trust `context_params.json → q_mean_physical → center_to_center_dist_A`
when n_pairs > 1 and pairs have mixed orientations.

---

## Isolated 2hb system has very long autocorrelation time (τ ≈ 11 ns)

The isolated 2-crossover 2hb system (param_extract.py) has τ_int ≈ 11 ns for all
inter-arm DOFs. At 200 ns and 10001 frames (skip=1), ESS = 9-90 — not converged.
Target ESS=100 requires ~2.2 µs (110,000 frames × 20 ps). Not practical.

**Root cause:** The arm is only constrained at its two ends (two DX crossovers).
With no neighboring helices, the arm fluctuates freely and slowly. In a bundle,
neighboring helices suppress these motions → shorter τ.

**How to apply:** Use the BUNDLE approach (local_crossover_extract.py) for T0
parameters. For T1 and T2, use either:
(a) A bundle run with the T-variant crossovers (e.g. 3NN_opt2 for T1), or
(b) The isolated run only for EQUILIBRIUM ANGLES (mean converges faster than std).

## Correct observable for mrdna crossover spring: bp-center distance

mrdna's HarmonicBond(k, r0) at a crossover connects two CG beads at adjacent
helix positions. The bead = approximate helix axis position at that bp.

**Wrong observable:** C1' of a single strand at the crossover bp — gives either
~10 Å (bonded neighbors when using crossing strand) or ~27 Å (non-crossing strand
facing away). Neither is the inter-helix distance.

**Correct observable:** bp center = mean(C1'_FORWARD, C1'_REVERSE) at the crossover
bp on each helix. This averages both strands → estimates the helix axis position.
Result: r0 = 19.03 ± 1.79 Å for 10hb interior DX crossovers, vs mrdna default 18.5 Å.

**How to apply:** Use `local_crossover_extract.py` which implements this correctly.
Key: build c1p_map keyed by (helix_id, bp_index, direction) and use both directions.

## k_bond is context-dependent in the bundle

From 10hb (52 interior crossovers, bp 1-40):
- 3-3 context (fully interior): k ≈ 3–5 kJ/mol/Å² (tightly constrained)
- 2-2 context (edge helices): k ≈ 0.1–0.9 kJ/mol/Å² (more flexible)
The pooled mean (0.047 kJ/mol/Å²) is dominated by the many low-k edge crossovers.
For mrdna parameterization, use context-appropriate values or the 2-2 mean for
isolated/edge designs, 3-3 for interior spring behavior.

## Trajectory selection: prefer production parts over stale view_whole.xtc

`bundle_extract.py` had a bug: it preferred `view_whole.xtc` even after production
continued past it. Fixed (2026-04-28) to prefer `prod_best.part*.xtc` when any part
is newer than `view_whole.xtc`. Both the backend and runs/ versions were updated.

**Why:** view_whole.xtc was built Apr 25 (54.6 ns) but by Apr 28 the simulation
reached 201.4 ns — the stale file missed 146 ns of data and caused underestimated ESS.
