"""Coupled ring-conformer review and fixed-geometry QM job tests."""

from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from pathlib import Path
import subprocess

import numpy as np
import pytest

from backend.core.photoproduct_chemistry import signed_tetrahedron_volume
from backend.parameterization.photoproduct_coupled_conformer import (
    apply_coupled_conformer_review_decisions,
    audit_fixed_geometry_hessian_result,
    audit_reviewed_coupled_conformer_plan,
    build_fixed_geometry_hessian_target_bundle,
    build_coupled_conformer_review_index,
    build_coupled_conformer_review_decision_template,
    build_coupled_conformer_review_template,
    build_coupled_conformer_review_visualization,
    generate_fixed_geometry_hessian_job,
    materialize_quantitatively_screened_coupled_conformer_plan,
    validate_reviewed_coupled_conformer_plan,
)
from backend.parameterization.photoproduct_conformer_candidates import (
    build_coupled_conformer_candidates,
    build_coupled_conformer_mode_source,
)
from backend.parameterization.photoproduct_distributed_response import (
    prepare_distributed_fixed_geometry_hessian,
)
from scripts.photoproduct_workflow import _enforce_storage_root, _parser


KEYS = ["A", "B", "C", "D", "E", "F", "G", "H"]
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "scripts/photoproduct_workflow.py"
QM_PYTHON = Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python")
REFERENCE = np.asarray(
    [
        [0.0, 0.0, 0.0],
        [1.5, 0.0, 0.0],
        [0.2, 1.4, 0.2],
        [0.1, 0.3, 1.4],
        [2.8, 0.2, 0.4],
        [0.4, 2.7, 0.6],
        [-0.8, 0.5, 2.5],
        [0.5, -0.7, 2.5],
    ]
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _xyz(path: Path, coordinates: np.ndarray) -> None:
    path.write_text(
        f"{len(coordinates)}\nsynthetic coupled conformer fixture\n"
        + "\n".join(f"C {x:.10f} {y:.10f} {z:.10f}" for x, y, z in coordinates)
        + "\n"
    )


def _fixtures(tmp_path: Path) -> dict[str, Path]:
    reference = tmp_path / "reference.xyz"
    first = tmp_path / "first.xyz"
    second = tmp_path / "second.xyz"
    _xyz(reference, REFERENCE)
    first_xyz = REFERENCE.copy()
    first_xyz[2, 2] += 0.08
    _xyz(first, first_xyz)
    second_xyz = REFERENCE.copy()
    second_xyz[3, 0] += 0.09
    _xyz(second, second_xyz)
    stable_map = tmp_path / "stable_map.json"
    stable_map.write_text(json.dumps(KEYS) + "\n")
    bonds = [
        ("A", "B"),
        ("B", "C"),
        ("C", "D"),
        ("D", "A"),
        ("A", "E"),
        ("B", "F"),
        ("C", "G"),
        ("D", "H"),
    ]
    graph = tmp_path / "model_graph.json"
    graph.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-graph.v1",
                "atom_count": len(KEYS),
                "bond_count": len(bonds),
                "formal_charge": 0,
                "atoms": [
                    {
                        "index": index,
                        "key": key,
                        "element": "C",
                        "formal_charge": 0,
                        "aromatic": False,
                    }
                    for index, key in enumerate(KEYS)
                ],
                "bonds": [
                    {
                        "atoms": list(pair),
                        "indices": [KEYS.index(item) for item in pair],
                        "order": 1.0,
                        "aromatic": False,
                    }
                    for pair in bonds
                ],
            }
        )
        + "\n"
    )
    coordinate_map = {
        key: point.tolist() for key, point in zip(KEYS, REFERENCE, strict=True)
    }
    center_specs = [
        ("A", ["B", "D", "E"]),
        ("B", ["A", "C", "F"]),
        ("C", ["B", "D", "G"]),
        ("D", ["C", "A", "H"]),
    ]
    stereochemistry = tmp_path / "stereochemistry.json"
    stereochemistry.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-chemical-definition.v1",
                "id": "tt-cpd-fixture",
                "product_stereocenters": [
                    {
                        "atom": center,
                        "signed_volume_reference_atoms": refs,
                        "expected_signed_volume": (
                            "positive"
                            if signed_tetrahedron_volume(coordinate_map, center, refs)
                            > 0
                            else "negative"
                        ),
                    }
                    for center, refs in center_specs
                ],
            }
        )
        + "\n"
    )
    optimized_audit = tmp_path / "optimized_model_audit.json"
    optimized_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "gate_effect": "none",
                "product_id": "tt-cpd-fixture",
                "model_id": "fixture-model",
                "optimized_xyz": {
                    "path": str(reference),
                    "sha256": _sha256(reference),
                },
            }
        )
        + "\n"
    )
    return {
        "reference": reference,
        "first": first,
        "second": second,
        "stable_map": stable_map,
        "graph": graph,
        "stereochemistry": stereochemistry,
        "optimized_audit": optimized_audit,
    }


def _review(path: Path) -> dict:
    payload = json.loads(path.read_text())
    payload.update(
        {
            "status": "reviewed",
            "reviewed_by": "Qualified Test Reviewer",
            "reviewed_at": "2026-09-04T21:00:00Z",
            "review_rationale": (
                "The two proper-rotation structures preserve all four signed centers "
                "and provide separate coupled-distortion training and validation cases."
            ),
        }
    )
    for index, conformer in enumerate(payload["conformers"]):
        conformer["partition"] = "training" if index == 0 else "validation"
        conformer["review_decision"] = "accepted"
        conformer["review_notes"] = "Accepted synthetic coupled distortion fixture."
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def test_review_boundary_recomputes_geometry_and_generates_no_optimization_job(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    plan_path = tmp_path / "review_plan.json"
    report = build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=plan_path,
    )
    assert report["status"] == "review_required"
    assert all(item["chirality_audit"]["passed"] for item in report["conformers"])
    assert all(item["geometry_audit"]["passed"] for item in report["conformers"])
    with pytest.raises(ValueError, match="human review"):
        validate_reviewed_coupled_conformer_plan(plan_path)

    _review(plan_path)
    checked = validate_reviewed_coupled_conformer_plan(plan_path)
    assert {item["partition"] for item in checked["conformers"]} == {
        "training",
        "validation",
    }
    review_audit_path = tmp_path / "review_audit.json"
    review_audit = audit_reviewed_coupled_conformer_plan(
        plan_path=plan_path, output_path=review_audit_path
    )
    assert review_audit["status"] == "passed_human_review_structure"
    assert review_audit["gate_effect"] == "none"
    assert review_audit["counts"] == {
        "total": 2,
        "accepted": 2,
        "rejected": 0,
        "training": 1,
        "validation": 1,
    }
    assert review_audit["source_plan"]["sha256"] == _sha256(plan_path)

    job_dir = tmp_path / "fixed_hessian"
    manifest = generate_fixed_geometry_hessian_job(
        plan_path=plan_path,
        conformer_id="conformer-001",
        output_dir=job_dir,
        charge=0,
        memory_gib=4,
        threads=2,
    )
    rendered = (job_dir / "input.dat").read_text()
    assert manifest["job_kind"] == "fixed_geometry_hessian"
    assert manifest["protocol_version"] == "1.5.0"
    assert manifest["conformer"]["partition"] == "training"
    assert "hessian('mp2'" in rendered
    assert "gradient_hartree_per_bohr.txt" in rendered
    assert "optimize(" not in rendered

    (job_dir / "output.dat").write_text("synthetic completed fixed Hessian\n")
    dimension = 3 * len(KEYS)
    np.savetxt(job_dir / "gradient_hartree_per_bohr.txt", np.arange(dimension) / 1000.0)
    np.savetxt(job_dir / "hessian_hartree_per_bohr2.txt", np.eye(dimension))
    job_path = job_dir / "job_manifest.json"
    outputs = {}
    for name in (
        "output.dat",
        "gradient_hartree_per_bohr.txt",
        "hessian_hartree_per_bohr2.txt",
    ):
        path = job_dir / name
        outputs[name] = {"path": str(path), "sha256": _sha256(path)}
    (job_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-qm-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "job_manifest_sha256": _sha256(job_path),
                "parsed": {"final_energy_hartree": -152.125},
                "outputs": outputs,
            }
        )
        + "\n"
    )
    audit = audit_fixed_geometry_hessian_result(job_dir)
    assert audit["status"] == "passed_candidate_response_evidence"
    assert audit["cartesian_gradient"]["dimension"] == dimension
    assert audit["electronic_energy"] == {
        "value": -152.125,
        "units": "hartree",
        "geometry_sha256": _sha256(files["first"]),
    }
    target_path = tmp_path / "off_equilibrium_target.json"
    target = build_fixed_geometry_hessian_target_bundle(
        job_dir=job_dir, output_path=target_path
    )
    assert target["schema"] == "nadoc.photoproduct-hessian-target-bundle.v2"
    assert target["target_kind"] == "reviewed_off_equilibrium_conformer"
    assert target["simulation_ready"] is False
    assert target["electronic_energy"]["value"] == -152.125


def test_distributed_fixed_hessian_rejects_changed_input_before_qm_import(
    tmp_path: Path, monkeypatch
) -> None:
    files = _fixtures(tmp_path)
    plan_path = tmp_path / "review_plan.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=plan_path,
    )
    _review(plan_path)
    job_dir = tmp_path / "fixed_hessian"
    generate_fixed_geometry_hessian_job(
        plan_path=plan_path,
        conformer_id="conformer-001",
        output_dir=job_dir,
        charge=0,
    )
    (job_dir / "input.dat").write_text("changed\n")

    def unexpected_import():  # pragma: no cover - called only on regression
        raise AssertionError("QM stack should not be imported after a hash failure")

    monkeypatch.setattr(
        "backend.parameterization.photoproduct_distributed_response._require_qm_stack",
        unexpected_import,
    )
    with pytest.raises(ValueError, match="input digest"):
        prepare_distributed_fixed_geometry_hessian(
            job_dir=job_dir,
            output_dir=tmp_path / "distributed",
        )


def _hydrogen_qm_fixtures(tmp_path: Path) -> dict[str, Path]:
    """Make the review fixture cheap enough for a real transport integration test."""

    files = _fixtures(tmp_path)
    for name in ("reference", "first", "second"):
        path = files[name]
        lines = path.read_text().splitlines()
        path.write_text(
            "\n".join([*lines[:2], *("H" + line[1:] for line in lines[2:])]) + "\n"
        )
    graph = json.loads(files["graph"].read_text())
    for atom in graph["atoms"]:
        atom["element"] = "H"
    files["graph"].write_text(json.dumps(graph) + "\n")
    audit = json.loads(files["optimized_audit"].read_text())
    audit["optimized_xyz"]["sha256"] = _sha256(files["reference"])
    files["optimized_audit"].write_text(json.dumps(audit) + "\n")
    return files


@pytest.mark.slow
def test_real_psi4_distributed_fixed_hessian_round_trip(tmp_path: Path) -> None:
    if not QM_PYTHON.is_file():
        pytest.skip("pinned nadoc-qm Python is not installed")
    files = _hydrogen_qm_fixtures(tmp_path)
    plan_path = tmp_path / "review_plan.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=plan_path,
    )
    _review(plan_path)
    job_dir = tmp_path / "fixed_hessian"
    generate_fixed_geometry_hessian_job(
        plan_path=plan_path,
        conformer_id="conformer-001",
        output_dir=job_dir,
        charge=0,
        memory_gib=1,
        threads=1,
    )
    distributed = tmp_path / "distributed"

    def run(*arguments: str, timeout: int = 180) -> None:
        completed = subprocess.run(
            [
                str(QM_PYTHON),
                str(WORKFLOW),
                "--storage-root",
                str(tmp_path),
                *arguments,
            ],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    run(
        "prepare-distributed-fixed-hessian",
        "--job-dir",
        str(job_dir),
        "--output-dir",
        str(distributed),
    )
    distributed_plan_path = distributed / "distributed_hessian_plan.json"
    distributed_plan = json.loads(distributed_plan_path.read_text())
    assert distributed_plan["job_kind"] == "fixed_geometry_hessian"
    assert distributed_plan["protocol"]["job_key"] == "fixed_geometry_hessian"
    assert distributed_plan["conformer"]["partition"] == "training"
    assert distributed_plan["finite_difference"]["center_gradient_retained"] is True
    assert distributed_plan["task_count"] > 1
    for task in distributed_plan["tasks"]:
        run(
            "run-distributed-hessian-task",
            "--plan",
            str(distributed_plan_path),
            "--task-id",
            task["id"],
            "--scratch-dir",
            str(tmp_path / "scratch" / task["id"]),
            "--threads",
            "1",
            "--memory-gib",
            "1",
        )
    assembly_path = distributed / "distributed_fixed_hessian_audit.json"
    run(
        "assemble-distributed-fixed-hessian",
        "--job-dir",
        str(job_dir),
        "--plan",
        str(distributed_plan_path),
        "--output",
        str(assembly_path),
    )
    assembly = json.loads(assembly_path.read_text())
    assert assembly["status"] == "assembled_unreviewed_response"
    assert assembly["simulation_ready"] is False
    assert assembly["conformer_id"] == "conformer-001"
    dimension = 3 * len(KEYS)
    assert assembly["cartesian_gradient"]["dimension"] == dimension
    assert assembly["cartesian_hessian"]["dimension"] == dimension
    audit = audit_fixed_geometry_hessian_result(job_dir)
    assert audit["status"] == "passed_candidate_response_evidence"
    assert np.isfinite(audit["electronic_energy"]["value"])


def test_review_revalidates_rejected_geometry_but_excludes_it_from_qm(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    rejected = tmp_path / "rejected.xyz"
    rejected_xyz = REFERENCE.copy()
    rejected_xyz[4, 1] += 0.07
    _xyz(rejected, rejected_xyz)
    plan_path = tmp_path / "review_plan.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"], rejected],
        output_path=plan_path,
    )
    payload = _review(plan_path)
    payload["conformers"][2]["review_decision"] = "rejected"
    payload["conformers"][2]["partition"] = None
    payload["conformers"][2]["review_notes"] = (
        "Rejected because it does not add an independent response direction."
    )
    plan_path.write_text(json.dumps(payload, indent=2) + "\n")

    checked = validate_reviewed_coupled_conformer_plan(plan_path)
    assert [item["id"] for item in checked["conformers"]] == [
        "conformer-001",
        "conformer-002",
    ]
    with pytest.raises(ValueError, match="no unique conformer"):
        generate_fixed_geometry_hessian_job(
            plan_path=plan_path,
            conformer_id="conformer-003",
            output_dir=tmp_path / "must-not-exist",
            charge=0,
        )

    rejected.write_text(rejected.read_text().replace("0.2700000000", "0.4700000000"))
    payload["conformers"][2]["geometry"]["sha256"] = _sha256(rejected)
    plan_path.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(ValueError, match="stored audit differs from recomputation"):
        validate_reviewed_coupled_conformer_plan(plan_path)


def test_review_rejects_duplicate_geometry_records(tmp_path: Path) -> None:
    files = _fixtures(tmp_path)
    plan_path = tmp_path / "review_plan.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=plan_path,
    )
    payload = _review(plan_path)
    payload["conformers"][1]["geometry"] = dict(payload["conformers"][0]["geometry"])
    payload["conformers"][1]["chirality_audit"] = dict(
        payload["conformers"][0]["chirality_audit"]
    )
    payload["conformers"][1]["geometry_audit"] = dict(
        payload["conformers"][0]["geometry_audit"]
    )
    plan_path.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(ValueError, match="must remain distinct"):
        validate_reviewed_coupled_conformer_plan(plan_path)


def test_reviewed_plan_fails_closed_on_coordinate_or_audit_tampering(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    plan_path = tmp_path / "review_plan.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=plan_path,
    )
    _review(plan_path)
    files["first"].write_text(
        files["first"].read_text().replace("0.2800000000", "0.2900000000")
    )
    with pytest.raises(ValueError, match="hash-mismatched"):
        validate_reviewed_coupled_conformer_plan(plan_path)


def test_reviewed_plan_rejects_reflection_even_if_hash_is_updated(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    plan_path = tmp_path / "review_plan.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=files["optimized_audit"],
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=plan_path,
    )
    payload = _review(plan_path)
    mirrored = REFERENCE.copy()
    mirrored[:, 0] *= -1.0
    mirrored[2, 2] += 0.08
    _xyz(files["first"], mirrored)
    payload["conformers"][0]["geometry"]["sha256"] = _sha256(files["first"])
    plan_path.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(ValueError, match="chirality/geometry"):
        validate_reviewed_coupled_conformer_plan(plan_path)


def test_workflow_storage_root_fails_before_an_output_can_escape(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    inside = archive / "future" / "result.json"
    checked = _enforce_storage_root(
        Namespace(
            storage_root=archive,
            output=inside,
            output_dir=None,
            cache_dir=None,
            scratch_dir=None,
            scratch_root=None,
        )
    )
    assert checked["output"] == str(inside.resolve())
    with pytest.raises(ValueError, match="must be under storage root"):
        _enforce_storage_root(
            Namespace(
                storage_root=archive,
                output=tmp_path / "small-drive-output.json",
                output_dir=None,
                cache_dir=None,
                scratch_dir=None,
                scratch_root=None,
            )
        )
    choices = _parser()._subparsers._group_actions[0].choices
    assert "build-coupled-conformer-mode-source" in choices
    assert "build-coupled-conformer-review" in choices
    assert "build-coupled-conformer-review-visualization" in choices
    assert "build-coupled-conformer-review-decisions" in choices
    assert "apply-coupled-conformer-review-decisions" in choices
    assert "audit-coupled-conformer-review" in choices
    assert "generate-fixed-geometry-hessian" in choices


def test_normal_mode_candidates_are_deterministic_gate_neutral_and_unreviewed(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    hessian = tmp_path / "minimum_hessian.txt"
    np.savetxt(hessian, np.eye(3 * len(KEYS)))
    targets = tmp_path / "minimum_targets.json"
    targets.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-hessian-target-bundle.v1",
                "frequency_evidence_status": "passed_harmonic_minimum",
                "gate_effect": "none",
                "product_id": "tt-cpd-fixture",
                "model_id": "fixture-model",
                "atom_map": KEYS,
                "source_geometry": {
                    "path": str(files["reference"]),
                    "sha256": _sha256(files["reference"]),
                },
                "cartesian_hessian": {
                    "path": str(hessian),
                    "sha256": _sha256(hessian),
                    "units": "hartree/bohr^2",
                    "dimension": 3 * len(KEYS),
                },
            }
        )
        + "\n"
    )
    first = build_coupled_conformer_candidates(
        hessian_targets_path=targets,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        active_atom_keys=["A", "B", "C", "D"],
        output_dir=tmp_path / "candidates-first",
        mode_pair_count=2,
        active_rmsd_amplitudes_angstrom=(0.04,),
    )
    second = build_coupled_conformer_candidates(
        hessian_targets_path=targets,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        active_atom_keys=["A", "B", "C", "D"],
        output_dir=tmp_path / "candidates-second",
        mode_pair_count=2,
        active_rmsd_amplitudes_angstrom=(0.04,),
    )
    assert first["status"] == "candidates_not_reviewed"
    assert first["simulation_ready"] is False
    assert first["gate_effect"] == "none"
    assert len(first["candidates"]) >= 2
    assert [item["id"] for item in first["candidates"]] == [
        item["id"] for item in second["candidates"]
    ]
    assert [item["geometry"]["sha256"] for item in first["candidates"]] == [
        item["geometry"]["sha256"] for item in second["candidates"]
    ]


def test_candidate_mode_source_exposes_response_without_parameter_targets(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    frequency_dir = tmp_path / "frequency"
    frequency_dir.mkdir()
    hessian = frequency_dir / "hessian_hartree_per_bohr2.txt"
    np.savetxt(hessian, np.eye(3 * len(KEYS)))
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "job_kind": "frequency",
        "product_id": "tt-cpd-fixture",
        "model_id": "fixture-model",
        "atom_count": len(KEYS),
        "atom_map": KEYS,
        "source_xyz": {
            "path": str(files["reference"]),
            "sha256": _sha256(files["reference"]),
        },
    }
    (frequency_dir / "job_manifest.json").write_text(json.dumps(job) + "\n")
    audit = {
        "schema": "nadoc.photoproduct-frequency-audit.v1",
        "status": "passed_candidate_harmonic_minimum",
        "gate_effect": "none",
        "product_id": "tt-cpd-fixture",
        "model_id": "fixture-model",
        "imaginary_mode_count": 0,
        "cartesian_hessian": {
            "status": "passed",
            "units": "hartree/bohr^2",
            "sha256": _sha256(hessian),
        },
    }
    (frequency_dir / "frequency_audit.json").write_text(json.dumps(audit) + "\n")
    mode_source_path = tmp_path / "mode-source.json"

    source = build_coupled_conformer_mode_source(
        frequency_job_dir=frequency_dir,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        output_path=mode_source_path,
    )

    assert source["status"] == "candidate_mode_source_not_fit_target"
    assert source["contains_parameter_targets"] is False
    assert source["chemical_definition_gate_required_before_fit_targets"] is True
    candidates = build_coupled_conformer_candidates(
        hessian_targets_path=mode_source_path,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        active_atom_keys=["A", "B", "C", "D"],
        output_dir=tmp_path / "mode-source-candidates",
        mode_pair_count=2,
        active_rmsd_amplitudes_angstrom=(0.04,),
    )
    assert candidates["status"] == "candidates_not_reviewed"
    assert candidates["gate_effect"] == "none"
    review_path = tmp_path / "auto-selected-review.json"
    review = build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=None,
        mode_source_path=mode_source_path,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[],
        candidate_manifest_path=(
            tmp_path / "mode-source-candidates/coupled_conformer_candidates.json"
        ),
        candidate_selection_policy=("top-two-modes-both-signs-largest-amplitude-v1"),
        output_path=review_path,
    )
    assert len(review["conformers"]) == 4
    assert review["candidate_selection"]["scientific_effect"] == "review_queue_only"
    assert all(item["source_candidate_id"] for item in review["conformers"])
    screened_path = tmp_path / "quantitatively-screened.json"
    screened = materialize_quantitatively_screened_coupled_conformer_plan(
        plan_path=review_path,
        output_path=screened_path,
    )
    assert screened["status"] == "quantitatively_screened"
    assert screened["quantitative_screening"]["releases_parameters"] is False
    assert [item["partition"] for item in screened["conformers"]] == [
        "training",
        "validation",
        "validation",
        "training",
    ]
    checked = validate_reviewed_coupled_conformer_plan(screened_path)
    assert len(checked["conformers"]) == 4
    auto_audit = audit_reviewed_coupled_conformer_plan(
        plan_path=screened_path,
        output_path=tmp_path / "quantitative-screen-audit.json",
    )
    assert auto_audit["status"] == "passed_quantitative_qm_input_screen"
    assert auto_audit["decision_authority"]["kind"] == ("automated_quantitative_policy")
    index = build_coupled_conformer_review_index(
        plan_paths=[review_path], output_dir=tmp_path / "review-index"
    )
    assert index["status"] == "human_review_required"
    assert index["product_count"] == 1
    assert len(index["records"][0]["conformers"]) == 4
    assert index["gate_effect"] == "none"
    visualization = build_coupled_conformer_review_visualization(
        review_index_path=(
            tmp_path / "review-index/coupled_conformer_review_index.json"
        ),
        output_dir=tmp_path / "review-visualization",
    )
    assert visualization["status"] == "visualization_only_human_review_required"
    assert visualization["simulation_ready"] is False
    assert visualization["gate_effect"] == "none"
    assert visualization["not_a_trajectory"] is True
    assert visualization["not_release_evidence"] is True
    assert visualization["product_count"] == 1
    assert visualization["model_count"] == 4
    pdb_path = Path(visualization["products"][0]["pdb_models"]["path"])
    pdb = pdb_path.read_text()
    assert pdb.count("MODEL     ") == 4
    assert pdb.count("ENDMDL") == 4
    assert "CONECT" in pdb
    assert "NOT A TRAJECTORY" in pdb
    assert _sha256(pdb_path) == visualization["products"][0]["pdb_models"]["sha256"]

    stale_index = json.loads(
        (tmp_path / "review-index/coupled_conformer_review_index.json").read_text()
    )
    stale_index["records"][0]["conformers"][0][
        "proper_rotation_aligned_rmsd_angstrom"
    ] += 0.1
    stale_path = tmp_path / "stale-review-index.json"
    stale_path.write_text(json.dumps(stale_index) + "\n")
    with pytest.raises(ValueError, match="audit changed or failed"):
        build_coupled_conformer_review_visualization(
            review_index_path=stale_path,
            output_dir=tmp_path / "must-not-exist",
        )
    assert not (tmp_path / "must-not-exist").exists()

    decisions_path = tmp_path / "review-decisions.json"
    decisions = build_coupled_conformer_review_decision_template(
        review_index_path=(
            tmp_path / "review-index/coupled_conformer_review_index.json"
        ),
        output_path=decisions_path,
    )
    assert decisions["status"] == "human_input_required"
    assert decisions["gate_effect"] == "none"
    with pytest.raises(ValueError, match="explicit complete"):
        apply_coupled_conformer_review_decisions(
            decisions_path=decisions_path,
            output_dir=tmp_path / "unreviewed-must-not-exist",
        )
    assert not (tmp_path / "unreviewed-must-not-exist").exists()

    decisions["status"] = "human_review_complete"
    product_review = decisions["reviews"][0]
    product_review["reviewed_by"] = "Qualified Test Reviewer"
    product_review["reviewed_at"] = "2026-09-05T10:00:00-06:00"
    product_review["review_rationale"] = (
        "All four coupled distortions were inspected with stable atom mapping."
    )
    for number, decision in enumerate(product_review["conformers"]):
        if number < 2:
            decision["review_decision"] = "accepted"
            decision["partition"] = "training" if number == 0 else "validation"
            decision["review_notes"] = "Plausible coupled ring distortion retained."
        else:
            decision["review_decision"] = "rejected"
            decision["partition"] = None
            decision["review_notes"] = "Rejected from fitting after human inspection."
    decisions_path.write_text(json.dumps(decisions, indent=2) + "\n")
    materialized = apply_coupled_conformer_review_decisions(
        decisions_path=decisions_path,
        output_dir=tmp_path / "materialized-reviews",
    )
    assert materialized["status"] == "passed_human_review_structure"
    assert materialized["simulation_ready"] is False
    assert materialized["gate_effect"] == "none"
    assert materialized["authorizes_qm"] is False
    assert materialized["product_count"] == 1
    assert materialized["products"][0]["counts"] == {
        "total": 4,
        "accepted": 2,
        "rejected": 2,
        "training": 1,
        "validation": 1,
    }


def test_equivalent_mode_source_permutates_geometry_and_hessian_together(
    tmp_path: Path,
) -> None:
    files = _fixtures(tmp_path)
    stereo = json.loads(files["stereochemistry"].read_text())
    stereo["schema"] = "nadoc.tt-cpd-stereo-candidate.v1"
    stereo["status"] = "candidate_not_reviewed"
    stereo["product_id"] = "tt-cpd-fixture"
    stereo["model_id"] = "fixture-model"
    stereo["model_signed_volume_stereochemistry"] = [
        {
            "atom": item["atom"],
            "reference_atoms": item["signed_volume_reference_atoms"],
            "expected_sign": item["expected_signed_volume"],
        }
        for item in stereo.pop("product_stereocenters")
    ]
    files["stereochemistry"].write_text(json.dumps(stereo) + "\n")
    target_in_source_order = ["B", "A", "D", "C", "F", "E", "H", "G"]
    source_coordinates = [REFERENCE[KEYS.index(key)] for key in target_in_source_order]
    source_xyz = tmp_path / "equivalent-source.xyz"
    _xyz(source_xyz, np.asarray(source_coordinates))
    source_hessian = tmp_path / "equivalent-source-hessian.txt"
    diagonal = np.arange(1, 3 * len(KEYS) + 1, dtype=float)
    np.savetxt(source_hessian, np.diag(diagonal))
    source_frequency = tmp_path / "equivalent-source-frequency.json"
    source_frequency.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-audit.v1",
                "status": "passed_harmonic_minimum",
                "product_id": "tt-cpd-source",
                "imaginary_mode_count": 0,
                "cartesian_hessian": {"sha256": _sha256(source_hessian)},
            }
        )
        + "\n"
    )
    equivalence = tmp_path / "equivalence-audit.json"
    equivalence.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-equivalence-audit.v1",
                "status": "passed_candidate_model_equivalence",
                "passed": True,
                "product_ids": ["tt-cpd-source", "tt-cpd-fixture"],
            }
        )
        + "\n"
    )
    reference = tmp_path / "equivalent-reference.json"
    reference.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-equivalent-hessian-reference.v1",
                "status": "passed_candidate_reuse_preconditions",
                "passed": True,
                "gate_effect": "none",
                "source_product_id": "tt-cpd-source",
                "target_product_id": "tt-cpd-fixture",
                "coordinate_frame": "source-retained-no-tensor-rotation",
                "source_atom_map": [f"source:{index}" for index in range(len(KEYS))],
                "target_atom_map_in_source_matrix_order": target_in_source_order,
                "source_frequency": {
                    "frequency_audit": {
                        "path": str(source_frequency),
                        "sha256": _sha256(source_frequency),
                    },
                    "cartesian_hessian": {
                        "path": str(source_hessian),
                        "sha256": _sha256(source_hessian),
                    },
                    "source_geometry": {
                        "path": str(source_xyz),
                        "sha256": _sha256(source_xyz),
                    },
                },
                "equivalence_audit": {
                    "path": str(equivalence),
                    "sha256": _sha256(equivalence),
                },
            }
        )
        + "\n"
    )
    output = tmp_path / "equivalent-mode-source.json"

    mode_source = build_coupled_conformer_mode_source(
        equivalent_hessian_reference_path=reference,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        output_path=output,
    )

    derivation = mode_source["sources"]["matrix_order_derivation"]
    assert derivation["spatial_transform"] == "none"
    assert derivation["tensor_operation"] == (
        "simultaneous row-and-column permutation only"
    )
    reordered = np.loadtxt(mode_source["cartesian_hessian"]["path"])
    atom_permutation = derivation["atom_permutation_zero_based"]
    coordinate_permutation = [
        3 * atom + component for atom in atom_permutation for component in range(3)
    ]
    assert np.array_equal(
        np.diag(reordered), diagonal[np.asarray(coordinate_permutation)]
    )
    assert mode_source["chirality_audit"]["passed"] is True

    review_path = tmp_path / "candidate-stereo-review.json"
    build_coupled_conformer_review_template(
        product_id="tt-cpd-fixture",
        model_id="fixture-model",
        optimized_audit_path=None,
        mode_source_path=output,
        model_graph_path=files["graph"],
        stable_atom_map_path=files["stable_map"],
        stereochemistry_evidence_path=files["stereochemistry"],
        candidate_xyz_paths=[files["first"], files["second"]],
        output_path=review_path,
    )
    _review(review_path)
    with pytest.raises(ValueError, match="chemical_definition gate"):
        generate_fixed_geometry_hessian_job(
            plan_path=review_path,
            conformer_id="conformer-001",
            output_dir=tmp_path / "candidate-stereo-qm",
            charge=0,
        )
