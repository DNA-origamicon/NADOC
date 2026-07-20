"""Minimum-viable atomistic propagator for DNA origami — Phase 1 pipeline.

Phase-1 modules (no torch required):
    systems.py        motif-aware batch generator of short-duplex NADOC designs
    dataset_build.py  solvate + submit each design as a captured NAMD reference run
    windows.py        turn finished trajectories into training windows + manifest
    analysis.py       reference NAMD structural/dynamical distributions (oracles)

Phase-2+ modules (torch, optional dependency group):
    dataset.py        torch Dataset over the window shards
    baseline.py       one-step baseline model (proves the loader/feature contract)

See the plan at .claude/plans/minimum-viable-atomistic-*.md and the project spec.
"""
