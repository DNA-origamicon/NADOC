import hashlib
import json
import math
from pathlib import Path

import numpy as np

import backend.parameterization.photoproduct_bonded_fit_plan as plan_module
from backend.parameterization.photoproduct_bonded_fit_plan import (
    _central_bond_context,
    _dihedral,
    build_bonded_fit_plan,
)
from backend.parameterization.photoproduct_terms import enumerate_graph_terms


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_central_bond_context_separates_ring_and_relaxed_scan_targets():
    chain = [
        {"atoms": ["A", "B"], "order": 1.0},
        {"atoms": ["B", "C"], "order": 1.0},
        {"atoms": ["C", "D"], "order": 1.0},
    ]
    ring = [*chain, {"atoms": ["D", "A"], "order": 1.0}]

    assert _central_bond_context(["A", "B", "C", "D"], chain) == {
        "central_bond": ["B", "C"],
        "central_bond_order": 1.0,
        "central_bond_in_cycle": False,
        "target_class": "relaxed_torsion_scan_candidate",
    }
    assert _central_bond_context(["A", "B", "C", "D"], ring)[
        "target_class"
    ] == "coupled_ring_response_no_independent_scan"


def test_dihedral_matches_openmm_namd_four_atom_convention():
    points = [
        np.asarray(value, dtype=float)
        for value in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1))
    ]

    assert _dihedral(*points) == 90.0


def test_dihedral_reproduces_real_namd_improper_fixture_energy():
    points = [
        np.asarray(value, dtype=float)
        for value in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    ]
    angle = _dihedral(*points)
    energy = 10.0 * math.radians(angle - 30.0) ** 2

    assert math.isclose(angle, 54.735610317245346, abs_tol=1.0e-12)
    assert math.isclose(energy, 1.8638029555548583, abs_tol=1.0e-12)


def test_bonded_fit_plan_joins_graph_hessian_coverage_and_stereochemistry(
    tmp_path: Path, monkeypatch
):
    keys = ["1:C", "1:A", "1:B", "1:D"]
    graph = tmp_path / "graph.json"
    graph_payload = {
        "schema": "nadoc.photoproduct-model-graph.v1",
        "atom_count": 4,
        "bond_count": 3,
        "formal_charge": 0,
        "atoms": [
            {
                "index": index,
                "key": key,
                "element": "C",
                "formal_charge": 0,
                "aromatic": False,
            }
            for index, key in enumerate(keys)
        ],
        "bonds": [
            {"atoms": ["1:C", key], "indices": [0, index], "order": 1.0}
            for index, key in enumerate(keys[1:], start=1)
        ],
    }
    graph.write_text(json.dumps(graph_payload))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-compound.v1",
                "product_id": "test-product",
                "model_id": "test-model",
                "atom_map": keys,
                "outputs": {"graph": {"path": str(graph), "sha256": _sha256(graph)}},
            }
        )
    )
    geometry = tmp_path / "optimized.xyz"
    geometry.write_text(
        "4\ntest\nC 0 0 0\nC 1 0 0\nC 0 1 0\nC 0 0 1\n"
    )
    hessian = tmp_path / "hessian.txt"
    np.savetxt(hessian, np.eye(12))
    targets = tmp_path / "targets.json"
    targets.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-hessian-target-bundle.v1",
                "product_id": "test-product",
                "model_id": "test-model",
                "atom_map": keys,
                "source_geometry": {
                    "path": str(geometry),
                    "sha256": _sha256(geometry),
                },
                "cartesian_hessian": {
                    "path": str(hessian),
                    "sha256": _sha256(hessian),
                    "dimension": 12,
                },
            }
        )
    )
    graph_terms = enumerate_graph_terms(
        [record["atoms"] for record in graph_payload["bonds"]]
    )
    categories = {}
    for category, paths in graph_terms.items():
        categories[category] = {
            "terms": [
                {
                    "atoms": path,
                    "types": [f"T{keys.index(key)}" for key in path],
                    "coverage": "missing",
                    "matches": [],
                }
                for path in paths
            ]
        }
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-parameter-coverage-audit.v1",
                "product_id": "test-product",
                "model_id": "test-model",
                "hypothesis_id": "explicit-types",
                "sources": {
                    "model_manifest": {"sha256": _sha256(manifest)}
                },
                "categories": categories,
            }
        )
    )
    convention = tmp_path / "convention.json"
    convention.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-namd-improper-convention-audit.v1",
                "status": "passed_convention_only",
                "passed": True,
                "product_parameter_authority": False,
            }
        )
    )
    monkeypatch.setattr(
        plan_module,
        "photoproduct_registry",
        lambda: {
            "products": [
                {
                    "id": "test-product",
                    "product": "TEST",
                    "stereochemistry": "hand-1",
                }
            ]
        },
    )
    monkeypatch.setattr(
        plan_module,
        "load_chemical_definition",
        lambda *_: {
            "id": "test-product",
            "product_stereocenters": [
                {
                    "atom": "1:C",
                    "signed_volume_reference_atoms": ["1:A", "1:B", "1:D"],
                    "expected_signed_volume": "positive",
                }
            ],
        },
    )
    monkeypatch.setattr(
        plan_module,
        "chemical_definition_asset",
        lambda *_: {"path": "definition.json", "sha256": "a" * 64},
    )

    report = build_bonded_fit_plan(
        model_manifest_path=manifest,
        hessian_targets_path=targets,
        model_coverage_path=coverage,
        improper_convention_audit_path=convention,
        output_path=tmp_path / "plan.json",
    )

    assert report["status"] == "candidate_plan_unassigned_not_releasable"
    assert report["gate_effect"] == "none"
    assert report["cartesian_hessian_dimension"] == 12
    assert report["dihedral_convention"] == "openmm_namd_four_atom_atan2_v1"
    assert all(
        value is None
        for group in report["uncovered_parameter_groups"]
        for value in group["variables"].values()
    )
    assert report["stereochemical_impropers"][0]["observed_signed_volume"] > 0
    assert report["stereochemical_impropers"][0]["variables"] == {
        "k_kcal_mol_rad2": None,
        "psi0_degrees": None,
    }
