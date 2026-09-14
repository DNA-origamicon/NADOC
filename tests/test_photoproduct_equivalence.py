import hashlib
import json

import numpy as np
import pytest

from backend.parameterization.photoproduct_equivalence import (
    _proper_rotation_fit,
    audit_endpoint_exchange_equivalence,
    build_equivalent_hessian_reference,
)
from backend.parameterization.photoproduct_qm import QM_PROTOCOL_PATH


def _write_job(root, product_id, coordinates, *, energy):
    root.mkdir()
    atom_map = ["1:C5", "1:H6", "2:C5", "2:H6"]
    xyz = root / "optimized.xyz"
    xyz.write_text(
        "4\noptimized\n"
        + "\n".join(
            f"{element} {x:.9f} {y:.9f} {z:.9f}"
            for element, (x, y, z) in zip(
                ("C", "H", "C", "H"), coordinates, strict=True
            )
        )
        + "\n"
    )
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "job_kind": "geometry_optimization",
        "product_id": product_id,
        "model_id": f"n1-methyl-{product_id}",
        "method": "mp2",
        "basis": "6-31G(d)",
        "charge": 0,
        "multiplicity": 1,
        "protocol_version": "1.4.0",
        "protocol_sha256": hashlib.sha256(
            QM_PROTOCOL_PATH.with_name(
                "photoproduct_qm_protocol_v1.4.0.json"
            ).read_bytes()
        ).hexdigest(),
        "atom_map": atom_map,
    }
    job_path = root / "job_manifest.json"
    job_path.write_text(json.dumps(job))
    audit = {
        "schema": "nadoc.photoproduct-optimized-model-audit.v1",
        "status": "passed_candidate_identity_and_chirality",
        "product_id": product_id,
        "model_id": job["model_id"],
        "final_energy_hartree": energy,
        "optimized_xyz": {
            "path": str(xyz.resolve()),
            "sha256": hashlib.sha256(xyz.read_bytes()).hexdigest(),
        },
    }
    (root / "optimized_model_audit.json").write_text(json.dumps(audit))


def _independent_audit(
    path,
    *,
    second_identifier="SAME",
    product_ids=("tt-cpd-a", "tt-cpd-b"),
):
    path.write_text(
        json.dumps(
            {
                "schema": "nadoc.tt-cpd-openbabel-stereo-audit.v1",
                "passed": True,
                "records": [
                    {
                        "product_id": product_ids[0],
                        "inchikey": "SAME",
                        "canonical_isomeric_smiles": "same",
                    },
                    {
                        "product_id": product_ids[1],
                        "inchikey": second_identifier,
                        "canonical_isomeric_smiles": "same",
                    },
                ],
            }
        )
    )


def test_proper_rotation_fit_never_uses_reflection():
    reference = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    reflected = reference.copy()
    reflected[:, 0] *= -1
    rmsd, _maximum, determinant = _proper_rotation_fit(reference, reflected)
    assert determinant == pytest.approx(1.0)
    assert rmsd > 0.1


def test_endpoint_exchange_equivalence_is_hash_linked_and_narrowly_scoped(tmp_path):
    first_coordinates = np.asarray(
        [[0, 0, 0], [0, 0, 1], [2, 0, 0], [2, 1, 0]], dtype=float
    )
    # Exchange endpoint atom rows, apply a proper z rotation, and translate.
    exchanged = first_coordinates[[2, 3, 0, 1]]
    rotation = np.asarray([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    second_coordinates = exchanged @ rotation + np.asarray([4, -3, 2])
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_job(first, "tt-cpd-a", first_coordinates, energy=-10.0)
    _write_job(second, "tt-cpd-b", second_coordinates, energy=-10.0 + 1e-9)
    independent = tmp_path / "openbabel.json"
    _independent_audit(independent)

    report = audit_endpoint_exchange_equivalence(
        first_job_dir=first,
        second_job_dir=second,
        independent_stereo_audit_path=independent,
        output_path=tmp_path / "equivalence.json",
    )
    assert report["passed"] is True
    assert report["reflection_used"] is False
    assert report["heavy_atom_rmsd_angstrom"] < 1e-8
    assert report["gate_effect"] == "none"
    assert "does not assert" in report["reuse_precondition"]
    assert "coordinate-template interchangeability" in report["not_established"]


def test_endpoint_exchange_accepts_only_a_hash_identical_relocated_xyz(tmp_path):
    coordinates = np.asarray(
        [[0, 0, 0], [0, 0, 1], [2, 0, 0], [2, 1, 0]], dtype=float
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_job(first, "tt-cpd-a", coordinates, energy=-10.0)
    _write_job(second, "tt-cpd-b", coordinates[[2, 3, 0, 1]], energy=-10.0)
    first_audit_path = first / "optimized_model_audit.json"
    first_audit = json.loads(first_audit_path.read_text())
    first_audit["optimized_xyz"]["path"] = "/missing/original/optimized.xyz"
    first_audit_path.write_text(json.dumps(first_audit))
    independent = tmp_path / "openbabel.json"
    _independent_audit(independent)

    report = audit_endpoint_exchange_equivalence(
        first_job_dir=first,
        second_job_dir=second,
        independent_stereo_audit_path=independent,
        output_path=tmp_path / "equivalence.json",
    )
    first_xyz = report["optimization_evidence"][0]["optimized_xyz"]
    assert first_xyz["relocated"] is True
    assert first_xyz["declared_path"] == "/missing/original/optimized.xyz"
    assert first_xyz["path"] == str((first / "optimized.xyz").resolve())

    (first / "optimized.xyz").write_text("changed\n")
    with pytest.raises(ValueError, match="missing or hash-mismatched"):
        audit_endpoint_exchange_equivalence(
            first_job_dir=first,
            second_job_dir=second,
            independent_stereo_audit_path=independent,
            output_path=tmp_path / "changed-equivalence.json",
        )


def test_endpoint_exchange_requires_matching_independent_identifier(tmp_path):
    coordinates = np.asarray(
        [[0, 0, 0], [0, 0, 1], [2, 0, 0], [2, 1, 0]], dtype=float
    )
    _write_job(tmp_path / "first", "tt-cpd-a", coordinates, energy=-10.0)
    _write_job(
        tmp_path / "second",
        "tt-cpd-b",
        coordinates[[2, 3, 0, 1]],
        energy=-10.0,
    )
    independent = tmp_path / "openbabel.json"
    _independent_audit(independent, second_identifier="DIFFERENT")
    with pytest.raises(ValueError, match="identifiers"):
        audit_endpoint_exchange_equivalence(
            first_job_dir=tmp_path / "first",
            second_job_dir=tmp_path / "second",
            independent_stereo_audit_path=independent,
            output_path=tmp_path / "equivalence.json",
        )


def test_equivalent_hessian_reference_relabels_keys_without_copy_or_rotation(tmp_path):
    coordinates = np.asarray(
        [[0, 0, 0], [0, 0, 1], [2, 0, 0], [2, 1, 0]], dtype=float
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_job(first, "tt-cpd-cis-syn", coordinates, energy=-10.0)
    _write_job(
        second,
        "tt-cpd-cis-syn-ii",
        coordinates[[2, 3, 0, 1]],
        energy=-10.0,
    )
    independent = tmp_path / "openbabel.json"
    _independent_audit(
        independent,
        product_ids=("tt-cpd-cis-syn", "tt-cpd-cis-syn-ii"),
    )
    equivalence_path = tmp_path / "equivalence.json"
    audit_endpoint_exchange_equivalence(
        first_job_dir=first,
        second_job_dir=second,
        independent_stereo_audit_path=independent,
        output_path=equivalence_path,
    )

    frequency = tmp_path / "frequency"
    frequency.mkdir()
    first_job = json.loads((first / "job_manifest.json").read_text())
    atom_map = first_job["atom_map"]
    source_xyz = first / "optimized.xyz"
    (frequency / "job_manifest.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-qm-job.v1",
                "job_kind": "frequency",
                "product_id": "tt-cpd-cis-syn",
                "model_id": first_job["model_id"],
                "atom_count": len(atom_map),
                "atom_map": atom_map,
                "source_xyz": {
                    "path": str(source_xyz),
                    "sha256": hashlib.sha256(source_xyz.read_bytes()).hexdigest(),
                },
            }
        )
    )
    dimension = 3 * len(atom_map)
    hessian = frequency / "hessian_hartree_per_bohr2.txt"
    hessian.write_text(
        "\n".join(
            " ".join("1.0" if row == column else "0.0" for column in range(dimension))
            for row in range(dimension)
        )
        + "\n"
    )
    (frequency / "frequency_audit.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-audit.v1",
                "status": "passed_candidate_harmonic_minimum",
                "product_id": "tt-cpd-cis-syn",
                "model_id": first_job["model_id"],
                "imaginary_mode_count": 0,
                "cartesian_hessian": {
                    "status": "passed",
                    "units": "hartree/bohr^2",
                    "sha256": hashlib.sha256(hessian.read_bytes()).hexdigest(),
                },
            }
        )
    )

    report = build_equivalent_hessian_reference(
        source_frequency_job_dir=frequency,
        equivalence_audit_path=equivalence_path,
        target_product_id="tt-cpd-cis-syn-ii",
        output_path=tmp_path / "equivalent-hessian.json",
    )

    assert report["status"] == "passed_candidate_reuse_preconditions"
    assert report["gate_effect"] == "none"
    assert report["coordinate_frame"] == "source-retained-no-tensor-rotation"
    assert report["source_atom_map"] == ["1:C5", "1:H6", "2:C5", "2:H6"]
    assert report["target_atom_map_in_source_matrix_order"] == [
        "2:C5",
        "2:H6",
        "1:C5",
        "1:H6",
    ]
    assert report["source_frequency"]["cartesian_hessian"]["path"] == str(
        hessian.resolve()
    )
    assert not (tmp_path / "equivalent-hessian_hessian.txt").exists()

    hessian.write_text("changed\n")
    with pytest.raises(ValueError, match="passed harmonic minimum"):
        build_equivalent_hessian_reference(
            source_frequency_job_dir=frequency,
            equivalence_audit_path=equivalence_path,
            target_product_id="tt-cpd-cis-syn-ii",
            output_path=tmp_path / "changed-reference.json",
        )
