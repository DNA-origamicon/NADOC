"""
API layer — flexible ssDNA segment route handlers (extracted from crud.py).

This module hosts the ``/design/flexible-segment*``, ``/design/flexible-relax``
and ``/design/flexible-connections`` endpoints. They mark a contiguous run of
UNPAIRED (ssDNA) beads as a flexible tether — each marked run bridging two
EXISTING clusters becomes a fixed-contour-length connection so one cluster can
be dragged free-until-taut. Display-layer only — they NEVER mutate topology.
See ``backend/core/flexible_segments.py`` + ``memory/project_ssdna_ball_joints.md``.

Factored out of ``crud.py`` following the same template as the camera-poses
(13-B), loop-skip (10-F), animations, extensions, and deformation sub-routers.

Routes
------
  POST   /design/flexible-relax              — commit a relax (N cluster poses, 1 feature-log step)
  POST   /design/flexible-segment            — mark one unpaired bead flexible
  DELETE /design/flexible-segment/{mark_id}  — unmark one bead
  POST   /design/flexible-segment/batch      — mark a list (or clear all with replace=true)
  GET    /design/flexible-connections        — derived connections + per-cluster gate

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state

# _design_response_with_geometry is the shared response helper used by 100+
# crud.py routes; it stays in crud.py and is imported back here (same convention
# as routes_camera_poses.py / routes_deformation.py).
from backend.api.crud import _design_response_with_geometry
from backend.core.models import Design

router = APIRouter()


class FlexibleSegmentMarkBody(BaseModel):
    strand_id: str
    domain_index: int
    bp_index: int
    direction: Literal["FORWARD", "REVERSE"]


class FlexibleSegmentBatchBody(BaseModel):
    """Mark an explicit list of unpaired beads (selective — no 'mark all ssDNA').
    ``replace`` clears existing marks first (default appends)."""

    marks: Optional[list[FlexibleSegmentMarkBody]] = None
    replace: bool = False


def _flex_mark_from_body(design: Design, b: FlexibleSegmentMarkBody, unpaired=None):
    """Validate that the addressed bead is UNPAIRED (no Watson-Crick partner) and
    return a FlexibleSegmentMark. Pass a precomputed *unpaired* set for batches."""
    from backend.core.flexible_segments import unpaired_bead_keys
    from backend.core.models import FlexibleSegmentMark, Direction

    s = next((s for s in design.strands if s.id == b.strand_id), None)
    if s is None:
        raise HTTPException(404, detail=f"Strand {b.strand_id!r} not found.")
    if not (0 <= b.domain_index < len(s.domains)):
        raise HTTPException(400, detail="domain_index out of range.")
    d = s.domains[b.domain_index]
    lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
    if not (lo <= b.bp_index <= hi):
        raise HTTPException(400, detail="bp_index outside the domain's range.")
    if unpaired is None:
        unpaired = unpaired_bead_keys(design)
    if (d.helix_id, b.bp_index, Direction(b.direction)) not in unpaired:
        raise HTTPException(
            400, detail="Only unpaired (single-stranded) beads can be flexible."
        )
    return FlexibleSegmentMark(
        strand_id=b.strand_id,
        domain_index=b.domain_index,
        bp_index=b.bp_index,
        direction=Direction(b.direction),
    )


def _flex_log_response(op_kind, label, params, fn):
    """Apply a flexible-segment mutation through the feature log (revertable +
    deletable like other snapshot ops), then ship full geometry so beads
    reclassify out of the rigid meshes and arcs/axis update."""
    updated, validation, _entry = design_state.mutate_with_feature_log(
        op_kind, label, params, fn
    )
    return _design_response_with_geometry(updated, validation)


class FlexibleRelaxTransform(BaseModel):
    """New absolute rigid pose for one cluster, produced by the frontend ssDNA
    relax solve (same {pivot, translation, rotation} shape as a cluster patch)."""

    cluster_id: str
    pivot: list[float]
    translation: list[float]
    rotation: list[float]  # quaternion [x, y, z, w]


class FlexibleRelaxBody(BaseModel):
    """Atomic relax commit: apply N cluster transforms as ONE feature-log step.

    The relax minimisation (pull the smaller cluster of each flexible-connected
    pair in until no tether exceeds its contour length) runs in the frontend on
    live anchor positions; this endpoint just persists the resulting cluster
    poses as a single revertable / deletable / undoable operation."""

    transforms: list[FlexibleRelaxTransform]
    label: Optional[str] = None


@router.post("/design/flexible-relax", status_code=200)
def flexible_relax(body: FlexibleRelaxBody) -> dict:
    """Commit a flexible-segment relax: apply all moved-cluster transforms in a
    single ``mutate_with_feature_log`` step (one SnapshotLogEntry → revertable +
    deletable + a single undo). Display/pose-layer only — never touches topology."""
    if not body.transforms:
        raise HTTPException(400, detail="No cluster transforms provided.")
    design0 = design_state.get_or_404()
    known = {c.id for c in design0.cluster_transforms}
    for t in body.transforms:
        if t.cluster_id not in known:
            raise HTTPException(404, detail=f"Cluster {t.cluster_id!r} not found.")

    def fn(d: Design) -> Design:
        by_id = {t.cluster_id: t for t in body.transforms}
        cts = [
            c.model_copy(
                update={
                    "pivot": list(by_id[c.id].pivot),
                    "translation": list(by_id[c.id].translation),
                    "rotation": list(by_id[c.id].rotation),
                }
            )
            if c.id in by_id
            else c
            for c in d.cluster_transforms
        ]
        return d.copy_with(cluster_transforms=cts)

    n = len(body.transforms)
    label = body.label or (
        "Relax flexible segment" if n == 1 else "Relax flexible segments"
    )
    params = {"cluster_ids": [t.cluster_id for t in body.transforms]}
    updated, validation, _entry = design_state.mutate_with_feature_log(
        "flexible-relax", label, params, fn
    )
    return _design_response_with_geometry(updated, validation)


@router.post("/design/flexible-segment", status_code=200)
def add_flexible_segment(body: FlexibleSegmentMarkBody) -> dict:
    """Mark one unpaired bead flexible and re-derive connections. Feature-log step."""
    from backend.core.flexible_segments import apply_marks

    mark = _flex_mark_from_body(design_state.get_or_404(), body)  # validates unpaired

    def fn(d: Design) -> Design:
        return apply_marks(
            d.copy_with(flexible_segment_marks=list(d.flexible_segment_marks) + [mark])
        )

    return _flex_log_response(
        "flexible-segment-mark", "Mark flexible ssDNA", {"mark_ids": [mark.id]}, fn
    )


@router.delete("/design/flexible-segment/{mark_id}", status_code=200)
def delete_flexible_segment(mark_id: str) -> dict:
    """Remove a flexible-segment mark and re-derive connections. Feature-log step."""
    from backend.core.flexible_segments import apply_marks

    design = design_state.get_or_404()
    if not any(m.id == mark_id for m in design.flexible_segment_marks):
        raise HTTPException(404, detail=f"Flexible-segment mark {mark_id!r} not found.")

    def fn(d: Design) -> Design:
        marks = [m for m in d.flexible_segment_marks if m.id != mark_id]
        return apply_marks(d.copy_with(flexible_segment_marks=marks))

    return _flex_log_response(
        "flexible-segment-unmark", "Unmark flexible ssDNA", {"mark_ids": [mark_id]}, fn
    )


@router.post("/design/flexible-segment/batch", status_code=200)
def batch_flexible_segment(body: FlexibleSegmentBatchBody) -> dict:
    """Mark an explicit list of unpaired beads flexible, re-derive once. Feature-log
    step. ``replace=True`` with no marks clears all flexible segments."""
    from backend.core.flexible_segments import apply_marks, unpaired_bead_keys
    from backend.core.models import FlexibleSegmentMark

    design = design_state.get_or_404()

    new_marks: list[FlexibleSegmentMark] = []
    if body.marks:
        unpaired = unpaired_bead_keys(design)
        for mb in body.marks:
            new_marks.append(_flex_mark_from_body(design, mb, unpaired))
    if not new_marks and not body.replace:
        raise HTTPException(
            400, detail="No marks supplied (use marks=[...] or replace=true to clear)."
        )

    def fn(d: Design) -> Design:
        existing = [] if body.replace else list(d.flexible_segment_marks)
        seen, merged = set(), []
        for m in existing + new_marks:
            kdup = (m.strand_id, m.domain_index, m.bp_index, m.direction)
            if kdup in seen:
                continue
            seen.add(kdup)
            merged.append(m)
        return apply_marks(d.copy_with(flexible_segment_marks=merged))

    is_clear = body.replace and not new_marks
    op_kind = "flexible-segment-unmark" if is_clear else "flexible-segment-mark"
    label = (
        "Clear flexible ssDNA"
        if is_clear
        else f"Mark flexible ssDNA ({len(new_marks)} base{'' if len(new_marks) == 1 else 's'})"
    )
    return _flex_log_response(
        op_kind, label, {"n_marks": len(new_marks), "replace": body.replace}, fn
    )


@router.get("/design/flexible-connections", status_code=200)
def get_flexible_connections() -> dict:
    """Derived flexible connections + per-cluster gate (no mutation). The gate tells the
    frontend which clusters can use the 'Constrained (tethers)' drag via ssDNA segments;
    ``connection_tether_clusters`` extends that availability to clusters constrained by an
    applied overhang connection (direct duplex / ss-ds linker) even with no ssDNA marks."""
    from backend.core.connection_tethers import clusters_with_connection_tethers
    from backend.core.flexible_segments import all_cluster_gates

    design = design_state.get_or_404()
    return {
        "connections": [c.model_dump() for c in design.flexible_connections],
        "gates": all_cluster_gates(design),
        "n_marks": len(design.flexible_segment_marks),
        "connection_tether_clusters": clusters_with_connection_tethers(design),
    }
