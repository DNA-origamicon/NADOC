"""Exact arithmetic acceleration of the approved Corner bridge gradient.

The equations are the shared atomistic_helpers bridge equations. NumPy's 1D
norm uses sqrt(dot), while Numba's norm uses a different BLAS reduction. Keep
sqrt(dot), disable fastmath, and leave scalar powers in Python to retain the
approved optimizer trajectory. The shared provider is the regression oracle.
"""

from __future__ import annotations

import numpy as _np
from numba import njit
from backend.core.atomistic_helpers import (
    _CANON_C3O3, _CANON_O3P, _CANON_PO5, _CANON_O5C5,
    _COS_C3O3P, _COS_O3PO5, _COS_PO5C5,
)


@njit(cache=True)
def _norm(value):
    return _np.sqrt(_np.dot(value, value))


@njit(cache=True)
def _cos_angle_grad(
    A: _np.ndarray,
    B: _np.ndarray,
    C: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray, _np.ndarray]":
    """Cosine of angle A–B–C and its gradients w.r.t. A, B, C.

    Returns (cos, dA, dB, dC).  Returns (1.0, 0, 0, 0) for degenerate arms.
    """
    u = A - B
    nu = float(_norm(u))
    v = C - B
    nv = float(_norm(v))
    if nu < 1e-12 or nv < 1e-12:
        z = _np.zeros(3)
        return 1.0, z, z, z
    cos_t = float(_np.dot(u, v) / (nu * nv))
    unorm = u / nu
    vnorm = v / nv
    # d(cosθ)/dA = (v/nv − cosθ·u/nu) / nu
    dA = (vnorm - cos_t * unorm) / nu
    # d(cosθ)/dC = (u/nu − cosθ·v/nv) / nv
    dC = (unorm - cos_t * vnorm) / nv
    # d(cosθ)/dB = −(u+v)/(nu·nv) + cosθ·(u/nu² + v/nv²)
    dB = -(u + v) / (nu * nv) + cos_t * (u / (nu * nu) + v / (nv * nv))
    return cos_t, dA, dB, dC


@njit(cache=True)
def _bridge_terms(
    c3: _np.ndarray,
    o3: _np.ndarray,
    p: _np.ndarray,
    o5: _np.ndarray,
    c5: _np.ndarray,
) -> tuple:
    """Cost terms and gradient of the bridge w.r.t. all 5 atoms.

    Returns (terms, g_c3, g_o3, g_p, g_o5, g_c5).
    c3/c5 gradients are used when those atoms belong to a rigid body.
    """
    d_c3o3 = o3 - c3
    n_c3o3 = float(_norm(d_c3o3))
    d_o3p = p - o3
    n_o3p = float(_norm(d_o3p))
    d_po5 = o5 - p
    n_po5 = float(_norm(d_po5))
    d_o5c5 = c5 - o5
    n_o5c5 = float(_norm(d_o5c5))

    def _safe(n: float) -> float:
        return n if n > 1e-12 else 1e-12

    el1 = n_c3o3 - _CANON_C3O3
    el2 = n_o3p - _CANON_O3P
    el3 = n_po5 - _CANON_PO5
    el4 = n_o5c5 - _CANON_O5C5

    # Bond-length gradient: d/dx (|x-a|-L)² = 2(|x-a|-L)(x-a)/|x-a|
    u1 = d_c3o3 / _safe(n_c3o3)
    u2 = d_o3p / _safe(n_o3p)
    u3 = d_po5 / _safe(n_po5)
    u4 = d_o5c5 / _safe(n_o5c5)

    g_c3_bl = -2.0 * el1 * u1
    g_o3_bl = 2.0 * el1 * u1 - 2.0 * el2 * u2
    g_p_bl = 2.0 * el2 * u2 - 2.0 * el3 * u3
    g_o5_bl = 2.0 * el3 * u3 - 2.0 * el4 * u4
    g_c5_bl = 2.0 * el4 * u4

    # Bond-angle gradients
    cos1, dA1, dB1, dC1 = _cos_angle_grad(c3, o3, p)  # ∠C3′-O3′-P:  A=c3, B=o3, C=p
    cos2, dA2, dB2, dC2 = _cos_angle_grad(o3, p, o5)  # ∠O3′-P-O5′:  A=o3, B=p,  C=o5
    cos3, dA3, dB3, dC3 = _cos_angle_grad(p, o5, c5)  # ∠P-O5′-C5′:  A=p,  B=o5, C=c5

    e1 = cos1 - _COS_C3O3P
    e2 = cos2 - _COS_O3PO5
    e3 = cos3 - _COS_PO5C5

    # Angle gradient: d/dx (cosθ - T)² = 2(cosθ-T) · d(cosθ)/dx
    # W = 2 * 0.1: factor of 2 from d(x²)/dx chain rule × 0.1 angle weight.
    # These g_*_ba terms are the COMPLETE angle contribution to the gradient;
    # do NOT multiply by 0.1 again in the return.
    W = 0.2
    g_c3_ba = W * e1 * dA1  # ∠1: c3 is A
    g_o3_ba = W * (e1 * dB1 + e2 * dA2)  # ∠1: o3 is B; ∠2: o3 is A
    g_p_ba = W * (e1 * dC1 + e2 * dB2 + e3 * dA3)  # ∠1: p is C; ∠2: p is B; ∠3: p is A
    g_o5_ba = W * (e2 * dC2 + e3 * dB3)  # ∠2: o5 is C; ∠3: o5 is B
    g_c5_ba = W * e3 * dC3  # ∠3: c5 is C

    cost = (el1, el2, el3, el4, e1, e2, e3)
    return (
        cost,
        g_c3_bl + g_c3_ba,
        g_o3_bl + g_o3_ba,
        g_p_bl + g_p_ba,
        g_o5_bl + g_o5_ba,
        g_c5_bl + g_c5_ba,
    )


def bridge_cost_grad(c3, o3, p, o5, c5):
    terms, *gradient = _bridge_terms(c3, o3, p, o5, c5)
    a, b, c, d, e, f, g = terms
    cost = (a**2 + b**2 + c**2 + d**2) + 0.1*(e**2 + f**2 + g**2)
    return cost, *gradient
