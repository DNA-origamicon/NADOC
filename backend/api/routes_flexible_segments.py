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

import time
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Response
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


def _flex_mark_from_body(design: Design, b: FlexibleSegmentMarkBody, unpaired=None, *, identity=None):
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
    from uuid import uuid4
    return FlexibleSegmentMark(
        id=identity or str(uuid4()),
        strand_id=b.strand_id,
        domain_index=b.domain_index,
        bp_index=b.bp_index,
        direction=Direction(b.direction),
    )


def _require_connected_marks(design: Design, marks):
    """Reject new inert marks without changing the document or its history.

    Keep this admission rule out of replay: older saved operations may contain
    intra-cluster marks and must remain faithfully replayable/removable.
    """
    def key(mark):
        return mark.strand_id, mark.domain_index, mark.bp_index, mark.direction

    connected = {key(bead) for connection in design.flexible_connections
                 for bead in connection.segment_bead_keys}
    if any(key(mark) not in connected for mark in marks):
        raise HTTPException(422, detail={
            "code": "flexible_connection_requires_distinct_clusters",
            "message": "flexible connections must be between two different cluster",
        })
    return design


def _mark_helix_ids(design: Design, marks) -> set[str]:
    """Helices whose per-nucleotide flexible classification can change."""
    strands = {strand.id: strand for strand in design.strands}
    result: set[str] = set()
    for mark in marks:
        strand = strands.get(mark.strand_id)
        if strand is not None and 0 <= mark.domain_index < len(strand.domains):
            result.add(strand.domains[mark.domain_index].helix_id)
    return result


def _flex_log_response(
    response: Response, op_kind, label, params, fn, changed_helix_ids
):
    """Apply a flexible-segment mutation through the feature log (revertable +
    deletable like other snapshot ops), then ship only the affected helices so
    beads reclassify out of the rigid meshes and arcs update."""
    started = time.perf_counter()
    updated, validation, _entry = design_state.mutate_with_feature_log(
        op_kind, label, params, fn
    )
    mutated = time.perf_counter()
    payload = _design_response_with_geometry(
        updated,
        validation,
        changed_helix_ids=sorted(changed_helix_ids),
    )
    built = time.perf_counter()
    response.headers["Server-Timing"] = (
        f"flex_mutate;dur={(mutated - started) * 1000:.1f}, "
        f"flex_geometry;dur={(built - mutated) * 1000:.1f}"
    )
    return payload


class FlexibleRelaxTransform(BaseModel):
    """Absolute rigid pose from a solve (same shape as a cluster patch)."""

    cluster_id: str
    pivot: list[float]
    translation: list[float]
    rotation: list[float]  # quaternion [x, y, z, w]


class FlexibleRelaxBody(BaseModel):
    """Solve a connected flexible network or commit explicitly supplied poses.

    Scope requests use the authoritative joint solver, fixing the largest body.
    Explicit poses remain supported for existing integrations and replay.
    """

    transforms: list[FlexibleRelaxTransform] = []
    label: Optional[str] = None
    scope: Optional[Literal["all", "one"]] = None
    conn_id: Optional[str] = None


@router.post("/design/flexible-relax", status_code=200)
def flexible_relax(body: FlexibleRelaxBody) -> dict:
    """Commit a flexible-segment relax: apply all moved-cluster transforms in a
    single ``mutate_with_feature_log`` step (one SnapshotLogEntry → revertable +
    deletable + a single undo). Display/pose-layer only — never touches topology."""
    source_revision = design_state.revision()
    design0 = design_state.get_or_404()
    result = None
    if body.scope is not None:
        if body.transforms:
            raise HTTPException(400, detail="Supply a solve scope or explicit poses, not both.")
        from backend.core.flexible_network import solve_design_network
        try:
            result = solve_design_network(design0, scope=body.scope, conn_id=body.conn_id)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        if not result["converged"]:
            raise HTTPException(422, detail={
                "message": f"Flexible relaxation did not converge; maximum remaining overstretch "
                           f"{result['max_excess_nm']:.3f} nm, duplex overlap "
                           f"{result.get('contacts', {}).get('max_penetration_nm', 0):.3f} nm. No changes applied.",
                "relaxation": result,
            })
        if not result["transforms"]:
            return {"relaxation": result, "unchanged": True}
        body = body.model_copy(update={
            "transforms": [FlexibleRelaxTransform(**t) for t in result["transforms"]],
            "label": body.label or ("Relax all flexible segments" if body.scope == "all"
                                   else "Relax flexible network"),
        })
    if not body.transforms:
        raise HTTPException(400, detail="No cluster transforms provided.")
    known = {c.id for c in design0.cluster_transforms}
    for t in body.transforms:
        if t.cluster_id not in known:
            raise HTTPException(404, detail=f"Cluster {t.cluster_id!r} not found.")

    def fn(d: Design) -> Design:
        from backend.api.part_flexible_commands import apply_poses
        updated = apply_poses(d, [t.model_dump() for t in body.transforms], carry=result is not None)
        if result is not None:
            from backend.core.flexible_relax import _geom_index, _anchor_world_pos
            import numpy as np
            geom = _geom_index(updated)
            original = _geom_index(d)
            fixed = set(result["fixed_cluster_ids"])
            selected = {c["connection_id"]: c for c in result["connections"]}
            for c in updated.flexible_connections:
                if c.id not in selected:
                    continue
                a = _anchor_world_pos(geom, updated, c.anchor_a)
                b = _anchor_world_pos(geom, updated, c.anchor_b)
                if a is None or b is None:
                    raise HTTPException(422, detail="Relaxed anchor could not be resolved. No changes applied.")
                for cid, anchor, point in ((c.cluster_a_id, c.anchor_a, a),
                                           (c.cluster_b_id, c.anchor_b, b)):
                    if cid in fixed and not np.allclose(
                        point, _anchor_world_pos(original, d, anchor), atol=1e-8, rtol=0
                    ):
                        raise HTTPException(422, detail="Overlapping cluster transforms would move the "
                                            "fixed reference. No changes applied.")
                length = float(np.linalg.norm(a - b))
                if length > c.contour_length_nm + result["tolerance_nm"]:
                    raise HTTPException(422, detail="Cluster pose composition does not satisfy all flexible "
                                        "tethers. No changes applied.")
                selected[c.id].update(length_nm=length, excess_nm=max(0., length - c.contour_length_nm))
            # Persist/report the actual NADOC geometry measurements, rather than
            # optimizer predictions (native coordinates may have lower precision).
            result["max_excess_nm"] = max((c["excess_nm"] for c in selected.values()), default=0.)
            params["relaxation"]["max_excess_nm"] = result["max_excess_nm"]
            if result.get('solver') in {'rigid-flex-staged-contact-v1', 'rigid-flex-staged-contact-v2'}:
                from backend.core.flexible_contacts import Contacts, design_capsules
                ids = set(result['cluster_sizes'])
                capsules = design_capsules(updated, ids)
                clearance = Contacts(capsules, [], {}).report(np.zeros(0))
                if clearance['max_penetration_nm'] > result['tolerance_nm']:
                    raise HTTPException(422, detail='Relaxed duplexes still overlap. No changes applied.')
                old_fixed = {c['id']: c for c in design_capsules(d, fixed)}
                new_fixed = {c['id']: c for c in capsules if c['owner'] in fixed}
                if old_fixed.keys() != new_fixed.keys() or any(
                    not np.allclose(old_fixed[k][p], new_fixed[k][p], atol=1e-8, rtol=0)
                    for k in old_fixed for p in ('p', 'q')
                ):
                    raise HTTPException(422, detail='Fixed cluster collision geometry moved. No changes applied.')
                result['contacts'] = clearance
                params['relaxation']['contacts'] = clearance
        return updated

    n = len(body.transforms)
    label = body.label or (
        "Relax flexible segment" if n == 1 else "Relax flexible segments"
    )
    params = {"cluster_ids": [t.cluster_id for t in body.transforms],
              "transforms": [t.model_dump() for t in body.transforms]}
    if result is not None:
        params.update(scope=body.scope, conn_id=body.conn_id,
                      relaxation={k: v for k, v in result.items() if k != "transforms"})
    from backend.api.part_flexible_commands import values
    try:
        values({"_proof_version": 1, **params})
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    updated, validation, _entry = design_state.mutate_with_feature_log(
        "flexible-relax", label, params, fn,
        expected_revision=source_revision if result is not None else None,
    )
    # Return authoritative geometry for every affected cluster, including exact
    # base selections on a shared helix and the flexible classification flags.
    by_cluster = {c.id: c for c in design0.cluster_transforms}
    changed_helix_ids = sorted({
        hid
        for t in body.transforms
        for hid in (by_cluster[t.cluster_id].helix_ids or [])
    })
    payload = _design_response_with_geometry(
        updated, validation,
        changed_helix_ids=changed_helix_ids, compact_deformed=True, partial_axes=True,
    )
    if result is not None:
        payload["relaxation"] = result
    return payload


@router.post("/design/flexible-segment", status_code=200)
def add_flexible_segment(body: FlexibleSegmentMarkBody, response: Response) -> dict:
    """Mark one unpaired bead flexible and re-derive connections. Feature-log step."""
    from backend.core.flexible_segments import apply_marks

    design = design_state.get_or_404()
    mark = _flex_mark_from_body(design, body)  # validates unpaired

    def fn(d: Design) -> Design:
        candidate = apply_marks(
            d.copy_with(flexible_segment_marks=list(d.flexible_segment_marks) + [mark])
        )
        return _require_connected_marks(candidate, [mark])

    return _flex_log_response(
        response, "flexible-segment-mark", "Mark flexible ssDNA",
        {"marks": [mark.model_dump(mode="json")], "batch": False}, fn,
        _mark_helix_ids(design, [*design.flexible_segment_marks, mark]),
    )


@router.delete("/design/flexible-segment/{mark_id}", status_code=200)
def delete_flexible_segment(mark_id: str, response: Response) -> dict:
    """Remove a flexible-segment mark and re-derive connections. Feature-log step."""
    from backend.core.flexible_segments import apply_marks

    design = design_state.get_or_404()
    if not any(m.id == mark_id for m in design.flexible_segment_marks):
        raise HTTPException(404, detail=f"Flexible-segment mark {mark_id!r} not found.")

    def fn(d: Design) -> Design:
        marks = [m for m in d.flexible_segment_marks if m.id != mark_id]
        return apply_marks(d.copy_with(flexible_segment_marks=marks))

    return _flex_log_response(
        response, "flexible-segment-unmark", "Unmark flexible ssDNA",
        {"mark_ids": [mark_id]}, fn,
        _mark_helix_ids(design, design.flexible_segment_marks),
    )


@router.post("/design/flexible-segment/batch", status_code=200)
def batch_flexible_segment(body: FlexibleSegmentBatchBody, response: Response) -> dict:
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
        candidate = apply_marks(d.copy_with(flexible_segment_marks=merged))
        # Replace is also the UI's unmark operation. Retained historical marks
        # must remain removable even if they predate this admission rule.
        previous = {(m.strand_id, m.domain_index, m.bp_index, m.direction)
                    for m in d.flexible_segment_marks} if body.replace else set()
        added = [m for m in new_marks if
                 (m.strand_id, m.domain_index, m.bp_index, m.direction) not in previous]
        return _require_connected_marks(candidate, added)

    is_clear = body.replace and not new_marks
    op_kind = "flexible-segment-unmark" if is_clear else "flexible-segment-mark"
    label = (
        "Clear flexible ssDNA"
        if is_clear
        else f"Mark flexible ssDNA ({len(new_marks)} base{'' if len(new_marks) == 1 else 's'})"
    )
    changed_helix_ids = _mark_helix_ids(
        design, [*design.flexible_segment_marks, *new_marks]
    )
    return _flex_log_response(
        response, op_kind, label,
        {"marks": [m.model_dump(mode="json") for m in new_marks], "replace": body.replace, "batch": True}, fn,
        changed_helix_ids,
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
