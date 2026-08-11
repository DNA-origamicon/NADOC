"""
API layer — Assembly CRUD router.

All routes are prefixed with /api (set in main.py).  The assembly endpoints
live under /assembly and are completely independent of the design endpoints —
mutations here never touch design_state and vice-versa.

Route summary
─────────────
GET   /assembly                         return active assembly (create if none)
POST  /assembly                         create new empty assembly
POST  /assembly/load                    load .nadoc-assembly from server-side path
POST  /assembly/import                  load from raw JSON string (browser upload)
GET   /assembly/export                  download as .nadoc-assembly file

POST  /assembly/instances               add a PartInstance
PATCH /assembly/instances/{id}          update instance fields
DELETE /assembly/instances/{id}         remove instance

POST  /assembly/joints                  add an AssemblyJoint
PATCH /assembly/joints/{id}             update joint (drives current_value → recomputes transform)
DELETE /assembly/joints/{id}            remove joint

POST  /assembly/instances/{id}/connectors           add a connector (InterfacePoint) to instance
DELETE /assembly/instances/{id}/connectors/{label}  remove a named connector

POST  /assembly/linker-helices          add a linker Helix to assembly_helices
DELETE /assembly/linker-helices/{id}    remove linker helix
POST  /assembly/linker-strands          add a linker Strand (prefix id __vsc__ for virtual scaffold)
DELETE /assembly/linker-strands/{id}    remove linker strand
GET   /assembly/linker-geometry         nucleotide geometry for all assembly_helices + assembly_strands

POST  /assembly/undo                    undo last assembly-level op
POST  /assembly/redo                    redo last undone op

GET   /assembly/instances/{id}/design   resolve and return instance's Design JSON
GET   /assembly/instances/{id}/geometry geometry for instance's design (local frame)

GET   /debug/assembly                   full assembly dump + counts
GET   /debug/assembly-undo-depth        undo/redo stack depths
GET   /debug/assembly-joint-transform/{joint_id}  preview joint transform at angle
"""

from __future__ import annotations

import math
import os
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.api import assembly_state
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    ClusterRigidTransform,
    ConnectionType,
    DesignMetadata,
    Direction,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartSourceFile,
    Vec3,
)
from backend.core import assembly_groups as _ag
from backend.core import workspace as _ws

router = APIRouter()

# ── Project root (two levels above this file: backend/api/ → backend/ → root) ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_DIR = Path(
    os.environ.get("NADOC_WORKSPACE", str(_PROJECT_ROOT / "workspace"))
)


# ── Geometry cache ─────────────────────────────────────────────────────────────
# The LRU + cache-key compute live in backend/core/assembly_geometry.py (router
# carve-up Refactor #49 — pure, unit-tested, no api deps). These thin shims keep
# the original private names (imported back by routes_assembly_geometry / _frames)
# and pass the api-layer's monkeypatch-able _WORKSPACE_DIR into the pure key fn.
from backend.core import assembly_geometry as _ageo  # noqa: E402

_geo_cache_get = _ageo.geo_cache_get
_geo_cache_set = _ageo.geo_cache_set


def _geo_cache_key(inst: "PartInstance") -> str | None:
    """Stable per-instance geometry cache key (None if not cacheable).

    Delegates to the pure ``assembly_geometry.geo_cache_key``, threading in the
    live ``_WORKSPACE_DIR`` at call time so tests that monkeypatch it still win.
    """
    return _ageo.geo_cache_key(inst, _WORKSPACE_DIR)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _assembly_response(assembly: Assembly) -> dict:
    """Standard response shape for assembly mutations.

    Phase 5 contract step (path-to-thousands wire-format compaction):

    * v2 fields are the only per-instance payload at the top of the
      ``assembly`` dict:
        - ``format_version: 2``
        - ``sources``: ``{src_key: PartSource dict}`` — deduplicated by
          ``_geo_cache_key`` when available so the response matches the
          dedup key used by ``/assembly/geometry``.  Falls back to
          ``Assembly._instance_src_key`` for inline/uncacheable sources.
        - ``instances_v2``: sparse-override compact dicts.  Each carries
          ``id``, ``src_key``, ``t12`` (12 floats — top 3 rows of the
          transform), plus only the fields whose value differs from its
          model default.
    * The legacy v1 ``instances`` list (full per-PartInstance Pydantic
      dumps) is **omitted** — frontend readers (commit ce34c8b) consume
      ``instances_v2`` + ``sources`` and expand client-side.  See
      ``project_path_to_thousands.md`` Phase 5 contract step.
    """
    full = assembly.to_dict()
    # Drop the per-instance v1 payload — v2 fields below carry the same
    # information in the compact form.  Other v1 fields on the Assembly
    # (joints, assembly_helices, camera_poses, …) survive unchanged.
    full.pop("instances", None)
    sources: dict[str, dict] = {}
    instances_v2: list[dict] = []
    for inst in assembly.instances:
        key = _geo_cache_key(inst) or Assembly._instance_src_key(inst)
        if key not in sources:
            sources[key] = inst.source.model_dump(mode="json")
        instances_v2.append(inst.to_compact_dict(src_key=key))
    full["format_version"] = 2
    full["sources"] = sources
    full["instances_v2"] = instances_v2
    return {"assembly": full}


def _find_instance(assembly: Assembly, instance_id: str) -> PartInstance:
    for inst in assembly.instances:
        if inst.id == instance_id:
            return inst
    raise HTTPException(404, detail=f"Instance {instance_id!r} not found.")


def _find_joint(assembly: Assembly, joint_id: str) -> AssemblyJoint:
    for j in assembly.joints:
        if j.id == joint_id:
            return j
    raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")


def _load_design_from_source(source, assembly_path: str | None = None):
    """Resolve a PartSource to a Design object."""
    from backend.core.models import Design

    if source.type == "inline":
        return source.design
    # File source: resolve relative path against workspace, assembly parent, then project root
    p = Path(source.path)
    if not p.is_absolute():
        bases = [
            _WORKSPACE_DIR,
            Path(assembly_path).parent if assembly_path else None,
            _PROJECT_ROOT,
        ]
        for base in filter(None, bases):
            candidate = (base / p).resolve()
            if candidate.is_file():
                p = candidate
                break
        else:
            raise HTTPException(400, detail=f"Part file not found: {source.path!r}")
    elif not p.is_file():
        raise HTTPException(400, detail=f"Part file not found: {source.path!r}")
    try:
        return Design.from_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            400, detail=f"Failed to load part file {source.path!r}: {exc}"
        ) from exc


def _design_with_instance_overrides(
    inst: PartInstance, assembly_path: str | None = None
):
    """Resolve an instance design plus assembly-scoped cluster transform overrides.

    File load stays here (L4-blocked on HTTPException); the pure override merge
    is ``assembly_geometry.merge_cluster_overrides`` (Refactor #49).
    """
    design = _load_design_from_source(inst.source, assembly_path)
    return _ageo.merge_cluster_overrides(design, inst.cluster_transform_overrides)


def _display_design(design):
    """Drop reference strands for assembly DISPLAY geometry.

    Reference strands (``is_reference=True``) are a single-design-editor
    backdrop construct; the assembly view excludes them entirely (reference
    geometry was out of scope for v1, see [[reference-geometry]]). Mirrors
    ``crud._design_for_export`` — strands only, never helices, so no helix
    references dangle. Returns the design unchanged when it has no reference
    strands (zero allocation for the common case). DISPLAY ONLY: never feed
    the result back into persisted assembly state — that would delete topology.
    """
    if any(s.is_reference for s in design.strands):
        return design.model_copy(update={"strands": design.active_strands()})
    return design


def _assembly_source_path(assembly: Assembly) -> str | None:
    return getattr(assembly.metadata, "source_path", None)


def _safe_workspace_path(rel_path: str) -> Path:
    """Resolve rel_path within _WORKSPACE_DIR, rejecting path traversal attempts.

    Thin api wrapper over `backend.core.workspace.safe_workspace_path`,
    translating its ValueError into a 400 HTTPException.
    """
    try:
        return _ws.safe_workspace_path(rel_path, _WORKSPACE_DIR)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


def _dedup_filename(stem: str, suffix: str) -> str:
    """Return a filename that does not already exist in _WORKSPACE_DIR."""
    return _ws.dedup_filename(stem, suffix, _WORKSPACE_DIR)


def _apply_prismatic_joint(
    base_mat: np.ndarray,
    axis_direction: list[float],
    distance: float,
) -> np.ndarray:
    """Return a new 4×4 row-major transform for instance_b after a prismatic displacement."""
    axis = np.array(axis_direction, dtype=float)
    n = np.linalg.norm(axis)
    if n < 1e-9:
        return base_mat
    axis /= n
    result = base_mat.copy()
    result[:3, 3] = base_mat[:3, 3] + axis * distance
    return result


def _mat4_to_model(m: np.ndarray) -> Mat4x4:
    """Convert a 4×4 numpy array (row-major) to Mat4x4."""
    return Mat4x4(values=m.flatten().tolist())


def _mat4_from_model(m: Mat4x4) -> np.ndarray:
    """Convert a Mat4x4 (row-major values list) to a 4×4 numpy array."""
    return np.array(m.values, dtype=float).reshape(4, 4)


# ── Forward kinematics helpers ────────────────────────────────────────────────
# The pure FK graph-propagation kernel (apply an SE3 ``delta`` through the joint
# graph, mutating PartInstance transforms in place) lives in
# ``backend/core/assembly_fk.py`` — no api dependency, directly unit-tested
# (tests/test_assembly_fk_core.py). Imported back here under their original
# names so the ~50 call sites below are unchanged.
from backend.core.assembly_fk import (  # noqa: E402
    _fk_apply_to_joint,
    _build_inst_by_id,
    _fk_expand_rigid_group,
    _fk_propagate,
    _move_instance_with_fk_delta,
)


# The connector-frame resolution kernel (connector label -> local/world SE3
# frame, or bare position) lives in backend/core/assembly_connectors.py — pure,
# api-free, directly unit-tested (tests/test_assembly_connectors_core.py).
# Imported back under their original names so the ~40 call sites below are
# unchanged. _enforce_connector_coincidence (the write-side twin — re-docks a
# constrained child whose mated connector drifted) lives there too (B=0 graph
# mutation). The cluster-inference helpers that need the api layer
# (_design_with_instance_overrides, _propagate_cluster_delta_to_mates) stay
# below and call these resolvers.
from backend.core.assembly_connectors import (  # noqa: E402
    _build_connector_frames,
    _refresh_connector_frames_for_instance,
    _enforce_connector_coincidence,
)


# The revolute-drive + gear/belt coupling kinematics kernel lives in
# backend/core/assembly_kinematics.py — pure transform math over the core
# models (no api dependency), directly unit-tested
# (tests/test_assembly_kinematics_core.py). Imported back under their original
# names so the route handlers below are unchanged. The kernel-internal helpers
# (_derive_revolute_angle, _axis_angle_rotation_matrix, _belt_to_relation,
# _coupling_relations) became module-private in core and are NOT imported back.
from backend.core.assembly_kinematics import (  # noqa: E402
    _apply_revolute_joint,
    _sync_revolute_values_for_instances,
    _sync_revolute_values_for_parent_moves,
    _propagate_gear_relations_from,
)


def _infer_cluster_ids_for_connector_label(
    inst: PartInstance, label: str | None
) -> list[str]:
    if not label or not label.startswith("blunt:"):
        return []
    parts = label.split(":")
    if len(parts) < 3:
        return []
    helix_id = parts[1]
    try:
        design = _design_with_instance_overrides(inst)
    except Exception:
        return []
    clusters = design.cluster_transforms or []
    joint_cluster_ids = {
        j.cluster_id for j in (design.cluster_joints or []) if j.cluster_id
    }
    matches = [ct for ct in clusters if helix_id in (ct.helix_ids or [])]
    matches.sort(
        key=lambda ct: (
            0 if ct.id in joint_cluster_ids else 1,
            1 if getattr(ct, "is_default", False) else 0,
            len(ct.helix_ids or []),
        )
    )
    return [ct.id for ct in matches]


def _joint_side_cluster_ids(assembly, joint, side: str) -> set[str]:
    ids: set[str] = set()
    if side == "a":
        if joint.cluster_id_a:
            ids.add(joint.cluster_id_a)
        if joint.instance_a_id is None or not joint.connector_a_label:
            return ids
        inst = next(
            (i for i in assembly.instances if i.id == joint.instance_a_id), None
        )
        label = joint.connector_a_label
    else:
        if joint.cluster_id_b:
            ids.add(joint.cluster_id_b)
        inst = next(
            (i for i in assembly.instances if i.id == joint.instance_b_id), None
        )
        label = joint.connector_b_label
    if not inst or not label:
        return ids
    ip = next((p for p in inst.interface_points if p.label == label), None)
    if ip is not None and ip.cluster_id:
        ids.add(ip.cluster_id)
    ids.update(_infer_cluster_ids_for_connector_label(inst, label))
    return ids


def _propagate_cluster_delta_to_mates(
    assembly,
    instance_id: str,
    cluster_id: str,
    delta: np.ndarray,
) -> set[str]:
    """Move all non-fixed parts mated to a locally moved cluster.

    Internal cluster motion does not change the owning instance transform, so FK
    starts from every external part attached to the moved cluster, regardless of
    whether the moved cluster is on side A or B of the mate.
    """
    visited: set[str] = {instance_id}
    inst_by_id = _build_inst_by_id(assembly)
    moved_any = False
    for j in assembly.joints:
        other_id = None
        if j.instance_a_id == instance_id and cluster_id in _joint_side_cluster_ids(
            assembly, j, "a"
        ):
            other_id = j.instance_b_id
        elif j.instance_b_id == instance_id and cluster_id in _joint_side_cluster_ids(
            assembly, j, "b"
        ):
            other_id = j.instance_a_id
        if not other_id:
            continue
        if _move_instance_with_fk_delta(assembly, other_id, delta, visited, inst_by_id):
            moved_any = True
            _fk_apply_to_joint(j, delta)
    if moved_any:
        _enforce_connector_coincidence(assembly, visited, inst_by_id)
    return visited


# ── Request bodies ────────────────────────────────────────────────────────────


class AddInstanceRequest(BaseModel):
    source: dict  # raw dict; validated below
    name: str = "Part"
    transform: Optional[dict] = None  # Mat4x4 dict; defaults to identity


_VALID_REPRESENTATIONS = (
    "full",
    "beads",
    "cylinders",
    "vdw",
    "ballstick",
    "stick",
    "hull-prism",
    "surface",
)


class PatchInstanceRequest(BaseModel):
    name: Optional[str] = None
    transform: Optional[dict] = None
    mode: Optional[str] = None
    visible: Optional[bool] = None
    fixed: Optional[bool] = None
    representation: Optional[str] = None
    allow_part_joints: Optional[bool] = None
    joint_states: Optional[dict] = None
    cluster_transform_overrides: Optional[list[dict]] = None


class PatchInstanceClusterTransformRequest(BaseModel):
    cluster_id: str
    cluster_transform: dict
    joint_id: Optional[str] = None
    joint_value: Optional[float] = None
    delta_transform: Optional[dict] = None


class AssemblyLoadRequest(BaseModel):
    path: str


class CreateAssemblyRequest(BaseModel):
    name: str = "Untitled"


class AssemblyImportRequest(BaseModel):
    content: str  # raw JSON string


class PatchInstanceDesignRequest(BaseModel):
    content: str  # raw Design JSON


class InstanceSeekFeaturesRequest(BaseModel):
    position: int
    sub_position: Optional[int] = None


# ── Core assembly routes ───────────────────────────────────────────────────────


@router.get("/assembly/exists", status_code=200)
def assembly_exists() -> dict:
    """Return whether an active assembly is loaded (without creating one)."""
    return {"exists": assembly_state.get_assembly() is not None}


@router.get("/assembly", status_code=200)
def get_assembly() -> dict:
    """Return the active assembly, creating an empty one if none exists."""
    return _assembly_response(assembly_state.get_or_create())


@router.post("/assembly", status_code=201)
def create_assembly(body: CreateAssemblyRequest = None) -> dict:
    """Create a new empty assembly, replacing any existing one."""
    name = body.name if body else "Untitled"
    a = Assembly(metadata=DesignMetadata(name=name))
    assembly_state.set_assembly(a)
    return _assembly_response(a)


# Above this many full-rep instances, the frontend's per-instance geometry
# pipeline tends to OOM the browser tab (each heavy origami builds ~50+ MB
# of GL state). Loading an assembly that already exceeds this gets silently
# downgraded so the file remains openable — the user can upgrade specific
# parts back to 'full' afterwards.
_AUTO_DOWNGRADE_FULL_REP_THRESHOLD = 6


def _maybe_auto_downgrade_for_memory(
    assembly: Assembly,
) -> tuple[Assembly, Optional[str]]:
    """If too many instances are at 'full' rep, downgrade to 'cylinders'.

    Returns ``(assembly, notice_or_None)``. The notice is meant to surface
    in the API response so the frontend can show a toast.
    """
    full_insts = [i for i in assembly.instances if i.representation == "full"]
    if len(full_insts) <= _AUTO_DOWNGRADE_FULL_REP_THRESHOLD:
        return assembly, None
    downgraded_ids = {i.id for i in full_insts}
    new_instances = [
        i.model_copy(update={"representation": "cylinders"})
        if i.id in downgraded_ids
        else i
        for i in assembly.instances
    ]
    notice = (
        f"Auto-downgraded {len(downgraded_ids)} parts from 'full' to "
        f"'cylinders' to keep the assembly openable (over "
        f"{_AUTO_DOWNGRADE_FULL_REP_THRESHOLD} parts at 'full' would OOM). "
        f"Switch any individual part back to 'full' via its rep picker."
    )
    return assembly.model_copy(update={"instances": new_instances}), notice


def _derive_assembly_duplexes_if_empty(assembly: Assembly) -> Assembly:
    """Populate ``assembly.duplexes`` from legacy ``overhang_bindings`` on load
    when the graph is empty (mirrors the per-design ``_derive_duplexes_if_empty``).
    Guarded: only runs when duplexes are empty AND bindings exist, so files that
    already carry duplexes are untouched. Bindings are KEPT (legacy-migrated, not
    retired here)."""
    if assembly.duplexes or not assembly.overhang_bindings:
        return assembly
    from backend.core.assembly_duplex import sync_assembly_duplexes_from_bindings

    return sync_assembly_duplexes_from_bindings(assembly)


@router.post("/assembly/load", status_code=200)
def load_assembly(body: AssemblyLoadRequest) -> dict:
    """Load a .nadoc-assembly file from the given server-side path."""
    path = os.path.abspath(body.path)
    if not os.path.isfile(path):
        raise HTTPException(400, detail=f"File not found: {path}")
    try:
        text = Path(path).read_text(encoding="utf-8")
        assembly = Assembly.from_json(text)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to load assembly: {exc}") from exc
    assembly, notice = _maybe_auto_downgrade_for_memory(assembly)
    assembly = _derive_assembly_duplexes_if_empty(assembly)
    assembly_state.clear_history()
    assembly_state.set_assembly(assembly)
    resp = _assembly_response(assembly)
    if notice:
        resp["notice"] = notice
    return resp


@router.post("/assembly/import", status_code=200)
def import_assembly(body: AssemblyImportRequest) -> dict:
    """Load an assembly from raw JSON content sent by the browser."""
    try:
        assembly = Assembly.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to parse assembly: {exc}") from exc
    assembly, notice = _maybe_auto_downgrade_for_memory(assembly)
    assembly = _derive_assembly_duplexes_if_empty(assembly)
    assembly_state.clear_history()
    assembly_state.set_assembly(assembly)
    resp = _assembly_response(assembly)
    if notice:
        resp["notice"] = notice
    return resp


@router.get("/assembly/export", status_code=200)
def export_assembly() -> Response:
    """Download the active assembly as a .nadoc-assembly file."""
    assembly = assembly_state.get_or_404()
    name = assembly.metadata.name or "assembly"
    safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in name)
    filename = f"{safe}.nass"
    return Response(
        content=assembly.to_json(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Instance routes ───────────────────────────────────────────────────────────


@router.post("/assembly/instances", status_code=201)
def add_instance(body: AddInstanceRequest) -> dict:
    """Add a PartInstance to the active assembly."""
    from pydantic import TypeAdapter
    from backend.core.models import PartSource

    try:
        source = TypeAdapter(PartSource).validate_python(body.source)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid source: {exc}") from exc

    transform = Mat4x4.model_validate(body.transform) if body.transform else Mat4x4()
    inst = PartInstance(name=body.name, source=source, transform=transform)

    assembly = assembly_state.get_or_create()
    new_instances = list(assembly.instances) + [inst]
    mutated = assembly.model_copy(update={"instances": new_instances})
    src_label = (
        getattr(source, "path", None)
        or getattr(getattr(source, "design", None), "metadata", None)
        and source.design.metadata.name
    ) or body.name
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-add-instance",
        label=f"Add part: {inst.name}",
        params={
            "instance_id": inst.id,
            "name": inst.name,
            "source": body.source,
            "transform": transform.model_dump(mode="json"),
            "source_label": src_label,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


class PropagateFKRequest(BaseModel):
    instance_id: str
    transform: dict  # {values: [16 floats], row-major}


def _propagate_fk_inplace(
    assembly: Assembly,
    instance_id: str,
    transform_values: list[float],
    inst_by_id: dict[str, PartInstance],
) -> None:
    """Move ``instance_id`` to a new world transform and propagate FK to all
    kinematic descendants — mutating ``assembly`` in place.

    The root instance has its base_transform nulled (user directly placed it).
    Descendants have their transforms + base_transforms updated by the same
    delta, so joint values stay visually unchanged.  Joint axes along the path
    are updated, then mated connectors are re-snapped to stay coincident.

    Caller owns snapshot/persist.  Raises HTTP 404/400 for missing / fixed /
    singular cases (validation is idempotent, safe to call after an early check).
    """
    inst = inst_by_id.get(instance_id)
    if not inst:
        raise HTTPException(404, detail=f"Instance {instance_id} not found")
    if inst.fixed:
        raise HTTPException(
            400, detail=f"Instance {instance_id} is fixed and cannot be moved"
        )

    old_T = inst.transform.to_array()
    new_T = np.array(transform_values, dtype=float).reshape(4, 4)
    try:
        delta = new_T @ np.linalg.inv(old_T)
    except np.linalg.LinAlgError:
        raise HTTPException(400, detail="Instance transform is singular")

    # Root: directly moved by user — null base_transform so next joint drive uses new position
    inst.transform = Mat4x4(values=[float(v) for v in new_T.flatten()])
    inst.base_transform = None

    # Expand root's rigid group and propagate FK to all kinematic descendants
    visited = {instance_id}
    _fk_expand_rigid_group(assembly, instance_id, delta, visited, [], inst_by_id)
    _fk_propagate(assembly, visited.copy(), delta, visited, inst_by_id)

    # Re-snap any rigid/revolute joint children that moved without their parent,
    # ensuring mated connectors remain coincident after the move.
    _enforce_connector_coincidence(assembly, visited, inst_by_id)


@router.post("/assembly/propagate_fk", status_code=200)
def propagate_fk(body: PropagateFKRequest) -> dict:
    """Move one instance to a new world transform and propagate FK to all kinematic descendants.

    The root instance has its base_transform nulled (user directly placed it).
    All descendant instances have their transforms and base_transforms updated by
    the same delta, so joint values remain visually unchanged.
    Joint axes along the propagation path are also updated.
    """
    assembly = assembly_state.get_or_404().model_copy(deep=True)
    inst_by_id = _build_inst_by_id(assembly)
    inst = inst_by_id.get(body.instance_id)
    if not inst:
        raise HTTPException(404, detail=f"Instance {body.instance_id} not found")
    if inst.fixed:
        raise HTTPException(
            400, detail=f"Instance {body.instance_id} is fixed and cannot be moved"
        )
    _propagate_fk_inplace(
        assembly, body.instance_id, body.transform["values"], inst_by_id
    )
    updated = _apply_assembly_mutation_with_feature_log(
        assembly,
        op_kind="assembly-transform-instance",
        label=f"Move/rotate part: {inst.name or body.instance_id}",
        params={"instance_id": body.instance_id, "transform": body.transform},
    )
    return _assembly_response(updated)


@router.post("/assembly/resolve", status_code=200)
def resolve_assembly() -> dict:
    """Re-apply all joint constraints in topological order (BFS from fixed/root instances).

    Handles every joint type:
      * revolute / prismatic — re-derives world axis_origin from
        connector_a, then re-applies the driven-DOF formula from
        base_transform.
      * rigid / spherical    — re-snaps instance_b so its connector_b
        world position matches connector_a's (cluster-transform-aware,
        so an internal Relax Bond rotation that moved the connector
        within the part is honoured).

    Returns the updated assembly plus ``solve_status``:
    ``{joint_id: {satisfied, discrepancy}}`` reflecting the state *before*
    re-applying — i.e. which joints were out of sync.
    """
    assembly = assembly_state.get_or_404()
    inst_by_id = _build_inst_by_id(assembly)

    # Per-source design cache so cluster-aware connector lookups don't
    # re-load .nadoc files for every instance.
    _design_cache: dict[str, "Design"] = {}

    def _design_for(inst: "PartInstance") -> "Optional[Design]":
        try:
            key = _geo_cache_key(inst) or inst.id
            d = _design_cache.get(key)
            if d is None:
                d = _design_with_instance_overrides(
                    inst, _assembly_source_path(assembly)
                )
                _design_cache[key] = d
            return d
        except Exception:
            return None

    # Pre-compute connector world frames for every (instance, label) touched
    # by a joint. The inner BFS reads from this dict instead of calling
    # _get_connector_world / _get_connector_world_frame each time, which
    # would otherwise re-run the per-bp deformation pipeline (the actual hot
    # path at N≳500). When the BFS mutates an instance's transform we
    # invalidate that instance's entries via
    # _refresh_connector_frames_for_instance.
    #
    # NB: invalidate-on-write (approach (a) in the Phase 4e plan), not a
    # per-iteration full rebuild. Per-iteration is unsafe if any future code
    # change causes the BFS to re-visit an instance; invalidate-on-write is
    # robust to that.
    frames_by_conn, labels_by_inst, frames_local_cache = _build_connector_frames(
        assembly, inst_by_id, _design_for
    )

    # ── Pre-resolve satisfaction check ───────────────────────────────────────
    solve_status: dict = {}
    for joint in assembly.joints:
        inst_b = inst_by_id.get(joint.instance_b_id) if joint.instance_b_id else None

        # Revolute / prismatic: compare expected vs. actual position derived
        # from base_transform + driven angle/displacement.
        if joint.joint_type in ("revolute", "prismatic"):
            if not inst_b or not inst_b.base_transform:
                solve_status[joint.id] = {"satisfied": None, "discrepancy": None}
                continue
            base_mat = _mat4_from_model(inst_b.base_transform)
            actual_mat = _mat4_from_model(inst_b.transform)
            if joint.joint_type == "revolute":
                expected = _apply_revolute_joint(
                    base_mat,
                    joint.axis_origin,
                    joint.axis_direction,
                    joint.current_value,
                )
            else:
                expected = _apply_prismatic_joint(
                    base_mat, joint.axis_direction, joint.current_value
                )
            disc = float(np.linalg.norm(expected[:3, 3] - actual_mat[:3, 3]))
            solve_status[joint.id] = {"satisfied": disc < 0.01, "discrepancy": disc}
            continue

        # Rigid / spherical: compare connector frames. With
        # mate_relative_transform set, both translation and rotation count
        # toward the discrepancy. Without it, fall back to position-only.
        if joint.joint_type in ("rigid", "spherical"):
            if (
                inst_b is None
                or not joint.instance_a_id
                or not joint.connector_a_label
                or not joint.connector_b_label
            ):
                solve_status[joint.id] = {"satisfied": None, "discrepancy": None}
                continue
            inst_a = (
                inst_by_id.get(joint.instance_a_id) if joint.instance_a_id else None
            )
            if inst_a is None:
                solve_status[joint.id] = {"satisfied": None, "discrepancy": None}
                continue
            disc_pos = None
            disc_rot = None
            if joint.mate_relative_transform is not None:
                F_a = frames_by_conn.get((inst_a.id, joint.connector_a_label))
                F_b = frames_by_conn.get((inst_b.id, joint.connector_b_label))
                if F_a is not None and F_b is not None:
                    try:
                        M = np.array(
                            joint.mate_relative_transform, dtype=float
                        ).reshape(4, 4)
                        F_b_target = F_a @ M
                        snap_T = F_b_target @ np.linalg.inv(F_b)
                        disc_pos = float(np.linalg.norm(snap_T[:3, 3]))
                        cos_a = float(
                            np.clip((np.trace(snap_T[:3, :3]) - 1.0) / 2.0, -1.0, 1.0)
                        )
                        disc_rot = float(np.arccos(cos_a))
                    except np.linalg.LinAlgError:
                        pass
            if disc_pos is None:
                F_a = frames_by_conn.get((inst_a.id, joint.connector_a_label))
                F_b = frames_by_conn.get((inst_b.id, joint.connector_b_label))
                if F_a is None or F_b is None:
                    solve_status[joint.id] = {"satisfied": None, "discrepancy": None}
                    continue
                disc_pos = float(np.linalg.norm(F_a[:3, 3] - F_b[:3, 3]))
            entry: dict = {"discrepancy": disc_pos}
            if disc_rot is not None:
                entry["rotation_discrepancy"] = disc_rot
                entry["satisfied"] = disc_pos < 0.01 and disc_rot < 1e-3
            else:
                entry["satisfied"] = disc_pos < 0.01
            solve_status[joint.id] = entry
            continue

        solve_status[joint.id] = {"satisfied": True, "discrepancy": 0.0}

    # ── BFS re-application from roots ────────────────────────────────────────
    child_ids = {j.instance_b_id for j in assembly.joints if j.instance_b_id}
    root_ids = [i.id for i in assembly.instances if i.id not in child_ids or i.fixed]

    # Include None (world) as a virtual root so world-anchored joints are processed
    visited: set = set(root_ids)
    visited.add(None)
    queue: list = [None] + list(root_ids)

    while queue:
        parent_id = queue.pop(0)
        for joint in assembly.joints:
            if joint.instance_a_id != parent_id:
                continue
            child_id = joint.instance_b_id
            if not child_id or child_id in visited:
                continue
            inst_b = inst_by_id.get(child_id)
            if not inst_b:
                visited.add(child_id)
                continue

            if joint.joint_type in ("revolute", "prismatic"):
                # Re-derive axis_origin from the live connector_a world position so that
                # any prior axis drift is corrected before re-applying the joint formula.
                # BFS processes parents before children, so inst_a.transform is already correct.
                if joint.connector_a_label and joint.instance_a_id:
                    inst_a_live = inst_by_id.get(joint.instance_a_id)
                    if inst_a_live:
                        F_a = frames_by_conn.get(
                            (inst_a_live.id, joint.connector_a_label)
                        )
                        if F_a is not None:
                            joint.axis_origin = F_a[:3, 3].tolist()
                old_T = _mat4_from_model(inst_b.transform)
                base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
                if joint.joint_type == "revolute":
                    new_mat = _apply_revolute_joint(
                        base_mat,
                        joint.axis_origin,
                        joint.axis_direction,
                        joint.current_value,
                    )
                else:
                    new_mat = _apply_prismatic_joint(
                        base_mat, joint.axis_direction, joint.current_value
                    )
                inst_b.transform = _mat4_to_model(new_mat)
                try:
                    delta = new_mat @ np.linalg.inv(old_T)
                    fk_vis: set = {child_id}
                    _fk_expand_rigid_group(
                        assembly, child_id, delta, fk_vis, [], inst_by_id
                    )
                    _fk_propagate(assembly, fk_vis.copy(), delta, fk_vis, inst_by_id)
                    visited.update(fk_vis)
                    for nxt in fk_vis - {child_id}:
                        if nxt not in visited:
                            queue.append(nxt)
                    # Invalidate-and-refresh cached connector world frames for
                    # every instance whose transform changed in this step.
                    for moved_id in fk_vis:
                        _refresh_connector_frames_for_instance(
                            frames_by_conn,
                            labels_by_inst,
                            inst_by_id,
                            moved_id,
                            _design_for,
                            frames_local_cache,
                        )
                except np.linalg.LinAlgError:
                    pass

            elif joint.joint_type in ("rigid", "spherical"):
                # Re-snap inst_b so connector_b's world frame restores the
                # captured relative pose to connector_a's world frame. When
                # ``mate_relative_transform`` is present the snap is a full
                # SE3 (translation + rotation) — needed when a part edit has
                # rotated a connector inside its part (e.g. via cluster
                # rotation from Relax Bond). When absent (legacy joints saved
                # before the field existed) we fall back to a pure-translation
                # snap matching the old behaviour. Cluster transforms are
                # honoured on both sides. axis_origin is kept in sync so the
                # joint indicator visually follows connector_a.
                if (
                    joint.connector_a_label
                    and joint.instance_a_id
                    and joint.connector_b_label
                ):
                    inst_a_live = inst_by_id.get(joint.instance_a_id)
                    if inst_a_live:
                        snap_T: "np.ndarray | None" = None
                        ca_world: "np.ndarray | None" = None
                        if joint.mate_relative_transform is not None:
                            F_a = frames_by_conn.get(
                                (inst_a_live.id, joint.connector_a_label)
                            )
                            F_b = frames_by_conn.get(
                                (inst_b.id, joint.connector_b_label)
                            )
                            if F_a is not None and F_b is not None:
                                try:
                                    M = np.array(
                                        joint.mate_relative_transform, dtype=float
                                    ).reshape(4, 4)
                                    F_b_target = F_a @ M
                                    snap_T = F_b_target @ np.linalg.inv(F_b)
                                    ca_world = F_a[:3, 3]
                                except np.linalg.LinAlgError:
                                    snap_T = None
                        if snap_T is None:
                            # Legacy / fallback path: translation-only snap.
                            F_a = frames_by_conn.get(
                                (inst_a_live.id, joint.connector_a_label)
                            )
                            F_b = frames_by_conn.get(
                                (inst_b.id, joint.connector_b_label)
                            )
                            if F_a is not None and F_b is not None:
                                ca = F_a[:3, 3]
                                cb = F_b[:3, 3]
                                trans = ca - cb
                                if float(np.linalg.norm(trans)) > 1e-6:
                                    snap_T = np.eye(4, dtype=float)
                                    snap_T[:3, 3] = trans
                                    ca_world = ca
                        if snap_T is not None:
                            # Skip the apply step if snap_T is effectively
                            # identity (tolerance: 1µm of translation,
                            # 1e-6 rad of rotation).
                            d_trans = float(np.linalg.norm(snap_T[:3, 3]))
                            d_rot = float(np.linalg.norm(snap_T[:3, :3] - np.eye(3)))
                            if d_trans > 1e-6 or d_rot > 1e-6:
                                old_T = _mat4_from_model(inst_b.transform)
                                new_T = snap_T @ old_T
                                inst_b.transform = _mat4_to_model(new_T)
                                if inst_b.base_transform:
                                    inst_b.base_transform = _mat4_to_model(
                                        snap_T @ _mat4_from_model(inst_b.base_transform)
                                    )
                                if ca_world is not None:
                                    joint.axis_origin = ca_world.tolist()
                                # Propagate the snap to NON-rigid kinematic
                                # children only (revolute/prismatic). Do NOT
                                # expand rigid neighbours — in a chain of
                                # rigid mates each pair is an independent
                                # constraint, and the next BFS iteration will
                                # snap each one with its own residual. Pre-
                                # moving the whole rigid group here would add
                                # downstream instances to ``visited`` and
                                # cause the BFS to skip every subsequent
                                # rigid joint in the chain.
                                pre_visited = set(visited)
                                try:
                                    _fk_propagate(
                                        assembly,
                                        {child_id},
                                        snap_T,
                                        visited,
                                        inst_by_id,
                                    )
                                except np.linalg.LinAlgError:
                                    pass
                                # Invalidate-and-refresh cache for inst_b plus
                                # any propagated children whose transforms
                                # changed in this step.
                                moved_ids = (visited - pre_visited) | {child_id}
                                for moved_id in moved_ids:
                                    _refresh_connector_frames_for_instance(
                                        frames_by_conn,
                                        labels_by_inst,
                                        inst_by_id,
                                        moved_id,
                                        _design_for,
                                        frames_local_cache,
                                    )

            visited.add(child_id)
            queue.append(child_id)

    assembly_state.set_assembly(assembly)
    resp = _assembly_response(assembly)
    resp["solve_status"] = solve_status
    return resp


class BatchPatchItem(BaseModel):
    id: str
    transform: Optional[dict] = None
    representation: Optional[str] = None  # Phase-4: batch rep change
    visible: Optional[bool] = None


class BatchPatchRequest(BaseModel):
    patches: list[BatchPatchItem]


@router.patch("/assembly/instances/batch", status_code=200)
def batch_patch_instances(body: BatchPatchRequest) -> dict:
    """Patch transforms / representation / visibility on multiple instances
    atomically (single undo entry, single client-side rebuild).

    Combining 'Apply to all' rep changes into one request avoids the N
    sequential PATCH / rebuild cycles that previously stalled the browser
    when flipping 20+ instances back to 'full'.
    """
    assembly = assembly_state.get_or_404()
    inst_by_id = _build_inst_by_id(assembly)
    patched_ids: set = set()
    for item in body.patches:
        inst = inst_by_id.get(item.id)
        if not inst:
            raise HTTPException(404, detail=f"Instance {item.id} not found")
        if item.transform:
            inst.transform = Mat4x4(**item.transform)
            inst.base_transform = None
            patched_ids.add(item.id)
        if item.representation is not None:
            if item.representation not in _VALID_REPRESENTATIONS:
                raise HTTPException(
                    400,
                    detail=f"representation must be one of {_VALID_REPRESENTATIONS}",
                )
            inst.representation = item.representation
            # Mirror the per-instance route's session-state bookkeeping so
            # feature-log scrubbing preserves the user's rep choice.
            assembly_state.remember_instance_display(
                item.id, representation=item.representation
            )
        if item.visible is not None:
            inst.visible = item.visible
            assembly_state.remember_instance_display(item.id, visible=item.visible)
    if patched_ids:
        _enforce_connector_coincidence(assembly, patched_ids, inst_by_id)
    assembly_state.set_assembly(assembly)
    return _assembly_response(assembly)


_VALID_EXPORT_REPRESENTATIONS = ("working",) + _VALID_REPRESENTATIONS


class ExportRepresentationRequest(BaseModel):
    representation: str


@router.post("/assembly/export-representation", status_code=200)
def set_export_representation(body: ExportRepresentationRequest) -> dict:
    """Set the per-assembly representation used ONLY for photo-mode PNG/video
    export.  The live working view is unchanged; ``'working'`` exports the
    current per-instance reps as-is.  Stored on the Assembly (saved to .nass);
    silent (no undo entry) since it's a render preference, not a topology op.
    """
    if body.representation not in _VALID_EXPORT_REPRESENTATIONS:
        raise HTTPException(
            400,
            detail=f"representation must be one of {_VALID_EXPORT_REPRESENTATIONS}",
        )
    assembly = assembly_state.get_or_404()
    assembly.export_representation = body.representation
    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly)


class TransformPatchBody(BaseModel):
    """Body for ``PATCH /assembly/instances/transforms``.

    Map instance id → flat float list.  Accepts either a 16-float
    row-major matrix or a 12-float compact pack (top 3 rows; the 4th
    row is the implicit ``[0,0,0,1]``).
    """

    transforms: dict[str, list[float]]


def _replace_instances_in_place(
    assembly: Assembly,
    new_instances: list[PartInstance],
) -> Assembly:
    """Phase 2d — swap the instances list on an Assembly without paying
    for ``model_copy(update={'instances': ...})``'s per-item revalidation.

    Pydantic v2's default ``revalidate_instances='never'`` means
    ``model_copy(update=...)`` would not revalidate, but it does still
    rebuild the entire ``Assembly`` model — copying every other field.
    For high-frequency drag callers (PATCH transforms) we only need to
    swap the list pointer; direct in-place mutation is safe because
    callers serialize Assembly access through ``assembly_state``'s lock.

    Returns the same assembly with ``instances`` replaced.  No copy is
    made and no validators fire.
    """
    # Use object.__setattr__ to bypass Pydantic's __setattr__ slot which
    # would invoke per-field assignment validators on each call.
    object.__setattr__(assembly, "instances", new_instances)
    return assembly


def _patch_instance_transform_in_place(
    inst: PartInstance,
    values: list[float],
) -> None:
    """Apply a transform patch to an existing PartInstance in place,
    skipping per-field assignment validators.

    Accepts 12-float (compact, top 3 rows) or 16-float (row-major) input.
    """
    if len(values) == 12:
        full_values = [
            float(values[0]),
            float(values[1]),
            float(values[2]),
            float(values[3]),
            float(values[4]),
            float(values[5]),
            float(values[6]),
            float(values[7]),
            float(values[8]),
            float(values[9]),
            float(values[10]),
            float(values[11]),
            0.0,
            0.0,
            0.0,
            1.0,
        ]
    elif len(values) == 16:
        full_values = [float(v) for v in values]
    else:
        raise HTTPException(
            400,
            detail=f"transform must be 12 or 16 floats, got {len(values)}",
        )
    new_mat = Mat4x4(values=full_values)
    # Bypass per-field assignment validation by stamping directly.
    object.__setattr__(inst, "transform", new_mat)
    object.__setattr__(inst, "base_transform", None)


@router.patch("/assembly/instances/transforms", status_code=200)
def patch_instance_transforms(body: TransformPatchBody) -> dict:
    """Apply many transform updates atomically — no feature_log entry,
    no full assembly response.

    Targeted at the joint-drag use case: 1-N instances move per frame,
    paying neither the snapshot encoding (Phase 1b deferred but still a
    multi-ms cost on large assemblies) nor the wire-format serialization
    of the full assembly.

    Validation:
      * Each value list must be 12 floats (top 3 rows; the 4th row is
        the implicit ``[0,0,0,1]``) or 16 floats (row-major).
      * Unknown instance ids → 404; ATOMIC: nothing is applied if any id
        is missing.

    Response:  ``{"updated": [<id>, ...]}`` — caller already knows the
    transforms it sent; this is just the ack.
    """
    assembly = assembly_state.get_or_404()
    inst_by_id = _build_inst_by_id(assembly)

    # Pre-flight: validate all ids before mutating ANY transform.  This
    # gives the route the atomicity the docstring promises.
    for instance_id in body.transforms.keys():
        if instance_id not in inst_by_id:
            raise HTTPException(404, detail=f"Instance {instance_id} not found")

    updated: list[str] = []
    for instance_id, values in body.transforms.items():
        inst = inst_by_id[instance_id]
        _patch_instance_transform_in_place(inst, values)
        updated.append(instance_id)

    # Silent set — no undo push, no feature log entry.  The drag UX
    # owns its own snapshot ahead of the gesture; intermediate frames
    # mustn't fill the undo stack.
    assembly_state.set_assembly_silent(assembly)
    return {"updated": updated}


@router.patch("/assembly/instances/{instance_id}", status_code=200)
def patch_instance(instance_id: str, body: PatchInstanceRequest) -> dict:
    """Update fields on a PartInstance.

    When transform changes, FK is propagated and connector coincidence is enforced so that
    revolute/rigid joints are never violated by a direct transform patch.
    """
    assembly = assembly_state.get_or_404()
    # Transform commits need an immutable post-state so the assembly feature-log
    # helper can snapshot the still-live pre-state. Metadata-only patches retain
    # their established lightweight undo path below.
    if body.transform is not None:
        assembly = assembly.model_copy(deep=True)
    inst = _find_instance(assembly, instance_id)

    # ── Non-transform fields: use immutable model_copy ────────────────────────
    meta_updates: dict = {}
    if body.name is not None:
        meta_updates["name"] = body.name
    if body.mode is not None:
        if body.mode not in ("rigid", "flexible"):
            raise HTTPException(400, detail="mode must be 'rigid' or 'flexible'")
        meta_updates["mode"] = body.mode
    if body.visible is not None:
        meta_updates["visible"] = body.visible
        # Remember outside the snapshot so feature-log scrubbing preserves it.
        assembly_state.remember_instance_display(instance_id, visible=body.visible)
    if body.fixed is not None:
        meta_updates["fixed"] = body.fixed
    if body.representation is not None:
        if body.representation not in _VALID_REPRESENTATIONS:
            raise HTTPException(
                400, detail=f"representation must be one of {_VALID_REPRESENTATIONS}"
            )
        meta_updates["representation"] = body.representation
        assembly_state.remember_instance_display(
            instance_id, representation=body.representation
        )
    if body.allow_part_joints is not None:
        meta_updates["allow_part_joints"] = body.allow_part_joints
    if body.joint_states is not None:
        meta_updates["joint_states"] = body.joint_states
    if body.cluster_transform_overrides is not None:
        meta_updates["cluster_transform_overrides"] = [
            ClusterRigidTransform(**ct) for ct in body.cluster_transform_overrides
        ]

    if not meta_updates and body.transform is None:
        return _assembly_response(assembly)

    if body.transform is None:
        assembly_state.snapshot()

    if meta_updates:
        new_inst = inst.model_copy(update=meta_updates)
        new_instances = [
            new_inst if i.id == instance_id else i for i in assembly.instances
        ]
        assembly = assembly.model_copy(update={"instances": new_instances})
        # Re-acquire inst from the new assembly so FK below sees updated state
        inst = next(i for i in assembly.instances if i.id == instance_id)

    # ── Transform change: in-place mutation + FK propagation ─────────────────
    fk_visited: set[str] = set()
    if body.transform is not None:
        old_T = _mat4_from_model(inst.transform)
        new_T = np.array(body.transform["values"], dtype=float).reshape(4, 4)
        inst.transform = Mat4x4(values=[float(v) for v in new_T.flatten()])
        # NOTE: do NOT clear inst.base_transform yet. The gear-sync step below
        # needs the original base_transform to derive the implied joint angle
        # from (current vs base). We clear it after sync, mirroring the
        # original semantic of "this PATCH is now the new base pose".
        try:
            delta = new_T @ np.linalg.inv(old_T)
            visited = {instance_id}
            inst_by_id = _build_inst_by_id(assembly)
            _fk_expand_rigid_group(
                assembly, instance_id, delta, visited, [], inst_by_id
            )
            _fk_propagate(assembly, visited.copy(), delta, visited, inst_by_id)
            _enforce_connector_coincidence(assembly, visited, inst_by_id)
            fk_visited = visited
        except np.linalg.LinAlgError:
            pass  # singular old transform — skip FK

    # Re-sync revolute joint values for any joint whose child is the moved
    # instance (or got swept along by FK), then propagate gear relations.
    # Without this, the instance gizmo (TransformControls) would update the
    # transform directly without driving any gear-coupled counterpart.
    if body.transform is not None:
        affected = fk_visited | {instance_id}
        updated_joint_ids = _sync_revolute_values_for_instances(assembly, affected)
        # Parent-side sync: also handle joints where the moved instance is the
        # PARENT (instance_a) of a revolute joint whose child stayed put (e.g.
        # because the child is fixed). Δ = the rotation of (new_T @ inv(old_T))
        # about the joint axis.
        try:
            world_delta_M = new_T @ np.linalg.inv(old_T)
            parent_updates = _sync_revolute_values_for_parent_moves(
                assembly,
                affected,
                world_delta_M,
            )
            updated_joint_ids = [*updated_joint_ids, *parent_updates]
        except (np.linalg.LinAlgError, NameError):
            pass
        for jid in updated_joint_ids:
            _propagate_gear_relations_from(assembly, jid)
        # Now safe to clear base_transform — gear sync has already used it.
        inst.base_transform = None

    if body.transform is not None:
        updated = _apply_assembly_mutation_with_feature_log(
            assembly,
            op_kind="assembly-transform-instance",
            label=f"Move/rotate part: {inst.name or instance_id}",
            params={"instance_id": instance_id, "transform": body.transform},
        )
        return _assembly_response(updated)
    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/instances/{instance_id}/cluster-transform", status_code=200)
def patch_instance_cluster_transform(
    instance_id: str, body: PatchInstanceClusterTransformRequest
) -> dict:
    """Store a part-internal cluster transform on the assembly instance.

    The source part design is not modified. If a world-space delta is supplied,
    any mated child parts attached to this instance/cluster are moved by that
    delta and their own mate descendants are propagated.
    """
    assembly = assembly_state.get_or_404().model_copy(deep=True)
    inst = _find_instance(assembly, instance_id)

    override = ClusterRigidTransform(**body.cluster_transform)
    overrides = list(inst.cluster_transform_overrides)
    replaced = False
    for idx, ct in enumerate(overrides):
        if ct.id == body.cluster_id:
            overrides[idx] = override
            replaced = True
            break
    if not replaced:
        overrides.append(override)

    joint_states = dict(inst.joint_states)
    if body.joint_id is not None and body.joint_value is not None:
        joint_states[body.joint_id] = body.joint_value

    new_inst = inst.model_copy(
        update={
            "cluster_transform_overrides": overrides,
            "joint_states": joint_states,
        }
    )
    assembly.instances = [
        new_inst if i.id == instance_id else i for i in assembly.instances
    ]

    if body.delta_transform is not None:
        delta = np.array(body.delta_transform["values"], dtype=float).reshape(4, 4)
        _propagate_cluster_delta_to_mates(assembly, instance_id, body.cluster_id, delta)

    updated = _apply_assembly_mutation_with_feature_log(
        assembly,
        op_kind="assembly-transform-instance-cluster",
        label=f"Move/rotate part cluster: {inst.name or instance_id}",
        params={
            "instance_id": instance_id,
            "cluster_id": body.cluster_id,
            "joint_id": body.joint_id,
        },
    )
    return _assembly_response(updated)


def _replace_instance_design(
    assembly: Assembly, inst: PartInstance, design
) -> tuple[Assembly, PartInstance]:
    """Persist a resolved instance design and return the updated assembly/instance."""
    if inst.source.type == "file":
        # Write back to the existing workspace file
        dest = _safe_workspace_path(inst.source.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(design.to_json(), encoding="utf-8")
        new_source = inst.source  # path unchanged; watchdog fires SSE
    else:
        # Save inline design to workspace and switch to file-backed
        safe_stem = "".join(
            c if c.isalnum() or c in "-_ " else "_"
            for c in (design.metadata.name or inst.name or "part")
        )
        filename = _dedup_filename(safe_stem, ".nadoc")
        dest = _WORKSPACE_DIR / filename
        dest.write_text(design.to_json(), encoding="utf-8")
        new_source = PartSourceFile(path=filename)

    new_inst = inst.model_copy(update={"source": new_source})
    new_instances = [new_inst if i.id == inst.id else i for i in assembly.instances]
    assembly_state.snapshot()
    updated = assembly.model_copy(update={"instances": new_instances})
    assembly_state.set_assembly_silent(updated)
    _ageo.clear_geo_cache()
    return assembly_state.get_or_404(), new_inst


@router.patch("/assembly/instances/{instance_id}/design", status_code=200)
def patch_instance_design(instance_id: str, body: PatchInstanceDesignRequest) -> dict:
    """Replace the design of a PartInstance.

    File-backed instances: writes JSON back to the workspace file (watchdog then
    fires an SSE event to connected browsers).
    Inline instances: auto-saves the design as a new .nadoc file in the workspace
    and converts the source to PartSourceFile.
    """
    from backend.core.models import Design

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    try:
        design = Design.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid design JSON: {exc}") from exc

    # Connector-geometry signature BEFORE the replace, so we can tell whether the
    # edit actually moved any mate connectors.
    try:
        old_design = _load_design_from_source(
            inst.source, _assembly_source_path(assembly)
        )
        pre_geo_sig = _part_geometry_signature(old_design)
    except Exception:
        pre_geo_sig = None
    post_geo_sig = _part_geometry_signature(design)

    updated_assembly, _new_inst = _replace_instance_design(assembly, inst, design)

    # Auto-resolve mates when the part's connector geometry changed (cluster
    # transforms / deformations / loop-skips), so a polymerized chain — or any
    # mate — re-docks to the new part shape. Without this the chain stayed frozen
    # at the pre-edit pose (the part editor's save path skipped resolve entirely).
    # Mirrors seek_instance_features; manual Resolve always works regardless.
    if pre_geo_sig != post_geo_sig and updated_assembly.joints:
        resolve_assembly()
        updated_assembly = assembly_state.get_or_404()

    return _assembly_response(updated_assembly)


def _apply_part_mutation_with_feature_log(
    assembly: Assembly,
    inst: PartInstance,
    before: "Design",
    mutated: "Design",
    *,
    op_kind: str,
    part_label: str,
    assembly_label: str,
    params: dict,
):
    """Shared post-mutation pipeline for assembly-level edits to a part design.

    Steps (mirrors state.mutate_with_feature_log for design-mode):

    1. Cluster reconcile + pending-ligation retry on the mutated design.
    2. Snapshot pre (``before``) and post (after reconcile/retry) states.
    3. Append a full ``SnapshotLogEntry`` to the part design's ``feature_log``
       so the part-edit window can revert / seek.
    4. Persist the part via ``_replace_instance_design`` (takes the
       assembly-level deque snapshot, clears geo cache, writes the file).
    5. Append a metadata-only ``SnapshotLogEntry`` to the assembly's
       ``feature_log`` identifying which instance was touched.

    Returns ``(updated_assembly, updated_design)``.
    """
    from backend.core.models import SnapshotLogEntry
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    from backend.core.lattice import retry_pending_ligations as _retry_pending_ligations
    from backend.api.state import (
        encode_design_snapshot,
        _evict_oldest_payloads_if_over_budget,
    )

    pre_b64, pre_size = encode_design_snapshot(before)

    reconciled = reconcile_cluster_membership(before, mutated, None)
    updated_design = _retry_pending_ligations(before, reconciled)

    post_b64, post_size = encode_design_snapshot(updated_design)

    timestamp = _dt.now(_tz.utc).isoformat()

    part_entry = SnapshotLogEntry(
        op_kind=op_kind,
        label=part_label,
        timestamp=timestamp,
        params=params,
        design_snapshot_gz_b64=pre_b64,
        snapshot_size_bytes=pre_size,
        post_state_gz_b64=post_b64,
        post_state_size_bytes=post_size,
    )
    updated_design.feature_log.append(part_entry)
    _evict_oldest_payloads_if_over_budget(updated_design)

    asm_entry = SnapshotLogEntry(
        op_kind=op_kind,
        label=assembly_label,
        timestamp=timestamp,
        params={**params, "instance_id": inst.id, "instance_name": inst.name},
        # No payloads — assembly-level undo rides on assembly_state's deque.
        # evicted=True keeps revert/seek paths from trying to decode emptiness.
        design_snapshot_gz_b64="",
        snapshot_size_bytes=0,
        post_state_gz_b64="",
        post_state_size_bytes=0,
        evicted=True,
    )

    _replace_instance_design(assembly, inst, updated_design)
    cur_assembly = assembly_state.get_or_404()
    cur_assembly.feature_log.append(asm_entry)
    assembly_state.set_assembly_silent(cur_assembly)

    return assembly_state.get_or_404(), updated_design


def _apply_assembly_mutation_with_feature_log(
    mutated: Assembly,
    *,
    op_kind: str,
    label: str,
    params: dict,
) -> Assembly:
    """Persist an assembly-level mutation and record it on Assembly.feature_log.

    Each entry carries gzip+base64 snapshots of the pre- and post-mutation
    assembly state.  The deque snapshot is still pushed (so Ctrl-Z and the
    slider-seek path still stack-walk), but the embedded payloads let the
    per-entry Delete / Revert / Edit routes operate on individual entries
    without depending on deque depth.

    Phase 4b path-to-thousands: when pre/post differ by a small fraction of
    instances (< 10%) AND the assembly is large enough (>= 50 instances) to
    make full gzip encoding measurably costly, store the entry as a diff
    snapshot instead.  The seek/revert/delete routes detect the diff format
    via empty ``design_snapshot_gz_b64`` + populated ``diff_*`` fields and
    reconstruct pre/post by applying the diff against an anchor.

    Phase 1b path-to-thousands: when the diff variant doesn't apply but the
    immediately-previous feature_log entry carries a usable
    ``post_state_gz_b64`` AND the live ``feature_log_cursor`` is -1 (= we're
    appending to the tail, not mid-seek), skip the pre-state gzip entirely
    and mark ``pre_state_from_previous=True``.  The pre-state is then
    recovered on demand from the prior entry's post.  Halves snapshot
    encode work per mutation in the common consecutive-mutations path.
    """
    from backend.core.models import SnapshotLogEntry

    pre_assembly = assembly_state.get_or_404()

    pre_n = len(pre_assembly.instances)
    post_n = len(mutated.instances)
    pre_inst_ids = {i.id for i in pre_assembly.instances}
    post_inst_ids = {i.id for i in mutated.instances}
    # ``symmetric_difference`` already counts both adds and removes, so
    # ``instance_churn`` IS |added| + |removed|.  An earlier version added
    # ``max(0, post_n - pre_n)`` on top, which double-counted adds and
    # cut the effective threshold to ~5% for pure-add ops.
    instance_churn = len(pre_inst_ids.symmetric_difference(post_inst_ids))
    use_diff = pre_n >= _DIFF_SNAPSHOT_MIN_INSTANCES and instance_churn <= max(
        1, int(_DIFF_SNAPSHOT_RATIO * max(pre_n, post_n))
    )

    timestamp = _dt.now(_tz.utc).isoformat()
    if use_diff:
        # Diff variant: skip the expensive pre-state gzip (recoverable via
        # inverse-diff applied to the post-state).  Still encode the full
        # post-state — keeps seek/revert paths reliable across multiple
        # scrubs without requiring a full chain-walk reconstruction.
        # Net win: ~50% of the per-mutation gzip cost is removed, scaling
        # linearly with assembly size.
        diff_fields = assembly_state.encode_diff_snapshot(pre_assembly, mutated)
        post_payload, post_size = assembly_state.encode_assembly_snapshot(mutated)
        entry = SnapshotLogEntry(
            op_kind=op_kind,
            label=label,
            timestamp=timestamp,
            params=params,
            post_state_gz_b64=post_payload,
            post_state_size_bytes=post_size,
            evicted=False,
            **diff_fields,
        )
    elif (
        getattr(pre_assembly, "feature_log_cursor", -1) == -1
        and len(mutated.feature_log) > 0
        and bool(mutated.feature_log[-1].post_state_gz_b64)
    ):
        # Skip-pre variant: previous entry's post == current pre by the
        # append-only invariant + cursor==-1 (no mid-seek mutation).  Save
        # the gzip of pre entirely; mark the entry so navigation routes
        # know to chain-walk to the prior post.
        post_payload, post_size = assembly_state.encode_assembly_snapshot(mutated)
        entry = SnapshotLogEntry(
            op_kind=op_kind,
            label=label,
            timestamp=timestamp,
            params=params,
            post_state_gz_b64=post_payload,
            post_state_size_bytes=post_size,
            pre_state_from_previous=True,
            evicted=False,
        )
    else:
        pre_payload, pre_size = assembly_state.encode_assembly_snapshot(pre_assembly)
        post_payload, post_size = assembly_state.encode_assembly_snapshot(mutated)
        entry = SnapshotLogEntry(
            op_kind=op_kind,
            label=label,
            timestamp=timestamp,
            params=params,
            design_snapshot_gz_b64=pre_payload,
            snapshot_size_bytes=pre_size,
            post_state_gz_b64=post_payload,
            post_state_size_bytes=post_size,
            evicted=False,
        )
    new_log = list(mutated.feature_log) + [entry]
    updated = mutated.model_copy(
        update={"feature_log": new_log, "feature_log_cursor": -1}
    )
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(updated)
    return assembly_state.get_or_404()


# Diff-snapshot policy: switch to diff format when (a) the assembly is
# large enough that gzipping the full state is non-trivial (>= 100 instances),
# AND (b) the mutation touches less than 10% of total instances.  Below this
# threshold the diff bookkeeping overhead (model_dump per affected item +
# extra gzip of the modified payload) doesn't pay off — full snapshots are
# both faster AND easier to debug.  The diff path's win shows up at the
# 1000+ instance scale where the full-state gzip dominates.
_DIFF_SNAPSHOT_MIN_INSTANCES = 100
_DIFF_SNAPSHOT_RATIO = 0.10


class InstanceOverhangExtrudeRequest(BaseModel):
    helix_id: str
    bp_index: int
    direction: Direction
    is_five_prime: bool
    neighbor_row: int
    neighbor_col: int
    length_bp: int


@router.post("/assembly/instances/{instance_id}/overhang/extrude", status_code=200)
def extrude_instance_overhang(
    instance_id: str, body: InstanceOverhangExtrudeRequest
) -> dict:
    """Create a single-stranded overhang on a PartInstance's design.

    Mirrors POST /design/overhang/extrude but operates on the instance's resolved
    design. See ``_apply_part_mutation_with_feature_log`` for the bookkeeping
    (snapshots on the part design + a metadata entry on the assembly).
    """
    from backend.core.lattice import make_overhang_extrude

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    before = design.model_copy(deep=True)

    try:
        mutated = make_overhang_extrude(
            design,
            body.helix_id,
            body.bp_index,
            body.direction,
            body.is_five_prime,
            body.neighbor_row,
            body.neighbor_col,
            body.length_bp,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    updated_assembly, updated_design = _apply_part_mutation_with_feature_log(
        assembly,
        inst,
        before,
        mutated,
        op_kind="overhang-extrude",
        part_label=f"Overhang extrude: {body.length_bp} bp",
        assembly_label=f"{inst.name}: overhang extrude ({body.length_bp} bp)",
        params=body.model_dump(mode="json"),
    )
    return {
        **_assembly_response(updated_assembly),
        "design": updated_design.model_dump(mode="json"),
    }


class InstanceOverhangPatchRequest(BaseModel):
    sequence: Optional[str] = None
    label: Optional[str] = None
    rotation: Optional[list[float]] = None  # unit quaternion [qx, qy, qz, qw]


@router.patch(
    "/assembly/instances/{instance_id}/overhang/{overhang_id}", status_code=200
)
def patch_instance_overhang(
    instance_id: str, overhang_id: str, body: InstanceOverhangPatchRequest
) -> dict:
    """Patch sequence / label / rotation on an overhang inside a PartInstance.

    Mirrors PATCH /design/overhang/{id} but operates on the instance's design.
    Writes feature-log entries at both levels — see
    ``_apply_part_mutation_with_feature_log`` for the shape.

    Note: the design-mode endpoint also appends an ``OverhangRotationLogEntry``
    inline when ``rotation`` changes. The assembly-mode entry is a wrapper
    ``SnapshotLogEntry`` that captures the full delta, so we don't duplicate
    the rotation-specific entry — one entry per assembly-mode patch.
    """
    from backend.api.crud import OverhangPatchRequest, _build_overhang_patch

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    before = design.model_copy(deep=True)

    # Reuse the design-mode pure builder. It validates inputs and raises
    # HTTPException 404 / 409 / 422 on bad data; we let those propagate.
    crud_body = OverhangPatchRequest(**body.model_dump(exclude_unset=True))
    mutated, _spec_updates, _new_spec = _build_overhang_patch(
        design, overhang_id, crud_body
    )

    # Build a human-readable label describing what changed.
    changes = []
    if "sequence" in body.model_fields_set:
        changes.append("sequence")
    if body.label is not None:
        changes.append("label")
    if body.rotation is not None:
        changes.append("rotation")
    delta = ", ".join(changes) or "no-op"

    updated_assembly, updated_design = _apply_part_mutation_with_feature_log(
        assembly,
        inst,
        before,
        mutated,
        op_kind="overhang-bulk",
        part_label=f"Overhang patch: {delta}",
        assembly_label=f"{inst.name}: overhang patch ({delta})",
        params={
            **body.model_dump(mode="json", exclude_unset=True),
            "overhang_id": overhang_id,
        },
    )
    return {
        **_assembly_response(updated_assembly),
        "design": updated_design.model_dump(mode="json"),
    }


def _cluster_transforms_signature(design) -> tuple:
    """Stable hashable summary of a design's cluster transforms.

    Two seek positions whose ``cluster_transforms`` lists produce the same
    signature have the same per-helix rigid offsets, so any mate that snapped
    correctly before is still correct after. Used as a cheap gate so we only
    auto-resolve mates when a slider move actually moved cluster geometry.
    """
    return tuple(
        (ct.id, tuple(ct.translation), tuple(ct.rotation), tuple(ct.pivot))
        for ct in (design.cluster_transforms or [])
    )


def _part_geometry_signature(design) -> tuple:
    """Hashable summary of everything that moves a part's CONNECTOR geometry:
    cluster transforms, bend/twist deformations, and per-helix loop/skips.

    Used to gate the auto-resolve in :func:`seek_instance_features`. The earlier
    gate only watched cluster_transforms, on the (wrong) assumption that
    "deformations don't move mate connectors" — but connector frames are pulled
    live from ``deformed_helix_axes`` / ``deformed_nucleotide_positions`` (and,
    for periodic chains, ``principal_seam_connectors``), all of which reflect
    deformations and loop/skips. So a twist/bend edit on a part DOES move its
    connectors and must re-resolve the assembly (e.g. a periodic-polymerized
    chain re-docking to the new seam geometry)."""
    clusters = _cluster_transforms_signature(design)
    deforms = tuple(
        (
            op.id,
            op.type,
            op.plane_a_bp,
            op.plane_b_bp,
            tuple(sorted(op.params.model_dump().items())),
        )
        for op in (design.deformations or [])
    )
    loopskips = tuple(
        (
            h.id,
            tuple(
                tuple(sorted(ls.model_dump().items())) for ls in (h.loop_skips or [])
            ),
        )
        for h in (design.helices or [])
    )
    return (clusters, deforms, loopskips)


@router.post("/assembly/instances/{instance_id}/features/seek", status_code=200)
def seek_instance_features(instance_id: str, body: InstanceSeekFeaturesRequest) -> dict:
    """Replay one part instance's feature log and persist the resulting part design.

    Response includes the post-seek geometry inline (``nucleotides_compact``
    + ``helix_axes``) so the frontend can update rendering without an extra
    ``GET /assembly/instances/{id}/geometry`` round-trip. The geometry is
    also populated into ``_GEO_CACHE`` keyed by the post-write mtime, so any
    follow-up refetch (e.g. the watchdog SSE echo) is a cache hit instead
    of a 2-3 s re-computation.

    When the seek changes the part's connector geometry — cluster transforms
    (e.g. a Relax Bond cycle tilts a hinge), bend/twist deformations, or
    loop/skips — the function auto-runs ``resolve_assembly`` so mates stay
    snapped to the new connector positions. This includes periodic-polymerized
    chains: a deformation edit moves the seam cross-sections, and the live
    ``seam0:*`` connectors let the chain re-dock to the new geometry. Seeks that
    leave connector geometry unchanged skip the resolve (it would be a no-op).
    """
    from backend.api import crud as crud_api
    from backend.api.crud import (
        _geometry_for_design,
        _compact_geometry_from_nucleotides,
    )
    from backend.core.deformation import (
        deformed_helix_axes,
        _apply_ovhg_rotations_to_axes,
    )

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    pre_geo_sig = _part_geometry_signature(design)

    updated_design = crud_api._seek_feature_log(
        design, body.position, body.sub_position
    )
    post_geo_sig = _part_geometry_signature(updated_design)
    updated_assembly, new_inst = _replace_instance_design(
        assembly, inst, updated_design
    )

    # Auto-resolve mates if the part's connector geometry changed (cluster
    # transforms, deformations, or loop/skips). resolve_assembly reads from
    # assembly_state and writes the snapped state back; we capture solve_status
    # for the response so the frontend's "Mates" panel reflects which joints moved.
    solve_status: dict | None = None
    if pre_geo_sig != post_geo_sig and updated_assembly.joints:
        resolve_resp = resolve_assembly()
        solve_status = resolve_resp.get("solve_status")
        updated_assembly = assembly_state.get_or_404()

    # Compute geometry once and ship it inline. Without this the frontend
    # has to re-fetch via getInstanceGeometry on every slider tick (the
    # ~3 s killer for 60 k-bp designs). Populate _GEO_CACHE so the
    # filesystem-watchdog SSE echo, which may still trigger a refetch in
    # other tabs, hits cache instead of recomputing.
    # DISPLAY geometry strips reference strands (see _display_design); the
    # persisted updated_design above keeps them so topology isn't lost.
    display_design = _display_design(updated_design)
    nucleotides = _geometry_for_design(display_design, junction_balance=True)
    axes = deformed_helix_axes(display_design)
    _apply_ovhg_rotations_to_axes(display_design, axes, nucleotides)
    design_dict = display_design.to_dict()
    crud_api._inject_joint_world_axes(
        design_dict
    )  # world cluster-joint axes (see get_instance_geometry)
    key = _geo_cache_key(new_inst)
    if key:
        _geo_cache_set(
            key, {"nucleotides": nucleotides, "helix_axes": axes, "design": design_dict}
        )

    return {
        **_assembly_response(updated_assembly),
        "design": design_dict,
        "geometry": {
            "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
            "helix_axes": axes,
        },
        # Path the frontend should mark as "self-saved" so the watchdog
        # SSE echo doesn't trigger a redundant invalidate+refetch.
        "source_path": inst.source.path if inst.source.type == "file" else None,
        # Mate snap report — present only when clusters actually changed
        # and resolve fired. Frontend's mate panel reads this just like a
        # manual Resolve click.
        "solve_status": solve_status,
        "auto_resolved": solve_status is not None,
    }


# ── Assembly feature-log seek / replay ───────────────────────────────────────


class SeekAssemblyFeaturesRequest(BaseModel):
    position: int  # log entry index; -1 = end, -2 = empty


def _materialize_post_state(
    full_log: list, target_idx: int, current: Assembly
) -> Optional[Assembly]:
    """Return the post-state of ``full_log[target_idx]`` reconstructed from
    snapshots.

    Diff entries (Phase 4b) still carry a full ``post_state_gz_b64``
    payload alongside their diff fields — that's the cheap reliable
    anchor for seek/revert.  The diff data lives on for inverse-apply
    in :func:`_materialize_pre_state`.

    Returns ``None`` if reconstruction is impossible.
    """
    if target_idx < 0 or target_idx >= len(full_log):
        return None
    target = full_log[target_idx]
    if target.post_state_gz_b64:
        try:
            return assembly_state.decode_assembly_snapshot(target.post_state_gz_b64)
        except Exception:
            return None
    return None


def _materialize_pre_state(
    full_log: list, target_idx: int, current: Assembly
) -> Optional[Assembly]:
    """Return the pre-state of ``full_log[target_idx]`` (= state immediately
    before that entry's op ran).

    Four cases (delegated to :func:`assembly_state.lookup_pre_state`):
    * Legacy full snapshot — decode ``design_snapshot_gz_b64`` directly.
    * Diff entry (has ``post_state_gz_b64`` + diff fields) — decode post,
      inverse-apply the diff.
    * Skip-pre entry (Phase 1b) — chain-walk to previous entry's post.
    * No usable pre payload anywhere → returns ``None`` (seek path falls
      back to showing the current state).
    """
    if target_idx < 0 or target_idx >= len(full_log):
        return None
    try:
        return assembly_state.lookup_pre_state(full_log, target_idx)
    except HTTPException:
        # Seek tolerates unrecoverable pre-states by leaving the visible
        # geometry alone (matches pre-Phase-1b behaviour for legacy
        # payloadless entries).
        return None


@router.post("/assembly/features/seek", status_code=200)
def seek_assembly_features(body: SeekAssemblyFeaturesRequest) -> dict:
    """Seek the assembly feature log.

    ``position = -1`` → end of log (most recent state).
    ``position = -2`` → empty state (all entries undone).
    ``position >= 0`` → state after entry index ``position`` was applied.

    Mechanic: each entry carries an embedded post-state snapshot
    (``post_state_gz_b64``).  Seek decodes the target entry's snapshot and
    restores the assembly geometry to that state, but **preserves the
    complete feature_log** on the assembly — so scrubbing the slider never
    drops entries, and the user can always slide back to ``position = -1``
    to recover the latest state.

    The undo/redo deque is left untouched: Ctrl-Z continues to revert
    actual mutations (not slider scrubs).

    Legacy entries created before payload embedding shipped have empty
    snapshot strings — for those the route returns the current state
    unchanged so the panel still renders the entries (the slider just
    becomes a no-op until the user runs a new mutation that does embed a
    payload).
    """
    target_pos = body.position
    current = assembly_state.get_or_404()
    full_log = list(current.feature_log)
    log_len = len(full_log)

    if target_pos == -2:
        # Empty state — pre-state of the FIRST entry (= initial assembly).
        if not full_log:
            new_state = current
        else:
            pre0 = _materialize_pre_state(full_log, 0, current)
            new_state = pre0 if pre0 is not None else current
        new_cursor = -2
    elif target_pos == -1:
        # End of log — post-state of the LAST entry.
        if not full_log:
            new_state = current
        else:
            last_post = _materialize_post_state(full_log, len(full_log) - 1, current)
            new_state = last_post if last_post is not None else current
        new_cursor = -1
    else:
        # Explicit entry index — post-state of that entry.
        if target_pos < 0 or target_pos >= log_len:
            raise HTTPException(
                400,
                detail=f"feature index {target_pos} out of range (log length {log_len}).",
            )
        target_post = _materialize_post_state(full_log, target_pos, current)
        new_state = target_post if target_post is not None else current
        new_cursor = target_pos

    # Preserve display-only preferences across the scrub: if the user
    # selected a cheaper representation (e.g. switched a heavy part from
    # 'full' to 'cylinders' for a large assembly), they shouldn't be
    # bounced back to whatever was active when the snapshot was taken.
    # The persistent override dict lives in assembly_state and survives
    # consecutive scrubs even when the displayed assembly transitions
    # through empty states (e.g. position == -2).  As a fallback, also
    # honour any rep/visible on the current displayed state.
    persistent_overrides = assembly_state.get_display_overrides()
    fallback_overrides = {
        i.id: {"representation": i.representation, "visible": i.visible}
        for i in current.instances
    }
    if new_state is current:
        restored_instances = list(current.instances)
    else:
        restored_instances = []
        for i in new_state.instances:
            merged = {
                **fallback_overrides.get(i.id, {}),
                **persistent_overrides.get(i.id, {}),
            }
            restored_instances.append(i.model_copy(update=merged) if merged else i)

    # Restore the full feature_log onto the decoded state; only geometry
    # (instances, joints, assembly_helices/strands, overhang_*) was
    # supposed to vary with seek.
    final = new_state.model_copy(
        update={
            "instances": restored_instances,
            "feature_log": full_log,
            "feature_log_cursor": new_cursor,
        }
    )
    assembly_state.set_assembly_silent(final)
    return _assembly_response(assembly_state.get_or_404())


# ── Per-entry actions: revert, delete, edit ───────────────────────────────────
#
# The slider / seek route stack-walks the deque to navigate without changing
# the log.  These three routes mutate the log itself.  Each one relies on the
# pre/post-state payloads embedded in every SnapshotLogEntry by
# `_apply_assembly_mutation_with_feature_log` above — without those payloads
# we'd be stuck navigating the deque, which doesn't allow surgical mid-log
# changes (the deque is depth-bounded and ordered, not random-access).

# Editable op kinds: backend allows the Edit button to re-run them with new
# params.  Subset of replayable.
_EDITABLE_OP_KINDS: set[str] = {
    "assembly-polymerize",
    "assembly-polymerize-periodic",
    "assembly-overhang-connection-add",
    "assembly-overhang-connection-patch",
}

# Replayable op kinds: surgical mid-history delete can re-apply these to
# rebuild the trailing log.  Larger than _EDITABLE_OP_KINDS — adds/deletes
# of instances / connectors / joints don't have a useful Edit UI but they
# CAN be replayed using their stored ids.
_REPLAYABLE_OP_KINDS: set[str] = _EDITABLE_OP_KINDS | {
    "assembly-transform-instance",
    "assembly-add-instance",
    "assembly-delete-instance",
    "assembly-duplicate-instance",
    "assembly-add-connector",
    "assembly-delete-connector",
    "assembly-add-joint",
    "assembly-delete-joint",
    # Existing overhang-binding ops already use _apply_assembly_mutation;
    # replay just re-runs the binding logic via the routes themselves.
    "assembly-overhang-bind",
    "assembly-overhang-bind-patch",
    "assembly-overhang-unbind",
    "assembly-overhang-connection-delete",
}


class EditAssemblyFeatureRequest(BaseModel):
    """New parameters for the targeted feature.

    Shape is op-kind dependent — the dispatcher pulls only the fields it
    understands. Unknown fields are ignored. Identifiers (joint_id,
    connection_id, etc.) are taken from the entry's stored params so the
    user only needs to pass what they want to change.
    """

    params: dict


def _replay_assembly_op(assembly: Assembly, op_kind: str, params: dict) -> Assembly:
    """Re-run a known op_kind against *assembly* and return the new state.

    Used by Edit (and could be used by future surgical-delete-with-replay).
    Raises HTTPException with a specific message when the op kind isn't
    replayable or its params are malformed.
    """
    if op_kind == "assembly-transform-instance":
        instance_id = params.get("instance_id")
        transform = params.get("transform")
        values = transform.get("values") if isinstance(transform, dict) else None
        if not instance_id or not values:
            raise HTTPException(
                400, detail="transform-instance replay: instance_id/transform missing."
            )
        replayed = assembly.model_copy(deep=True)
        _propagate_fk_inplace(
            replayed, instance_id, values, _build_inst_by_id(replayed)
        )
        return replayed

    if op_kind == "assembly-polymerize":
        # Delegate to the actual route so all the chain math + pattern-mate
        # replication stays in one place. The route reads from
        # assembly_state; temporarily install the input assembly, invoke,
        # then strip the entry the route appends (the caller will append
        # a fresh one).
        joint_id = params.get("joint_id")
        count = int(params.get("count", 0))
        direction = params.get("direction", "forward")
        if (
            not joint_id
            or count < 2
            or direction not in ("forward", "backward", "both")
        ):
            raise HTTPException(400, detail="polymerize params malformed.")
        if count == 2:
            return assembly

        # Route fn + model now live in routes_assembly_polymerize.py; local
        # import avoids a circular import (that module imports kernel helpers
        # from here).
        from backend.api.routes_assembly_polymerize import (
            PolymerizeAssemblyRequest,
            polymerize_assembly,
        )

        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            body = PolymerizeAssemblyRequest(
                joint_id=joint_id,
                count=count,
                direction=direction,
                additional_instance_ids=list(
                    params.get("additional_instance_ids") or []
                ),
            )
            polymerize_assembly(body)
            result = assembly_state.get_or_404()
            result = result.model_copy(
                update={
                    "feature_log": result.feature_log[: len(assembly.feature_log)],
                    "feature_log_cursor": -1,
                }
            )
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-polymerize-periodic":
        # Delegate to the route (single source of truth for the chain math),
        # then strip the entry it appends so the caller can append a fresh one.
        instance_id = params.get("instance_id")
        count = int(params.get("count", 0))
        direction = params.get("direction", "forward")
        if (
            not instance_id
            or count < 2
            or direction not in ("forward", "backward", "both")
        ):
            raise HTTPException(400, detail="polymerize-periodic params malformed.")

        # Route fn + model now live in routes_assembly_polymerize.py; local
        # import avoids a circular import (that module imports kernel helpers
        # from here).
        from backend.api.routes_assembly_polymerize import (
            PolymerizePeriodicRequest,
            polymerize_periodic_assembly,
        )

        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            body = PolymerizePeriodicRequest(
                instance_id=instance_id,
                count=count,
                direction=direction,
            )
            polymerize_periodic_assembly(body)
            result = assembly_state.get_or_404()
            result = result.model_copy(
                update={
                    "feature_log": result.feature_log[: len(assembly.feature_log)],
                    "feature_log_cursor": -1,
                }
            )
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-overhang-connection-add":
        # Re-run by constructing a CreateAssemblyOverhangConnectionRequest and
        # delegating to the existing route logic. The route reads from
        # assembly_state, so we temporarily install the target assembly,
        # invoke, then capture the result.
        # Function-local import: the overhang routes live in
        # routes_assembly_overhangs, which imports the shared kernel helpers back
        # from this module — a top-level import here would be circular (L21/#23).
        from backend.api.routes_assembly_overhangs import (
            CreateAssemblyOverhangConnectionRequest,
            create_assembly_overhang_connection,
        )

        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            body = CreateAssemblyOverhangConnectionRequest(
                **{
                    k: v
                    for k, v in params.items()
                    if k in CreateAssemblyOverhangConnectionRequest.model_fields
                }
            )
            create_assembly_overhang_connection(body)
            result = assembly_state.get_or_404()
            # The route appended its own feature_log entry; strip it since
            # the caller will append a fresh entry for the edit.
            result = result.model_copy(
                update={
                    "feature_log": result.feature_log[: len(assembly.feature_log)],
                    "feature_log_cursor": -1,
                }
            )
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-overhang-connection-patch":
        connection_id = params.get("connection_id")
        if not connection_id:
            raise HTTPException(400, detail="connection_id missing from patch params.")
        # Function-local import: avoid the circular top-level import (see above).
        from backend.api.routes_assembly_overhangs import (
            PatchAssemblyOverhangConnectionRequest,
            patch_assembly_overhang_connection,
        )

        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            fields = {k: v for k, v in params.items() if k != "connection_id"}
            body = PatchAssemblyOverhangConnectionRequest(
                **{
                    k: v
                    for k, v in fields.items()
                    if k in PatchAssemblyOverhangConnectionRequest.model_fields
                }
            )
            patch_assembly_overhang_connection(connection_id, body)
            result = assembly_state.get_or_404()
            result = result.model_copy(
                update={
                    "feature_log": result.feature_log[: len(assembly.feature_log)],
                    "feature_log_cursor": -1,
                }
            )
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-add-instance":
        from pydantic import TypeAdapter
        from backend.core.models import PartSource

        source_data = params.get("source")
        if source_data is None:
            raise HTTPException(400, detail="add-instance replay: source missing.")
        try:
            source = TypeAdapter(PartSource).validate_python(source_data)
        except Exception as exc:
            raise HTTPException(
                400, detail=f"add-instance replay: invalid source: {exc}"
            ) from exc
        t_data = params.get("transform")
        transform = Mat4x4.model_validate(t_data) if t_data else Mat4x4()
        # Preserve the original id so later ops referencing it still resolve.
        inst = PartInstance(
            id=params.get("instance_id") or str(_uuid.uuid4()),
            name=params.get("name") or "Part",
            source=source,
            transform=transform,
        )
        return assembly.model_copy(
            update={
                "instances": list(assembly.instances) + [inst],
            }
        )

    if op_kind == "assembly-delete-instance":
        instance_id = params.get("instance_id")
        if not instance_id:
            raise HTTPException(
                400, detail="delete-instance replay: instance_id missing."
            )
        new_instances = [i for i in assembly.instances if i.id != instance_id]
        new_joints = [
            j
            for j in assembly.joints
            if j.instance_a_id != instance_id and j.instance_b_id != instance_id
        ]
        return assembly.model_copy(
            update={"instances": new_instances, "joints": new_joints}
        )

    if op_kind == "assembly-duplicate-instance":
        src_id = params.get("source_instance_id")
        new_id = params.get("new_instance_id")
        if not src_id or not new_id:
            raise HTTPException(
                400, detail="duplicate-instance replay: source/new id missing."
            )
        src = next((i for i in assembly.instances if i.id == src_id), None)
        if src is None:
            raise HTTPException(
                422,
                detail=f"duplicate-instance replay: source instance {src_id} no longer exists.",
            )
        offset = list(params.get("offset") or [5.0, 0.0, 0.0])
        new_T_arr = src.transform.to_array().copy()
        if len(offset) >= 3:
            new_T_arr[0, 3] += float(offset[0])
            new_T_arr[1, 3] += float(offset[1])
            new_T_arr[2, 3] += float(offset[2])
        new_inst = src.model_copy(
            deep=True,
            update={
                "id": new_id,
                "name": params.get("name") or f"{src.name} (copy)",
                "transform": Mat4x4.from_array(new_T_arr),
                "base_transform": None,
            },
        )
        return assembly.model_copy(
            update={
                "instances": list(assembly.instances) + [new_inst],
            }
        )

    if op_kind == "assembly-add-connector":
        instance_id = params.get("instance_id")
        label = params.get("label")
        if not instance_id or not label:
            raise HTTPException(
                400, detail="add-connector replay: instance_id/label missing."
            )
        pos = params.get("position") or [0.0, 0.0, 0.0]
        nrm = params.get("normal") or [0.0, 0.0, 1.0]
        ip = InterfacePoint(
            label=label,
            position=Vec3(x=float(pos[0]), y=float(pos[1]), z=float(pos[2])),
            normal=Vec3(x=float(nrm[0]), y=float(nrm[1]), z=float(nrm[2])),
            connection_type=ConnectionType.COVALENT,
            cluster_id=params.get("cluster_id"),
        )
        return assembly.model_copy(
            update={
                "instances": [
                    i.model_copy(update={"interface_points": [*i.interface_points, ip]})
                    if i.id == instance_id
                    else i
                    for i in assembly.instances
                ],
            }
        )

    if op_kind == "assembly-delete-connector":
        instance_id = params.get("instance_id")
        label = params.get("label")
        if not instance_id or not label:
            raise HTTPException(
                400, detail="delete-connector replay: instance_id/label missing."
            )
        return assembly.model_copy(
            update={
                "instances": [
                    i.model_copy(
                        update={
                            "interface_points": [
                                ip for ip in i.interface_points if ip.label != label
                            ],
                        }
                    )
                    if i.id == instance_id
                    else i
                    for i in assembly.instances
                ],
            }
        )

    if op_kind == "assembly-add-joint":
        # Reconstruct the joint directly from stored params, preserving its id.
        joint_id = params.get("joint_id")
        instance_b_id = params.get("instance_b_id")
        if not joint_id or not instance_b_id:
            raise HTTPException(
                400, detail="add-joint replay: joint_id/instance_b_id missing."
            )
        mate_rel = params.get("mate_relative_transform")
        joint = AssemblyJoint(
            id=joint_id,
            name=params.get("name") or "Joint",
            joint_type=params.get("joint_type") or "revolute",
            instance_a_id=params.get("instance_a_id"),
            instance_b_id=instance_b_id,
            cluster_id_a=params.get("cluster_id_a"),
            cluster_id_b=params.get("cluster_id_b"),
            axis_origin=list(params.get("axis_origin") or [0.0, 0.0, 0.0]),
            axis_direction=list(params.get("axis_direction") or [0.0, 0.0, 1.0]),
            current_value=0.0,
            min_limit=params.get("min_limit"),
            max_limit=params.get("max_limit"),
            connector_a_label=params.get("connector_a_label"),
            connector_b_label=params.get("connector_b_label"),
            mate_relative_transform=list(mate_rel) if mate_rel else None,
        )
        return assembly.model_copy(
            update={
                "joints": list(assembly.joints) + [joint],
            }
        )

    if op_kind == "assembly-delete-joint":
        joint_id = params.get("joint_id")
        if not joint_id:
            raise HTTPException(400, detail="delete-joint replay: joint_id missing.")
        return assembly.model_copy(
            update={
                "joints": [j for j in assembly.joints if j.id != joint_id],
            }
        )

    raise HTTPException(
        422,
        detail=f"Replay not supported for op_kind {op_kind!r}.",
    )


def _decode_entry_pre_state(feature_log, index: int) -> Assembly:
    """Return the pre-state Assembly for ``feature_log[index]``.

    Thin wrapper over :func:`assembly_state.lookup_pre_state` that also
    handles legacy full snapshots, Phase 4b diff entries, and Phase 1b
    skip-pre entries.  See the helper docstring for the full storage-mode
    matrix.
    """
    return assembly_state.lookup_pre_state(feature_log, index)


@router.post("/assembly/features/{index}/revert", status_code=200)
def revert_assembly_to_before_feature(index: int) -> dict:
    """Restore the pre-state of entry *index* and truncate the log to *index*.

    Subsequent entries (index+1, …) are dropped; their effects are no longer
    applied. The mutation is pushed onto the undo deque so Ctrl-Z restores
    the prior state.
    """
    assembly = assembly_state.get_or_404()
    if index < 0 or index >= len(assembly.feature_log):
        raise HTTPException(404, detail=f"feature index {index} out of range.")
    pre_assembly = _decode_entry_pre_state(assembly.feature_log, index)
    pre_assembly = pre_assembly.model_copy(
        update={
            "feature_log": list(assembly.feature_log[:index]),
            "feature_log_cursor": -1,
        }
    )
    assembly_state.set_assembly(pre_assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/features/{index}", status_code=200)
def delete_assembly_feature(index: int) -> dict:
    """Surgically remove entry *index* and replay later entries.

    For the latest entry this is equivalent to revert. For mid-history
    entries each following entry is re-run via :func:`_replay_assembly_op`;
    if any later entry has an op kind that isn't replayable, the request
    is rejected with 422 so the user can fall back to Revert.
    """
    assembly = assembly_state.get_or_404()
    if index < 0 or index >= len(assembly.feature_log):
        raise HTTPException(404, detail=f"feature index {index} out of range.")
    pre_assembly = _decode_entry_pre_state(assembly.feature_log, index)
    later_entries = list(assembly.feature_log[index + 1 :])

    # Verify every later entry is replayable before we touch state.
    for j, ent in enumerate(later_entries):
        if ent.op_kind not in _REPLAYABLE_OP_KINDS:
            raise HTTPException(
                422,
                detail=(
                    f"Cannot surgically delete entry {index}: "
                    f"later entry {index + 1 + j} ({ent.op_kind}) is not "
                    f"replayable. Use Revert to truncate from index {index} instead."
                ),
            )

    # Replay each later entry against the rebuilt state and re-record the log.
    new_log: list = []
    base_log = list(assembly.feature_log[:index])
    prev_state = pre_assembly.model_copy(
        update={
            "feature_log": base_log,
            "feature_log_cursor": -1,
        }
    )
    for ent in later_entries:
        replayed = _replay_assembly_op(prev_state, ent.op_kind, ent.params)
        # Pre-state for this re-recorded entry = the state immediately
        # before re-applying the op (= prev_state); post-state = result of
        # the replay. Encode each so the new entry still supports per-entry
        # actions later.
        pre_b64, pre_size = assembly_state.encode_assembly_snapshot(prev_state)
        post_b64, post_size = assembly_state.encode_assembly_snapshot(replayed)
        replayed_entry = ent.model_copy(
            update={
                "design_snapshot_gz_b64": pre_b64,
                "snapshot_size_bytes": pre_size,
                "post_state_gz_b64": post_b64,
                "post_state_size_bytes": post_size,
                "evicted": False,
                # Re-recorded as legacy full-snapshot — clear any diff / skip-pre
                # flags inherited from the original entry so navigation reads it
                # as the full snapshot it now is.
                "diff_added_b64": "",
                "diff_removed_ids": [],
                "diff_modified_b64": "",
                "pre_state_from_previous": False,
            }
        )
        new_log.append(replayed_entry)
        prev_state = replayed.model_copy(update={"feature_log": base_log + new_log})

    final = prev_state.model_copy(update={"feature_log_cursor": -1})
    assembly_state.set_assembly(final)
    return _assembly_response(assembly_state.get_or_404())


@router.post("/assembly/features/{index}/edit", status_code=200)
def edit_assembly_feature(index: int, body: EditAssemblyFeatureRequest) -> dict:
    """Re-run entry *index* with new params, replacing it (and only it).

    v1 supports editing only the latest entry — replaying later entries on
    top of a changed earlier op is not yet wired (would need careful
    handling for entries that reference the original entry's outputs).
    """
    assembly = assembly_state.get_or_404()
    if index < 0 or index >= len(assembly.feature_log):
        raise HTTPException(404, detail=f"feature index {index} out of range.")
    if index != len(assembly.feature_log) - 1:
        raise HTTPException(
            422,
            detail="Edit currently supported only on the most recent entry.",
        )
    entry = assembly.feature_log[index]
    if entry.op_kind not in _EDITABLE_OP_KINDS:
        raise HTTPException(
            422,
            detail=f"Edit not supported for op_kind {entry.op_kind!r}.",
        )
    pre_assembly = _decode_entry_pre_state(assembly.feature_log, index)
    pre_assembly = pre_assembly.model_copy(
        update={
            "feature_log": list(assembly.feature_log[:index]),
            "feature_log_cursor": -1,
        }
    )

    # Merge stored params with the user's overrides — the user only sends
    # the fields they want to change.
    new_params = {**(entry.params or {}), **(body.params or {})}

    # Install the pre-state and re-run via the standard mutation helper so
    # the resulting entry is fully payloaded.
    assembly_state.set_assembly_silent(pre_assembly)
    mutated = _replay_assembly_op(pre_assembly, entry.op_kind, new_params)
    label = f"{entry.label} (edited)" if entry.label else f"Edit {entry.op_kind}"
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind=entry.op_kind,
        label=label,
        params=new_params,
    )
    return _assembly_response(assembly_state.get_or_404())


class DuplicateInstanceRequest(BaseModel):
    """Optional knobs for /assembly/instances/{id}/duplicate.

    The new instance inherits source + interface_points + representation/mode
    from the source instance; its transform is the source transform plus a
    user-controllable translational offset (default: +5 nm along world +X so
    the clone is visible next to the original)."""

    offset: list[float] = [5.0, 0.0, 0.0]
    name: Optional[str] = None


@router.post("/assembly/instances/{instance_id}/duplicate", status_code=200)
def duplicate_instance(
    instance_id: str, body: DuplicateInstanceRequest = DuplicateInstanceRequest()
) -> dict:
    """Create a copy of a PartInstance: same source, same connectors, slightly
    offset transform so the clone is visible next to the original.

    Connectors are deep-copied so the clone is immediately mateable on the
    same labels as the source.
    """
    assembly = assembly_state.get_or_404()
    src = _find_instance(assembly, instance_id)

    new_T_arr = src.transform.to_array().copy()
    if len(body.offset) >= 3:
        new_T_arr[0, 3] += float(body.offset[0])
        new_T_arr[1, 3] += float(body.offset[1])
        new_T_arr[2, 3] += float(body.offset[2])

    new_inst = src.model_copy(
        deep=True,
        update={
            "id": str(_uuid.uuid4()),
            "name": body.name or f"{src.name} (copy)",
            "transform": Mat4x4.from_array(new_T_arr),
            "base_transform": None,
        },
    )
    new_instances = list(assembly.instances) + [new_inst]
    mutated = assembly.model_copy(update={"instances": new_instances})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplicate-instance",
        label=f"Duplicate part: {src.name} → {new_inst.name}",
        params={
            "source_instance_id": instance_id,
            "new_instance_id": new_inst.id,
            "offset": list(body.offset),
            "name": new_inst.name,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/instances/{instance_id}", status_code=200)
def delete_instance(instance_id: str) -> dict:
    """Remove a PartInstance and any joints that reference it."""
    assembly = assembly_state.get_or_404()
    target = _find_instance(assembly, instance_id)

    new_instances = [i for i in assembly.instances if i.id != instance_id]
    new_joints = [
        j
        for j in assembly.joints
        if j.instance_a_id != instance_id and j.instance_b_id != instance_id
    ]
    new_groups = _ag.filter_groups_after_instance_removal(
        list(assembly.groups),
        {instance_id},
    )
    mutated = assembly.model_copy(
        update={
            "instances": new_instances,
            "joints": new_joints,
            "groups": new_groups,
        }
    )

    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-instance",
        label=f"Delete part: {target.name}",
        params={"instance_id": instance_id, "name": target.name},
    )
    assembly_state.forget_instance_display(instance_id)
    return _assembly_response(assembly_state.get_or_404())


# ── Gear/belt endpoint resolution (shared helper) ─────────────────────────────
#
# The gear-relation routes live in routes_assembly_gears.py and the belt-path
# routes in routes_assembly_belts.py; this resolver stays here because both
# routers' pulley/endpoint handlers call it (gear's create/patch,
# belt's _resolve_belt_pulley) and it raises HTTPException (L4-blocked from
# backend/core). Both routers import it back as shared infrastructure.


def _resolve_gear_endpoint(
    joint: AssemblyJoint, instance_id: Optional[str], side: Optional[str], label: str
) -> tuple[Optional[str], str]:
    if side not in (None, "a", "b"):
        raise HTTPException(400, detail=f"{label}.side must be 'a' or 'b'.")
    if instance_id:
        if instance_id == joint.instance_a_id:
            resolved_side = "a"
        elif instance_id == joint.instance_b_id:
            resolved_side = "b"
        else:
            raise HTTPException(
                400,
                detail=f"{label} instance is not an endpoint of the selected revolute mate.",
            )
        if side and side != resolved_side:
            raise HTTPException(
                400, detail=f"{label} side does not match its instance."
            )
        return instance_id, resolved_side
    resolved_side = side or "b"
    resolved_id = joint.instance_a_id if resolved_side == "a" else joint.instance_b_id
    return resolved_id, resolved_side


# ── Instance connectors (InterfacePoints) ─────────────────────────────────────
# NOTE: the add/delete instance-connector (InterfacePoint) routes now live in
# routes_assembly_connectors.py.


# ── Linker geometry ───────────────────────────────────────────────────────────
# NOTE: the linker-helix / linker-strand CRUD routes and the
# GET /assembly/linker-geometry route now live in routes_assembly_linkers.py.
# The compute helper below stays here: it depends on the api-layer
# crud._geometry_for_design (cannot move to backend/core without inverting the
# api→core arrow) and is also called from the overhang-connections region +
# the relax test suite. routes_assembly_linkers.py imports it back.


def _linker_geometry_for_assembly(assembly) -> dict:
    """Compute nucleotide geometry for *assembly*'s linker helices and strands.

    Pure (takes the assembly explicitly) so the relax solver + connector-arc
    checker can emit the SAME world-space beads the renderer shows, not a
    re-derived approximation. Builds a synthetic Design from assembly_helices +
    assembly_strands plus *world-space alias helices* for every cross-part
    complement domain (``<inst_id>::<orig_helix_id>``) and runs the main
    geometry pipeline. Returns ``{nucleotides, helix_axes, aliased_helices}``.

    Returns empty arrays when there are no linker helices/strands.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.assembly_linker import (
        parse_namespaced_helix_id,
        _world_axes_for_helix,
    )
    from backend.core.deformation import deformed_helix_axes
    from backend.core.geometry import _frame_from_helix_axis
    from backend.core.models import Design

    if not assembly.assembly_helices and not assembly.assembly_strands:
        return {"nucleotides": [], "helix_axes": {}, "aliased_helices": []}

    # Synthesize world-space alias helices for every (instance_id, original
    # helix_id) referenced by a complement domain. Without these the
    # geometry pipeline silently skips the cross-part bp emissions.
    referenced: dict[str, tuple[str, str]] = {}
    for s in assembly.assembly_strands:
        for d in s.domains:
            parsed = parse_namespaced_helix_id(d.helix_id)
            if parsed is not None:
                referenced[d.helix_id] = parsed

    aliased: list = []
    seen_namespaced_ids: set[str] = set()
    for namespaced_id, (inst_id, orig_helix_id) in referenced.items():
        if namespaced_id in seen_namespaced_ids:
            continue
        seen_namespaced_ids.add(namespaced_id)
        inst = next((i for i in assembly.instances if i.id == inst_id), None)
        if inst is None:
            continue
        design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
        helix = design.find_helix(orig_helix_id)
        if helix is None:
            continue
        T = inst.transform.to_array()
        ws, we = _world_axes_for_helix(helix, T)
        # Phase correction. The geometry pipeline derives a helix's radial frame
        # from a FIXED world reference (`_frame_from_helix_axis`), which is NOT
        # rotation-equivariant: frame(R·axis) ≠ R·frame(axis) once the part is
        # tilted off world-Z. The overhang itself is built in the part's local
        # frame and then placed by the instance transform T, so its phase is
        # R·(local frame); but this aliased helix is in world space, so the
        # pipeline would roll the complement (the overhang's binding domain) to
        # frame(R·axis) instead — visibly wrong phase for any tilted part. Bake
        # the roll difference δ between the world-pipeline frame and R·(local
        # frame) into phase_offset so the world pass reproduces R·(local geometry).
        R = T[:3, :3]
        local_axis = helix.axis_end.to_array() - helix.axis_start.to_array()
        world_axis = we - ws
        wx = _frame_from_helix_axis(world_axis)[:, 0]
        correct_x = R @ _frame_from_helix_axis(local_axis)[:, 0]
        z_hat = world_axis / (float(np.linalg.norm(world_axis)) or 1.0)
        delta = math.atan2(
            float(np.dot(np.cross(wx, correct_x), z_hat)), float(np.dot(wx, correct_x))
        )
        aliased.append(
            helix.model_copy(
                update={
                    "id": namespaced_id,
                    "axis_start": Vec3.from_array(ws),
                    "axis_end": Vec3.from_array(we),
                    "phase_offset": helix.phase_offset + delta,
                    # Loop/skip records reference original-helix bp indices, which
                    # don't apply to the cross-part complement (it's not part of
                    # the OH's helix geometry pass). Drop them to keep the
                    # synthetic pass clean.
                    "loop_skips": [],
                }
            )
        )

    synthetic = Design(
        helices=list(assembly.assembly_helices) + aliased,
        strands=list(assembly.assembly_strands),
        lattice_type="HONEYCOMB",  # LatticeType enum value (lowercase 500s the endpoint)
        metadata=DesignMetadata(name="__linkers__"),
    )
    return {
        # include_linker_helices=True: render the world-space __lnk__ bridge
        # helix directly (the assembly synthetic design has no
        # overhang_connections, so _emit_bridge_nucs can't emit the bridge).
        # junction_balance is a no-op here: `synthetic` is hardcoded HONEYCOMB above,
        # whose balance roll is 0.  A ds linker on a SQUARE design therefore draws its
        # bridge unrolled beside rolled part beads — a known gap, unexercised (no
        # fixture in Examples/ or workspace/ has a ds linker).
        "nucleotides": _geometry_for_design(
            synthetic, include_linker_helices=True, junction_balance=True
        ),
        "helix_axes": deformed_helix_axes(synthetic),
        "aliased_helices": [h.model_dump(mode="json") for h in aliased],
    }


def assembly_connector_arc_lengths(assembly) -> dict[str, dict[str, float]]:
    """Checker: the ACTUAL 3D connector-arc lengths per ds connection, measured
    between the EMITTED complement-junction backbone bead and the EMITTED bridge-
    boundary backbone bead — the exact quantity the relax drives to zero (mirrors
    the per-design ``_anchor_pos_and_normal`` / arc-residual checks).

    Returns ``{conn_id: {'a': length_nm, 'b': length_nm}}`` for each ds linker.
    """
    from backend.core.assembly_linker_relax import _connector_arc_endpoints

    geo = _linker_geometry_for_assembly(assembly)
    nucs = geo.get("nucleotides", [])
    out: dict[str, dict[str, float]] = {}
    for conn in assembly.overhang_connections:
        if getattr(conn, "linker_type", "ds") != "ds":
            continue
        ep = _connector_arc_endpoints(nucs, assembly.assembly_strands, conn)
        sides: dict[str, float] = {}
        for side in ("a", "b"):
            seg = ep.get(side)
            if seg is not None:
                anchor, bead = seg
                sides[side] = float(np.linalg.norm(bead - anchor))
        out[conn.id] = sides
    return out


# ── Undo / Redo ───────────────────────────────────────────────────────────────


@router.post("/assembly/undo", status_code=200)
def undo_assembly() -> dict:
    """Undo the last assembly-level operation."""
    return _assembly_response(assembly_state.undo())


@router.post("/assembly/redo", status_code=200)
def redo_assembly() -> dict:
    """Redo the last undone assembly-level operation."""
    return _assembly_response(assembly_state.redo())


# ── Debug endpoints ───────────────────────────────────────────────────────────


@router.get("/debug/assembly", status_code=200)
def debug_assembly() -> dict:
    """Return the full active assembly JSON plus summary counts."""
    assembly = assembly_state.get_or_create()
    return {
        "assembly": assembly.to_dict(),
        "instance_count": len(assembly.instances),
        "joint_count": len(assembly.joints),
    }


@router.get("/debug/assembly-undo-depth", status_code=200)
def debug_assembly_undo_depth() -> dict:
    """Return current undo and redo stack depths for the assembly."""
    return {
        "undo": assembly_state.undo_depth(),
        "redo": assembly_state.redo_depth(),
    }


@router.get("/debug/assembly-joint-transform/{joint_id}", status_code=200)
def debug_assembly_joint_transform(joint_id: str, angle: float = 0.0) -> dict:
    """
    Preview the transform that would be applied to instance_b at *angle* radians,
    without committing.  Useful for verifying cos/sin values in the rotation matrix.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)
    inst_b = _find_instance(assembly, joint.instance_b_id)
    base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
    result = _apply_revolute_joint(
        base_mat, joint.axis_origin, joint.axis_direction, angle
    )
    return {
        "joint_id": joint_id,
        "angle_rad": angle,
        "angle_deg": math.degrees(angle),
        "instance_b_id": joint.instance_b_id,
        "transform_preview": result.flatten().tolist(),
    }
