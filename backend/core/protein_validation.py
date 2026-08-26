"""Quantitative validation for a committed protein–ssDNA conjugate.

The report is deliberately pure and JSON-shaped so the API, tests, saved
acceptance artifacts, and UI all consume the same measurements.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.core.conjugation import conjugation_candidate_for_serial
from backend.core.models import Design, ProteinAsset, ProteinAttachment, Strand
from backend.core.protein import (
    compose_protein_world_transform,
    protein_asset_to_atomistic,
    resolve_overhang_anchor,
    reverse_complement,
)

ANCHOR_TOLERANCE_NM = 1.0e-4
RIGID_TOLERANCE = 1.0e-6


def _metric(value: Any, passed: bool, *, gate: str) -> dict[str, Any]:
    return {"value": value, "passed": bool(passed), "gate": gate}


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def validate_protein_conjugate(
    before: Design,
    after: Design,
    *,
    asset: ProteinAsset,
    attachment: ProteinAttachment,
    binder: Strand,
    geometry: list[dict],
    source_attachment_id: str | None = None,
    candidates: list[dict] | None = None,
) -> dict[str, Any]:
    """Measure structural invariants of one just-committed conjugate."""
    metrics: dict[str, dict[str, Any]] = {}

    placement_delta = len(after.protein_attachments) - len(before.protein_attachments)
    expected_placement_delta = 0 if source_attachment_id else 1
    metrics["placement_cardinality_delta"] = _metric(
        placement_delta,
        placement_delta == expected_placement_delta,
        gate=f"exactly {expected_placement_delta}",
    )
    asset_delta = len(after.protein_assets) - len(before.protein_assets)
    expected_asset_delta = 0 if any(a.id == asset.id for a in before.protein_assets) else 1
    metrics["asset_cardinality_delta"] = _metric(
        asset_delta, asset_delta == expected_asset_delta, gate=f"exactly {expected_asset_delta}"
    )
    metrics["stable_placement_identity"] = _metric(
        attachment.id,
        source_attachment_id is None or attachment.id == source_attachment_id,
        gate="source ID preserved for conversion",
    )
    asset_refs = [a for a in after.protein_assets if a.id == attachment.asset_id]
    metrics["asset_referential_integrity"] = _metric(
        len(asset_refs), len(asset_refs) == 1, gate="exactly 1 embedded asset"
    )

    target = attachment.target
    overhang_id = getattr(target, "overhang_id", None)
    target_ok = (
        getattr(target, "kind", None) == "overhang"
        and getattr(target, "attach_end", None) in ("free_end", "root")
        and sum(o.id == overhang_id for o in after.overhangs) == 1
    )
    metrics["target_integrity"] = _metric(target_ok, target_ok, gate="valid unique overhang target")

    before_strands = {s.id: s.model_dump(mode="json") for s in before.strands}
    after_strands = {s.id: s.model_dump(mode="json") for s in after.strands}
    new_ids = set(after_strands) - set(before_strands)
    target_binders = [
        strand
        for strand in after.strands
        if any(domain.binds_overhang_id == overhang_id for domain in strand.domains)
    ]
    metrics["binder_cardinality"] = _metric(
        len(target_binders),
        new_ids == {binder.id}
        and len(target_binders) == 1
        and target_binders[0].id == binder.id,
        gate="exactly 1 target binder and it is the committed binder",
    )
    unchanged = all(after_strands.get(sid) == value for sid, value in before_strands.items())
    metrics["topology_locality"] = _metric(
        sum(not (after_strands.get(sid) == value) for sid, value in before_strands.items()),
        unchanged,
        gate="0 pre-existing strands changed",
    )
    spec = next((o for o in after.overhangs if o.id == overhang_id), None)
    # Use the same canonical sub-domain-aware assembly as binder construction.
    # ``OverhangSpec.sequence`` alone can disagree with overrides or cover only
    # part of the backing domain.
    from backend.core.sequences import _assemble_overhang_5to3

    binder_domain = next(
        (d for d in binder.domains if d.binds_overhang_id == overhang_id), None
    )
    domain_len = (
        abs(binder_domain.end_bp - binder_domain.start_bp) + 1
        if binder_domain is not None
        else 0
    )
    assembled = _assemble_overhang_5to3(spec, domain_len) if spec else []
    expected_sequence = reverse_complement("".join(assembled)) if assembled else None
    binder_binds_target = any(
        getattr(domain, "binds_overhang_id", None) == overhang_id
        for domain in binder.domains
    )
    sequence_ok = bool(expected_sequence) and binder.sequence == expected_sequence
    metrics["sequence_fidelity"] = _metric(
        binder.sequence,
        sequence_ok and binder_binds_target,
        gate="exact reverse complement on a domain bound to the target",
    )

    serial = attachment.conjugation_atom_serial
    atom = next((a for a in asset.atoms if a.serial == serial), None)
    if candidates is None:
        candidate = (
            conjugation_candidate_for_serial(asset, serial) if serial is not None else None
        )
    else:
        candidate = next(
            (c for c in candidates if c["functional_atom_serial"] == serial), None
        )
    metrics["conjugation_atom_integrity"] = _metric(
        serial,
        atom is not None and candidate is not None,
        gate="atom exists and is a surface-accessible supported candidate",
    )
    metrics["candidate_accessibility"] = _metric(
        candidate["accessible"] if candidate else None,
        candidate is not None and candidate["accessible"] >= 0.1,
        gate=">= 0.1 solvent-accessible fraction",
    )
    stored_chemistry = getattr(attachment, "conjugation_chemistry", None)
    stored_accessibility = getattr(
        attachment, "conjugation_accessible_fraction", None
    )
    evidence_ok = candidate is not None and (
        (stored_chemistry is None and stored_accessibility is None)
        or (
            stored_chemistry == candidate["chemistry"]
            and stored_accessibility is not None
            and abs(float(stored_accessibility) - float(candidate["accessible"]))
            <= 1.0e-4
        )
    )
    metrics["selection_evidence"] = _metric(
        {
            "chemistry": stored_chemistry or (candidate["chemistry"] if candidate else None),
            "accessible": (
                stored_accessibility
                if stored_accessibility is not None
                else (candidate["accessible"] if candidate else None)
            ),
            "persisted": stored_chemistry is not None and stored_accessibility is not None,
        },
        evidence_ok,
        gate="persisted evidence matches analysis (legacy records may be inferred)",
    )

    tip, outward = resolve_overhang_anchor(
        geometry, overhang_id, getattr(target, "attach_end", "free_end")
    )
    world = compose_protein_world_transform(asset, attachment, tip, outward)
    finite = bool(np.isfinite(world).all())
    rotation = world[:3, :3]
    ortho_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3))) if finite else math.inf
    determinant = float(np.linalg.det(rotation)) if finite else math.nan
    transform_ok = finite and ortho_error <= RIGID_TOLERANCE and abs(determinant - 1.0) <= RIGID_TOLERANCE
    metrics["transform_health"] = _metric(
        {
            "finite": finite,
            "orthonormal_error": _finite_or_none(ortho_error),
            "determinant": _finite_or_none(determinant),
        },
        transform_ok,
        gate=f"finite, orthonormal error <= {RIGID_TOLERANCE:g}, determinant ~= 1",
    )

    anchor_error = math.inf
    orientation_dot = math.nan
    if atom is not None and tip is not None and outward is not None and finite:
        atom_world = world @ np.array([atom.x, atom.y, atom.z, 1.0])
        from backend.core.protein import _conjugate_terminus_position

        binder_tip = _conjugate_terminus_position(geometry, attachment)
        expected_tip = (
            binder_tip
            if binder_tip is not None
            else tip + outward * max(attachment.handle_spacer_nt, 0) * 0.5
        )
        anchor_error = float(np.linalg.norm(atom_world[:3] - expected_tip))
        com_world = world @ np.array([*asset.center_of_mass, 1.0])
        orientation_dot = float(np.dot(com_world[:3] - atom_world[:3], outward))
    metrics["anchor_error_nm"] = _metric(
        _finite_or_none(anchor_error),
        anchor_error <= ANCHOR_TOLERANCE_NM,
        gate=f"<= {ANCHOR_TOLERANCE_NM:g} nm",
    )
    metrics["outward_orientation_dot_nm"] = _metric(
        _finite_or_none(orientation_dot),
        math.isfinite(orientation_dot) and orientation_dot >= -ANCHOR_TOLERANCE_NM,
        gate=f">= -{ANCHOR_TOLERANCE_NM:g} nm",
    )
    rendered_atom_count = len(
        protein_asset_to_atomistic(asset, pose_matrix=world, sentinel_id=attachment.id).atoms
    )
    metrics["render_atom_census"] = _metric(
        rendered_atom_count,
        rendered_atom_count == len(asset.atoms) and attachment.visible,
        gate=f"exactly {len(asset.atoms)} rendered atoms, visible",
    )

    failed = [name for name, metric in metrics.items() if not metric["passed"]]
    return {
        "schema_version": 1,
        "valid": not failed,
        "attachment_id": attachment.id,
        "asset_id": asset.id,
        "overhang_id": overhang_id,
        "binder_strand_id": binder.id,
        "metrics": metrics,
        "failed_metrics": failed,
    }


def audit_protein_design(design: Design, geometry: list[dict]) -> dict[str, Any]:
    """Audit all persisted protein placements and conjugates in ``design``.

    This catches legacy files that predate commit validation, including the
    free+anchored double-placement pattern seen in VoltronCoreArm.
    """
    assets_by_id: dict[str, list[ProteinAsset]] = {}
    for asset in design.protein_assets:
        assets_by_id.setdefault(asset.id, []).append(asset)
    placements_by_asset: dict[str, list[ProteinAttachment]] = {}
    for attachment in design.protein_attachments:
        placements_by_asset.setdefault(attachment.asset_id, []).append(attachment)

    findings: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []

    for asset_id, assets in assets_by_id.items():
        if len(assets) != 1:
            findings.append(
                {
                    "code": "duplicate_asset_id",
                    "severity": "error",
                    "asset_id": asset_id,
                    "count": len(assets),
                }
            )
        if asset_id not in placements_by_asset:
            findings.append(
                {"code": "orphan_asset", "severity": "warning", "asset_id": asset_id}
            )

    for asset_id, placements in placements_by_asset.items():
        free_ids = [a.id for a in placements if getattr(a.target, "kind", None) == "free"]
        anchored_ids = [
            a.id for a in placements if getattr(a.target, "kind", None) == "overhang"
        ]
        if free_ids and anchored_ids:
            legacy_import_index = next(
                (
                    i
                    for i, entry in enumerate(design.feature_log)
                    if getattr(entry, "op_kind", None) == "protein-import"
                    and entry.params.get("asset_id") == asset_id
                ),
                None,
            )
            legacy_conjugate_index = next(
                (
                    i
                    for i, entry in enumerate(design.feature_log)
                    if getattr(entry, "op_kind", None) == "protein-conjugate"
                    and entry.params.get("asset_id") == asset_id
                    and not entry.params.get("source_attachment_id")
                ),
                None,
            )
            legacy_conversion = (
                len(free_ids) == 1
                and len(anchored_ids) == 1
                and legacy_import_index is not None
                and legacy_conjugate_index is not None
                and legacy_import_index < legacy_conjugate_index
            )
            findings.append(
                {
                    "code": (
                        "legacy_unconverted_free_placement"
                        if legacy_conversion
                        else "mixed_placement_intent_review"
                    ),
                    "severity": "error" if legacy_conversion else "warning",
                    "asset_id": asset_id,
                    "free_attachment_ids": free_ids,
                    "conjugated_attachment_ids": anchored_ids,
                    "repairable": legacy_conversion,
                }
            )

    for attachment in design.protein_attachments:
        assets = assets_by_id.get(attachment.asset_id, [])
        kind = getattr(attachment.target, "kind", None)
        if len(assets) != 1:
            elements.append(
                {
                    "attachment_id": attachment.id,
                    "asset_id": attachment.asset_id,
                    "kind": kind,
                    "valid": False,
                    "failed_metrics": ["asset_referential_integrity"],
                }
            )
            continue
        asset = assets[0]
        if kind == "free":
            world = compose_protein_world_transform(asset, attachment)
            transform_ok = bool(np.isfinite(world).all())
            elements.append(
                {
                    "schema_version": 1,
                    "attachment_id": attachment.id,
                    "asset_id": asset.id,
                    "kind": "free",
                    "valid": transform_ok,
                    "metrics": {
                        "asset_referential_integrity": _metric(
                            1, True, gate="exactly 1 embedded asset"
                        ),
                        "transform_finite": _metric(
                            transform_ok, transform_ok, gate="finite world transform"
                        ),
                        "render_atom_census": _metric(
                            len(protein_asset_to_atomistic(asset, pose_matrix=world).atoms),
                            bool(asset.atoms),
                            gate=f"exactly {len(asset.atoms)} rendered atoms",
                        ),
                    },
                    "failed_metrics": [] if transform_ok else ["transform_finite"],
                }
            )
            continue
        if kind != "overhang":
            findings.append(
                {
                    "code": "unsupported_attachment_target",
                    "severity": "warning",
                    "attachment_id": attachment.id,
                    "kind": kind,
                }
            )
            continue

        overhang_id = getattr(attachment.target, "overhang_id", None)
        binders = [
            strand
            for strand in design.strands
            if any(domain.binds_overhang_id == overhang_id for domain in strand.domains)
        ]
        if len(binders) != 1:
            elements.append(
                {
                    "schema_version": 1,
                    "attachment_id": attachment.id,
                    "asset_id": asset.id,
                    "kind": "overhang",
                    "overhang_id": overhang_id,
                    "valid": False,
                    "metrics": {
                        "binder_cardinality": _metric(
                            len(binders), len(binders) == 1, gate="exactly 1 binder"
                        )
                    },
                    "failed_metrics": ["binder_cardinality"],
                }
            )
            continue
        binder = binders[0]
        before = design.model_copy(
            update={
                "strands": [s for s in design.strands if s.id != binder.id],
                "protein_attachments": [
                    a for a in design.protein_attachments if a.id != attachment.id
                ],
            }
        )
        report = validate_protein_conjugate(
            before,
            design,
            asset=asset,
            attachment=attachment,
            binder=binder,
            geometry=geometry,
        )
        report["kind"] = "overhang"
        elements.append(report)

    failed_elements = [e["attachment_id"] for e in elements if not e.get("valid")]
    error_findings = [f for f in findings if f["severity"] == "error"]
    return {
        "schema_version": 1,
        "valid": not failed_elements and not error_findings,
        "summary": {
            "asset_count": len(design.protein_assets),
            "placement_count": len(design.protein_attachments),
            "free_placement_count": sum(
                getattr(a.target, "kind", None) == "free"
                for a in design.protein_attachments
            ),
            "conjugated_placement_count": sum(
                getattr(a.target, "kind", None) == "overhang"
                for a in design.protein_attachments
            ),
            "failed_element_count": len(failed_elements),
            "error_count": len(error_findings),
            "warning_count": sum(f["severity"] == "warning" for f in findings),
        },
        "findings": findings,
        "elements": elements,
        "failed_attachment_ids": failed_elements,
    }
