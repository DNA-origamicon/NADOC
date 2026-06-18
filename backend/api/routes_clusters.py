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

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
# _design_response is the shared response helper used by 100+ crud.py routes;
# _ensure_default_cluster is the shared cluster-bootstrap helper (also called by
# crud.py's auto-clustering path). Both stay in crud.py and are imported back
# here (same convention as routes_camera_poses.py / routes_deformation.py).
from backend.api.crud import _design_response, _ensure_default_cluster
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry

router = APIRouter()


class AddClusterBody(BaseModel):
    name: str = "Cluster"
    helix_ids: List[str]
    domain_ids: List[dict] = Field(default_factory=list)  # [{strand_id, domain_index}]
    log: bool = False                                       # when True: append a cluster_create feature_log entry


class PatchClusterBody(BaseModel):
    name: Optional[str] = None
    helix_ids: Optional[List[str]] = None
    domain_ids: Optional[List[dict]] = None     # [{strand_id, domain_index}]
    translation: Optional[List[float]] = None   # [x, y, z] nm
    rotation: Optional[List[float]] = None      # [x, y, z, w] quaternion
    pivot: Optional[List[float]] = None         # [x, y, z] nm
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
