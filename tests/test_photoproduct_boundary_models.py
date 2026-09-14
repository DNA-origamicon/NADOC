import hashlib
import json

import numpy as np
import pytest

from backend.parameterization.photoproduct_models import (
    _expected_boundary_bond_orders,
    _mmcif_loop_rows,
    _proper_rotation_fit,
    audit_dna_boundary_model_replicates,
    materialize_reviewed_dna_boundary_model,
)


def _candidate(tmp_path, name, coordinates):
    item_dir = tmp_path / name
    item_dir.mkdir()
    atom_map = ["1:C5", "2:C5", "1:C1'", "2:P"]
    elements = ["C", "C", "C", "P"]
    xyz = item_dir / "candidate.xyz"
    xyz.write_text(
        "4\ntest boundary\n"
        + "\n".join(
            f"{element} {x} {y} {z}"
            for element, (x, y, z) in zip(elements, coordinates, strict=True)
        )
        + "\n"
    )
    atom_map_path = item_dir / "atom_map.json"
    atom_map_path.write_text(json.dumps(atom_map))
    sdf = item_dir / "candidate.sdf"
    sdf.write_text("test boundary SDF\n")
    manifest = {
        "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        "status": "candidate_pending_cap_review",
        "gate_effect": "none",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-boundary-model",
        "chirality_audit": {"passed": True},
        "source_selection": {"copy": name, "chain": name},
        "outputs": {
            "xyz": {
                "path": str(xyz),
                "sha256": hashlib.sha256(xyz.read_bytes()).hexdigest(),
            },
            "atom_map": {
                "path": str(atom_map_path),
                "sha256": hashlib.sha256(atom_map_path.read_bytes()).hexdigest(),
            },
            "sdf": {
                "path": str(sdf),
                "sha256": hashlib.sha256(sdf.read_bytes()).hexdigest(),
            },
        },
        "release_blockers": [
            "independent review of atom map, phosphate resonance choice, and terminal caps",
            "QM optimization and validation",
        ],
    }
    path = item_dir / "candidate_manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_simple_mmcif_loop_parser_preserves_quoted_atom_ids(tmp_path):
    path = tmp_path / "small.cif"
    path.write_text(
        "loop_\n_atom_site.id\n_atom_site.auth_atom_id\n"
        "1 \"C1'\"\n2 C5\n#\n"
    )
    assert _mmcif_loop_rows(path, "atom_site") == [
        {"_atom_site.id": "1", "_atom_site.auth_atom_id": "C1'"},
        {"_atom_site.id": "2", "_atom_site.auth_atom_id": "C5"},
    ]


def test_boundary_replicate_audit_uses_proper_rotation_without_mirroring(tmp_path):
    reference = _candidate(
        tmp_path,
        "reference",
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
    )
    # A rigid proper rotation plus translation must align to numerical precision.
    mobile = _candidate(
        tmp_path,
        "mobile",
        [(5, 2, -1), (5, 3, -1), (4, 2, -1), (5, 2, 0)],
    )
    report = audit_dna_boundary_model_replicates(
        manifest_paths=[reference, mobile], output_path=tmp_path / "audit.json"
    )
    comparison = report["comparisons"][0]
    assert report["gate_effect"] == "none"
    assert comparison["reflection_used"] is False
    assert comparison["proper_rotation_determinant"] == pytest.approx(1.0)
    assert comparison["all_heavy_rmsd_angstrom"] == pytest.approx(0.0, abs=1e-12)


def test_boundary_product_graft_fit_is_proper_and_non_reflective():
    source = np.asarray(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], dtype=float
    )
    target = np.asarray(
        [(5, 2, -1), (5, 3, -1), (4, 2, -1), (5, 2, 0)], dtype=float
    )

    rotation, translation, rmsd = _proper_rotation_fit(source, target)

    fitted = (rotation @ source.T).T + translation
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    assert rmsd == pytest.approx(0.0, abs=1e-12)
    assert fitted == pytest.approx(target, abs=1e-12)


def test_boundary_expected_graph_uses_selected_syn_or_anti_crosslinks():
    definition = {
        "graph_delta": {
            "bonds_added": [
                {"atom_1": "1:C5", "atom_2": "2:C5", "order": "single"},
                {"atom_1": "1:C6", "atom_2": "2:C6", "order": "single"},
            ]
        }
    }
    syn = _expected_boundary_bond_orders(definition)
    anti_definition = json.loads(json.dumps(definition))
    anti_definition["graph_delta"]["bonds_added"] = [
        {"atom_1": "1:C5", "atom_2": "2:C6", "order": "single"},
        {"atom_1": "1:C6", "atom_2": "2:C5", "order": "single"},
    ]
    anti = _expected_boundary_bond_orders(anti_definition)

    assert tuple(sorted(("1:C5", "2:C5"))) in syn
    assert tuple(sorted(("1:C6", "2:C6"))) in syn
    assert tuple(sorted(("1:C5", "2:C6"))) in anti
    assert tuple(sorted(("1:C6", "2:C5"))) in anti
    assert set(syn) != set(anti)


def test_boundary_visual_approval_materializes_hash_pinned_review(tmp_path):
    candidate_path = _candidate(
        tmp_path,
        "B",
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
    )
    candidate = json.loads(candidate_path.read_text())
    visual_path = tmp_path / "visual.json"
    visual_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-visual-review-decisions.v1",
                "simulation_ready": False,
                "gate_effect": "none",
                "decisions": [
                    {
                        "stage": "dna_boundary_model",
                        "product_id": "tt-cpd-cis-syn",
                        "conformer_id": "chain-b",
                        "decision": "approve",
                        "partition": None,
                        "reviewer": "Jojo Reviewer",
                        "reviewed_at": "2026-09-05T12:00:00-06:00",
                        "notes": "Caps, phosphate, charge, and atom mapping look consistent.",
                        "source_geometry_sha256": candidate["outputs"]["xyz"]["sha256"],
                    }
                ],
            }
        )
    )
    output = tmp_path / "reviewed-boundary.json"
    reviewed = materialize_reviewed_dna_boundary_model(
        candidate_manifest_path=candidate_path,
        visual_decisions_path=visual_path,
        output_path=output,
    )
    assert reviewed["status"] == "human_cap_review_complete"
    assert reviewed["simulation_ready"] is False
    assert reviewed["cap_review"]["decision"] == "APPROVE"
    assert all("cap" not in item.lower() for item in reviewed["release_blockers"])
