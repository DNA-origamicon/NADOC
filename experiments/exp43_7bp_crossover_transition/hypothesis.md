# Hypothesis

A central seven-base-pair DNA token in a honeycomb-lattice three-helix system has a
measurably different conditional transition distribution when it is uncoupled,
coupled by one boundary crossover, or bracketed by crossovers at both boundaries.

The crossover-conditioned models should improve predictions of local twist, bend,
shear, inter-helix separation, and relaxation relative to a model that sees only the
central duplex geometry. The two-helix no-crossover control isolates covalent
crossover effects from steric, electrostatic, hydration, and ion effects caused by
neighboring helices.

## Falsification criteria

The hypothesis is not supported if crossover labels add no reproducible held-out
predictive skill after conditioning on initial geometry and velocities, or if a
seven-bp target with its boundary context cannot reproduce longer-range correlation
statistics without a substantially larger target.

## Experimental system

- Honeycomb lattice, a central 21-bp duplex and its two relevant neighbors.
- Prediction token: bp 7 through 13 inclusive.
- Conditions: no crossover, crossover at bp 7 to one neighbor, crossovers at bp 7
  and 14 to the two successive honeycomb neighbors.
- Explicit TIP3P water, 150 mM NaCl, 300 K, CHARMM36/CUFIX reference protocol.
- Full relaxation ladder followed by unrestrained production; 2-fs, non-HMR
  propagator-reference capture includes positions, velocities, and forces.
- This pilot tests topology conditioning. Additional imposed-strain replicas follow
  only after the matched relaxed controls are healthy.
