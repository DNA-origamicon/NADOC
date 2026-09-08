import hashlib
import json
from pathlib import Path

import pytest

from backend.parameterization.photoproduct_openmm_skeleton import (
    _graph_distances,
    assert_pinned_cgenff_inputs,
    parse_charmm_masses,
    parse_charmm_residue_impropers,
    retained_thymine_impropers,
)


def test_parse_charmm_masses_keeps_type_mass_and_element(tmp_path: Path):
    topology = tmp_path / "test.rtf"
    topology.write_text(
        "* test\n36 1\n"
        "MASS 1 CT 12.011 C ! carbon\n"
        "MASS 2 HT 1.008 H\n"
        "RESI TST 0.0\n"
    )

    assert parse_charmm_masses(topology) == {
        "CT": {"mass_amu": 12.011, "element": "C"},
        "HT": {"mass_amu": 1.008, "element": "H"},
    }


def test_graph_distances_classify_exclusions_and_one_four_pairs():
    keys = ["A", "B", "C", "D", "E"]
    bonds = [
        {"atoms": ["A", "B"]},
        {"atoms": ["B", "C"]},
        {"atoms": ["C", "D"]},
        {"atoms": ["C", "E"]},
    ]

    distances = _graph_distances(keys, bonds)

    assert distances[(0, 1)] == 1
    assert distances[(0, 2)] == 2
    assert distances[(0, 3)] == 3
    assert distances[(0, 4)] == 3
    assert distances[(3, 4)] == 2


def test_pinned_cgenff_guard_accepts_exact_hashes_and_rejects_changes(tmp_path: Path):
    topology = tmp_path / "top.rtf"
    parameters = tmp_path / "par.prm"
    topology.write_text("topology\n")
    parameters.write_text("parameters\n")
    manifest = tmp_path / "references.json"
    manifest.write_text(
        json.dumps(
            {
                "cgenff_reference_library": {
                    "topology_sha256": hashlib.sha256(topology.read_bytes()).hexdigest(),
                    "parameters_sha256": hashlib.sha256(
                        parameters.read_bytes()
                    ).hexdigest(),
                }
            }
        )
    )

    hashes = assert_pinned_cgenff_inputs(
        topology, parameters, reference_manifest_path=manifest
    )
    assert hashes["topology_sha256"] == hashlib.sha256(topology.read_bytes()).hexdigest()

    parameters.write_text("modified parameters\n")
    with pytest.raises(ValueError, match="parameters differ from the pinned"):
        assert_pinned_cgenff_inputs(
            topology, parameters, reference_manifest_path=manifest
        )


def test_parse_charmm_residue_impropers_keeps_only_requested_residue(tmp_path: Path):
    topology = tmp_path / "top.rtf"
    topology.write_text(
        "RESI ADE 0.0\nIMPR A B C D\n"
        "RESI THY -1.0\nIMPR C2 N1 N3 O2 C4 N3 C5 O4\n"
        "IMPR C5 C4 C6 C5M\n"
        "PRES NEXT 0.0\nIMPR X1 X2 X3 X4\n"
    )

    assert parse_charmm_residue_impropers(topology, "THY") == [
        ["C2", "N1", "N3", "O2"],
        ["C4", "N3", "C5", "O4"],
        ["C5", "C4", "C6", "C5M"],
    ]


def test_retained_thymine_impropers_excludes_replaced_c5_planarity(tmp_path: Path):
    topology = tmp_path / "top.rtf"
    topology.write_text(
        "RESI THY -1.0\n"
        "IMPR C2 N1 N3 O2 C4 N3 C5 O4 C5 C4 C6 C5M\n"
    )
    parameters = tmp_path / "par.prm"
    parameters.write_text(
        "IMPROPER\n"
        "CN1T NN2B NN2U ON1 110.0 0 0.0\n"
        "CN1 X X ON1 90.0 0 0.0\n"
        "CN9 X X CPD5 14.0 0 0.0\n"
        "END\n"
    )
    atom_types = {}
    for endpoint, c5_type in ((1, "CPD5"), (2, "CPD5B")):
        atom_types.update(
            {
                f"{endpoint}:C2": "CN1T",
                f"{endpoint}:N1": "NN2B",
                f"{endpoint}:N3": "NN2U",
                f"{endpoint}:O2": "ON1",
                f"{endpoint}:C4": "CN1",
                f"{endpoint}:C5": c5_type,
                f"{endpoint}:O4": "ON1",
                f"{endpoint}:C6": "CPD6",
                f"{endpoint}:C7": "CN9",
            }
        )
    removed = [
        [f"{endpoint}:C5", f"{endpoint}:C4", f"{endpoint}:C6", f"{endpoint}:C7"]
        for endpoint in (1, 2)
    ]

    retained = retained_thymine_impropers(
        topology_path=topology,
        parameter_paths=[parameters],
        atom_types=atom_types,
        removed_impropers=removed,
    )

    assert len(retained) == 4
    assert [item["k_kcal_mol_rad2"] for item in retained] == [110.0, 90.0] * 2
    assert all("C7" not in item["atoms"] for item in retained)
