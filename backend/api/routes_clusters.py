"""
API layer — cluster rigid-transform route handlers (extracted from crud.py).

This module hosts the ``/design/cluster`` CRUD endpoints: create a named cluster
of helices/domains, patch its pose (the live gizmo-drag path — silent until a
drag-end ``commit``), record ordinary membership/name/style edits, and delete it. Clusters are the
rigid-body grouping that bend/twist/relax operate on; the transform they carry
(translation/rotation/pivot) is a DISPLAY-layer pose — it never mutates topology.

Factored out of ``crud.py`` following the same template as the camera-poses
(13-B), loop-skip (10-F), animations, extensions, deformation, and
flexible-segments sub-routers.

Routes
------
  POST   /design/cluster               — create a named cluster (pushes undo)
  PATCH  /design/cluster/{cluster_id}  — update pose/membership (silent preview; commit→undo + feature_log)
  DELETE /design/cluster/{cluster_id}  — recorded dissolve (keeps members)
  POST   /design/clusters/dissolve    — atomic recorded batch dissolve
  POST   /design/cluster-paste         — duplicate cluster(s) at a lattice offset (feature-logged)

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state

# _design_response is the shared response helper used by 100+ crud.py routes;
# _ensure_default_cluster is the shared cluster-bootstrap helper (also called by
# crud.py's auto-clustering path). Both stay in crud.py and are imported back
# here (same convention as routes_camera_poses.py / routes_deformation.py).
from backend.api.crud import _design_response
from backend.api.pattern_features import (
    CircularPatternBody,
    LinearPatternBody,
    build_pattern,
    pattern_inputs,
    pattern_label,
)
from backend.core.cluster_copy import paste_clusters
from backend.core.cluster_reconcile import MutationReport

router = APIRouter()


class AddClusterBody(BaseModel):
    name: str = "Cluster"
    helix_ids: List[str]
    domain_ids: List[dict] = Field(default_factory=list)  # [{strand_id, domain_index}]
    log: bool = False  # deprecated compatibility field; every creation is logged


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
    domain_ids: Optional[List[dict]] = None  # [{strand_id, domain_index}]
    translation: Optional[List[float]] = None  # [x, y, z] nm
    rotation: Optional[List[float]] = None  # [x, y, z, w] quaternion
    pivot: Optional[List[float]] = None  # [x, y, z] nm
    color: Optional[str] = None  # "#rrggbb"; "" clears to the auto palette
    opacity: Optional[float] = None  # 0..1, clamped
    commit: bool = False  # pose confirm; non-null authored fields always commit
    log: bool = False  # deprecated compatibility field; every commit is logged


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
    from backend.api.part_group_recording import create_group

    updated, report = create_group(body)
    return _design_response(updated, report, normalize_legacy=False)


@router.post("/design/cluster-unassigned", status_code=200)
def repair_unassigned_clusters() -> dict:
    """Undoable additive repair; existing cluster identities and poses survive."""
    from backend.api.part_group_recording import repair_unassigned_groups

    updated, report = repair_unassigned_groups()
    return _design_response(updated, report, normalize_legacy=False)


@router.patch("/design/cluster/{cluster_id}", status_code=200)
def update_cluster(cluster_id: str, body: PatchClusterBody) -> dict:
    """Record authored edits; pose-only previews retain the legacy drag path."""
    from backend.core.validator import validate_design
    from backend.api.part_group_recording import AUTHORED_FIELDS, update_group

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.helix_ids is not None:
        fields["helix_ids"] = body.helix_ids
    if body.domain_ids is not None:
        fields["domain_ids"] = body.domain_ids
    if body.translation is not None:
        fields["translation"] = body.translation
    if body.rotation is not None:
        fields["rotation"] = body.rotation
    if body.pivot is not None:
        fields["pivot"] = body.pivot
    # Display-only fields. "" clears the color back to the auto palette (see the
    # PatchClusterBody docstring); anything else must be a #rrggbb hex.
    if body.color is not None:
        c = body.color.strip()
        if c and not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise HTTPException(
                400, detail=f"color must be #rrggbb, got {body.color!r}"
            )
        fields["color"] = c or None
    if body.opacity is not None:
        if not math.isfinite(body.opacity):
            raise HTTPException(422, detail={"code": "invalid_group_opacity"})
        fields["opacity"] = max(0.0, min(1.0, float(body.opacity)))

    # Joints are stored in the cluster's LOCAL frame, so a cluster transform
    # change leaves their authored axes invariant.
    if body.commit or AUTHORED_FIELDS.intersection(fields):
        updated, report = update_group(cluster_id, fields)
        membership = {"helix_ids", "domain_ids"}.intersection(fields)
        mixed_pose = AUTHORED_FIELDS.intersection(fields) and {"translation", "rotation", "pivot"}.intersection(fields)
        if membership or mixed_pose:
            from backend.api.crud import _design_response_with_geometry

            # Use this exact accepted candidate and request revision outside the
            # publication lock. A separate unrevisioned GET could race another
            # membership edit and paint stale geometry over its newer design.
            return _design_response_with_geometry(updated, report, normalize_legacy=False)
        return _design_response(updated, report, normalize_legacy=False)

    # Pose-only live preview compatibility. Private drag ownership/cancel/undo
    # is a separate lifecycle change (FH-23); do not add history proof or the
    # bounded structural/reference scan to this frame-rate path.
    design = design_state.get_or_404()
    cts = list(design.cluster_transforms)
    idx = next((i for i, c in enumerate(cts) if c.id == cluster_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")
    cts[idx] = cts[idx].model_copy(update=fields)
    updated = design.copy_with(cluster_transforms=cts)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/cluster/{cluster_id}", status_code=200)
def delete_cluster(cluster_id: str) -> dict:
    """Dissolve one group when its members retain their native placement."""
    return _dissolve_response([cluster_id])


class DissolveClustersBody(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    cluster_ids: List[str] = Field(min_length=1, max_length=128)


@router.post("/design/clusters/dissolve", status_code=200)
def dissolve_clusters(body: DissolveClustersBody) -> dict:
    """Import omission and ordinary batch removal are all-or-none."""
    return _dissolve_response(body.cluster_ids)


def _dissolve_response(cluster_ids):
    from backend.api.crud import _design_response_with_geometry
    from backend.api.part_group_recording import dissolve_groups

    updated, report = dissolve_groups(cluster_ids)
    return _design_response_with_geometry(updated, report, normalize_legacy=False,
        preserve_feature_log_id=updated.feature_log[-1].id)


# ── Overhang-duplex cluster rotation point ([[overhang-duplex-cluster]] P2) ────
class RotationPointBody(BaseModel):
    kind: str  # 'overhang_root' | 'centroid'
    overhang_id: Optional[str] = None


@router.get("/design/cluster/{cluster_id}/rotation-points", status_code=200)
def get_cluster_rotation_points(cluster_id: str) -> dict:
    """Candidate gizmo rotation points for a DUPLEX cluster: each participating overhang's
    root bead + the duplex centroid. 404 if the cluster isn't a duplex cluster."""
    from backend.core.duplex_cluster import duplex_cluster_rotation_points

    design = design_state.get_or_404()
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None or cl.overhang_duplex_driver_id is None:
        raise HTTPException(
            404, detail=f"Cluster {cluster_id!r} is not an overhang-duplex cluster."
        )
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
        raise HTTPException(
            404, detail=f"Cluster {cluster_id!r} is not an overhang-duplex cluster."
        )
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
    """Record a native pivot rebase without moving the duplex geometry."""
    from backend.api.part_group_rotation_point import record_rotation_point

    updated, report = record_rotation_point(cluster_id, body)
    return _design_response(updated, report, normalize_legacy=False)


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
    from uuid import uuid4
    params = {**body.model_dump(mode="json"), "history_seed": str(uuid4())}
    holder: dict = {}

    def _fn(design):
        try:
            grafted, pasted_helix_ids, report = paste_clusters(
                design, body.cluster_ids, (body.delta_row, body.delta_col), identity_seed=params["history_seed"]
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
        params=params,
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


def _create_pattern(kind, body):
    from backend.api.crud import _design_response_with_geometry
    holder = {}
    from uuid import uuid4
    params = pattern_inputs(body)
    if design_state.get_or_404().group_organization is not None:
        from backend.api.part_pattern_recording import create
        updated, report, _, copies = create(kind, params,
            expected_design_id=body.expected_design_id, expected_revision=body.expected_revision)
        response = _design_response_with_geometry(updated, report, embed_straight=True,
                                                 normalize_legacy=False)
        response["pattern_report"] = copies
        return response
    params["history_seed"] = str(uuid4())

    def build(design):
        try:
            candidate, ids, copy_report = build_pattern(kind, design, params, id_seed=params["history_seed"])
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        holder["report"] = copy_report
        return candidate, MutationReport(new_helix_origins={hid: None for hid in ids})

    updated, report, _ = design_state.mutate_with_feature_log(
        op_kind=kind,
        label=pattern_label(kind, params),
        params=params,
        fn=build,
        expected_revision=body.expected_revision,
    )
    response = _design_response_with_geometry(updated, report, embed_straight=True)
    copies = holder["report"]
    response["pattern_report"] = (
        [vars(r) for r in copies] if isinstance(copies, list) else vars(copies)
    )
    return response


@router.post("/design/circular-pattern", status_code=200)
def circular_pattern(body: CircularPatternBody) -> dict:
    return _create_pattern("circular-pattern", body)


@router.post("/design/linear-pattern", status_code=200)
def linear_pattern(body: LinearPatternBody) -> dict:
    return _create_pattern("linear-pattern", body)
