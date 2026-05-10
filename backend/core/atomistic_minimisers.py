"""
Backbone-bridge + extra-crossover-base minimisers extracted from atomistic.py.

Extracted in Pass 13-A as a self-contained leaf cluster.  All functions in this
module operate on flat lists of `Atom` dataclasses produced by atomistic.py,
mutating them in place via the `_atom_pos`/`_set_atom_pos`/`_translate_atom`
primitives.

Functions
─────────
Atom-mutation primitives (read/write/translate by serial):
  • _atom_pos
  • _set_atom_pos
  • _translate_atom

Rigid-body primitives (snapshot, transform, apply):
  • _rb_extract     — build (origin, names, local_mat) snapshot of a ribose ring
  • _rb_world       — translate + spin to world coordinates
  • _rb_apply       — write rigid-body world positions back into the atom list
  • _apply_phosphate — write P/O5'/OP1/OP2 with same delta as P

Bridge interpolators (place O3'(src), P(dst), O5'(dst) between two riboses):
  • _interpolate_backbone_bridge — linear lerp at 1/4, 2/4, 3/4
  • _minimize_backbone_bridge    — scipy L-BFGS-B against canonical bond
                                   lengths and angles (used for crossovers
                                   and skip-site bridges)

Joint extra-base minimisers (used by `_build_extra_base_atoms`):
  • _minimize_1_extra_base — 19 DOF (1 rigid body + 4 linker phosphate sets)
  • _minimize_2_extra_base — 29 DOF
  • _minimize_3_extra_base — 39 DOF

Cache (geometry-keyed; avoids re-running scipy when the atomistic view is
toggled off/on without design changes):
  • _XB_CACHE, _XB_CACHE_MAX, _XB_CACHE_LOCK

This module is a pure leaf — it imports only third-party libraries
(numpy, scipy) and the pure-math helpers from `atomistic_helpers.py`.  It
does NOT import from atomistic.py (avoiding the circular dependency); the
`Atom` dataclass is referenced only via string-form type hints (enabled by
`from __future__ import annotations`).

Locked constants (`_PHASE_*`, `_SUGAR`, `_FRAME_ROT_RAD`, `_ATOMISTIC_*`) are
NOT used by these functions; they remain in atomistic.py.
"""

from __future__ import annotations

import math as _math
import threading as _threading
from typing import TYPE_CHECKING

import numpy as _np
from scipy.optimize import minimize as _scipy_minimize

from backend.core.atomistic_helpers import (
    _CANON_C3O3,
    _CANON_C3O3P,
    _CANON_O3P,
    _CANON_O3PO5,
    _CANON_O5C5,
    _CANON_PO5,
    _CANON_PO5C5,
    _DEG2RAD,
    _PHOSPHATE_ATOMS,
    _W_GLYCOSIDIC,
    _W_REPULSION,
    _backbone_bridge_cost_grad,
    _bwd_bridge_x0,
    _fwd_bridge_x0,
    _glycosidic_cost_grad,
    _lerp,
    _make_spin_rotation,
    _rb_grad_propagate,
    _rb_pair_repulsion_grad,
    _repulsion_cost_grad,
    _spin_rotation_deriv,
)

if TYPE_CHECKING:
    from backend.core.atomistic import Atom


# ── Atom-list primitives ─────────────────────────────────────────────────────


def _atom_pos(atoms: list["Atom"], serial: int) -> _np.ndarray:
    a = atoms[serial]
    return _np.array([a.x, a.y, a.z])


def _set_atom_pos(atoms: list["Atom"], serial: int, pos: _np.ndarray) -> None:
    a = atoms[serial]
    a.x, a.y, a.z = float(pos[0]), float(pos[1]), float(pos[2])


def _translate_atom(atoms: list["Atom"], serial: int, delta: _np.ndarray) -> None:
    a = atoms[serial]
    a.x += float(delta[0])
    a.y += float(delta[1])
    a.z += float(delta[2])


# ── Backbone bridge interpolation (linear) ────────────────────────────────────


def _interpolate_backbone_bridge(
    atoms: list["Atom"],
    src_s: dict[str, int],
    dst_s: dict[str, int],
) -> None:
    """
    Linearly interpolate the phosphodiester linker atoms between C3′(src) and
    C5′(dst), leaving both ribose rings — and their canonical C4′ positions —
    completely undisturbed.

    C3′(src) is the ring carbon at the 3′ exit of the src ribose; C5′(dst) is
    the exocyclic carbon at the 5′ entry of the dst ribose.  Neither is moved.
    Only the three true linker atoms spanning the junction are repositioned:

      O3′(src) → t=1/4  (quarter-way from C3′(src) to C5′(dst))
      P(dst)   → t=2/4  (midpoint)
      O5′(dst) → t=3/4  (three-quarters)

    Branch atoms OP1(dst)/OP2(dst) are rigidly translated by the same delta
    as P(dst).
    """
    if "C3'" not in src_s or "C5'" not in dst_s or "P" not in dst_s:
        return
    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])

    orig_P    = _atom_pos(atoms, dst_s["P"])
    new_P_pos = _lerp(c3_src, c5_dst, 2.0 / 4.0)
    delta_P   = new_P_pos - orig_P

    for serials_dict, aname, t in (
        (src_s, "O3'", 1.0 / 4.0),
        (dst_s, "P",   2.0 / 4.0),
        (dst_s, "O5'", 3.0 / 4.0),
    ):
        s = serials_dict.get(aname)
        if s is not None:
            _set_atom_pos(atoms, s, _lerp(c3_src, c5_dst, t))

    for op in ("OP1", "OP2"):
        s = dst_s.get(op)
        if s is not None:
            _translate_atom(atoms, s, delta_P)


# ── Minimisation result cache (keyed by junction geometry) ───────────────────
# Avoids re-running scipy when the atomistic view is toggled off/on without
# design changes.  Keyed by (xo.id, extra_bases, rounded C3′(src), rounded C5′(dst),
# rounded target_c1n).  Stores the optimised x vector from the solver.
_XB_CACHE:      dict[tuple, "_np.ndarray"] = {}
_XB_CACHE_MAX:  int = 512   # entries before a full eviction (simple LRU-free strategy)
_XB_CACHE_LOCK: "_threading.Lock" = _threading.Lock()


# ── Minimisation-based backbone bridge ───────────────────────────────────────


def _minimize_backbone_bridge(
    atoms: list["Atom"],
    src_s: dict[str, int],
    dst_s: dict[str, int],
) -> None:
    """
    Place O3′(src), P(dst), O5′(dst) so that the C3′(src)→C5′(dst) bridge has
    bond lengths and angles close to canonical B-DNA values.

    Anchors (not moved): C3′(src), C5′(dst).
    Free atoms  (3 DOF each): O3′(src), P(dst), O5′(dst).
    OP1/OP2(dst) are rigidly translated by the same delta as P(dst).

    Objective: weighted sum of squared bond-length + bond-angle deviations.
    Bond lengths dominate (weight 1); angles are secondary (weight 0.1).
    Initial guess: 1/4, 2/4, 3/4 linear spacing (same as _interpolate_backbone_bridge).

    When the junction gap is larger than the canonical chain length (≈0.6 nm),
    the minimiser distributes the excess evenly while keeping angles as close to
    canonical as possible — strictly better than the collinear 180° interpolation.
    """
    if "C3'" not in src_s or "C5'" not in dst_s or "P" not in dst_s:
        return

    c3 = _atom_pos(atoms, src_s["C3'"])
    c5 = _atom_pos(atoms, dst_s["C5'"])

    cos_c3o3p = _math.cos(_CANON_C3O3P * _DEG2RAD)
    cos_o3po5 = _math.cos(_CANON_O3PO5 * _DEG2RAD)
    cos_po5c5 = _math.cos(_CANON_PO5C5 * _DEG2RAD)

    def _cos_angle(a: _np.ndarray, b: _np.ndarray, c: _np.ndarray) -> float:
        """Cosine of angle A–B–C."""
        ba = a - b; bc = c - b
        n1 = float(_np.linalg.norm(ba)); n2 = float(_np.linalg.norm(bc))
        if n1 < 1e-12 or n2 < 1e-12:
            return 1.0
        return float(_np.dot(ba, bc) / (n1 * n2))

    def objective(x: _np.ndarray) -> float:
        o3 = x[0:3]; p = x[3:6]; o5 = x[6:9]
        bl = (
            (_np.linalg.norm(o3 - c3) - _CANON_C3O3) ** 2 +
            (_np.linalg.norm(p  - o3) - _CANON_O3P)  ** 2 +
            (_np.linalg.norm(o5 - p)  - _CANON_PO5)  ** 2 +
            (_np.linalg.norm(c5 - o5) - _CANON_O5C5) ** 2
        )
        ba = (
            (_cos_angle(c3, o3, p)  - cos_c3o3p) ** 2 +
            (_cos_angle(o3, p,  o5) - cos_o3po5) ** 2 +
            (_cos_angle(p,  o5, c5) - cos_po5c5) ** 2
        )
        return float(bl + 0.1 * ba)

    x0 = _np.concatenate([
        _lerp(c3, c5, 1.0 / 4.0),
        _lerp(c3, c5, 2.0 / 4.0),
        _lerp(c3, c5, 3.0 / 4.0),
    ])

    res = _scipy_minimize(
        objective, x0, method="L-BFGS-B",
        options={"ftol": 1e-14, "gtol": 1e-9, "maxiter": 200},
    )
    o3_new = res.x[0:3]; p_new = res.x[3:6]; o5_new = res.x[6:9]

    orig_P  = _atom_pos(atoms, dst_s["P"])
    delta_P = p_new - orig_P

    s = src_s.get("O3'")
    if s is not None:
        _set_atom_pos(atoms, s, o3_new)
    for aname, pos in (("P", p_new), ("O5'", o5_new)):
        s = dst_s.get(aname)
        if s is not None:
            _set_atom_pos(atoms, s, pos)
    for op in ("OP1", "OP2"):
        s = dst_s.get(op)
        if s is not None:
            _translate_atom(atoms, s, delta_P)


# ── Rigid-body primitives ────────────────────────────────────────────────────


def _rb_extract(
    atoms:  list["Atom"],
    s_dict: dict[str, int],
) -> "tuple[_np.ndarray, tuple[str, ...], _np.ndarray]":
    """
    Snapshot rigid-body atom positions in C2′-centred coordinates.

    Phosphate atoms (P, OP1, OP2, O5′) are excluded — they are free linkers.
    O3′ IS retained so ring-exit geometry is preserved under rigid-body motion.

    Returns (c2_world, names_tuple, local_mat) where local_mat is (N, 3) — a
    row-matrix of local coordinate vectors.  This form lets _rb_world do the
    full transform as a single (N, 3) @ (3, 3) matrix multiply instead of a
    Python loop over N atoms.
    """
    c2_w  = _atom_pos(atoms, s_dict["C2'"])
    names = tuple(name for name in s_dict if name not in _PHOSPHATE_ATOMS)
    mat   = _np.array([_atom_pos(atoms, s_dict[name]) - c2_w for name in names])
    return c2_w, names, mat


def _rb_world(
    c2_orig: _np.ndarray,
    names:   "tuple[str, ...]",
    mat:     _np.ndarray,
    delta:   _np.ndarray,
    R:       _np.ndarray,
) -> dict[str, _np.ndarray]:
    """World positions of rigid-body atoms after C2′ translation + spin rotation.

    Uses a single (N, 3) @ (3, 3) matrix multiply for all N atoms.
    """
    c2_new = c2_orig + delta
    world  = c2_new + mat @ R.T      # (N, 3); broadcasting c2_new over rows
    return dict(zip(names, world))


def _rb_apply(
    atoms:  list["Atom"],
    s_dict: dict[str, int],
    rb_pos: dict[str, _np.ndarray],
) -> None:
    """Write optimised rigid-body world positions back into the atoms list."""
    for name, s in s_dict.items():
        if name not in _PHOSPHATE_ATOMS and name in rb_pos:
            _set_atom_pos(atoms, s, rb_pos[name])


def _apply_phosphate(
    atoms:  list["Atom"],
    s_dict: dict[str, int],
    p_new:  _np.ndarray,
    o5_new: _np.ndarray,
) -> None:
    """
    Set P and O5′ to optimised positions; rigidly translate OP1/OP2 with P.
    Reads the current P position *before* overwriting it.
    """
    orig_p = _atom_pos(atoms, s_dict["P"]) if "P" in s_dict else None
    if "P"   in s_dict: _set_atom_pos(atoms, s_dict["P"],   p_new)
    if "O5'" in s_dict: _set_atom_pos(atoms, s_dict["O5'"], o5_new)
    if orig_p is not None:
        delta_p = p_new - orig_p
        for op in ("OP1", "OP2"):
            s = s_dict.get(op)
            if s is not None:
                _translate_atom(atoms, s, delta_p)


# ── Joint placement minimisers for 1–3 extra crossover bases ─────────────────
#
# Each function jointly optimises:
#   • The placement (C2′ translation + spin about target_c1n) of every extra
#     nucleotide rigid body  — preserving the C1′→N direction established by
#     the glycosidic alignment step.
#   • All free backbone linker atoms (O3′(src), and P/O5′ of each incoming
#     phosphate group) that stitch the chain together.
#
# This is strictly better than the sequential per-pair _minimize_backbone_bridge
# approach because it couples the nucleotide placement with both flanking bridges
# simultaneously, allowing the optimizer to slide each ring to the position that
# minimises total backbone strain rather than freezing it at the lerp point.


def _minimize_1_extra_base(
    atoms:      list["Atom"],
    src_s:      dict[str, int],
    dst_s:      dict[str, int],
    eb1_s:      dict[str, int],
    eb1_n:      str,
    target_c1n: _np.ndarray,
    repel_pos:  list[_np.ndarray],
    cache_key:  "tuple | None" = None,
) -> None:
    """
    Joint backbone placement for 1 extra crossover base (19 DOF).

    Variables
    ─────────
      x[0:3]   delta_eb1  – C2′ translation of eb1 rigid body
      x[3]     theta_eb1  – spin of eb1 about target_c1n
      x[4:7]   O3′(src)
      x[7:10]  P(eb1)   x[10:13] O5′(eb1)
      x[13:16] P(dst)   x[16:19] O5′(dst)

    Objective: backbone bridges + C1′→N alignment + steric repulsion
    """
    if "C3'" not in src_s or "O3'" not in src_s:
        return
    if not all(k in dst_s for k in ("C5'", "P", "O5'")):
        return
    if not all(k in eb1_s for k in ("C2'", "C3'", "C5'", "O3'")):
        return

    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])
    c2_eb1, eb1_names, eb1_mat = _rb_extract(atoms, eb1_s)

    def _eb1(x: _np.ndarray, R: _np.ndarray) -> dict[str, _np.ndarray]:
        return _rb_world(c2_eb1, eb1_names, eb1_mat, x[0:3], R)

    def objective_and_grad(x: _np.ndarray) -> "tuple[float, _np.ndarray]":
        R   = _make_spin_rotation(target_c1n, float(x[3]))
        dRt = _spin_rotation_deriv(target_c1n, float(x[3]))
        w   = _eb1(x, R)

        c1, g_c3s, g_o3s, g_peb1, g_o5eb1, g_c5w = _backbone_bridge_cost_grad(
            c3_src, x[4:7], x[7:10], x[10:13], w["C5'"])
        c2, g_c3w, g_o3w, g_pdst, g_o5dst, _gc5d = _backbone_bridge_cost_grad(
            w["C3'"], w["O3'"], x[13:16], x[16:19], c5_dst)
        c3v, g_c1v, g_nv = _glycosidic_cost_grad(w["C1'"], w[eb1_n], target_c1n)
        c4, g_rep       = _repulsion_cost_grad(w, repel_pos)

        total = c1 + c2 + _W_GLYCOSIDIC * c3v + _W_REPULSION * c4

        # Accumulate gradients flowing back to the rigid-body world positions
        g_w: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb1_names}
        def _acc(name: str, g: _np.ndarray) -> None:
            if name in g_w:
                g_w[name] += g
        _acc("C5'", g_c5w)
        _acc("C3'", g_c3w)
        _acc("O3'", g_o3w)
        _acc("C1'", _W_GLYCOSIDIC * g_c1v)
        _acc(eb1_n,  _W_GLYCOSIDIC * g_nv)
        for aname, gv in g_rep.items():
            _acc(aname, _W_REPULSION * gv)

        g_delta, g_theta = _rb_grad_propagate(g_w, eb1_names, eb1_mat, dRt)

        grad = _np.empty_like(x)
        grad[0:3]   = g_delta
        grad[3]     = g_theta
        grad[4:7]   = g_o3s
        grad[7:10]  = g_peb1
        grad[10:13] = g_o5eb1
        grad[13:16] = g_pdst
        grad[16:19] = g_o5dst
        return total, grad

    def _apply1(x: _np.ndarray) -> None:
        R = _make_spin_rotation(target_c1n, float(x[3]))
        _rb_apply(atoms, eb1_s, _eb1(x, R))
        _set_atom_pos(atoms, src_s["O3'"], x[4:7])
        _apply_phosphate(atoms, eb1_s, x[7:10],  x[10:13])
        _apply_phosphate(atoms, dst_s, x[13:16], x[16:19])

    if cache_key is not None and cache_key in _XB_CACHE:
        _apply1(_XB_CACHE[cache_key])
        return

    # Better initial guess: place linker atoms proportionally along canonical
    # bond-length fractions of each bridge chord (reduces initial bond stretching
    # from ~6× canonical to ~2×, cutting scipy iterations by ~5×).
    c5_eb1 = _atom_pos(atoms, eb1_s["C5'"])   # rigid body at delta=0
    o3_eb1 = _atom_pos(atoms, eb1_s["O3'"])   # rigid body at delta=0
    o3_src_x0, p_eb1_x0, o5_eb1_x0 = _fwd_bridge_x0(c3_src, c5_eb1)
    p_dst_x0, o5_dst_x0             = _bwd_bridge_x0(o3_eb1, c5_dst)
    x0 = _np.concatenate([
        _np.zeros(3), [0.0],
        o3_src_x0, p_eb1_x0, o5_eb1_x0,
        p_dst_x0, o5_dst_x0,
    ])
    res = _scipy_minimize(objective_and_grad, x0, method="L-BFGS-B", jac=True,
                          options={"ftol": 1e-8, "gtol": 1e-6, "maxiter": 200})
    x = res.x
    if cache_key is not None:
        with _XB_CACHE_LOCK:
            if len(_XB_CACHE) >= _XB_CACHE_MAX:
                _XB_CACHE.pop(next(iter(_XB_CACHE)))
            _XB_CACHE[cache_key] = x
    _apply1(x)


def _minimize_2_extra_base(
    atoms:      list["Atom"],
    src_s:      dict[str, int],
    dst_s:      dict[str, int],
    eb1_s:      dict[str, int],
    eb2_s:      dict[str, int],
    eb1_n:      str,
    eb2_n:      str,
    target_c1n: _np.ndarray,
    repel_pos:  list[_np.ndarray],
    cache_key:  "tuple | None" = None,
) -> None:
    """
    Joint backbone placement for 2 extra crossover bases (29 DOF).

    Variables
    ─────────
      x[0:4]   rb eb1  (delta[3], theta[1])
      x[4:8]   rb eb2  (delta[3], theta[1])
      x[8:11]  O3′(src)
      x[11:14] P(eb1)  x[14:17] O5′(eb1)
      x[17:20] P(eb2)  x[20:23] O5′(eb2)
      x[23:26] P(dst)  x[26:29] O5′(dst)

    Objective: backbone bridges + C1′→N alignment + steric repulsion (inter-strand
               and inter-extra-base)
    """
    if "C3'" not in src_s or "O3'" not in src_s:
        return
    if not all(k in dst_s for k in ("C5'", "P", "O5'")):
        return
    for eb in (eb1_s, eb2_s):
        if not all(k in eb for k in ("C2'", "C3'", "C5'", "O3'")):
            return

    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])
    c2_eb1, eb1_names, eb1_mat = _rb_extract(atoms, eb1_s)
    c2_eb2, eb2_names, eb2_mat = _rb_extract(atoms, eb2_s)

    def _eb(x: _np.ndarray, off: int, c2_0: _np.ndarray,
            names: tuple, mat: _np.ndarray,
            R: _np.ndarray) -> dict[str, _np.ndarray]:
        return _rb_world(c2_0, names, mat, x[off:off+3], R)

    def objective_and_grad(x: _np.ndarray) -> "tuple[float, _np.ndarray]":
        R1   = _make_spin_rotation(target_c1n, float(x[3]))
        dRt1 = _spin_rotation_deriv(target_c1n, float(x[3]))
        R2   = _make_spin_rotation(target_c1n, float(x[7]))
        dRt2 = _spin_rotation_deriv(target_c1n, float(x[7]))
        w1 = _eb(x, 0, c2_eb1, eb1_names, eb1_mat, R1)
        w2 = _eb(x, 4, c2_eb2, eb2_names, eb2_mat, R2)

        c1, _, g_o3s, g_peb1, g_o5eb1, g_c5w1 = _backbone_bridge_cost_grad(
            c3_src, x[8:11], x[11:14], x[14:17], w1["C5'"])
        c2, g_c3w1, g_o3w1, g_peb2, g_o5eb2, g_c5w2 = _backbone_bridge_cost_grad(
            w1["C3'"], w1["O3'"], x[17:20], x[20:23], w2["C5'"])
        c3v, g_c3w2, g_o3w2, g_pdst, g_o5dst, _ = _backbone_bridge_cost_grad(
            w2["C3'"], w2["O3'"], x[23:26], x[26:29], c5_dst)
        c4a, g_c1a, g_na = _glycosidic_cost_grad(w1["C1'"], w1[eb1_n], target_c1n)
        c4b, g_c1b, g_nb = _glycosidic_cost_grad(w2["C1'"], w2[eb2_n], target_c1n)
        c5a, g_r1   = _repulsion_cost_grad(w1, repel_pos)
        c5b, g_r2   = _repulsion_cost_grad(w2, repel_pos)
        c6,  g_p1, g_p2 = _rb_pair_repulsion_grad(w1, w2)

        total = (c1 + c2 + c3v
                 + _W_GLYCOSIDIC * (c4a + c4b)
                 + _W_REPULSION  * (c5a + c5b + c6))

        gw1: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb1_names}
        gw2: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb2_names}

        def _acc1(n: str, g: _np.ndarray) -> None:
            if n in gw1: gw1[n] += g
        def _acc2(n: str, g: _np.ndarray) -> None:
            if n in gw2: gw2[n] += g

        _acc1("C5'", g_c5w1); _acc1("C3'", g_c3w1); _acc1("O3'", g_o3w1)
        _acc1("C1'", _W_GLYCOSIDIC * g_c1a); _acc1(eb1_n, _W_GLYCOSIDIC * g_na)
        for a, g in g_r1.items(): _acc1(a, _W_REPULSION * g)
        for a, g in g_p1.items(): _acc1(a, _W_REPULSION * g)

        _acc2("C5'", g_c5w2); _acc2("C3'", g_c3w2); _acc2("O3'", g_o3w2)
        _acc2("C1'", _W_GLYCOSIDIC * g_c1b); _acc2(eb2_n, _W_GLYCOSIDIC * g_nb)
        for a, g in g_r2.items(): _acc2(a, _W_REPULSION * g)
        for a, g in g_p2.items(): _acc2(a, _W_REPULSION * g)

        gd1, gt1 = _rb_grad_propagate(gw1, eb1_names, eb1_mat, dRt1)
        gd2, gt2 = _rb_grad_propagate(gw2, eb2_names, eb2_mat, dRt2)

        grad = _np.empty_like(x)
        grad[0:3] = gd1;   grad[3]     = gt1
        grad[4:7] = gd2;   grad[7]     = gt2
        grad[8:11]  = g_o3s
        grad[11:14] = g_peb1;  grad[14:17] = g_o5eb1
        grad[17:20] = g_peb2;  grad[20:23] = g_o5eb2
        grad[23:26] = g_pdst;  grad[26:29] = g_o5dst
        return total, grad

    def _apply2(x: _np.ndarray) -> None:
        R1 = _make_spin_rotation(target_c1n, float(x[3]))
        R2 = _make_spin_rotation(target_c1n, float(x[7]))
        _rb_apply(atoms, eb1_s, _eb(x, 0, c2_eb1, eb1_names, eb1_mat, R1))
        _rb_apply(atoms, eb2_s, _eb(x, 4, c2_eb2, eb2_names, eb2_mat, R2))
        _set_atom_pos(atoms, src_s["O3'"], x[8:11])
        _apply_phosphate(atoms, eb1_s, x[11:14], x[14:17])
        _apply_phosphate(atoms, eb2_s, x[17:20], x[20:23])
        _apply_phosphate(atoms, dst_s, x[23:26], x[26:29])

    if cache_key is not None and cache_key in _XB_CACHE:
        _apply2(_XB_CACHE[cache_key])
        return

    c5_eb1 = _atom_pos(atoms, eb1_s["C5'"])   # rigid body at delta=0
    o3_eb1 = _atom_pos(atoms, eb1_s["O3'"])   # rigid body at delta=0
    c5_eb2 = _atom_pos(atoms, eb2_s["C5'"])   # rigid body at delta=0
    o3_eb2 = _atom_pos(atoms, eb2_s["O3'"])   # rigid body at delta=0
    o3_src_x0, p_eb1_x0, o5_eb1_x0 = _fwd_bridge_x0(c3_src, c5_eb1)
    p_eb2_x0, o5_eb2_x0             = _bwd_bridge_x0(o3_eb1, c5_eb2)
    p_dst_x0, o5_dst_x0             = _bwd_bridge_x0(o3_eb2, c5_dst)
    x0 = _np.concatenate([
        _np.zeros(3), [0.0],
        _np.zeros(3), [0.0],
        o3_src_x0,
        p_eb1_x0, o5_eb1_x0,
        p_eb2_x0, o5_eb2_x0,
        p_dst_x0, o5_dst_x0,
    ])
    res = _scipy_minimize(objective_and_grad, x0, method="L-BFGS-B", jac=True,
                          options={"ftol": 1e-8, "gtol": 1e-6, "maxiter": 200})
    x = res.x
    if cache_key is not None:
        with _XB_CACHE_LOCK:
            if len(_XB_CACHE) >= _XB_CACHE_MAX:
                _XB_CACHE.pop(next(iter(_XB_CACHE)))
            _XB_CACHE[cache_key] = x
    _apply2(x)


def _minimize_3_extra_base(
    atoms:      list["Atom"],
    src_s:      dict[str, int],
    dst_s:      dict[str, int],
    eb1_s:      dict[str, int],
    eb2_s:      dict[str, int],
    eb3_s:      dict[str, int],
    eb1_n:      str,
    eb2_n:      str,
    eb3_n:      str,
    target_c1n: _np.ndarray,
    repel_pos:  list[_np.ndarray],
    cache_key:  "tuple | None" = None,
) -> None:
    """
    Joint backbone placement for 3 extra crossover bases (39 DOF).

    Variables
    ─────────
      x[0:4]   rb eb1  x[4:8]   rb eb2  x[8:12]  rb eb3
      x[12:15] O3′(src)
      x[15:18] P(eb1)  x[18:21] O5′(eb1)
      x[21:24] P(eb2)  x[24:27] O5′(eb2)
      x[27:30] P(eb3)  x[30:33] O5′(eb3)
      x[33:36] P(dst)  x[36:39] O5′(dst)

    Objective: backbone bridges + C1′→N alignment + steric repulsion (inter-strand
               and all inter-extra-base pairs)
    """
    if "C3'" not in src_s or "O3'" not in src_s:
        return
    if not all(k in dst_s for k in ("C5'", "P", "O5'")):
        return
    for eb in (eb1_s, eb2_s, eb3_s):
        if not all(k in eb for k in ("C2'", "C3'", "C5'", "O3'")):
            return

    c3_src = _atom_pos(atoms, src_s["C3'"])
    c5_dst = _atom_pos(atoms, dst_s["C5'"])
    c2_eb1, eb1_names, eb1_mat = _rb_extract(atoms, eb1_s)
    c2_eb2, eb2_names, eb2_mat = _rb_extract(atoms, eb2_s)
    c2_eb3, eb3_names, eb3_mat = _rb_extract(atoms, eb3_s)

    def _eb(x: _np.ndarray, off: int, c2_0: _np.ndarray,
            names: tuple, mat: _np.ndarray,
            R: _np.ndarray) -> dict[str, _np.ndarray]:
        return _rb_world(c2_0, names, mat, x[off:off+3], R)

    def objective_and_grad(x: _np.ndarray) -> "tuple[float, _np.ndarray]":
        R1   = _make_spin_rotation(target_c1n, float(x[3]))
        dRt1 = _spin_rotation_deriv(target_c1n, float(x[3]))
        R2   = _make_spin_rotation(target_c1n, float(x[7]))
        dRt2 = _spin_rotation_deriv(target_c1n, float(x[7]))
        R3   = _make_spin_rotation(target_c1n, float(x[11]))
        dRt3 = _spin_rotation_deriv(target_c1n, float(x[11]))
        w1 = _eb(x,  0, c2_eb1, eb1_names, eb1_mat, R1)
        w2 = _eb(x,  4, c2_eb2, eb2_names, eb2_mat, R2)
        w3 = _eb(x,  8, c2_eb3, eb3_names, eb3_mat, R3)

        c1, _, g_o3s, g_peb1, g_o5eb1, g_c5w1 = _backbone_bridge_cost_grad(
            c3_src,     x[12:15], x[15:18], x[18:21], w1["C5'"])
        c2, g_c3w1, g_o3w1, g_peb2, g_o5eb2, g_c5w2 = _backbone_bridge_cost_grad(
            w1["C3'"], w1["O3'"], x[21:24], x[24:27], w2["C5'"])
        c3v, g_c3w2, g_o3w2, g_peb3, g_o5eb3, g_c5w3 = _backbone_bridge_cost_grad(
            w2["C3'"], w2["O3'"], x[27:30], x[30:33], w3["C5'"])
        c4, g_c3w3, g_o3w3, g_pdst, g_o5dst, _ = _backbone_bridge_cost_grad(
            w3["C3'"], w3["O3'"], x[33:36], x[36:39], c5_dst)

        c5a, g_c1a, g_na = _glycosidic_cost_grad(w1["C1'"], w1[eb1_n], target_c1n)
        c5b, g_c1b, g_nb = _glycosidic_cost_grad(w2["C1'"], w2[eb2_n], target_c1n)
        c5c, g_c1c, g_nc = _glycosidic_cost_grad(w3["C1'"], w3[eb3_n], target_c1n)
        c6a, g_r1 = _repulsion_cost_grad(w1, repel_pos)
        c6b, g_r2 = _repulsion_cost_grad(w2, repel_pos)
        c6c, g_r3 = _repulsion_cost_grad(w3, repel_pos)
        c7ab, g_p1ab, g_p2ab = _rb_pair_repulsion_grad(w1, w2)
        c7ac, g_p1ac, g_p3ac = _rb_pair_repulsion_grad(w1, w3)
        c7bc, g_p2bc, g_p3bc = _rb_pair_repulsion_grad(w2, w3)

        total = (c1 + c2 + c3v + c4
                 + _W_GLYCOSIDIC * (c5a + c5b + c5c)
                 + _W_REPULSION  * (c6a + c6b + c6c + c7ab + c7ac + c7bc))

        gw1: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb1_names}
        gw2: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb2_names}
        gw3: dict[str, _np.ndarray] = {n: _np.zeros(3) for n in eb3_names}

        def _a1(n: str, g: _np.ndarray) -> None:
            if n in gw1: gw1[n] += g
        def _a2(n: str, g: _np.ndarray) -> None:
            if n in gw2: gw2[n] += g
        def _a3(n: str, g: _np.ndarray) -> None:
            if n in gw3: gw3[n] += g

        _a1("C5'", g_c5w1); _a1("C3'", g_c3w1); _a1("O3'", g_o3w1)
        _a1("C1'", _W_GLYCOSIDIC * g_c1a); _a1(eb1_n, _W_GLYCOSIDIC * g_na)
        for a, g in g_r1.items():   _a1(a, _W_REPULSION * g)
        for a, g in g_p1ab.items(): _a1(a, _W_REPULSION * g)
        for a, g in g_p1ac.items(): _a1(a, _W_REPULSION * g)

        _a2("C5'", g_c5w2); _a2("C3'", g_c3w2); _a2("O3'", g_o3w2)
        _a2("C1'", _W_GLYCOSIDIC * g_c1b); _a2(eb2_n, _W_GLYCOSIDIC * g_nb)
        for a, g in g_r2.items():   _a2(a, _W_REPULSION * g)
        for a, g in g_p2ab.items(): _a2(a, _W_REPULSION * g)
        for a, g in g_p2bc.items(): _a2(a, _W_REPULSION * g)

        _a3("C5'", g_c5w3); _a3("C3'", g_c3w3); _a3("O3'", g_o3w3)
        _a3("C1'", _W_GLYCOSIDIC * g_c1c); _a3(eb3_n, _W_GLYCOSIDIC * g_nc)
        for a, g in g_r3.items():   _a3(a, _W_REPULSION * g)
        for a, g in g_p3ac.items(): _a3(a, _W_REPULSION * g)
        for a, g in g_p3bc.items(): _a3(a, _W_REPULSION * g)

        gd1, gt1 = _rb_grad_propagate(gw1, eb1_names, eb1_mat, dRt1)
        gd2, gt2 = _rb_grad_propagate(gw2, eb2_names, eb2_mat, dRt2)
        gd3, gt3 = _rb_grad_propagate(gw3, eb3_names, eb3_mat, dRt3)

        grad = _np.empty_like(x)
        grad[0:3]  = gd1;  grad[3]  = gt1
        grad[4:7]  = gd2;  grad[7]  = gt2
        grad[8:11] = gd3;  grad[11] = gt3
        grad[12:15] = g_o3s
        grad[15:18] = g_peb1;  grad[18:21] = g_o5eb1
        grad[21:24] = g_peb2;  grad[24:27] = g_o5eb2
        grad[27:30] = g_peb3;  grad[30:33] = g_o5eb3
        grad[33:36] = g_pdst;  grad[36:39] = g_o5dst
        return total, grad

    def _apply3(x: _np.ndarray) -> None:
        R1 = _make_spin_rotation(target_c1n, float(x[3]))
        R2 = _make_spin_rotation(target_c1n, float(x[7]))
        R3 = _make_spin_rotation(target_c1n, float(x[11]))
        _rb_apply(atoms, eb1_s, _eb(x,  0, c2_eb1, eb1_names, eb1_mat, R1))
        _rb_apply(atoms, eb2_s, _eb(x,  4, c2_eb2, eb2_names, eb2_mat, R2))
        _rb_apply(atoms, eb3_s, _eb(x,  8, c2_eb3, eb3_names, eb3_mat, R3))
        _set_atom_pos(atoms, src_s["O3'"], x[12:15])
        _apply_phosphate(atoms, eb1_s, x[15:18], x[18:21])
        _apply_phosphate(atoms, eb2_s, x[21:24], x[24:27])
        _apply_phosphate(atoms, eb3_s, x[27:30], x[30:33])
        _apply_phosphate(atoms, dst_s, x[33:36], x[36:39])

    if cache_key is not None and cache_key in _XB_CACHE:
        _apply3(_XB_CACHE[cache_key])
        return

    c5_eb1 = _atom_pos(atoms, eb1_s["C5'"])   # rigid body at delta=0
    o3_eb1 = _atom_pos(atoms, eb1_s["O3'"])   # rigid body at delta=0
    c5_eb2 = _atom_pos(atoms, eb2_s["C5'"])   # rigid body at delta=0
    o3_eb2 = _atom_pos(atoms, eb2_s["O3'"])   # rigid body at delta=0
    c5_eb3 = _atom_pos(atoms, eb3_s["C5'"])   # rigid body at delta=0
    o3_eb3 = _atom_pos(atoms, eb3_s["O3'"])   # rigid body at delta=0
    o3_src_x0, p_eb1_x0, o5_eb1_x0 = _fwd_bridge_x0(c3_src, c5_eb1)
    p_eb2_x0, o5_eb2_x0             = _bwd_bridge_x0(o3_eb1, c5_eb2)
    p_eb3_x0, o5_eb3_x0             = _bwd_bridge_x0(o3_eb2, c5_eb3)
    p_dst_x0, o5_dst_x0             = _bwd_bridge_x0(o3_eb3, c5_dst)
    x0 = _np.concatenate([
        _np.zeros(3), [0.0],
        _np.zeros(3), [0.0],
        _np.zeros(3), [0.0],
        o3_src_x0,
        p_eb1_x0, o5_eb1_x0,
        p_eb2_x0, o5_eb2_x0,
        p_eb3_x0, o5_eb3_x0,
        p_dst_x0, o5_dst_x0,
    ])
    res = _scipy_minimize(objective_and_grad, x0, method="L-BFGS-B", jac=True,
                          options={"ftol": 1e-8, "gtol": 1e-6, "maxiter": 200})
    x = res.x
    if cache_key is not None:
        with _XB_CACHE_LOCK:
            if len(_XB_CACHE) >= _XB_CACHE_MAX:
                _XB_CACHE.pop(next(iter(_XB_CACHE)))
            _XB_CACHE[cache_key] = x
    _apply3(x)
