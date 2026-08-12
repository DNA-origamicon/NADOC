"""
Backbone-bridge minimisers extracted from atomistic.py.

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

Bridge interpolators (place O3'(src), P(dst), O5'(dst) between two riboses):
  • _interpolate_backbone_bridge — chord interpolation at 1/4, 2/4, 3/4,
                                   with an optional tapered Holliday bow
  • _minimize_backbone_bridge    — scipy L-BFGS-B against canonical bond
                                   lengths and angles (used for crossovers
                                   and skip-site bridges)

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
    _lerp,
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


# ── Backbone bridge interpolation ─────────────────────────────────────────────


def _backbone_bridge_points(
    c3_src: _np.ndarray,
    c5_dst: _np.ndarray,
    bow: _np.ndarray | None = None,
) -> tuple[_np.ndarray, _np.ndarray, _np.ndarray]:
    """Return O3′/P/O5′ positions along a straight or gently bowed bridge.

    ``bow`` is the displacement at the phosphate midpoint. A sine envelope makes the
    displacement taper to zero at the fixed C3′/C5′ anchors while preserving the old
    quarter/half/three-quarter construction when no bow is supplied.
    """
    offset = _np.zeros(3) if bow is None else _np.asarray(bow, dtype=float)
    return tuple(
        _lerp(c3_src, c5_dst, t) + offset * _math.sin(_math.pi * t)
        for t in (0.25, 0.5, 0.75)
    )


def _interpolate_backbone_bridge(
    atoms: list["Atom"],
    src_s: dict[str, int],
    dst_s: dict[str, int],
    bow: _np.ndarray | None = None,
) -> None:
    """
    Interpolate the phosphodiester linker atoms between C3′(src) and C5′(dst),
    leaving both ribose rings — and their canonical C4′ positions — completely
    undisturbed. ``bow=None`` is the historical straight interpolation; a bow is
    used only for paired scaffold crossovers that would otherwise contact.

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

    o3_pos, new_P_pos, o5_pos = _backbone_bridge_points(c3_src, c5_dst, bow)
    orig_P = _atom_pos(atoms, dst_s["P"])
    delta_P = new_P_pos - orig_P

    for serials_dict, aname, pos in (
        (src_s, "O3'", o3_pos),
        (dst_s, "P", new_P_pos),
        (dst_s, "O5'", o5_pos),
    ):
        s = serials_dict.get(aname)
        if s is not None:
            _set_atom_pos(atoms, s, pos)

    for op in ("OP1", "OP2"):
        s = dst_s.get(op)
        if s is not None:
            _translate_atom(atoms, s, delta_P)


# ── Minimisation result cache (keyed by junction geometry) ───────────────────
# Avoids re-running scipy when the atomistic view is toggled off/on without
# design changes.  Keyed by (xo.id, extra_bases, rounded C3′(src), rounded C5′(dst),
# rounded target_c1n).  Stores the optimised x vector from the solver.


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
        ba = a - b
        bc = c - b
        n1 = float(_np.linalg.norm(ba))
        n2 = float(_np.linalg.norm(bc))
        if n1 < 1e-12 or n2 < 1e-12:
            return 1.0
        return float(_np.dot(ba, bc) / (n1 * n2))

    def objective(x: _np.ndarray) -> float:
        o3 = x[0:3]
        p = x[3:6]
        o5 = x[6:9]
        bl = (
            (_np.linalg.norm(o3 - c3) - _CANON_C3O3) ** 2
            + (_np.linalg.norm(p - o3) - _CANON_O3P) ** 2
            + (_np.linalg.norm(o5 - p) - _CANON_PO5) ** 2
            + (_np.linalg.norm(c5 - o5) - _CANON_O5C5) ** 2
        )
        ba = (
            (_cos_angle(c3, o3, p) - cos_c3o3p) ** 2
            + (_cos_angle(o3, p, o5) - cos_o3po5) ** 2
            + (_cos_angle(p, o5, c5) - cos_po5c5) ** 2
        )
        return float(bl + 0.1 * ba)

    x0 = _np.concatenate(
        [
            _lerp(c3, c5, 1.0 / 4.0),
            _lerp(c3, c5, 2.0 / 4.0),
            _lerp(c3, c5, 3.0 / 4.0),
        ]
    )

    res = _scipy_minimize(
        objective,
        x0,
        method="L-BFGS-B",
        options={"ftol": 1e-14, "gtol": 1e-9, "maxiter": 200},
    )
    o3_new = res.x[0:3]
    p_new = res.x[3:6]
    o5_new = res.x[6:9]

    orig_P = _atom_pos(atoms, dst_s["P"])
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
