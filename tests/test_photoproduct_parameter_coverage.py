import hashlib
import json
from pathlib import Path

import pytest

import backend.parameterization.photoproduct_parameter_coverage as coverage_module
from backend.parameterization.photoproduct_parameter_coverage import (
    audit_model_graph_parameter_coverage,
    audit_photoproduct_parameter_coverage,
    match_charmm_parameter,
    parse_charmm_bonded_parameters,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_parse_charmm_bonded_parameters_keeps_fourier_multiplicity(tmp_path: Path):
    path = tmp_path / "terms.prm"
    path.write_text(
        "* test\n"
        "BONDS\n"
        "C N 300.0 1.33 ! retained source comment\n"
        "ANGLES\n"
        "C N C 40.0 120.0\n"
        "DIHEDRALS\n"
        "X C N X 0.20 1 0.0\n"
        "X C N X 0.10 2 180.0\n"
        "IMPROPERS\n"
        "C X X O 10.0 0 180.0\n"
        "NONBONDED nbxmod 5\n"
        "C 0.0 -0.10 2.0\n"
    )

    records = parse_charmm_bonded_parameters(path)

    assert [record["category"] for record in records] == [
        "bonds",
        "angles",
        "dihedrals",
        "dihedrals",
        "impropers",
    ]
    assert records[0]["types"] == ["C", "N"]
    assert records[0]["values"] == [300.0, 1.33]
    assert records[0]["line_number"] == 3
    assert "retained source comment" in records[0]["raw"]


def test_match_prefers_exact_and_accepts_reverse_order():
    records = [
        {"category": "angles", "types": ["X", "N", "C"], "id": "wild"},
        {"category": "angles", "types": ["O", "N", "C"], "id": "exact"},
        {"category": "bonds", "types": ["O", "N"], "id": "wrong-category"},
    ]

    assert [item["id"] for item in match_charmm_parameter(records, "angles", ["C", "N", "O"])] == [
        "exact"
    ]
    assert match_charmm_parameter(records, "dihedrals", ["C", "N", "O", "H"]) == []


def test_coverage_audit_is_gate_neutral_and_reports_wildcards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cgenff = tmp_path / "cgenff.prm"
    cgenff.write_text(
        "BONDS\nC CT 100.0 1.5\n"
        "ANGLES\nCT C CT 40.0 110.0\n"
        "DIHEDRALS\nX C C X 0.2 3 0.0\n"
    )
    nucleic = tmp_path / "na.prm"
    nucleic.write_text("BONDS\nQ Q 100.0 1.0\n")
    references = tmp_path / "references.json"
    references.write_text(
        json.dumps(
            {
                "cgenff_reference_library": {
                    "parameters_sha256": _sha256(cgenff)
                },
                "base_forcefield": {
                    "topology": {"sha256": "topology-hash"},
                    "parameters": {"sha256": _sha256(nucleic)},
                },
            }
        )
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-atom-type-candidate-plan.v1",
                "product_id": "tt-cpd-cis-syn",
                "atoms": [
                    {
                        "model_atom": "1:C5",
                        "decision": "fit_required",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    hypotheses = tmp_path / "hypotheses.json"
    hypotheses.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-nonbonded-fit-hypotheses.v1",
                "product_id": "tt-cpd-cis-syn",
                "hypotheses": [
                    {
                        "id": "test-types",
                        "unresolved_type_sources": {"C5": "C"},
                    }
                ],
            }
        )
    )
    boundary = tmp_path / "boundary.json"
    boundary.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-parameter-coverage-hypotheses.v1",
                "status": "candidate_not_reviewed",
                "product_id": "tt-cpd-cis-syn",
                "unchanged_boundary_types": {"C1'": "CT"},
                "boundary_source": {"topology_sha256": "topology-hash"},
            }
        )
    )
    monkeypatch.setattr(
        coverage_module,
        "build_term_inventory",
        lambda *_: {
            "all_local_terms_requiring_type_or_parameter_audit": {
                "bonds": [["1:C5", "1:C1'"]],
                "angles": [["1:C1'", "1:C5", "1:C1'"]],
                "dihedrals": [["1:C1'", "1:C5", "1:C5", "1:C1'"]],
            }
        },
    )
    output = tmp_path / "coverage.json"

    report = audit_photoproduct_parameter_coverage(
        atom_type_plan_path=plan,
        hypotheses_path=hypotheses,
        cgenff_parameters_path=cgenff,
        nucleic_parameters_path=nucleic,
        output_path=output,
        reference_manifest_path=references,
        coverage_hypotheses_path=boundary,
    )

    assert report["status"] == "coverage_audit_complete_not_releasable"
    assert report["gate_effect"] == "none"
    assert report["results"][0]["release_eligible"] is False
    assert report["results"][0]["categories"]["bonds"]["exact_count"] == 1
    assert report["results"][0]["categories"]["angles"]["exact_count"] == 1
    assert report["results"][0]["categories"]["dihedrals"]["wildcard_count"] == 1
    assert report["results"][0]["total_missing_terms"] == 0
    assert json.loads(output.read_text()) == report


def test_complete_model_graph_coverage_is_hash_linked_and_gate_neutral(tmp_path: Path):
    graph = tmp_path / "model_graph.json"
    graph.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-graph.v1",
                "atom_count": 3,
                "bond_count": 2,
                "formal_charge": 0,
                "atoms": [
                    {"index": 0, "key": "1:C", "element": "C", "formal_charge": 0},
                    {"index": 1, "key": "1:N", "element": "N", "formal_charge": 0},
                    {"index": 2, "key": "1:H", "element": "H", "formal_charge": 0},
                ],
                "bonds": [
                    {"atoms": ["1:C", "1:N"], "indices": [0, 1], "order": 1.0},
                    {"atoms": ["1:N", "1:H"], "indices": [1, 2], "order": 1.0},
                ],
            }
        )
    )
    manifest = tmp_path / "model_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-compound.v1",
                "product_id": "test-product",
                "model_id": "test-model",
                "atom_map": ["1:C", "1:N", "1:H"],
                "charge": 0,
                "outputs": {
                    "graph": {"path": str(graph), "sha256": _sha256(graph)}
                },
            }
        )
    )
    parameters = tmp_path / "model.prm"
    parameters.write_text(
        "BONDS\nCT NT 100.0 1.4\nNT HT 100.0 1.0\n"
        "ANGLES\nCT NT HT 50.0 120.0\n"
        "DIHEDRALS\nX CT NT X 0.1 3 0.0\n"
    )
    fit = tmp_path / "fit.json"
    fit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1",
                "product_id": "test-product",
                "model_id": "test-model",
                "source_records": {
                    "cgenff_parameters": {"sha256": _sha256(parameters)}
                },
                "results": [
                    {
                        "hypothesis_id": "explicit-types",
                        "atom_types": {"1:C": "CT", "1:N": "NT", "1:H": "HT"},
                        "charges_e": {"1:C": 0.1, "1:N": -0.2, "1:H": 0.1},
                    }
                ],
            }
        )
    )
    output = tmp_path / "coverage.json"

    report = audit_model_graph_parameter_coverage(
        model_manifest_path=manifest,
        nonbonded_fit_path=fit,
        hypothesis_id="explicit-types",
        cgenff_parameters_path=parameters,
        output_path=output,
    )

    assert report["status"] == "coverage_audit_complete_not_releasable"
    assert report["gate_effect"] == "none"
    assert report["total_missing_terms"] == 0
    assert report["categories"]["bonds"]["exact_count"] == 2
    assert report["categories"]["angles"]["exact_count"] == 1
    assert report["categories"]["dihedrals"]["term_count"] == 0
    assert report["sources"]["model_graph"]["sha256"] == _sha256(graph)


def test_complete_model_graph_coverage_rejects_stale_bond_identity(tmp_path: Path):
    graph = tmp_path / "model_graph.json"
    graph.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-graph.v1",
                "atom_count": 2,
                "bond_count": 1,
                "formal_charge": 0,
                "atoms": [
                    {"index": 0, "key": "1:C", "element": "C", "formal_charge": 0},
                    {"index": 1, "key": "1:N", "element": "N", "formal_charge": 0},
                ],
                "bonds": [
                    {"atoms": ["1:N", "1:C"], "indices": [0, 1], "order": 1.0}
                ],
            }
        )
    )
    manifest = tmp_path / "model_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-compound.v1",
                "product_id": "test-product",
                "model_id": "test-model",
                "atom_map": ["1:C", "1:N"],
                "charge": 0,
                "outputs": {
                    "graph": {"path": str(graph), "sha256": _sha256(graph)}
                },
            }
        )
    )
    fit = tmp_path / "fit.json"
    fit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1",
                "product_id": "test-product",
                "model_id": "test-model",
            }
        )
    )
    parameters = tmp_path / "model.prm"
    parameters.write_text("BONDS\nC N 1.0 1.0\n")

    with pytest.raises(ValueError, match="invalid or stale bond"):
        audit_model_graph_parameter_coverage(
            model_manifest_path=manifest,
            nonbonded_fit_path=fit,
            hypothesis_id="unused",
            cgenff_parameters_path=parameters,
            output_path=tmp_path / "coverage.json",
        )
