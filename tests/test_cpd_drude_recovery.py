"""Chemical graph regressions for the isolated Drude campaign (no QM/MD runs)."""

import json
from pathlib import Path

import pytest

pytest.importorskip("openmm")
from experiments.cpd_drude_recovery.campaign import audit_graph
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms, nuclear_graph


def registry():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "backend/data/forcefield/photoproduct_registry.json"
        ).read_text()
    )


def test_anti_graph_rejects_syn_crosslinks():
    names = ["1:C5", "1:C6", "2:C5", "2:C6"]
    with pytest.raises(ValueError, match="Anti graph mismatch"):
        audit_graph(names, [(0, 1), (2, 3), (0, 2), (1, 3)], registry())
    assert audit_graph(names, [(0, 1), (2, 3), (0, 3), (1, 2)], registry())["passed"]


@pytest.mark.parametrize("extra", [[(0, 3)], [(0, 0)], [(0, 4)]])
def test_graph_cannot_hide_duplicate_or_invalid_bonds(extra):
    with pytest.raises(ValueError):
        audit_graph(
            ["1:C5", "1:C6", "2:C5", "2:C6"], [(0, 3), (1, 2)] + extra, registry()
        )


def test_psf_zero_is_preserved_for_explicit_rejection():
    psf = """PSF EXT DRUDE
         3 !NATOM
         1 D 1 THY O5' OD31A 1.0 15.6
         2 D 1 THY DO5' DRUD -1.0 0.4
         3 D 1 THY H5T HDP1A 0.0 1.008
         3 !NBOND
         1 0 1 2 1 3
"""
    _, _, sections = atoms_and_terms(psf)
    assert sections["NBOND"][3][0] == (1, 0)
    # Auxiliary particles and invalid indices cannot become nuclear graph atoms.
    atoms, bonds = nuclear_graph(psf)
    assert atoms == {("1", "O5'"), ("1", "H5T")}
    assert bonds == {(("1", "H5T"), ("1", "O5'"))}
