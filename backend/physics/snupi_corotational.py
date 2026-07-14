"""SNUPI full corotational 3D beam element (SI Notes S1–S2) — Phase D (G4/G5/G11).

The validated snupi/cando shape solve freezes element frames per load level (a corotational
*predictor*) and iterates only the electrostatics; that is exact per level but is not a genuine
per-step Newton, so a single large step under-rotates. This module adds the real thing: a 2-node
3D **corotational** beam with a CONSISTENT internal-force vector and material + geometric tangent,
driven by a global Newton–Raphson solve. It improves only the Fine-mode SHAPE (the validated
RMSF/DCCM metrics are the separate NMA, untouched).

Formulation — **element-independent corotational (EICR)**: rather than re-derive a bespoke local
beam (the error-prone route that made an earlier naive Newton diverge — see project_snupi_mimic S9),
we wrap the STANDARD, correct 12×12 linear beam as the local core. Each iteration: (1) build the
corotated frame E (local z = chord) from the node positions + triads; (2) extract the LOCAL
deformational displacement d_l (rigid-body motion removed, referenced to the initial config);
(3) f_l = K₁₂·d_l — a consistent internal force in the local frame; (4) rotate back to global,
f_g = T f_l. So the effective stiffness is exactly the validated element's, and only the large-
rotation kinematics are added. Nodal orientations are carried as 3×3 triads, updated by the
exponential map each Newton step. Pure Physical layer (Three-Layer Law): shape/display only.
"""
from __future__ import annotations

import numpy as np

_I3 = np.eye(3)


# ── SO(3) utilities (Rodrigues) ─────────────────────────────────────────────────

def _skew(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def exp_so3(phi) -> np.ndarray:
    """Rotation matrix from a rotation vector (Rodrigues)."""
    phi = np.asarray(phi, dtype=float)
    a = float(np.linalg.norm(phi))
    if a < 1e-12:
        return _I3 + _skew(phi)
    K = _skew(phi / a)
    return _I3 + np.sin(a) * K + (1.0 - np.cos(a)) * (K @ K)


def log_so3(R) -> np.ndarray:
    """Rotation vector from a rotation matrix (inverse of :func:`exp_so3`)."""
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    a = np.arccos(c)
    if a < 1e-10:
        return 0.5 * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    if abs(a - np.pi) < 1e-6:
        A = (R + _I3) / 2.0
        axis = np.sqrt(np.clip(np.diag(A), 0.0, None))
        if axis[0] > 1e-6:
            axis[1] = np.sign(A[0, 1]) * axis[1]; axis[2] = np.sign(A[0, 2]) * axis[2]
        elif axis[1] > 1e-6:
            axis[2] = np.sign(A[1, 2]) * axis[2]
        return a * axis / (np.linalg.norm(axis) or 1.0)
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return (a / (2.0 * np.sin(a))) * w


# ── Local 12×12 beam stiffness (DOF [u,v,w,θx,θy,θz] per node, local z = axial) ──

def local_beam_stiffness_12(L, EA, GJ, EIy, EIz):
    """12×12 Euler-Bernoulli beam in the local frame, local z = axial (matches fem_solver's
    ``_beam_stiffness_local`` convention). EIy bends in the x–z plane (u,θy), EIz in y–z (v,θx)."""
    K = np.zeros((12, 12))
    ea, gj = EA / L, GJ / L
    K[2, 2] = ea; K[2, 8] = -ea; K[8, 2] = -ea; K[8, 8] = ea         # axial (w)
    K[5, 5] = gj; K[5, 11] = -gj; K[11, 5] = -gj; K[11, 11] = gj     # torsion (θz)
    # bending x–z (u=0,θy=4,u2=6,θy2=10) with EIy
    ei = EIy; c1 = 12 * ei / L**3; c2 = 6 * ei / L**2; c3 = 4 * ei / L; c4 = 2 * ei / L
    K[0, 0] = c1; K[0, 4] = c2; K[0, 6] = -c1; K[0, 10] = c2
    K[4, 0] = c2; K[4, 4] = c3; K[4, 6] = -c2; K[4, 10] = c4
    K[6, 0] = -c1; K[6, 4] = -c2; K[6, 6] = c1; K[6, 10] = -c2
    K[10, 0] = c2; K[10, 4] = c4; K[10, 6] = -c2; K[10, 10] = c3
    # bending y–z (v=1,θx=3,v2=7,θx2=9) with EIz
    ei = EIz; c1 = 12 * ei / L**3; c2 = 6 * ei / L**2; c3 = 4 * ei / L; c4 = 2 * ei / L
    K[1, 1] = c1; K[1, 3] = -c2; K[1, 7] = -c1; K[1, 9] = -c2
    K[3, 1] = -c2; K[3, 3] = c3; K[3, 7] = c2; K[3, 9] = c4
    K[7, 1] = -c1; K[7, 3] = c2; K[7, 7] = c1; K[7, 9] = c2
    K[9, 1] = -c2; K[9, 3] = c4; K[9, 7] = c2; K[9, 9] = c3
    return K


# ── Corotational kinematics (EICR) ──────────────────────────────────────────────

def _cr_frame(x1, x2, R1, R2):
    """Corotated frame E (cols [e1,e2,e3], **e3 = chord = local axial**) + current length Lf.
    e1/e2 from the mean nodal x-axis (Battini auxiliary vector), orthogonalised against the chord."""
    d = x2 - x1
    Lf = float(np.linalg.norm(d))
    e3 = d / Lf
    q = 0.5 * (R1[:, 0] + R2[:, 0])
    e2 = np.cross(e3, q); n2 = np.linalg.norm(e2)
    if n2 < 1e-8:
        q = 0.5 * (R1[:, 1] + R2[:, 1]); e2 = np.cross(e3, q); n2 = np.linalg.norm(e2)
    e2 = e2 / n2
    e1 = np.cross(e2, e3)
    return np.column_stack([e1, e2, e3]), Lf


def element_reference(x10, x20, R10, R20, rest_length=None):
    """Rest data ``(L0, E0, Rref1, Rref2)`` from the initial config; ``RrefN = E0ᵀ RN0`` is node N's
    initial orientation relative to the initial corotated frame (so rest/rigid motion → zero
    deformation).

    ``rest_length`` overrides ``L0`` for an element whose UNSTRESSED length differs from the
    distance between its nodes in the initial config — SNUPI's ssDNA element, whose rest length is
    the WLC RMS end-to-end distance (G9/SS-1). The axial deformation ``Lf − L0`` then starts
    non-zero, so a short single-stranded gap enters the solve pre-tensioned, as it physically is."""
    E0, L0 = _cr_frame(x10, x20, R10, R20)
    if rest_length is not None:
        L0 = float(rest_length)
    return L0, E0, E0.T @ R10, E0.T @ R20


def _local_defo(x1, x2, R1, R2, ref, E):
    """12-vector local deformational displacement [u1,v1,w1,φ1, u2,v2,w2,φ2] in the corotated
    frame: node 1 at the origin (zero translation); node 2 axial stretch only (transverse absorbed
    by the chord); nodal rotations = deformation from the initial relative orientation."""
    L0, _E0, Rref1, Rref2 = ref
    Lf = float(np.linalg.norm(x2 - x1))
    phi1 = log_so3(Rref1.T @ (E.T @ R1))
    phi2 = log_so3(Rref2.T @ (E.T @ R2))
    d = np.zeros(12)
    d[3:6] = phi1
    d[8] = Lf - L0
    d[9:12] = phi2
    return d


def _T12(E):
    T = np.zeros((12, 12))
    for b in range(4):
        T[3 * b:3 * b + 3, 3 * b:3 * b + 3] = E
    return T


def _internal_force(x1, x2, R1, R2, ref, K12):
    E, _ = _cr_frame(x1, x2, R1, R2)
    return _T12(E) @ (K12 @ _local_defo(x1, x2, R1, R2, ref, E))


def element_force_tangent(x1, x2, R1, R2, ref, K12, *, geometric=True):
    """Consistent global internal force (12) + tangent (12×12) on incremental DOF
    [δu1,δθ1,δu2,δθ2]. Material tangent = ``T K₁₂ Tᵀ``; with ``geometric=True`` the full numerical
    Jacobian ∂f_g/∂d (includes the geometric term through finite rotation)."""
    f_g = _internal_force(x1, x2, R1, R2, ref, K12)
    if not geometric:
        E, _ = _cr_frame(x1, x2, R1, R2)
        T = _T12(E)
        return f_g, T @ K12 @ T.T
    K_g = np.zeros((12, 12))
    eps = 1e-7
    for k in range(12):
        x1p, x2p, R1p, R2p = x1.copy(), x2.copy(), R1.copy(), R2.copy()
        if k < 3:
            x1p[k] += eps
        elif k < 6:
            R1p = exp_so3(_axis(k - 3) * eps) @ R1p
        elif k < 9:
            x2p[k - 6] += eps
        else:
            R2p = exp_so3(_axis(k - 9) * eps) @ R2p
        K_g[:, k] = (_internal_force(x1p, x2p, R1p, R2p, ref, K12) - f_g) / eps
    return f_g, 0.5 * (K_g + K_g.T)


def _axis(i):
    v = np.zeros(3); v[i] = 1.0
    return v


# ── Global Newton–Raphson corotational solve (G5) ───────────────────────────────

def solve_corotational(X0, elements, f_ext, fixed_dofs, *, n_steps=10, max_iter=30,
                       tol=1e-6, R0=None, extra_ft=None, geometric=True):
    """Load-stepped global Newton over corotational beams.

    ``X0`` (N,3) initial positions; ``elements`` = ``(i, j, ref, K12)`` (ref/K12 from
    :func:`element_reference`/:func:`local_beam_stiffness_12`); ``f_ext`` (6N,) dead load on
    [δu,δθ] per node; ``fixed_dofs`` = clamped global DOF indices. ``extra_ft(X, scale)`` (optional)
    returns ``(f_extra 6N, K_extra 6N×6N sparse)`` added to the residual + tangent each iteration —
    the hook for the inter-helix electrostatics (G11: the FULL nonlinear-spring tangent, which a real
    Newton tolerates) and any ssDNA springs, ramped by the load fraction ``scale``. Returns
    ``(X, R, converged)``."""
    from scipy.sparse import lil_matrix
    from scipy.sparse.linalg import spsolve

    N = len(X0)
    X = np.array(X0, dtype=float)
    R = [np.eye(3) for _ in range(N)] if R0 is None else [np.array(r) for r in R0]
    ndof = 6 * N
    fixed = set(int(d) for d in fixed_dofs)
    free = np.array([d for d in range(ndof) if d not in fixed], dtype=int)
    converged = True
    for step in range(1, n_steps + 1):
        scale = step / n_steps
        fe = f_ext * scale
        ok = False
        for _ in range(max_iter):
            f_int = np.zeros(ndof)
            Kt = lil_matrix((ndof, ndof))
            for (i, j, ref, K12) in elements:
                fg, Kg = element_force_tangent(X[i], X[j], R[i], R[j], ref, K12,
                                               geometric=geometric)
                dofs = list(range(6 * i, 6 * i + 6)) + list(range(6 * j, 6 * j + 6))
                for a in range(12):
                    f_int[dofs[a]] += fg[a]
                    row = Kg[a]
                    for b in range(12):
                        if row[b] != 0.0:
                            Kt[dofs[a], dofs[b]] += row[b]
            f_ex = fe
            if extra_ft is not None:
                f_extra, K_extra = extra_ft(X, scale)          # electrostatics + springs (G11)
                f_int = f_int - f_extra                         # move to the internal side
                Kt = Kt + K_extra
            r = f_ex - f_int
            if float(np.linalg.norm(r[free])) < tol * (1.0 + float(np.linalg.norm(f_ex[free]))):
                ok = True
                break
            try:
                dd_free = spsolve(Kt.tocsr()[free][:, free], r[free])
            except Exception:  # noqa: BLE001
                break
            if not np.all(np.isfinite(dd_free)):
                break
            dd = np.zeros(ndof); dd[free] = dd_free
            mx = np.abs(dd).max()
            if mx > 0.5:                       # cap the increment for robustness
                dd *= 0.5 / mx
            for n in range(N):
                X[n] = X[n] + dd[6 * n:6 * n + 3]
                R[n] = exp_so3(dd[6 * n + 3:6 * n + 6]) @ R[n]
        converged = converged and ok
    return X, R, converged
