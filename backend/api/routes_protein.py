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

from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.api import state as design_state

# Shared kernel/infra helpers that stay in crud.py and are imported back:
#   _design_response       — response helper used by 100+ routes (kernel)
#   _geometry_for_helices  — geometry kernel (10 cross-region callers)
#   _find_ovhg_or_404      — trivial overhang lookup (11 overhang-region callers)
# Same convention as routes_camera_poses.py / routes_clusters.py.
from backend.api.crud import _design_response, _find_ovhg_or_404, _geometry_for_helices
from backend.core.models import Design
from backend.core.protein import protein_asset_meta

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
    * no arg — render every visible design ``ProteinAttachment`` placed at its
      overhang anchor, plus any imported asset not yet referenced by an
      attachment at its PDB coordinates.

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
    nucs = None  # geometry lazily computed only if an overhang target needs it
    for att in design.protein_attachments:
        kind = getattr(att.target, "kind", None)
        if kind not in ("free", "overhang") or not att.visible:
            continue  # assembly-scope (Phase 3) / hidden
        asset = assets_by_id.get(att.asset_id)
        if asset is None:
            continue
        tip = outward = None
        if kind == "overhang":
            if nucs is None:
                nucs = _geometry_for_helices(design)
            tip, outward = resolve_overhang_anchor(
                nucs, att.target.overhang_id, att.target.attach_end
            )
            if tip is None:
                continue  # overhang has no geometry yet
        m = compose_protein_world_transform(asset, att, tip, outward)
        models.append(
            protein_asset_to_atomistic(asset, pose_matrix=m, sentinel_id=att.id)
        )

    merged = merge_models(*models) if models else merge_models()
    return atomistic_to_json(merged)


@router.get("/design/protein/conjugation-candidates")
def get_conjugation_candidates(asset_id: str = Query(...)) -> dict:
    """Surface-accessible azide-oligo conjugation sites on a protein asset.

    Read-only.  Returns the residues (Lys ε-amine / Cys thiol / N-terminal amine)
    whose functional atom is solvent-exposed — the viable points for the two-step
    SPAAC conjugation of an azide-modified oligo (see ``backend/core/conjugation``).
    Coordinates are the asset's PDB/local frame, matching the ``?asset_id=``
    atomistic preview render.
    """
    from backend.core.conjugation import find_conjugation_candidates

    asset = _resolve_protein_asset(asset_id)
    if asset is None:
        raise HTTPException(404, detail=f"Protein asset {asset_id} not found.")
    return {"asset_id": asset.id, "candidates": find_conjugation_candidates(asset)}


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
    handle_seq = reverse_complement(spec.sequence) if spec.sequence else None

    attachment = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetDesign(
            overhang_id=body.overhang_id, attach_end=body.attach_end
        ),
        conjugation_atom_serial=conj,
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
    from backend.core.lattice import make_binder_for_overhang
    from backend.core.models import ProteinAttachment, ProteinTargetDesign
    from backend.core.protein import azide_attach_end, reverse_complement

    design = design_state.get_or_404()
    asset = _resolve_protein_asset(body.asset_id)
    if asset is None:
        raise HTTPException(404, detail=f"Protein asset {body.asset_id} not found.")
    spec = _find_ovhg_or_404(design, body.overhang_id)

    # Build the binder once (deterministic id) so the appended strand and the
    # geometry used to resolve the attach end refer to the same object.
    try:
        binder_design = make_binder_for_overhang(design, body.overhang_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    existing_ids = {s.id for s in design.strands}
    binder = next((s for s in binder_design.strands if s.id not in existing_ids), None)
    if binder is None:
        raise HTTPException(500, detail="Binder strand was not created.")

    nucs = _geometry_for_helices(binder_design)
    attach_end = azide_attach_end(nucs, body.overhang_id, binder.id, body.azide_end)

    conj = body.conjugation_atom_serial
    if conj is None:
        conj = asset.default_conjugation_atom_serial
    attachment = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetDesign(overhang_id=body.overhang_id, attach_end=attach_end),
        conjugation_atom_serial=conj,
        handle_sequence=reverse_complement(spec.sequence) if spec.sequence else None,
    )

    def _fn(d: Design) -> Design:
        assets = (
            d.protein_assets
            if any(a.id == asset.id for a in d.protein_assets)
            else [*d.protein_assets, asset]
        )
        return d.copy_with(
            strands=[*d.strands, binder],
            protein_assets=assets,
            protein_attachments=[*d.protein_attachments, attachment],
        )

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-conjugate",
        f"Conjugate {asset.name} to {spec.label or body.overhang_id}",
        {
            "asset_id": asset.id,
            "overhang_id": body.overhang_id,
            "azide_end": body.azide_end,
        },
        _fn,
    )
    from backend.api.crud import _design_response_with_geometry

    resp = _design_response_with_geometry(updated, report)
    resp["attachment_id"] = attachment.id
    resp["binder_strand_id"] = binder.id
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

    def _fn(d: Design) -> None:
        out = []
        for att in d.protein_attachments:
            if att.id != attachment_id:
                out.append(att)
                continue
            upd = {}
            if body.pose is not None:
                upd["pose"] = Mat4x4(values=body.pose)
            if body.gizmo_move is not None:
                new_pose = gizmo_move_to_pose(
                    att.pose.to_array(),
                    body.gizmo_move.pivot,
                    body.gizmo_move.translation,
                    body.gizmo_move.rotation,
                )
                upd["pose"] = Mat4x4.from_array(new_pose)
            if body.conjugation_atom_serial is not None:
                upd["conjugation_atom_serial"] = body.conjugation_atom_serial
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
    return _design_response(updated, report)


@router.delete("/design/protein/attachments/{attachment_id}")
def delete_protein_attachment(attachment_id: str) -> dict:
    """Remove a protein attachment (leaves the asset embedded in the design)."""
    design = design_state.get_or_404()
    if not any(a.id == attachment_id for a in design.protein_attachments):
        raise HTTPException(
            404, detail=f"Protein attachment {attachment_id} not found."
        )

    def _fn(d: Design) -> None:
        d.protein_attachments = [
            a for a in d.protein_attachments if a.id != attachment_id
        ]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-attach-delete",
        "Detach protein",
        {"attachment_id": attachment_id},
        _fn,
    )
    return _design_response(updated, report)
