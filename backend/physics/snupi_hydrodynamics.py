"""SNUPI hydrodynamic model — Rotne–Prager–Yamakawa mobility → friction matrix Z (Phase 1b).

The paper (Lee/Koh/Kim 2023, Supp Note 3) models the solvent's viscous drag with a generalized RPY
mobility matrix Ξ (6 DOF/node) and takes the friction matrix as ``Z = Ξ⁻¹``; the random force is
colored by ``Z`` (fluctuation–dissipation ``⟨R R⟩ = 2 k_BT Z``). Unlike the diagonal Stokes drag of
Phase 1a, the RPY mobility couples the motion of nearby nodes through the fluid — the hydrodynamic
interaction — which sets the collective diffusion, the breathing timescale, and the dynamic
cross-correlations (the paper's Fig 4 correlation maps), WITHOUT changing the equilibrium
configuration distribution (that is friction-independent — the Phase 1b invariant we test).

**Scope (this pass — translational RPY).** We implement the full translational RPY tensor Ξ_tt (self
Stokes + the pair tensor with the r < 2a overlap regularization that keeps Ξ SPD — essential here,
since adjacent bp sit 0.34 nm apart ≪ 2σ = 2.2 nm), plus the self rotational Stokes drag on the
rotational DOF. The translational hydrodynamic coupling is the dominant (∝1/r) effect. The full
generalized rotation–translation / rotation–rotation coupling blocks (Wajnryb et al. 2013, the ∝1/r²
and ∝1/r³ terms) are the documented **1b-ii refinement** — they only add torsional hydrodynamics.

Everything is built in the module's **nm · pN · ns** unit system (see :mod:`snupi_dynamics`): the
Stokes self mobility is ``1/STOKES_TRANS`` (translational) / ``1/STOKES_ROT`` (rotational), and all
RPY pair terms are dimensionless ratios of ``a/r`` times that self mobility — so units are automatic.
"""
from __future__ import annotations

import numpy as np

from backend.physics.snupi_dynamics import (
    HYDRO_RADIUS_NM,
    STOKES_TRANS,
    STOKES_ROT,
)

_I3 = np.eye(3)


def _rpy_pair_tt(rvec: np.ndarray, a: float, mu_self: float) -> np.ndarray:
    """3×3 translational RPY mobility block between two beads of radius ``a`` separated by ``rvec``
    (nm). ``mu_self = 1/(6πηa)`` is the Stokes self mobility. Uses the r ≥ 2a far tensor and the
    r < 2a overlap regularization (continuous at r = 2a; keeps the grand mobility SPD)."""
    r = float(np.linalg.norm(rvec))
    if r < 1e-9:
        return mu_self * _I3
    rh = rvec / r
    P = np.outer(rh, rh)
    if r >= 2.0 * a:
        pref = mu_self * (3.0 * a / (4.0 * r))
        return pref * ((1.0 + 2.0 * a * a / (3.0 * r * r)) * _I3
                       + (1.0 - 2.0 * a * a / (r * r)) * P)
    # overlapping spheres (r < 2a) — the RPY regularization
    return mu_self * ((1.0 - 9.0 * r / (32.0 * a)) * _I3
                      + (3.0 * r / (32.0 * a)) * P)


def rpy_mobility_translational(positions: np.ndarray, a: float = HYDRO_RADIUS_NM) -> np.ndarray:
    """Full translational RPY mobility Ξ_tt (3N×3N, SPD) for beads at ``positions`` (N,3 in nm).
    Self blocks = Stokes ``1/STOKES_TRANS·I``; pair blocks = :func:`_rpy_pair_tt`."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    mu_self = 1.0 / STOKES_TRANS
    Xi = np.zeros((3 * n, 3 * n), dtype=float)
    for i in range(n):
        Xi[3 * i:3 * i + 3, 3 * i:3 * i + 3] = mu_self * _I3
        for j in range(i + 1, n):
            blk = _rpy_pair_tt(pos[j] - pos[i], a, mu_self)
            Xi[3 * i:3 * i + 3, 3 * j:3 * j + 3] = blk
            Xi[3 * j:3 * j + 3, 3 * i:3 * i + 3] = blk.T
    return Xi


def friction_matrix(positions: np.ndarray, a: float = HYDRO_RADIUS_NM) -> np.ndarray:
    """The 6N×6N SNUPI friction matrix ``Z`` (pN·ns/nm on translational DOF, pN·nm·ns on rotational),
    ordered per node ``[tx,ty,tz, rx,ry,rz]``.

    Translational block = ``inv(Ξ_tt)`` (the RPY hydrodynamic coupling); rotational DOF carry the
    diagonal self rotational Stokes drag ``STOKES_ROT`` (no rot–rot / rot–trans coupling in this pass).
    Because the rotation–translation mobility coupling is zero here, Z is block-structured, so we invert
    only the 3N×3N translational mobility (half the dimension) rather than the full 6N×6N. Z is SPD."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    Xi_tt = rpy_mobility_translational(pos, a)
    Z_tt = np.linalg.inv(Xi_tt)
    Z_tt = 0.5 * (Z_tt + Z_tt.T)                      # symmetrize (guard tiny asymmetry)
    Z = np.zeros((6 * n, 6 * n), dtype=float)
    for i in range(n):
        for j in range(n):
            Z[6 * i:6 * i + 3, 6 * j:6 * j + 3] = Z_tt[3 * i:3 * i + 3, 3 * j:3 * j + 3]
        Z[6 * i + 3:6 * i + 6, 6 * i + 3:6 * i + 6] = STOKES_ROT * _I3
    return Z
