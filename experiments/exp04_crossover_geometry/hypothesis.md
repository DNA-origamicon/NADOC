# Exp04 — Crossover Geometry Hypothesis

## System
Two 21bp duplexes connected by a staple crossover at bp=10. Helices at x=0 and
x=2.25 nm (honeycomb spacing). 200 frames, noise=0.05 nm/substep, n_substeps=20.

## Crossover topology
- scaffold0: FORWARD on h0, bp 0-20
- scaffold1: FORWARD on h1, bp 0-20
- staple_h0_left:   REVERSE on h0, bp 20-11
- staple_crossover: REVERSE on h0 bp 10-0, then REVERSE on h1 bp 0-10
- staple_h1_right:  REVERSE on h1, bp 11-20

The staple crossover strand crosses between h0 and h1 at bp=10. The backbone
bond spanning the crossover connects h0:bp10:REVERSE → h1:bp10:REVERSE (or
equivalent in 5'→3' order). This bond is ~2.25 nm long (helix spacing) vs. the
normal ~0.678 nm backbone bond, creating a tension-transmitting element.

## Hypothesis
1. **Crossover constraint**: The crossover junction bond (~2.25 nm) will be the
   longest bond in the system and will pull the two helices together. After
   relaxation, helices near bp=10 should move slightly inward vs. ideal geometry.
2. **Mobility gradient**: Backbone beads near the crossover (bp 8-12) should
   show LOWER average displacement from initial positions (less free to move)
   compared to free ends (bp 0-4 and bp 16-20) which have no cross-helix constraint.
3. **Direction**: The effect should be visible on the FORWARD scaffold strand
   as well, since base-pair bonds connect it to the constrained staple beads.

## Physical expectation
In real DNA origami, crossover regions are stiffer and show lower B-factors in
cryo-EM maps. This experiment tests whether the XPBD model qualitatively
reproduces this gradient, even without proper distance-dependent stiffness.
