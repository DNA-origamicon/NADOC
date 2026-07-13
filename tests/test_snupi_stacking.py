"""Phase 2 — base-stacking Morse element (:mod:`backend.physics.snupi_stacking`)."""
from __future__ import annotations

import numpy as np
import pytest

from backend.physics import snupi_stacking as stk


def test_morse_well_depth_and_dissociation():
    p = stk.MorseParams()
    assert stk.morse_energy(p.r0, p) == pytest.approx(-p.eps)      # min = −ε at r₀
    assert stk.morse_energy(5.0, p) == pytest.approx(0.0, abs=1e-2)  # → 0 unstacked
    assert stk.morse_energy(0.05, p) > 0.0                         # steep repulsive wall when compressed
    # compressing below r₀ produces a repulsive (push-apart) force: −dΠ/dr > 0
    assert -stk.morse_dEdr(0.2, p) > 0.0


def test_morse_force_matches_finite_difference():
    p = stk.MorseParams()
    for r in (0.2, p.r0, 0.6, 1.2):
        h = 1e-6
        fd = (stk.morse_energy(r + h, p) - stk.morse_energy(r - h, p)) / (2 * h)
        assert stk.morse_dEdr(r, p) == pytest.approx(fd, abs=1e-3)
    assert stk.morse_dEdr(p.r0, p) == pytest.approx(0.0, abs=1e-9)  # force zero at the well


def test_morse_rupture_force_is_finite_barrier():
    """The bond ruptures once the pulling force exceeds max(dΠ/dr) ≈ 57 pN at r ≈ r₀ + ln2/a — the
    finite barrier that makes the stack a bistable latch (below it stacked, above it unstacks)."""
    p = stk.MorseParams()
    rs = np.linspace(p.r0, p.r0 + 2.0, 400)
    fmax = max(stk.morse_dEdr(float(r), p) for r in rs)
    assert 50.0 < fmax < 65.0


def test_stacking_force_is_central_and_newton_paired():
    xi = np.array([0.0, 0.0, 0.0]); xj = np.array([0.6, 0.0, 0.0])
    fi, fj = stk.stacking_force(xi, xj)
    assert np.allclose(fi, -fj)                     # Newton's third law
    assert fj[0] < 0 and abs(fj[1]) < 1e-9 and abs(fj[2]) < 1e-9   # attractive along the bond (r>r₀)


def test_stacking_tangent_matches_finite_difference():
    xi = np.array([0.0, 0.0, 0.0]); xj = np.array([0.6, 0.1, 0.0])
    K = stk.stacking_tangent(xi, xj)
    base = np.concatenate(stk.stacking_force(xi, xj))
    h = 1e-6
    Knum = np.zeros((6, 6))
    for k in range(6):
        dx = np.zeros(6); dx[k] = h
        f2 = np.concatenate(stk.stacking_force(xi + dx[:3], xj + dx[3:]))
        Knum[:, k] = -(f2 - base) / h
    assert np.abs(K - Knum).max() < 1e-2


def test_is_stacked_distinguishes_states():
    assert stk.is_stacked(np.zeros(3), np.array([stk.R0_STACK, 0, 0]))
    assert not stk.is_stacked(np.zeros(3), np.array([3.0, 0, 0]))
