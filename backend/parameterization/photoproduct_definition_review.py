"""Build a human-review packet for all noncanonical TT-CPD definitions."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DECISIONS = frozenset({"APPROVE", "REJECT", "REVISE"})
_RELEASE_FORBIDDEN_FIELDS = frozenset(
    {
        "candidate_evidence",
        "gate_effect",
        "patch_charge_scope",
        "release_blockers",
        "requested_contexts",
        "status",
    }
)
_CHEMICAL_IDENTITY_FIELDS = (
    "state",
    "ordered_endpoints",
    "graph_delta",
    "precursor_local_connectivity",
    "product_stereocenters",
    "source_ring_coordinates_angstrom",
    "model_compounds",
    "minimum_geometry_evidence",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(
    record: object, label: str, *, fallback_paths: Sequence[Path] = ()
) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} reference is missing")
    expected = record.get("sha256")
    embedded = Path(str(record.get("path") or ""))
    candidates = [*fallback_paths, embedded]
    for path in candidates:
        if path.is_file() and _sha256(path) == expected:
            return path.resolve()
    raise ValueError(f"{label} is missing or hash-mismatched")


def _load_frequency_audits(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        audit = json.loads(path.read_text())
        product_id = str(audit.get("product_id") or "")
        if (
            audit.get("schema") != "nadoc.photoproduct-frequency-audit.v1"
            or audit.get("status") != "passed_candidate_harmonic_minimum"
            or audit.get("gate_effect") != "none"
            or not product_id
        ):
            raise ValueError(f"{path}: a passed gate-neutral candidate frequency audit is required")
        if product_id in records:
            raise ValueError(f"duplicate frequency audit for {product_id}")
        hessian = audit.get("cartesian_hessian") or {}
        if hessian.get("status") != "passed" or hessian.get("units") != "hartree/bohr^2":
            raise ValueError(f"{path}: Cartesian Hessian audit is incomplete")
        records[product_id] = {
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "status": audit["status"],
            "imaginary_mode_count": audit.get("imaginary_mode_count"),
            "lowest_frequency_cm_inverse": audit.get("lowest_frequency_cm_inverse"),
            "cartesian_hessian_sha256": hessian.get("sha256"),
        }
    return records


def _load_equivalent_hessian_references(
    paths: Sequence[Path],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        reference = json.loads(path.read_text())
        target_id = str(reference.get("target_product_id") or "")
        source = reference.get("source_frequency") or {}
        frequency_record = source.get("frequency_audit") or {}
        hessian_record = source.get("cartesian_hessian") or {}
        geometry_record = source.get("source_geometry") or {}
        equivalence_record = reference.get("equivalence_audit") or {}
        if (
            reference.get("schema")
            != "nadoc.photoproduct-equivalent-hessian-reference.v1"
            or reference.get("status") != "passed_candidate_reuse_preconditions"
            or reference.get("passed") is not True
            or reference.get("gate_effect") != "none"
            or reference.get("coordinate_frame")
            != "source-retained-no-tensor-rotation"
            or not target_id
        ):
            raise ValueError(f"{path}: a passed equivalent-Hessian reference is required")
        if target_id in records:
            raise ValueError(f"duplicate equivalent-Hessian reference for {target_id}")
        frequency_path = _checked(frequency_record, f"{target_id} source frequency audit")
        hessian_path = _checked(hessian_record, f"{target_id} source Cartesian Hessian")
        geometry_path = _checked(geometry_record, f"{target_id} source geometry")
        equivalence_path = _checked(
            equivalence_record, f"{target_id} endpoint equivalence audit"
        )
        frequency = json.loads(frequency_path.read_text())
        equivalence = json.loads(equivalence_path.read_text())
        source_map = reference.get("source_atom_map")
        target_map = reference.get("target_atom_map_in_source_matrix_order")
        if (
            frequency.get("schema") != "nadoc.photoproduct-frequency-audit.v1"
            or frequency.get("status")
            not in {"passed_harmonic_minimum", "passed_candidate_harmonic_minimum"}
            or frequency.get("product_id") != reference.get("source_product_id")
            or frequency.get("imaginary_mode_count") != 0
            or ((frequency.get("cartesian_hessian") or {}).get("sha256"))
            != _sha256(hessian_path)
            or equivalence.get("schema")
            != "nadoc.photoproduct-model-equivalence-audit.v1"
            or equivalence.get("status") != "passed_candidate_model_equivalence"
            or equivalence.get("passed") is not True
            or equivalence.get("product_ids")
            != [reference.get("source_product_id"), target_id]
            or not isinstance(source_map, list)
            or not isinstance(target_map, list)
            or len(source_map) != len(target_map)
            or not source_map
            or len(source_map) != len(set(source_map))
            or len(target_map) != len(set(target_map))
        ):
            raise ValueError(f"{path}: equivalent-Hessian evidence is inconsistent")
        records[target_id] = {
            "status": "passed_equivalent_source_candidate",
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "source_product_id": reference["source_product_id"],
            "source_frequency_status": frequency["status"],
            "source_frequency_audit_sha256": _sha256(frequency_path),
            "source_cartesian_hessian_sha256": _sha256(hessian_path),
            "source_geometry_sha256": _sha256(geometry_path),
            "equivalence_audit_sha256": _sha256(equivalence_path),
            "coordinate_frame": reference["coordinate_frame"],
        }
    return records


def _render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# TT-CPD atom-mapped chemical-definition review packet",
        "",
        "> This packet is evidence for a human decision. It does not approve a definition,",
        "> change a registry gate, or authorize force-field use.",
        "",
        "## Candidate comparison",
        "",
        "| Product ID | Orientation | C5 pair | C6 pair | Crosslinks | Open Babel InChIKey | QM minimum | Definition coordinates |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in packet["candidates"]:
        centers = {record["atom"]: record for record in item["product_stereocenters"]}
        c5 = "/".join(
            str(centers[key]["ccd_configuration"]) for key in ("1:C5", "2:C5")
        )
        c6 = "/".join(
            str(centers[key]["ccd_configuration"]) for key in ("1:C6", "2:C6")
        )
        crosslinks = ", ".join(
            f"{record['atom_1']}–{record['atom_2']}" for record in item["bonds_added"]
        )
        frequency = item["frequency_evidence"]
        if frequency.get("status") == "passed_candidate_harmonic_minimum":
            frequency_text = (
                f"passed; {frequency['imaginary_mode_count']} imaginary; "
                f"lowest {frequency['lowest_frequency_cm_inverse']:.4f} cm⁻¹"
            )
        elif frequency.get("status") == "passed_equivalent_source_candidate":
            frequency_text = (
                "audited endpoint-exchange reuse from "
                f"{frequency['source_product_id']}; no independent run"
            )
        else:
            frequency_text = "not supplied"
        minimum_kind = (item.get("minimum_geometry_evidence") or {}).get("kind")
        coordinate_text = {
            "direct_candidate_harmonic_minimum": "direct audited minimum",
            "audited_endpoint_exchange_equivalent_minimum": (
                "audited endpoint-exchange equivalent minimum"
            ),
        }.get(minimum_kind, "initial candidate embedding")
        lines.append(
            "| "
            + " | ".join(
                (
                    item["product_id"],
                    item["orientation"],
                    c5,
                    c6,
                    crosslinks,
                    item["openbabel"]["inchikey"],
                    frequency_text,
                    coordinate_text,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Required atom-mapped checks",
            "",
            "For every row, an independent reviewer must check:",
            "",
            "- [ ] ordered endpoint convention and cited product name;",
            "- [ ] one-to-one precursor/product atom mapping and conserved formal charge;",
            "- [ ] the two declared crosslinks and both retained intrabase C5–C6 bonds;",
            "- [ ] all four C5/C6 absolute configurations, including the Roman numeral;",
            "- [ ] protonation, tautomer, and ordered N1 sugar-attachment sites;",
            "- [ ] agreement of the RDKit graph with the independent Open Babel record;",
            "- [ ] the definition-coordinate evidence maps the exact stable atom keys to the declared minimum without reflection;",
            "- [ ] no use of the candidate coordinates as a validated DNA template.",
            "",
            "## Per-product decisions",
            "",
        ]
    )
    for item in packet["candidates"]:
        lines.extend(
            [
                f"### {item['product_id']}",
                "",
                "- Decision: `APPROVE` / `REJECT` / `REVISE`",
                "- Reviewer:",
                "- Date:",
                "- Atom-mapped rationale:",
                "- Evidence or corrected definition SHA-256:",
                "",
            ]
        )
    lines.extend(
        [
            "## Release boundary",
            "",
            "A completed packet is not a force-field release. Each approved definition still",
            "requires its reviewed asset attachment, QM/model-boundary evidence, parameter fit,",
            "real psfgen/NAMD validation, context validation, and independent final release review.",
            "",
        ]
    )
    return "\n".join(lines)


def build_tt_cpd_definition_review_packet(
    *,
    definition_candidate_paths: Sequence[Path],
    candidate_audit_path: Path,
    independent_audit_path: Path,
    frequency_audit_paths: Sequence[Path],
    output_dir: Path,
    equivalent_hessian_reference_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    """Hash-audit and collate all seven definition candidates for human review."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite definition review packet: {output_dir}")
    registry = photoproduct_registry()
    expected_entries = {
        item["id"]: item
        for item in registry["products"]
        if item["product"] == "TT-CPD" and item["stereochemistry"] != "cis-syn"
    }
    candidate_audit = json.loads(candidate_audit_path.read_text())
    independent_audit = json.loads(independent_audit_path.read_text())
    if (
        candidate_audit.get("schema") != "nadoc.tt-cpd-stereo-candidate-audit.v1"
        or candidate_audit.get("status") != "passed_candidate"
        or candidate_audit.get("passed") is not True
        or candidate_audit.get("gate_effect") != "none"
    ):
        raise ValueError("a passed gate-neutral candidate series audit is required")
    if (
        independent_audit.get("schema") != "nadoc.tt-cpd-openbabel-stereo-audit.v1"
        or independent_audit.get("status")
        != "software_crosscheck_passed_human_review_required"
        or independent_audit.get("passed") is not True
        or independent_audit.get("gate_effect") != "none"
        or (independent_audit.get("candidate_audit") or {}).get("sha256")
        != _sha256(candidate_audit_path)
    ):
        raise ValueError("a matching passed Open Babel stereo audit is required")
    series_records = {
        item["product_id"]: item for item in candidate_audit.get("candidates") or []
    }
    independent_records = {
        item["product_id"]: item for item in independent_audit.get("records") or []
    }
    frequency_records = _load_frequency_audits(frequency_audit_paths)
    equivalent_frequency_records = _load_equivalent_hessian_references(
        equivalent_hessian_reference_paths
    )

    definitions: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in definition_candidate_paths:
        definition = json.loads(path.read_text())
        product_id = str(definition.get("id") or "")
        if product_id in definitions:
            raise ValueError(f"duplicate definition candidate for {product_id}")
        definitions[product_id] = (path.resolve(), definition)
    if set(definitions) != set(expected_entries):
        raise ValueError(
            "definition candidates must cover exactly the seven noncanonical TT-CPDs"
        )
    unexpected_frequency = set(frequency_records) - set(expected_entries)
    if unexpected_frequency:
        raise ValueError(
            f"frequency audits include unexpected products: {sorted(unexpected_frequency)}"
        )
    unexpected_equivalent = set(equivalent_frequency_records) - set(expected_entries)
    if unexpected_equivalent:
        raise ValueError(
            "equivalent-Hessian references include unexpected products: "
            f"{sorted(unexpected_equivalent)}"
        )
    overlap = set(frequency_records) & set(equivalent_frequency_records)
    if overlap:
        raise ValueError(
            f"products have both direct and equivalent Hessian evidence: {sorted(overlap)}"
        )

    candidates: list[dict[str, Any]] = []
    for product_id, entry in expected_entries.items():
        path, definition = definitions[product_id]
        if (
            definition.get("schema")
            != "nadoc.photoproduct-chemical-definition-candidate.v1"
            or definition.get("status") != "review_required"
            or definition.get("gate_effect") != "none"
            or definition.get("product") != "TT-CPD"
            or definition.get("stereochemistry") != entry["stereochemistry"]
        ):
            raise ValueError(f"{product_id}: definition candidate identity/status is invalid")
        evidence = definition.get("candidate_evidence") or {}
        manifest_path = _checked(
            evidence.get("manifest"),
            f"{product_id} candidate manifest",
            fallback_paths=(
                candidate_audit_path.parent / product_id / "candidate_manifest.json",
            ),
        )
        _checked(
            evidence.get("series_audit"),
            f"{product_id} series audit",
            fallback_paths=(candidate_audit_path,),
        )
        _checked(
            evidence.get("independent_stereo_audit"),
            f"{product_id} independent audit",
            fallback_paths=(independent_audit_path,),
        )
        manifest = json.loads(manifest_path.read_text())
        series_record = series_records.get(product_id) or {}
        independent_record = independent_records.get(product_id) or {}
        if (
            manifest.get("schema") != "nadoc.tt-cpd-stereo-candidate.v1"
            or manifest.get("product_id") != product_id
            or series_record.get("passed") is not True
            or series_record.get("manifest_sha256") != _sha256(manifest_path)
            or independent_record.get("sdf_sha256")
            != ((manifest.get("outputs") or {}).get("sdf") or {}).get("sha256")
        ):
            raise ValueError(f"{product_id}: candidate/audit records do not match")
        outputs = {
            name: {
                "path": str(
                    _checked(
                        record,
                        f"{product_id} {name}",
                        fallback_paths=(
                            manifest_path.parent
                            / Path(str(record.get("path") or "")).name,
                        ),
                    )
                ),
                "sha256": record["sha256"],
            }
            for name, record in (manifest.get("outputs") or {}).items()
        }
        centers = definition.get("product_stereocenters") or []
        if {item.get("atom") for item in centers} != {
            "1:C5",
            "1:C6",
            "2:C5",
            "2:C6",
        }:
            raise ValueError(f"{product_id}: four ordered product stereocenters are required")
        bonds_added = (definition.get("graph_delta") or {}).get("bonds_added") or []
        observed_bonds = {
            f"{item.get('atom_1')}--{item.get('atom_2')}" for item in bonds_added
        }
        if observed_bonds != set(entry["graph_delta"]["bonds_added"]):
            raise ValueError(f"{product_id}: crosslinks differ from the registry")
        _validate_minimum_geometry_evidence(definition)
        candidates.append(
            {
                "product_id": product_id,
                "stereochemistry": definition["stereochemistry"],
                "orientation": entry["structural_class"]["double_bond_orientation"],
                "ordered_c5_configurations": entry["structural_class"][
                    "ordered_c5_configurations"
                ],
                "product_stereocenters": centers,
                "bonds_added": bonds_added,
                "bonds_retained": (definition.get("graph_delta") or {}).get(
                    "bonds_retained"
                ),
                "openbabel": {
                    "canonical_isomeric_smiles": independent_record.get(
                        "canonical_isomeric_smiles"
                    ),
                    "inchikey": independent_record.get("inchikey"),
                    "constitutional_inchikey_block": independent_record.get(
                        "constitutional_inchikey_block"
                    ),
                },
                "frequency_evidence": frequency_records.get(product_id)
                or equivalent_frequency_records.get(product_id)
                or {"status": "not_supplied"},
                "minimum_geometry_evidence": definition.get(
                    "minimum_geometry_evidence"
                )
                or {"kind": "not_supplied"},
                "definition_candidate": {
                    "path": str(path),
                    "sha256": _sha256(path),
                },
                "candidate_manifest": {
                    "path": str(manifest_path),
                    "sha256": _sha256(manifest_path),
                },
                "candidate_outputs": outputs,
                "human_decision": {
                    "decision": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "atom_mapped_rationale": None,
                    "evidence_or_corrected_definition_sha256": None,
                },
            }
        )

    packet = {
        "schema": "nadoc.tt-cpd-definition-human-review-packet.v1",
        "status": "human_review_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "candidate_count": len(candidates),
        "all_required_candidates_present": len(candidates) == 7,
        "candidates": candidates,
        "sources": {
            "registry": {
                "path": str(REGISTRY_PATH.resolve()),
                "sha256": _sha256(REGISTRY_PATH),
            },
            "candidate_audit": {
                "path": str(candidate_audit_path.resolve()),
                "sha256": _sha256(candidate_audit_path),
            },
            "independent_openbabel_audit": {
                "path": str(independent_audit_path.resolve()),
                "sha256": _sha256(independent_audit_path),
            },
            "equivalent_hessian_references": [
                {"path": str(path.resolve()), "sha256": _sha256(path)}
                for path in equivalent_hessian_reference_paths
            ],
        },
        "release_blockers": [
            "independent human atom-mapped decision for every candidate",
            "approved definitions must be installed through the ordered registry gate",
            "QM evidence does not substitute for definition review",
            "no topology or parameter release is implied by this packet",
        ],
    }
    markdown = _render_markdown(packet)
    output_dir.mkdir(parents=True)
    json_path = output_dir / "definition_review_packet.json"
    markdown_path = output_dir / "definition_review_packet.md"
    markdown_path.write_text(markdown)
    packet["artifacts"] = {
        "markdown": {
            "path": str(markdown_path.resolve()),
            "sha256": _sha256(markdown_path),
        },
    }
    json_path.write_text(json.dumps(packet, indent=2) + "\n")
    return packet


def _parse_path_map(
    paths: Mapping[str, Path], expected_ids: set[str], label: str
) -> dict[str, Path]:
    unexpected = set(paths) - expected_ids
    if unexpected:
        raise ValueError(f"{label} contains unexpected products: {sorted(unexpected)}")
    resolved: dict[str, Path] = {}
    for product_id, path in paths.items():
        candidate = path.resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"{label} is missing for {product_id}: {candidate}")
        resolved[product_id] = candidate
    return resolved


def _validated_human_decision(record: object, product_id: str) -> dict[str, str]:
    if not isinstance(record, dict) or record.get("decision") not in _DECISIONS:
        raise ValueError(
            f"{product_id}: human decision must be APPROVE, REJECT, or REVISE"
        )
    values: dict[str, str] = {}
    for field in (
        "reviewer",
        "reviewed_at",
        "atom_mapped_rationale",
        "evidence_or_corrected_definition_sha256",
    ):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{product_id}: human decision field {field!r} is required")
        values[field] = value.strip()
    if len(values["atom_mapped_rationale"]) < 20:
        raise ValueError(f"{product_id}: atom-mapped rationale is too short")
    if not _SHA256_RE.fullmatch(
        values["evidence_or_corrected_definition_sha256"]
    ):
        raise ValueError(f"{product_id}: decision evidence SHA-256 is invalid")
    try:
        reviewed_at = datetime.fromisoformat(values["reviewed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{product_id}: reviewed_at must be an ISO-8601 timestamp") from exc
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError(f"{product_id}: reviewed_at must include a timezone")
    return {"decision": record["decision"], **values}


def _revalidate_packet_candidate(
    *,
    item: dict[str, Any],
    entry: dict[str, Any],
    series_records: Mapping[str, Any],
    independent_records: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    product_id = entry["id"]
    definition_path = _checked(
        item.get("definition_candidate"), f"{product_id} definition candidate"
    )
    definition = json.loads(definition_path.read_text())
    if (
        definition.get("schema")
        != "nadoc.photoproduct-chemical-definition-candidate.v1"
        or definition.get("status") != "review_required"
        or definition.get("gate_effect") != "none"
        or definition.get("id") != product_id
        or definition.get("product") != "TT-CPD"
        or definition.get("stereochemistry") != entry["stereochemistry"]
    ):
        raise ValueError(f"{product_id}: candidate identity or review status changed")
    _validate_minimum_geometry_evidence(definition)

    manifest_path = _checked(
        item.get("candidate_manifest"), f"{product_id} candidate manifest"
    )
    manifest = json.loads(manifest_path.read_text())
    series_record = series_records.get(product_id) or {}
    independent_record = independent_records.get(product_id) or {}
    if (
        manifest.get("schema") != "nadoc.tt-cpd-stereo-candidate.v1"
        or manifest.get("product_id") != product_id
        or series_record.get("passed") is not True
        or series_record.get("manifest_sha256") != _sha256(manifest_path)
        or independent_record.get("sdf_sha256")
        != ((manifest.get("outputs") or {}).get("sdf") or {}).get("sha256")
    ):
        raise ValueError(f"{product_id}: candidate audit chain changed")
    output_records = item.get("candidate_outputs")
    if not isinstance(output_records, dict) or set(output_records) != set(
        manifest.get("outputs") or {}
    ):
        raise ValueError(f"{product_id}: candidate output inventory changed")
    for name, output in output_records.items():
        path = _checked(output, f"{product_id} {name}")
        if output.get("sha256") != (manifest["outputs"][name] or {}).get("sha256"):
            raise ValueError(f"{product_id}: {name} hash differs from candidate manifest")
        if _sha256(path) != output["sha256"]:
            raise ValueError(f"{product_id}: {name} is hash-mismatched")

    expected_packet_fields = {
        "stereochemistry": definition["stereochemistry"],
        "orientation": entry["structural_class"]["double_bond_orientation"],
        "ordered_c5_configurations": entry["structural_class"][
            "ordered_c5_configurations"
        ],
        "product_stereocenters": definition.get("product_stereocenters"),
        "bonds_added": (definition.get("graph_delta") or {}).get("bonds_added"),
        "bonds_retained": (definition.get("graph_delta") or {}).get("bonds_retained"),
        "openbabel": {
            "canonical_isomeric_smiles": independent_record.get(
                "canonical_isomeric_smiles"
            ),
            "inchikey": independent_record.get("inchikey"),
            "constitutional_inchikey_block": independent_record.get(
                "constitutional_inchikey_block"
            ),
        },
        "minimum_geometry_evidence": definition.get("minimum_geometry_evidence")
        or {"kind": "not_supplied"},
    }
    for field, expected in expected_packet_fields.items():
        if item.get(field) != expected:
            raise ValueError(f"{product_id}: packet field {field!r} changed")

    frequency = item.get("frequency_evidence") or {}
    status = frequency.get("status")
    if status == "passed_candidate_harmonic_minimum":
        path = _checked(frequency, f"{product_id} frequency audit")
        expected = _load_frequency_audits([path])[product_id]
        if frequency != expected:
            raise ValueError(f"{product_id}: frequency evidence changed")
    elif status == "passed_equivalent_source_candidate":
        path = _checked(frequency, f"{product_id} equivalent-Hessian reference")
        expected = _load_equivalent_hessian_references([path])[product_id]
        if frequency != expected:
            raise ValueError(f"{product_id}: equivalent-Hessian evidence changed")
    elif status != "not_supplied":
        raise ValueError(f"{product_id}: unsupported frequency evidence status")
    return definition_path, definition


def audit_tt_cpd_definition_review(
    *,
    packet_path: Path,
    reviewed_definition_paths: Mapping[str, Path],
    decision_evidence_paths: Mapping[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    """Revalidate a completed human packet without advancing any registry gate.

    ``APPROVE`` requires an explicit released-schema definition whose hash is the one
    signed in the packet. ``REJECT`` and ``REVISE`` require a separately hash-pinned
    rationale/evidence file. The audit is gate-neutral; curating and attaching approved
    definitions remains an explicit later action.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite definition-review audit: {output_path}")
    packet_path = packet_path.resolve()
    packet = json.loads(packet_path.read_text())
    if (
        packet.get("schema") != "nadoc.tt-cpd-definition-human-review-packet.v1"
        or packet.get("status") != "human_review_complete"
        or packet.get("simulation_ready") is not False
        or packet.get("gate_effect") != "none"
        or packet.get("candidate_count") != 7
        or packet.get("all_required_candidates_present") is not True
    ):
        raise ValueError(
            "a completed, gate-neutral seven-candidate TT-CPD review packet is required"
        )

    sources = packet.get("sources") or {}
    registry_path = _checked(sources.get("registry"), "review packet registry snapshot")
    registry = photoproduct_registry(registry_path)
    expected_entries = {
        entry["id"]: entry
        for entry in registry["products"]
        if entry["product"] == "TT-CPD" and entry["stereochemistry"] != "cis-syn"
    }
    if len(expected_entries) != 7:
        raise ValueError("reviewed registry snapshot does not define seven noncanonical TT-CPDs")
    candidate_audit_path = _checked(
        sources.get("candidate_audit"), "candidate series audit"
    )
    independent_path = _checked(
        sources.get("independent_openbabel_audit"), "independent Open Babel audit"
    )
    candidate_audit = json.loads(candidate_audit_path.read_text())
    independent = json.loads(independent_path.read_text())
    if (
        candidate_audit.get("schema") != "nadoc.tt-cpd-stereo-candidate-audit.v1"
        or candidate_audit.get("status") != "passed_candidate"
        or candidate_audit.get("passed") is not True
        or candidate_audit.get("gate_effect") != "none"
        or independent.get("schema") != "nadoc.tt-cpd-openbabel-stereo-audit.v1"
        or independent.get("status")
        != "software_crosscheck_passed_human_review_required"
        or independent.get("passed") is not True
        or independent.get("gate_effect") != "none"
        or (independent.get("candidate_audit") or {}).get("sha256")
        != _sha256(candidate_audit_path)
    ):
        raise ValueError("packet candidate and independent stereo audits are inconsistent")
    series_records = {
        item["product_id"]: item for item in candidate_audit.get("candidates") or []
    }
    independent_records = {
        item["product_id"]: item for item in independent.get("records") or []
    }

    candidates = packet.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("review packet candidates must be a list")
    packet_ids = [item.get("product_id") for item in candidates if isinstance(item, dict)]
    if len(packet_ids) != 7 or len(set(packet_ids)) != 7 or set(packet_ids) != set(
        expected_entries
    ):
        raise ValueError("review packet must contain each noncanonical TT-CPD exactly once")
    definitions = _parse_path_map(
        reviewed_definition_paths, set(expected_entries), "reviewed definitions"
    )
    decision_evidence = _parse_path_map(
        decision_evidence_paths, set(expected_entries), "decision evidence"
    )

    # Validate every source and every decision before writing even a gate-neutral audit.
    results: list[dict[str, Any]] = []
    for item in candidates:
        product_id = item["product_id"]
        entry = expected_entries[product_id]
        candidate_path, candidate = _revalidate_packet_candidate(
            item=item,
            entry=entry,
            series_records=series_records,
            independent_records=independent_records,
        )
        decision = _validated_human_decision(item.get("human_decision"), product_id)
        signed_hash = decision["evidence_or_corrected_definition_sha256"]
        result: dict[str, Any] = {
            "product_id": product_id,
            "decision": decision["decision"],
            "reviewer": decision["reviewer"],
            "reviewed_at": decision["reviewed_at"],
            "atom_mapped_rationale": decision["atom_mapped_rationale"],
            "definition_candidate": {
                "path": str(candidate_path),
                "sha256": _sha256(candidate_path),
            },
        }
        if decision["decision"] == "APPROVE":
            if product_id not in definitions:
                raise ValueError(f"{product_id}: APPROVE requires --reviewed-definition")
            if product_id in decision_evidence:
                raise ValueError(
                    f"{product_id}: APPROVE must hash the reviewed definition, not separate evidence"
                )
            release_path = definitions[product_id]
            if _sha256(release_path) != signed_hash:
                raise ValueError(f"{product_id}: reviewed definition does not match signed hash")
            release = json.loads(release_path.read_text())
            from backend.core.photoproduct_chemistry import (
                audit_product_chirality,
                chemical_definition_registry_graph,
                validate_chemical_definition_document,
            )

            validate_chemical_definition_document(
                release,
                expected_id=product_id,
                expected_product="TT-CPD",
                expected_stereochemistry=entry["stereochemistry"],
            )
            forbidden = sorted(_RELEASE_FORBIDDEN_FIELDS & set(release))
            if forbidden:
                raise ValueError(
                    f"{product_id}: released definition retains candidate-only fields: {forbidden}"
                )
            for field in _CHEMICAL_IDENTITY_FIELDS:
                if release.get(field) != candidate.get(field):
                    raise ValueError(
                        f"{product_id}: approved definition changes candidate field {field!r}; "
                        "record REVISE and regenerate the review packet instead"
                    )
            if chemical_definition_registry_graph(release) != entry["graph_delta"]:
                raise ValueError(f"{product_id}: released graph differs from registry")
            chirality = audit_product_chirality(
                release, release["source_ring_coordinates_angstrom"]
            )
            if chirality["passed"] is not True or len(chirality["centers"]) != 4:
                raise ValueError(f"{product_id}: released source coordinates fail chirality audit")
            result["reviewed_definition"] = {
                "path": str(release_path),
                "sha256": signed_hash,
                "schema": release["schema"],
                "chirality_audit": chirality,
            }
        else:
            if product_id in definitions:
                raise ValueError(
                    f"{product_id}: {decision['decision']} cannot provide a releasable definition"
                )
            if product_id not in decision_evidence:
                raise ValueError(
                    f"{product_id}: {decision['decision']} requires --decision-evidence"
                )
            evidence_path = decision_evidence[product_id]
            if _sha256(evidence_path) != signed_hash:
                raise ValueError(f"{product_id}: decision evidence does not match signed hash")
            result["decision_evidence"] = {
                "path": str(evidence_path),
                "sha256": signed_hash,
            }
        results.append(result)

    approved = [item["product_id"] for item in results if item["decision"] == "APPROVE"]
    unresolved = [item["product_id"] for item in results if item["decision"] != "APPROVE"]
    audit = {
        "schema": "nadoc.tt-cpd-definition-review-ingestion-audit.v1",
        "status": "passed_review_ingestion",
        "passed": True,
        "simulation_ready": False,
        "gate_effect": "none",
        "review_packet": {"path": str(packet_path), "sha256": _sha256(packet_path)},
        "approved_product_ids": approved,
        "unresolved_product_ids": unresolved,
        "records": results,
        "release_boundary": (
            "This audit does not attach assets or pass gates. Each approved exact file must "
            "be curated under the force-field tree, attached, and independently gate-reviewed."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit, indent=2) + "\n")
    return audit


def materialize_visual_definition_review(
    *,
    packet_path: Path,
    visual_decisions_path: Path,
    source_asset_template_path: Path,
    structural_reference_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Convert current hash-pinned UI decisions into formal review artifacts.

    This operation is deliberately gate-neutral.  It refuses decisions made against
    any geometry other than the exact minimum-backed definition candidate.  Approved
    candidates are copied into released *schema* only; they are not curated, attached
    to the registry, or authorized for parameter use here.
    """

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite visual-review ingestion output: {output_dir}"
        )
    packet_path = packet_path.resolve()
    visual_decisions_path = visual_decisions_path.resolve()
    source_asset_template_path = source_asset_template_path.resolve()
    structural_reference_manifest_path = structural_reference_manifest_path.resolve()
    packet = json.loads(packet_path.read_text())
    visual = json.loads(visual_decisions_path.read_text())
    source_template = json.loads(source_asset_template_path.read_text())
    structural_references = json.loads(structural_reference_manifest_path.read_text())
    if (
        packet.get("schema") != "nadoc.tt-cpd-definition-human-review-packet.v1"
        or packet.get("status") != "human_review_required"
        or packet.get("candidate_count") != 7
        or packet.get("all_required_candidates_present") is not True
        or packet.get("simulation_ready") is not False
        or packet.get("gate_effect") != "none"
    ):
        raise ValueError("a pristine seven-candidate definition review packet is required")
    if (
        visual.get("schema") != "nadoc.photoproduct-visual-review-decisions.v1"
        or visual.get("simulation_ready") is not False
        or visual.get("gate_effect") != "none"
        or ((visual.get("source_definition_packet") or {}).get("sha256"))
        != _sha256(packet_path)
    ):
        raise ValueError("visual decisions do not match the pristine review packet")
    assets = source_template.get("source_assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("source-asset template has no immutable source assets")
    for asset in assets:
        if (
            not isinstance(asset, dict)
            or not all(asset.get(key) for key in ("id", "url", "filename", "license"))
            or not _SHA256_RE.fullmatch(str(asset.get("sha256") or ""))
        ):
            raise ValueError("source-asset template contains incomplete provenance")
    if structural_references.get("schema") != "nadoc.photoproduct-structural-references.v1":
        raise ValueError("unsupported structural-reference manifest")
    taylor_records = [
        record
        for record in structural_references.get("sources") or []
        if record.get("id") == "Taylor-2023-CPD-stereochemistry"
    ]
    if len(taylor_records) != 1:
        raise ValueError("Taylor 2023 ordered-stereochemistry citation record is required")
    taylor = taylor_records[0]
    citation_bytes = json.dumps(
        taylor, sort_keys=True, separators=(",", ":")
    ).encode()
    citation_asset = {
        "id": taylor["id"],
        "url": taylor["url"],
        "filename": "Taylor-2023-CPD-stereochemistry.citation.json",
        "sha256": hashlib.sha256(citation_bytes).hexdigest(),
        "license": (
            "NADOC citation metadata only; underlying publisher article is not "
            "redistributed and remains subject to publisher terms"
        ),
        "hash_scope": "embedded_citation_record_not_publisher_article",
        "citation_record": deepcopy(taylor),
    }
    release_assets = [deepcopy(asset) for asset in assets]
    if citation_asset["id"] not in {asset.get("id") for asset in release_assets}:
        release_assets.append(citation_asset)

    raw_decisions = [
        item
        for item in visual.get("decisions") or []
        if isinstance(item, dict) and item.get("stage") == "chemical_definition"
    ]
    decisions_by_id: dict[str, dict[str, Any]] = {}
    for decision in raw_decisions:
        product_id = str(decision.get("product_id") or "")
        if product_id in decisions_by_id:
            raise ValueError(f"duplicate visual definition decision for {product_id}")
        decisions_by_id[product_id] = decision
    packet_ids = [item.get("product_id") for item in packet.get("candidates") or []]
    if len(packet_ids) != 7 or set(decisions_by_id) != set(packet_ids):
        missing = sorted(set(packet_ids) - set(decisions_by_id))
        unexpected = sorted(set(decisions_by_id) - set(packet_ids))
        raise ValueError(
            "current visual decisions must cover all seven definitions exactly once "
            f"(missing={missing}, unexpected={unexpected})"
        )

    # Validate everything that does not depend on newly materialized files before
    # creating the output directory.
    candidates_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for item in packet["candidates"]:
        product_id = item["product_id"]
        candidate_path = _checked(
            item.get("definition_candidate"), f"{product_id} definition candidate"
        )
        candidate = json.loads(candidate_path.read_text())
        decision = decisions_by_id[product_id]
        if decision.get("decision") not in {"approve", "reject", "revise"}:
            raise ValueError(f"{product_id}: unsupported visual decision")
        if decision.get("conformer_id") is not None or decision.get("partition") is not None:
            raise ValueError(f"{product_id}: definition decision has conformer fields")
        if not str(decision.get("reviewer") or "").strip():
            raise ValueError(f"{product_id}: visual reviewer is missing")
        if len(str(decision.get("notes") or "").strip()) < 12:
            raise ValueError(f"{product_id}: visual review rationale is too short")
        try:
            reviewed_at = datetime.fromisoformat(
                str(decision.get("reviewed_at") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"{product_id}: invalid visual review timestamp") from exc
        if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
            raise ValueError(f"{product_id}: visual review timestamp needs a timezone")
        # The current reviewer pins the exact definition file because that file
        # contains the exact stable-key coordinate mapping rendered in 3D.
        if decision.get("source_geometry_sha256") != _sha256(candidate_path):
            raise ValueError(
                f"{product_id}: visual decision is stale or reviewed a different geometry"
            )
        candidates_by_id[product_id] = (candidate_path, candidate)

    output_dir.mkdir(parents=True)
    release_dir = output_dir / "reviewed_definitions"
    evidence_dir = output_dir / "decision_evidence"
    release_dir.mkdir()
    evidence_dir.mkdir()
    completed = deepcopy(packet)
    completed["status"] = "human_review_complete"
    releases: dict[str, Path] = {}
    evidence: dict[str, Path] = {}
    for item in completed["candidates"]:
        product_id = item["product_id"]
        _candidate_path, candidate = candidates_by_id[product_id]
        visual_decision = decisions_by_id[product_id]
        formal_decision = visual_decision["decision"].upper()
        if formal_decision == "APPROVE":
            release = deepcopy(candidate)
            release["schema"] = "nadoc.photoproduct-chemical-definition.v1"
            for field in _RELEASE_FORBIDDEN_FIELDS:
                release.pop(field, None)
            release["source_assets"] = deepcopy(release_assets)
            target = release_dir / f"{product_id}.json"
            target.write_text(json.dumps(release, indent=2) + "\n")
            releases[product_id] = target
            signed_hash = _sha256(target)
        else:
            record = {
                "schema": "nadoc.photoproduct-visual-definition-decision-evidence.v1",
                "status": "unresolved_human_decision",
                "simulation_ready": False,
                "gate_effect": "none",
                "product_id": product_id,
                "visual_decision": deepcopy(visual_decision),
                "definition_candidate": {
                    "path": str(candidates_by_id[product_id][0]),
                    "sha256": _sha256(candidates_by_id[product_id][0]),
                },
            }
            target = evidence_dir / f"{product_id}.json"
            target.write_text(json.dumps(record, indent=2) + "\n")
            evidence[product_id] = target
            signed_hash = _sha256(target)
        item["human_decision"] = {
            "decision": formal_decision,
            "reviewer": str(visual_decision["reviewer"]).strip(),
            "reviewed_at": str(visual_decision["reviewed_at"]).strip(),
            "atom_mapped_rationale": (
                "Visual-review rationale (verbatim): "
                + str(visual_decision["notes"]).strip()
            ),
            "evidence_or_corrected_definition_sha256": signed_hash,
        }

    completed_path = output_dir / "completed_definition_review_packet.json"
    completed_path.write_text(json.dumps(completed, indent=2) + "\n")
    audit_path = output_dir / "definition_review_ingestion_audit.json"
    audit = audit_tt_cpd_definition_review(
        packet_path=completed_path,
        reviewed_definition_paths=releases,
        decision_evidence_paths=evidence,
        output_path=audit_path,
    )
    receipt = {
        "schema": "nadoc.photoproduct-visual-definition-review-materialization.v1",
        "status": "passed_gate_neutral_materialization",
        "passed": True,
        "simulation_ready": False,
        "gate_effect": "none",
        "source_packet": {"path": str(packet_path), "sha256": _sha256(packet_path)},
        "source_visual_decisions": {
            "path": str(visual_decisions_path),
            "sha256": _sha256(visual_decisions_path),
        },
        "source_asset_template": {
            "path": str(source_asset_template_path),
            "sha256": _sha256(source_asset_template_path),
        },
        "structural_reference_manifest": {
            "path": str(structural_reference_manifest_path),
            "sha256": _sha256(structural_reference_manifest_path),
        },
        "completed_packet": {
            "path": str(completed_path),
            "sha256": _sha256(completed_path),
        },
        "ingestion_audit": {"path": str(audit_path), "sha256": _sha256(audit_path)},
        "approved_product_ids": audit["approved_product_ids"],
        "unresolved_product_ids": audit["unresolved_product_ids"],
        "release_boundary": (
            "These files use the released chemical-definition schema but remain "
            "unattached and cannot advance force-field or simulation gates."
        ),
    }
    receipt_path = output_dir / "materialization_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def _coordinates_from_xyz(
    xyz_path: Path, atom_map: object
) -> dict[str, list[float]]:
    from backend.parameterization.photoproduct_qm import parse_xyz

    atoms, _comment = parse_xyz(xyz_path.read_text())
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != len(atoms)
        or len(atom_map) != len(set(atom_map))
        or not all(isinstance(key, str) and key for key in atom_map)
    ):
        raise ValueError("minimum XYZ requires a matching unique stable atom map")
    coordinates: dict[str, list[float]] = {}
    for key, (element, x, y, z) in zip(atom_map, atoms, strict=True):
        atom_name = key.rsplit(":", 1)[-1]
        expected_element = next(
            (
                symbol
                for symbol in ("Cl", "Br", "C", "N", "O", "P", "S", "H")
                if atom_name.startswith(symbol)
            ),
            None,
        )
        if (
            expected_element is not None
            and element.casefold() != expected_element.casefold()
        ):
            raise ValueError(f"stable atom {key!r} does not match XYZ element {element!r}")
        xyz = [float(x), float(y), float(z)]
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError("minimum XYZ contains non-finite coordinates")
        coordinates[key] = xyz
    return coordinates


def _direct_minimum_coordinates(
    *,
    product_id: str,
    frequency_audit_path: Path,
    optimized_xyz_path: Path,
    optimized_model_audit_path: Path | None,
    frequency_job_manifest_path: Path | None,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    if optimized_model_audit_path is None or frequency_job_manifest_path is None:
        raise ValueError(
            "direct frequency evidence requires optimized-model audit and frequency job manifest"
        )
    optimized_xyz_path = optimized_xyz_path.resolve()
    optimized_model_audit_path = optimized_model_audit_path.resolve()
    frequency_job_manifest_path = frequency_job_manifest_path.resolve()
    for label, path in (
        ("optimized XYZ", optimized_xyz_path),
        ("optimized-model audit", optimized_model_audit_path),
        ("frequency job manifest", frequency_job_manifest_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")
    frequency = json.loads(frequency_audit_path.read_text())
    _load_frequency_audits([frequency_audit_path])
    parent = json.loads(optimized_model_audit_path.read_text())
    job = json.loads(frequency_job_manifest_path.read_text())
    xyz_hash = _sha256(optimized_xyz_path)
    parent_hash = _sha256(optimized_model_audit_path)
    model_id = (parent.get("model_id") or "")
    if (
        frequency.get("product_id") != product_id
        or frequency.get("model_id") != model_id
        or frequency.get("status") != "passed_candidate_harmonic_minimum"
        or frequency.get("imaginary_mode_count") != 0
        or (frequency.get("parent_optimized_model_audit") or {}).get("sha256")
        != parent_hash
        or parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("status") != "passed_candidate_identity_and_chirality"
        or parent.get("gate_effect") != "none"
        or parent.get("product_id") != product_id
        or (parent.get("optimized_xyz") or {}).get("sha256") != xyz_hash
        or (parent.get("chirality_audit") or {}).get("passed") is not True
        or not isinstance(parent.get("final_energy_hartree"), (int, float))
        or not math.isfinite(float(parent["final_energy_hartree"]))
        or job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "frequency"
        or job.get("product_id") != product_id
        or job.get("model_id") != model_id
        or (job.get("source_xyz") or {}).get("sha256") != xyz_hash
        or (job.get("parent_manifest") or {}).get("sha256") != parent_hash
    ):
        raise ValueError("direct minimum evidence identity/hash chain is inconsistent")
    _checked(
        frequency.get("output"),
        f"{product_id} frequency output",
        fallback_paths=(frequency_audit_path.parent / "output.dat",),
    )
    _checked(
        frequency.get("cartesian_hessian"),
        f"{product_id} Cartesian Hessian",
        fallback_paths=(frequency_audit_path.parent / "hessian_hartree_per_bohr2.txt",),
    )
    coordinates = _coordinates_from_xyz(optimized_xyz_path, job.get("atom_map"))
    return coordinates, {
        "kind": "direct_candidate_harmonic_minimum",
        "frequency_audit": {
            "path": str(frequency_audit_path.resolve()),
            "sha256": _sha256(frequency_audit_path),
        },
        "optimized_xyz": {"path": str(optimized_xyz_path), "sha256": xyz_hash},
        "optimized_model_audit": {
            "path": str(optimized_model_audit_path),
            "sha256": parent_hash,
        },
        "frequency_job_manifest": {
            "path": str(frequency_job_manifest_path),
            "sha256": _sha256(frequency_job_manifest_path),
        },
        "model_id": model_id,
        "imaginary_mode_count": frequency.get("imaginary_mode_count"),
        "lowest_frequency_cm_inverse": frequency.get("lowest_frequency_cm_inverse"),
    }


def _equivalent_minimum_coordinates(
    *, product_id: str, reference_path: Path
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    records = _load_equivalent_hessian_references([reference_path])
    if product_id not in records:
        raise ValueError("equivalent-Hessian reference target does not match candidate")
    reference = json.loads(reference_path.read_text())
    source_geometry = _checked(
        ((reference.get("source_frequency") or {}).get("source_geometry")),
        f"{product_id} equivalent source geometry",
    )
    source_map = reference.get("source_atom_map")
    target_map = reference.get("target_atom_map_in_source_matrix_order")
    source_coordinates = _coordinates_from_xyz(source_geometry, source_map)
    if not isinstance(target_map, list) or len(target_map) != len(source_map):
        raise ValueError("equivalent-Hessian target atom map is incomplete")
    coordinates = {
        target_key: source_coordinates[source_key]
        for source_key, target_key in zip(source_map, target_map, strict=True)
    }
    if len(coordinates) != len(target_map):
        raise ValueError("equivalent-Hessian target atom map contains duplicates")
    record = records[product_id]
    return coordinates, {
        "kind": "audited_endpoint_exchange_equivalent_minimum",
        "equivalent_hessian_reference": {
            "path": str(reference_path.resolve()),
            "sha256": _sha256(reference_path),
        },
        "source_product_id": record["source_product_id"],
        "source_geometry": {
            "path": str(source_geometry),
            "sha256": _sha256(source_geometry),
        },
        "coordinate_frame": record["coordinate_frame"],
        "independent_target_frequency_run": False,
    }


def _validate_minimum_geometry_evidence(definition: Mapping[str, Any]) -> None:
    record = definition.get("minimum_geometry_evidence")
    if record is None:
        return
    if not isinstance(record, dict):
        raise ValueError("minimum_geometry_evidence must be an object")
    product_id = str(definition.get("id") or "")
    kind = record.get("kind")
    if kind == "direct_candidate_harmonic_minimum":
        frequency = _checked(
            record.get("frequency_audit"), f"{product_id} minimum frequency audit"
        )
        xyz = _checked(record.get("optimized_xyz"), f"{product_id} minimum XYZ")
        parent = _checked(
            record.get("optimized_model_audit"),
            f"{product_id} optimized-model audit",
        )
        job = _checked(
            record.get("frequency_job_manifest"),
            f"{product_id} frequency job manifest",
        )
        coordinates, expected = _direct_minimum_coordinates(
            product_id=product_id,
            frequency_audit_path=frequency,
            optimized_xyz_path=xyz,
            optimized_model_audit_path=parent,
            frequency_job_manifest_path=job,
        )
    elif kind == "audited_endpoint_exchange_equivalent_minimum":
        reference = _checked(
            record.get("equivalent_hessian_reference"),
            f"{product_id} equivalent-Hessian reference",
        )
        coordinates, expected = _equivalent_minimum_coordinates(
            product_id=product_id, reference_path=reference
        )
    else:
        raise ValueError(f"{product_id}: unsupported minimum geometry evidence kind")

    from backend.core.photoproduct_chemistry import audit_product_chirality

    required_keys = set(definition.get("source_ring_coordinates_angstrom") or {})
    missing = sorted(required_keys - set(coordinates))
    if not required_keys or missing:
        raise ValueError(
            f"{product_id}: minimum geometry is missing ring sentinels: {missing}"
        )
    observed = {key: coordinates[key] for key in sorted(required_keys)}
    if observed != definition.get("source_ring_coordinates_angstrom"):
        raise ValueError(f"{product_id}: minimum-backed ring coordinates changed")
    expected["chirality_audit"] = audit_product_chirality(definition, observed)
    if record != expected or expected["chirality_audit"].get("passed") is not True:
        raise ValueError(f"{product_id}: minimum geometry evidence changed or failed")


def build_minimum_backed_definition_candidate(
    *,
    definition_candidate_path: Path,
    minimum_evidence_path: Path,
    output_path: Path,
    optimized_xyz_path: Path | None = None,
    optimized_model_audit_path: Path | None = None,
    frequency_job_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Replace initial candidate ring coordinates with hash-audited minimum evidence.

    The result remains a review-only chemical-definition candidate. Direct frequency
    evidence and endpoint-exchange-equivalent evidence are supported, but never conflated.
    """

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite minimum-backed definition candidate: {output_path}"
        )
    definition_candidate_path = definition_candidate_path.resolve()
    minimum_evidence_path = minimum_evidence_path.resolve()
    if not definition_candidate_path.is_file() or not minimum_evidence_path.is_file():
        raise FileNotFoundError("definition candidate and minimum evidence are required")
    source = json.loads(definition_candidate_path.read_text())
    if (
        source.get("schema")
        != "nadoc.photoproduct-chemical-definition-candidate.v1"
        or source.get("status") != "review_required"
        or source.get("gate_effect") != "none"
        or source.get("product") != "TT-CPD"
    ):
        raise ValueError("a gate-neutral TT-CPD chemical-definition candidate is required")
    product_id = source.get("id")
    evidence = json.loads(minimum_evidence_path.read_text())
    if evidence.get("schema") == "nadoc.photoproduct-frequency-audit.v1":
        if optimized_xyz_path is None:
            raise ValueError("direct frequency evidence requires --optimized-xyz")
        coordinates, minimum_record = _direct_minimum_coordinates(
            product_id=product_id,
            frequency_audit_path=minimum_evidence_path,
            optimized_xyz_path=optimized_xyz_path,
            optimized_model_audit_path=optimized_model_audit_path,
            frequency_job_manifest_path=frequency_job_manifest_path,
        )
    elif (
        evidence.get("schema")
        == "nadoc.photoproduct-equivalent-hessian-reference.v1"
    ):
        if any(
            path is not None
            for path in (
                optimized_xyz_path,
                optimized_model_audit_path,
                frequency_job_manifest_path,
            )
        ):
            raise ValueError(
                "equivalent evidence resolves its own source geometry; direct-evidence paths are invalid"
            )
        coordinates, minimum_record = _equivalent_minimum_coordinates(
            product_id=product_id, reference_path=minimum_evidence_path
        )
    else:
        raise ValueError("minimum evidence has an unsupported schema")

    required_keys = set(source.get("source_ring_coordinates_angstrom") or {})
    missing = sorted(required_keys - set(coordinates))
    if not required_keys or missing:
        raise ValueError(
            "minimum geometry is missing reviewed ring sentinels: " + ", ".join(missing)
        )
    result = deepcopy(source)
    result["source_ring_coordinates_angstrom"] = {
        key: coordinates[key] for key in sorted(required_keys)
    }
    from backend.core.photoproduct_chemistry import audit_product_chirality

    chirality = audit_product_chirality(
        result, result["source_ring_coordinates_angstrom"]
    )
    if chirality.get("passed") is not True or len(chirality.get("centers") or []) != 4:
        raise ValueError("minimum-backed candidate fails its four-center chirality audit")
    minimum_record["chirality_audit"] = chirality
    result["minimum_geometry_evidence"] = minimum_record
    charge_model = ((result.get("model_compounds") or {}).get("charge_model") or {})
    charge_model["source_asset"] = (
        "hash-linked passed QM minimum; chemical-definition review still pending"
    )
    blockers = [
        blocker
        for blocker in result.get("release_blockers") or []
        if blocker
        != "replace candidate coordinates with a passed QM minimum and frequency evidence"
    ]
    if minimum_record["kind"] == "audited_endpoint_exchange_equivalent_minimum":
        blockers.append(
            "human review must accept endpoint-exchange equivalence in place of an independent target minimum"
        )
    result["release_blockers"] = blockers
    result["candidate_evidence"]["pre_minimum_definition"] = {
        "path": str(definition_candidate_path),
        "sha256": _sha256(definition_candidate_path),
    }
    _validate_minimum_geometry_evidence(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result
