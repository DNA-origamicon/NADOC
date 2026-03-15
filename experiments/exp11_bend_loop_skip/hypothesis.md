# Exp11 — Bend Loop/Skip Hypothesis

## Background

Dietz, Douglas & Shih (Science 2009) demonstrated that a gradient of insertions
(outer arc) and deletions (inner arc) across the short axis of a honeycomb bundle
cross-section produces tunable global curvature.  The seven versions of their
3-row × 6-helix bundle achieved bend angles from 0° to 166° with radii from ∞
to 6 nm.

The elastic continuum formula for curvature is:
  κ = Σ_i(ΔL_i × r_i) / (L_nom × Σ_i(r_i²))

where:
  ΔL_i = Δ_bp_i × 0.335 nm  (effective length change for helix i)
  r_i   = cross-section offset in bend direction (nm, signed)
  L_nom = n_cells × 7 × 0.335 nm  (nominal segment length)

The minimum achievable radius for a 3-row bundle (r_max = 2.25 nm):
  R_min = 7 × r_max / 3 = 5.25 nm  (≈ 6 nm observed in Dietz)

## System

6 helices arranged as 3 rows (y = 0, 2.25, 4.5 nm), 2 helices per row
(x = 0 and 1.9486 nm).  Bend direction = 90° (+Y, across the short axis).
Segment: plane_a_bp = 0, plane_b_bp = 105 (15 cells of 7 bp).

This is the exact cross-sectional geometry of the Dietz 3-by-6 bundle.

## Variables

Target radii tested: [6, 7, 8, 10, 12, 15, 20, 30, 50, 100] nm.
Additional test: requests below R_min (< 5.25 nm) must raise ValueError.

## Hypothesis

1. **Round-trip accuracy**: predict_radius_nm(mods) should reproduce the target
   radius within ±30% for all valid targets.  The error arises from integer
   rounding of Δ_bp, which can shift by ±1 bp per helix.

2. **Inner deletions / outer insertions**: Helices at negative r (inner side)
   must receive exclusively skips (delta=-1); helices at positive r (outer side)
   must receive exclusively loops (delta=+1); helices near the neutral axis
   receive no modification (or minimal modification).

3. **Minimum radius enforcement**: Any target radius below R_min ≈ 5.25 nm
   must raise ValueError.  The maximum 3-per-cell constraint corresponds to
   the Dietz 6 bp/turn inner, 15 bp/turn outer extreme.

4. **Monotonicity**: As target radius decreases (tighter bend), the number of
   modifications per helix should increase monotonically.

5. **Dietz calibration**: At R = 6 nm (paper's tightest achievable), inner
   helices should have close to 3 deletions/cell and outer helices 3 insertions/cell.

## Expected Figure

- Main panel: target radius (nm) vs predicted radius, log-scale, with ideal y=x
- Lower panels: per-helix modification count vs target radius (shows gradient)
- Inset: per-helix twist density (bp/turn) for each target radius
- Red vertical line at R_min showing the hard limit
