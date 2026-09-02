"""
API layer — protein import/library + attachment route handlers (extracted from crud.py).

Display-only: proteins are imported from PDB into a session-level library and
anchored to overhangs as ``ProteinAttachment`` records.  None of these routes
touch the strand graph (Three-Layer Law — physical/display state only).  See
``backend/core/protein.py`` for the PDB parsing + pose math.

Routes
------
  POST   /design/protein/import                       — import a protein from PDB (library)
  GET    /design/protein/library                      — list session library (metadata only)
  DELETE /design/protein/{asset_id}                   — remove a library asset
  GET    /design/protein/atomistic                    — all-atom geometry for the renderer
  POST   /design/protein/attachments                  — anchor a protein to an overhang (undo)
  PATCH  /design/protein/attachments/{attachment_id}  — update pose / conjugation / handle / visibility
  DELETE /design/protein/attachments/{attachment_id}  — detach a protein (undo)

URLs are unchanged from their previous home in crud.py.  Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.  See the carve-up loop
in ``backend_router_carveup.md`` (Refactor #41).
"""

from __future__ import annotations

import time
import uuid
from typing import List, Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.api import state as design_state

# Shared kernel/infra helpers that stay in crud.py and are imported back:
#   _design_response       — response helper used by 100+ routes (kernel)
#   _geometry_for_helices  — geometry kernel (10 cross-region callers)
#   _find_ovhg_or_404      — trivial overhang lookup (11 overhang-region callers)
# Same convention as routes_camera_poses.py / routes_clusters.py.
from backend.api.crud import (
    _design_response,
    _design_response_with_geometry,
    _find_ovhg_or_404,
    _geometry_for_helices,
)
from backend.core.models import Design
from backend.core.protein import protein_asset_meta
from backend.core.render_diff import _local_changed_helices, _strand_occupancy

router = APIRouter()


# ── Protein import + library (display-only; see backend/core/protein.py) ───────


class ProteinImportRequest(BaseModel):
    content: str  # raw PDB file text sent by the browser
    name: str = ""  # display name (defaults to filename)
    source_filename: str = ""


@router.post("/design/protein/import", status_code=201)
def import_protein(body: ProteinImportRequest) -> dict:
    """Import a protein from PDB into the session library.

    Keeps protein/HETATM atoms (drops only water + ions).  The asset is stored
    in the session-level library, decoupled from any one design, so it can be
    attached across designs.  Returns library metadata only (not the full atom
    list — fetch atoms via ``GET /design/protein/atomistic``).
    """
    from backend.core.protein import parse_protein_pdb

    try:
        asset = parse_protein_pdb(
            body.content,
            name=body.name,
            source_filename=body.source_filename,
        )
    except Exception as exc:
        raise HTTPException(400, detail=f"Protein PDB import failed: {exc}") from exc
    if not asset.atoms:
        raise HTTPException(
            400, detail="No protein atoms found in PDB (only water/ions/DNA?)."
        )
    design_state.add_protein_asset(asset)
    return protein_asset_meta(asset)


@router.get("/design/protein/library")
def list_protein_library() -> dict:
    """List all protein assets in the session library (metadata only)."""
    return {
        "assets": [protein_asset_meta(a) for a in design_state.list_protein_assets()]
    }


@router.delete("/design/protein/{asset_id}")
def delete_protein_asset(asset_id: str) -> dict:
    """Remove a protein asset from the session library."""
    if not design_state.remove_protein_asset(asset_id):
        raise HTTPException(404, detail=f"Protein asset {asset_id} not found.")
    return {"removed": asset_id}


@router.get("/design/protein/atomistic")
def get_protein_atomistic(asset_id: str | None = Query(None)) -> dict:
    """Return all-atom protein geometry for the renderer.

    * ``?asset_id=`` — render that single asset at its imported PDB coordinates
      (library preview).
    * no arg — render every visible design ``ProteinAttachment`` at its target.

    Response shape matches ``GET /design/atomistic`` ({ atoms, bonds, element_meta }).
    """
    from backend.core.atomistic import atomistic_to_json, merge_models
    from backend.core.protein import (
        compose_protein_world_transform,
        protein_asset_to_atomistic,
        resolve_overhang_anchor,
    )

    if asset_id is not None:
        asset = _resolve_protein_asset(asset_id)
        if asset is None:
            raise HTTPException(404, detail=f"Protein asset {asset_id} not found.")
        return atomistic_to_json(protein_asset_to_atomistic(asset))

    design = design_state.get_design()
    if design is None:
        return atomistic_to_json(merge_models())

    # The scene shows EXACTLY the design's attachments (the single source of
    # truth) — never the session library directly.  This keeps move / delete /
    # undo / redo correct: whatever the design holds is what renders, and an
    # undone import (no attachment) renders nothing.  Assets are resolved from
    # the design's embedded copies, with the session library as a fallback.
    assets_by_id = {a.id: a for a in design.protein_assets}
    for a in design_state.list_protein_assets():
        assets_by_id.setdefault(a.id, a)

    models = []
    constraints = []
    target_helix_ids = {
        ovhg.helix_id
        for att in design.protein_attachments
        if getattr(att.target, "kind", None) == "overhang" and att.visible
        for ovhg in design.overhangs
        if ovhg.id == att.target.overhang_id
    }
    # Protein placement only needs its target overhang helices.  On large designs
    # computing every unrelated helix here dominated every post-move refresh.
    nucs = (
        _geometry_for_helices(design, frozenset(target_helix_ids))
        if target_helix_ids
        else None
    )
    for att in design.protein_attachments:
        kind = getattr(att.target, "kind", None)
        if kind not in ("free", "overhang") or not att.visible:
            continue  # assembly-scope (Phase 3) / hidden
        asset = assets_by_id.get(att.asset_id)
        if asset is None:
            continue
        tip = outward = None
        if kind == "overhang":
            tip, outward = resolve_overhang_anchor(
                nucs, att.target.overhang_id, att.target.attach_end
            )
            if tip is None:
                continue  # overhang has no geometry yet
        m = compose_protein_world_transform(asset, att, tip, outward)
        if att.binder_strand_id and att.conjugation_atom_serial is not None:
            from backend.core.protein import _conjugate_terminus_position

            root, _ = resolve_overhang_anchor(nucs, att.target.overhang_id, "root")
            terminus = _conjugate_terminus_position(nucs, att)
            if root is not None and terminus is not None:
                overhang = next(
                    o for o in design.overhangs if o.id == att.target.overhang_id
                )
                domain_ids = [
                    {"strand_id": strand.id, "domain_index": index}
                    for strand in design.strands
                    for index, domain in enumerate(strand.domains)
                    if domain.overhang_id == overhang.id
                    or domain.binds_overhang_id == overhang.id
                ]
                is_extrude = not any(
                    strand.strand_type.value == "scaffold"
                    and any(domain.helix_id == overhang.helix_id for domain in strand.domains)
                    for strand in design.strands
                )
                constraints.append(
                    {
                        "attachment_id": att.id,
                        "mode": "two_ball_joint",
                        "root": root.tolist(),
                        "joint": terminus.tolist(),
                        "radius_nm": float(np.linalg.norm(terminus - root)),
                        "helix_id": overhang.helix_id,
                        "overhang_id": overhang.id,
                        "domain_ids": domain_ids,
                        "is_extrude": is_extrude,
                    }
                )
        models.append(
            protein_asset_to_atomistic(asset, pose_matrix=m, sentinel_id=att.id)
        )

    merged = merge_models(*models) if models else merge_models()
    payload = atomistic_to_json(merged)
    payload["protein_constraints"] = constraints
    return payload


@router.get("/design/protein/conjugation-candidates")
def get_conjugation_candidates(
    asset_id: str = Query(...), operation_id: str | None = Query(None)
) -> dict:
    """Surface-accessible azide-oligo conjugation sites on a protein asset.

    Read-only.  Returns the residues (Lys ε-amine / Cys thiol / N-terminal amine)
    whose functional atom is solvent-exposed — the viable points for the two-step
    SPAAC conjugation of an azide-modified oligo (see ``backend/core/conjugation``).
    Coordinates are the asset's PDB/local frame, matching the ``?asset_id=``
    atomistic preview render.
    """
    from backend.core.conjugation import find_conjugation_candidates_cached

    asset = _resolve_protein_asset(asset_id)
    if asset is None:
        raise HTTPException(404, detail=f"Protein asset {asset_id} not found.")
    started = time.perf_counter()
    candidates, cache_hit = find_conjugation_candidates_cached(asset)
    metrics = {
        "schema_version": 1,
        "operation_id": operation_id or str(uuid.uuid4()),
        "outcome": "completed",
        "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stage": "candidate_analysis",
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stages_ms": {
            "candidate_analysis": round(
                (time.perf_counter() - started) * 1000.0, 3
            )
        },
        "cache_hit": cache_hit,
        "candidate_count": len(candidates),
    }
    from backend.core.protein_metrics import record_protein_process

    record_protein_process("candidate_analysis", metrics)
    return {
        "asset_id": asset.id,
        # The candidate/overhang choices belong to this exact design snapshot.
        # Apply uses it for optimistic concurrency instead of a potentially
        # stale frontend-global watermark.
        "design_revision": design_state.revision(),
        "candidates": candidates,
        "process_metrics": metrics,
    }


@router.get("/design/protein/metrics")
def get_protein_process_metrics() -> dict:
    """Rolling p50/p95 process telemetry; contains no molecular content."""
    from backend.core.protein_metrics import protein_process_summary

    return protein_process_summary()


@router.get("/design/protein/validation")
def get_protein_validation(operation_id: str | None = Query(None)) -> dict:
    """Quantitatively audit every persisted protein placement/conjugate."""
    from backend.core.protein_validation import audit_protein_design

    design = design_state.get_or_404()
    needs_geometry = any(
        getattr(a.target, "kind", None) == "overhang"
        for a in design.protein_attachments
    )
    started = time.perf_counter()
    stage_started = time.perf_counter()
    geometry = _geometry_for_helices(design) if needs_geometry else []
    geometry_ms = (time.perf_counter() - stage_started) * 1000.0
    stage_started = time.perf_counter()
    report = audit_protein_design(design, geometry)
    audit_ms = (time.perf_counter() - stage_started) * 1000.0
    report["audit_ms"] = round(audit_ms, 3)
    metrics = {
        "schema_version": 1,
        "operation_id": operation_id or str(uuid.uuid4()),
        "outcome": "valid" if report["valid"] else "invalid",
        "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stages_ms": {
            "geometry": round(geometry_ms, 3),
            "element_audit": round(audit_ms, 3),
        },
    }
    from backend.core.protein_metrics import record_protein_process

    record_protein_process("validation", metrics)
    report["process_metrics"] = metrics
    return report


class ProteinDuplicateRepairRequest(BaseModel):
    free_attachment_id: str
    conjugated_attachment_id: str
    apply: bool = False


@router.post("/design/protein/validation/repair-duplicate")
def repair_protein_duplicate(body: ProteinDuplicateRepairRequest) -> dict:
    """Preview or apply a narrowly proven legacy import→conjugate repair.

    The endpoint never guesses from asset cardinality alone. It requires the
    exact pair reported as ``legacy_unconverted_free_placement`` and defaults
    to a read-only preview. Applying records a normal feature-log mutation.
    """
    from backend.core.protein_validation import audit_protein_design

    design = design_state.get_or_404()
    geometry = _geometry_for_helices(design)
    before = audit_protein_design(design, geometry)
    finding = next(
        (
            item
            for item in before["findings"]
            if item["code"] == "legacy_unconverted_free_placement"
            and item.get("repairable")
            and item["free_attachment_ids"] == [body.free_attachment_id]
            and item["conjugated_attachment_ids"] == [body.conjugated_attachment_id]
        ),
        None,
    )
    if finding is None:
        raise HTTPException(
            409,
            detail="The requested pair is not an unambiguous legacy duplicate; no changes made.",
        )
    if not body.apply:
        return {
            "applied": False,
            "would_remove_attachment_id": body.free_attachment_id,
            "validation_before": before,
        }

    def _fn(d: Design) -> None:
        d.protein_attachments = [
            attachment
            for attachment in d.protein_attachments
            if attachment.id != body.free_attachment_id
        ]
        for override in d.representation_overrides:
            override.protein_attachment_ids = [
                item for item in override.protein_attachment_ids
                if item != body.free_attachment_id
            ]
        d.representation_overrides = [
            override for override in d.representation_overrides
            if override.segments or override.protein_attachment_ids
        ]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-attach-delete",
        "Repair legacy duplicate protein placement",
        {
            "attachment_id": body.free_attachment_id,
            "kept_attachment_id": body.conjugated_attachment_id,
            "repair": "legacy-import-conjugate-duplicate",
        },
        _fn,
    )
    after = audit_protein_design(updated, _geometry_for_helices(updated))
    resp = _design_response(updated, report)
    resp.update(
        {
            "applied": True,
            "removed_attachment_id": body.free_attachment_id,
            "kept_attachment_id": body.conjugated_attachment_id,
            "validation_before": before,
            "validation_after": after,
        }
    )
    return resp


# ── Protein attachments (anchor a protein to an overhang; display-only) ────────


def _resolve_protein_asset(asset_id: str):
    """Find a protein asset in the session library, then the active design."""
    asset = design_state.get_protein_asset(asset_id)
    if asset is not None:
        return asset
    design = design_state.get_design()
    if design is not None:
        return next((a for a in design.protein_assets if a.id == asset_id), None)
    return None


class ProteinAttachRequest(BaseModel):
    asset_id: str
    overhang_id: str
    attach_end: Literal["free_end", "root"] = "free_end"
    conjugation_atom_serial: Optional[int] = None
    handle_complement_bp: int = 0
    handle_spacer_nt: int = 0


@router.post("/design/protein/attachments", status_code=201)
def create_protein_attachment(body: ProteinAttachRequest) -> dict:
    """Anchor a protein to an overhang in the active design.

    Embeds the referenced asset into the design (so the file is self-contained)
    and records a display-only ``ProteinAttachment``.  Does NOT touch the strand
    graph.
    """
    from backend.core.models import ProteinAttachment, ProteinTargetDesign
    from backend.core.protein import reverse_complement

    design = design_state.get_or_404()
    asset = _resolve_protein_asset(body.asset_id)
    if asset is None:
        raise HTTPException(404, detail=f"Protein asset {body.asset_id} not found.")
    spec = _find_ovhg_or_404(design, body.overhang_id)

    conj = body.conjugation_atom_serial
    if conj is None:
        conj = asset.default_conjugation_atom_serial
    from backend.core.conjugation import conjugation_candidate_for_serial

    selected_candidate = (
        conjugation_candidate_for_serial(asset, conj) if conj is not None else None
    )
    handle_seq = reverse_complement(spec.sequence) if spec.sequence else None

    attachment = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetDesign(
            overhang_id=body.overhang_id, attach_end=body.attach_end
        ),
        conjugation_atom_serial=conj,
        conjugation_chemistry=(
            selected_candidate["chemistry"] if selected_candidate else None
        ),
        conjugation_accessible_fraction=(
            selected_candidate["accessible"] if selected_candidate else None
        ),
        handle_complement_bp=body.handle_complement_bp,
        handle_spacer_nt=body.handle_spacer_nt,
        handle_sequence=handle_seq,
    )

    def _fn(d: Design) -> None:
        if not any(a.id == asset.id for a in d.protein_assets):
            d.protein_assets = [*d.protein_assets, asset]
        d.protein_attachments = [*d.protein_attachments, attachment]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-attach",
        f"Attach protein {asset.name} to {spec.label or body.overhang_id}",
        {"asset_id": asset.id, "overhang_id": body.overhang_id},
        _fn,
    )
    resp = _design_response(updated, report)
    resp["attachment_id"] = attachment.id
    return resp


class ProteinConjugateRequest(BaseModel):
    asset_id: str
    overhang_id: str
    # When conjugation starts from a rendered protein, convert that placement
    # instead of creating a second instance.  Omitted for library-only assets.
    source_attachment_id: Optional[str] = None
    operation_id: Optional[str] = None
    expected_revision: Optional[int] = None
    conjugation_atom_serial: Optional[int] = None
    azide_end: Literal["5p", "3p"] = "5p"


@router.post("/design/protein/conjugate", status_code=201)
def conjugate_protein_to_overhang(body: ProteinConjugateRequest) -> dict:
    """Commit an azide-oligo conjugation into the design (one undo step).

    Creates the ssDNA handle as a real **overhang-binding domain** (an OH_BINDER
    strand antiparallel to the overhang — ``make_binder_for_overhang``), and
    attaches the protein so its selected conjugation residue coincides with the
    binder terminus the user marked as the azide end (``azide_end`` → the nearer
    overhang end, via ``azide_attach_end``).  The strand edit + the display-only
    attachment land as a single feature-log entry.
    """
    operation_id = body.operation_id or str(uuid.uuid4())
    started = time.perf_counter()
    stages_ms: dict[str, float] = {}

    from backend.core.lattice import make_binder_for_overhang
    from backend.core.models import ProteinAttachment, ProteinTargetDesign
    from backend.core.protein import azide_attach_end

    design = design_state.get_or_404()
    if body.operation_id is not None and any(
        getattr(entry, "op_kind", None) == "protein-conjugate"
        and entry.params.get("operation_id") == body.operation_id
        for entry in design.feature_log
    ):
        raise HTTPException(
            409, detail=f"Conjugation operation {body.operation_id} was already committed."
        )
    asset = _resolve_protein_asset(body.asset_id)
    if asset is None:
        raise HTTPException(404, detail=f"Protein asset {body.asset_id} not found.")
    spec = _find_ovhg_or_404(design, body.overhang_id)
    source_attachment = None
    if body.source_attachment_id is not None:
        source_attachment = next(
            (a for a in design.protein_attachments if a.id == body.source_attachment_id),
            None,
        )
        if source_attachment is None:
            raise HTTPException(404, detail="Source protein attachment not found.")
        if source_attachment.asset_id != asset.id:
            raise HTTPException(
                400, detail="Source protein attachment does not reference this asset."
            )
        if getattr(source_attachment.target, "kind", None) != "free":
            raise HTTPException(
                409,
                detail=(
                    "Only a free protein placement can be converted. Detach an existing "
                    "conjugate before attaching it to another overhang."
                ),
            )
    stages_ms["resolve_inputs"] = (time.perf_counter() - started) * 1000.0

    # Build the binder once (deterministic id) so the appended strand and the
    # geometry used to resolve the attach end refer to the same object.
    try:
        stage_started = time.perf_counter()
        binder_design = make_binder_for_overhang(design, body.overhang_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    existing_ids = {s.id for s in design.strands}
    binder = next((s for s in binder_design.strands if s.id not in existing_ids), None)
    if binder is None:
        raise HTTPException(500, detail="Binder strand was not created.")
    stages_ms["build_binder"] = (time.perf_counter() - stage_started) * 1000.0

    stage_started = time.perf_counter()
    nucs = _geometry_for_helices(binder_design)
    attach_end = azide_attach_end(nucs, body.overhang_id, binder.id, body.azide_end)
    stages_ms["resolve_geometry"] = (time.perf_counter() - stage_started) * 1000.0

    conj = body.conjugation_atom_serial
    if conj is None:
        conj = asset.default_conjugation_atom_serial
    from backend.core.conjugation import conjugation_candidate_for_serial

    selected_candidate = (
        conjugation_candidate_for_serial(asset, conj) if conj is not None else None
    )
    attachment_kwargs = (
        {"id": source_attachment.id} if source_attachment is not None else {}
    )
    attachment = ProteinAttachment(
        **attachment_kwargs,
        asset_id=asset.id,
        target=ProteinTargetDesign(overhang_id=body.overhang_id, attach_end=attach_end),
        conjugation_atom_serial=conj,
        conjugation_chemistry=(
            selected_candidate["chemistry"] if selected_candidate else None
        ),
        conjugation_accessible_fraction=(
            selected_candidate["accessible"] if selected_candidate else None
        ),
        binder_strand_id=binder.id,
        azide_end=body.azide_end,
        # Cache the sequence of the REAL topology element, not a second
        # derivation from OverhangSpec that could diverge on sub-domain overrides.
        handle_sequence=binder.sequence,
    )
    # Affix the selected protein atom to the actual binder backbone terminus,
    # not the opposite strand's base-pair axis.  The two backbones are radially
    # separated, so this offset is physically meaningful.
    from backend.core.models import Mat4x4
    from backend.core.protein import _conjugate_terminus_position, resolve_overhang_anchor

    binder_tip = _conjugate_terminus_position(nucs, attachment)
    overhang_tip, _ = resolve_overhang_anchor(
        nucs, body.overhang_id, attachment.target.attach_end
    )
    if binder_tip is not None and overhang_tip is not None:
        delta = binder_tip - overhang_tip
        values = np.eye(4)
        values[:3, 3] = delta
        attachment.pose = Mat4x4.from_array(values)

    def _fn(d: Design) -> Design:
        assets = (
            d.protein_assets
            if any(a.id == asset.id for a in d.protein_assets)
            else [*d.protein_assets, asset]
        )
        return d.copy_with(
            strands=[*d.strands, binder],
            protein_assets=assets,
            protein_attachments=[
                *(
                    a
                    for a in d.protein_attachments
                    if source_attachment is None or a.id != source_attachment.id
                ),
                attachment,
            ],
        )

    # Validate the complete proposed element before touching shared design
    # state. This turns every metric into a commit gate, not post-hoc telemetry.
    stage_started = time.perf_counter()
    from backend.core.protein_validation import validate_protein_conjugate

    proposed = _fn(design)
    element_validation = validate_protein_conjugate(
        design,
        proposed,
        asset=asset,
        attachment=attachment,
        binder=binder,
        geometry=nucs,
        source_attachment_id=body.source_attachment_id,
    )
    stages_ms["validate_element"] = (time.perf_counter() - stage_started) * 1000.0
    if not element_validation["valid"]:
        process_metrics = {
            "schema_version": 1,
            "operation_id": operation_id,
            "outcome": "rejected_invalid",
            "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "stages_ms": {
                name: round(value, 3) for name, value in stages_ms.items()
            },
        }
        from backend.core.protein_metrics import record_protein_process

        record_protein_process("conjugation", process_metrics)
        raise HTTPException(
            422,
            detail={
                "message": "Protein conjugate failed element validation; no changes committed.",
                "operation_id": operation_id,
                "element_validation": element_validation,
                "process_metrics": process_metrics,
            },
        )

    before_occ = _strand_occupancy(design)
    stage_started = time.perf_counter()
    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-conjugate",
        f"Conjugate {asset.name} to {spec.label or body.overhang_id}",
        {
            "asset_id": asset.id,
            "overhang_id": body.overhang_id,
            "azide_end": body.azide_end,
            "source_attachment_id": body.source_attachment_id,
            "operation_id": operation_id,
            "attachment_id": attachment.id,
            "binder_strand_id": binder.id,
        },
        _fn,
        expected_revision=body.expected_revision,
    )
    stages_ms["commit"] = (time.perf_counter() - stage_started) * 1000.0
    from backend.api.crud import _design_response_with_geometry

    changed = _local_changed_helices(before_occ, _strand_occupancy(updated))
    resp = _design_response_with_geometry(
        updated, report, changed_helix_ids=changed, compact_deformed=True,
    )
    resp["attachment_id"] = attachment.id
    resp["binder_strand_id"] = binder.id
    resp["element_validation"] = element_validation
    resp["process_metrics"] = {
        "schema_version": 1,
        "operation_id": operation_id,
        "outcome": "committed",
        "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stages_ms": {name: round(value, 3) for name, value in stages_ms.items()},
    }
    from backend.core.protein_metrics import record_protein_process

    record_protein_process("conjugation", resp["process_metrics"])
    return resp


class ProteinGizmoMove(BaseModel):
    """A world-space gizmo delta (cluster-gizmo convention)."""

    pivot: List[float]  # rotation centre (world nm)
    translation: List[float]  # additional world offset
    rotation: List[float]  # quaternion [x, y, z, w] about pivot


class ProteinAttachPatchRequest(BaseModel):
    pose: Optional[List[float]] = None  # 16-float row-major 4×4 (absolute)
    gizmo_move: Optional[ProteinGizmoMove] = None  # incremental world-space move
    conjugation_atom_serial: Optional[int] = None
    handle_complement_bp: Optional[int] = None
    handle_spacer_nt: Optional[int] = None
    visible: Optional[bool] = None


@router.patch("/design/protein/attachments/{attachment_id}")
def patch_protein_attachment(
    attachment_id: str, body: ProteinAttachPatchRequest
) -> dict:
    """Update a protein attachment's pose / conjugation atom / handle / visibility.

    A move is expressed either as an absolute ``pose`` (16-float row-major 4×4)
    or as an incremental ``gizmo_move`` (left-multiplied into the current pose).
    Logged as ``protein-attach-patch`` for undo/redo.
    """
    from backend.core.models import Mat4x4
    from backend.core.protein import gizmo_move_to_pose

    design = design_state.get_or_404()
    if not any(a.id == attachment_id for a in design.protein_attachments):
        raise HTTPException(
            404, detail=f"Protein attachment {attachment_id} not found."
        )
    if body.pose is not None and len(body.pose) != 16:
        raise HTTPException(400, detail="pose must be 16 floats (row-major 4×4).")
    current_attachment = next(
        a for a in design.protein_attachments if a.id == attachment_id
    )
    selected_candidate = None
    if body.conjugation_atom_serial is not None:
        from backend.core.conjugation import conjugation_candidate_for_serial

        asset = _resolve_protein_asset(current_attachment.asset_id)
        selected_candidate = (
            conjugation_candidate_for_serial(asset, body.conjugation_atom_serial)
            if asset is not None
            else None
        )
        if selected_candidate is None:
            raise HTTPException(
                422,
                detail="Conjugation atom must be a supported surface-accessible site.",
            )

    constraint_result = None
    constrained_pose = None
    constrained_rotation = None
    if body.gizmo_move is not None and current_attachment.binder_strand_id:
        from backend.core.protein import constrained_conjugate_move

        asset = _resolve_protein_asset(current_attachment.asset_id)
        if asset is None:
            raise HTTPException(422, detail="Conjugated protein asset is missing.")
        target_spec = next(
            (
                ovhg
                for ovhg in design.overhangs
                if ovhg.id == current_attachment.target.overhang_id
            ),
            None,
        )
        if target_spec is None:
            raise HTTPException(422, detail="Conjugated protein overhang is missing.")
        try:
            constrained_pose, constrained_rotation, constraint_result = (
                constrained_conjugate_move(
                    design,
                    asset,
                    current_attachment,
                    _geometry_for_helices(
                        design, frozenset({target_spec.helix_id})
                    ),
                    pivot=body.gizmo_move.pivot,
                    translation=body.gizmo_move.translation,
                    rotation=body.gizmo_move.rotation,
                )
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    def _fn(d: Design) -> None:
        if constrained_rotation is not None:
            d.overhangs = [
                ovhg.model_copy(update={"rotation": constrained_rotation})
                if ovhg.id == current_attachment.target.overhang_id
                else ovhg
                for ovhg in d.overhangs
            ]
        out = []
        for att in d.protein_attachments:
            if att.id != attachment_id:
                out.append(att)
                continue
            upd = {}
            if body.pose is not None:
                upd["pose"] = Mat4x4(values=body.pose)
            if body.gizmo_move is not None:
                new_pose = (
                    constrained_pose
                    if constrained_pose is not None
                    else gizmo_move_to_pose(
                        att.pose.to_array(),
                        body.gizmo_move.pivot,
                        body.gizmo_move.translation,
                        body.gizmo_move.rotation,
                    )
                )
                upd["pose"] = Mat4x4.from_array(new_pose)
            if body.conjugation_atom_serial is not None:
                upd["conjugation_atom_serial"] = body.conjugation_atom_serial
                upd["conjugation_chemistry"] = selected_candidate["chemistry"]
                upd["conjugation_accessible_fraction"] = selected_candidate[
                    "accessible"
                ]
            if body.handle_complement_bp is not None:
                upd["handle_complement_bp"] = body.handle_complement_bp
            if body.handle_spacer_nt is not None:
                upd["handle_spacer_nt"] = body.handle_spacer_nt
            if body.visible is not None:
                upd["visible"] = body.visible
            out.append(att.model_copy(update=upd))
        d.protein_attachments = out

    label = (
        "Move protein"
        if (body.pose is not None or body.gizmo_move is not None)
        else "Edit protein attachment"
    )
    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-attach-patch",
        label,
        {"attachment_id": attachment_id},
        _fn,
    )
    if constraint_result is not None:
        changed_spec = next(
            ovhg
            for ovhg in updated.overhangs
            if ovhg.id == current_attachment.target.overhang_id
        )
        response = _design_response_with_geometry(
            updated,
            report,
            changed_helix_ids=[changed_spec.helix_id],
            compact_deformed=True,
            partial_axes=True,
        )
    else:
        response = _design_response(updated, report)
    if constraint_result is not None:
        response["protein_constraint"] = constraint_result
    return response


@router.delete("/design/protein/attachments/{attachment_id}")
def delete_protein_attachment(attachment_id: str) -> dict:
    """Remove a protein attachment and its owned conjugate binder, if any."""
    design = design_state.get_or_404()
    attachment = next(
        (a for a in design.protein_attachments if a.id == attachment_id), None
    )
    if attachment is None:
        raise HTTPException(
            404, detail=f"Protein attachment {attachment_id} not found."
        )

    binder_id = None
    overhang_id = getattr(attachment.target, "overhang_id", None)
    if overhang_id is not None:
        # New entries carry exact IDs. Legacy entries are repairable only when
        # history proves a conjugation and the target has one unambiguous binder.
        log_entry = next(
            (
                entry
                for entry in reversed(design.feature_log)
                if getattr(entry, "op_kind", None) == "protein-conjugate"
                and entry.params.get("asset_id") == attachment.asset_id
                and entry.params.get("overhang_id") == overhang_id
                and (
                    entry.params.get("attachment_id") in (None, attachment.id)
                )
            ),
            None,
        )
        if log_entry is not None:
            logged_binder = log_entry.params.get("binder_strand_id")
            candidates = [
                strand
                for strand in design.strands
                if any(
                    domain.binds_overhang_id == overhang_id
                    for domain in strand.domains
                )
            ]
            if logged_binder and any(s.id == logged_binder for s in candidates):
                binder_id = logged_binder
            elif len(candidates) == 1:
                binder_id = candidates[0].id

    def _fn(d: Design) -> None:
        d.protein_attachments = [
            a for a in d.protein_attachments if a.id != attachment_id
        ]
        for override in d.representation_overrides:
            override.protein_attachment_ids = [
                item for item in override.protein_attachment_ids
                if item != attachment_id
            ]
        d.representation_overrides = [
            override for override in d.representation_overrides
            if override.segments or override.protein_attachment_ids
        ]
        if binder_id is not None:
            d.strands = [strand for strand in d.strands if strand.id != binder_id]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-attach-delete",
        "Detach protein",
        {"attachment_id": attachment_id, "binder_strand_id": binder_id},
        _fn,
    )
    if binder_id is None:
        return _design_response(updated, report)
    from backend.api.crud import _design_response_with_geometry

    return _design_response_with_geometry(
        updated,
        report,
        changed_helix_ids={
            domain.helix_id
            for strand in design.strands
            if strand.id == binder_id
            for domain in strand.domains
        },
        compact_deformed=True,
    )
