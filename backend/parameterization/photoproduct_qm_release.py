"""Consolidate full d(TpT) optimization/frequency evidence for registry gating."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry


ACCEPTANCE_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_parameter_acceptance.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _load_collection(
    root: Path, *, schema: str, status: str, label: str
) -> tuple[Path, dict[str, Any]]:
    path = root.resolve() / "collection_report.json"
    payload = json.loads(path.read_text())
    if (
        payload.get("schema") != schema
        or payload.get("status") != status
        or payload.get("gate_effect") != "none"
        or payload.get("simulation_ready") is not False
        or payload.get("passed_product_count") != payload.get("product_count")
        or payload.get("product_count") != len(payload.get("products") or [])
    ):
        raise ValueError(f"{label} collection is incomplete or failed: {path}")
    return path, payload


def _optimization_records(roots: list[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for root in roots:
        collection_path, collection = _load_collection(
            root,
            schema="nadoc.photoproduct-alpine-boundary-optimization-collection.v1",
            status="passed_import_and_identity_audit",
            label="optimization",
        )
        for item in collection["products"]:
            product_id = item.get("product_id")
            if product_id in records:
                raise ValueError(f"duplicate optimized product: {product_id}")
            if item.get("status") != "passed_identity_and_chirality":
                raise ValueError(f"{product_id}: optimization did not pass identity/chirality")
            audit_path = _checked(item.get("optimized_model_audit"), f"{product_id} optimization audit")
            records[str(product_id)] = {
                "campaign_root": root.resolve(),
                "collection": _source(collection_path),
                "audit_path": audit_path,
            }
    return records


def _frequency_records(root: Path) -> dict[str, dict[str, Any]]:
    collection_path, collection = _load_collection(
        root,
        schema="nadoc.photoproduct-alpine-boundary-frequency-collection.v1",
        status="passed_harmonic_minimum_audits",
        label="frequency",
    )
    records: dict[str, dict[str, Any]] = {}
    for item in collection["products"]:
        product_id = str(item.get("product_id"))
        if product_id in records:
            raise ValueError(f"duplicate frequency product: {product_id}")
        if item.get("status") != "passed_harmonic_minimum":
            raise ValueError(f"{product_id}: full-boundary frequency audit did not pass")
        records[product_id] = {
            "campaign_root": root.resolve(),
            "collection": _source(collection_path),
            "audit_path": _checked(item.get("frequency_audit"), f"{product_id} frequency audit"),
        }
    return records


def _validate_product(
    *,
    entry: dict[str, Any],
    optimization: dict[str, Any],
    frequency: dict[str, Any],
    registry_path: Path,
    acceptance_policy_path: Path,
) -> dict[str, Any]:
    product_id = entry["id"]
    opt_audit_path = optimization["audit_path"]
    freq_audit_path = frequency["audit_path"]
    opt = json.loads(opt_audit_path.read_text())
    freq = json.loads(freq_audit_path.read_text())
    opt_job_path = (
        optimization["campaign_root"]
        / "bundle"
        / "cases"
        / product_id
        / "job"
        / "job_manifest.json"
    )
    freq_job_path = (
        frequency["campaign_root"]
        / "bundle"
        / "cases"
        / product_id
        / "job"
        / "job_manifest.json"
    )
    opt_job = json.loads(opt_job_path.read_text())
    freq_job = json.loads(freq_job_path.read_text())
    atom_map = opt_job.get("atom_map")
    definition_record = entry["assets"]["chemical_definition"]
    definition_path = (registry_path.parent / definition_record["path"]).resolve()
    if not definition_path.is_file() or _sha256(definition_path) != definition_record["sha256"]:
        raise ValueError(f"{product_id}: chemical definition is missing or hash-mismatched")
    definition = json.loads(definition_path.read_text())
    scope_record = entry["assets"]["patch_charge_scope"]
    scope_path = (registry_path.parent / scope_record["path"]).resolve()
    if not scope_path.is_file() or _sha256(scope_path) != scope_record["sha256"]:
        raise ValueError(f"{product_id}: patch charge scope is missing or hash-mismatched")

    expected_graph = {
        (category, frozenset((bond["atom_1"], bond["atom_2"])))
        for category in ("bonds_added", "bonds_retained")
        for bond in definition["graph_delta"][category]
    }
    observed_graph = {
        (record.get("category"), frozenset((record.get("atom_1"), record.get("atom_2"))))
        for record in opt.get("product_ring_bond_distances") or []
    }
    distances_ok = all(
        isinstance(record.get("distance_angstrom"), (int, float))
        and math.isfinite(float(record["distance_angstrom"]))
        and 1.3 <= float(record["distance_angstrom"]) <= 1.7
        for record in opt.get("product_ring_bond_distances") or []
    )
    stable_identity = (
        opt_job.get("schema") == "nadoc.photoproduct-qm-job.v1"
        and opt_job.get("job_kind") == "geometry_optimization"
        and opt_job.get("product_id") == product_id
        and opt_job.get("atom_count") == 63
        and isinstance(atom_map, list)
        and len(atom_map) == 63
        and len(set(atom_map)) == 63
        and opt.get("schema") == "nadoc.photoproduct-optimized-model-audit.v1"
        and opt.get("status") == "passed_identity_and_chirality"
        and opt.get("atom_count") == 63
        and opt.get("atom_map_unique") is True
        and opt.get("coordinates_finite") is True
    )
    charge_ok = (
        opt_job.get("charge") == -1
        and opt_job.get("multiplicity") == 1
        and entry["graph_delta"].get("atoms_added") == 0
        and entry["graph_delta"].get("atoms_removed") == 0
        and entry["graph_delta"].get("formal_charge_change") == 0
    )
    graph_ok = expected_graph == observed_graph and len(expected_graph) == 4 and distances_ok
    chirality_ok = (
        (opt.get("chirality_audit") or {}).get("passed") is True
        and len((opt.get("chirality_audit") or {}).get("centers") or []) == 4
        and all(
            center.get("passed") is True
            for center in (opt.get("chirality_audit") or {}).get("centers") or []
        )
    )
    energy_ok = isinstance(opt.get("final_energy_hartree"), (int, float)) and math.isfinite(
        float(opt["final_energy_hartree"])
    )
    minimum_ok = (
        freq_job.get("schema") == "nadoc.photoproduct-qm-job.v1"
        and freq_job.get("job_kind") == "frequency"
        and freq_job.get("product_id") == product_id
        and freq_job.get("atom_count") == 63
        and freq_job.get("charge") == -1
        and freq_job.get("atom_map") == atom_map
        and freq.get("schema") == "nadoc.photoproduct-frequency-audit.v1"
        and freq.get("status") == "passed_harmonic_minimum"
        and freq.get("product_id") == product_id
        and freq.get("atom_count") == 63
        and freq.get("expected_mode_count") == 183
        and freq.get("parsed_mode_count") == 183
        and freq.get("frequency_table_complete") is True
        and freq.get("imaginary_mode_count") == 0
        and isinstance(freq.get("lowest_frequency_cm_inverse"), (int, float))
        and float(freq["lowest_frequency_cm_inverse"]) > 0.0
        and (freq.get("cartesian_hessian") or {}).get("status") == "passed"
        and (freq.get("cartesian_hessian") or {}).get("dimension") == 189
        and (freq.get("cartesian_hessian") or {}).get("finite") is True
    )

    checked_paths = {
        "optimization_audit": opt_audit_path,
        "optimization_job": opt_job_path,
        "optimization_run": _checked(opt.get("effective_run_record"), f"{product_id} optimization run"),
        "optimized_xyz": _checked(opt.get("optimized_xyz"), f"{product_id} optimized XYZ"),
        "frequency_audit": freq_audit_path,
        "frequency_job": freq_job_path,
        "frequency_run": _checked(freq.get("effective_run_record"), f"{product_id} frequency run"),
        "frequency_output": _checked(freq.get("output"), f"{product_id} frequency output"),
        "cartesian_hessian": _checked(freq.get("cartesian_hessian"), f"{product_id} Cartesian Hessian"),
        "chemical_definition": definition_path,
        "patch_charge_scope": scope_path,
        "registry": registry_path,
        "acceptance_policy": acceptance_policy_path,
    }
    parent = freq.get("parent_optimized_model_audit") or {}
    provenance_ok = (
        parent.get("sha256") == _sha256(opt_audit_path)
        and opt_job.get("product_id") == freq_job.get("product_id")
        and opt_job.get("model_id") == freq_job.get("model_id")
    )
    checks = {
        "stable_atom_identity_bijective": stable_identity,
        "atom_count_and_charge_conserved": charge_ok,
        "product_graph_exact": graph_ok,
        "stereochemistry_retained": chirality_ok,
        "optimized_minimum_has_no_imaginary_modes": minimum_ok and energy_ok,
        "qm_provenance_and_hashes_complete": provenance_ok,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"{product_id}: QM release checks failed: {', '.join(failed)}")
    return {
        "schema": "nadoc.photoproduct-qm-reference-release-audit.v1",
        "status": "passed",
        "passed": True,
        "gate_effect": "eligible_for_metric_gate_envelope_only",
        "simulation_ready": False,
        "product_id": product_id,
        "product": entry["product"],
        "stereochemistry": entry["stereochemistry"],
        "model_id": opt["model_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "observations": {
            "atom_count": 63,
            "charge": -1,
            "multiplicity": 1,
            "final_energy_hartree": float(opt["final_energy_hartree"]),
            "lowest_frequency_cm_inverse": float(freq["lowest_frequency_cm_inverse"]),
            "imaginary_mode_count": 0,
            "cartesian_hessian_dimension": 189,
            "ring_bond_distances_angstrom": opt["product_ring_bond_distances"],
        },
        "sources": {name: _source(source_path) for name, source_path in checked_paths.items()},
        "collections": {
            "optimization": optimization["collection"],
            "frequency": frequency["collection"],
        },
        "errors": [],
        "remaining_gates": [
            "parameter_fit",
            "topology_patch",
            "coordinate_templates",
            "static_topology_audit",
            "namd_smoke",
            "solution_validation",
            "release_review",
        ],
    }


def build_boundary_qm_release_audits(
    *,
    optimization_campaign_roots: list[Path],
    frequency_campaign_root: Path,
    output_root: Path,
    acceptance_policy_path: Path = ACCEPTANCE_POLICY_PATH,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    """Write all-eight full-boundary QM reports after exact revalidation."""

    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite QM release evidence: {output_root}")
    registry = photoproduct_registry(registry_path)
    policy = json.loads(acceptance_policy_path.read_text())
    if (
        policy.get("schema") != "nadoc.photoproduct-parameter-acceptance.v2"
        or policy.get("version") != "2.1.0"
    ):
        raise ValueError("full-boundary release assembler requires acceptance policy 2.1.0")
    entries = [item for item in registry["products"] if item["product"] == "TT-CPD"]
    expected = {item["id"] for item in entries}
    optimizations = _optimization_records(optimization_campaign_roots)
    frequencies = _frequency_records(frequency_campaign_root)
    if set(optimizations) != expected or set(frequencies) != expected or len(expected) != 8:
        raise ValueError("QM release evidence requires exactly all eight registered TT-CPD products")

    reports: list[dict[str, Any]] = []
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for entry in entries:
        payload = _validate_product(
            entry=entry,
            optimization=optimizations[entry["id"]],
            frequency=frequencies[entry["id"]],
            registry_path=registry_path.resolve(),
            acceptance_policy_path=acceptance_policy_path.resolve(),
        )
        report_path = output_root.resolve() / entry["id"] / "qm_reference_report.json"
        payloads.append((report_path, payload))
    for report_path, payload in payloads:
        report_path.parent.mkdir(parents=True, exist_ok=False)
        report_path.write_text(json.dumps(payload, indent=2) + "\n")
        reports.append(
            {
                "product_id": payload["product_id"],
                "report": _source(report_path),
                "lowest_frequency_cm_inverse": payload["observations"][
                    "lowest_frequency_cm_inverse"
                ],
            }
        )
    index = {
        "schema": "nadoc.photoproduct-all-form-qm-reference-release-audit.v1",
        "status": "passed",
        "passed": True,
        "gate_effect": "eligible_for_metric_gate_envelopes_only",
        "simulation_ready": False,
        "product_count": len(reports),
        "products": reports,
        "registry": _source(registry_path),
        "acceptance_policy": _source(acceptance_policy_path),
        "remaining_work": "Fit and validate product-specific CHARMM parameters and every downstream gate.",
    }
    index_path = output_root.resolve() / "all_form_qm_reference_audit.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    return index
