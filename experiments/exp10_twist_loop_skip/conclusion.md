# Exp10 — Twist Loop/Skip Conclusion

## Result: PASS

## What happened

A 6-helix bundle (2 cols × 3 rows honeycomb cross-section) with 126 bp (18 cells
of 7 bp) was swept across 37 target twist angles from −1833° to +1833°.

### Linearity

`twist_loop_skips()` distributes modifications using a Bresenham algorithm that
places 0–3 skips or loops per cell.  The relationship between target twist angle
and predicted twist is linear with R² = 0.999903 — essentially a perfect linear
mapping interrupted only by integer rounding (which can shift by at most ½ ×
34.286° ≈ 17° per modification).  Measured max |residual| = 16.80°, just under
the one-full-bp-twist threshold of 34.286°.

### Dietz calibration match

At target = +205.71° (6 × 34.286°, corresponding to Dietz's "10 bp/turn" design):
- `twist_loop_skips()` placed exactly **6 deletions per helix**, 1 per 3 cells ✓
- This matches the Dietz 10-by-6 bundle: one deletion per every third array cell
- Effective twist density: 10.5 × 120/126 ≈ **10.0 bp/turn** ✓
- Dietz paper observed ribbons with 235 ± 32 nm half-period (left-handed twist)

At target = −205.71° (Dietz "11 bp/turn"):
- Exactly **6 insertions per helix** placed ✓
- Effective twist density: 10.5 × 132/126 ≈ **11.0 bp/turn** ✓
- Dietz observed 286 ± 48 nm half-period (right-handed twist)

### Limit enforcement

Requesting |target| > 18 × 3 × 34.286° = 1851.4° correctly raises `ValueError`
with a message citing the 6 bp/turn minimum constraint (4 bp minimum cell size).

### Bresenham spacing quality

At all modification densities (1–3 per cell), the Bresenham distribution correctly
spreads modifications within each 7-bp cell at distinct bp positions (e.g.,
3 deletions in a cell → bp 0, 2, 4 of that cell are skipped).  The geometry
engine correctly omits these bp positions from the nucleotide position list,
producing the expected count reduction.

## Implications

1. **Formula is correct**: The Dietz "each bp modification = ±34.286° of angular
   strain" is correctly implemented and verified against published calibration
   data.

2. **Integer rounding is the dominant error source**: At small twist targets
   (< 34.286°), the rounding to the nearest integer modification causes up to
   ±17° error.  For practical use, targets should be multiples of 34.286° for
   zero residual.

3. **Hard limits match the Dietz paper's physico-chemical constraints**: The 6
   bp/turn lower limit (corresponding to ≥ 3 bp deletions per cell → 4 bp cells)
   is enforced with a clear ValueError, matching the paper's observation that
   deviations below 6 bp/turn "compromise folding quality and increase the
   frequency of defective particles."

4. **The calculator is ready for Phase 7 UI integration**: `twist_loop_skips()`
   can be called directly from the API endpoint with user-specified target twist
   angles, and the limit check protects against physically impossible designs.

## Actionable decisions

- **UI input limits**: In the Bend/Twist popup, the twist slider/input should
  be clamped to [−max_twist_deg(n_cells), +max_twist_deg(n_cells)] before
  calling the API.  The backend also enforces this, but the UI should prevent
  invalid inputs proactively.
- **User display**: Show effective bp/turn alongside the twist angle, and warn
  if the resulting twist density at any cell approaches 6 or 15 bp/turn.
- **Rounding residual**: The actual twist will differ from the target by up to
  ±17° (½ bp modification).  This is inherent to the discrete nature of DNA
  modification and should be communicated in the UI as "approximate."
