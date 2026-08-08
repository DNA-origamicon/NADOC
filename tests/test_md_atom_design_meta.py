"""MD all-atom views must carry design identity, or every atom renders CPK.

The live Display-MD ball-and-stick stream, the NAMD trajectory-frame atoms and the MD
molecular surface all render the SIMULATION's own atoms — which, unlike the design's own
atomistic model, carry no strand/helix/bp keys.  The frontend colour resolver looks up
``atom.strand_id``; with nothing there every MD atom fell back to CPK and the
strand/base/cluster colouring buttons did nothing.

``build_atom_design_meta`` restores that identity per residue (P atom → ``p_order`` key →
the design model's strand id), and ``intern_atom_design_meta`` packs it for the wire.
These are pure/fast: a faked MDAnalysis Universe, no topology or trajectory on disk.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from backend.core.atomistic_to_nadoc import (
    build_atom_design_meta,
    intern_atom_design_meta,
)


def _model_p(helix_id, bp_index, direction, strand_id, **extra):
    """A design-model P atom (md_pkey reads the identity fields off it)."""
    return SimpleNamespace(
        name="P",
        helix_id=helix_id,
        bp_index=bp_index,
        direction=direction,
        strand_id=strand_id,
        crossover_id=None,
        extension_id=None,
        copy_k=0,
        **extra,
    )


def _residue(ix, resid, segid, n_atoms=1):
    res = SimpleNamespace(ix=ix, resid=resid, segid=segid)
    res.atoms = [SimpleNamespace(segid=segid, residue=res) for _ in range(n_atoms)]
    return res


class _FakeUniverse:
    """Answers the two selections build_atom_design_meta makes."""

    def __init__(self, residues, p_resindices):
        self._residues = residues
        self._p = SimpleNamespace(resindices=np.array(p_resindices, dtype=int))

    def select_atoms(self, sel):
        if sel.startswith("name P"):
            return self._p
        return SimpleNamespace(residues=self._residues)


def _heavy(resindices):
    return SimpleNamespace(resindices=np.array(resindices, dtype=int))


def test_heavy_atoms_inherit_their_residues_strand_id():
    # Two nucleotides, each with 3 heavy atoms, on two different strands.
    u = _FakeUniverse([_residue(0, 1, "A"), _residue(1, 1, "B")], p_resindices=[0, 1])
    p_order = [("h0", 5, "FORWARD"), ("h1", 9, "REVERSE")]
    model = SimpleNamespace(
        atoms=[
            _model_p("h0", 5, "FORWARD", "scaf"),
            _model_p("h1", 9, "REVERSE", "stap7"),
        ]
    )

    rows = build_atom_design_meta(u, _heavy([0, 0, 0, 1, 1, 1]), p_order, model)

    assert [r["strand_id"] for r in rows] == ["scaf"] * 3 + ["stap7"] * 3
    assert [r["helix_id"] for r in rows] == ["h0"] * 3 + ["h1"] * 3
    assert [r["bp_index"] for r in rows] == [5] * 3 + [9] * 3
    assert [r["direction"] for r in rows] == ["FORWARD"] * 3 + ["REVERSE"] * 3


def test_five_prime_terminus_without_a_p_atom_still_gets_its_strand():
    """pdb2gmx strips the 5' P, so that residue is absent from p_order — it must be
    recovered through the chain map or the whole first base of every strand goes CPK."""
    residues = [_residue(0, 1, "SEGA"), _residue(1, 2, "SEGA")]
    u = _FakeUniverse(residues, p_resindices=[1])  # only residue 1 has a P
    p_order = [("h0", 2, "FORWARD")]
    model = SimpleNamespace(
        atoms=[
            _model_p("h0", 1, "FORWARD", "scaf"),
            _model_p("h0", 2, "FORWARD", "scaf"),
        ]
    )
    chain_map = {("A", 1): ("h0", 1, "FORWARD"), ("A", 2): ("h0", 2, "FORWARD")}

    rows = build_atom_design_meta(
        u, _heavy([0, 1]), p_order, model, chain_map, {"SEGA": "A"}
    )

    assert [r["strand_id"] for r in rows] == ["scaf", "scaf"]
    assert [r["bp_index"] for r in rows] == [1, 2]


def test_terminus_falls_back_to_cpk_when_the_segid_map_is_unavailable():
    """Without the segid→chain map there is no way to key the P-less residue — it must
    come back blank (→ CPK) rather than borrow a neighbour's strand."""
    u = _FakeUniverse(
        [_residue(0, 1, "SEGA"), _residue(1, 2, "SEGA")], p_resindices=[1]
    )
    model = SimpleNamespace(atoms=[_model_p("h0", 2, "FORWARD", "scaf")])

    rows = build_atom_design_meta(u, _heavy([0, 1]), [("h0", 2, "FORWARD")], model)

    assert rows[0] == {"strand_id": "", "helix_id": "", "bp_index": -1, "direction": ""}
    assert rows[1]["strand_id"] == "scaf"


def test_crossover_extra_base_keeps_its_strand_colour_without_a_bogus_bp():
    """A ``__xb__`` key puts a str in slot 1 and an int in slot 2 — positionally reading
    them as (bp_index, direction) would emit garbage.  Strand id must still resolve."""
    u = _FakeUniverse([_residue(0, 1, "A")], p_resindices=[0])
    xb = SimpleNamespace(
        name="P",
        crossover_id="xo3",
        extra_base_k=1,
        strand_id="stap2",
        helix_id="h0",
        bp_index=4,
        direction="FORWARD",
    )
    rows = build_atom_design_meta(
        u, _heavy([0, 0]), [("__xb__", "xo3", 1)], SimpleNamespace(atoms=[xb])
    )

    assert [r["strand_id"] for r in rows] == ["stap2", "stap2"]
    assert rows[0]["helix_id"] == "__xb__"
    assert rows[0]["bp_index"] == -1  # no base-letter lookup → falls back to strand
    assert rows[0]["direction"] == ""


def test_intern_round_trips_every_atom():
    rows = [
        {"strand_id": "scaf", "helix_id": "h0", "bp_index": 5, "direction": "FORWARD"},
        {"strand_id": "scaf", "helix_id": "h0", "bp_index": 6, "direction": "REVERSE"},
        {"strand_id": "", "helix_id": "", "bp_index": -1, "direction": ""},
    ]
    packed = intern_atom_design_meta(rows)

    # Repeated values are interned once — that is the point of the wire format.
    assert packed["strands"] == ["scaf", ""]
    assert len(packed["strand_idx"]) == len(rows)
    unpacked = [
        {
            "strand_id": packed["strands"][packed["strand_idx"][i]],
            "helix_id": packed["helices"][packed["helix_idx"][i]],
            "direction": packed["dirs"][packed["dir_idx"][i]],
            "bp_index": packed["bp"][i],
        }
        for i in range(len(rows))
    ]
    assert unpacked == rows
