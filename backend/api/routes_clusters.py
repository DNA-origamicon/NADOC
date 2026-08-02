"""
API layer — cluster rigid-transform route handlers (extracted from crud.py).

This module hosts the ``/design/cluster`` CRUD endpoints: create a named cluster
of helices/domains, patch its pose (the live gizmo-drag path — silent until a
drag-end ``commit``, optionally feature-logged), and delete it. Clusters are the
rigid-body grouping that bend/twist/relax operate on; the transform they carry
(translation/rotation/pivot) is a DISPLAY-layer pose — it never mutates topology.

Factored out of ``crud.py`` following the same template as the camera-poses
(13-B), loop-skip (10-F), animations, extensions, deformation, and
flexible-segments sub-routers.

Routes
------
  POST   /design/cluster               — create a named cluster (pushes undo)
  PATCH  /design/cluster/{cluster_id}  — update pose/membership (silent; commit→undo; +log→feature_log)
  DELETE /design/cluster/{cluster_id}  — remove a cluster (pushes undo)
  POST   /design/cluster-paste         — duplicate cluster(s) at a lattice offset (feature-logged)

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
# _design_response is the shared response helper used by 100+ crud.py routes;
# _ensure_default_cluster is the shared cluster-bootstrap helper (also called by
# crud.py's auto-clustering path). Both stay in crud.py and are imported back
# here (same convention as routes_camera_poses.py / routes_deformation.py).
from backend.api.crud import _design_response, _ensure_default_cluster
from backend.core.cluster_copy import paste_clusters
from backend.core.cluster_reconcile import MutationReport
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry

router = APIRouter()


class AddClusterBody(BaseModel):
    name: str = "Cluster"
    helix_ids: List[str]
    domain_ids: List[dict] = Field(default_factory=list)  # [{strand_id, domain_index}]
    log: bool = False                                       # when True: append a cluster_create feature_log entry


class PatchClusterBody(BaseModel):
    """PATCH body. Every field is a whitelist entry — a key that is not declared
    here is silently dropped, so a new cluster property must be added in BOTH this
    model and ``update_cluster``'s field-copy block.

    ``color`` uses a sentinel: ``None`` means "not supplied" (PATCH semantics), so
    the empty string ``""`` is what CLEARS the color back to the auto palette. That
    is what the sidebar's Reset button sends.
    """
    name: Optional[str] = None
    helix_ids: Optional[List[str]] = None
    domain_ids: Optional[List[dict]] = None     # [{strand_id, domain_index}]
    translation: Optional[List[float]] = None   # [x, y, z] nm
    rotation: Optional[List[float]] = None      # [x, y, z, w] quaternion
    pivot: Optional[List[float]] = None         # [x, y, z] nm
    color: Optional[str] = None                 # "#rrggbb"; "" clears to the auto palette
    opacity: Optional[float] = None             # 0..1, clamped
    commit: bool = False                         # when True: push to undo stack
    log: bool = False                            # when True (with commit): append to feature_log


@router.post("/design/cluster", status_code=200)
def add_cluster(body: AddClusterBody) -> dict:
    """Create a named cluster of helices. Pushes to the undo stack.

    Only the auto-created default catch-all cluster (is_default=True) surrenders
    helices to the new cluster.  All intentional clusters — user-created or
    imported (is_default=False, e.g. scaffold clusters from a multi-scaffold
    import) — are left completely untouched so they cannot be overridden.

    If no clusters exist at all, auto-creates the default cluster first so the
    remainder always has a home.
    """
    from backend.core.models import ClusterRigidTransform, DomainRef
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    # Ensure a default cluster exists before splitting so the remainder lands somewhere.
    # This is a no-op when intentional clusters (e.g. scaffold clusters) already exist.
    design = _ensure_default_cluster(design)

    new_helix_set = set(body.helix_ids)

    # Strip the new cluster's helices ONLY from the default catch-all cluster.
    # Non-default clusters (scaffold-imported, user-created) are preserved intact.
    surviving = []
    for c in design.cluster_transforms:
        if c.is_default:
            remaining = [h for h in c.helix_ids if h not in new_helix_set]
            if remaining:
                surviving.append(c.model_copy(update={"helix_ids": remaining}))
            # Default cluster with no remaining helices is silently dropped.
        else:
            surviving.append(c)

    domain_ids = [DomainRef(**d) for d in (body.domain_ids or [])]
    ct = ClusterRigidTransform(name=body.name, helix_ids=body.helix_ids, domain_ids=domain_ids)

    if body.log:
        # Record the cluster-creation step in the feature log so a design's
        # construction history can replay "group these helices into a bar"
        # (mirrors the commit+log cursor discipline update_cluster uses).
        log = list(design.feature_log)
        if design.feature_log_cursor >= 0:
            log = log[:design.feature_log_cursor + 1]
        log_entry = ClusterCreateLogEntry(
            cluster_id=ct.id,
            name=ct.name,
            helix_ids=list(ct.helix_ids),
            domain_ids=list(ct.domain_ids),
        )
        updated = design.copy_with(
            cluster_transforms=surviving + [ct],
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )
    else:
        updated = design.copy_with(cluster_transforms=surviving + [ct])
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/cluster/{cluster_id}", status_code=200)
def update_cluster(cluster_id: str, body: PatchClusterBody) -> dict:
    """Update cluster properties (silent — no undo push, used for live gizmo drag)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    cts = list(design.cluster_transforms)
    idx = next((i for i, c in enumerate(cts) if c.id == cluster_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    from backend.core.models import DomainRef
    fields: dict = {}
    if body.name        is not None: fields["name"]        = body.name
    if body.helix_ids   is not None: fields["helix_ids"]   = body.helix_ids
    if body.domain_ids  is not None: fields["domain_ids"]  = [DomainRef(**d) for d in body.domain_ids]
    if body.translation is not None: fields["translation"] = body.translation
    if body.rotation    is not None: fields["rotation"]    = body.rotation
    if body.pivot       is not None: fields["pivot"]       = body.pivot
    # Display-only fields. "" clears the color back to the auto palette (see the
    # PatchClusterBody docstring); anything else must be a #rrggbb hex.
    if body.color is not None:
        c = body.color.strip()
        if c and not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise HTTPException(400, detail=f"color must be #rrggbb, got {body.color!r}")
        fields["color"] = c or None
    if body.opacity is not None:
        fields["opacity"] = max(0.0, min(1.0, float(body.opacity)))

    cts[idx] = cts[idx].model_copy(update=fields)
    updated_ct = cts[idx]

    # Joints are stored in the cluster's LOCAL frame, so a cluster transform
    # change leaves cluster_joints invariant — world-space axes are derived
    # lazily from cluster_transforms[id] at read time. The legacy world-space
    # update math (J_new = R_delta @ (J - D_old) + D_new) accumulated
    # floating-point drift across many commits and is no longer needed.
    updated_joints = list(design.cluster_joints)

    if body.commit and body.log:
        # Final tool confirm — push to undo stack and record in feature_log.
        # Truncate suppressed future entries if cursor is not at end.
        log = list(design.feature_log)
        if design.feature_log_cursor >= 0:
            log = log[:design.feature_log_cursor + 1]
        log_entry = ClusterOpLogEntry(
            cluster_id=cluster_id,
            translation=list(updated_ct.translation),
            rotation=list(updated_ct.rotation),
            pivot=list(updated_ct.pivot),
        )
        updated = design.copy_with(
            cluster_transforms=cts,
            cluster_joints=updated_joints,
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )
        design_state.set_design(updated)
    elif body.commit:
        # Drag-end commit — push to undo stack only (no feature_log entry).
        updated = design.copy_with(cluster_transforms=cts, cluster_joints=updated_joints)
        design_state.set_design(updated)
    else:
        updated = design.copy_with(cluster_transforms=cts)
        design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/cluster/{cluster_id}", status_code=200)
def delete_cluster(cluster_id: str) -> dict:
    """Remove a cluster. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    cts = [c for c in design.cluster_transforms if c.id != cluster_id]
    if len(cts) == len(design.cluster_transforms):
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    updated = design.model_copy(update={"cluster_transforms": cts}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Overhang-duplex cluster rotation point ([[overhang-duplex-cluster]] P2) ────
class RotationPointBody(BaseModel):
    kind: str                       # 'overhang_root' | 'centroid'
    overhang_id: Optional[str] = None


@router.get("/design/cluster/{cluster_id}/rotation-points", status_code=200)
def get_cluster_rotation_points(cluster_id: str) -> dict:
    """Candidate gizmo rotation points for a DUPLEX cluster: each participating overhang's
    root bead + the duplex centroid. 404 if the cluster isn't a duplex cluster."""
    from backend.core.duplex_cluster import duplex_cluster_rotation_points

    design = design_state.get_or_404()
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None or cl.overhang_duplex_driver_id is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} is not an overhang-duplex cluster.")
    return {"rotation_points": duplex_cluster_rotation_points(design, cl)}


@router.get("/design/cluster/{cluster_id}/duplex-tethers", status_code=200)
def get_cluster_duplex_tethers(cluster_id: str) -> dict:
    """Free-until-taut drag tethers for a DUPLEX cluster ([[overhang-duplex-cluster]] P3):
    each applied connection's backbone bond as {moving, fixed, contour_nm}. 404 unless it's
    a duplex cluster. Read-only — the client feeds these to the gizmo's taut projector."""
    from backend.core.duplex_cluster import duplex_cluster_tethers

    design = design_state.get_or_404()
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None or cl.overhang_duplex_driver_id is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} is not an overhang-duplex cluster.")
    return {"tethers": duplex_cluster_tethers(design, cl)}


@router.get("/design/cluster/{cluster_id}/connection-tethers", status_code=200)
def get_cluster_connection_tethers(cluster_id: str) -> dict:
    """Free-until-taut drag tethers from a REGULAR cluster's applied overhang CONNECTIONS
    (directly-connected duplex + ss/ds linker bridge) to the partner cluster, as
    {moving, fixed, contour_nm}. Fed (merged with ssDNA flexible tethers) to the gizmo's
    taut projector for the "Constrained (tethers)" drag. Read-only; empty list if none."""
    from backend.core.connection_tethers import cluster_connection_tethers

    design = design_state.get_or_404()
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")
    return {"tethers": cluster_connection_tethers(design, cl)}


@router.get("/design/cluster/{cluster_id}/movable-links", status_code=200)
def get_cluster_movable_links(cluster_id: str) -> dict:
    """Movable intermediate links (overhang-duplex bodies) for dragging this regular cluster: the
    link swings live to follow the drag while the partner part stays fixed. Each link carries its
    backbone bonds to BOTH parts. Read-only; empty if the cluster has no movable-link connections."""
    from backend.core.connection_tethers import cluster_movable_links

    design = design_state.get_or_404()
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")
    return {"links": cluster_movable_links(design, cl)}


@router.post("/design/cluster/{cluster_id}/rotation-point", status_code=200)
def set_cluster_rotation_point(cluster_id: str, body: RotationPointBody) -> dict:
    """Set a DUPLEX cluster's rotation pivot to one of its candidate points (an overhang's
    root bead or the centroid), rebasing the translation so the geometry doesn't jump.
    Pushes to the undo stack."""
    from backend.core.duplex_cluster import (
        duplex_cluster_rotation_points, set_duplex_cluster_pivot,
    )
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None or cl.overhang_duplex_driver_id is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} is not an overhang-duplex cluster.")
    pts = duplex_cluster_rotation_points(design, cl)
    match = next((p for p in pts if p["kind"] == body.kind
                  and (body.kind != "overhang_root" or p["overhang_id"] == body.overhang_id)), None)
    if match is None:
        raise HTTPException(422, detail=f"No rotation point {body.kind!r}"
                            + (f" for overhang {body.overhang_id!r}" if body.overhang_id else "") + ".")
    updated = set_duplex_cluster_pivot(design, cluster_id, match["point"])
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class ClusterPasteBody(BaseModel):
    """A cluster copy/paste: duplicate `cluster_ids` at a lattice offset.

    The offset is (row, col) only — bp indices are copied verbatim (Δbp = 0).
    ``(delta_row + delta_col)`` must be EVEN; an odd shift flips every helix's
    FORWARD/REVERSE polarity and moves every crossover off its allowed bp phase.
    The core layer enforces this and 400s.
    """
    cluster_ids: List[str]
    delta_row: int
    delta_col: int


@router.post("/design/cluster-paste", status_code=200)
def cluster_paste(body: ClusterPasteBody) -> dict:
    """Paste a copy of the selected cluster(s) at a lattice offset.

    Emits a ``cluster-paste`` feature-log entry, which is what gives the user
    rollback / revert / delete and feature-slider seek for free.
    """
    holder: dict = {}

    def _fn(design):
        try:
            grafted, pasted_helix_ids, report = paste_clusters(
                design, body.cluster_ids, (body.delta_row, body.delta_col)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        holder["report"] = report
        # Explicit orphans: without this hint reconcile_cluster_membership sweeps
        # the pasted helices into whichever existing cluster is lattice-adjacent
        # (Manhattan <= 2) — usually the SOURCE cluster they were copied from.
        return grafted, MutationReport(
            new_helix_origins={hid: None for hid in pasted_helix_ids}
        )

    n = len(body.cluster_ids)
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="cluster-paste",
        label=f"Paste {n} cluster{'s' if n != 1 else ''} "
              f"(Δrow {body.delta_row:+d}, Δcol {body.delta_col:+d})",
        params=body.model_dump(mode="json"),
        fn=_fn,
    )

    resp = _design_response(updated, report)
    copy_report = holder["report"]
    resp["paste_report"] = {
        "requested_cluster_ids": copy_report.requested_cluster_ids,
        "closure_cluster_ids": copy_report.closure_cluster_ids,
        "auto_added_cluster_ids": copy_report.auto_added_cluster_ids,
        "copied_helix_ids": copy_report.copied_helix_ids,
        "truncated_strand_count": copy_report.truncated_strand_count,
        "dropped_boundary_crossovers": copy_report.dropped_boundary_crossovers,
        "dropped_boundary_fls": copy_report.dropped_boundary_fls,
    }
    return resp
