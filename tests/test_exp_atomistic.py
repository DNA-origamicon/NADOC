"""All-atom output and measured Full display; not equilibrium/seed validation."""

from threading import Event

import numpy as np
import pytest

from backend.core.exp_atomistic import full_frame, load_adapter, native_atoms
from backend.core.lattice import make_bundle_design
from backend.core.namd_topology import find_psfgen


def test_native_dna_includes_hydrogens_and_terminal_atoms_without_design_mutation():
    try:
        find_psfgen()
    except RuntimeError:
        pytest.skip("psfgen unavailable")
    design = make_bundle_design(cells=[(0, 0)], length_bp=8, strand_filter="scaffold")
    before = design.model_dump_json()
    native = native_atoms(design)
    assert len(native["keys"]) == 8
    assert native["elements"].count("H") > 8
    assert len(native["identities"]) == len(set(native["identities"]))
    assert native["names"].count("P") == 7
    frame = np.asarray(
        full_frame(
            native["positions_nm"],
            native["names"],
            native["residue_index"],
            native["keys"],
        )
    ).reshape(-1, 12)
    # First residue has O5' instead of P, just like NAMD's recovered termini.
    for row, key in enumerate(native["keys"]):
        indices = np.flatnonzero(native["residue_index"] == row)
        atoms = {native["names"][i]: native["positions_nm"][i] for i in indices}
        np.testing.assert_allclose(frame[row, :3], atoms.get("P", atoms["O5'"]))
        np.testing.assert_allclose(np.linalg.norm(frame[row, 3:6]), 1)
        np.testing.assert_allclose(np.linalg.norm(frame[row, 6:9]), 1)
    assert design.model_dump_json() == before


def test_installed_model_predicts_every_atom_and_projects_its_predicted_ring(
    monkeypatch,
):
    # Multiple non-collinear rings along a bundle; H displacements must survive.
    ring = np.column_stack([np.cos(np.arange(6)), np.sin(np.arange(6)), np.zeros(6)])
    xyz = np.vstack(
        [
            np.vstack([[2, 0, 0], [1.5, 0, 0], ring, [2.1, 0, 0.1]]) + [0, 0, z]
            for z in range(0, 30, 3)
        ]
    )
    names = ["P", "C1'", "N1", "C2", "N3", "C4", "C5", "C6", "H1"] * 10
    keys = [("h", i, "FORWARD", 0) for i in range(10)]
    native = dict(
        positions_nm=xyz,
        names=names,
        elements=[n[0] for n in names],
        residue_index=np.repeat(np.arange(10), 9),
        keys=keys,
    )
    monkeypatch.setattr("backend.core.exp_atomistic.native_atoms", lambda _: native)
    design = make_bundle_design(cells=[(0, 0)], length_bp=10, strand_filter="scaffold")
    adapter, card = load_adapter()
    result = adapter(design, lambda *_: None, Event())
    predicted = np.asarray(result["positions_nm"])
    assert card["id"] == "exp-0xT-atoms-v1"
    assert predicted.shape == xyz.shape
    assert result["atoms"]["includes_hydrogens"]
    assert not np.allclose(predicted[8::9], xyz[8::9])
    frame = np.asarray(result["full"]["frame"]).reshape(-1, 12)
    np.testing.assert_allclose(frame[:, :3], predicted[::9])
    np.testing.assert_allclose(
        frame[:, 9:12], predicted.reshape(10, 9, 3)[:, 2:8].mean(axis=1)
    )
