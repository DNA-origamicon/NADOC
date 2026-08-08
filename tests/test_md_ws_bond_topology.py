"""The STICK half of ball-and-stick for a NAMD run.

``/ws/md-run`` streams coordinates only; bond connectivity is static across a
trajectory, so it rides the one-time ``ready`` message.  Before
``_heavy_bond_pairs`` existed the frontend substituted ``bonds: []`` and MD Display
drew bare spheres for every NAMD job, live or finished.

Fast: builds tiny synthetic Universes in memory, no simulation, no fixture files.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.api.ws import _heavy_bond_pairs


def _pairs(flat):
    """Bond ORDER is not part of the contract — each cylinder is independent, and
    MDAnalysis normalises the list it hands back.  Compare the set of pairs."""
    assert flat is not None and len(flat) % 2 == 0
    return {(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)}


def _universe(n_atoms: int, bonds=None):
    """A minimal in-memory Universe, optionally carrying bond topology."""
    mda = pytest.importorskip("MDAnalysis")
    u = mda.Universe.empty(n_atoms, trajectory=True)
    if bonds is not None:
        u.add_TopologyAttr("bonds", list(bonds))
    return u


def test_returns_flat_serial_pairs_in_universe_index_space():
    # atom_meta sends `serial = Atom.index`, so bonds must be universe-global
    # indices — the frontend resolves them through its own serial→row map.
    u = _universe(6, bonds=[(0, 1), (1, 2), (3, 4)])

    out = _heavy_bond_pairs(u, np.arange(6))

    assert _pairs(out) == {(0, 1), (1, 2), (3, 4)}
    assert all(isinstance(v, int) for v in out)  # JSON-serialisable, not np.int32


def test_drops_bonds_reaching_outside_the_drawn_heavy_subset():
    # Atoms 4 and 5 stand in for hydrogens: not in the atom table, so a bond to
    # them has no second endpoint to draw and must not be emitted.
    u = _universe(6, bonds=[(0, 1), (1, 4), (2, 3), (4, 5)])

    out = _heavy_bond_pairs(u, np.array([0, 1, 2, 3]))

    assert _pairs(out) == {(0, 1), (2, 3)}


def test_heavy_subset_may_be_sparse_and_unsorted():
    # dna_heavy.indices is whatever the resname selection picked out of a solvated
    # box — non-contiguous, and never the low indices only.
    u = _universe(10, bonds=[(7, 9), (2, 7), (0, 1)])

    out = _heavy_bond_pairs(u, np.array([9, 2, 7]))

    assert _pairs(out) == {(7, 9), (2, 7)}


def test_returns_none_when_the_topology_carries_no_bonds():
    # GRO topologies have none.  None (not []) so the caller can log the reason and
    # the display falls back to spheres exactly as it did before.
    assert _heavy_bond_pairs(_universe(4), np.arange(4)) is None


def test_returns_none_when_no_bond_survives_the_heavy_filter():
    u = _universe(4, bonds=[(0, 2), (1, 3)])

    assert _heavy_bond_pairs(u, np.array([0, 1])) is None


def test_survives_a_universe_that_raises_on_bonds():
    class _Exploding:
        atoms = ()

        @property
        def bonds(self):
            raise RuntimeError("no bond data")

    # Colour and connectivity are cosmetic — a bad topology must never fail a display.
    assert _heavy_bond_pairs(_Exploding(), np.array([0])) is None


# ── the REST trajectory-scrub model (the OTHER consumer) ─────────────────────
#
# The live WS stream and the REST atomistic-model both need these bonds, in the same
# serial space, but on DIFFERENT wire shapes. That difference is not cosmetic:
# ``atomistic_renderer._rebuild`` reads a **typed** array as flat and a **plain** array
# as nested pairs, so handing the REST path a flat plain list renders NO sticks at all
# and reports no error. These pin both shapes and the fact that they agree.


def test_nested_shape_is_pairs_not_a_flat_list():
    from backend.core.md_trajectory import heavy_bond_pairs

    u = _universe(6, bonds=[(0, 1), (1, 2), (3, 4)])

    out = heavy_bond_pairs(u, np.arange(6), nested=True)

    assert all(isinstance(p, list) and len(p) == 2 for p in out)
    assert {tuple(p) for p in out} == {(0, 1), (1, 2), (3, 4)}
    assert all(isinstance(v, int) for p in out for v in p)  # JSON, not np.int32


def test_flat_and_nested_carry_the_same_bonds():
    from backend.core.md_trajectory import heavy_bond_pairs

    u = _universe(10, bonds=[(7, 9), (2, 7), (0, 1)])
    heavy = np.array([9, 2, 7])

    flat = heavy_bond_pairs(u, heavy, nested=False)
    nested = heavy_bond_pairs(u, heavy, nested=True)

    assert _pairs(flat) == {tuple(p) for p in nested}


def test_ws_delegates_to_the_shared_implementation():
    """One owner: the serial space has to match atom_meta on both paths, and two copies
    of that rule drift."""
    from backend.core.md_trajectory import heavy_bond_pairs

    u = _universe(6, bonds=[(0, 1), (1, 2), (3, 4)])

    assert _heavy_bond_pairs(u, np.arange(6)) == heavy_bond_pairs(
        u, np.arange(6), nested=False
    )


def test_nested_returns_none_with_no_bonds_so_the_model_declares_unavailable():
    from backend.core.md_trajectory import heavy_bond_pairs

    # md_atomistic_model turns this None into bonds_available=False, which tells the
    # display to stop hunting rather than re-run a ~30 s reconstruction per repr flip.
    assert heavy_bond_pairs(_universe(4), np.arange(4), nested=True) is None
