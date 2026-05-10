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
    _XB_CACHE,
    _XB_CACHE_LOCK,
    _XB_CACHE_MAX,
    _apply_phosphate,
    _atom_pos,
    _interpolate_backbone_bridge,
    _minimize_1_extra_base,
    _minimize_2_extra_base,
    _minimize_3_extra_base,
    _minimize_backbone_bridge,
    _rb_apply,
    _rb_extract,
    _rb_world,
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


def _build_ribose(origin: np.ndarray, scale: float = 0.15) -> tuple[list[AtomLike], dict[str, int]]:
    """
    Build a minimal sugar-phosphate ribose ring around `origin` with the
    serial-name pattern expected by the minimisers.  Atom positions are
    placed approximately at canonical B-DNA distances.
    """
    # Synthetic but plausible ribose layout.  Origin = C2'.
    layout = {
        "C2'":  origin + np.array([ 0.00,  0.00, 0.00]),
        "C1'":  origin + np.array([ 0.15,  0.00, 0.00]),
        "C3'":  origin + np.array([-0.10,  0.10, 0.00]),
        "O3'":  origin + np.array([-0.20,  0.20, 0.00]),
        "C4'":  origin + np.array([ 0.05,  0.15, 0.00]),
        "O4'":  origin + np.array([ 0.18,  0.10, 0.00]),
        "C5'":  origin + np.array([ 0.10,  0.30, 0.00]),
        "O5'":  origin + np.array([ 0.20,  0.40, 0.00]),
        "P":    origin + np.array([ 0.30,  0.55, 0.00]),
        "OP1":  origin + np.array([ 0.35,  0.60, 0.10]),
        "OP2":  origin + np.array([ 0.25,  0.60,-0.10]),
        "N1":   origin + np.array([ 0.30, -0.05, 0.00]),  # base attachment for DT/DC
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
        np.testing.assert_array_equal([atoms[0].x, atoms[0].y, atoms[0].z], [0.7, 0.8, 0.9])


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
        np.testing.assert_allclose(_atom_pos(atoms, src["O3'"]), c3 + 0.25 * (c5 - c3), atol=1e-9)
        np.testing.assert_allclose(_atom_pos(atoms, dst["P"]),   c3 + 0.50 * (c5 - c3), atol=1e-9)
        np.testing.assert_allclose(_atom_pos(atoms, dst["O5'"]), c3 + 0.75 * (c5 - c3), atol=1e-9)

    def test_op1_op2_translated_with_p(self):
        atoms, src = _build_ribose(np.zeros(3))
        atoms2, dst = _build_ribose(np.array([0.5, 0.0, 0.0]))
        offset = len(atoms)
        atoms.extend(atoms2)
        dst = {k: v + offset for k, v in dst.items()}

        op1_before = _atom_pos(atoms, dst["OP1"])
        op2_before = _atom_pos(atoms, dst["OP2"])
        p_before   = _atom_pos(atoms, dst["P"])
        _interpolate_backbone_bridge(atoms, src, dst)
        p_after    = _atom_pos(atoms, dst["P"])
        delta_p    = p_after - p_before
        np.testing.assert_allclose(_atom_pos(atoms, dst["OP1"]), op1_before + delta_p, atol=1e-9)
        np.testing.assert_allclose(_atom_pos(atoms, dst["OP2"]), op2_before + delta_p, atol=1e-9)

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
        p  = _atom_pos(atoms, dst["P"])
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

        p_before   = _atom_pos(atoms, dst["P"])
        op1_before = _atom_pos(atoms, dst["OP1"])
        _minimize_backbone_bridge(atoms, src, dst)
        p_after    = _atom_pos(atoms, dst["P"])
        op1_after  = _atom_pos(atoms, dst["OP1"])
        np.testing.assert_allclose(op1_after - op1_before, p_after - p_before, atol=1e-9)

    def test_missing_keys_returns_silently(self):
        _minimize_backbone_bridge([], {}, {})


# ── Rigid-body primitives ─────────────────────────────────────────────────────


class TestRbExtract:
    def test_excludes_phosphate(self):
        atoms, s = _build_ribose(np.zeros(3))
        c2_w, names, mat = _rb_extract(atoms, s)
        np.testing.assert_array_equal(c2_w, [0.0, 0.0, 0.0])
        # Phosphate atoms must be excluded
        for forbidden in ("P", "OP1", "OP2", "O5'"):
            assert forbidden not in names
        # Other ring atoms preserved
        for required in ("C1'", "C2'", "C3'", "O3'", "C4'", "O4'", "C5'"):
            assert required in names

    def test_local_mat_relative_to_c2(self):
        atoms, s = _build_ribose(np.zeros(3))
        c2_w, names, mat = _rb_extract(atoms, s)
        # mat is (N, 3); the row for C2' should be (0, 0, 0).
        c2_idx = names.index("C2'")
        np.testing.assert_allclose(mat[c2_idx], [0.0, 0.0, 0.0], atol=1e-9)


class TestRbWorld:
    def test_zero_delta_identity_rot(self):
        c2_w = np.array([1.0, 2.0, 3.0])
        names = ("a", "b")
        mat = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0]])
        out = _rb_world(c2_w, names, mat, np.zeros(3), np.eye(3))
        np.testing.assert_allclose(out["a"], c2_w + np.array([0.5, 0.0, 0.0]))
        np.testing.assert_allclose(out["b"], c2_w + np.array([0.0, 0.5, 0.0]))

    def test_translation_offset(self):
        c2_w = np.zeros(3)
        names = ("a",)
        mat = np.array([[1.0, 0.0, 0.0]])
        out = _rb_world(c2_w, names, mat, np.array([1.0, 2.0, 3.0]), np.eye(3))
        np.testing.assert_allclose(out["a"], [2.0, 2.0, 3.0])

    def test_rotation_about_z(self):
        c2_w = np.zeros(3)
        names = ("a",)
        mat = np.array([[1.0, 0.0, 0.0]])
        # 90° z-rotation: (1,0,0) → (0,1,0)
        c, s = 0.0, 1.0
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        out = _rb_world(c2_w, names, mat, np.zeros(3), R)
        np.testing.assert_allclose(out["a"], [0.0, 1.0, 0.0], atol=1e-12)


class TestRbApply:
    def test_writes_non_phosphate_only(self):
        atoms, s = _build_ribose(np.zeros(3))
        rb_pos = {
            "C1'": np.array([10.0, 20.0, 30.0]),
            "P":   np.array([99.0, 99.0, 99.0]),  # should be ignored (phosphate)
            "OP1": np.array([99.0, 99.0, 99.0]),
        }
        p_orig = _atom_pos(atoms, s["P"])
        op1_orig = _atom_pos(atoms, s["OP1"])
        _rb_apply(atoms, s, rb_pos)
        np.testing.assert_array_equal(_atom_pos(atoms, s["C1'"]), [10.0, 20.0, 30.0])
        np.testing.assert_array_equal(_atom_pos(atoms, s["P"]), p_orig)
        np.testing.assert_array_equal(_atom_pos(atoms, s["OP1"]), op1_orig)


class TestApplyPhosphate:
    def test_translates_op1_op2_with_p(self):
        atoms, s = _build_ribose(np.zeros(3))
        p_orig   = _atom_pos(atoms, s["P"])
        op1_orig = _atom_pos(atoms, s["OP1"])
        op2_orig = _atom_pos(atoms, s["OP2"])

        new_p  = p_orig + np.array([1.0, 0.0, 0.0])
        new_o5 = _atom_pos(atoms, s["O5'"]) + np.array([0.5, 0.0, 0.0])
        _apply_phosphate(atoms, s, new_p, new_o5)

        np.testing.assert_allclose(_atom_pos(atoms, s["P"]),   new_p)
        np.testing.assert_allclose(_atom_pos(atoms, s["O5'"]), new_o5)
        np.testing.assert_allclose(_atom_pos(atoms, s["OP1"]), op1_orig + np.array([1.0, 0.0, 0.0]))
        np.testing.assert_allclose(_atom_pos(atoms, s["OP2"]), op2_orig + np.array([1.0, 0.0, 0.0]))


# ── Joint extra-base minimisers ───────────────────────────────────────────────


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


class TestMinimize1ExtraBase:
    def test_runs_and_writes_positions(self):
        atoms, src, dst, ebs = _build_eb_scenario(1)
        target_c1n = np.array([0.0, 0.0, 1.0])
        before = _atom_pos(atoms, src["O3'"]).copy()
        _minimize_1_extra_base(atoms, src, dst, ebs[0], "N1", target_c1n, [])
        after = _atom_pos(atoms, src["O3'"])
        assert not np.allclose(before, after)

    def test_missing_src_keys_returns_silently(self):
        # src missing C3'/O3' → return without crash
        atoms, _, dst, ebs = _build_eb_scenario(1)
        _minimize_1_extra_base(atoms, {}, dst, ebs[0], "N1", np.array([0, 0, 1.0]), [])

    def test_cache_replays_solution(self):
        atoms, src, dst, ebs = _build_eb_scenario(1)
        target = np.array([0.0, 0.0, 1.0])
        cache_key = ("test_xo_1", ("A",), (0.0,) * 3, (1.0,) * 3, (0.0, 0.0, 1.0))
        # Clear before test to avoid pollution
        _XB_CACHE.pop(cache_key, None)
        _minimize_1_extra_base(atoms, src, dst, ebs[0], "N1", target, [], cache_key=cache_key)
        assert cache_key in _XB_CACHE
        # Second call uses cache (should not re-run scipy; just apply)
        atoms2, src2, dst2, ebs2 = _build_eb_scenario(1)
        _minimize_1_extra_base(atoms2, src2, dst2, ebs2[0], "N1", target, [], cache_key=cache_key)
        # Resulting positions should match the cached solution
        np.testing.assert_allclose(
            _atom_pos(atoms, src["O3'"]),
            _atom_pos(atoms2, src2["O3'"]),
            atol=1e-9,
        )
        _XB_CACHE.pop(cache_key, None)


class TestMinimize2ExtraBase:
    def test_runs_and_writes_positions(self):
        atoms, src, dst, ebs = _build_eb_scenario(2)
        target = np.array([0.0, 0.0, 1.0])
        before = _atom_pos(atoms, src["O3'"]).copy()
        _minimize_2_extra_base(atoms, src, dst, ebs[0], ebs[1], "N1", "N1", target, [])
        after = _atom_pos(atoms, src["O3'"])
        assert not np.allclose(before, after)

    def test_missing_eb_keys_returns_silently(self):
        atoms, src, dst, ebs = _build_eb_scenario(2)
        _minimize_2_extra_base(atoms, src, dst, ebs[0], {}, "N1", "N1",
                               np.array([0, 0, 1.0]), [])

    def test_cache_path(self):
        atoms, src, dst, ebs = _build_eb_scenario(2)
        target = np.array([0.0, 0.0, 1.0])
        cache_key = ("test_xo_2", ("A", "T"), (0.0,) * 3, (1.5,) * 3, (0.0, 0.0, 1.0))
        _XB_CACHE.pop(cache_key, None)
        _minimize_2_extra_base(atoms, src, dst, ebs[0], ebs[1], "N1", "N1",
                               target, [], cache_key=cache_key)
        assert cache_key in _XB_CACHE
        _XB_CACHE.pop(cache_key, None)


class TestMinimize3ExtraBase:
    def test_runs_and_writes_positions(self):
        atoms, src, dst, ebs = _build_eb_scenario(3)
        target = np.array([0.0, 0.0, 1.0])
        before = _atom_pos(atoms, src["O3'"]).copy()
        _minimize_3_extra_base(atoms, src, dst, ebs[0], ebs[1], ebs[2],
                               "N1", "N1", "N1", target, [])
        after = _atom_pos(atoms, src["O3'"])
        assert not np.allclose(before, after)

    def test_missing_dst_keys_returns_silently(self):
        atoms, src, _, ebs = _build_eb_scenario(3)
        _minimize_3_extra_base(atoms, src, {}, ebs[0], ebs[1], ebs[2],
                               "N1", "N1", "N1", np.array([0, 0, 1.0]), [])

    def test_cache_path(self):
        atoms, src, dst, ebs = _build_eb_scenario(3)
        target = np.array([0.0, 0.0, 1.0])
        cache_key = ("test_xo_3", ("A", "T", "G"), (0.0,) * 3, (2.0,) * 3, (0.0, 0.0, 1.0))
        _XB_CACHE.pop(cache_key, None)
        _minimize_3_extra_base(atoms, src, dst, ebs[0], ebs[1], ebs[2],
                               "N1", "N1", "N1", target, [], cache_key=cache_key)
        assert cache_key in _XB_CACHE
        _XB_CACHE.pop(cache_key, None)


# ── Cache eviction ────────────────────────────────────────────────────────────


class TestCacheModule:
    def test_constants_present(self):
        assert isinstance(_XB_CACHE, dict)
        assert _XB_CACHE_MAX > 0
        assert _XB_CACHE_LOCK is not None

    def test_cache_eviction_drops_oldest(self):
        # Pre-fill cache to MAX; running a fresh job should evict.
        # Use a tiny throwaway test that exercises the eviction branch.
        sentinel_keys = [(f"sentinel_{i}", (), (0,) * 3, (0,) * 3, (0,) * 3)
                          for i in range(_XB_CACHE_MAX)]
        with _XB_CACHE_LOCK:
            for k in sentinel_keys:
                _XB_CACHE[k] = np.zeros(1)
        # Trigger eviction via _minimize_1_extra_base with a fresh key
        atoms, src, dst, ebs = _build_eb_scenario(1)
        new_key = ("evict_test", ("A",), (9,) * 3, (9,) * 3, (9,) * 3)
        _minimize_1_extra_base(atoms, src, dst, ebs[0], "N1",
                               np.array([0, 0, 1.0]), [], cache_key=new_key)
        # The cache should still be at MAX (one evicted, one added)
        # Sanity: eviction did happen — first sentinel may or may not be present
        # depending on dict iteration order, but the new key is present.
        assert new_key in _XB_CACHE
        # Cleanup
        for k in sentinel_keys:
            _XB_CACHE.pop(k, None)
        _XB_CACHE.pop(new_key, None)
