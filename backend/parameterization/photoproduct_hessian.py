"""Create hash-linked bonded-fit targets from an audited QM Cartesian Hessian.

This module intentionally does not convert a Hessian into CHARMM force constants.
It preserves the raw response, stable atom identity, and reviewed internal-coordinate
inventory so a documented fitter (for example ForceBalance) can optimize coupled terms
without an unreviewed one-coordinate projection becoming a released parameter.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.core.photoproduct_chemistry import (
    chemical_definition_asset,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_distributed_hessian import (
    _frequency_reference,
)
from backend.parameterization.photoproduct_terms import build_term_inventory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_square_matrix(path: Path, dimension: int) -> tuple[list[list[float]], float]:
    try:
        rows = [
            [float(value) for value in line.split()]
            for line in path.read_text().splitlines()
            if line.strip()
        ]
    except ValueError as exc:
        raise ValueError("Cartesian Hessian contains a non-numeric value") from exc
    if len(rows) != dimension or any(len(row) != dimension for row in rows):
        raise ValueError(f"Cartesian Hessian must be a {dimension} by {dimension} matrix")
    if not all(math.isfinite(value) for row in rows for value in row):
        raise ValueError("Cartesian Hessian contains a non-finite value")
    symmetry_error = max(
        (abs(rows[i][j] - rows[j][i]) for i in range(dimension) for j in range(i)),
        default=0.0,
    )
    if symmetry_error > 1e-8:
        raise ValueError("Cartesian Hessian exceeds the audited symmetry tolerance")
    return rows, symmetry_error


def build_hessian_target_bundle(
    *, frequency_job_dir: Path, output_path: Path
) -> dict[str, Any]:
    """Bind a passed frequency Hessian to stable atoms and reviewed local terms."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite Hessian target bundle: {output_path}")
    job_path = frequency_job_dir / "job_manifest.json"
    audit_path = frequency_job_dir / "frequency_audit.json"
    hessian_path = frequency_job_dir / "hessian_hartree_per_bohr2.txt"
    if not all(path.is_file() for path in (job_path, audit_path, hessian_path)):
        raise ValueError("frequency job, passed audit, and Cartesian Hessian are required")
    job = json.loads(job_path.read_text())
    audit = json.loads(audit_path.read_text())
    accepted_frequency_statuses = {
        "passed_harmonic_minimum",
        "passed_candidate_harmonic_minimum",
    }
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "frequency"
        or audit.get("schema") != "nadoc.photoproduct-frequency-audit.v1"
        or audit.get("status") not in accepted_frequency_statuses
        or audit.get("product_id") != job.get("product_id")
        or audit.get("model_id") != job.get("model_id")
    ):
        raise ValueError("frequency job and audit are not a passed matching pair")
    hessian_audit = audit.get("cartesian_hessian") or {}
    if (
        hessian_audit.get("status") != "passed"
        or hessian_audit.get("units") != "hartree/bohr^2"
        or hessian_audit.get("sha256") != _sha256(hessian_path)
    ):
        raise ValueError("frequency audit does not pass and hash-link the Cartesian Hessian")
    atom_map = job.get("atom_map")
    atom_count = job.get("atom_count")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != atom_count
        or len(atom_map) != len(set(atom_map))
    ):
        raise ValueError("frequency job lacks a unique stable atom map")
    source_path = _frequency_reference(
        job_dir=frequency_job_dir,
        job=job,
        key="source_xyz",
        label="frequency source geometry",
    )
    atoms, _comment = parse_xyz(source_path.read_text())
    if len(atoms) != atom_count:
        raise ValueError("frequency source geometry does not match the atom count")
    _matrix, symmetry_error = _load_square_matrix(hessian_path, 3 * atom_count)

    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == job.get("product_id")
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError("frequency job refers to an unregistered photoproduct")
    try:
        definition_record = chemical_definition_asset(
            registry_entry["product"], registry_entry["stereochemistry"]
        )
        definition = load_chemical_definition(
            registry_entry["product"], registry_entry["stereochemistry"]
        )
        inventory = build_term_inventory(
            registry_entry["product"], registry_entry["stereochemistry"]
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "a reviewed chemical definition is required before enumerating Hessian fit targets"
        ) from exc
    full_targets = {
        category: inventory["all_local_terms_requiring_type_or_parameter_audit"][category]
        for category in ("bonds", "angles")
    }
    coordinate_targets: dict[str, list[list[str]]] = {}
    excluded_targets: dict[str, list[dict[str, Any]]] = {}
    atom_set = set(atom_map)
    for category, records in full_targets.items():
        coordinate_targets[category] = [
            record for record in records if set(record).issubset(atom_set)
        ]
        excluded_targets[category] = [
            {
                "atoms": record,
                "missing_model_atoms": sorted(set(record) - atom_set),
            }
            for record in records
            if not set(record).issubset(atom_set)
        ]
        if not coordinate_targets[category]:
            raise ValueError(f"QM model covers no reviewed {category} Hessian targets")
    required_ring_atoms = {
        atom
        for category in ("bonds_added", "bonds_retained")
        for record in definition["graph_delta"][category]
        for atom in (record.get("atom_1"), record.get("atom_2"))
        if atom
    }
    missing_required = sorted(required_ring_atoms - atom_set)
    if missing_required:
        raise ValueError(
            "QM model omits product-ring atoms required for Hessian fitting: "
            + ", ".join(missing_required)
        )
    atom_indices = {key: index for index, key in enumerate(atom_map)}
    report = {
        "schema": "nadoc.photoproduct-hessian-target-bundle.v1",
        "status": (
            "partial_candidate_evidence_boundary_model_required"
            if any(excluded_targets.values())
            else "complete_candidate_evidence"
        ),
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "frequency_evidence_status": audit["status"],
        "atom_count": atom_count,
        "atom_map": atom_map,
        "atom_zero_based_indices": atom_indices,
        "coordinate_targets": coordinate_targets,
        "excluded_coordinate_targets": excluded_targets,
        "coordinate_target_coverage": {
            category: {
                "covered": len(coordinate_targets[category]),
                "excluded": len(excluded_targets[category]),
                "total": len(full_targets[category]),
            }
            for category in full_targets
        },
        "cartesian_hessian": {
            "path": str(hessian_path.resolve()),
            "sha256": _sha256(hessian_path),
            "units": "hartree/bohr^2",
            "dimension": 3 * atom_count,
            "maximum_symmetry_error": symmetry_error,
        },
        "source_geometry": {
            "path": str(source_path.resolve()),
            "declared_path": str((job.get("source_xyz") or {}).get("path") or ""),
            "relocated": source_path.resolve()
            != Path(str((job.get("source_xyz") or {}).get("path") or "")).resolve(),
            "sha256": _sha256(source_path),
            "units": "angstrom",
        },
        "chemical_definition": definition_record,
        "frequency_job": {"path": str(job_path.resolve()), "sha256": _sha256(job_path)},
        "frequency_audit": {
            "path": str(audit_path.resolve()),
            "sha256": _sha256(audit_path),
        },
        "fit_policy": (
            "Use the coupled Cartesian Hessian as an optimization target. No diagonal "
            "projection or force constant in this bundle is a released CHARMM term. "
            "Targets absent from this model remain excluded and require a separately "
            "audited DNA-boundary model before release."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
