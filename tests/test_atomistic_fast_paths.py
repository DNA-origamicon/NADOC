"""Behaviour pins for the export/display hot-path optimisations in `backend.core.atomistic`.

Both of these replaced working code for SPEED only, so every test here carries the ORIGINAL
implementation inline as its oracle and asserts the new code agrees with it. That way the pin
does not depend on test-ordering (a test written against moved/adapted code and green on its
first run proves nothing on its own).

Motivating profile — one export frame of VoltronCoreScad (16,168 nt / 330,622 atoms), 2026-07-23:
    frame_atomistic_flat            6.8 s
      np.cross (57,500 calls)       3.0 s   <- _cross3
      builtins.round (996,960)      0.5 s   <- atomistic_positions_flat
"""
import numpy as np
import pytest

from backend.core.atomistic import _cross3, atomistic_positions_flat


class TestCross3:
    """_cross3 must be indistinguishable from np.cross on 3-vectors."""

    @pytest.mark.parametrize("a,b", [
        ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),          # canonical basis
        ([0.0, 0.0, 1.0], [0.0, 0.0, 1.0]),          # parallel -> zero
        ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),          # generic
        ([-3.5, 0.25, 7.125], [2.0, -8.5, 0.125]),   # exact binary fractions
        ([1e-12, 2e-12, 3e-12], [4e12, 5e12, 6e12]), # wide dynamic range
        ([0.1, 0.2, 0.3], [0.4, 0.5, 0.6]),          # inexact binary reprs
    ])
    def test_bit_identical_to_np_cross(self, a, b):
        av, bv = np.array(a), np.array(b)
        expected = np.cross(av, bv)
        got = _cross3(av, bv)
        # Bit-identical, not merely close: same IEEE ops in the same order.
        assert got.tolist() == expected.tolist()
        assert got.dtype == expected.dtype

    def test_anticommutes_and_is_orthogonal(self):
        a = np.array([0.3, -1.7, 2.2])
        b = np.array([4.1, 0.9, -0.6])
        assert _cross3(a, b).tolist() == (-_cross3(b, a)).tolist()
        assert abs(float(np.dot(_cross3(a, b), a))) < 1e-12
        assert abs(float(np.dot(_cross3(a, b), b))) < 1e-12

    def test_accepts_plain_sequences_like_np_cross(self):
        assert _cross3([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]).tolist() == [0.0, 0.0, 1.0]

    def test_randomised_agreement_over_many_vectors(self):
        rng = np.random.default_rng(20260723)
        for _ in range(500):
            a = rng.normal(size=3) * rng.choice([1e-6, 1.0, 1e6])
            b = rng.normal(size=3) * rng.choice([1e-6, 1.0, 1e6])
            assert _cross3(a, b).tolist() == np.cross(a, b).tolist()


class _FakeAtom:
    __slots__ = ("serial", "x", "y", "z")

    def __init__(self, serial, x, y, z):
        self.serial = serial
        self.x, self.y, self.z = x, y, z


class _FakeModel:
    def __init__(self, atoms):
        self.atoms = atoms


def _positions_flat_original(model):
    """The pre-vectorisation implementation, verbatim — this test's oracle."""
    atom_count = len(model.atoms)
    result = [0.0] * (atom_count * 3)
    for a in model.atoms:
        idx = a.serial * 3
        result[idx] = round(a.x, 5)
        result[idx + 1] = round(a.y, 5)
        result[idx + 2] = round(a.z, 5)
    return result


class TestAtomisticPositionsFlat:
    def test_matches_original_loop_on_dense_serials(self):
        rng = np.random.default_rng(7)
        atoms = [_FakeAtom(i, *(float(v) for v in rng.normal(size=3) * 30.0))
                 for i in range(500)]
        model = _FakeModel(atoms)
        assert atomistic_positions_flat(model) == _positions_flat_original(model)

    def test_scatters_by_serial_not_list_order(self):
        # Serials out of list order must land at serial*3, as the loop did.
        atoms = [_FakeAtom(2, 7.0, 8.0, 9.0),
                 _FakeAtom(0, 1.0, 2.0, 3.0),
                 _FakeAtom(1, 4.0, 5.0, 6.0)]
        model = _FakeModel(atoms)
        assert atomistic_positions_flat(model) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        assert atomistic_positions_flat(model) == _positions_flat_original(model)

    def test_unwritten_slot_reads_zero_not_garbage(self):
        # A duplicate serial leaves slot 1 never written. np.empty would surface
        # uninitialised memory there; the original loop left 0.0.
        atoms = [_FakeAtom(0, 1.0, 1.0, 1.0), _FakeAtom(0, 3.0, 3.0, 3.0)]
        model = _FakeModel(atoms)
        out = atomistic_positions_flat(model)
        assert out == [3.0, 3.0, 3.0, 0.0, 0.0, 0.0]      # last write wins, slot 1 zeroed
        assert out == _positions_flat_original(model)

    def test_serial_beyond_atom_count_raises_as_it_always_did(self):
        # The result is sized atom_count*3, so a serial >= atom_count overran the list
        # in the original loop. numpy raises the same IndexError — preserved, not "fixed",
        # because callers rely on dense 0-based serials and a silent resize would mask a bug.
        model = _FakeModel([_FakeAtom(0, 1.0, 1.0, 1.0), _FakeAtom(2, 3.0, 3.0, 3.0)])
        with pytest.raises(IndexError):
            atomistic_positions_flat(model)
        with pytest.raises(IndexError):
            _positions_flat_original(model)

    def test_rounds_to_five_decimals(self):
        model = _FakeModel([_FakeAtom(0, 1.234567891, -2.000004999, 3.9999951)])
        assert atomistic_positions_flat(model) == _positions_flat_original(model)

    def test_empty_model(self):
        assert atomistic_positions_flat(_FakeModel([])) == []

    def test_agrees_with_loop_on_many_random_models(self):
        rng = np.random.default_rng(31337)
        for _ in range(40):
            n = int(rng.integers(1, 60))
            order = rng.permutation(n)
            atoms = [_FakeAtom(int(s), *(float(v) for v in rng.normal(size=3) * 100.0))
                     for s in order]
            model = _FakeModel(atoms)
            assert atomistic_positions_flat(model) == _positions_flat_original(model)
