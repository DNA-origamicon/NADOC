# Exp03 — Excluded Volume Hypothesis

## System
Two parallel 42bp duplexes at 2.25 nm centre-to-centre separation (standard
honeycomb spacing), run with high noise (0.08 nm/substep) for 300 frames.

## Hypothesis
The excluded-volume constraints (EXCLUDED_VOLUME_DIST = 0.6 nm) should prevent
any backbone bead from one helix penetrating within 0.6 nm of any backbone bead
on the other helix throughout the entire simulation.

- **Primary**: min inter-helix bead distance >= 0.6 nm at all frames.
- **Secondary**: EV violation count per frame should be zero or near-zero.
  Some transient violations may appear immediately after a thermal kick (within
  a substep) but should be resolved before the frame is recorded.

## Rationale
At 2.25 nm separation, the inter-helix gap between outer bead surfaces is
approximately 2.25 - 2×1.0 = 0.25 nm (axis-to-axis minus two helix radii).
The actual closest backbone-bead distances oscillate as the helices twist.
With high noise (0.08 nm/substep), beads are kicked significantly each substep,
making EV the binding physical constraint preventing helix interpenetration.

## Secondary question
Does EV enforcement significantly slow XPBD convergence (bond length stability)?
If bond deviations grow compared to a single-helix run at the same noise, this
suggests EV-backbone constraint conflicts are costing solver iterations.
