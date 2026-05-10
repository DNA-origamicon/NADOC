"""
Pure-math helpers extracted from backend/core/atomistic.py (Pass 11-A).

Leaf module: imports only ``__future__``, ``math``, ``numpy``. No subprocess,
no filesystem I/O, no mutable globals, no imports from other backend.core
modules. Each function is testable with synthetic numeric inputs and returns
its output (no in-place mutation of caller-owned data).

Two families live here:

1. **Pure-math primitives** — ``_lerp``, ``_normalise``, ``_cos_angle_3pt``,
   ``_make_spin_rotation``, ``_spin_rotation_deriv``, ``_bezier_pt``,
   ``_bezier_tan``, ``_arc_bow_dir``, ``_arc_ctrl_pt``.

2. **Cost / gradient leaves** for the joint extra-base minimisers
   (Pass 5-C surfaced these as @60 vulture candidates; verified pure on
   Pass 11-A).  These take dicts/arrays of positions and return scalar cost
   plus gradients without touching atom objects:
   ``_backbone_bridge_cost`` / ``_backbone_bridge_cost_grad``,
   ``_glycosidic_cost``     / ``_glycosidic_cost_grad``,
   ``_repulsion_cost``      / ``_repulsion_cost_grad``,
   ``_rb_pair_repulsion``   / ``_rb_pair_repulsion_grad``,
   ``_rb_grad_propagate``,
   ``_fwd_bridge_x0``, ``_bwd_bridge_x0``.

Canonical bond lengths/angles (B-DNA / AMBER ff14SB) and weight constants
travel with these functions — they are pure floats, no I/O.
"""

from __future__ import annotations

import math as _math

import numpy as _np


# ── Canonical backbone geometry (AMBER ff14SB / B-DNA) ───────────────────────
_CANON_C3O3:  float = 0.1430   # C3′–O3′ bond length (nm)
_CANON_O3P:   float = 0.1600   # O3′–P   bond length (nm)
_CANON_PO5:   float = 0.1590   # P–O5′   bond length (nm)
_CANON_O5C5:  float = 0.1440   # O5′–C5′ bond length (nm)
_CANON_C3O3P: float = 119.0    # ∠C3′–O3′–P  (degrees)
_CANON_O3PO5: float = 103.6    # ∠O3′–P–O5′  (degrees)
_CANON_PO5C5: float = 120.9    # ∠P–O5′–C5′  (degrees)
_DEG2RAD: float = _math.pi / 180.0
# Precomputed cosines of canonical backbone angles (used in joint objective functions)
_COS_C3O3P: float = _math.cos(_CANON_C3O3P * _DEG2RAD)
_COS_O3PO5: float = _math.cos(_CANON_O3PO5 * _DEG2RAD)
_COS_PO5C5: float = _math.cos(_CANON_PO5C5 * _DEG2RAD)

# Phosphate group atoms — treated as free backbone linkers, not part of the ribose rigid body
_PHOSPHATE_ATOMS: frozenset[str] = frozenset({"P", "OP1", "OP2", "O5'"})

# Objective weights for joint extra-base minimisers
_W_GLYCOSIDIC: float = 2.0    # C1′→N alignment penalty (1 − cos θ; range [0, 2])
_W_REPULSION:  float = 100.0  # steric repulsion weight per clashing pair
_R_REPULSION:  float = 0.35   # nm — soft-sphere contact radius (≈ C–C vdW contact)

# Pre-computed chord fractions for proportional initial-guess placement of linker atoms.
# Placing linker atoms proportionally to canonical bond lengths (rather than using the
# template positions) reduces the initial objective by ~10×, cutting scipy iterations
# from ~150 to ~30 for typical crossover distances.
_TOTAL_LINKER_F: float = _CANON_C3O3 + _CANON_O3P + _CANON_PO5 + _CANON_O5C5   # 0.606 nm
_TOTAL_LINKER_B: float = _CANON_O3P  + _CANON_PO5 + _CANON_O5C5                # 0.463 nm
_FRAC_O3_F:  float = _CANON_C3O3                               / _TOTAL_LINKER_F
_FRAC_P_F:   float = (_CANON_C3O3 + _CANON_O3P)               / _TOTAL_LINKER_F
_FRAC_O5_F:  float = (_CANON_C3O3 + _CANON_O3P + _CANON_PO5)  / _TOTAL_LINKER_F
_FRAC_P_B:   float = _CANON_O3P                                / _TOTAL_LINKER_B
_FRAC_O5_B:  float = (_CANON_O3P   + _CANON_PO5)              / _TOTAL_LINKER_B

# Extra-base arc geometry constant (matches crossover_connections.js BOW_FRAC_3D)
_BOW_FRAC_3D: float = 0.3


# ── Pure-math primitives ──────────────────────────────────────────────────────


def _normalise(v: _np.ndarray) -> _np.ndarray:
    n = float(_np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _lerp(p0: _np.ndarray, p1: _np.ndarray, t: float) -> _np.ndarray:
    return p0 + t * (p1 - p0)


def _cos_angle_3pt(a: _np.ndarray, b: _np.ndarray, c: _np.ndarray) -> float:
    """Cosine of angle A–B–C; returns 1.0 for degenerate (zero-length) arms."""
    ba = a - b; bc = c - b
    n1 = float(_np.linalg.norm(ba)); n2 = float(_np.linalg.norm(bc))
    if n1 < 1e-12 or n2 < 1e-12:
        return 1.0
    return float(_np.dot(ba, bc) / (n1 * n2))


def _make_spin_rotation(axis: _np.ndarray, theta: float) -> _np.ndarray:
    """Rodrigues rotation matrix: rotation about unit *axis* by *theta* radians."""
    K = _np.array([
        [ 0.0,      -axis[2],  axis[1]],
        [ axis[2],   0.0,     -axis[0]],
        [-axis[1],   axis[0],  0.0    ],
    ])
    return _np.eye(3) + _math.sin(theta) * K + (1.0 - _math.cos(theta)) * (K @ K)


def _spin_rotation_deriv(axis: _np.ndarray, theta: float) -> _np.ndarray:
    """Derivative dR/dθ of the Rodrigues rotation about *axis* by *theta*.

    dR/dθ = cos(θ)·K + sin(θ)·K² where K is the skew-symmetric cross-product
    matrix for *axis*.
    """
    K = _np.array([
        [ 0.0,      -axis[2],  axis[1]],
        [ axis[2],   0.0,     -axis[0]],
        [-axis[1],   axis[0],  0.0    ],
    ])
    return _math.cos(theta) * K + _math.sin(theta) * (K @ K)


# ── Bond cost / gradient leaves ───────────────────────────────────────────────


def _backbone_bridge_cost(
    c3: _np.ndarray, o3: _np.ndarray,
    p:  _np.ndarray, o5: _np.ndarray,
    c5: _np.ndarray,
) -> float:
    """
    Weighted squared-deviation cost for a C3′–O3′–P–O5′–C5′ chain.
    Bond-length weight = 1.0, bond-angle weight = 0.1.
    Uses module-level _COS_* and _CANON_* constants.
    """
    bl = (
        (_np.linalg.norm(o3 - c3) - _CANON_C3O3) ** 2 +
        (_np.linalg.norm(p  - o3) - _CANON_O3P)  ** 2 +
        (_np.linalg.norm(o5 - p)  - _CANON_PO5)  ** 2 +
        (_np.linalg.norm(c5 - o5) - _CANON_O5C5) ** 2
    )
    ba = (
        (_cos_angle_3pt(c3, o3, p)  - _COS_C3O3P) ** 2 +
        (_cos_angle_3pt(o3, p,  o5) - _COS_O3PO5) ** 2 +
        (_cos_angle_3pt(p,  o5, c5) - _COS_PO5C5) ** 2
    )
    return float(bl + 0.1 * ba)


def _cos_angle_grad(
    A: _np.ndarray, B: _np.ndarray, C: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray, _np.ndarray]":
    """Cosine of angle A–B–C and its gradients w.r.t. A, B, C.

    Returns (cos, dA, dB, dC).  Returns (1.0, 0, 0, 0) for degenerate arms.
    """
    u = A - B;  nu = float(_np.linalg.norm(u))
    v = C - B;  nv = float(_np.linalg.norm(v))
    if nu < 1e-12 or nv < 1e-12:
        z = _np.zeros(3)
        return 1.0, z, z, z
    cos_t  = float(_np.dot(u, v) / (nu * nv))
    unorm  = u / nu;  vnorm = v / nv
    # d(cosθ)/dA = (v/nv − cosθ·u/nu) / nu
    dA = (vnorm - cos_t * unorm) / nu
    # d(cosθ)/dC = (u/nu − cosθ·v/nv) / nv
    dC = (unorm - cos_t * vnorm) / nv
    # d(cosθ)/dB = −(u+v)/(nu·nv) + cosθ·(u/nu² + v/nv²)
    dB = -(u + v) / (nu * nv) + cos_t * (u / (nu * nu) + v / (nv * nv))
    return cos_t, dA, dB, dC


def _backbone_bridge_cost_grad(
    c3: _np.ndarray, o3: _np.ndarray,
    p:  _np.ndarray, o5: _np.ndarray,
    c5: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray, _np.ndarray, _np.ndarray, _np.ndarray]":
    """Value and gradient of backbone bridge cost w.r.t. all 5 atoms.

    Returns (cost, g_c3, g_o3, g_p, g_o5, g_c5).
    c3/c5 gradients are used when those atoms belong to a rigid body.
    """
    d_c3o3 = o3 - c3;  n_c3o3 = float(_np.linalg.norm(d_c3o3))
    d_o3p  = p  - o3;  n_o3p  = float(_np.linalg.norm(d_o3p))
    d_po5  = o5 - p;   n_po5  = float(_np.linalg.norm(d_po5))
    d_o5c5 = c5 - o5;  n_o5c5 = float(_np.linalg.norm(d_o5c5))

    def _safe(n: float) -> float:
        return n if n > 1e-12 else 1e-12

    el1 = n_c3o3 - _CANON_C3O3
    el2 = n_o3p  - _CANON_O3P
    el3 = n_po5  - _CANON_PO5
    el4 = n_o5c5 - _CANON_O5C5

    bl = el1 ** 2 + el2 ** 2 + el3 ** 2 + el4 ** 2

    # Bond-length gradient: d/dx (|x-a|-L)² = 2(|x-a|-L)(x-a)/|x-a|
    u1 = d_c3o3 / _safe(n_c3o3);  u2 = d_o3p / _safe(n_o3p)
    u3 = d_po5  / _safe(n_po5);   u4 = d_o5c5 / _safe(n_o5c5)

    g_c3_bl = -2.0 * el1 * u1
    g_o3_bl =  2.0 * el1 * u1 - 2.0 * el2 * u2
    g_p_bl  =  2.0 * el2 * u2 - 2.0 * el3 * u3
    g_o5_bl =  2.0 * el3 * u3 - 2.0 * el4 * u4
    g_c5_bl =  2.0 * el4 * u4

    # Bond-angle gradients
    cos1, dA1, dB1, dC1 = _cos_angle_grad(c3, o3, p)   # ∠C3′-O3′-P:  A=c3, B=o3, C=p
    cos2, dA2, dB2, dC2 = _cos_angle_grad(o3, p,  o5)  # ∠O3′-P-O5′:  A=o3, B=p,  C=o5
    cos3, dA3, dB3, dC3 = _cos_angle_grad(p,  o5, c5)  # ∠P-O5′-C5′:  A=p,  B=o5, C=c5

    e1 = cos1 - _COS_C3O3P
    e2 = cos2 - _COS_O3PO5
    e3 = cos3 - _COS_PO5C5

    ba = e1 ** 2 + e2 ** 2 + e3 ** 2

    # Angle gradient: d/dx (cosθ - T)² = 2(cosθ-T) · d(cosθ)/dx
    # W = 2 * 0.1: factor of 2 from d(x²)/dx chain rule × 0.1 angle weight.
    # These g_*_ba terms are the COMPLETE angle contribution to the gradient;
    # do NOT multiply by 0.1 again in the return.
    W = 0.2
    g_c3_ba = W * e1 * dA1                              # ∠1: c3 is A
    g_o3_ba = W * (e1 * dB1 + e2 * dA2)                 # ∠1: o3 is B; ∠2: o3 is A
    g_p_ba  = W * (e1 * dC1 + e2 * dB2 + e3 * dA3)     # ∠1: p is C; ∠2: p is B; ∠3: p is A
    g_o5_ba = W * (e2 * dC2 + e3 * dB3)                 # ∠2: o5 is C; ∠3: o5 is B
    g_c5_ba = W * e3 * dC3                              # ∠3: c5 is C

    cost = float(bl + 0.1 * ba)
    return (
        cost,
        g_c3_bl + g_c3_ba,
        g_o3_bl + g_o3_ba,
        g_p_bl  + g_p_ba,
        g_o5_bl + g_o5_ba,
        g_c5_bl + g_c5_ba,
    )


def _glycosidic_cost_grad(
    c1_pos: _np.ndarray,
    n_pos:  _np.ndarray,
    target: _np.ndarray,
) -> "tuple[float, _np.ndarray, _np.ndarray]":
    """Glycosidic alignment cost = 1 − dot(c1n/|c1n|, target).

    Returns (cost, g_c1, g_n) — gradients w.r.t. c1_pos and n_pos.
    """
    c1n    = n_pos - c1_pos
    length = float(_np.linalg.norm(c1n))
    if length < 1e-9:
        return 0.0, _np.zeros(3), _np.zeros(3)
    c1n_hat = c1n / length
    dot_val = float(_np.dot(c1n_hat, target))
    cost    = 1.0 - dot_val
    # d/d(c1n) [1 − dot(c1n/|c1n|, t)] = −(t − dot_val·c1n_hat) / |c1n|
    g_c1n = -(target - dot_val * c1n_hat) / length
    # chain rule: d(c1n)/d(c1_pos) = −I
    return float(cost), -g_c1n, g_c1n


def _repulsion_cost_grad(
    w:         dict[str, _np.ndarray],
    repel_pos: list[_np.ndarray],
) -> "tuple[float, dict[str, _np.ndarray]]":
    """Soft-sphere repulsion cost and gradient.

    Returns (cost, g_dict) where g_dict maps atom name → gradient vector.
    """
    cost   = 0.0
    g_dict: dict[str, _np.ndarray] = {}
    for a_name in ("C1'", "C3'", "C4'"):
        if a_name not in w:
            continue
        pos = w[a_name]
        g   = _np.zeros(3)
        for rep in repel_pos:
            diff = pos - rep
            d    = float(_np.linalg.norm(diff))
            if 1e-12 < d < _R_REPULSION:
                overlap  = 1.0 - d / _R_REPULSION
                cost    += overlap ** 2
                # d/d(pos) (1−d/R)² = 2(1−d/R)(−1/R)(pos−rep)/d
                g += 2.0 * overlap * (-1.0 / _R_REPULSION) * (diff / d)
        g_dict[a_name] = g
    return cost, g_dict


def _rb_pair_repulsion_grad(
    w1: dict[str, _np.ndarray],
    w2: dict[str, _np.ndarray],
) -> "tuple[float, dict[str, _np.ndarray], dict[str, _np.ndarray]]":
    """Soft-sphere pair repulsion cost and gradient for two rigid bodies.

    Returns (cost, g1_dict, g2_dict).
    """
    cost = 0.0
    rep_names = ("C1'", "C3'", "C4'")
    g1: dict[str, _np.ndarray] = {a: _np.zeros(3) for a in rep_names if a in w1}
    g2: dict[str, _np.ndarray] = {b: _np.zeros(3) for b in rep_names if b in w2}
    for a in rep_names:
        if a not in w1:
            continue
        for b in rep_names:
            if b not in w2:
                continue
            diff = w1[a] - w2[b]
            d    = float(_np.linalg.norm(diff))
            if 1e-12 < d < _R_REPULSION:
                overlap  = 1.0 - d / _R_REPULSION
                cost    += overlap ** 2
                g_ab     = 2.0 * overlap * (-1.0 / _R_REPULSION) * (diff / d)
                # d/d(w1[a]) = same sign; d/d(w2[b]) = opposite sign
                g1[a] += g_ab
                g2[b] -= g_ab
    return cost, g1, g2


def _rb_grad_propagate(
    g_w:       dict[str, _np.ndarray],
    names:     "tuple[str, ...]",
    mat:       _np.ndarray,
    dR_dtheta: _np.ndarray,
) -> "tuple[_np.ndarray, float]":
    """Propagate world-position gradients through a rigid-body transform.

    Given accumulated gradients g_w[name] (∂f/∂w[name]) and the rigid-body
    local coordinates (mat rows), compute ∂f/∂delta and ∂f/∂theta.

    d(w[name])/d(delta) = I  →  ∂f/∂delta = Σ g_w[name]
    d(w[name])/d(theta) = dR/dθ @ local[name]  →  ∂f/∂theta = Σ g_w[name]·(dR/dθ @ local)
    """
    g_delta = _np.zeros(3)
    g_theta = 0.0
    name_to_idx = {n: i for i, n in enumerate(names)}
    for name, g in g_w.items():
        if g is None:
            continue
        g_delta += g
        idx = name_to_idx.get(name)
        if idx is not None:
            dw_dth  = dR_dtheta @ mat[idx]   # (3,)
            g_theta += float(_np.dot(g, dw_dth))
    return g_delta, g_theta


def _glycosidic_cost(
    w:     dict[str, _np.ndarray],
    n_name: str,
    target: _np.ndarray,
) -> float:
    """
    C1′→N alignment penalty: 1 − cos(angle to target_c1n).
    Returns 0.0 if the glycosidic N is absent from the rigid-body world dict.
    """
    if n_name not in w or "C1'" not in w:
        return 0.0
    c1n = w[n_name] - w["C1'"]
    length = float(_np.linalg.norm(c1n))
    if length < 1e-9:
        return 0.0
    return float(1.0 - _np.dot(c1n / length, target))


def _repulsion_cost(
    w:         dict[str, _np.ndarray],
    repel_pos: list[_np.ndarray],
) -> float:
    """
    Soft-sphere repulsion between C1′/C3′/C4′ of one rigid body and a list of
    fixed positions (opposite-strand junction atoms).
    Cost = Σ max(0, 1 − d / _R_REPULSION)².
    """
    cost = 0.0
    for a_name in ("C1'", "C3'", "C4'"):
        if a_name not in w:
            continue
        pos = w[a_name]
        for rep in repel_pos:
            d = float(_np.linalg.norm(pos - rep))
            if d < _R_REPULSION:
                cost += (1.0 - d / _R_REPULSION) ** 2
    return cost


def _rb_pair_repulsion(
    w1: dict[str, _np.ndarray],
    w2: dict[str, _np.ndarray],
) -> float:
    """
    Soft-sphere repulsion between C1′/C3′/C4′ atoms of two extra-base rigid bodies.
    Prevents neighbouring extra bases from clashing at the Holliday junction.
    """
    cost = 0.0
    rep_names = ("C1'", "C3'", "C4'")
    for a in rep_names:
        if a not in w1:
            continue
        for b in rep_names:
            if b not in w2:
                continue
            d = float(_np.linalg.norm(w1[a] - w2[b]))
            if d < _R_REPULSION:
                cost += (1.0 - d / _R_REPULSION) ** 2
    return cost


def _fwd_bridge_x0(
    c3_start: "_np.ndarray", c5_end: "_np.ndarray",
) -> "tuple[_np.ndarray, _np.ndarray, _np.ndarray]":
    """Proportional initial positions for O3′, P, O5′ along C3′→C5′ chord."""
    d = c5_end - c3_start
    return (
        c3_start + _FRAC_O3_F * d,
        c3_start + _FRAC_P_F  * d,
        c3_start + _FRAC_O5_F * d,
    )


def _bwd_bridge_x0(
    o3_start: "_np.ndarray", c5_end: "_np.ndarray",
) -> "tuple[_np.ndarray, _np.ndarray]":
    """Proportional initial positions for P, O5′ along O3′→C5′ chord."""
    d = c5_end - o3_start
    return (
        o3_start + _FRAC_P_B  * d,
        o3_start + _FRAC_O5_B * d,
    )


# ── Extra-base arc geometry helpers ──────────────────────────────────────────


def _bezier_pt(
    posA: _np.ndarray, ctrl: _np.ndarray, posB: _np.ndarray, t: float,
) -> _np.ndarray:
    """Quadratic Bezier position: (1-t)²A + 2(1-t)tC + t²B."""
    u = 1.0 - t
    return u * u * posA + 2.0 * u * t * ctrl + t * t * posB


def _bezier_tan(
    posA: _np.ndarray, ctrl: _np.ndarray, posB: _np.ndarray, t: float,
) -> _np.ndarray:
    """Normalised quadratic Bezier tangent: 2(1-t)(C-A) + 2t(B-C)."""
    u = 1.0 - t
    tan = 2.0 * u * (ctrl - posA) + 2.0 * t * (posB - ctrl)
    n = float(_np.linalg.norm(tan))
    return tan / n if n > 1e-9 else tan


def _arc_bow_dir(
    posA: _np.ndarray, posB: _np.ndarray,
    ax_a: _np.ndarray, ax_b: _np.ndarray,
) -> _np.ndarray:
    """
    Bow direction for a crossover arc: normalise(cross(chord, avg_axis)).

    Matches arcControlPoint() bow direction in crossover_connections.js.
    Points away from the Holliday junction — the direction the arc bows and
    the direction the base of each extra nucleotide faces outward.
    """
    chord = posB - posA
    dist  = float(_np.linalg.norm(chord))
    if dist < 1e-9:
        return _np.array([0.0, 0.0, 1.0])
    chord_hat = chord / dist
    avg_ax    = ax_a + ax_b
    avg_ax_n  = float(_np.linalg.norm(avg_ax))
    avg_ax    = avg_ax / avg_ax_n if avg_ax_n > 1e-9 else _np.array([0.0, 0.0, 1.0])
    bow       = _np.cross(chord_hat, avg_ax)
    bow_n     = float(_np.linalg.norm(bow))
    if bow_n < 1e-6:
        # Degenerate: chord parallel to axis — fall back to avg_ax
        return avg_ax
    return bow / bow_n


def _arc_ctrl_pt(
    posA: _np.ndarray, posB: _np.ndarray, bow_dir: _np.ndarray,
) -> _np.ndarray:
    """Quadratic Bezier control point bowing outward by BOW_FRAC_3D of chord length."""
    dist = float(_np.linalg.norm(posB - posA))
    mid  = (posA + posB) * 0.5
    return mid + bow_dir * (dist * _BOW_FRAC_3D)
