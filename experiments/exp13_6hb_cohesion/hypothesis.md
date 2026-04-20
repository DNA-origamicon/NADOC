# Exp13 — Hypothesis: 6HB Structural Cohesion With vs Without Crossovers

## Context

The XPBD physics engine models DNA origami dynamics through backbone bonds,
bending stiffness, base-pair bonds, stacking, and excluded-volume repulsion.
In a multi-helix bundle, the only inter-helix constraints are:
  1. Excluded volume (pushes beads apart if < 0.3 nm — almost never triggered
     at the 2.25 nm honeycomb lattice spacing)
  2. Backbone bonds across crossover junctions (when crossovers are present)

Without crossovers, adjacent helices have NO attractive interaction — only
the excluded-volume repulsion (which is inactive at 2.25 nm separation).
Thermal noise will therefore cause helices to random-walk away from each
other without any restoring force.

With crossovers, inter-helix backbone bonds impose a rest-length constraint
at the crossover junction (~0.68 nm bone length). This holds the two helices
at approximately their ideal lattice separation and propagates tension
throughout the bundle when any helix deviates.

## System

A 6-helix bundle (cells [(0,0),(0,1),(1,0),(0,2),(1,2),(2,1)]), 42 bp long
(= 6 crossover array cells at 7 bp/cell).

Two conditions:
- **No crossovers**: bare bundle, only intra-helix constraints.
- **With crossovers**: one half-crossover per adjacent helix pair at the
  nearest valid bp position, giving 6 crossovers total (one per edge).

## Predictions

### Without crossovers

1. **Mean inter-helix centroid distance** (adjacent pairs) will grow from
   2.25 nm toward ≥ 4 nm within 200 steps at noise_amplitude = 0.02 nm.
   Prediction: > 50% increase over 200 steps.

2. **Non-adjacent pairs** will drift even further, breaking away from the
   bundle structure entirely.

3. **Centroid drift** (distance of each helix centroid from its initial
   position): will grow as √step (random walk character, ~0.02×√(step×20)
   nm per helix) → ~2 nm after 200 steps.

4. **Bundle diameter** (max distance between any two centroid projections
   in XY) will expand from ~4.9 nm to > 10 nm by step 300.

### With crossovers

1. **Mean inter-helix centroid distance** will remain near 2.25 nm ± 0.3 nm
   throughout 300 steps. Crossover bonds create a restoring force that
   opposes separation.

2. **Bundle diameter** will remain near its initial value (< 6 nm),
   oscillating around the lattice-ideal configuration.

3. **Crossover constraint satisfaction**: the inter-helix backbone bonds
   (crossover junctions) will have mean |dist − rest| < 0.05 nm, indicating
   they are effectively constraining the helices.

4. **Individual helix wandering** (centroid from initial position) will be
   < 0.5 nm at all times.

### Qualitative conclusion expected

The experiment will show that:
- A crossover-free bundle is not a "structure" in any dynamic sense — it is
  a collection of independent rods that immediately diverge under thermal noise.
- A crossover-linked bundle maintains its topology and shows coordinated
  thermal fluctuations around the ideal geometry.
- This confirms that the XPBD physics correctly represents the role of
  crossovers as the load-bearing topological element of DNA origami.

## Pass/Fail

The experiment passes if:
1. Without crossovers: bundle diameter grows by > 50% over 300 steps.
2. With crossovers: mean adjacent inter-helix distance stays within ±25%
   of the ideal 2.25 nm spacing for all 300 steps.
3. Centroid drift in the no-crossover case is > 3× that of the crossover case
   at step 300.
