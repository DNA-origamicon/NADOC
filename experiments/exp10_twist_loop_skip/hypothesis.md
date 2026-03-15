# Exp10 — Twist Loop/Skip Hypothesis

## Background

Dietz, Douglas & Shih (Science 2009) showed that uniform deletions from every
array cell (7-bp segment between crossover planes) in a honeycomb bundle cause
a global left-handed twist.  The mechanism: each deleted bp reduces the local
twist by 34.286°, creating unrelieved angular strain that the bundle relieves as
macroscopic rotation.

In their 10-by-6 bundle:
- Default: 126 bp / 18 cells / 12 full turns at 10.5 bp/turn → no twist
- 1 del per 3 cells (6 total deletions): 120 bp, "10 bp/turn" average → left-handed twist
  - Measured half-period 235 ± 32 nm (left-handed ribbon)
- 1 ins per 3 cells (6 total insertions): 132 bp, "11 bp/turn" average → right-handed
  - Measured half-period 286 ± 48 nm (right-handed ribbon)

## System

6 helices in a 2×3 honeycomb cross-section (cols 0-1, rows 0-2) with 126 bp each
(18 cells of 7 bp between planes 0–126).  Equivalent to one row of the 10-by-6
bundle in the Dietz paper.

## Variables

Target twist angles from 0° to max (18 cells × 3 del/cell × 34.286° = 1851°),
tested at 18 evenly spaced values including the Dietz calibration points:
- Dietz "10 bp/turn": 6 deletions → predicted 205.71° (≈ 6 × 34.286°)
- Dietz "11 bp/turn": 6 insertions → predicted −205.71°

## Hypothesis

1. **Linearity**: predict_global_twist_deg(mods) should be linearly proportional
   to target_twist_deg with slope ≈ 1.0 (it is an inverse of itself up to integer
   rounding). R² should exceed 0.999.

2. **Dietz calibration point**: At target ≈ 205.7° (6 × 34.3°), all 6 helices
   should each receive exactly 6 deletions (1 per 3 cells), matching the Dietz
   "10 bp/turn" design. Predicted twist should be 205.71°.

3. **Hard limit enforcement**: A target > max_twist_deg(18) = 1851° should raise
   ValueError with a clear message about the 6 bp/turn lower limit.

4. **Symmetry**: A target of −T should produce the mirror image (insertions
   instead of deletions) with predicted_twist ≈ −T.

5. **Even spacing**: Modifications should be as evenly spaced as possible across
   cells (Bresenham distribution), minimizing local clustering.

## Expected Figure

- Main panel: target_twist_deg vs predict_global_twist_deg, with ideal y=x line
- Residual panel: (predicted − target) vs target, showing rounding error ≤ ±34.3°
- Inset table: Dietz calibration comparison (10 bp/turn, 11 bp/turn cases)
