import hashlib
import json
from pathlib import Path

import backend.parameterization.photoproduct_boundary_nonbonded as module
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.parameterization.photoproduct_boundary_nonbonded import (
    build_boundary_nonbonded_specification,
)
from backend.parameterization.photoproduct_models import (
    _expected_boundary_bond_orders,
)


ROOT = Path(__file__).parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_boundary_nonbonded_scope_freezes_native_dtpdt_without_endpoint_symmetry(
    tmp_path: Path, monkeypatch
):
    definition = load_chemical_definition("TT-CPD", "trans-anti-I")
    bonds = _expected_boundary_bond_orders(definition)
    atom_map = sorted({atom for pair in bonds for atom in pair})
    graph_path = tmp_path / "model_graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-graph.v1",
                "formal_charge": -1,
                "atoms": [{"key": key} for key in atom_map],
            }
        )
        + "\n"
    )
    map_path = tmp_path / "atom_map.json"
    map_path.write_text(json.dumps(atom_map) + "\n")
    model_path = tmp_path / "model_manifest.json"
    model_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-compound.v1",
                "status": "optimized_full_boundary_fit_input",
                "product_id": "tt-cpd-trans-anti-i",
                "model_id": "trans-anti-i-dtpdt-test",
                "product": "TT-CPD",
                "stereochemistry": "trans-anti-I",
                "atom_count": 63,
                "charge": -1,
                "atom_map": atom_map,
                "outputs": {
                    "atom_map": {"path": str(map_path), "sha256": _sha256(map_path)},
                    "graph": {"path": str(graph_path), "sha256": _sha256(graph_path)},
                },
            }
        )
        + "\n"
    )

    nucleic = ROOT / "backend/data/forcefield/top_all36_na.rtf"
    cgenff_topology = tmp_path / "top_all36_cgenff.rtf"
    cgenff_topology.write_text("* hash fixture\n")
    cgenff_parameters = tmp_path / "par_all36_cgenff.prm"
    cgenff_parameters.write_text("* hash fixture\n")
    references = tmp_path / "references.json"
    references.write_text(
        json.dumps(
            {
                "base_forcefield": {"topology": {"sha256": _sha256(nucleic)}},
                "cgenff_reference_library": {
                    "topology_sha256": _sha256(cgenff_topology),
                    "parameters_sha256": _sha256(cgenff_parameters),
                },
            }
        )
        + "\n"
    )
    monkeypatch.setattr(module, "REFERENCE_MANIFEST_PATH", references)

    report = build_boundary_nonbonded_specification(
        model_manifest_path=model_path,
        nucleic_topology_path=nucleic,
        cgenff_topology_path=cgenff_topology,
        cgenff_parameters_path=cgenff_parameters,
        output_path=tmp_path / "nonbonded_specification.json",
    )

    assert report["product_id"] == "tt-cpd-trans-anti-i"
    assert len(report["variable_atoms"]) == 28
    assert len(report["fixed_atoms"]) == 35
    assert report["charge_audit"]["initial_variable_charge_e"] == 0.0
    assert report["charge_audit"]["fixed_charge_e"] == -1.0
    assert report["charge_audit"]["total_model_charge_e"] == -1.0
    assert report["charge_audit"]["endpoint_exchange_symmetry_enforced"] is False
    types = {item["atom"]: item["candidate_type"] for item in report["variable_atoms"]}
    assert types["1:C5"] == "CG3C41"
    assert types["2:C6"] == "CG3C41"
