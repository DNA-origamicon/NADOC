"""Versioned photoproduct parameterization registry and release gates.

The registry records requested chemistry even when no simulation assets exist.
Readiness is derived from evidence gates and verified files; it is never trusted
from a hand-edited ``available`` boolean.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from datetime import datetime, timezone
from typing import Any

REGISTRY_PATH = (
    Path(__file__).parents[1] / "data" / "forcefield" / "photoproduct_registry.json"
)
GATE_STATES = frozenset({"pending", "blocked", "passed"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PATCH_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")
_GATE_REQUIRED_ASSET = {
    "chemical_definition": "chemical_definition",
    "qm_reference_data": "qm_reference_report",
    "parameter_fit": "parameter_fit_report",
    "topology_patch": "topology",
    "coordinate_templates": "coordinate_template",
    "static_topology_audit": "topology_audit_spec",
    "namd_smoke": "namd_smoke_report",
    "solution_validation": "validation_report",
    "release_review": "release_review",
}
_METRIC_GATE_REQUIRED_CHECKS = {
    "qm_reference_data": frozenset(
        {
            "stable_atom_identity_bijective",
            "atom_count_and_charge_conserved",
            "product_graph_exact",
            "stereochemistry_retained",
            "optimized_minimum_has_no_imaginary_modes",
            "qm_provenance_and_hashes_complete",
        }
    ),
    "parameter_fit": frozenset(
        {
            "charge_constraints_passed",
            "training_nonbonded_targets_passed",
            "held_out_nonbonded_targets_passed",
            "training_bonded_targets_passed",
            "held_out_bonded_targets_passed",
            "torsion_targets_passed",
            "parameter_basis_identifiable",
            "parameter_coverage_complete",
        }
    ),
    "topology_patch": frozenset(
        {
            "ordered_patch_identity_exact",
            "product_atom_types_and_charges_complete",
            "bonded_terms_and_parameters_complete",
            "stereochemical_impropers_complete",
            "redistributable_charmm_assets_hash_verified",
        }
    ),
    "coordinate_templates": frozenset(
        {
            "proper_rotation_only",
            "declared_chirality_retained",
            "backbone_and_glycosidic_connectivity_retained",
            "placement_strain_clash_and_piercing_checks_passed",
            "required_contexts_passed",
        }
    ),
    "static_topology_audit": frozenset(
        {
            "atom_identity_and_count_conserved",
            "pair_and_system_charge_conserved",
            "exact_crosslink_delta",
            "expected_types_and_impropers",
            "regenerated_bonded_graph_exact",
            "reverse_identity_mapping_complete",
            "missing_parameters_zero",
        }
    ),
    "namd_smoke": frozenset(
        {
            "real_namd_engine",
            "ordinary_mass_at_most_2fs",
            "all_energies_and_forces_finite",
            "chirality_retained_all_frames",
            "bond_and_clash_safety_ranges_passed",
            "staged_restart_outputs_complete",
            "static_audit_and_assets_hash_linked",
        }
    ),
    "solution_validation": frozenset(
        {
            "required_dna_contexts_complete",
            "matched_reactant_controls_complete",
            "minimum_replicates_and_sampling_complete",
            "finite_stable_ensembles",
            "lesion_backbone_and_stereochemistry_integrity",
            "preregistered_observables_reported",
        }
    ),
    "release_review": frozenset(
        {
            "all_predecessor_evidence_hashes_verified",
            "all_required_assets_verified",
            "acceptance_decision_rule_satisfied",
            "license_and_redistribution_complete",
            "known_limitations_recorded",
        }
    ),
}


class PhotoproductRegistryError(RuntimeError):
    """The parameterization registry is invalid or internally inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON objects instead of silently keeping the last key."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PhotoproductRegistryError(
                f"duplicate JSON key in photoproduct registry: {key!r}"
            )
        result[key] = value
    return result


def _validated_registry(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != "nadoc.photoproduct-registry.v1":
        raise PhotoproductRegistryError("unsupported photoproduct registry schema")
    gates = raw.get("workflow_gates")
    products = raw.get("products")
    if not isinstance(gates, list) or not gates or len(gates) != len(set(gates)):
        raise PhotoproductRegistryError("workflow_gates must be a non-empty unique list")
    if not isinstance(products, list):
        raise PhotoproductRegistryError("products must be a list")

    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    for entry in products:
        if not isinstance(entry, dict):
            raise PhotoproductRegistryError("every product entry must be an object")
        product_id = entry.get("id")
        key = (entry.get("product"), entry.get("stereochemistry"))
        if not all(isinstance(value, str) and value for value in (product_id, *key)):
            raise PhotoproductRegistryError("product id, product, and stereochemistry are required")
        if product_id in seen_ids or key in seen_keys:
            raise PhotoproductRegistryError(f"duplicate photoproduct identity: {product_id!r}")
        seen_ids.add(product_id)
        seen_keys.add(key)

        gate_records = entry.get("gates")
        if not isinstance(gate_records, dict) or set(gate_records) != set(gates):
            raise PhotoproductRegistryError(
                f"{product_id}: gate set must exactly match workflow_gates"
            )
        for gate_name in gates:
            record = gate_records[gate_name]
            if not isinstance(record, dict) or record.get("status") not in GATE_STATES:
                raise PhotoproductRegistryError(
                    f"{product_id}: invalid state for gate {gate_name!r}"
                )
            if not isinstance(record.get("evidence"), list):
                raise PhotoproductRegistryError(
                    f"{product_id}: gate {gate_name!r} evidence must be a list"
                )
    catalog_basis = raw.get("catalog_basis")
    if catalog_basis is not None:
        tt_products = [entry for entry in products if entry["product"] == "TT-CPD"]
        expected_count = catalog_basis.get("design_level_isomer_count")
        if expected_count != 8 or len(tt_products) != expected_count:
            raise PhotoproductRegistryError(
                "ordered DNA TT-CPD catalog must contain exactly eight isomers"
            )
        configurations = []
        for entry in tt_products:
            pair = (entry.get("structural_class") or {}).get(
                "ordered_c5_configurations"
            )
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(value not in {"R", "S"} for value in pair)
            ):
                raise PhotoproductRegistryError(
                    f"{entry['id']}: two ordered C5 configurations are required"
                )
            configurations.append((entry["stereochemistry"], tuple(pair)))
        if len(configurations) != len(set(configurations)):
            raise PhotoproductRegistryError(
                "TT-CPD stereochemistry/C5 configuration records must be unique"
            )
    return raw


def photoproduct_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return _validated_registry(
        json.loads(path.read_text(), object_pairs_hook=_unique_json_object)
    )


def _asset_audit(entry: dict[str, Any], registry_path: Path) -> dict[str, Any]:
    assets = entry.get("assets") or {}
    missing: list[str] = []
    hash_mismatches: list[str] = []
    invalid_metadata: list[str] = []
    checked: list[dict[str, str]] = []
    checked_paths: dict[str, Path] = {}
    for name, record in assets.items():
        if not isinstance(record, dict) or not record.get("path") or not record.get("sha256"):
            missing.append(name)
            continue
        if name == "topology" and not _PATCH_NAME_RE.fullmatch(
            str(record.get("patch_name") or "")
        ):
            invalid_metadata.append(name)
        candidate = (registry_path.parent / record["path"]).resolve()
        try:
            candidate.relative_to(registry_path.parent.resolve())
        except ValueError:
            raise PhotoproductRegistryError(
                f"{entry['id']}: asset {name!r} escapes the force-field directory"
            ) from None
        if not candidate.is_file():
            missing.append(name)
            continue
        actual = _sha256(candidate)
        if actual != record["sha256"]:
            hash_mismatches.append(name)
        else:
            checked_paths[name] = candidate
        checked.append({"name": name, "path": str(candidate), "sha256": actual})
    template_path = checked_paths.get("coordinate_template")
    parameter_record = assets.get("parameters")
    if template_path is not None and isinstance(parameter_record, dict):
        try:
            template = json.loads(template_path.read_text())
        except (OSError, ValueError):
            template = None
        safety = template.get("placement_safety") if isinstance(template, dict) else None
        if (
            not isinstance(template, dict)
            or template.get("schema")
            != "nadoc.photoproduct-coordinate-template.v1"
            or template.get("product_id") != entry["id"]
            or template.get("product") != entry["product"]
            or template.get("stereochemistry") != entry["stereochemistry"]
            or template.get("release_status") != "released"
            or template.get("reflection_allowed") is not False
            or not isinstance(safety, dict)
            or safety.get("schema")
            != "nadoc.photoproduct-placement-safety.v1"
            or safety.get("parameter_asset_sha256") != parameter_record.get("sha256")
        ):
            invalid_metadata.append("coordinate_template")
    trajectory_path = checked_paths.get("help_trajectory")
    smoke_record = assets.get("namd_smoke_report")
    if trajectory_path is not None:
        try:
            trajectory = json.loads(trajectory_path.read_text())
        except (OSError, ValueError):
            trajectory = None
        provenance = (
            trajectory.get("provenance") if isinstance(trajectory, dict) else None
        )
        if (
            not isinstance(trajectory, dict)
            or trajectory.get("schema")
            != "nadoc.photoproduct-help-trajectory.v1"
            or trajectory.get("product_id") != entry["id"]
            or not isinstance(provenance, dict)
            or not isinstance(parameter_record, dict)
            or provenance.get("parameters_sha256")
            != parameter_record.get("sha256")
            or not isinstance(smoke_record, dict)
            or provenance.get("namd_smoke_report_sha256")
            != smoke_record.get("sha256")
        ):
            invalid_metadata.append("help_trajectory")
    return {
        "declared": sorted(assets),
        "checked": checked,
        "missing": missing,
        "hash_mismatches": hash_mismatches,
        "invalid_metadata": invalid_metadata,
        "passed": not missing and not hash_mismatches and not invalid_metadata,
    }


def _capability(entry: dict[str, Any], gates: list[str], registry_path: Path) -> dict[str, Any]:
    gate_status = {name: entry["gates"][name]["status"] for name in gates}
    pending = [name for name in gates if gate_status[name] != "passed"]
    assets = _asset_audit(entry, registry_path)
    required_assets = {
        *_GATE_REQUIRED_ASSET.values(),
        # A fit report is evidence about a parameterization; it is not the
        # loadable CHARMM parameter stream itself.  Require both so catalog
        # readiness cannot get ahead of package-time/NAMD validation.
        "parameters",
        # Kept separate from the immutable structural definition so adding an
        # explicit charge boundary does not invalidate upstream QM provenance.
        "patch_charge_scope",
        # A release-review narrative is not a substitute for explicit redistribution
        # terms for the topology, parameters, template, and derived trajectory.
        "license",
    }
    assets_complete = required_assets.issubset(assets["declared"]) and assets["passed"]
    simulation_ready = not pending and assets_complete
    trajectory_declared = "help_trajectory" in assets["declared"]
    trajectory_verified = trajectory_declared and not (
        {"help_trajectory"}
        & set(
            assets["missing"]
            + assets["hash_mismatches"]
            + assets["invalid_metadata"]
        )
    )
    trajectory_available = trajectory_verified and simulation_ready
    return {
        "id": entry["id"],
        "product": entry["product"],
        "stereochemistry": entry["stereochemistry"],
        "label": entry.get("label", entry["id"]),
        "structural_class": entry.get("structural_class") or {},
        "graph_delta": entry.get("graph_delta") or {},
        "requested_contexts": list(entry.get("requested_contexts") or []),
        "validated_contexts": list(entry.get("validated_contexts") or []),
        "gate_status": gate_status,
        "next_gate": pending[0] if pending else None,
        "simulation_ready": simulation_ready,
        "help_trajectory": {
            "available": trajectory_available,
            "reason": None
            if trajectory_available
            else (
                "real NAMD smoke validation has not passed"
                if gate_status.get("namd_smoke") != "passed"
                else (
                    "product release validation is not complete"
                    if not simulation_ready
                    else "no verified help_trajectory asset is declared"
                )
            ),
        },
        "asset_audit": assets,
        "blockers": [
            *[f"gate not passed: {name}" for name in pending],
            *[f"required asset not declared: {name}" for name in sorted(required_assets - set(assets["declared"]))],
            *[f"asset missing: {name}" for name in assets["missing"]],
            *[f"asset hash mismatch: {name}" for name in assets["hash_mismatches"]],
            *[f"asset metadata invalid: {name}" for name in assets["invalid_metadata"]],
        ],
        "references": list(entry.get("references") or []),
    }


def photoproduct_help_trajectory(
    product_id: str, *, path: Path = REGISTRY_PATH
) -> dict[str, Any]:
    """Load a hash-verified NAMD trajectory only after its smoke gate passes."""

    registry = photoproduct_registry(path)
    entry = next((item for item in registry["products"] if item["id"] == product_id), None)
    if entry is None:
        raise KeyError(f"unregistered photoproduct id: {product_id}")
    capability = _capability(entry, registry["workflow_gates"], path)
    if not capability["help_trajectory"]["available"]:
        raise PhotoproductRegistryError(
            f"{product_id}: help trajectory unavailable: "
            f"{capability['help_trajectory']['reason']}"
        )
    record = entry["assets"]["help_trajectory"]
    candidate = (path.parent / record["path"]).resolve()
    if not candidate.is_file() or _sha256(candidate) != record.get("sha256"):
        raise PhotoproductRegistryError(
            f"{product_id}: help trajectory changed after capability audit"
        )
    payload = json.loads(candidate.read_text())
    if payload.get("schema") != "nadoc.photoproduct-help-trajectory.v1":
        raise PhotoproductRegistryError(
            f"{product_id}: unsupported help trajectory schema"
        )
    if payload.get("product_id") != product_id:
        raise PhotoproductRegistryError(
            f"{product_id}: trajectory product identity does not match"
        )
    atom_keys = payload.get("atom_keys")
    elements = payload.get("elements")
    frames = payload.get("frames")
    bonds = payload.get("bonds")
    provenance = payload.get("provenance")
    required_provenance = {
        "engine",
        "source_dcd_sha256",
        "topology_sha256",
        "parameters_sha256",
        "static_topology_audit_sha256",
        "namd_smoke_report_sha256",
    }
    if (
        payload.get("units") != "angstrom"
        or not isinstance(atom_keys, list)
        or not atom_keys
        or len(atom_keys) != len(set(atom_keys))
        or not isinstance(elements, list)
        or len(elements) != len(atom_keys)
        or any(element not in {"H", "C", "N", "O", "P", "S"} for element in elements)
        or not isinstance(frames, list)
        or len(frames) < 2
        or not isinstance(payload.get("timestep_fs"), (int, float))
        or not 0 < payload["timestep_fs"] <= 2.0
        or not isinstance(payload.get("stride_steps"), int)
        or payload["stride_steps"] < 1
        or not isinstance(bonds, list)
        or any(
            not isinstance(bond, list)
            or len(bond) != 2
            or not all(isinstance(index, int) for index in bond)
            or not all(0 <= index < len(atom_keys) for index in bond)
            or bond[0] == bond[1]
            for bond in bonds
        )
        or len({tuple(sorted(bond)) for bond in bonds}) != len(bonds)
        or not isinstance(provenance, dict)
        or not required_provenance.issubset(provenance)
        or not isinstance(provenance.get("engine"), str)
        or "NAMD" not in provenance["engine"].upper()
        or any(
            not isinstance(provenance.get(field), str)
            or not re.fullmatch(r"[0-9a-f]{64}", provenance[field])
            for field in required_provenance - {"engine"}
        )
        or any(
            not isinstance(frame, list)
            or len(frame) != len(atom_keys)
            or any(
                not isinstance(xyz, list)
                or len(xyz) != 3
                or not all(
                    isinstance(value, (int, float)) and math.isfinite(float(value))
                    for value in xyz
                )
                for xyz in frame
            )
            for frame in frames
        )
        or not isinstance(payload.get("source_frame_indices"), list)
        or len(payload["source_frame_indices"]) != len(frames)
        or any(
            not isinstance(index, int) or index < 0
            for index in payload["source_frame_indices"]
        )
        or payload["source_frame_indices"] != sorted(set(payload["source_frame_indices"]))
    ):
        raise PhotoproductRegistryError(
            f"{product_id}: malformed help trajectory atom/frame arrays"
        )
    return payload


def photoproduct_capabilities(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = photoproduct_registry(path)
    products = [
        _capability(entry, registry["workflow_gates"], path)
        for entry in registry["products"]
    ]
    return {
        "schema": "nadoc.photoproduct-capabilities.v1",
        "registry_schema": registry["schema"],
        "registry_path": str(path),
        "registry_sha256": _sha256(path),
        "forcefield_target": registry["forcefield_target"],
        "workflow_gates": registry["workflow_gates"],
        "products": products,
        "all_simulation_ready": bool(products) and all(
            item["simulation_ready"] for item in products
        ),
    }


def photoproduct_capability(
    product: str, stereochemistry: str, *, path: Path = REGISTRY_PATH
) -> dict[str, Any]:
    catalog = photoproduct_capabilities(path)
    for item in catalog["products"]:
        if item["product"] == product and item["stereochemistry"] == stereochemistry:
            return item
    raise KeyError(f"unregistered photoproduct: {product}/{stereochemistry}")


def registered_stereochemistries(
    product: str, *, path: Path = REGISTRY_PATH
) -> tuple[str, ...]:
    registry = photoproduct_registry(path)
    return tuple(
        entry["stereochemistry"]
        for entry in registry["products"]
        if entry["product"] == product
    )


def request_photoproduct(
    *,
    product_id: str,
    product: str,
    stereochemistry: str,
    label: str,
    requested_contexts: list[str] | None = None,
    path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    """Append a definition-pending product request without weakening any gate."""
    if not _ID_RE.fullmatch(product_id):
        raise ValueError("product_id must be a lowercase kebab-case identifier")
    if not all(value.strip() for value in (product, stereochemistry, label)):
        raise ValueError("product, stereochemistry, and label are required")
    registry = photoproduct_registry(path)
    if any(
        entry["id"] == product_id
        or (
            entry["product"] == product
            and entry["stereochemistry"] == stereochemistry
        )
        for entry in registry["products"]
    ):
        raise ValueError(f"photoproduct request already exists: {product_id}")
    entry = {
        "id": product_id,
        "product": product,
        "stereochemistry": stereochemistry,
        "label": label,
        "structural_class": {},
        "graph_delta": {},
        "requested_contexts": list(requested_contexts or []),
        "validated_contexts": [],
        "references": [],
        "gates": {
            name: {"status": "pending", "evidence": []}
            for name in registry["workflow_gates"]
        },
        "assets": {},
    }
    registry["products"].append(entry)
    _validated_registry(registry)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, indent=2) + "\n")
    temporary.replace(path)
    return entry


def _entry_by_id(registry: dict[str, Any], product_id: str) -> dict[str, Any]:
    entry = next((item for item in registry["products"] if item["id"] == product_id), None)
    if entry is None:
        raise KeyError(f"unregistered photoproduct id: {product_id}")
    return entry


def _atomic_registry_write(registry: dict[str, Any], path: Path) -> None:
    _validated_registry(registry)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, indent=2) + "\n")
    temporary.replace(path)


def attach_photoproduct_asset(
    *,
    product_id: str,
    kind: str,
    asset_path: Path,
    patch_name: str | None = None,
    path: Path = REGISTRY_PATH,
) -> dict[str, str]:
    """Attach one already-curated, in-tree asset by immutable relative path/hash."""

    registry = photoproduct_registry(path)
    entry = _entry_by_id(registry, product_id)
    forcefield_root = path.parent.resolve()
    candidate = asset_path.resolve()
    try:
        relative = candidate.relative_to(forcefield_root)
    except ValueError:
        raise ValueError(
            f"asset must already be curated under {forcefield_root}; got {candidate}"
        ) from None
    if not candidate.is_file():
        raise FileNotFoundError(f"photoproduct asset does not exist: {candidate}")
    if not kind or not _ID_RE.fullmatch(kind.replace("_", "-")):
        raise ValueError("asset kind must be a lowercase identifier")
    record = {"path": relative.as_posix(), "sha256": _sha256(candidate)}
    if kind == "topology":
        if not isinstance(patch_name, str) or not _PATCH_NAME_RE.fullmatch(patch_name):
            raise ValueError(
                "a topology asset requires its 1-8 character uppercase CHARMM patch name"
            )
        record["patch_name"] = patch_name
    elif patch_name is not None:
        raise ValueError("patch_name is valid only for a topology asset")
    existing = (entry.get("assets") or {}).get(kind)
    if existing is not None and existing != record:
        raise ValueError(
            f"{product_id} already declares a different {kind!r} asset; remove or review "
            "the old declaration explicitly before replacement"
        )
    entry.setdefault("assets", {})[kind] = record
    _atomic_registry_write(registry, path)
    return record


def record_photoproduct_gate_review(
    *,
    product_id: str,
    gate: str,
    status: str,
    reviewer: str,
    rationale: str,
    evidence_path: Path | None = None,
    path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    """Record a human review without allowing quantitative gates to pass.

    Human review may pass only ``chemical_definition``, where identity, graph, ordered
    atom mapping, and stereochemical intent are the review subject.  Every later gate is
    quantitative or engine-backed and must be promoted through its machine-evidence
    validator.  Human review may mark any gate blocked for diagnosis.  This command never
    generates scientific evidence and never infers a pass from a successful program exit.
    """

    if status not in {"passed", "blocked"}:
        raise ValueError("review status must be 'passed' or 'blocked'")
    if not reviewer.strip() or not rationale.strip():
        raise ValueError("reviewer and rationale are required")
    registry = photoproduct_registry(path)
    if gate not in registry["workflow_gates"]:
        raise ValueError(f"unknown workflow gate: {gate}")
    entry = _entry_by_id(registry, product_id)
    gate_index = registry["workflow_gates"].index(gate)
    if status == "passed":
        predecessors = registry["workflow_gates"][:gate_index]
        unpassed = [
            name for name in predecessors if entry["gates"][name]["status"] != "passed"
        ]
        if unpassed:
            raise ValueError(
                f"cannot pass {gate} before predecessor gates: {', '.join(unpassed)}"
            )
        if gate != "chemical_definition":
            raise ValueError(
                f"cannot pass {gate} by human review: use the gate-specific "
                "machine-evidence validator; visual approval has no release effect"
            )
        required_asset = _GATE_REQUIRED_ASSET[gate]
        if required_asset not in (entry.get("assets") or {}):
            raise ValueError(
                f"cannot pass {gate}: attach the curated {required_asset!r} asset first"
            )
        asset_audit = _asset_audit(entry, path)
        unusable = set(
            asset_audit["missing"]
            + asset_audit["hash_mismatches"]
            + asset_audit["invalid_metadata"]
        )
        if required_asset in unusable:
            raise ValueError(
                f"cannot pass {gate}: curated {required_asset!r} asset is missing, "
                "hash-mismatched, or has invalid metadata"
            )
        if evidence_path is None:
            raise ValueError("a passed gate requires a review evidence file")
        if gate == "chemical_definition":
            # Import lazily because the chemistry loader itself uses this registry.
            from backend.core.photoproduct_chemistry import (
                chemical_definition_registry_graph,
                load_chemical_definition,
            )

            definition = load_chemical_definition(
                entry["product"], entry["stereochemistry"], registry_path=path
            )
            reviewed_graph = chemical_definition_registry_graph(definition)
            registered_graph = entry.get("graph_delta") or {}
            if registered_graph and registered_graph != reviewed_graph:
                raise ValueError(
                    "cannot pass chemical_definition: reviewed definition graph does "
                    "not match the registry graph"
                )
            # A new product request begins without an asserted graph. The explicit
            # human pass is the point at which its validated, hash-pinned definition
            # becomes the compact registry identity.
            if not registered_graph:
                entry["graph_delta"] = reviewed_graph
    evidence: dict[str, Any] = {
        "reviewer": reviewer.strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "rationale": rationale.strip(),
    }
    if evidence_path is not None:
        candidate = evidence_path.resolve()
        root = path.parent.resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            raise ValueError(
                f"review evidence must already be curated under {root}; got {candidate}"
            ) from None
        if not candidate.is_file():
            raise FileNotFoundError(f"review evidence does not exist: {candidate}")
        evidence["path"] = relative.as_posix()
        evidence["sha256"] = _sha256(candidate)
    entry["gates"][gate] = {"status": status, "evidence": [evidence]}
    _atomic_registry_write(registry, path)
    return entry["gates"][gate]


def record_photoproduct_metric_gate(
    *,
    product_id: str,
    gate: str,
    evidence_path: Path,
    acceptance_policy_path: Path,
    path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    """Promote one non-identity gate from a curated machine-evidence envelope.

    This is deliberately a verifier, not a report generator.  The scientific stage that
    owns a metric must first emit its own audit; a compact release envelope then names
    every required check and hash-links those source audits, the current acceptance
    policy, and the gate's required registry asset.  Missing checks, mutable sources, a
    failed source decision, or an unsupported gate all fail closed.
    """

    registry = photoproduct_registry(path)
    if gate not in registry["workflow_gates"]:
        raise ValueError(f"unknown workflow gate: {gate}")
    if gate == "chemical_definition":
        raise ValueError(
            "chemical_definition is an identity review; use record_photoproduct_gate_review"
        )
    required_checks = _METRIC_GATE_REQUIRED_CHECKS.get(gate)
    if required_checks is None:
        raise ValueError(f"no machine-evidence validator is defined for gate {gate}")
    entry = _entry_by_id(registry, product_id)
    gate_index = registry["workflow_gates"].index(gate)
    unpassed = [
        name
        for name in registry["workflow_gates"][:gate_index]
        if entry["gates"][name]["status"] != "passed"
    ]
    if unpassed:
        raise ValueError(
            f"cannot pass {gate} before predecessor gates: {', '.join(unpassed)}"
        )

    root = path.parent.resolve()

    def curated_file(candidate: Path, *, label: str) -> tuple[Path, str]:
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            raise ValueError(
                f"{label} must already be curated under {root}; got {resolved}"
            ) from None
        if not resolved.is_file():
            raise FileNotFoundError(f"{label} does not exist: {resolved}")
        return resolved, relative

    policy_file, policy_relative = curated_file(
        acceptance_policy_path, label="acceptance policy"
    )
    policy = json.loads(policy_file.read_text(), object_pairs_hook=_unique_json_object)
    if (
        not isinstance(policy, dict)
        or policy.get("schema") != "nadoc.photoproduct-parameter-acceptance.v2"
        or not isinstance(policy.get("decision_rule"), str)
        or not policy["decision_rule"].strip()
    ):
        raise ValueError("unsupported or incomplete photoproduct acceptance policy")
    policy_sha256 = _sha256(policy_file)

    evidence_file, evidence_relative = curated_file(
        evidence_path, label="metric-gate evidence"
    )
    evidence = json.loads(
        evidence_file.read_text(), object_pairs_hook=_unique_json_object
    )
    required_asset = _GATE_REQUIRED_ASSET[gate]
    asset_record = (entry.get("assets") or {}).get(required_asset)
    if not isinstance(asset_record, dict):
        raise ValueError(
            f"cannot pass {gate}: attach the curated {required_asset!r} asset first"
        )
    audit = _asset_audit(entry, path)
    unusable = set(
        audit["missing"] + audit["hash_mismatches"] + audit["invalid_metadata"]
    )
    if required_asset in unusable:
        raise ValueError(
            f"cannot pass {gate}: curated {required_asset!r} asset is unusable"
        )

    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != "nadoc.photoproduct-metric-gate-evidence.v1"
        or evidence.get("product_id") != product_id
        or evidence.get("product") != entry["product"]
        or evidence.get("stereochemistry") != entry["stereochemistry"]
        or evidence.get("gate") != gate
        or evidence.get("decision") != "passed"
        or evidence.get("errors") != []
    ):
        raise ValueError(
            "metric-gate evidence identity, decision, or error record is invalid"
        )
    policy_record = evidence.get("acceptance_policy")
    if policy_record != {"path": policy_relative, "sha256": policy_sha256}:
        raise ValueError("metric-gate evidence does not pin the current acceptance policy")
    if evidence.get("required_asset") != {
        "kind": required_asset,
        "path": asset_record.get("path"),
        "sha256": asset_record.get("sha256"),
    }:
        raise ValueError("metric-gate evidence does not pin the current required asset")

    producer = evidence.get("producer")
    if (
        not isinstance(producer, dict)
        or not all(
            isinstance(producer.get(field), str) and producer[field].strip()
            for field in ("name", "version", "command")
        )
    ):
        raise ValueError("metric-gate evidence requires producer name, version, and command")
    if not isinstance(evidence.get("generated_at"), str) or not evidence[
        "generated_at"
    ].strip():
        raise ValueError("metric-gate evidence requires generated_at")

    sources = evidence.get("source_files")
    if not isinstance(sources, list) or not sources:
        raise ValueError("metric-gate evidence requires hash-pinned source files")
    source_hashes: set[str] = set()
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("every metric-gate source must be an object")
        source_id = source.get("id")
        source_path = source.get("path")
        source_sha256 = source.get("sha256")
        source_schema = source.get("schema")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in source_ids
            or not isinstance(source_path, str)
            or not source_path
            or not isinstance(source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
            or not isinstance(source_schema, str)
            or not source_schema.startswith("nadoc.photoproduct-")
        ):
            raise ValueError("metric-gate source identity, schema, or hash is invalid")
        source_file, source_relative = curated_file(
            root / source_path, label=f"metric-gate source {source_id!r}"
        )
        if source_relative != source_path or _sha256(source_file) != source_sha256:
            raise ValueError(f"metric-gate source {source_id!r} hash/path mismatch")
        source_payload = json.loads(
            source_file.read_text(), object_pairs_hook=_unique_json_object
        )
        if not isinstance(source_payload, dict) or source_payload.get("schema") != source_schema:
            raise ValueError(f"metric-gate source {source_id!r} schema mismatch")
        if source_payload.get("passed") is not True and source_payload.get("status") != "passed":
            raise ValueError(
                f"metric-gate source {source_id!r} does not declare a passed decision"
            )
        if source_payload.get("errors") not in (None, []):
            raise ValueError(f"metric-gate source {source_id!r} declares errors")
        source_ids.add(source_id)
        source_hashes.add(source_sha256)

    checks = evidence.get("checks")
    if not isinstance(checks, list):
        raise ValueError("metric-gate evidence checks must be a list")
    check_ids: set[str] = set()
    for check in checks:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("id"), str)
            or not check["id"]
            or check["id"] in check_ids
            or check.get("passed") is not True
            or check.get("automated") is not True
            or check.get("source_sha256") not in source_hashes
        ):
            raise ValueError(
                "every metric-gate check must be unique, automated, passed, and source-linked"
            )
        check_ids.add(check["id"])
    missing_checks = sorted(required_checks - check_ids)
    if missing_checks:
        raise ValueError(
            f"metric-gate evidence is missing required checks: {', '.join(missing_checks)}"
        )

    record = {
        "decision_kind": "automated-metrics",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "path": evidence_relative,
        "sha256": _sha256(evidence_file),
        "acceptance_policy_sha256": policy_sha256,
        "source_sha256": sorted(source_hashes),
    }
    entry["gates"][gate] = {"status": "passed", "evidence": [record]}
    _atomic_registry_write(registry, path)
    return entry["gates"][gate]
