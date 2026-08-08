"""SNUPI hydrodynamic model — Rotne–Prager–Yamakawa mobility → friction matrix Z (Phase 1b).

The paper (Lee/Koh/Kim 2023, Supp Note 3) models the solvent's viscous drag with a generalized RPY
mobility matrix Ξ (6 DOF/node) and takes the friction matrix as ``Z = Ξ⁻¹``; the random force is
colored by ``Z`` (fluctuation–dissipation ``⟨R R⟩ = 2 k_BT Z``). Unlike the diagonal Stokes drag of
Phase 1a, the RPY mobility couples the motion of nearby nodes through the fluid — the hydrodynamic
interaction — which sets the collective diffusion, the breathing timescale, and the dynamic
cross-correlations (the paper's Fig 4 correlation maps), WITHOUT changing the equilibrium
configuration distribution (that is friction-independent — the Phase 1b invariant we test).

**Default model — translational RPY.** :func:`rpy_mobility_translational` + ``friction_matrix``
(default ``generalized=False``) implement the full translational RPY tensor Ξ_tt (self Stokes + the
pair tensor with the r < 2a overlap regularization that keeps Ξ SPD — essential here, since adjacent
bp sit 0.34 nm apart ≪ 2σ = 2.2 nm), plus the self rotational Stokes drag on the rotational DOF. The
translational hydrodynamic coupling is the dominant (∝1/r) effect. This is an APPROXIMATION to the
paper (it drops the rotational coupling), kept as the default only because zero cross-blocks let the
friction be handled 3N×3N instead of 6N×6N — a 4× memory saving that matters at origami scale.

**1b-ii — full generalized RPY (paper-faithful).** :func:`rpy_mobility_generalized` adds the rotation–
translation (∝1/r²) and rotation–rotation (∝1/r³) coupling blocks with their r < 2a regularizations
(Wajnryb et al. 2013 eqs 3.13/3.15 = SNUPI dynamics SI eqs 3.9/3.10 — transcribed + verified continuous
at r = 2a; NB the SI prints the overlap ``r r ᵀ/(σ r²)`` terms with a spurious 1/σ, dimensionally
inconsistent — we use the standard ``r̂ r̂ᵀ`` forms). It IS positive-definite at origami bead density,
as the paper asserts and as the RPY construction guarantees.

*History (2026-07-13):* this module previously claimed the superposition RPY "loses positive-
definiteness at the extreme bead overlap of an origami mesh" and had ``generalized=True`` raise. That
was a BUG in our own cross-block parity, not a property of RPY — see
:func:`rpy_mobility_generalized` for the derivation. Retracted.

Everything is built in the module's **nm · pN · ns** unit system (see :mod:`snupi_dynamics`): the
Stokes self mobility is ``1/STOKES_TRANS`` (translational) / ``1/STOKES_ROT`` (rotational), and all
RPY pair terms are dimensionless ratios of ``a/r`` times that self mobility — so units are automatic.
"""

from __future__ import annotations

import math
import os

import numpy as np

from backend.physics.snupi_dynamics import (
    HYDRO_RADIUS_NM,
    STOKES_TRANS,
    STOKES_ROT,
)

_I3 = np.eye(3)

# ── Memory model ────────────────────────────────────────────────────────────────
# The exact (non-coarse) friction path is O(N²) in memory and there is no way around it: the SNUPI
# algorithm (SI Note 4.3) holds several dense 6N×6N matrices at once — Z, the mass-weighted Z̃, its
# eigenbasis U (our GJF reduction) or the Cholesky S + auxiliary inverses j, b (the paper's). Measured
# peak RSS of our path is ≈ 5.3× the size of ONE dense matrix (N=798→1.01 GB, 1200→2.20, 1596→3.85 GB),
# which this factor reproduces to a few %.
_DENSE_PEAK_FACTOR = 5.5


def estimate_friction_memory_gb(
    n_nodes: int, coarse_bp: int | None = None, n_blobs: int | None = None
) -> float:
    """Predicted PEAK process memory (GB) of building + using the RPY friction for ``n_nodes`` FE nodes.

    ``coarse_bp=None`` → the exact path (dense 6N×6N). ``coarse_bp=k`` → the coarse-grained blob model
    (:mod:`backend.physics.snupi_hydro_coarse`), whose dense object is only 6B×6B for B blobs.

    ``n_blobs`` is the ACTUAL B. Pass it whenever you have it (:func:`snupi_hydro_coarse.blob_count`
    is O(N) and allocation-free): blobs never straddle a helix, and free ssDNA tails are blobbed along
    the chain, so B > ⌈N/k⌉ in general and the ⌈N/k⌉ fallback UNDERSTATES the cost — the wrong way for a
    guard to be wrong.

    This is the number the preflight guard refuses on, so it is deliberately a *peak*, not a steady
    state: a full M13 origami (≈7240 nodes) predicts ≈79 GB exact, ≈0.4 GB coarse at k=8."""
    n = max(int(n_nodes), 1)
    if not coarse_bp:
        dim = 6 * n
    elif n_blobs:
        dim = 6 * int(n_blobs)
    else:
        dim = 6 * math.ceil(n / max(int(coarse_bp), 1))
    return _DENSE_PEAK_FACTOR * (dim**2) * 8 / 1e9


def _total_ram_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):  # pragma: no cover — non-POSIX
        return 8.0


def hydro_memory_budget_gb() -> float:
    """RAM (GB) we allow a hydrodynamics solve to reach. Half of physical RAM by default — the solve
    runs in a DETACHED worker alongside the dev server, the browser and the editor, and overshooting
    does not merely fail the job: it drives the machine into swap and the OOM killer takes whatever is
    biggest (in practice, the user's editor). Override with ``NADOC_HYDRO_MEM_GB``."""
    env = os.environ.get("NADOC_HYDRO_MEM_GB")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return 0.5 * _total_ram_gb()


class HydroMemoryError(MemoryError):
    """Raised (before allocating anything) when an RPY solve would not fit in the memory budget."""


def check_friction_memory(
    n_nodes: int, coarse_bp: int | None = None, n_blobs: int | None = None
) -> None:
    """Preflight the RPY memory cost; raise :class:`HydroMemoryError` with an actionable message rather
    than let the allocation OOM the machine. Call BEFORE building any matrix."""
    need = estimate_friction_memory_gb(n_nodes, coarse_bp, n_blobs)
    budget = hydro_memory_budget_gb()
    if need <= budget:
        return
    mode = (
        f"coarse-grained (1 bead / {coarse_bp} bp)"
        if coarse_bp
        else "exact (1 bead / bp)"
    )
    hint = (
        f"Coarse-graining to 1 bead per 8 bp would need only "
        f"{estimate_friction_memory_gb(n_nodes, 8):.2f} GB."
        if not coarse_bp
        else "Increase the coarse-graining factor, or run without hydrodynamics."
    )
    raise HydroMemoryError(
        f"SNUPI hydrodynamics (RPY) on {n_nodes} nodes needs ≈{need:.1f} GB of RAM in {mode} mode, "
        f"over the {budget:.1f} GB budget. The friction matrix is dense and scales as O(N²) — this is "
        f"inherent to the method (SNUPI's own dynamics example is a 339-bp structure). {hint} "
        f"Or untick Hydrodynamics: the equilibrium shape and flexibility are friction-INDEPENDENT, so "
        f"plain Stokes friction gives the identical mean shape and RMSF — you lose only the kinetics "
        f"(relaxation times, dynamic cross-correlations)."
    )


def mu_self_trans(a: float = HYDRO_RADIUS_NM) -> float:
    """Stokes translational self-mobility ``1/(6πηa)`` of a bead of radius ``a``. ``STOKES_TRANS`` is the
    DRAG 6πησ at the reference radius σ, so this rescales it by σ/a."""
    return (1.0 / STOKES_TRANS) * (HYDRO_RADIUS_NM / a)


def mu_self_rot(a: float = HYDRO_RADIUS_NM) -> float:
    """Stokes rotational self-mobility ``1/(8πηa³)`` of a bead of radius ``a`` (``STOKES_ROT`` = 8πησ³)."""
    return (1.0 / STOKES_ROT) * (HYDRO_RADIUS_NM / a) ** 3


def _skew(v: np.ndarray) -> np.ndarray:
    """Cross-product matrix E(v) with ``E(v)·w = v × w`` (the ε·v of the RPY rt coupling)."""
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


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
        return pref * (
            (1.0 + 2.0 * a * a / (3.0 * r * r)) * _I3
            + (1.0 - 2.0 * a * a / (r * r)) * P
        )
    # overlapping spheres (r < 2a) — the RPY regularization
    return mu_self * ((1.0 - 9.0 * r / (32.0 * a)) * _I3 + (3.0 * r / (32.0 * a)) * P)


def rpy_mobility_translational(
    positions: np.ndarray, a: float = HYDRO_RADIUS_NM
) -> np.ndarray:
    """Full translational RPY mobility Ξ_tt (3N×3N, SPD) for beads at ``positions`` (N,3 in nm).
    Self blocks = Stokes ``1/STOKES_TRANS·I``; pair blocks = :func:`_rpy_pair_tt`."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    mu_self = mu_self_trans(a)
    Xi = np.zeros((3 * n, 3 * n), dtype=float)
    for i in range(n):
        Xi[3 * i : 3 * i + 3, 3 * i : 3 * i + 3] = mu_self * _I3
        for j in range(i + 1, n):
            blk = _rpy_pair_tt(pos[j] - pos[i], a, mu_self)
            Xi[3 * i : 3 * i + 3, 3 * j : 3 * j + 3] = blk
            Xi[3 * j : 3 * j + 3, 3 * i : 3 * i + 3] = blk.T
    return Xi


def _rpy_pair_rr(rvec: np.ndarray, a: float) -> np.ndarray:
    """3×3 rotation–rotation RPY mobility block between two beads of radius ``a`` (Wajnryb 2013
    eq 3.13; ζ_rr = STOKES_ROT). Non-overlap (r ≥ 2a) = the rotlet-dipole ``∝1/r³``; overlap (r < 2a)
    the paper's regularization (continuous at r = 2a; keeps the grand mobility SPD)."""
    r = float(np.linalg.norm(rvec))
    mu_r = mu_self_rot(a)  # 1/(8πηa³)
    if r < 1e-9:
        return mu_r * _I3
    rh = rvec / r
    P = np.outer(rh, rh)
    if r >= 2.0 * a:
        # 1/(16πηr³) = mu_r · a³/(2r³)
        return (mu_r * a**3 / (2.0 * r**3)) * (3.0 * P - _I3)
    x = r / a
    A = 1.0 - (27.0 / 32.0) * x + (5.0 / 64.0) * x**3
    B = (9.0 / 32.0) * x - (3.0 / 64.0) * x**3
    return mu_r * (A * _I3 + B * P)


def _rpy_pair_rt(rvec: np.ndarray, a: float) -> np.ndarray:
    """3×3 rotation–translation coupling RPY block between two beads (Wajnryb 2013 eq 3.15 / SNUPI SI
    eq 3.10) = ``scale(r)·E(r̂)``, the antisymmetric ε·r̂ coupling ``∝1/r²``. Overlap (r < 2a) uses the
    paper's regularization (continuous at r = 2a; self coupling = 0). ``rvec`` is ``r_mn = u_n − u_m``
    (SI eq 3.8) and the block is ODD in it — see :func:`rpy_mobility_generalized` for why that parity
    (not the overall sign, which is a diag(I,−I) convention) is what positive-definiteness turns on."""
    r = float(np.linalg.norm(rvec))
    if r < 1e-9:
        return np.zeros((3, 3))
    rh = rvec / r
    mu_r = mu_self_rot(a)  # 1/(8πηa³)
    if r >= 2.0 * a:
        s = mu_r * (a**3) / (r * r)  # 1/(8πηr²)
    else:
        x = r / a
        s = mu_r * (a / 2.0) * (x - (3.0 / 8.0) * x * x)  # 1/(16πηa²) at x→…
    return s * _skew(rh)


def rpy_mobility_generalized(
    positions: np.ndarray, a: float = HYDRO_RADIUS_NM
) -> np.ndarray:
    """The FULL generalized 6N×6N RPY mobility Ξ (Wajnryb 2013; SNUPI dynamics SI Note 3.2): all four
    coupling blocks — translation–translation (∝1/r), rotation–translation (∝1/r²) and rotation–rotation
    (∝1/r³) — with the r < 2a overlap regularizations that keep Ξ SPD for every configuration (essential
    here: bonded bp sit 0.34 nm ≪ 2a = 2.2 nm). DOF order per node ``[tx,ty,tz, rx,ry,rz]``.

    Self blocks: tt = 1/STOKES_TRANS·I, rr = 1/STOKES_ROT·I, tr = 0.

    **The cross-block parity (the thing PD turns on).** ``μ^rt`` is built from ``ε·r̂``, which is
    ANTISYMMETRIC as a 3×3 and ODD in ``r``. Reciprocity (Ξ = Ξᵀ) requires ``μ^tr_ij = (μ^rt_ji)ᵀ``;
    with ``μ^rt_ji = −μ^rt_ij`` (odd in r) and ``(μ^rt)ᵀ = −μ^rt`` (antisymmetric), that collapses to

        μ^tr_ij = +μ^rt_ij          ← the two cross-blocks of a pair are EQUAL, not transposes

    so BOTH cross-slots of the (i,j) 6×6 take the same block; mirroring ``Ξ_ji = Ξ_ijᵀ`` then reproduces
    the formula's odd-in-r sign for free. Reading the SI's ``μ^rt = [μ^tr]ᵀ`` literally (i.e. storing
    ``tr`` and ``trᵀ``) instead flips one block's sign, and the error COMPOUNDS through the many-body
    superposition — min eig went −2.6e-2 → −1.8e-1 as N grew 40 → 480, which is what previously made us
    believe (wrongly) that generalized RPY simply loses positive-definiteness at origami bead density.
    With the parity right, Ξ is PD and its min eigenvalue is stable in N (+1.58e-3), exactly as the
    paper's PD proof requires. The overall skew SIGN, by contrast, is a mere diag(I,−I) convention and
    is PD-invariant."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    mu_t, mu_r = mu_self_trans(a), mu_self_rot(a)
    Xi = np.zeros((6 * n, 6 * n), dtype=float)
    for i in range(n):
        bi = 6 * i
        Xi[bi : bi + 3, bi : bi + 3] = mu_t * _I3  # tt self (Stokes translational)
        Xi[bi + 3 : bi + 6, bi + 3 : bi + 6] = mu_r * _I3  # rr self (Stokes rotational)
        for j in range(i + 1, n):
            bj = 6 * j
            rvec = pos[j] - pos[i]  # r_ij = u_j − u_i  (SI eq 3.8)
            tr = _rpy_pair_rt(rvec, a)
            Xi[bi : bi + 3, bj : bj + 3] = _rpy_pair_tt(rvec, a, mu_t)
            Xi[bi + 3 : bi + 6, bj + 3 : bj + 6] = _rpy_pair_rr(rvec, a)
            Xi[bi : bi + 3, bj + 3 : bj + 6] = tr  # μ^tr_ij  (trans_i ← rot_j)
            Xi[bi + 3 : bi + 6, bj : bj + 3] = tr  # μ^rt_ij  = μ^tr_ij  (see docstring)
            Xi[bj : bj + 6, bi : bi + 6] = Xi[
                bi : bi + 6, bj : bj + 6
            ].T  # reciprocity → symmetric
    return Xi


def mobility_translational_6n(
    positions: np.ndarray, a: float = HYDRO_RADIUS_NM
) -> np.ndarray:
    """The 6N×6N mobility of the TRANSLATIONAL-ONLY model: the full RPY Ξ_tt on the translational DOF,
    the Stokes self rotational mobility (no coupling) on the rotational ones. The mobility counterpart
    of ``friction_matrix(generalized=False)``, and the cheap ``C`` for the coarse blob model."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    Xi_tt = rpy_mobility_translational(pos, a)
    Xi = np.zeros((6 * n, 6 * n), dtype=float)
    mu_r = mu_self_rot(a)
    for i in range(n):
        for j in range(n):
            Xi[6 * i : 6 * i + 3, 6 * j : 6 * j + 3] = Xi_tt[
                3 * i : 3 * i + 3, 3 * j : 3 * j + 3
            ]
        Xi[6 * i + 3 : 6 * i + 6, 6 * i + 3 : 6 * i + 6] = mu_r * _I3
    return Xi


def friction_matrix(
    positions: np.ndarray, a: float = HYDRO_RADIUS_NM, generalized: bool = False
) -> np.ndarray:
    """The 6N×6N SNUPI friction matrix ``Z = Ξ⁻¹`` (pN·ns/nm on translational DOF, pN·nm·ns on
    rotational), ordered per node ``[tx,ty,tz, rx,ry,rz]``. SPD.

    ``generalized=False`` (**default — the production model**): the translational-only RPY pass —
    ``inv(Ξ_tt)`` on the translational block, diagonal self rotational Stokes drag on the rotational
    DOF (half-dimension inverse). Stays SPD at DNA-origami bead density.

    ``generalized=True`` (1b-ii): invert the FULL generalized RPY mobility
    (:func:`rpy_mobility_generalized`) — adds rotation–translation (∝1/r²) + rotation–rotation (∝1/r³)
    hydrodynamic coupling (Wajnryb 2013). **This is the paper-faithful friction** (SNUPI dynamics SI
    Note 3, which builds all four blocks on exactly this bead set — one bead per bp, σ = 1.1 nm — and
    Cholesky-factors the resulting Z). It is SPD at origami bead density; the PD probe below is kept as
    a cheap guard, not because failure is expected. It is not the DEFAULT only because it forecloses the
    block-structure memory saving of the translational-only path (a dense 6N×6N Z instead of 3N×3N) —
    see :func:`estimate_friction_memory_gb`. The equilibrium RMSF is friction-independent either way;
    only the kinetics (relaxation times, dynamic cross-correlations) differ."""
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    if generalized:
        Xi = rpy_mobility_generalized(pos, a)
        try:
            np.linalg.cholesky(Xi)  # PD probe (cheap, exact)
        except (
            np.linalg.LinAlgError
        ) as exc:  # pragma: no cover — parity fix keeps Ξ SPD
            raise ValueError(
                "Generalized RPY mobility is not positive-definite for this configuration. This should "
                "not happen (RPY is PD by construction, incl. overlaps) — suspect the μ^tr/μ^rt "
                "cross-block parity in rpy_mobility_generalized."
            ) from exc
        Z = np.linalg.inv(Xi)
        return 0.5 * (Z + Z.T)  # symmetrize (guard tiny asymmetry)
    Xi_tt = rpy_mobility_translational(pos, a)
    Z_tt = np.linalg.inv(Xi_tt)
    Z_tt = 0.5 * (Z_tt + Z_tt.T)
    Z = np.zeros((6 * n, 6 * n), dtype=float)
    zeta_rot = 1.0 / mu_self_rot(a)  # rotational Stokes DRAG at radius a (= 8πηa³)
    for i in range(n):
        for j in range(n):
            Z[6 * i : 6 * i + 3, 6 * j : 6 * j + 3] = Z_tt[
                3 * i : 3 * i + 3, 3 * j : 3 * j + 3
            ]
        Z[6 * i + 3 : 6 * i + 6, 6 * i + 3 : 6 * i + 6] = zeta_rot * _I3
    return Z
