"""CI-safe pins for the SNUPI visual-comparison harness (scripts/snupi_visual_compare.py).

The harness itself compares every SNUPI display mode against a local NAMD DCD (gitignored, not in
CI). These tests pin the pure COMPUTATION building blocks it uses — the Kabsch shape RMSD and the
per-bp axis-centre extraction — plus that a predict_shape result carries the fields each visual
reads (positions / axis / rmsf), so a regression in any visual's data is caught without MD.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.core.models import LatticeType
from backend.physics.fem_solver import predict_shape
from scripts.snupi_visual_compare import _fe_axis_centers, _kabsch_rmsd


def test_kabsch_rmsd_zero_under_rigid_motion():
    """RMSD is superposition-invariant: identical / rotated / translated point sets → ~0 nm."""
    rng = np.random.default_rng(0)
    A = rng.normal(size=(40, 3))
    assert _kabsch_rmsd(A, A.copy()) < 1e-9
    theta = 0.7
    R = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    assert _kabsch_rmsd(A, A @ R.T + np.array([5.0, -2.0, 1.0])) < 1e-9


def test_kabsch_rmsd_recovers_known_deformation():
    """A pure axial stretch of a straight line by factor s → a known, non-zero RMSD."""
    z = np.linspace(-10, 10, 50)
    A = np.column_stack([np.zeros_like(z), np.zeros_like(z), z])
    B = A.copy(); B[:, 2] *= 1.5                     # stretch 50% along the line
    rmsd = _kabsch_rmsd(A, B)
    assert rmsd > 1.0                                # substantially different
    assert _kabsch_rmsd(A, A) < 1e-9                 # sanity


@pytest.fixture(scope="module")
def routed_2hb():
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 1), (1, 1)], 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def test_predict_shape_carries_every_visual_field(routed_2hb):
    """Each SNUPI display mode reads a field of the predict_shape result — deform/deviation need
    `positions`, the cylinder rep needs `axis`, the flex map needs `rmsf`. Pin they are all present
    + well-formed so no visual silently loses its data source."""
    out = predict_shape(routed_2hb, nonlinear=False, with_rmsf=True, material="snupi")
    assert out["positions"] and all("backbone_position" in p for p in out["positions"])
    assert out["axis"] and all("helix_id" in a and "bp_index" in a for a in out["axis"])
    assert out["rmsf"] and all(np.isfinite(r["rmsf_nm"]) for r in out["rmsf"])


def test_fe_axis_centers_extracts_matched_keys(routed_2hb):
    """The per-bp axis-centre extraction (the shape-RMSD input) yields one (helix, bp) key per axis
    node with finite 3-D positions."""
    out = predict_shape(routed_2hb, nonlinear=False, with_rmsf=False, material="snupi")
    keys, pos = _fe_axis_centers(out)
    assert len(keys) == len(pos) == len(out["axis"])
    assert pos.shape[1] == 3 and np.all(np.isfinite(pos))
    assert all(isinstance(k[0], str) and isinstance(k[1], int) for k in keys)
