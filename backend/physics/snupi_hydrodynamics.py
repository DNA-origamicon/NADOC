"""SNUPI hydrodynamic model — Rotne–Prager–Yamakawa mobility → friction matrix Z (Phase 1b).

The paper (Lee/Koh/Kim 2023, Supp Note 3) models the solvent's viscous drag with a generalized RPY
mobility matrix Ξ (6 DOF/node) and takes the friction matrix as ``Z = Ξ⁻¹``; the random force is
colored by ``Z`` (fluctuation–dissipation ``⟨R R⟩ = 2 k_BT Z``). Unlike the diagonal Stokes drag of
Phase 1a, the RPY mobility couples the motion of nearby nodes through the fluid — the hydrodynamic
interaction — which sets the collective diffusion, the breathing timescale, and the dynamic
cross-correlations (the paper's Fig 4 correlation maps), WITHOUT changing the equilibrium
configuration distribution (that is friction-independent — the Phase 1b invariant we test).

**Production model — translational RPY.** :func:`rpy_mobility_translational` + ``friction_matrix``
(default ``generalized=False``) implement the full translational RPY tensor Ξ_tt (self Stokes + the
pair tensor with the r < 2a overlap regularization that keeps Ξ SPD — essential here, since adjacent
bp sit 0.34 nm apart ≪ 2σ = 2.2 nm), plus the self rotational Stokes drag on the rotational DOF. The
translational hydrodynamic coupling is the dominant (∝1/r) effect and stays SPD at origami density.

**1b-ii — full generalized RPY (opt-in).** :func:`rpy_mobility_generalized` adds the rotation–
translation (∝1/r²) and rotation–rotation (∝1/r³) coupling blocks with their r < 2a regularizations
(Wajnryb et al. 2013, eqs 3.13/3.15 — transcribed + verified continuous at r = 2a). Each *pair* is SPD
at every separation, but the many-body superposition loses positive-definiteness at the extreme bead
overlap of an origami mesh (σ = 1.1 nm beads 0.34 nm apart, r/a ≈ 0.3, ~10 near-concentric neighbours
per node) — so ``friction_matrix(generalized=True)`` raises rather than return a non-PD friction. This
is why translational-only RPY is the production model; the rotational coupling is available only for
dilute bead sets, and it changes only the kinetics (the equilibrium RMSF is friction-independent).

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


def _skew(v: np.ndarray) -> np.ndarray:
    """Cross-product matrix E(v) with ``E(v)·w = v × w`` (the ε·v of the RPY rt coupling)."""
    return np.array([[0.0, -v[2], v[1]],
                     [v[2], 0.0, -v[0]],
                     [-v[1], v[0], 0.0]])


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


def _rpy_pair_rr(rvec: np.ndarray, a: float) -> np.ndarray:
    """3×3 rotation–rotation RPY mobility block between two beads of radius ``a`` (Wajnryb 2013
    eq 3.13; ζ_rr = STOKES_ROT). Non-overlap (r ≥ 2a) = the rotlet-dipole ``∝1/r³``; overlap (r < 2a)
    the paper's regularization (continuous at r = 2a; keeps the grand mobility SPD)."""
    r = float(np.linalg.norm(rvec))
    if r < 1e-9:
        return (1.0 / STOKES_ROT) * _I3
    rh = rvec / r
    P = np.outer(rh, rh)
    if r >= 2.0 * a:
        # 1/(16πηr³) = a³ / (2·ζ_rr·r³)
        return (a ** 3 / (2.0 * STOKES_ROT * r ** 3)) * (3.0 * P - _I3)
    x = r / a
    A = 1.0 - (27.0 / 32.0) * x + (5.0 / 64.0) * x ** 3
    B = (9.0 / 32.0) * x - (3.0 / 64.0) * x ** 3
    return (1.0 / STOKES_ROT) * (A * _I3 + B * P)


def _rpy_pair_rt(rvec: np.ndarray, a: float) -> np.ndarray:
    """3×3 rotation–translation coupling RPY block μ^rt = μ^tr·(±) between two beads (Wajnryb 2013
    eq 3.15) = ``scale(r)·E(r̂)``, the antisymmetric ε·r̂ coupling ``∝1/r²``. Overlap (r < 2a) uses the
    paper's regularization (continuous at r = 2a; self coupling = 0). The overall skew sign is a
    convention flipped by conjugating the rotational DOF (diag(I,−I)) — SPD-invariant — so only the
    magnitude is load-bearing."""
    r = float(np.linalg.norm(rvec))
    if r < 1e-9:
        return np.zeros((3, 3))
    rh = rvec / r
    if r >= 2.0 * a:
        s = (a ** 3) / (STOKES_ROT * r * r)           # 1/(8πηr²) = a³/(ζ_rr·r²)
    else:
        x = r / a
        s = (a / (2.0 * STOKES_ROT)) * (x - (3.0 / 8.0) * x * x)  # 1/(16πηa²) = a/(2·ζ_rr)
    return s * _skew(rh)


def rpy_mobility_generalized(positions: np.ndarray, a: float = HYDRO_RADIUS_NM) -> np.ndarray:
    """The FULL generalized 6N×6N RPY mobility Ξ (Wajnryb 2013, 1b-ii): all four coupling blocks —
    translation–translation (∝1/r), rotation–translation (∝1/r²) and rotation–rotation (∝1/r³) — with
    the r < 2a overlap regularizations that keep Ξ SPD for every configuration (essential here: bonded
    bp sit 0.34 nm ≪ 2a = 2.2 nm). DOF order per node ``[tx,ty,tz, rx,ry,rz]``.

    Self blocks: tt = 1/STOKES_TRANS·I, rr = 1/STOKES_ROT·I, tr = 0. Symmetry is enforced by mirroring
    each upper-triangle 6×6 pair block into the lower triangle as its transpose (Lorentz reciprocity)."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    mu_t, mu_r = 1.0 / STOKES_TRANS, 1.0 / STOKES_ROT
    Xi = np.zeros((6 * n, 6 * n), dtype=float)
    for i in range(n):
        bi = 6 * i
        Xi[bi:bi + 3, bi:bi + 3] = mu_t * _I3          # tt self (Stokes translational)
        Xi[bi + 3:bi + 6, bi + 3:bi + 6] = mu_r * _I3  # rr self (Stokes rotational)
        for j in range(i + 1, n):
            bj = 6 * j
            rvec = pos[i] - pos[j]                      # R_ij for the i←j block
            tt = _rpy_pair_tt(rvec, a, mu_t)
            rr = _rpy_pair_rr(rvec, a)
            tr = _rpy_pair_rt(rvec, a)                  # trans_i ↔ rot_j coupling
            Xi[bi:bi + 3, bj:bj + 3] = tt
            Xi[bi + 3:bi + 6, bj + 3:bj + 6] = rr
            Xi[bi:bi + 3, bj + 3:bj + 6] = tr
            Xi[bi + 3:bi + 6, bj:bj + 3] = tr.T        # μ^rt = μ^tr^T
            Xi[bj:bj + 6, bi:bi + 6] = Xi[bi:bi + 6, bj:bj + 6].T   # reciprocity → symmetric
    return Xi


def friction_matrix(positions: np.ndarray, a: float = HYDRO_RADIUS_NM,
                    generalized: bool = False) -> np.ndarray:
    """The 6N×6N SNUPI friction matrix ``Z = Ξ⁻¹`` (pN·ns/nm on translational DOF, pN·nm·ns on
    rotational), ordered per node ``[tx,ty,tz, rx,ry,rz]``. SPD.

    ``generalized=False`` (**default — the production model**): the translational-only RPY pass —
    ``inv(Ξ_tt)`` on the translational block, diagonal self rotational Stokes drag on the rotational
    DOF (half-dimension inverse). Stays SPD at DNA-origami bead density.

    ``generalized=True`` (1b-ii, opt-in): invert the FULL generalized RPY mobility
    (:func:`rpy_mobility_generalized`) — adds rotation–translation (∝1/r²) + rotation–rotation (∝1/r³)
    hydrodynamic coupling (Wajnryb 2013). Correct and SPD for *sufficiently separated* beads, but the
    superposition RPY loses positive-definiteness at the extreme overlap of an origami FE mesh (σ =
    1.1 nm beads only 0.34 nm apart, r/a ≈ 0.3, summed over ~10 neighbours). It is therefore **NOT the
    production friction** — it raises ``ValueError`` rather than return a non-PD (unphysical) Z, so a
    caller never silently gets garbage. Use it only on dilute / well-separated bead sets. The
    equilibrium RMSF is friction-independent either way; only the kinetics differ."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    if generalized:
        Xi = rpy_mobility_generalized(pos, a)
        try:
            np.linalg.cholesky(Xi)                     # PD probe (cheap, exact)
        except np.linalg.LinAlgError as exc:
            raise ValueError(
                "Generalized RPY mobility is not positive-definite for this configuration — the "
                "rotation-translation/rotation-rotation coupling of superposition RPY breaks down at "
                "the extreme bead overlap of a DNA-origami mesh (r/a ≈ 0.3). Use generalized=False "
                "(translational-only, the production model)."
            ) from exc
        Z = np.linalg.inv(Xi)
        return 0.5 * (Z + Z.T)                         # symmetrize (guard tiny asymmetry)
    Xi_tt = rpy_mobility_translational(pos, a)
    Z_tt = np.linalg.inv(Xi_tt)
    Z_tt = 0.5 * (Z_tt + Z_tt.T)
    Z = np.zeros((6 * n, 6 * n), dtype=float)
    for i in range(n):
        for j in range(n):
            Z[6 * i:6 * i + 3, 6 * j:6 * j + 3] = Z_tt[3 * i:3 * i + 3, 3 * j:3 * j + 3]
        Z[6 * i + 3:6 * i + 6, 6 * i + 3:6 * i + 6] = STOKES_ROT * _I3
    return Z
