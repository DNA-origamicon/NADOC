"""
Crossover parameterization pipeline.

Extracts CG potentials for non-standard crossover motifs (extra thymines,
future CPD crosslinks) from short atomistic MD of isolated 2-crossover systems,
then injects those parameters into mrdna topology.

Workflow
--------
1. crossover_extract   — assign sequences to 2hb design, build PDB per T-count variant
2. md_setup            — GROMACS setup: solvation, soft end restraints, MDP files
3. param_extract       — MDAnalysis: 6-DOF inter-arm covariance → stiffness matrix
4. convergence         — block averaging, ESS, running-mean diagnostics
5. mrdna_inject        — SegmentModel subclass with per-crossover-type potential overrides
6. validation_stub     — stub: full-origami CG vs atomistic shape comparison

Design rule: parameterization trajectories and validation trajectories must
never be the same runs.  Modules 1-5 produce parameters; module 6 consumes
them on an independent system.
"""
