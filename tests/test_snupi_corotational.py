"""Phase-D pins: the SNUPI full corotational 3D beam (G4) + Newton solve (G5).

Proves the element/solver CONVENTION mechanically against analytic benchmarks (not by reasoning):
rigid-body invariance, exact linear-Euler-Bernoulli recovery in the small-strain limit, and a
convergent large-deflection cantilever with the correct geometric foreshortening. See
memory/project_snupi_gaps.md (Phase D) — the earlier naive Newton diverged for lack of a
consistent corotational internal force; these pin that it is now consistent.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.physics.snupi_corotational import (
    element_force_tangent,
    element_reference,
    exp_so3,
    local_beam_stiffness_12,
    log_so3,
    solve_corotational,
)


def test_so3_exp_log_roundtrip():
    for v in ([0.1, -0.2, 0.3], [2.0, 0.0, 0.0], [0.0, 0.0, 3.0]):
        v = np.array(v)
        assert np.allclose(log_so3(exp_so3(v)), v, atol=1e-8)


def test_element_zero_force_at_rest_and_under_rigid_motion():
    """The consistent internal force must vanish at rest AND under any rigid-body motion — the
    property the earlier naive residual lacked (its f_int was frame-inconsistent)."""
    K12 = local_beam_stiffness_12(0.34, 1100.0, 460.0, 230.0, 245.0)
    x1 = np.array([0.0, 0.0, 0.0]); x2 = np.array([0.0, 0.0, 0.34])
    ref = element_reference(x1, x2, np.eye(3), np.eye(3))
    f0, K = element_force_tangent(x1, x2, np.eye(3), np.eye(3), ref, K12)
    assert np.linalg.norm(f0) < 1e-9
    assert np.allclose(K, K.T, atol=1e-4)                     # symmetric tangent
    Q = exp_so3(np.array([0.3, -0.5, 0.7])); t = np.array([1.0, 2.0, 3.0])
    fr, _ = element_force_tangent(Q @ x1 + t, Q @ x2 + t, Q @ np.eye(3), Q @ np.eye(3), ref, K12)
    assert np.linalg.norm(fr) < 1e-8                          # THE key gate: rigid ⇒ zero force


def _cantilever(Nel=20, Le=1.0, EA=1e5, GJ=1e4, EI=1e3):
    X0 = np.array([[0.0, 0.0, k * Le] for k in range(Nel + 1)])
    elems = [(k, k + 1, element_reference(X0[k], X0[k + 1], np.eye(3), np.eye(3)),
              local_beam_stiffness_12(Le, EA, GJ, EI, EI)) for k in range(Nel)]
    return X0, elems, list(range(6)), Nel * Le, EI


def test_small_load_recovers_linear_euler_bernoulli():
    """A tiny tip load must reproduce the analytic cantilever δ = F L³/3EI — proving the
    corotational element carries the correct bending stiffness (EICR wraps the exact 12×12)."""
    X0, elems, fixed, L, EI = _cantilever()
    Nel = len(X0) - 1
    F = 0.01
    fe = np.zeros(6 * (Nel + 1)); fe[6 * Nel] = F                  # transverse tip load (x)
    X, _R, conv = solve_corotational(X0, elems, fe, fixed, n_steps=10, max_iter=60)
    assert conv
    tip_x = X[Nel][0]
    assert tip_x == pytest.approx(F * L**3 / (3 * EI), rel=2e-3)   # ratio ≈ 1.000


def test_large_deflection_converges_with_foreshortening():
    """A large tip load must CONVERGE (the earlier naive Newton diverged) and show geometric
    foreshortening — the tip pulls axially inward (z < L), which a linear solve cannot capture."""
    X0, elems, fixed, L, EI = _cantilever()
    Nel = len(X0) - 1
    F = 3.0
    fe = np.zeros(6 * (Nel + 1)); fe[6 * Nel] = F
    X, _R, conv = solve_corotational(X0, elems, fe, fixed, n_steps=30, max_iter=60)
    assert conv                                                   # convergence is the headline
    tip = X[Nel]
    assert np.all(np.isfinite(tip))
    assert tip[2] < L - 0.5                                       # foreshortened (elastica)
    lin = F * L**3 / (3 * EI)
    assert tip[0] < lin                                           # nonlinear stiffer than linear extrapolation


def test_corotational_integration_on_real_design_converges():
    """Phase D wired end-to-end: predict_shape(material='snupi', corotational=True) runs the
    corotational Newton (+ electrostatics in the residual, G11) on a real bundle and returns a
    finite, physically-bounded shape; the default fixed-point snupi path is unchanged."""
    from backend.core.models import LatticeType
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.physics.fem_solver import predict_shape

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 1), (1, 1)], 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
        d = design_state.get_or_404().model_copy(deep=True)

    cor = predict_shape(d, nonlinear=True, with_rmsf=False, material="snupi", corotational=True)
    fp = predict_shape(d, nonlinear=True, with_rmsf=False, material="snupi", corotational=False)
    Pc = np.array([p["backbone_position"] for p in cor["positions"]])
    Pf = np.array([p["backbone_position"] for p in fp["positions"]])
    assert np.all(np.isfinite(Pc))                                # converged to finite positions
    assert Pc.shape == Pf.shape
    assert np.ptp(Pc, axis=0).max() < 3.0 * np.ptp(Pf, axis=0).max()   # physically bounded (no blow-up)
