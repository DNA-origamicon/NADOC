# PEG-supported DNA platform: feasibility-map deliverable

Agreed project direction, 2026-09-10. This document specifies a deliverable;
it does not report a completed parameter sweep or an experimentally validated regime.

## Objective

Map experimentally accessible combinations of PEG brush properties, electrolyte,
electrode potential and platform constraints to stable, resolvable vertical
actuation of a DNA origami platform above gold. Identify robust candidate regimes
and the measurements that could falsify them. PEG supplies mechanical resistance;
electrode–electrolyte–DNA coupling supplies electrical drive.

The user's platform is approximately “50 × 50, honeycomb lattice.” Treat
50 × 50 nm as a provisional dimensional interpretation, not confirmed geometry.
Do not generate or modify molecular topology from that interpretation.
Brush and buffer parameters are design variables. Stroke, precision and response
time are initially performance axes, not invented pass/fail requirements.
Hypothesis 3 and the fulcrum/load specification remain unavailable.

## Inputs and outputs

| Input family | Variables and constraints |
|---|---|
| Brush | PEG molecular weight/dispersity, graft density, end/linker chemistry; derive equilibrium height rather than varying it independently without a constitutive model |
| Electrolyte | Individual ion species/concentrations, pH and temperature; require origami compatibility and assess ion partitioning into PEG |
| Electrode | Potential versus a specified reference, potential of zero charge, Stern/SAM capacitance, coating-specific usable window |
| Platform | Confirmed dimensions/thickness/porosity, charge representation, bending and tilt constraints, support geometry and load |
| Drive | DC hold or waveform, amplitude, frequency/ramp rate, observation time |

For each parameter set retain the complete height-dependent force/free-energy
curve, not just one root. Report equilibrium branches, stability, height–voltage
curves, stroke, differential stiffness, thermal height uncertainty, total force
and torque, and distance from the electrochemical limits. Predict response time
only after specifying and checking a dissipative model, including confined-fluid
drainage where relevant. Distinguish intrinsic equilibrium fluctuations from
measurement uncertainty at a specified bandwidth.

Use dimensionless coordinates such as h/lambda_D, h/H and brush overlap to
organize the map, but export actual molecular weights, graft densities, buffer
recipes and reference-electrode voltages for experimental use. A chosen h/lambda_D
is a diagnostic, not an independently selectable input once h and buffer are set.

## Model and evidence ladder

1. Complete the existing bounded bulk PEG validation. Preserve its frozen scope,
   convergence criteria and allocation limits. Its EOS and chain statistics inform
   brush modeling; they cannot establish electrode or surface validity.
2. Build an inexpensive equilibrium screening model: neutral-brush compression
   plus nonlinear Poisson–Boltzmann electrolyte, a constant-potential electrode
   with interfacial capacitance, and a separately defined DNA charge boundary.
   Include ionic osmotic and Maxwell stresses, and use the thermodynamic potential
   appropriate to fixed voltage. Begin with a planar approximation and state its
   finite-platform/porosity limitations explicitly.
3. Verify the solver before interpreting maps: zero-charge/large-separation and
   linearized limits, stress/free-energy consistency, spatial convergence and
   branch tracking. Avoid double-counting condensed ions through both effective
   charge reduction and explicit treatment of the same population.
4. Sweep broadly, then refine near feasibility boundaries and competing minima.
   Propagate uncertainty in charge, graft density, surface capacitance and
   constitutive laws. Compare alternative defensible boundary/model choices;
   distinguish parameter uncertainty from model discrepancy.
5. Refine promising regions with grafted-PEG compression and finite-platform
   oxDNA calculations, then include ion-specific physics or electrokinetic
   dynamics only where the first model is insufficient for the intended claim.
   Do not add an arbitrary qE term to screened oxDNA and label it validated.
6. Compare predictions with coated-gold electrochemistry, brush force–distance
   measurements and height–voltage measurements, including voltage cycling at
   multiple rates. Reclassify the map using those observations.

For a one-coordinate equilibrium model, stationary heights obey G_h = 0 and
stable branches require G_hh > 0; dh*/dV = -G_hV/G_hh. Check other mechanical
modes before declaring a platform stable. Multiple minima indicate possible
switching; label hysteresis only when barriers and the observation/drive timescale
support it. A monotonic mean height alone does not establish precise control.

## Map labels and experimental selection

Keep physical behavior and evidence status as separate fields.

Physical labels: stable monotonic branch; stable but inadequate stroke or excessive
fluctuations for a selected target; competing minima/pull-in; contact/adhesion;
required voltage outside the measured window. Unknown electrochemical limits
must remain unknown rather than becoming a green feasibility verdict.

Evidence labels: screening prediction; robust across declared uncertainty/model
ranges; requires higher-fidelity modeling; experimentally supported; experimentally
rejected. Report model validity violations rather than extrapolating through them.

Choose a small Pareto set balancing stroke, precision, voltage margin, response
time and fabrication tolerance. Include a predicted non-actuating control and
a boundary case as well as favorable candidates. Candidate sheets must specify
fabrication/buffer/drive conditions, predicted observables with uncertainty,
assumptions, and quantitative falsification criteria established before experiments.
Do not claim compatibility with Hypothesis 3 until that load/failure criterion is known.

## Deliverable package

- Machine-readable parameter table with units, provenance, uncertainty ranges,
  model version, solver checks, outputs and verdicts.
- Linked two-dimensional slices with selectable other parameters, showing feasible
  regions, uncertainty bands and missing-evidence masks; avoid implying an actual
  thermodynamic phase transition merely by calling this a “phase space.”
- Representative force–height, free-energy–height and height–voltage curves,
  including unstable branches and thermal uncertainty where available.
- Short ranked experimental candidate sheets and a list of measurements with
  the greatest expected ability to resolve feasibility uncertainty.

Completion means a reproducible, uncertainty-qualified map and experimentally
actionable candidates, not simply a successful PEG trajectory. Initial ranges
must be justified by literature and fabrication constraints before production
sweeps; this specification does not invent a universal gold voltage window.

## Literature anchors from the preceding assessment

- [Electrical actuation of an origami nanolever](https://pubmed.ncbi.nlm.nih.gov/29111693/):
  related experimental precedent, not validation of this brush-supported geometry.
- [PB force and fixed-potential thermodynamics](https://arxiv.org/abs/0902.1457).
- [PEG bulk and brush scaling](https://www-f1.ijs.si/~rudi/reprints/350.pdf).
- [Brush compression analysis](https://www.frontiersin.org/journals/mechanical-engineering/articles/10.3389/fmech.2022.931271/full).
- [Charged-brush chain rearrangement](https://doi.org/10.1021/acs.langmuir.3c03127):
  does not by itself establish the same transition in neutral PEG.
- [Gold-bound thiolate electrochemical stability](https://doi.org/10.1039/D4AN00241E):
  motivates characterization of the actual coating and buffer.
