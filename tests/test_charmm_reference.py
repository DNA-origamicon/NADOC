from pathlib import Path

import pytest

from backend.parameterization.charmm_reference import (
    _model_to_1mth_name,
    build_atom_type_candidate_plan,
    parse_charmm_residue,
)


def test_parse_charmm_residue_extracts_declared_atom_charges(tmp_path: Path):
    topology = tmp_path / "test.rtf"
    topology.write_text(
        "* test\n36 1\n"
        "RESI TEST 0.00\n"
        "GROUP\n"
        "ATOM C1 CT -0.20\n"
        "ATOM H1 HT  0.20 ! inline comment\n"
        "BOND C1 H1\n"
        "RESI NEXT 0.00\n"
    )
    residue = parse_charmm_residue(topology, "TEST")
    assert residue["declared_charge"] == 0
    assert residue["atoms"] == [
        {"name": "C1", "atom_type": "CT", "charge": -0.2},
        {"name": "H1", "atom_type": "HT", "charge": 0.2},
    ]


def test_parse_charmm_residue_rejects_inconsistent_declared_charge(tmp_path: Path):
    topology = tmp_path / "bad.rtf"
    topology.write_text("RESI BAD 0.00\nATOM C CT -0.20\n")
    with pytest.raises(ValueError, match="atom charges sum"):
        parse_charmm_residue(topology, "BAD")


def test_legacy_ccd_hydrogen_aliases_remain_losslessly_mappable():
    assert _model_to_1mth_name("1:HN3") == "H3"
    assert _model_to_1mth_name("2:HT") == "H3"
    assert _model_to_1mth_name("1:H5A2") == "H52"
    assert _model_to_1mth_name("2:H73") == "H53"


def test_atom_type_plan_refuses_unreviewed_product(tmp_path: Path):
    topology = tmp_path / "cgenff.rtf"
    topology.write_text("not the pinned topology")
    manifest = tmp_path / "model.json"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="CGenFF topology hash mismatch"):
        build_atom_type_candidate_plan(
            cgenff_topology=topology,
            model_manifest_path=manifest,
            output_path=tmp_path / "plan.json",
        )
