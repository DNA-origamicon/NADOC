"""Build candidate product-coordinate templates from audited QM evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_qm import parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_model_key(definition: dict[str, Any], key: str) -> str | None:
    for cap in definition["model_compounds"]["charge_model"]["endpoint_caps"]:
        if key == cap["model_atom"]:
            return f"{cap['endpoint']}:C1'"
    endpoint_text, separator, atom_name = key.partition(":")
    if not separator or not endpoint_text.isdigit():
        raise ValueError(f"invalid stable model atom key: {key!r}")
    if atom_name.startswith("HCM"):
        return None
    aliases = {
        int(item["endpoint"]): item["aliases"]
        for item in definition["model_compounds"]["charge_model"].get(
            "endpoint_hydrogen_aliases", []
        )
    }
    canonical = aliases.get(int(endpoint_text), {}).get(atom_name, atom_name)
    return f"{endpoint_text}:{canonical}"


def build_candidate_coordinate_template(
    *,
    geometry_job_dir: Path,
    frequency_job_dir: Path,
    output_path: Path,
    version: str,
) -> dict[str, Any]:
    """Create a non-released template tied to passed geometry/frequency audits.

    Promotion to ``released`` is intentionally outside this function: it requires the
    coordinate-context, force-field, NAMD, and release-review gates, not just gas-phase
    QM evidence.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite coordinate template: {output_path}")
    geometry_job_path = geometry_job_dir / "job_manifest.json"
    geometry_audit_path = geometry_job_dir / "optimized_model_audit.json"
    optimized_path = geometry_job_dir / "optimized.xyz"
    frequency_job_path = frequency_job_dir / "job_manifest.json"
    frequency_audit_path = frequency_job_dir / "frequency_audit.json"
    required = (
        geometry_job_path,
        geometry_audit_path,
        optimized_path,
        frequency_job_path,
        frequency_audit_path,
    )
    if not all(path.is_file() for path in required):
        raise ValueError("geometry/frequency jobs and their passed audits are required")
    geometry_job = json.loads(geometry_job_path.read_text())
    geometry_audit = json.loads(geometry_audit_path.read_text())
    frequency_job = json.loads(frequency_job_path.read_text())
    frequency_audit = json.loads(frequency_audit_path.read_text())
    identity = (geometry_job.get("product_id"), geometry_job.get("model_id"))
    if (
        geometry_job.get("job_kind") != "geometry_optimization"
        or frequency_job.get("job_kind") != "frequency"
        or (frequency_job.get("product_id"), frequency_job.get("model_id")) != identity
        or geometry_audit.get("schema")
        != "nadoc.photoproduct-optimized-model-audit.v1"
        or (geometry_audit.get("product_id"), geometry_audit.get("model_id"))
        != identity
        or geometry_audit.get("status") != "passed_identity_and_chirality"
        or frequency_audit.get("schema")
        != "nadoc.photoproduct-frequency-audit.v1"
        or (frequency_audit.get("product_id"), frequency_audit.get("model_id"))
        != identity
        or frequency_audit.get("status") != "passed_harmonic_minimum"
    ):
        raise ValueError("geometry and frequency evidence is not a passed matching pair")
    if geometry_audit.get("optimized_xyz", {}).get("sha256") != _sha256(optimized_path):
        raise ValueError("optimized XYZ does not match the geometry audit")
    geometry_audit_hash = _sha256(geometry_audit_path)
    if frequency_job.get("source_xyz", {}).get("sha256") != _sha256(optimized_path):
        raise ValueError("frequency job was not generated from the optimized XYZ")
    if frequency_job.get("parent_manifest", {}).get("sha256") != geometry_audit_hash:
        raise ValueError("frequency job does not reference this geometry audit")
    if frequency_audit.get("parent_optimized_model_audit", {}).get("sha256") != (
        geometry_audit_hash
    ):
        raise ValueError("frequency audit does not reference this geometry audit")

    atom_map = geometry_job.get("atom_map")
    atoms, _comment = parse_xyz(optimized_path.read_text())
    if not isinstance(atom_map, list) or len(atom_map) != len(atoms):
        raise ValueError("optimized model has no matching stable atom map")
    registry_entry = next(
        (
            entry
            for entry in photoproduct_registry()["products"]
            if entry["id"] == geometry_audit["product_id"]
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError("optimized model product is not registered")
    definition = load_chemical_definition(
        registry_entry["product"], registry_entry["stereochemistry"]
    )
    if definition["id"] != geometry_job["product_id"]:
        raise ValueError("chemical definition does not match the optimized model")
    coordinates: dict[str, list[float]] = {}
    elements: dict[str, str] = {}
    for source_key, atom in zip(atom_map, atoms, strict=True):
        key = _canonical_model_key(definition, source_key)
        if key is None:
            continue
        if key in coordinates:
            raise ValueError(f"canonical template atom key is duplicated: {key}")
        element, x, y, z = atom
        coordinates[key] = [x, y, z]
        elements[key] = element
    chirality = audit_product_chirality(definition, coordinates)
    if not chirality["passed"]:
        raise ValueError("candidate template failed the signed stereochemistry audit")
    required_atoms = {
        f"{endpoint}:{name}"
        for endpoint in (1, 2)
        for name in ("C1'", "N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7", "H6")
    }
    if missing := sorted(required_atoms - set(coordinates)):
        raise ValueError("candidate template is missing atoms: " + ", ".join(missing))
    template = {
        "schema": "nadoc.photoproduct-coordinate-template.v1",
        "version": version,
        "product_id": definition["id"],
        "product": definition["product"],
        "stereochemistry": definition["stereochemistry"],
        "release_status": "candidate_unreviewed",
        "gate_effect": "none",
        "units": "angstrom",
        "reflection_allowed": False,
        "ordered_endpoints": [1, 2],
        "fit_anchors": ["1:C1'", "1:N1", "2:C1'", "2:N1"],
        "coordinates": coordinates,
        "elements": elements,
        "chirality_audit": chirality,
        "minimum_audit_summary": {
            "expected_mode_count": frequency_audit["expected_mode_count"],
            "parsed_mode_count": frequency_audit["parsed_mode_count"],
            "imaginary_mode_count": frequency_audit["imaginary_mode_count"],
            "lowest_frequency_cm_inverse": frequency_audit[
                "lowest_frequency_cm_inverse"
            ],
        },
        "placement_safety": {
            "status": "parameter_review_required",
            "parameter_asset_sha256": None,
            "product_ring_bond_ranges_angstrom": [],
            "release_rule": (
                "release review must supply exact bounds for every added and retained "
                "product-ring bond from the matching validated parameter set"
            ),
        },
        "provenance": {
            "optimized_xyz_sha256": _sha256(optimized_path),
            "optimized_model_audit_sha256": geometry_audit_hash,
            "frequency_audit_sha256": _sha256(frequency_audit_path),
            "geometry_job_manifest_sha256": _sha256(geometry_job_path),
            "frequency_job_manifest_sha256": _sha256(frequency_job_path),
            "geometry_protocol_version": geometry_job["protocol_version"],
            "frequency_protocol_version": frequency_job["protocol_version"],
        },
        "release_blockers": [
            "DNA-bound placement thresholds require validation in every claimed context",
            "the product topology and parameters must pass static and NAMD audits",
            "release_review must promote this exact hash; generation cannot self-approve",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(template, indent=2) + "\n")
    return template
