"""Exact inset selections must survive the atomistic display transport."""
from dataclasses import replace

from backend.core.atomistic import Atom, AtomisticModel, atomistic_to_json


def test_display_json_preserves_extension_loop_and_crossover_identity():
    anchor = Atom(serial=0, name="P", element="P", residue="DT", chain_id="A",
                  seq_num=1, x=1.0, y=2.0, z=3.0, strand_id="s", helix_id="h",
                  bp_index=4, direction="FORWARD")
    atoms = [anchor, replace(anchor, serial=1, extension_id="tail", ext_k=0),
             replace(anchor, serial=2, copy_k=1),
             replace(anchor, serial=3, crossover_id="xo", extra_base_k=2)]
    wire = atomistic_to_json(AtomisticModel(atoms=atoms, bonds=[(0, 1)]))
    assert [(a["extension_id"], a["ext_k"], a["copy_k"],
             a["crossover_id"], a["extra_base_k"]) for a in wire["atoms"]] == [
        (None, None, None, None, None), ("tail", 0, None, None, None),
        (None, None, 1, None, None), (None, None, None, "xo", 2),
    ]
    assert wire["bonds"] == [[0, 1]]
    assert all((a["x"], a["y"], a["z"]) == (1.0, 2.0, 3.0) for a in wire["atoms"])
