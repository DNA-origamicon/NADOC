"""
Unit tests for backend/core/atomistic_minimisers.py (Pass 13-A leaf extract).

Coverage target: ≥90% per precondition #21.

The module exposes three categories of helpers, each with a focused test class:

  1. Atom-mutation primitives (_atom_pos / _set_atom_pos / _translate_atom)
  2. Rigid-body primitives (_rb_extract / _rb_world / _rb_apply / _apply_phosphate)
  3. Bridge / extra-base minimisers (_interpolate_backbone_bridge,
     _minimize_backbone_bridge, _minimize_{1,2,3}_extra_base)

The minimiser tests build small synthetic ribose-ring serial dicts so we can
verify scipy-driven placement yields canonical bond lengths/angles within
tolerance.  No real Design / Atom topology is required — we use lightweight
"AtomLike" objects with x/y/z attributes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from backend.core.atomistic_helpers import (
    _CANON_C3O3,
    _CANON_O3P,
    _CANON_O5C5,
    _CANON_PO5,
)
from backend.core.atomistic_minimisers import (
    _atom_pos,
    _interpolate_backbone_bridge,
    _minimize_backbone_bridge,
    _set_atom_pos,
    _translate_atom,
)


# ── Test fixtures ─────────────────────────────────────────────────────────────


@dataclass
class AtomLike:
    """Lightweight x/y/z holder — enough for the minimisers' attribute access."""

    x: float
    y: float
    z: float


def _make_atoms(positions: list[tuple[float, float, float]]) -> list[AtomLike]:
    return [AtomLike(x, y, z) for x, y, z in positions]


def _build_ribose(
    origin: np.ndarray, scale: float = 0.15
) -> tuple[list[AtomLike], dict[str, int]]:
    """
    Build a minimal sugar-phosphate ribose ring around `origin` with the
    serial-name pattern expected by the minimisers.  Atom positions are
    placed approximately at canonical B-DNA distances.
    """
    # Synthetic but plausible ribose layout.  Origin = C2'.
    layout = {
        "C2'": origin + np.array([0.00, 0.00, 0.00]),
        "C1'": origin + np.array([0.15, 0.00, 0.00]),
        "C3'": origin + np.array([-0.10, 0.10, 0.00]),
        "O3'": origin + np.array([-0.20, 0.20, 0.00]),
        "C4'": origin + np.array([0.05, 0.15, 0.00]),
        "O4'": origin + np.array([0.18, 0.10, 0.00]),
        "C5'": origin + np.array([0.10, 0.30, 0.00]),
        "O5'": origin + np.array([0.20, 0.40, 0.00]),
        "P": origin + np.array([0.30, 0.55, 0.00]),
        "OP1": origin + np.array([0.35, 0.60, 0.10]),
        "OP2": origin + np.array([0.25, 0.60, -0.10]),
        "N1": origin + np.array([0.30, -0.05, 0.00]),  # base attachment for DT/DC
    }
    atoms_list = []
    serials: dict[str, int] = {}
    for name, pos in layout.items():
        serials[name] = len(atoms_list)
        atoms_list.append(AtomLike(float(pos[0]), float(pos[1]), float(pos[2])))
    return atoms_list, serials


# ── Atom-mutation primitives ──────────────────────────────────────────────────


class TestAtomPos:
    def test_returns_xyz_array(self):
        atoms = _make_atoms([(1.0, 2.0, 3.0)])
        out = _atom_pos(atoms, 0)
        assert isinstance(out, np.ndarray)
        np.testing.assert_array_equal(out, [1.0, 2.0, 3.0])

    def test_picks_correct_serial(self):
        atoms = _make_atoms([(0.0, 0.0, 0.0), (4.0, 5.0, 6.0)])
        np.testing.assert_array_equal(_atom_pos(atoms, 1), [4.0, 5.0, 6.0])


class TestSetAtomPos:
    def test_writes_xyz_in_place(self):
        atoms = _make_atoms([(0.0, 0.0, 0.0)])
        _set_atom_pos(atoms, 0, np.array([7.0, 8.0, 9.0]))
        assert atoms[0].x == 7.0
        assert atoms[0].y == 8.0
        assert atoms[0].z == 9.0

    def test_floats_coerced(self):
        atoms = _make_atoms([(0.0, 0.0, 0.0)])
        _set_atom_pos(atoms, 0, np.array([np.float32(1.5), np.float64(2.5), 3]))
        assert isinstance(atoms[0].x, float)


class TestTranslateAtom:
    def test_adds_delta(self):
        atoms = _make_atoms([(1.0, 2.0, 3.0)])
        _translate_atom(atoms, 0, np.array([0.5, -1.0, 2.0]))
        assert atoms[0].x == pytest.approx(1.5)
        assert atoms[0].y == pytest.approx(1.0)
        assert atoms[0].z == pytest.approx(5.0)

    def test_zero_delta_no_change(self):
        atoms = _make_atoms([(0.7, 0.8, 0.9)])
        _translate_atom(atoms, 0, np.zeros(3))
        np.testing.assert_array_equal(
            [atoms[0].x, atoms[0].y, atoms[0].z], [0.7, 0.8, 0.9]
        )


# ── Bridge interpolation (linear) ─────────────────────────────────────────────


class TestInterpolateBackboneBridge:
    def test_lerp_quarter_half_three_quarter(self):
        atoms, src = _build_ribose(np.zeros(3))
        atoms2, dst = _build_ribose(np.array([1.0, 0.0, 0.0]))
        # combine — make dst serials offset
        offset = len(atoms)
        atoms.extend(atoms2)
        dst = {k: v + offset for k, v in dst.items()}
        c3 = _atom_pos(atoms, src["C3'"])
        c5 = _atom_pos(atoms, dst["C5'"])
        _interpolate_backbone_bridge(atoms, src, dst)
        # O3'(src) should be at c3 + 0.25*(c5 - c3)
        np.testing.assert_allclose(
            _atom_pos(atoms, src["O3'"]), c3 + 0.25 * (c5 - c3), atol=1e-9
        )
        np.testing.assert_allclose(
            _atom_pos(atoms, dst["P"]), c3 + 0.50 * (c5 - c3), atol=1e-9
        )
        np.testing.assert_allclose(
            _atom_pos(atoms, dst["O5'"]), c3 + 0.75 * (c5 - c3), atol=1e-9
        )

    def test_op1_op2_translated_with_p(self):
        atoms, src = _build_ribose(np.zeros(3))
        atoms2, dst = _build_ribose(np.array([0.5, 0.0, 0.0]))
        offset = len(atoms)
        atoms.extend(atoms2)
        dst = {k: v + offset for k, v in dst.items()}

        op1_before = _atom_pos(atoms, dst["OP1"])
        op2_before = _atom_pos(atoms, dst["OP2"])
        p_before = _atom_pos(atoms, dst["P"])
        _interpolate_backbone_bridge(atoms, src, dst)
        p_after = _atom_pos(atoms, dst["P"])
        delta_p = p_after - p_before
        np.testing.assert_allclose(
            _atom_pos(atoms, dst["OP1"]), op1_before + delta_p, atol=1e-9
        )
        np.testing.assert_allclose(
            _atom_pos(atoms, dst["OP2"]), op2_before + delta_p, atol=1e-9
        )

    def test_optional_bow_tapers_to_fixed_anchors(self):
        atoms, src = _build_ribose(np.zeros(3))
        atoms2, dst = _build_ribose(np.array([1.0, 0.0, 0.0]))
        offset = len(atoms)
        atoms.extend(atoms2)
        dst = {key: value + offset for key, value in dst.items()}
        c3_before = _atom_pos(atoms, src["C3'"])
        c5_before = _atom_pos(atoms, dst["C5'"])
        bow = np.array([0.0, 0.06, 0.0])

        _interpolate_backbone_bridge(atoms, src, dst, bow=bow)

        np.testing.assert_allclose(_atom_pos(atoms, src["C3'"]), c3_before)
        np.testing.assert_allclose(_atom_pos(atoms, dst["C5'"]), c5_before)
        for name, serials, t in (
            ("O3'", src, 0.25),
            ("P", dst, 0.5),
            ("O5'", dst, 0.75),
        ):
            expected = c3_before + t * (c5_before - c3_before) + bow * np.sin(np.pi * t)
            np.testing.assert_allclose(_atom_pos(atoms, serials[name]), expected)

    def test_missing_keys_returns_silently(self):
        atoms = []
        # No C3'/C5'/P → should not raise
        _interpolate_backbone_bridge(atoms, {}, {})


# ── Bridge minimisation ───────────────────────────────────────────────────────


class TestMinimizeBackboneBridge:
    def test_canonical_chain_length(self):
        # Place src and dst at the canonical chain length so the minimiser
        # should reach near-zero residual.
        chain_len = _CANON_C3O3 + _CANON_O3P + _CANON_PO5 + _CANON_O5C5
        atoms, src = _build_ribose(np.zeros(3))
        atoms2, dst = _build_ribose(np.array([chain_len, 0.0, 0.0]))
        offset = len(atoms)
        atoms.extend(atoms2)
        dst = {k: v + offset for k, v in dst.items()}

        # Move dst C5' to be exactly chain_len from src C3' along x
        c3 = _atom_pos(atoms, src["C3'"])
        _set_atom_pos(atoms, dst["C5'"], c3 + np.array([chain_len, 0.0, 0.0]))

        _minimize_backbone_bridge(atoms, src, dst)

        c5 = _atom_pos(atoms, dst["C5'"])
        o3 = _atom_pos(atoms, src["O3'"])
        p = _atom_pos(atoms, dst["P"])
        o5 = _atom_pos(atoms, dst["O5'"])

        # Bond lengths should be near canonical (loose tol — angle terms compete
        # with bond-length terms in the objective, so the minimiser converges to
        # a compromise rather than exact canonical).
        assert abs(np.linalg.norm(o3 - c3) - _CANON_C3O3) / _CANON_C3O3 < 0.25
        assert abs(np.linalg.norm(p - o3) - _CANON_O3P) / _CANON_O3P < 0.25
        assert abs(np.linalg.norm(o5 - p) - _CANON_PO5) / _CANON_PO5 < 0.25
        assert abs(np.linalg.norm(c5 - o5) - _CANON_O5C5) / _CANON_O5C5 < 0.25

    def test_op1_op2_follow_p(self):
        atoms, src = _build_ribose(np.zeros(3))
        atoms2, dst = _build_ribose(np.array([0.6, 0.0, 0.0]))
        offset = len(atoms)
        atoms.extend(atoms2)
        dst = {k: v + offset for k, v in dst.items()}

        p_before = _atom_pos(atoms, dst["P"])
        op1_before = _atom_pos(atoms, dst["OP1"])
        _minimize_backbone_bridge(atoms, src, dst)
        p_after = _atom_pos(atoms, dst["P"])
        op1_after = _atom_pos(atoms, dst["OP1"])
        np.testing.assert_allclose(
            op1_after - op1_before, p_after - p_before, atol=1e-9
        )

    def test_missing_keys_returns_silently(self):
        _minimize_backbone_bridge([], {}, {})


# ── Rigid-body primitives ─────────────────────────────────────────────────────


def _build_eb_scenario(n_eb: int) -> tuple[list[AtomLike], dict, dict, list[dict]]:
    """Place src + dst + n_eb extra-base ribose rings spread along the x-axis."""
    atoms = []
    atoms_src, src = _build_ribose(np.zeros(3))
    src = {k: v for k, v in src.items()}
    atoms.extend(atoms_src)

    eb_dicts = []
    for i in range(n_eb):
        atoms_eb, eb_s = _build_ribose(np.array([0.5 * (i + 1), 0.0, 0.0]))
        offset = len(atoms)
        atoms.extend(atoms_eb)
        eb_dicts.append({k: v + offset for k, v in eb_s.items()})

    atoms_dst, dst = _build_ribose(np.array([0.5 * (n_eb + 1), 0.0, 0.0]))
    offset = len(atoms)
    atoms.extend(atoms_dst)
    dst = {k: v + offset for k, v in dst.items()}

    return atoms, src, dst, eb_dicts
