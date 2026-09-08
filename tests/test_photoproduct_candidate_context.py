from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import resolve_base_keys
from backend.parameterization.photoproduct_candidate_context import (
    _candidate_asset,
    _candidate_coordinate_template,
    _local_constraint_pdb,
    _pdb_with_coordinates,
    _require_under,
    build_duplex_context,
    build_reciprocal_crossover_1xt_context,
)


def test_context_candidate_asset_is_hash_pinned_and_confined(tmp_path):
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    topology = candidate_dir / "photoproduct.rtf"
    topology.write_text("* synthetic topology\n")
    digest = hashlib.sha256(topology.read_bytes()).hexdigest()
    manifest_path = candidate_dir / "candidate_manifest.json"
    manifest_path.write_text("{}\n")
    manifest = {"assets": {"topology": {"path": topology.name, "sha256": digest}}}

    assert _candidate_asset(manifest_path, manifest, "topology") == topology.resolve()

    manifest["assets"]["topology"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash-mismatched"):
        _candidate_asset(manifest_path, manifest, "topology")

    manifest["assets"]["topology"] = {
        "path": "../outside.rtf",
        "sha256": digest,
    }
    with pytest.raises(ValueError, match="escapes"):
        _candidate_asset(manifest_path, manifest, "topology")


def test_context_output_must_stay_under_declared_storage_root(tmp_path):
    storage = tmp_path / "archive"
    storage.mkdir()
    assert (
        _require_under(storage / "evidence", storage)
        == (storage / "evidence").resolve()
    )
    with pytest.raises(ValueError, match="outside the storage root"):
        _require_under(tmp_path / "elsewhere", storage)


def test_reciprocal_fixture_has_two_resolvable_extra_thymines_on_distinct_strands():
    design = build_reciprocal_crossover_1xt_context(stereochemistry="trans-anti-II")
    model = build_atomistic_model(design)
    lesion = design.photoproduct_junctions[0]
    resolved, errors = resolve_base_keys(
        design,
        [lesion.base_key_1, lesion.base_key_2],
        atomistic_model=model,
    )

    assert errors == []
    assert [endpoint.base for endpoint in resolved] == ["T", "T"]
    assert [endpoint.source_class for endpoint in resolved] == [
        "crossover-extra",
        "crossover-extra",
    ]
    assert resolved[0].strand_id != resolved[1].strand_id
    assert lesion.stereochemistry == "trans-anti-II"


@pytest.mark.parametrize(
    ("relationship", "same_strand"),
    [("adjacent-intrastrand", True), ("antiparallel-interstrand", False)],
)
def test_duplex_contexts_resolve_ordered_native_thymines(relationship, same_strand):
    design = build_duplex_context(
        stereochemistry="cis-anti-I", relationship=relationship
    )
    model = build_atomistic_model(design)
    lesion = design.photoproduct_junctions[0]
    resolved, errors = resolve_base_keys(
        design,
        [lesion.base_key_1, lesion.base_key_2],
        atomistic_model=model,
    )
    assert errors == []
    assert [endpoint.base for endpoint in resolved] == ["T", "T"]
    assert [endpoint.source_class for endpoint in resolved] == ["ordinary", "ordinary"]
    assert (resolved[0].strand_id == resolved[1].strand_id) is same_strand


def test_candidate_template_requires_hash_linked_qm_minimum(tmp_path):
    atom_map = [
        f"{endpoint}:{name}"
        for endpoint in (1, 2)
        for name in (
            "C1'",
            "N1",
            "C2",
            "O2",
            "N3",
            "C4",
            "O4",
            "C5",
            "C6",
            "C7",
            "H6",
        )
    ]
    atom_map.extend(f"1:X{index}" for index in range(41))
    xyz = tmp_path / "optimized.xyz"
    xyz.write_text(
        "63\nsynthetic hash-link fixture\n"
        + "\n".join(f"C {index * 0.01:.4f} 0.0 0.0" for index in range(63))
        + "\n"
    )
    atom_map_path = tmp_path / "atom_map.json"
    atom_map_path.write_text(json.dumps(atom_map) + "\n")
    optimization_audit = tmp_path / "optimization_audit.json"
    frequency_audit = tmp_path / "frequency_audit.json"
    optimization_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "tt-cpd-cis-syn",
                "chirality_audit": {"passed": True},
            }
        )
        + "\n"
    )
    frequency_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-audit.v1",
                "status": "passed_harmonic_minimum",
                "product_id": "tt-cpd-cis-syn",
                "imaginary_mode_count": 0,
            }
        )
        + "\n"
    )

    def source(path):
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    boundary = {
        "atom_map": atom_map,
        "outputs": {"xyz": source(xyz), "atom_map": source(atom_map_path)},
    }
    release = {
        "product_id": "tt-cpd-cis-syn",
        "product": "TT-CPD",
        "stereochemistry": "cis-syn",
        "sources": {
            "optimized_xyz": source(xyz),
            "optimization_audit": source(optimization_audit),
            "frequency_audit": source(frequency_audit),
        },
    }
    policy = json.loads(
        open(
            "backend/data/forcefield/photoproduct_context_precondition_policy.json"
        ).read()
    )
    template = _candidate_coordinate_template(
        boundary=boundary,
        qm_release=release,
        parameter_sha256="a" * 64,
        policy=policy,
    )
    assert template["release_status"] == "candidate_validation_only"
    assert template["reflection_allowed"] is False
    assert template["provenance"]["optimized_xyz_sha256"] == source(xyz)["sha256"]
    assert len(template["placement_safety"]["product_ring_bond_ranges_angstrom"]) == 4

    xyz.write_text(xyz.read_text().replace("0.0000", "0.0001", 1))
    with pytest.raises(ValueError, match="boundary XYZ is missing or hash-mismatched"):
        _candidate_coordinate_template(
            boundary=boundary,
            qm_release=release,
            parameter_sha256="a" * 64,
            policy=policy,
        )


def test_local_constraint_pdb_marks_only_endpoint_neighborhood_mobile(tmp_path):
    pdb = tmp_path / "context.pdb"
    lines = []
    for resid in range(1, 7):
        lines.append(
            f"ATOM  {resid:5d} C1'  THY A{resid:4d}    "
            f"{float(resid):8.3f}{0.0:8.3f}{0.0:8.3f}"
            f"{1.0:6.2f}{0.0:6.2f}      {'D000':>4}  C"
        )
    pdb.write_text("\n".join([*lines, "END", ""]))
    output, mobile = _local_constraint_pdb(
        pdb,
        [{"segid": "D000", "resid": "3"}],
        residue_radius=1,
        restraint_k=10.0,
    )
    atom_lines = [line for line in output.splitlines() if line.startswith("ATOM")]
    assert mobile.tolist() == [False, True, True, True, False, False]
    assert [float(line[60:66]) for line in atom_lines] == [
        10.0,
        0.0,
        0.0,
        0.0,
        10.0,
        10.0,
    ]
    moved = _pdb_with_coordinates(
        pdb,
        np.asarray([[float(index), 1.25, -2.5] for index in range(6)]),
    )
    moved_atoms = [line for line in moved.splitlines() if line.startswith("ATOM")]
    assert [float(value) for value in moved_atoms[4][30:54].split()] == [
        4.0,
        1.25,
        -2.5,
    ]
