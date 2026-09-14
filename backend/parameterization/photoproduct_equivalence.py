"""Audit narrowly scoped equivalence between optimized photoproduct model compounds."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_distributed_hessian import (
    _frequency_reference,
)
from backend.parameterization.photoproduct_hessian import _load_square_matrix
from backend.parameterization.photoproduct_qm import QM_PROTOCOL_PATH, parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_relocated_hashed_file(
    record: object, *, local_copy: Path, label: str
) -> tuple[Path, Path, bool]:
    if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
        raise ValueError(f"{label} has no immutable file record")
    declared = Path(str(record.get("path") or ""))
    candidates = [declared, local_copy]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file() and _sha256(candidate) == record["sha256"]:
            return resolved, declared, resolved != declared.resolve()
    raise ValueError(f"{label} is missing or hash-mismatched")


def _load_passed_optimization(job_dir: Path) -> dict[str, Any]:
    job_path = job_dir / "job_manifest.json"
    audit_path = job_dir / "optimized_model_audit.json"
    if not job_path.is_file() or not audit_path.is_file():
        raise ValueError(f"optimized job and chirality audit are required: {job_dir}")
    job = json.loads(job_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "geometry_optimization"
        or audit.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or audit.get("status")
        not in {"passed_identity_and_chirality", "passed_candidate_identity_and_chirality"}
        or audit.get("product_id") != job.get("product_id")
        or audit.get("model_id") != job.get("model_id")
    ):
        raise ValueError(f"job has no matching passed optimization audit: {job_dir}")
    xyz_record = audit.get("optimized_xyz") or {}
    xyz_path, xyz_declared_path, xyz_relocated = _resolve_relocated_hashed_file(
        xyz_record,
        local_copy=job_dir / "optimized.xyz",
        label=f"optimized coordinates for {job_dir}",
    )
    atoms, _comment = parse_xyz(xyz_path.read_text())
    atom_map = job.get("atom_map")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != len(atoms)
        or len(atom_map) != len(set(atom_map))
    ):
        raise ValueError(f"optimization has no unique stable atom map: {job_dir}")
    reconciliation_path = job_dir / "run_reconciliation.json"
    energy = audit.get("final_energy_hartree")
    effective_run_path = None
    if energy is None and reconciliation_path.is_file():
        reconciliation = json.loads(reconciliation_path.read_text())
        if (
            reconciliation.get("schema")
            != "nadoc.photoproduct-qm-run-reconciliation.v1"
            or reconciliation.get("job_manifest_sha256") != _sha256(job_path)
        ):
            raise ValueError(f"optimization reconciliation is hash-mismatched: {job_dir}")
        energy = (reconciliation.get("parsed") or {}).get("final_energy_hartree")
        effective_run_path = reconciliation_path
    if not isinstance(energy, (int, float)) or not math.isfinite(float(energy)):
        raise ValueError(f"optimization has no finite final energy: {job_dir}")
    return {
        "job": job,
        "job_path": job_path,
        "audit": audit,
        "audit_path": audit_path,
        "xyz_path": xyz_path,
        "xyz_declared_path": xyz_declared_path,
        "xyz_relocated": xyz_relocated,
        "atoms": atoms,
        "atom_map": atom_map,
        "energy": float(energy),
        "effective_run_path": effective_run_path,
    }


def _endpoint_exchange(key: str) -> str:
    endpoint, separator, atom_name = key.partition(":")
    if not separator or endpoint not in {"1", "2"} or not atom_name:
        raise ValueError(f"model atom is not an ordered endpoint key: {key!r}")
    return f"{3 - int(endpoint)}:{atom_name}"


def _geometry_protocol_identity(job: dict[str, Any]) -> dict[str, Any]:
    version = job.get("protocol_version")
    if not isinstance(version, str) or not version:
        raise ValueError("optimization does not name a protocol version")
    path = QM_PROTOCOL_PATH.with_name(f"photoproduct_qm_protocol_v{version}.json")
    if not path.is_file() or _sha256(path) != job.get("protocol_sha256"):
        raise ValueError(f"immutable QM protocol snapshot is missing or mismatched: {version}")
    protocol = json.loads(path.read_text())
    identity = (protocol.get("jobs") or {}).get("geometry_optimization")
    if not isinstance(identity, dict):
        raise ValueError(f"QM protocol {version} has no geometry optimization definition")
    return identity


_LEGACY_HYDROGEN_ALIASES = {
    "HN3": "H3",
    "HT": "H3",
    "H5A1": "H51",
    "H5A2": "H52",
    "H5A3": "H53",
    "H71": "H51",
    "H72": "H52",
    "H73": "H53",
}


def _canonical_model_atom_key(key: str) -> str:
    endpoint, separator, atom_name = key.partition(":")
    if not separator:
        raise ValueError(f"model atom is not an ordered endpoint key: {key!r}")
    return f"{endpoint}:{_LEGACY_HYDROGEN_ALIASES.get(atom_name, atom_name)}"


def _proper_rotation_fit(
    reference: np.ndarray, candidate: np.ndarray
) -> tuple[float, float, float]:
    first = reference - reference.mean(axis=0)
    second = candidate - candidate.mean(axis=0)
    left, _singular, right = np.linalg.svd(first.T @ second)
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right
    delta = first @ rotation - second
    distances = np.linalg.norm(delta, axis=1)
    return (
        float(np.sqrt(np.mean(distances**2))),
        float(np.max(distances)),
        float(np.linalg.det(rotation)),
    )


def audit_endpoint_exchange_equivalence(
    *,
    first_job_dir: Path,
    second_job_dir: Path,
    independent_stereo_audit_path: Path,
    output_path: Path,
    maximum_energy_difference_hartree: float = 1e-6,
    maximum_heavy_atom_rmsd_angstrom: float = 1e-3,
) -> dict[str, Any]:
    """Prove model-compound equivalence under endpoint exchange and proper rotation.

    The result can justify sharing gas-phase model-compound targets. It deliberately
    says nothing about ordered DNA attachments, coordinate templates, or context gates.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite equivalence audit: {output_path}")
    first = _load_passed_optimization(first_job_dir)
    second = _load_passed_optimization(second_job_dir)
    if first["job"]["product_id"] == second["job"]["product_id"]:
        raise ValueError("equivalence audit requires two distinct ordered products")
    quantum_identity_fields = ("method", "basis", "charge", "multiplicity")
    if any(
        first["job"].get(field) != second["job"].get(field)
        for field in quantum_identity_fields
    ):
        raise ValueError("optimized models use different QM identities")
    first_protocol_identity = _geometry_protocol_identity(first["job"])
    second_protocol_identity = _geometry_protocol_identity(second["job"])
    if first_protocol_identity != second_protocol_identity:
        raise ValueError("optimized models use different geometry-optimization protocols")

    independent = json.loads(independent_stereo_audit_path.read_text())
    if (
        independent.get("schema") != "nadoc.tt-cpd-openbabel-stereo-audit.v1"
        or independent.get("passed") is not True
    ):
        raise ValueError("a passed independent stereo audit is required")
    record_by_id = {
        item.get("product_id"): item for item in independent.get("records") or []
    }
    product_ids = [first["job"]["product_id"], second["job"]["product_id"]]
    independent_records = [record_by_id.get(product_id) for product_id in product_ids]
    if any(record is None for record in independent_records):
        raise ValueError("independent stereo audit does not cover both products")
    identifiers = [record.get("inchikey") for record in independent_records]
    smiles = [record.get("canonical_isomeric_smiles") for record in independent_records]
    if not identifiers[0] or identifiers[0] != identifiers[1] or smiles[0] != smiles[1]:
        raise ValueError(
            "independent identifiers do not establish endpoint-exchange identity"
        )

    second_index = {
        _canonical_model_atom_key(key): index
        for index, key in enumerate(second["atom_map"])
    }
    if len(second_index) != len(second["atom_map"]):
        raise ValueError("second model atom aliases are not unique")
    mapping: list[dict[str, Any]] = []
    reference_coordinates = []
    candidate_coordinates = []
    for first_index, key in enumerate(first["atom_map"]):
        exchanged = _endpoint_exchange(_canonical_model_atom_key(key))
        if exchanged not in second_index:
            raise ValueError(f"second model lacks exchanged atom key {exchanged!r}")
        other_index = second_index[exchanged]
        first_atom = first["atoms"][first_index]
        second_atom = second["atoms"][other_index]
        if first_atom[0] != second_atom[0]:
            raise ValueError(f"element differs under endpoint exchange for {key}")
        mapping.append(
            {
                "first_atom": key,
                "second_atom": second["atom_map"][other_index],
                "canonical_exchanged_atom": exchanged,
                "element": first_atom[0],
            }
        )
        if first_atom[0].upper() != "H":
            reference_coordinates.append(first_atom[1:])
            candidate_coordinates.append(second_atom[1:])
    rmsd, maximum, determinant = _proper_rotation_fit(
        np.asarray(reference_coordinates, dtype=float),
        np.asarray(candidate_coordinates, dtype=float),
    )
    energy_difference = abs(first["energy"] - second["energy"])
    errors = []
    if energy_difference > maximum_energy_difference_hartree:
        errors.append("optimized energy difference exceeds tolerance")
    if rmsd > maximum_heavy_atom_rmsd_angstrom:
        errors.append("endpoint-exchanged heavy-atom RMSD exceeds tolerance")
    if determinant < 1.0 - 1e-8:
        errors.append("coordinate equivalence would require reflection")
    report = {
        "schema": "nadoc.photoproduct-model-equivalence-audit.v1",
        "status": "passed_candidate_model_equivalence" if not errors else "failed",
        "passed": not errors,
        "gate_effect": "none",
        "mapping": "ordered-endpoint-exchange",
        "product_ids": product_ids,
        "qm_identity": {
            field: first["job"].get(field) for field in quantum_identity_fields
        },
        "geometry_optimization_protocol": first_protocol_identity,
        "energies_hartree": [first["energy"], second["energy"]],
        "absolute_energy_difference_hartree": energy_difference,
        "maximum_energy_difference_hartree": maximum_energy_difference_hartree,
        "heavy_atom_count": len(reference_coordinates),
        "heavy_atom_rmsd_angstrom": rmsd,
        "maximum_heavy_atom_displacement_angstrom": maximum,
        "maximum_heavy_atom_rmsd_angstrom": maximum_heavy_atom_rmsd_angstrom,
        "rotation_determinant": determinant,
        "reflection_used": False,
        "atom_mapping": mapping,
        "independent_identifier": {
            "inchikey": identifiers[0],
            "canonical_isomeric_smiles": smiles[0],
            "audit": {
                "path": str(independent_stereo_audit_path.resolve()),
                "sha256": _sha256(independent_stereo_audit_path),
            },
        },
        "optimization_evidence": [
            {
                "job_manifest": {
                    "path": str(record["job_path"].resolve()),
                    "sha256": _sha256(record["job_path"]),
                },
                "optimized_model_audit": {
                    "path": str(record["audit_path"].resolve()),
                    "sha256": _sha256(record["audit_path"]),
                },
                "optimized_xyz": {
                    "path": str(record["xyz_path"].resolve()),
                    "declared_path": str(record["xyz_declared_path"]),
                    "relocated": record["xyz_relocated"],
                    "sha256": _sha256(record["xyz_path"]),
                },
                "protocol_version": record["job"].get("protocol_version"),
                "protocol_sha256": record["job"].get("protocol_sha256"),
            }
            for record in (first, second)
        ],
        "shareable_scope": [
            "achiral gas-phase N-methyl model-compound optimized geometry",
            "a separately passed source frequency/Hessian after the recorded atom permutation and proper rotation",
        ],
        "reuse_precondition": (
            "the source target must pass its own frequency/Hessian audit; this "
            "equivalence report does not assert that such a target exists"
        ),
        "not_established": [
            "source harmonic-minimum or Hessian completion",
            "ordered DNA chemical-definition equivalence",
            "DNA boundary-model equivalence",
            "coordinate-template interchangeability",
            "intrastrand or interstrand context validation",
            "registry gate passage",
        ],
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_equivalent_hessian_reference(
    *,
    source_frequency_job_dir: Path,
    equivalence_audit_path: Path,
    target_product_id: str,
    output_path: Path,
) -> dict[str, Any]:
    """Bind a passed Hessian to an independently proved endpoint permutation.

    The Cartesian frame and matrix order remain exactly those of the source. Only stable
    atom identity is relabelled through the audited endpoint exchange, avoiding an
    unrecorded tensor rotation or a second copy of the large matrix.
    """

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite equivalent-Hessian reference: {output_path}"
        )
    equivalence = json.loads(equivalence_audit_path.read_text())
    product_ids = equivalence.get("product_ids")
    if (
        equivalence.get("schema")
        != "nadoc.photoproduct-model-equivalence-audit.v1"
        or equivalence.get("status") != "passed_candidate_model_equivalence"
        or equivalence.get("passed") is not True
        or equivalence.get("gate_effect") != "none"
        or equivalence.get("mapping") != "ordered-endpoint-exchange"
        or equivalence.get("reflection_used") is not False
        or not isinstance(product_ids, list)
        or len(product_ids) != 2
        or product_ids[1] != target_product_id
    ):
        raise ValueError("a passed source-to-target endpoint equivalence audit is required")

    job_path = source_frequency_job_dir / "job_manifest.json"
    audit_path = source_frequency_job_dir / "frequency_audit.json"
    hessian_path = source_frequency_job_dir / "hessian_hartree_per_bohr2.txt"
    if not all(path.is_file() for path in (job_path, audit_path, hessian_path)):
        raise ValueError("source frequency job, audit, and Hessian are required")
    job = json.loads(job_path.read_text())
    audit = json.loads(audit_path.read_text())
    hessian_record = audit.get("cartesian_hessian") or {}
    accepted_statuses = {
        "passed_harmonic_minimum",
        "passed_candidate_harmonic_minimum",
    }
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "frequency"
        or job.get("product_id") != product_ids[0]
        or audit.get("schema") != "nadoc.photoproduct-frequency-audit.v1"
        or audit.get("status") not in accepted_statuses
        or audit.get("product_id") != job.get("product_id")
        or audit.get("model_id") != job.get("model_id")
        or audit.get("imaginary_mode_count") != 0
        or hessian_record.get("status") != "passed"
        or hessian_record.get("units") != "hartree/bohr^2"
        or hessian_record.get("sha256") != _sha256(hessian_path)
    ):
        raise ValueError("source frequency evidence is not a passed harmonic minimum")
    atom_map = job.get("atom_map")
    atom_count = job.get("atom_count")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != atom_count
        or len(atom_map) != len(set(atom_map))
    ):
        raise ValueError("source frequency job lacks a unique stable atom map")
    _matrix, symmetry_error = _load_square_matrix(hessian_path, 3 * atom_count)
    source_geometry = _frequency_reference(
        job_dir=source_frequency_job_dir,
        job=job,
        key="source_xyz",
        label="frequency source geometry",
    )

    optimization_evidence = equivalence.get("optimization_evidence")
    if not isinstance(optimization_evidence, list) or len(optimization_evidence) != 2:
        raise ValueError("equivalence audit lacks two optimization evidence records")
    source_optimized = optimization_evidence[0].get("optimized_xyz") or {}
    if source_optimized.get("sha256") != _sha256(source_geometry):
        raise ValueError("source frequency geometry differs from equivalence evidence")

    key_mapping: dict[str, str] = {}
    for record in equivalence.get("atom_mapping") or []:
        try:
            source_key = _canonical_model_atom_key(record["first_atom"])
            target_key = str(record["canonical_exchanged_atom"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("equivalence audit contains a malformed atom mapping") from exc
        if source_key in key_mapping or not target_key:
            raise ValueError("equivalence atom mapping is not one-to-one")
        key_mapping[source_key] = target_key
    if set(key_mapping) != set(atom_map):
        raise ValueError("equivalence atom mapping does not cover the frequency atom map")
    target_atom_map = [key_mapping[key] for key in atom_map]
    if len(target_atom_map) != len(set(target_atom_map)):
        raise ValueError("equivalence target atom mapping is not one-to-one")

    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == target_product_id
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError("equivalent Hessian target is not a registered photoproduct")
    target_job_record = optimization_evidence[1].get("job_manifest") or {}
    target_job_path = Path(str(target_job_record.get("path") or ""))
    if (
        not target_job_path.is_file()
        or _sha256(target_job_path) != target_job_record.get("sha256")
    ):
        raise ValueError("target optimization job is missing or hash-mismatched")
    target_job = json.loads(target_job_path.read_text())
    target_job_atom_map = target_job.get("atom_map")
    if (
        target_job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or target_job.get("job_kind") != "geometry_optimization"
        or target_job.get("product_id") != target_product_id
        or not isinstance(target_job_atom_map, list)
        or set(target_job_atom_map) != set(target_atom_map)
    ):
        raise ValueError("target optimization job does not match the exchanged atom map")

    report = {
        "schema": "nadoc.photoproduct-equivalent-hessian-reference.v1",
        "status": "passed_candidate_reuse_preconditions",
        "passed": True,
        "gate_effect": "none",
        "source_product_id": job["product_id"],
        "target_product_id": target_product_id,
        "source_model_id": job["model_id"],
        "target_model_id": target_job["model_id"],
        "coordinate_frame": "source-retained-no-tensor-rotation",
        "source_atom_map": atom_map,
        "target_atom_map_in_source_matrix_order": target_atom_map,
        "stable_atom_mapping": [
            {"source": source, "target": target}
            for source, target in zip(atom_map, target_atom_map, strict=True)
        ],
        "source_frequency": {
            "job_manifest": {"path": str(job_path.resolve()), "sha256": _sha256(job_path)},
            "frequency_audit": {
                "path": str(audit_path.resolve()),
                "sha256": _sha256(audit_path),
                "status": audit["status"],
            },
            "cartesian_hessian": {
                "path": str(hessian_path.resolve()),
                "sha256": _sha256(hessian_path),
                "units": "hartree/bohr^2",
                "dimension": 3 * atom_count,
                "maximum_symmetry_error": symmetry_error,
            },
            "source_geometry": {
                "path": str(source_geometry.resolve()),
                "sha256": _sha256(source_geometry),
                "units": "angstrom",
            },
        },
        "equivalence_audit": {
            "path": str(equivalence_audit_path.resolve()),
            "sha256": _sha256(equivalence_audit_path),
        },
        "reuse_scope": (
            "Gas-phase N-methyl geometry and Cartesian response under the explicit stable-"
            "atom endpoint permutation only. The source frame is retained, so no Hessian "
            "tensor rotation or interpolation is performed."
        ),
        "not_established": [
            "ordered DNA chemical-definition equivalence",
            "DNA boundary-model response",
            "coordinate-template interchangeability",
            "context validation",
            "parameter or registry gate passage",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
