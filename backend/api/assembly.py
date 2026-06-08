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

GET   /assembly/library                 scan parts-library/ for *.nadoc files
POST  /assembly/library/register        manually register a part file
POST  /assembly/library/rescan          refresh sha256 hashes, remove missing files

GET   /assembly/instances/{id}/design   resolve and return instance's Design JSON
GET   /assembly/instances/{id}/geometry geometry for instance's design (local frame)

GET   /debug/assembly                   full assembly dump + counts
GET   /debug/assembly-undo-depth        undo/redo stack depths
GET   /debug/assembly-joint-transform/{joint_id}  preview joint transform at angle
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid as _uuid
from collections import OrderedDict
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

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
    PartLibraryEntry,
    PartSourceFile,
    Vec3,
)
from backend.core import assembly_groups as _ag
from backend.core import workspace as _ws

router = APIRouter()

# ── Project root (two levels above this file: backend/api/ → backend/ → root) ──
_PROJECT_ROOT  = Path(__file__).resolve().parent.parent.parent
_LIBRARY_DIR   = _PROJECT_ROOT / "parts-library"
_WORKSPACE_DIR = Path(os.environ.get("NADOC_WORKSPACE", str(_PROJECT_ROOT / "workspace")))


# ── Geometry cache ─────────────────────────────────────────────────────────────
# In-memory LRU cache for nucleotide geometry + helix axes.
# Key: stable fingerprint of (source file + mtime, cluster_transform_overrides).
# Value: {"nucleotides": [...], "helix_axes": [...], "design": {...}}
# Avoids re-running the expensive _geometry_for_design pipeline on repeated calls
# for the same design configuration (e.g. undo/redo, reassembly rebuilds, tab
# switches back to the same instance).

_GEO_CACHE: OrderedDict[str, dict] = OrderedDict()
_GEO_CACHE_MAX = 16


def _geo_cache_key(inst: "PartInstance") -> str | None:
    """Return a stable cache key for an instance's geometry, or None if not cacheable."""
    overrides = inst.cluster_transform_overrides or []
    try:
        ov_str = json.dumps(
            [co.model_dump() for co in overrides],
            sort_keys=True, separators=(',', ':'),
        )
    except Exception:
        return None
    ov_hash = hashlib.sha256(ov_str.encode()).hexdigest()[:12] if overrides else ''

    src = inst.source
    if src.type == 'file':
        p = Path(src.path)
        if not p.is_absolute():
            for base in filter(None, [_WORKSPACE_DIR]):
                candidate = (base / p).resolve()
                if candidate.is_file():
                    p = candidate
                    break
            else:
                return None
        if not p.is_file():
            return None
        mtime_ns = p.stat().st_mtime_ns
        return f"f:{p}:{mtime_ns}:{ov_hash}"
    elif src.type == 'inline' and src.design:
        return f"i:{src.design.id}:{ov_hash}"
    return None


def _geo_cache_get(key: str) -> dict | None:
    if key not in _GEO_CACHE:
        return None
    _GEO_CACHE.move_to_end(key)
    return _GEO_CACHE[key]


def _geo_cache_set(key: str, value: dict) -> None:
    if key in _GEO_CACHE:
        _GEO_CACHE.move_to_end(key)
    _GEO_CACHE[key] = value
    while len(_GEO_CACHE) > _GEO_CACHE_MAX:
        _GEO_CACHE.popitem(last=False)


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


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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
        raise HTTPException(400, detail=f"Failed to load part file {source.path!r}: {exc}") from exc


def _design_with_instance_overrides(inst: PartInstance, assembly_path: str | None = None):
    """Resolve an instance design plus assembly-scoped cluster transform overrides."""
    design = _load_design_from_source(inst.source, assembly_path)
    if not inst.cluster_transform_overrides:
        return design
    overrides = {ct.id: ct for ct in inst.cluster_transform_overrides}
    merged = [overrides.get(ct.id, ct) for ct in design.cluster_transforms]
    existing = {ct.id for ct in merged}
    merged.extend(ct for ct in inst.cluster_transform_overrides if ct.id not in existing)
    return design.copy_with(cluster_transforms=merged)


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
    _get_connector_world_frame,
    _get_connector_world,
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
    _apply_revolute_value_to_gear_endpoint,
    _propagate_gear_relations_from,
)


def _infer_cluster_ids_for_connector_label(inst: PartInstance, label: str | None) -> list[str]:
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
    joint_cluster_ids = {j.cluster_id for j in (design.cluster_joints or []) if j.cluster_id}
    matches = [ct for ct in clusters if helix_id in (ct.helix_ids or [])]
    matches.sort(key=lambda ct: (
        0 if ct.id in joint_cluster_ids else 1,
        1 if getattr(ct, "is_default", False) else 0,
        len(ct.helix_ids or []),
    ))
    return [ct.id for ct in matches]


def _joint_side_cluster_ids(assembly, joint, side: str) -> set[str]:
    ids: set[str] = set()
    if side == "a":
        if joint.cluster_id_a:
            ids.add(joint.cluster_id_a)
        if joint.instance_a_id is None or not joint.connector_a_label:
            return ids
        inst = next((i for i in assembly.instances if i.id == joint.instance_a_id), None)
        label = joint.connector_a_label
    else:
        if joint.cluster_id_b:
            ids.add(joint.cluster_id_b)
        inst = next((i for i in assembly.instances if i.id == joint.instance_b_id), None)
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
        if j.instance_a_id == instance_id and cluster_id in _joint_side_cluster_ids(assembly, j, "a"):
            other_id = j.instance_b_id
        elif j.instance_b_id == instance_id and cluster_id in _joint_side_cluster_ids(assembly, j, "b"):
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
    source: dict                         # raw dict; validated below
    name: str = "Part"
    transform: Optional[dict] = None     # Mat4x4 dict; defaults to identity


_VALID_REPRESENTATIONS = ('full', 'beads', 'cylinders', 'vdw', 'ballstick', 'hull-prism', 'surface')

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


class AddJointRequest(BaseModel):
    name: str = "Joint"
    joint_type: str = "revolute"
    instance_a_id: Optional[str] = None
    cluster_id_a: Optional[str] = None
    instance_b_id: str
    cluster_id_b: Optional[str] = None
    axis_origin: list[float] = [0.0, 0.0, 0.0]
    axis_direction: list[float] = [0.0, 0.0, 1.0]
    current_value: float = 0.0
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    connector_a_label: Optional[str] = None
    connector_b_label: Optional[str] = None


class MateConnectorSpec(BaseModel):
    """One side of a mate. ``position``/``normal`` are instance-LOCAL and used
    only to auto-register the connector as an InterfacePoint when one of the
    ``is_*`` flags is true (no-op if the label already exists).

    ``is_blunt_end``  — free helix endpoint (label ``end:<helix>:<bp>``).
    ``is_bend_center`` — derived center-of-curvature of a bend op (label
    ``bend_<i>_center``). Auto-registered the same way as blunt ends.
    """
    instance_id: str
    label: str
    position: list[float] = [0.0, 0.0, 0.0]
    normal: list[float] = [0.0, 0.0, 1.0]
    cluster_id: Optional[str] = None
    is_blunt_end: bool = False
    is_bend_center: bool = False


class CreateMateRequest(BaseModel):
    """Atomic mate creation: register blunt-end connectors + propagate FK to the
    aligned pose + add the joint, in ONE request.  Collapses the old
    4-round-trip frontend sequence (addConnector ×2 → propagate_fk → add_joint)
    into a single store update / undo step / feature-log entry."""
    child_connector: MateConnectorSpec
    parent_connector: Optional[MateConnectorSpec] = None   # None => World mate
    moved_instance_id: Optional[str] = None                # which instance FK moves (None => no move)
    transform: Optional[dict] = None                       # {"values": [16]} row-major, for moved instance
    name: str = "Joint"
    joint_type: str = "rigid"
    axis_origin: list[float] = [0.0, 0.0, 0.0]
    axis_direction: list[float] = [0.0, 0.0, 1.0]
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None


class PatchJointRequest(BaseModel):
    name: Optional[str] = None
    joint_type: Optional[str] = None  # changing type resets current_value to 0
    current_value: Optional[float] = None
    axis_origin: Optional[list[float]] = None
    axis_direction: Optional[list[float]] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    clear_limits: Optional[bool] = None
    angular_velocity_rpm: Optional[float] = None   # revolute only; 0 = static
    spin_paused: Optional[bool] = None             # per-joint freeze
    silent: Optional[bool] = None  # True during animation playback (suppress undo push)
    # Which body moves when driving current_value on a revolute joint: 'b' (child,
    # the default/legacy) or 'a' (parent). Set by the gizmo when the moving body
    # is the joint's parent (e.g. a pulley whose fixed axle is authored as the
    # child) so we rotate the pulley, not the fixed axle.
    endpoint_side: Optional[Literal["a", "b"]] = None


class AssemblyLoadRequest(BaseModel):
    path: str


class CreateAssemblyRequest(BaseModel):
    name: str = "Untitled"


class AssemblyImportRequest(BaseModel):
    content: str   # raw JSON string


class PatchInstanceDesignRequest(BaseModel):
    content: str  # raw Design JSON


class InstanceSeekFeaturesRequest(BaseModel):
    position: int
    sub_position: Optional[int] = None


class InstanceLoadoutCreateRequest(BaseModel):
    name: Optional[str] = None


class InstanceLoadoutRenameRequest(BaseModel):
    name: str


class RegisterLibraryRequest(BaseModel):
    path: str
    name: Optional[str] = None
    tags: list[str] = []


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


def _maybe_auto_downgrade_for_memory(assembly: Assembly) -> tuple[Assembly, Optional[str]]:
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
        if i.id in downgraded_ids else i
        for i in assembly.instances
    ]
    notice = (
        f"Auto-downgraded {len(downgraded_ids)} parts from 'full' to "
        f"'cylinders' to keep the assembly openable (over "
        f"{_AUTO_DOWNGRADE_FULL_REP_THRESHOLD} parts at 'full' would OOM). "
        f"Switch any individual part back to 'full' via its rep picker."
    )
    return assembly.model_copy(update={"instances": new_instances}), notice


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
        getattr(source, "path", None) or
        getattr(getattr(source, "design", None), "metadata", None) and source.design.metadata.name
    ) or body.name
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-add-instance",
        label=f"Add part: {inst.name}",
        params={
            "instance_id": inst.id,
            "name":        inst.name,
            "source":      body.source,
            "transform":   transform.model_dump(mode="json"),
            "source_label": src_label,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


class PropagateFKRequest(BaseModel):
    instance_id: str
    transform: dict   # {values: [16 floats], row-major}


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
        raise HTTPException(400, detail=f"Instance {instance_id} is fixed and cannot be moved")

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
    assembly = assembly_state.get_or_404()
    inst_by_id = _build_inst_by_id(assembly)
    inst = inst_by_id.get(body.instance_id)
    if not inst:
        raise HTTPException(404, detail=f"Instance {body.instance_id} not found")
    if inst.fixed:
        raise HTTPException(400, detail=f"Instance {body.instance_id} is fixed and cannot be moved")
    assembly_state.snapshot()
    _propagate_fk_inplace(assembly, body.instance_id, body.transform["values"], inst_by_id)
    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly)


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
    _design_cache: dict[str, 'Design'] = {}
    def _design_for(inst: 'PartInstance') -> 'Optional[Design]':
        try:
            key = _geo_cache_key(inst) or inst.id
            d = _design_cache.get(key)
            if d is None:
                d = _design_with_instance_overrides(inst, _assembly_source_path(assembly))
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
        assembly, inst_by_id, _design_for)

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
            base_mat   = _mat4_from_model(inst_b.base_transform)
            actual_mat = _mat4_from_model(inst_b.transform)
            if joint.joint_type == "revolute":
                expected = _apply_revolute_joint(base_mat, joint.axis_origin, joint.axis_direction, joint.current_value)
            else:
                expected = _apply_prismatic_joint(base_mat, joint.axis_direction, joint.current_value)
            disc = float(np.linalg.norm(expected[:3, 3] - actual_mat[:3, 3]))
            solve_status[joint.id] = {"satisfied": disc < 0.01, "discrepancy": disc}
            continue

        # Rigid / spherical: compare connector frames. With
        # mate_relative_transform set, both translation and rotation count
        # toward the discrepancy. Without it, fall back to position-only.
        if joint.joint_type in ("rigid", "spherical"):
            if (inst_b is None
                or not joint.instance_a_id
                or not joint.connector_a_label
                or not joint.connector_b_label):
                solve_status[joint.id] = {"satisfied": None, "discrepancy": None}
                continue
            inst_a = inst_by_id.get(joint.instance_a_id) if joint.instance_a_id else None
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
                        M = np.array(joint.mate_relative_transform, dtype=float).reshape(4, 4)
                        F_b_target = F_a @ M
                        snap_T = F_b_target @ np.linalg.inv(F_b)
                        disc_pos = float(np.linalg.norm(snap_T[:3, 3]))
                        cos_a = float(np.clip((np.trace(snap_T[:3, :3]) - 1.0) / 2.0, -1.0, 1.0))
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
                entry["satisfied"] = (disc_pos < 0.01 and disc_rot < 1e-3)
            else:
                entry["satisfied"] = disc_pos < 0.01
            solve_status[joint.id] = entry
            continue

        solve_status[joint.id] = {"satisfied": True, "discrepancy": 0.0}

    # ── BFS re-application from roots ────────────────────────────────────────
    child_ids = {j.instance_b_id for j in assembly.joints if j.instance_b_id}
    root_ids  = [i.id for i in assembly.instances if i.id not in child_ids or i.fixed]

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
                        F_a = frames_by_conn.get((inst_a_live.id, joint.connector_a_label))
                        if F_a is not None:
                            joint.axis_origin = F_a[:3, 3].tolist()
                old_T    = _mat4_from_model(inst_b.transform)
                base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
                if joint.joint_type == "revolute":
                    new_mat = _apply_revolute_joint(base_mat, joint.axis_origin, joint.axis_direction, joint.current_value)
                else:
                    new_mat = _apply_prismatic_joint(base_mat, joint.axis_direction, joint.current_value)
                inst_b.transform = _mat4_to_model(new_mat)
                try:
                    delta   = new_mat @ np.linalg.inv(old_T)
                    fk_vis: set = {child_id}
                    _fk_expand_rigid_group(assembly, child_id, delta, fk_vis, [], inst_by_id)
                    _fk_propagate(assembly, fk_vis.copy(), delta, fk_vis, inst_by_id)
                    visited.update(fk_vis)
                    for nxt in fk_vis - {child_id}:
                        if nxt not in visited:
                            queue.append(nxt)
                    # Invalidate-and-refresh cached connector world frames for
                    # every instance whose transform changed in this step.
                    for moved_id in fk_vis:
                        _refresh_connector_frames_for_instance(
                            frames_by_conn, labels_by_inst, inst_by_id,
                            moved_id, _design_for, frames_local_cache)
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
                if (joint.connector_a_label and joint.instance_a_id
                    and joint.connector_b_label):
                    inst_a_live = inst_by_id.get(joint.instance_a_id)
                    if inst_a_live:
                        snap_T: 'np.ndarray | None' = None
                        ca_world: 'np.ndarray | None' = None
                        if joint.mate_relative_transform is not None:
                            F_a = frames_by_conn.get((inst_a_live.id, joint.connector_a_label))
                            F_b = frames_by_conn.get((inst_b.id, joint.connector_b_label))
                            if F_a is not None and F_b is not None:
                                try:
                                    M = np.array(joint.mate_relative_transform, dtype=float).reshape(4, 4)
                                    F_b_target = F_a @ M
                                    snap_T = F_b_target @ np.linalg.inv(F_b)
                                    ca_world = F_a[:3, 3]
                                except np.linalg.LinAlgError:
                                    snap_T = None
                        if snap_T is None:
                            # Legacy / fallback path: translation-only snap.
                            F_a = frames_by_conn.get((inst_a_live.id, joint.connector_a_label))
                            F_b = frames_by_conn.get((inst_b.id, joint.connector_b_label))
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
                            d_rot   = float(np.linalg.norm(snap_T[:3, :3] - np.eye(3)))
                            if d_trans > 1e-6 or d_rot > 1e-6:
                                old_T = _mat4_from_model(inst_b.transform)
                                new_T = snap_T @ old_T
                                inst_b.transform = _mat4_to_model(new_T)
                                if inst_b.base_transform:
                                    inst_b.base_transform = _mat4_to_model(
                                        snap_T @ _mat4_from_model(inst_b.base_transform))
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
                                    _fk_propagate(assembly, {child_id}, snap_T, visited, inst_by_id)
                                except np.linalg.LinAlgError:
                                    pass
                                # Invalidate-and-refresh cache for inst_b plus
                                # any propagated children whose transforms
                                # changed in this step.
                                moved_ids = (visited - pre_visited) | {child_id}
                                for moved_id in moved_ids:
                                    _refresh_connector_frames_for_instance(
                                        frames_by_conn, labels_by_inst, inst_by_id,
                                        moved_id, _design_for, frames_local_cache)

            visited.add(child_id)
            queue.append(child_id)

    assembly_state.set_assembly(assembly)
    resp = _assembly_response(assembly)
    resp["solve_status"] = solve_status
    return resp


class BatchPatchItem(BaseModel):
    id: str
    transform:      Optional[dict] = None
    representation: Optional[str]  = None   # Phase-4: batch rep change
    visible:        Optional[bool] = None


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
            assembly_state.remember_instance_display(item.id, representation=item.representation)
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
    assembly: Assembly, new_instances: list[PartInstance],
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
    inst: PartInstance, values: list[float],
) -> None:
    """Apply a transform patch to an existing PartInstance in place,
    skipping per-field assignment validators.

    Accepts 12-float (compact, top 3 rows) or 16-float (row-major) input.
    """
    if len(values) == 12:
        full_values = [
            float(values[0]),  float(values[1]),  float(values[2]),  float(values[3]),
            float(values[4]),  float(values[5]),  float(values[6]),  float(values[7]),
            float(values[8]),  float(values[9]),  float(values[10]), float(values[11]),
            0.0, 0.0, 0.0, 1.0,
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
            raise HTTPException(
                404, detail=f"Instance {instance_id} not found"
            )

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
            raise HTTPException(400, detail=f"representation must be one of {_VALID_REPRESENTATIONS}")
        meta_updates["representation"] = body.representation
        assembly_state.remember_instance_display(instance_id, representation=body.representation)
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

    assembly_state.snapshot()

    if meta_updates:
        new_inst      = inst.model_copy(update=meta_updates)
        new_instances = [new_inst if i.id == instance_id else i for i in assembly.instances]
        assembly      = assembly.model_copy(update={"instances": new_instances})
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
            delta   = new_T @ np.linalg.inv(old_T)
            visited = {instance_id}
            inst_by_id = _build_inst_by_id(assembly)
            _fk_expand_rigid_group(assembly, instance_id, delta, visited, [], inst_by_id)
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
                assembly, affected, world_delta_M,
            )
            updated_joint_ids = [*updated_joint_ids, *parent_updates]
        except (np.linalg.LinAlgError, NameError):
            pass
        for jid in updated_joint_ids:
            _propagate_gear_relations_from(assembly, jid)
        # Now safe to clear base_transform — gear sync has already used it.
        inst.base_transform = None

    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/instances/{instance_id}/cluster-transform", status_code=200)
def patch_instance_cluster_transform(instance_id: str, body: PatchInstanceClusterTransformRequest) -> dict:
    """Store a part-internal cluster transform on the assembly instance.

    The source part design is not modified. If a world-space delta is supplied,
    any mated child parts attached to this instance/cluster are moved by that
    delta and their own mate descendants are propagated.
    """
    assembly = assembly_state.get_or_404()
    assembly_state.snapshot()
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

    new_inst = inst.model_copy(update={
        "cluster_transform_overrides": overrides,
        "joint_states": joint_states,
    })
    assembly.instances = [new_inst if i.id == instance_id else i for i in assembly.instances]

    if body.delta_transform is not None:
        delta = np.array(body.delta_transform["values"], dtype=float).reshape(4, 4)
        _propagate_cluster_delta_to_mates(assembly, instance_id, body.cluster_id, delta)

    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly_state.get_or_404())


def _replace_instance_design(assembly: Assembly, inst: PartInstance, design) -> tuple[Assembly, PartInstance]:
    """Persist a resolved instance design and return the updated assembly/instance."""
    if inst.source.type == "file":
        # Write back to the existing workspace file
        dest = _safe_workspace_path(inst.source.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(design.to_json(), encoding="utf-8")
        new_source = inst.source   # path unchanged; watchdog fires SSE
    else:
        # Save inline design to workspace and switch to file-backed
        safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (design.metadata.name or inst.name or "part"))
        filename  = _dedup_filename(safe_stem, ".nadoc")
        dest = _WORKSPACE_DIR / filename
        dest.write_text(design.to_json(), encoding="utf-8")
        new_source = PartSourceFile(path=filename)

    new_inst      = inst.model_copy(update={"source": new_source})
    new_instances = [new_inst if i.id == inst.id else i for i in assembly.instances]
    assembly_state.snapshot()
    updated = assembly.model_copy(update={"instances": new_instances})
    assembly_state.set_assembly_silent(updated)
    _GEO_CACHE.clear()
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
    inst     = _find_instance(assembly, instance_id)
    try:
        design = Design.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid design JSON: {exc}") from exc

    # Connector-geometry signature BEFORE the replace, so we can tell whether the
    # edit actually moved any mate connectors.
    try:
        old_design  = _load_design_from_source(inst.source, _assembly_source_path(assembly))
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

    reconciled     = reconcile_cluster_membership(before, mutated, None)
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

    pre_n  = len(pre_assembly.instances)
    post_n = len(mutated.instances)
    pre_inst_ids  = {i.id for i in pre_assembly.instances}
    post_inst_ids = {i.id for i in mutated.instances}
    # ``symmetric_difference`` already counts both adds and removes, so
    # ``instance_churn`` IS |added| + |removed|.  An earlier version added
    # ``max(0, post_n - pre_n)`` on top, which double-counted adds and
    # cut the effective threshold to ~5% for pure-add ops.
    instance_churn = len(pre_inst_ids.symmetric_difference(post_inst_ids))
    use_diff = (
        pre_n >= _DIFF_SNAPSHOT_MIN_INSTANCES
        and instance_churn <= max(1, int(_DIFF_SNAPSHOT_RATIO * max(pre_n, post_n)))
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
        pre_payload, pre_size   = assembly_state.encode_assembly_snapshot(pre_assembly)
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
    updated = mutated.model_copy(update={"feature_log": new_log, "feature_log_cursor": -1})
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
    helix_id:      str
    bp_index:      int
    direction:     Direction
    is_five_prime: bool
    neighbor_row:  int
    neighbor_col:  int
    length_bp:     int


@router.post("/assembly/instances/{instance_id}/overhang/extrude", status_code=200)
def extrude_instance_overhang(instance_id: str, body: InstanceOverhangExtrudeRequest) -> dict:
    """Create a single-stranded overhang on a PartInstance's design.

    Mirrors POST /design/overhang/extrude but operates on the instance's resolved
    design. See ``_apply_part_mutation_with_feature_log`` for the bookkeeping
    (snapshots on the part design + a metadata entry on the assembly).
    """
    from backend.core.lattice import make_overhang_extrude

    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    before   = design.model_copy(deep=True)

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
        assembly, inst, before, mutated,
        op_kind="overhang-extrude",
        part_label=f"Overhang extrude: {body.length_bp} bp",
        assembly_label=f"{inst.name}: overhang extrude ({body.length_bp} bp)",
        params=body.model_dump(mode="json"),
    )
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


class InstanceOverhangPatchRequest(BaseModel):
    sequence: Optional[str] = None
    label:    Optional[str] = None
    rotation: Optional[list[float]] = None   # unit quaternion [qx, qy, qz, qw]


@router.patch("/assembly/instances/{instance_id}/overhang/{overhang_id}", status_code=200)
def patch_instance_overhang(instance_id: str, overhang_id: str, body: InstanceOverhangPatchRequest) -> dict:
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
    inst     = _find_instance(assembly, instance_id)
    design   = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    before   = design.model_copy(deep=True)

    # Reuse the design-mode pure builder. It validates inputs and raises
    # HTTPException 404 / 409 / 422 on bad data; we let those propagate.
    crud_body = OverhangPatchRequest(**body.model_dump(exclude_unset=True))
    mutated, _spec_updates, _new_spec = _build_overhang_patch(design, overhang_id, crud_body)

    # Build a human-readable label describing what changed.
    changes = []
    if "sequence" in body.model_fields_set: changes.append("sequence")
    if body.label is not None:              changes.append("label")
    if body.rotation is not None:           changes.append("rotation")
    delta = ", ".join(changes) or "no-op"

    updated_assembly, updated_design = _apply_part_mutation_with_feature_log(
        assembly, inst, before, mutated,
        op_kind="overhang-bulk",
        part_label=f"Overhang patch: {delta}",
        assembly_label=f"{inst.name}: overhang patch ({delta})",
        params={**body.model_dump(mode="json", exclude_unset=True), "overhang_id": overhang_id},
    )
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


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
        (op.id, op.type, op.plane_a_bp, op.plane_b_bp,
         tuple(sorted(op.params.model_dump().items())))
        for op in (design.deformations or [])
    )
    loopskips = tuple(
        (h.id, tuple(tuple(sorted(ls.model_dump().items())) for ls in (h.loop_skips or [])))
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
    from backend.api.crud import _geometry_for_design, _compact_geometry_from_nucleotides
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    pre_geo_sig = _part_geometry_signature(design)

    updated_design = crud_api._seek_feature_log(design, body.position, body.sub_position)
    post_geo_sig = _part_geometry_signature(updated_design)
    updated_assembly, new_inst = _replace_instance_design(assembly, inst, updated_design)

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
    nucleotides = _geometry_for_design(display_design)
    axes = deformed_helix_axes(display_design)
    _apply_ovhg_rotations_to_axes(display_design, axes, nucleotides)
    design_dict = display_design.to_dict()
    crud_api._inject_joint_world_axes(design_dict)   # world cluster-joint axes (see get_instance_geometry)
    key = _geo_cache_key(new_inst)
    if key:
        _geo_cache_set(key, {"nucleotides": nucleotides, "helix_axes": axes,
                             "design": design_dict})

    return {
        **_assembly_response(updated_assembly),
        "design":   design_dict,
        "geometry": {
            "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
            "helix_axes":          axes,
        },
        # Path the frontend should mark as "self-saved" so the watchdog
        # SSE echo doesn't trigger a redundant invalidate+refetch.
        "source_path": inst.source.path if inst.source.type == "file" else None,
        # Mate snap report — present only when clusters actually changed
        # and resolve fired. Frontend's mate panel reads this just like a
        # manual Resolve click.
        "solve_status":   solve_status,
        "auto_resolved":  solve_status is not None,
    }


# ── Assembly-level overhang bindings ────────────────────────────────────────────

class CreateAssemblyOverhangBindingRequest(BaseModel):
    instance_a_id:    str
    sub_domain_a_id:  str
    overhang_a_id:    str
    instance_b_id:    str
    sub_domain_b_id:  str
    overhang_b_id:    str
    binding_mode:     Optional[str] = None   # 'duplex' | 'toehold'
    allow_n_wildcard: Optional[bool] = None


class PatchAssemblyOverhangBindingRequest(BaseModel):
    binding_mode:     Optional[str] = None
    allow_n_wildcard: Optional[bool] = None


class SeekAssemblyFeaturesRequest(BaseModel):
    position: int                            # log entry index; -1 = end, -2 = empty


def _validate_overhang_ref(design, sub_domain_id: str, overhang_id: str, side: str) -> None:
    """Confirm ``sub_domain_id`` lives on overhang ``overhang_id`` in ``design``."""
    ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
    if ovhg is None:
        raise HTTPException(404, detail=f"Side {side}: overhang {overhang_id!r} not found.")
    if not any(sd.id == sub_domain_id for sd in (ovhg.sub_domains or [])):
        raise HTTPException(
            404, detail=f"Side {side}: sub-domain {sub_domain_id!r} not on overhang {overhang_id!r}.")


@router.post("/assembly/overhang-bindings", status_code=200)
def create_assembly_overhang_binding(body: CreateAssemblyOverhangBindingRequest) -> dict:
    """Create a cross-part Watson-Crick binding between two overhangs."""
    from backend.core.models import AssemblyOverhangBinding

    assembly = assembly_state.get_or_404()
    inst_a   = _find_instance(assembly, body.instance_a_id)
    inst_b   = _find_instance(assembly, body.instance_b_id)
    design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
    design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))
    _validate_overhang_ref(design_a, body.sub_domain_a_id, body.overhang_a_id, "A")
    _validate_overhang_ref(design_b, body.sub_domain_b_id, body.overhang_b_id, "B")

    # Reject duplicates: same unordered pair of (instance_id, sub_domain_id).
    key_new = frozenset({
        (body.instance_a_id, body.sub_domain_a_id),
        (body.instance_b_id, body.sub_domain_b_id),
    })
    if len(key_new) < 2:
        raise HTTPException(400, detail="Cannot bind a sub-domain to itself.")
    for ex in assembly.overhang_bindings:
        key_ex = frozenset({
            (ex.instance_a_id, ex.sub_domain_a_id),
            (ex.instance_b_id, ex.sub_domain_b_id),
        })
        if key_ex == key_new:
            raise HTTPException(409, detail=f"Binding already exists ({ex.name}).")

    next_n = len(assembly.overhang_bindings) + 1
    binding_kwargs: dict = dict(
        name=f"AB{next_n}",
        instance_a_id=body.instance_a_id,
        sub_domain_a_id=body.sub_domain_a_id,
        overhang_a_id=body.overhang_a_id,
        instance_b_id=body.instance_b_id,
        sub_domain_b_id=body.sub_domain_b_id,
        overhang_b_id=body.overhang_b_id,
    )
    if body.binding_mode is not None:
        binding_kwargs["binding_mode"] = body.binding_mode
    if body.allow_n_wildcard is not None:
        binding_kwargs["allow_n_wildcard"] = body.allow_n_wildcard
    new_binding = AssemblyOverhangBinding(**binding_kwargs)

    new_bindings = list(assembly.overhang_bindings) + [new_binding]
    mutated = assembly.model_copy(update={"overhang_bindings": new_bindings})

    oh_a_name = next((o.label or o.id for o in design_a.overhangs if o.id == body.overhang_a_id), body.overhang_a_id)
    oh_b_name = next((o.label or o.id for o in design_b.overhangs if o.id == body.overhang_b_id), body.overhang_b_id)
    label = f"{new_binding.name}: {inst_a.name}.{oh_a_name} ↔ {inst_b.name}.{oh_b_name}"

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-bind",
        label=label,
        params={**body.model_dump(mode="json"), "binding_id": new_binding.id, "name": new_binding.name},
    )
    return _assembly_response(updated)


@router.patch("/assembly/overhang-bindings/{binding_id}", status_code=200)
def patch_assembly_overhang_binding(binding_id: str, body: PatchAssemblyOverhangBindingRequest) -> dict:
    """Patch ``binding_mode`` or ``allow_n_wildcard`` on a cross-part binding."""
    assembly = assembly_state.get_or_404()
    bindings = list(assembly.overhang_bindings)
    idx = next((i for i, b in enumerate(bindings) if b.id == binding_id), -1)
    if idx < 0:
        raise HTTPException(404, detail=f"AssemblyOverhangBinding {binding_id!r} not found.")

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, detail="No fields to patch.")
    bindings[idx] = bindings[idx].model_copy(update=fields)
    mutated = assembly.model_copy(update={"overhang_bindings": bindings})

    changes = ", ".join(fields.keys())
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-bind-patch",
        label=f"{bindings[idx].name}: patch ({changes})",
        params={**fields, "binding_id": binding_id},
    )
    return _assembly_response(updated)


@router.delete("/assembly/overhang-bindings/{binding_id}", status_code=200)
def delete_assembly_overhang_binding(binding_id: str) -> dict:
    """Remove a cross-part overhang binding."""
    assembly = assembly_state.get_or_404()
    target = next((b for b in assembly.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"AssemblyOverhangBinding {binding_id!r} not found.")
    new_bindings = [b for b in assembly.overhang_bindings if b.id != binding_id]
    mutated = assembly.model_copy(update={"overhang_bindings": new_bindings})

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-unbind",
        label=f"{target.name}: unbind",
        params={"binding_id": binding_id, "name": target.name},
    )
    return _assembly_response(updated)


# ── Assembly-level overhang connections (cross-part linkers) ────────────────────

class CreateAssemblyOverhangConnectionRequest(BaseModel):
    name:              Optional[str] = None
    instance_a_id:     str
    overhang_a_id:     str
    overhang_a_attach: str   # 'root' | 'free_end'
    instance_b_id:     str
    overhang_b_id:     str
    overhang_b_attach: str
    linker_type:       str   # 'ss' | 'ds'
    length_value:      float
    length_unit:       str   # 'bp' | 'nm'
    bridge_sequence:   Optional[str] = None


class PatchAssemblyOverhangConnectionRequest(BaseModel):
    name:              Optional[str]   = None
    overhang_a_attach: Optional[str]   = None
    overhang_b_attach: Optional[str]   = None
    linker_type:       Optional[str]   = None
    length_value:      Optional[float] = None
    length_unit:       Optional[str]   = None
    bridge_sequence:   Optional[str]   = None


class RelaxAssemblyLinkerRequest(BaseModel):
    """Body for the cross-part linker relax. Empty today (the placement is
    deterministic); kept for forward-compat (e.g. an explicit movable side)."""
    pass


def _validate_overhang_in_instance(design, overhang_id: str, side: str) -> None:
    if not any(o.id == overhang_id for o in (design.overhangs or [])):
        raise HTTPException(404, detail=f"Side {side}: overhang {overhang_id!r} not found.")


def _check_polarity_allowed(type_id: str, end_a: str, end_b: str) -> bool:
    """Mirror the frontend's _ctIsForbidden rule set, server-side.

    end_a / end_b are '5p' or '3p' (the overhang free-end polarity, derived
    from the overhang id suffix). Returns False (= forbidden) for the same
    combinations the frontend rejects so the two layers stay in sync.
    """
    # Derive from canonical type id.
    if type_id in ('end-to-root',):
        return end_a == end_b
    if type_id in ('root-to-root',):
        return end_a != end_b
    if type_id in ('root-to-root-dsdna-linker', 'end-to-end-dsdna-linker'):
        return end_a == end_b
    if type_id in ('root-to-root-ssdna-linker', 'end-to-end-ssdna-linker',
                   'root-to-root-indirect',    'end-to-end-indirect'):
        return end_a != end_b
    if type_id in ('end-to-root-dsdna-linker', 'root-to-end-dsdna-linker'):
        return end_a != end_b
    if type_id in ('end-to-root-ssdna-linker', 'root-to-end-ssdna-linker'):
        return end_a == end_b
    return True


def _overhang_polarity(overhang_id: str) -> Optional[str]:
    """Recover '5p' / '3p' suffix from the canonical overhang id, e.g.
    ``ovhg_<helix>_<bp>_5p``. Returns None when no suffix is present."""
    if overhang_id.endswith('_5p'): return '5p'
    if overhang_id.endswith('_3p'): return '3p'
    return None


def _variant_id_for(linker_type: str, attach_a: str, attach_b: str) -> Optional[str]:
    """Reconstruct the CT variant id from (linker_type, attach_a, attach_b).

    Used only for server-side polarity rule lookup — mirrors the frontend's
    `_ctAttachPair` inverse plus the type family. Returns None for direct
    connections (which the assembly path does not create — those go through
    AssemblyOverhangBinding).
    """
    if linker_type not in ('ss', 'ds'):
        return None
    family = 'ssdna' if linker_type == 'ss' else 'dsdna'
    if   attach_a == 'free_end' and attach_b == 'root':     return f'end-to-root-{family}-linker'
    elif attach_a == 'root'     and attach_b == 'free_end': return f'root-to-end-{family}-linker'
    elif attach_a == 'root'     and attach_b == 'root':     return f'root-to-root-{family}-linker'
    elif attach_a == 'free_end' and attach_b == 'free_end': return f'end-to-end-{family}-linker'
    return None


@router.post("/assembly/overhang-connections", status_code=200)
def create_assembly_overhang_connection(body: CreateAssemblyOverhangConnectionRequest) -> dict:
    """Create a cross-part linker between two overhangs on different parts."""
    from backend.core.models import AssemblyOverhangConnection

    if body.overhang_a_attach not in ('root', 'free_end'):
        raise HTTPException(400, detail=f"overhang_a_attach must be 'root' or 'free_end' (got {body.overhang_a_attach!r}).")
    if body.overhang_b_attach not in ('root', 'free_end'):
        raise HTTPException(400, detail=f"overhang_b_attach must be 'root' or 'free_end' (got {body.overhang_b_attach!r}).")
    if body.linker_type not in ('ss', 'ds'):
        raise HTTPException(400, detail=f"linker_type must be 'ss' or 'ds' (got {body.linker_type!r}).")
    if body.length_unit not in ('bp', 'nm'):
        raise HTTPException(400, detail=f"length_unit must be 'bp' or 'nm' (got {body.length_unit!r}).")
    # Allow 0 for indirect variants (shared-linker strand has no user-set length).
    if body.length_value < 0:
        raise HTTPException(400, detail="length_value must be non-negative.")

    assembly = assembly_state.get_or_404()
    inst_a   = _find_instance(assembly, body.instance_a_id)
    inst_b   = _find_instance(assembly, body.instance_b_id)
    design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
    design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))
    _validate_overhang_in_instance(design_a, body.overhang_a_id, "A")
    _validate_overhang_in_instance(design_b, body.overhang_b_id, "B")

    # Polarity rule: reject combinations the frontend would mark forbidden,
    # so a misconfigured client can't sneak invalid linkers past the UI.
    pa = _overhang_polarity(body.overhang_a_id)
    pb = _overhang_polarity(body.overhang_b_id)
    variant = _variant_id_for(body.linker_type, body.overhang_a_attach, body.overhang_b_attach)
    if pa and pb and variant and not _check_polarity_allowed(variant, pa, pb):
        raise HTTPException(
            422,
            detail=f"Polarity {pa}/{pb} is forbidden for {variant} (server polarity rule).",
        )

    next_n = len(assembly.overhang_connections) + 1
    new_conn = AssemblyOverhangConnection(
        name=body.name or f"AL{next_n}",
        instance_a_id=body.instance_a_id,
        overhang_a_id=body.overhang_a_id,
        overhang_a_attach=body.overhang_a_attach,
        instance_b_id=body.instance_b_id,
        overhang_b_id=body.overhang_b_id,
        overhang_b_attach=body.overhang_b_attach,
        linker_type=body.linker_type,
        length_value=body.length_value,
        length_unit=body.length_unit,
        bridge_sequence=body.bridge_sequence,
    )
    new_list = list(assembly.overhang_connections) + [new_conn]

    # Materialise the cross-part linker topology (complement strands + virtual
    # __lnk__ helix + bridge strand) into the assembly so the linker is
    # visible in the 3D workspace and shows up as new rows in the strand
    # spreadsheet.
    from backend.core.assembly_linker import generate_assembly_linker_topology
    new_helices, new_strands = generate_assembly_linker_topology(
        new_conn, inst_a, inst_b, design_a, design_b,
    )
    mutated = assembly.model_copy(update={
        "overhang_connections": new_list,
        "assembly_helices":     list(assembly.assembly_helices) + new_helices,
        "assembly_strands":     list(assembly.assembly_strands) + new_strands,
    })

    oh_a_name = next((o.label or o.id for o in design_a.overhangs if o.id == body.overhang_a_id), body.overhang_a_id)
    oh_b_name = next((o.label or o.id for o in design_b.overhangs if o.id == body.overhang_b_id), body.overhang_b_id)
    label = f"{new_conn.name}: {inst_a.name}.{oh_a_name} ↔ {inst_b.name}.{oh_b_name} ({body.linker_type}, {body.length_value:g} {body.length_unit})"

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-add",
        label=label,
        params={**body.model_dump(mode="json"), "connection_id": new_conn.id, "name": new_conn.name},
    )
    return _assembly_response(updated)


@router.patch("/assembly/overhang-connections/{connection_id}", status_code=200)
def patch_assembly_overhang_connection(connection_id: str, body: PatchAssemblyOverhangConnectionRequest) -> dict:
    """Patch a cross-part overhang connection."""
    assembly = assembly_state.get_or_404()
    conns = list(assembly.overhang_connections)
    idx = next((i for i, c in enumerate(conns) if c.id == connection_id), -1)
    if idx < 0:
        raise HTTPException(404, detail=f"AssemblyOverhangConnection {connection_id!r} not found.")

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, detail="No fields to patch.")

    # Validate enum-like values when present.
    if fields.get("overhang_a_attach") not in (None, "root", "free_end"):
        raise HTTPException(400, detail="overhang_a_attach must be 'root' or 'free_end'.")
    if fields.get("overhang_b_attach") not in (None, "root", "free_end"):
        raise HTTPException(400, detail="overhang_b_attach must be 'root' or 'free_end'.")
    if fields.get("linker_type") not in (None, "ss", "ds"):
        raise HTTPException(400, detail="linker_type must be 'ss' or 'ds'.")
    if fields.get("length_unit") not in (None, "bp", "nm"):
        raise HTTPException(400, detail="length_unit must be 'bp' or 'nm'.")
    if "length_value" in fields and fields["length_value"] is not None and fields["length_value"] < 0:
        raise HTTPException(400, detail="length_value must be non-negative.")

    old_conn  = conns[idx]
    new_conn  = old_conn.model_copy(update=fields)
    conns[idx] = new_conn

    # Decide what to do with the linker topology depending on which fields
    # changed:
    #   length_value / length_unit / linker_type — regenerate from scratch.
    #   bridge_sequence (only) — keep topology, only recompose strand .sequence.
    #   anything else (attach, name) — leave the existing strands alone.
    topology_changing = {"length_value", "length_unit", "linker_type",
                          "overhang_a_attach", "overhang_b_attach"}
    helices = list(assembly.assembly_helices)
    strands = list(assembly.assembly_strands)
    if any(f in fields for f in topology_changing):
        from backend.core.assembly_linker import (
            generate_assembly_linker_topology,
            remove_assembly_linker_topology,
        )
        helices, strands = remove_assembly_linker_topology(helices, strands, connection_id)
        inst_a   = _find_instance(assembly, new_conn.instance_a_id)
        inst_b   = _find_instance(assembly, new_conn.instance_b_id)
        design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
        design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))
        add_h, add_s = generate_assembly_linker_topology(
            new_conn, inst_a, inst_b, design_a, design_b,
        )
        helices = helices + add_h
        strands = strands + add_s
    elif "bridge_sequence" in fields:
        from backend.core.assembly_linker import recompose_strand_sequences_for_connection
        inst_a   = _find_instance(assembly, new_conn.instance_a_id)
        inst_b   = _find_instance(assembly, new_conn.instance_b_id)
        design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
        design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))
        strands = recompose_strand_sequences_for_connection(
            new_conn, inst_a, inst_b, design_a, design_b, strands,
        )

    mutated = assembly.model_copy(update={
        "overhang_connections": conns,
        "assembly_helices":     helices,
        "assembly_strands":     strands,
    })

    changes = ", ".join(fields.keys())
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-patch",
        label=f"{conns[idx].name}: patch ({changes})",
        params={**fields, "connection_id": connection_id},
    )
    return _assembly_response(updated)


@router.delete("/assembly/overhang-connections/{connection_id}", status_code=200)
def delete_assembly_overhang_connection(connection_id: str) -> dict:
    """Remove a cross-part overhang connection."""
    assembly = assembly_state.get_or_404()
    target = next((c for c in assembly.overhang_connections if c.id == connection_id), None)
    if target is None:
        raise HTTPException(404, detail=f"AssemblyOverhangConnection {connection_id!r} not found.")
    new_list = [c for c in assembly.overhang_connections if c.id != connection_id]

    from backend.core.assembly_linker import remove_assembly_linker_topology
    new_helices, new_strands = remove_assembly_linker_topology(
        list(assembly.assembly_helices),
        list(assembly.assembly_strands),
        connection_id,
    )
    mutated = assembly.model_copy(update={
        "overhang_connections": new_list,
        "assembly_helices":     new_helices,
        "assembly_strands":     new_strands,
    })

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-delete",
        label=f"{target.name}: delete linker",
        params={"connection_id": connection_id, "name": target.name},
    )
    return _assembly_response(updated)


def _find_assembly_connection(assembly: Assembly, connection_id: str):
    conn = next((c for c in assembly.overhang_connections if c.id == connection_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"AssemblyOverhangConnection {connection_id!r} not found.")
    return conn


@router.get("/assembly/overhang-connections/{connection_id}/relax-status", status_code=200)
def assembly_overhang_connection_relax_status(connection_id: str) -> dict:
    """Whether a cross-part linker can be rigid-place relaxed (gates the UI button)."""
    from backend.core.assembly_linker_relax import assembly_relax_status

    assembly = assembly_state.get_or_404()
    conn     = _find_assembly_connection(assembly, connection_id)
    inst_a   = _find_instance(assembly, conn.instance_a_id)
    inst_b   = _find_instance(assembly, conn.instance_b_id)
    return assembly_relax_status(assembly, conn, inst_a, inst_b)


@router.post("/assembly/overhang-connections/{connection_id}/relax", status_code=200)
def relax_assembly_overhang_connection(
    connection_id: str,
    body: Optional[RelaxAssemblyLinkerRequest] = None,
) -> dict:
    """Rigidly move the free part so the ds linker becomes a coaxial native-length duplex.

    Holds one part fixed (per ``assembly_relax_status``) and rigid-places the
    other; then re-materializes the now-stale bridge from the moved world
    anchors. Single undoable feature-log entry.
    """
    from backend.core.assembly_linker_relax import (
        assembly_relax_status,
        relax_assembly_linker,
    )
    from backend.core.assembly_linker import (
        generate_assembly_linker_topology,
        remove_assembly_linker_topology,
    )

    assembly = assembly_state.get_or_404()
    conn     = _find_assembly_connection(assembly, connection_id)
    inst_a   = _find_instance(assembly, conn.instance_a_id)
    inst_b   = _find_instance(assembly, conn.instance_b_id)
    design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
    design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))

    status = assembly_relax_status(assembly, conn, inst_a, inst_b)
    if not status["available"]:
        raise HTTPException(400, detail=status["reason"])

    moved_id   = status["movable_instance_id"]
    inst_moved = inst_a if moved_id == inst_a.id else inst_b

    # Zero-length INDIRECT ss linker: no bridge — a single complement↔complement
    # arc. Collapse it with ONE translation of the moved part. The indirect
    # strand topology is unchanged (its complement beads follow the moved part on
    # re-emission), so we only move the part and commit.
    if conn.length_value == 0:
        from backend.core.assembly_linker_relax import relax_assembly_indirect_linker
        nucs = _linker_geometry_for_assembly(assembly).get("nucleotides", [])
        try:
            new_T, info = relax_assembly_indirect_linker(
                conn, nucs, assembly.assembly_strands, inst_moved,
                movable_instance_id=moved_id,
                fixed_instance_id=status["fixed_instance_id"],
            )
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        working = assembly.model_copy(deep=True)
        inst_by_id = _build_inst_by_id(working)
        _propagate_fk_inplace(working, moved_id, new_T, inst_by_id)
        updated = _apply_assembly_mutation_with_feature_log(
            working,
            op_kind="assembly-overhang-connection-relax",
            label=f"{conn.name}: relax linker",
            params={"connection_id": connection_id, **info},
        )
        payload = _assembly_response(updated)
        payload["relax_info"] = info
        return payload

    bridge_helix_id = f"__lnk__{conn.id}"

    # Generate a fresh bridge from the CURRENT anchors and EMIT it (same pipeline
    # the renderer uses), so the relax minimizes the actual 3D backbone-bead
    # coordinates the user sees — not a re-derived approximation.
    base_h, base_s = remove_assembly_linker_topology(
        list(assembly.assembly_helices), list(assembly.assembly_strands), connection_id,
    )
    add_h, add_s = generate_assembly_linker_topology(conn, inst_a, inst_b, design_a, design_b)
    fresh = assembly.model_copy(update={
        "assembly_helices": base_h + add_h,
        "assembly_strands": base_s + add_s,
    })
    nucs = _linker_geometry_for_assembly(fresh).get("nucleotides", [])

    moved_id   = status["movable_instance_id"]
    inst_moved = inst_a if moved_id == inst_a.id else inst_b

    # Two-translation, rotation-free relax on the emitted beads. Returns the
    # moved part's pure translation + the bridge-helix translation (T1).
    try:
        new_T, t1, info = relax_assembly_linker(
            conn, nucs, fresh.assembly_strands, inst_moved,
            movable_instance_id=moved_id,
            fixed_instance_id=status["fixed_instance_id"],
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    # Work on a deep copy so the live assembly stays as the feature-log pre-state.
    working = assembly.model_copy(deep=True)
    inst_by_id = _build_inst_by_id(working)
    _propagate_fk_inplace(working, moved_id, new_T, inst_by_id)

    # Commit the fresh bridge with its __lnk__ helix slid onto the fixed overhang
    # (T1). Do NOT regenerate from the moved pose — that would re-center the
    # bridge and undo T1. The complement strands reference the parts' helices, so
    # they follow the (now-moved) parts on their own.
    t1v = np.asarray(t1, dtype=float)
    bridge_helices = []
    for h in add_h:
        if h.id == bridge_helix_id:
            ws = h.axis_start.to_array() + t1v
            we = h.axis_end.to_array() + t1v
            bridge_helices.append(h.model_copy(update={
                "axis_start": Vec3.from_array(ws),
                "axis_end":   Vec3.from_array(we),
            }))
        else:
            bridge_helices.append(h)
    helices, strands = remove_assembly_linker_topology(
        list(working.assembly_helices), list(working.assembly_strands), connection_id,
    )
    mutated = working.model_copy(update={
        "assembly_helices": helices + bridge_helices,
        "assembly_strands": strands + add_s,
    })

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-relax",
        label=f"{conn.name}: relax linker",
        params={"connection_id": connection_id, **info},
    )
    payload = _assembly_response(updated)
    payload["relax_info"] = info
    return payload


def _materialize_post_state(full_log: list, target_idx: int, current: Assembly) -> Optional[Assembly]:
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


def _materialize_pre_state(full_log: list, target_idx: int, current: Assembly) -> Optional[Assembly]:
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
    log_len  = len(full_log)

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
            merged = {**fallback_overrides.get(i.id, {}), **persistent_overrides.get(i.id, {})}
            restored_instances.append(i.model_copy(update=merged) if merged else i)

    # Restore the full feature_log onto the decoded state; only geometry
    # (instances, joints, assembly_helices/strands, overhang_*) was
    # supposed to vary with seek.
    final = new_state.model_copy(update={
        "instances":          restored_instances,
        "feature_log":        full_log,
        "feature_log_cursor": new_cursor,
    })
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
    if op_kind == "assembly-polymerize":
        # Delegate to the actual route so all the chain math + pattern-mate
        # replication stays in one place. The route reads from
        # assembly_state; temporarily install the input assembly, invoke,
        # then strip the entry the route appends (the caller will append
        # a fresh one).
        joint_id  = params.get("joint_id")
        count     = int(params.get("count", 0))
        direction = params.get("direction", "forward")
        if not joint_id or count < 2 or direction not in ("forward", "backward", "both"):
            raise HTTPException(400, detail="polymerize params malformed.")
        if count == 2:
            return assembly

        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            body = PolymerizeAssemblyRequest(
                joint_id=joint_id, count=count, direction=direction,
                additional_instance_ids=list(params.get("additional_instance_ids") or []),
            )
            polymerize_assembly(body)
            result = assembly_state.get_or_404()
            result = result.model_copy(update={
                "feature_log":        result.feature_log[:len(assembly.feature_log)],
                "feature_log_cursor": -1,
            })
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-polymerize-periodic":
        # Delegate to the route (single source of truth for the chain math),
        # then strip the entry it appends so the caller can append a fresh one.
        instance_id = params.get("instance_id")
        count       = int(params.get("count", 0))
        direction   = params.get("direction", "forward")
        if not instance_id or count < 2 or direction not in ("forward", "backward", "both"):
            raise HTTPException(400, detail="polymerize-periodic params malformed.")

        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            body = PolymerizePeriodicRequest(
                instance_id=instance_id, count=count, direction=direction,
            )
            polymerize_periodic_assembly(body)
            result = assembly_state.get_or_404()
            result = result.model_copy(update={
                "feature_log":        result.feature_log[:len(assembly.feature_log)],
                "feature_log_cursor": -1,
            })
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-overhang-connection-add":
        # Re-run by constructing a CreateAssemblyOverhangConnectionRequest and
        # delegating to the existing route logic. The route reads from
        # assembly_state, so we temporarily install the target assembly,
        # invoke, then capture the result.
        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            body = CreateAssemblyOverhangConnectionRequest(**{
                k: v for k, v in params.items()
                if k in CreateAssemblyOverhangConnectionRequest.model_fields
            })
            create_assembly_overhang_connection(body)
            result = assembly_state.get_or_404()
            # The route appended its own feature_log entry; strip it since
            # the caller will append a fresh entry for the edit.
            result = result.model_copy(update={
                "feature_log": result.feature_log[:len(assembly.feature_log)],
                "feature_log_cursor": -1,
            })
        finally:
            assembly_state.set_assembly_silent(previous)
        return result

    if op_kind == "assembly-overhang-connection-patch":
        connection_id = params.get("connection_id")
        if not connection_id:
            raise HTTPException(400, detail="connection_id missing from patch params.")
        previous = assembly_state.get_or_404()
        assembly_state.set_assembly_silent(assembly)
        try:
            fields = {k: v for k, v in params.items() if k != "connection_id"}
            body = PatchAssemblyOverhangConnectionRequest(**{
                k: v for k, v in fields.items()
                if k in PatchAssemblyOverhangConnectionRequest.model_fields
            })
            patch_assembly_overhang_connection(connection_id, body)
            result = assembly_state.get_or_404()
            result = result.model_copy(update={
                "feature_log": result.feature_log[:len(assembly.feature_log)],
                "feature_log_cursor": -1,
            })
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
            raise HTTPException(400, detail=f"add-instance replay: invalid source: {exc}") from exc
        t_data = params.get("transform")
        transform = Mat4x4.model_validate(t_data) if t_data else Mat4x4()
        # Preserve the original id so later ops referencing it still resolve.
        inst = PartInstance(
            id=params.get("instance_id") or str(_uuid.uuid4()),
            name=params.get("name") or "Part",
            source=source,
            transform=transform,
        )
        return assembly.model_copy(update={
            "instances": list(assembly.instances) + [inst],
        })

    if op_kind == "assembly-delete-instance":
        instance_id = params.get("instance_id")
        if not instance_id:
            raise HTTPException(400, detail="delete-instance replay: instance_id missing.")
        new_instances = [i for i in assembly.instances if i.id != instance_id]
        new_joints    = [j for j in assembly.joints
                         if j.instance_a_id != instance_id and j.instance_b_id != instance_id]
        return assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    if op_kind == "assembly-duplicate-instance":
        src_id = params.get("source_instance_id")
        new_id = params.get("new_instance_id")
        if not src_id or not new_id:
            raise HTTPException(400, detail="duplicate-instance replay: source/new id missing.")
        src = next((i for i in assembly.instances if i.id == src_id), None)
        if src is None:
            raise HTTPException(422, detail=f"duplicate-instance replay: source instance {src_id} no longer exists.")
        offset = list(params.get("offset") or [5.0, 0.0, 0.0])
        new_T_arr = src.transform.to_array().copy()
        if len(offset) >= 3:
            new_T_arr[0, 3] += float(offset[0])
            new_T_arr[1, 3] += float(offset[1])
            new_T_arr[2, 3] += float(offset[2])
        new_inst = src.model_copy(deep=True, update={
            "id":             new_id,
            "name":           params.get("name") or f"{src.name} (copy)",
            "transform":      Mat4x4.from_array(new_T_arr),
            "base_transform": None,
        })
        return assembly.model_copy(update={
            "instances": list(assembly.instances) + [new_inst],
        })

    if op_kind == "assembly-add-connector":
        instance_id = params.get("instance_id")
        label       = params.get("label")
        if not instance_id or not label:
            raise HTTPException(400, detail="add-connector replay: instance_id/label missing.")
        pos = params.get("position") or [0.0, 0.0, 0.0]
        nrm = params.get("normal")   or [0.0, 0.0, 1.0]
        ip = InterfacePoint(
            label=label,
            position=Vec3(x=float(pos[0]), y=float(pos[1]), z=float(pos[2])),
            normal=Vec3(x=float(nrm[0]), y=float(nrm[1]), z=float(nrm[2])),
            connection_type=ConnectionType.COVALENT,
            cluster_id=params.get("cluster_id"),
        )
        return assembly.model_copy(update={
            "instances": [
                i.model_copy(update={"interface_points": [*i.interface_points, ip]})
                if i.id == instance_id else i
                for i in assembly.instances
            ],
        })

    if op_kind == "assembly-delete-connector":
        instance_id = params.get("instance_id")
        label       = params.get("label")
        if not instance_id or not label:
            raise HTTPException(400, detail="delete-connector replay: instance_id/label missing.")
        return assembly.model_copy(update={
            "instances": [
                i.model_copy(update={
                    "interface_points": [ip for ip in i.interface_points if ip.label != label],
                }) if i.id == instance_id else i
                for i in assembly.instances
            ],
        })

    if op_kind == "assembly-add-joint":
        # Reconstruct the joint directly from stored params, preserving its id.
        joint_id = params.get("joint_id")
        instance_b_id = params.get("instance_b_id")
        if not joint_id or not instance_b_id:
            raise HTTPException(400, detail="add-joint replay: joint_id/instance_b_id missing.")
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
        return assembly.model_copy(update={
            "joints": list(assembly.joints) + [joint],
        })

    if op_kind == "assembly-delete-joint":
        joint_id = params.get("joint_id")
        if not joint_id:
            raise HTTPException(400, detail="delete-joint replay: joint_id missing.")
        return assembly.model_copy(update={
            "joints": [j for j in assembly.joints if j.id != joint_id],
        })

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
    pre_assembly = pre_assembly.model_copy(update={
        "feature_log":        list(assembly.feature_log[:index]),
        "feature_log_cursor": -1,
    })
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
    later_entries = list(assembly.feature_log[index + 1:])

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
    prev_state = pre_assembly.model_copy(update={
        "feature_log":        base_log,
        "feature_log_cursor": -1,
    })
    for ent in later_entries:
        replayed = _replay_assembly_op(prev_state, ent.op_kind, ent.params)
        # Pre-state for this re-recorded entry = the state immediately
        # before re-applying the op (= prev_state); post-state = result of
        # the replay. Encode each so the new entry still supports per-entry
        # actions later.
        pre_b64,  pre_size  = assembly_state.encode_assembly_snapshot(prev_state)
        post_b64, post_size = assembly_state.encode_assembly_snapshot(replayed)
        replayed_entry = ent.model_copy(update={
            "design_snapshot_gz_b64":   pre_b64,
            "snapshot_size_bytes":      pre_size,
            "post_state_gz_b64":        post_b64,
            "post_state_size_bytes":    post_size,
            "evicted":                  False,
            # Re-recorded as legacy full-snapshot — clear any diff / skip-pre
            # flags inherited from the original entry so navigation reads it
            # as the full snapshot it now is.
            "diff_added_b64":           "",
            "diff_removed_ids":         [],
            "diff_modified_b64":        "",
            "pre_state_from_previous":  False,
        })
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
    pre_assembly = pre_assembly.model_copy(update={
        "feature_log":        list(assembly.feature_log[:index]),
        "feature_log_cursor": -1,
    })

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


@router.post("/assembly/instances/{instance_id}/loadouts", status_code=200)
def create_instance_loadout(instance_id: str, body: InstanceLoadoutCreateRequest) -> dict:
    from backend.api import crud as crud_api
    from backend.core.models import DesignLoadout

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    current = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(current)
    loadouts = crud_api._save_active_loadout_snapshot(current, loadouts, active_id)
    n = len(loadouts) + 1
    name = (body.name or "").strip() or f"Loadout {n}"
    new_id = str(_uuid.uuid4())
    payload, size = crud_api._encode_loadout_design_snapshot(current)
    loadouts.append(DesignLoadout(
        id=new_id,
        name=name,
        design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size,
    ))
    updated_design = current.copy_with(loadouts=loadouts, active_loadout_id=new_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


@router.post("/assembly/instances/{instance_id}/loadouts/{loadout_id}/select", status_code=200)
def select_instance_loadout(instance_id: str, loadout_id: str) -> dict:
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    current = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(current)
    loadouts = crud_api._save_active_loadout_snapshot(current, loadouts, active_id)
    selected = next((l for l in loadouts if l.id == loadout_id), None)
    if selected is None:
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    try:
        restored = crud_api._decode_loadout_design_snapshot(selected.design_snapshot_gz_b64)
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to restore loadout: {exc}") from exc
    updated_design = restored.copy_with(loadouts=loadouts, active_loadout_id=loadout_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


@router.patch("/assembly/instances/{instance_id}/loadouts/{loadout_id}", status_code=200)
def rename_instance_loadout(instance_id: str, loadout_id: str, body: InstanceLoadoutRenameRequest) -> dict:
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(design)
    if loadout_id == "__implicit_loadout_1__":
        loadout_id = active_id
    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail="Loadout name cannot be empty.")
    if not any(l.id == loadout_id for l in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    loadouts = [
        l.model_copy(update={"name": name}) if l.id == loadout_id else l
        for l in loadouts
    ]
    updated_design = design.copy_with(loadouts=loadouts, active_loadout_id=active_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


@router.delete("/assembly/instances/{instance_id}/loadouts/{loadout_id}", status_code=200)
def delete_instance_loadout(instance_id: str, loadout_id: str) -> dict:
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    current = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(current)
    if len(loadouts) <= 1:
        raise HTTPException(400, detail="Cannot delete the only loadout.")
    if not any(l.id == loadout_id for l in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    loadouts = crud_api._save_active_loadout_snapshot(current, loadouts, active_id)
    remaining = [l for l in loadouts if l.id != loadout_id]
    next_id = active_id if active_id != loadout_id else remaining[0].id
    if next_id == active_id:
        updated_design = current.copy_with(loadouts=remaining, active_loadout_id=next_id)
    else:
        try:
            restored = crud_api._decode_loadout_design_snapshot(remaining[0].design_snapshot_gz_b64)
        except Exception as exc:
            raise HTTPException(500, detail=f"Failed to restore next loadout: {exc}") from exc
        updated_design = restored.copy_with(loadouts=remaining, active_loadout_id=next_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


class DuplicateInstanceRequest(BaseModel):
    """Optional knobs for /assembly/instances/{id}/duplicate.

    The new instance inherits source + interface_points + representation/mode
    from the source instance; its transform is the source transform plus a
    user-controllable translational offset (default: +5 nm along world +X so
    the clone is visible next to the original)."""
    offset: list[float] = [5.0, 0.0, 0.0]
    name:   Optional[str] = None


@router.post("/assembly/instances/{instance_id}/duplicate", status_code=200)
def duplicate_instance(instance_id: str, body: DuplicateInstanceRequest = DuplicateInstanceRequest()) -> dict:
    """Create a copy of a PartInstance: same source, same connectors, slightly
    offset transform so the clone is visible next to the original.

    Connectors are deep-copied so the clone is immediately mateable on the
    same labels as the source.
    """
    assembly = assembly_state.get_or_404()
    src      = _find_instance(assembly, instance_id)

    new_T_arr = src.transform.to_array().copy()
    if len(body.offset) >= 3:
        new_T_arr[0, 3] += float(body.offset[0])
        new_T_arr[1, 3] += float(body.offset[1])
        new_T_arr[2, 3] += float(body.offset[2])

    new_inst = src.model_copy(deep=True, update={
        "id":             str(_uuid.uuid4()),
        "name":           body.name or f"{src.name} (copy)",
        "transform":      Mat4x4.from_array(new_T_arr),
        "base_transform": None,
    })
    new_instances = list(assembly.instances) + [new_inst]
    mutated = assembly.model_copy(update={"instances": new_instances})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplicate-instance",
        label=f"Duplicate part: {src.name} → {new_inst.name}",
        params={
            "source_instance_id": instance_id,
            "new_instance_id":    new_inst.id,
            "offset":             list(body.offset),
            "name":               new_inst.name,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/instances/{instance_id}", status_code=200)
def delete_instance(instance_id: str) -> dict:
    """Remove a PartInstance and any joints that reference it."""
    assembly = assembly_state.get_or_404()
    target   = _find_instance(assembly, instance_id)

    new_instances = [i for i in assembly.instances if i.id != instance_id]
    new_joints    = [j for j in assembly.joints
                     if j.instance_a_id != instance_id and j.instance_b_id != instance_id]
    new_groups    = _ag.filter_groups_after_instance_removal(
        list(assembly.groups), {instance_id},
    )
    mutated = assembly.model_copy(update={
        "instances": new_instances,
        "joints":    new_joints,
        "groups":    new_groups,
    })

    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-instance",
        label=f"Delete part: {target.name}",
        params={"instance_id": instance_id, "name": target.name},
    )
    assembly_state.forget_instance_display(instance_id)
    return _assembly_response(assembly_state.get_or_404())


# ── Joint routes ──────────────────────────────────────────────────────────────

def _compose_add_joint(
    assembly: Assembly, body: AddJointRequest,
) -> tuple[Assembly, AssemblyJoint, str, dict]:
    """Build the assembly state for a new joint: derive axis_origin, snap
    instance_b to connector_a, snapshot base_transform, capture
    mate_relative_transform, and propagate the snap to non-rigid children.

    Returns ``(new_assembly, joint, feature_log_label, feature_log_params)``.
    Pure w.r.t. ``assembly_state`` — the caller persists via
    ``_apply_assembly_mutation_with_feature_log``.  Shared by ``add_joint``
    and the atomic ``create_mate`` endpoint.
    """
    _find_instance(assembly, body.instance_b_id)
    if body.instance_a_id is not None:
        _find_instance(assembly, body.instance_a_id)

    # Derive axis_origin from connector positions (safety net — frontend pre-aligns,
    # but the backend recomputes to guarantee connector coincidence at creation time).
    axis_origin = list(body.axis_origin)
    snap_delta: 'np.ndarray | None' = None

    inst_b = _find_instance(assembly, body.instance_b_id)
    cluster_id_a = body.cluster_id_a
    cluster_id_b = body.cluster_id_b
    # Snap + axis_origin go through _get_connector_world so the snap math
    # uses LIVE cluster-aware connector positions (for blunt-end labels,
    # pulled fresh from helix geometry; for manual connectors,
    # T_inst @ ip.position). Keeps add_joint, resolve, and the highlight
    # markers all on the same definition of "where the connector is."
    asm_path = _assembly_source_path(assembly)
    if body.connector_b_label:
        ip_b = next((p for p in inst_b.interface_points if p.label == body.connector_b_label), None)
        if ip_b is not None:
            if cluster_id_b is None:
                cluster_id_b = (_infer_cluster_ids_for_connector_label(inst_b, body.connector_b_label) or [ip_b.cluster_id])[0]
            design_b = _design_with_instance_overrides(inst_b, asm_path)
            cb_world = _get_connector_world(inst_b, body.connector_b_label, design_b)
            if cb_world is None:
                cb_world = np.zeros(3, dtype=float)
            if body.connector_a_label and body.instance_a_id:
                inst_a = _find_instance(assembly, body.instance_a_id)
                ip_a   = next((p for p in inst_a.interface_points
                               if p.label == body.connector_a_label), None)
                if ip_a is not None:
                    if cluster_id_a is None:
                        cluster_id_a = (_infer_cluster_ids_for_connector_label(inst_a, body.connector_a_label) or [ip_a.cluster_id])[0]
                    design_a = _design_with_instance_overrides(inst_a, asm_path)
                    ca_world = _get_connector_world(inst_a, body.connector_a_label, design_a)
                    if ca_world is None:
                        ca_world = np.zeros(3, dtype=float)
                    snap = ca_world - cb_world
                    if np.linalg.norm(snap) > 1e-6:
                        snap_delta = np.eye(4, dtype=float)
                        snap_delta[:3, 3] = snap
                    axis_origin = ca_world.tolist()
                else:
                    axis_origin = cb_world.tolist()
            else:
                axis_origin = cb_world.tolist()

    joint = AssemblyJoint(
        name=body.name,
        joint_type=body.joint_type,
        instance_a_id=body.instance_a_id,
        cluster_id_a=cluster_id_a,
        instance_b_id=body.instance_b_id,
        cluster_id_b=cluster_id_b,
        axis_origin=axis_origin,
        axis_direction=body.axis_direction,
        current_value=body.current_value,
        min_limit=body.min_limit,
        max_limit=body.max_limit,
        connector_a_label=body.connector_a_label,
        connector_b_label=body.connector_b_label,
    )

    # Apply any residual snap and snapshot base_transform (value=0 reference pose)
    T_b         = _mat4_from_model(inst_b.transform)
    snapped_T_b = snap_delta @ T_b if snap_delta is not None else T_b
    new_inst_b  = inst_b.model_copy(update={
        "transform":      _mat4_to_model(snapped_T_b),
        "base_transform": _mat4_to_model(snapped_T_b),
    })
    new_instances = [new_inst_b if i.id == inst_b.id else i for i in assembly.instances]
    new_joints    = list(assembly.joints) + [joint]
    new_assembly = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # Capture mate_relative_transform = F_a_world^-1 @ F_b_world right after the
    # creation-time snap so future resolve_assembly invocations can restore not
    # just the position coincidence but the full relative orientation between
    # the two connector frames (important when a later part edit rotates a
    # connector within its part — e.g. via a Relax Bond cluster transform).
    if joint.joint_type in ("rigid", "spherical") and body.connector_a_label and body.instance_a_id and body.connector_b_label:
        post_inst_a = _find_instance(new_assembly, body.instance_a_id)
        post_inst_b = _find_instance(new_assembly, body.instance_b_id)
        design_a = _design_with_instance_overrides(post_inst_a, _assembly_source_path(new_assembly))
        design_b = _design_with_instance_overrides(post_inst_b, _assembly_source_path(new_assembly))
        F_a = _get_connector_world_frame(post_inst_a, body.connector_a_label, design_a)
        F_b = _get_connector_world_frame(post_inst_b, body.connector_b_label, design_b)
        if F_a is not None and F_b is not None:
            try:
                M = np.linalg.inv(F_a) @ F_b
                new_joints = [
                    j.model_copy(update={"mate_relative_transform": M.flatten().tolist()})
                    if j.id == joint.id else j
                    for j in new_assembly.joints
                ]
                new_assembly = new_assembly.model_copy(update={"joints": new_joints})
                joint = next(j for j in new_assembly.joints if j.id == joint.id)
            except np.linalg.LinAlgError:
                pass

    # Propagate snap to inst_b's NON-rigid kinematic children only. Do NOT
    # call _fk_expand_rigid_group here: that helper walks rigid joints
    # bidirectionally, so for the brand-new rigid joint we just added it
    # would find instance_a as a rigid neighbour of instance_b and translate
    # instance_a by the same snap_delta — dragging the parent away from
    # where its connector was. instance_a is the snap target and must not
    # move. (Same reasoning as the rigid branch in resolve_assembly.)
    if snap_delta is not None:
        try:
            _fk_propagate(new_assembly, {body.instance_b_id}, snap_delta, {body.instance_b_id},
                          _build_inst_by_id(new_assembly))
        except np.linalg.LinAlgError:
            pass

    inst_a_name = (_find_instance(new_assembly, body.instance_a_id).name
                    if body.instance_a_id else "world")
    inst_b_name = _find_instance(new_assembly, body.instance_b_id).name
    label_str = f"Add mate: {inst_a_name} ↔ {inst_b_name}"

    params = {
        "joint_id":          joint.id,
        "name":              joint.name,
        "joint_type":        joint.joint_type,
        "instance_a_id":     joint.instance_a_id,
        "instance_b_id":     joint.instance_b_id,
        "cluster_id_a":      joint.cluster_id_a,
        "cluster_id_b":      joint.cluster_id_b,
        "axis_origin":       list(joint.axis_origin),
        "axis_direction":    list(joint.axis_direction),
        "min_limit":         joint.min_limit,
        "max_limit":         joint.max_limit,
        "connector_a_label": joint.connector_a_label,
        "connector_b_label": joint.connector_b_label,
        "mate_relative_transform": list(joint.mate_relative_transform) if joint.mate_relative_transform else None,
    }
    return new_assembly, joint, label_str, params


@router.post("/assembly/joints", status_code=201)
def add_joint(body: AddJointRequest) -> dict:
    """Add an AssemblyJoint, snap instance_b to connector_a, and snapshot base_transform."""
    assembly = assembly_state.get_or_404()
    new_assembly, _joint, label_str, params = _compose_add_joint(assembly, body)
    _apply_assembly_mutation_with_feature_log(
        new_assembly,
        op_kind="assembly-add-joint",
        label=label_str,
        params=params,
    )
    return _assembly_response(assembly_state.get_or_404())


@router.post("/assembly/joints/create-mate", status_code=201)
def create_mate(body: CreateMateRequest) -> dict:
    """Create a mate in ONE request: register blunt-end connectors, propagate FK
    to the aligned pose, and add the joint.

    Replaces the old frontend sequence of four awaited round-trips
    (addConnector × 2 → propagate_fk → add_joint), each of which replaced the
    active assembly and fired the renderer's store subscriber.  Two of those
    carried an unchanged transform and snapped any live mate preview back to
    the stored pose, producing the visible "moves three times" jank.  Doing it
    all server-side yields a single store update, a single undo step, and a
    single feature-log entry.
    """
    live = assembly_state.get_or_404()
    # Work on a deep copy so every sub-step mutates freely; the live state is
    # untouched until the single feature-log apply at the end.
    assembly = live.model_copy(deep=True)
    inst_by_id = _build_inst_by_id(assembly)

    # 1. Register blunt-end connectors as InterfacePoints (idempotent — skip if
    #    the label already exists, e.g. a previously-defined interface point).
    def _register(conn: 'MateConnectorSpec | None') -> None:
        if conn is None or not (conn.is_blunt_end or conn.is_bend_center):
            return
        inst = inst_by_id.get(conn.instance_id)
        if inst is None or any(ip.label == conn.label for ip in inst.interface_points):
            return
        inst.interface_points.append(InterfacePoint(
            label=conn.label,
            position=Vec3(x=conn.position[0], y=conn.position[1], z=conn.position[2]),
            normal=Vec3(x=conn.normal[0], y=conn.normal[1], z=conn.normal[2]),
            connection_type=ConnectionType.COVALENT,
            cluster_id=conn.cluster_id,
        ))
    _register(body.child_connector)
    _register(body.parent_connector)

    # 2. Propagate FK to the aligned pose.  Skipped for World mates / both-fixed
    #    parts, where the frontend sends no transform.
    if body.moved_instance_id and body.transform and "values" in body.transform:
        _propagate_fk_inplace(assembly, body.moved_instance_id, body.transform["values"], inst_by_id)

    # 3. Compose the joint on the connector-registered, FK-moved assembly.
    joint_body = AddJointRequest(
        name=body.name,
        joint_type=body.joint_type,
        instance_a_id=(body.parent_connector.instance_id if body.parent_connector else None),
        cluster_id_a=(body.parent_connector.cluster_id if body.parent_connector else None),
        instance_b_id=body.child_connector.instance_id,
        cluster_id_b=body.child_connector.cluster_id,
        axis_origin=body.axis_origin,
        axis_direction=body.axis_direction,
        min_limit=body.min_limit,
        max_limit=body.max_limit,
        connector_a_label=(body.parent_connector.label if body.parent_connector else None),
        connector_b_label=body.child_connector.label,
    )
    new_assembly, joint, _label, _params = _compose_add_joint(assembly, joint_body)

    # 4. Apply once: single undo step + single feature-log entry.
    inst_a_name = (_find_instance(new_assembly, joint.instance_a_id).name
                   if joint.instance_a_id else "world")
    inst_b_name = _find_instance(new_assembly, joint.instance_b_id).name
    _apply_assembly_mutation_with_feature_log(
        new_assembly,
        op_kind="assembly-create-mate",
        label=f"Create mate: {inst_a_name} ↔ {inst_b_name}",
        params={
            "joint_id":          joint.id,
            "joint_type":        joint.joint_type,
            "instance_a_id":     joint.instance_a_id,
            "instance_b_id":     joint.instance_b_id,
            "moved_instance_id": body.moved_instance_id,
            "connector_a_label": joint.connector_a_label,
            "connector_b_label": joint.connector_b_label,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/joints/{joint_id}", status_code=200)
def patch_joint(joint_id: str, body: PatchJointRequest) -> dict:
    """
    Update joint fields.  When current_value changes on a revolute joint,
    recomputes instance_b.transform from base_transform to avoid accumulation.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)
    if os.environ.get('NADOC_GEAR_DEBUG', '1') != '0':
        print(f"[patch_joint] joint={joint_id[:8]} type={joint.joint_type} "
              f"body.current_value={body.current_value} "
              f"joint.current_value={joint.current_value}", flush=True)

    joint_updates: dict = {}
    if body.name is not None:
        joint_updates["name"] = body.name
    if body.joint_type is not None and body.joint_type != joint.joint_type:
        joint_updates["joint_type"] = body.joint_type
        joint_updates["current_value"] = 0.0   # reset value when type changes
        joint_updates["min_limit"] = None
        joint_updates["max_limit"] = None
    if body.axis_origin is not None:
        joint_updates["axis_origin"] = body.axis_origin
    if body.axis_direction is not None:
        joint_updates["axis_direction"] = body.axis_direction
    if body.clear_limits:
        joint_updates["min_limit"] = None
        joint_updates["max_limit"] = None
    fields_set = getattr(body, "model_fields_set", set())
    if "min_limit" in fields_set:
        joint_updates["min_limit"] = body.min_limit
    if "max_limit" in fields_set:
        joint_updates["max_limit"] = body.max_limit
    if body.angular_velocity_rpm is not None:
        joint_updates["angular_velocity_rpm"] = float(body.angular_velocity_rpm)
    if body.spin_paused is not None:
        joint_updates["spin_paused"] = bool(body.spin_paused)

    value_changed = body.current_value is not None and body.current_value != joint.current_value
    if body.current_value is not None:
        # Clamp to limits if set
        val = body.current_value
        active_min = joint_updates.get("min_limit", joint.min_limit)
        active_max = joint_updates.get("max_limit", joint.max_limit)
        lo  = active_min if active_min is not None else -math.inf
        hi  = active_max if active_max is not None else  math.inf
        joint_updates["current_value"] = max(lo, min(hi, val))

    # ── Endpoint-aware revolute drive ────────────────────────────────────────
    # Apply the value via the gear-endpoint helper, which rotates the correct
    # seed even when the joint is authored "backward" (moving pulley = parent,
    # fixed axle = child). The legacy path below always moves instance_b, which
    # would rotate the *fixed axle*. The gizmo passes endpoint_side explicitly;
    # for any other caller (e.g. the joint-edit form re-sending current_value
    # after a limits toggle) we INFER it: never rotate a fixed child — if
    # instance_b is anchored but the parent isn't, the moving body is the parent.
    endpoint_side = body.endpoint_side
    if endpoint_side is None and value_changed and joint.joint_type == "revolute":
        inst_a = next((i for i in assembly.instances if i.id == joint.instance_a_id), None)
        inst_b = next((i for i in assembly.instances if i.id == joint.instance_b_id), None)
        if inst_b is not None and inst_b.fixed and not (inst_a is not None and inst_a.fixed):
            endpoint_side = "a"

    if (value_changed and joint.joint_type == "revolute"
            and endpoint_side in ("a", "b")):
        target_value = joint_updates.pop("current_value")  # helper sets it from the OLD value
        new_joint = joint.model_copy(update=joint_updates)
        new_joints = [new_joint if j.id == joint_id else j for j in assembly.joints]
        silent = bool(body.silent)
        if not silent:
            assembly_state.snapshot()
        new_assembly = assembly.model_copy(update={"joints": new_joints})
        inst_by_id = _build_inst_by_id(new_assembly)
        target_joint = next(j for j in new_assembly.joints if j.id == joint_id)
        _apply_revolute_value_to_gear_endpoint(
            new_assembly, target_joint, endpoint_side, float(target_value), inst_by_id,
        )
        _propagate_gear_relations_from(new_assembly, joint_id)
        assembly_state.set_assembly_silent(new_assembly)
        return _assembly_response(assembly_state.get_or_404())

    new_joint = joint.model_copy(update=joint_updates)
    new_joints = [new_joint if j.id == joint_id else j for j in assembly.joints]

    # Recompute instance_b transform when driving a revolute or prismatic joint
    new_instances = list(assembly.instances)
    new_mat: np.ndarray | None = None
    old_inst_b_T: np.ndarray | None = None
    if value_changed and new_joint.joint_type in ("revolute", "prismatic"):
        inst_b = _find_instance(assembly, joint.instance_b_id)
        old_inst_b_T = _mat4_from_model(inst_b.transform)
        base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
        if new_joint.joint_type == "revolute":
            new_mat = _apply_revolute_joint(
                base_mat,
                new_joint.axis_origin,
                new_joint.axis_direction,
                new_joint.current_value,
            )
        else:
            new_mat = _apply_prismatic_joint(
                base_mat,
                new_joint.axis_direction,
                new_joint.current_value,
            )
        new_inst_b    = inst_b.model_copy(update={"transform": _mat4_to_model(new_mat)})
        new_instances = [new_inst_b if i.id == inst_b.id else i for i in assembly.instances]

    silent = body.silent  # True during animation playback
    if not silent:
        assembly_state.snapshot()

    new_assembly = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # FK propagation: propagate delta from instance_b's motion to its kinematic descendants
    if new_mat is not None and old_inst_b_T is not None:
        try:
            delta = new_mat @ np.linalg.inv(old_inst_b_T)
            visited = {new_joint.instance_b_id}
            inst_by_id = _build_inst_by_id(new_assembly)
            _fk_expand_rigid_group(new_assembly, new_joint.instance_b_id, delta, visited, [], inst_by_id)
            _fk_propagate(new_assembly, visited.copy(), delta, visited, inst_by_id)
            _enforce_connector_coincidence(new_assembly, visited, inst_by_id)
        except np.linalg.LinAlgError:
            pass  # singular old transform — skip FK propagation

    # Gear-relation propagation: if this joint is a driver of any GearRelation,
    # update each driven joint's current_value + instance_b transform + FK so
    # the gear-coupled part follows whether the user got here via ring drag,
    # the joint edit form, or any other source.
    if value_changed and new_joint.joint_type == 'revolute':
        _propagate_gear_relations_from(new_assembly, joint_id)

    assembly_state.set_assembly_silent(new_assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.post("/assembly/joints/{joint_id}/refresh-mate", status_code=200)
def refresh_mate(joint_id: str) -> dict:
    """Capture the mate's current relative *rotation* and snap connectors together.

    For a rigid mate the captured invariant is: "the two connector frames are
    coincident in position with this relative rotation". So we:
      1. Compute the live world frames F_a, F_b (cluster-aware).
      2. Capture mate_relative_transform with the rotation part of
         ``F_a^-1 @ F_b`` and a ZERO translation column. Capturing the raw
         translation would lock in any current position discrepancy as the
         "intended" state — exactly what a user clicking this button on a
         misaligned mate wants to avoid.
      3. Apply the SE3 snap to instance_b so connector_b coincides with
         connector_a using the captured rotation, propagating the same snap
         to inst_b's non-rigid kinematic children. This makes the button a
         single-click fix instead of requiring a follow-up Resolve.

    Useful for legacy joints (no mate_relative_transform set) and for re-
    capturing intent after a part edit has rotated a connector inside its
    part — typical example is the Hinge dimers case where a linker-length
    change tilts the hinge's mating face.

    Only rigid / spherical joints are eligible.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)
    if joint.joint_type not in ("rigid", "spherical"):
        raise HTTPException(400, detail="Only rigid / spherical mates store a relative transform.")
    if not (joint.connector_a_label and joint.instance_a_id and joint.connector_b_label):
        raise HTTPException(400, detail="Joint must reference both connectors to refresh.")
    inst_a = _find_instance(assembly, joint.instance_a_id)
    inst_b = _find_instance(assembly, joint.instance_b_id)
    design_a = _design_with_instance_overrides(inst_a, _assembly_source_path(assembly))
    design_b = _design_with_instance_overrides(inst_b, _assembly_source_path(assembly))
    F_a = _get_connector_world_frame(inst_a, joint.connector_a_label, design_a)
    F_b = _get_connector_world_frame(inst_b, joint.connector_b_label, design_b)
    if F_a is None or F_b is None:
        raise HTTPException(400, detail="Failed to compute connector frames for this mate.")
    try:
        M_full = np.linalg.inv(F_a) @ F_b
    except np.linalg.LinAlgError:
        raise HTTPException(400, detail="Singular connector frame; cannot capture mate transform.")

    # Rotation-only capture: discard any current position discrepancy.
    M = np.eye(4, dtype=float)
    M[:3, :3] = M_full[:3, :3]

    # Compute the SE3 snap that brings F_b to F_a @ M (positions coincide
    # using the captured rotation) and apply it to inst_b + non-rigid
    # children. Mirrors the rigid branch of resolve_assembly.
    F_b_target = F_a @ M
    try:
        snap_T = F_b_target @ np.linalg.inv(F_b)
    except np.linalg.LinAlgError:
        raise HTTPException(400, detail="Singular connector frame; cannot capture mate transform.")

    new_origin = F_a[:3, 3].tolist()
    # Apply the snap to inst_b's transform + base_transform.
    old_T = _mat4_from_model(inst_b.transform)
    new_T = snap_T @ old_T
    new_inst_b_updates = {"transform": _mat4_to_model(new_T)}
    if inst_b.base_transform:
        new_inst_b_updates["base_transform"] = _mat4_to_model(
            snap_T @ _mat4_from_model(inst_b.base_transform))

    new_instances = [
        i.model_copy(update=new_inst_b_updates) if i.id == inst_b.id else i
        for i in assembly.instances
    ]
    new_joints = [
        j.model_copy(update={
            "mate_relative_transform": M.flatten().tolist(),
            "axis_origin": new_origin,
        }) if j.id == joint_id else j
        for j in assembly.joints
    ]
    mutated = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # Propagate the snap to inst_b's non-rigid kinematic children so
    # revolute / prismatic descendants follow the mate fix.
    try:
        _fk_propagate(mutated, {inst_b.id}, snap_T, {inst_b.id},
                      _build_inst_by_id(mutated))
    except np.linalg.LinAlgError:
        pass

    assembly_state.set_assembly(mutated)
    return _assembly_response(mutated)


@router.delete("/assembly/joints/{joint_id}", status_code=200)
def delete_joint(joint_id: str) -> dict:
    """Remove an AssemblyJoint."""
    assembly = assembly_state.get_or_404()
    target   = _find_joint(assembly, joint_id)
    new_joints = [j for j in assembly.joints if j.id != joint_id]
    # Cascade-drop any gear relations that referenced this joint.
    new_gears  = [g for g in assembly.gear_relations
                  if g.joint_a_id != joint_id and g.joint_b_id != joint_id]
    mutated = assembly.model_copy(update={"joints": new_joints, "gear_relations": new_gears})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-joint",
        label=f"Delete mate: {target.name}",
        params={"joint_id": joint_id, "name": target.name},
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Gear/belt endpoint resolution (shared helper) ─────────────────────────────
#
# The gear-relation routes live in routes_assembly_gears.py and the belt-path
# routes in routes_assembly_belts.py; this resolver stays here because both
# routers' pulley/endpoint handlers call it (gear's create/patch,
# belt's _resolve_belt_pulley) and it raises HTTPException (L4-blocked from
# backend/core). Both routers import it back as shared infrastructure.

def _resolve_gear_endpoint(joint: AssemblyJoint, instance_id: Optional[str], side: Optional[str],
                           label: str) -> tuple[Optional[str], str]:
    if side not in (None, "a", "b"):
        raise HTTPException(400, detail=f"{label}.side must be 'a' or 'b'.")
    if instance_id:
        if instance_id == joint.instance_a_id:
            resolved_side = "a"
        elif instance_id == joint.instance_b_id:
            resolved_side = "b"
        else:
            raise HTTPException(400, detail=f"{label} instance is not an endpoint of the selected revolute mate.")
        if side and side != resolved_side:
            raise HTTPException(400, detail=f"{label} side does not match its instance.")
        return instance_id, resolved_side
    resolved_side = side or "b"
    resolved_id = joint.instance_a_id if resolved_side == "a" else joint.instance_b_id
    return resolved_id, resolved_side


# ── Polymerize Origami ────────────────────────────────────────────────────────
#
# Replicate an existing mate (joint between two identical PartInstances) to
# grow a linear chain of identical parts.  Math lives in
# :mod:`backend.core.assembly_polymer`; this route applies the resulting
# transforms + spawns new PartInstance + AssemblyJoint records.

class PolymerizeAssemblyRequest(BaseModel):
    joint_id:  str
    count:     int                                            # total chain length, ≥ 2
    direction: Literal["forward", "backward", "both"] = "forward"
    # Additional instances (beyond the seed mate's two) that should be
    # carried along as part of the pattern. Each gets cloned at every chain
    # step at `delta^step @ T(original)`, and any mate inside the pattern
    # unit (seed_a, seed_b, and these additionals) is replicated between
    # the corresponding new clones at each step.
    additional_instance_ids: list[str] = Field(default_factory=list)


@router.post("/assembly/polymerize", status_code=200)
def polymerize_assembly(body: PolymerizeAssemblyRequest) -> dict:
    """Grow a linear polymer of identical parts from a seed mate.

    The seed mate's two instances are the chain anchor + first primary.
    Additional instances passed in ``additional_instance_ids`` are carried
    along as part of the pattern — at each new chain step they get cloned
    with transform ``delta^step @ T(original)`` so the spatial relationship
    inside the pattern unit is preserved. Mates whose both endpoints live
    in the pattern unit are replicated at every step between the matching
    cloned instances.
    """
    from backend.core.assembly_polymer import (
        _sources_match, _split_count,
        compute_additional_chain_transforms,
        compute_chain_joint_axes, compute_chain_transforms,
        compute_delta_powers, transform_joint_axis,
    )

    if body.count < 2:
        raise HTTPException(400, detail="count must be at least 2 (the existing pair).")

    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, body.joint_id)
    if not joint.instance_a_id or not joint.instance_b_id:
        raise HTTPException(
            422,
            detail="Polymerize requires a mate between two instances (joint has only one side).",
        )
    inst_a = _find_instance(assembly, joint.instance_a_id)
    inst_b = _find_instance(assembly, joint.instance_b_id)
    if not _sources_match(inst_a.source, inst_b.source):
        raise HTTPException(
            422,
            detail="Polymerize requires identical parts on both sides of the mate.",
        )

    # Resolve "to pattern" additional instances. Silently drop ids that
    # match the seed pair (UI may include them by mistake), but 404 on
    # truly missing ones so the user knows something is off.
    seed_pair_ids: set[str] = {joint.instance_a_id, joint.instance_b_id}
    additional_instances: list[PartInstance] = []
    seen: set[str] = set()
    for aid in (body.additional_instance_ids or []):
        if aid in seed_pair_ids or aid in seen:
            continue
        seen.add(aid)
        additional_instances.append(_find_instance(assembly, aid))

    # count == 2 is a no-op — chain is already that length.
    if body.count == 2:
        return _assembly_response(assembly)

    forward_T, backward_T = compute_chain_transforms(
        inst_a.transform, inst_b.transform, body.count, body.direction,
    )
    n_forward, n_backward = _split_count(body.count, body.direction)
    forward_axes, backward_axes = compute_chain_joint_axes(
        joint, inst_a.transform, inst_b.transform, n_forward, n_backward,
    )
    # Compute delta powers to cover ALL iteration counts — the extended
    # additional-clone chain may need one more matrix than the primary
    # chain (see add_n_forward / add_n_backward below).
    forward_delta_pow, backward_delta_pow = compute_delta_powers(
        inst_a.transform, inst_b.transform,
        n_forward + 1, n_backward + 1,
    )

    # Mates in the pattern unit (excluding the seed mate itself). Each will
    # be replicated at every chain step. ``instance_a_id`` is Optional in
    # the model — a None side never participates in pattern replication.
    unit_ids: set[str] = seed_pair_ids | {i.id for i in additional_instances}
    pattern_mates = [
        j for j in assembly.joints
        if j.id != joint.id
        and j.instance_a_id is not None
        and j.instance_a_id in unit_ids
        and j.instance_b_id in unit_ids
    ]

    # ── Connector union ───────────────────────────────────────────────────────
    # The seed mate references one InterfacePoint label on each side; users
    # typically only `Define Connector` once per instance, so inst_a has just
    # the "a" label and inst_b has just the "b" label.  In a chain every
    # interior instance plays both roles, so each chained instance needs both
    # labels.  Build the union (deduped by label, source order preserved) and
    # apply it to A, B, and every new clone.  Positions are part-local; since
    # _sources_match is true above, the union is well-defined.
    union_ips: list = []
    seen_labels: set[str] = set()
    for ip in list(inst_a.interface_points) + list(inst_b.interface_points):
        if ip.label in seen_labels:
            continue
        seen_labels.add(ip.label)
        union_ips.append(ip.model_copy(deep=True))

    inst_a_updated = inst_a.model_copy(update={"interface_points": list(union_ips)})
    inst_b_updated = inst_b.model_copy(update={"interface_points": list(union_ips)})

    # Stitch the originals back into the assembly's instance list at their
    # original indexes so positional ordering is preserved.
    existing_instances = [
        inst_a_updated if i.id == inst_a.id else
        inst_b_updated if i.id == inst_b.id else i
        for i in assembly.instances
    ]

    # ── Build new PartInstances (forward side) ────────────────────────────────
    # Phase 4a path-to-thousands: bypass per-clone Pydantic deep validation
    # by using ``PartInstance.model_construct`` (skips validators) AND
    # sharing the heavy ``source`` field by reference across all clones.
    # The source field on a PartInstance is treated as immutable downstream
    # (loaded read-only via _load_design_from_source), so reference-sharing
    # is safe; the original code's ``model_copy(deep=True)`` was deep-copying
    # a heavy Design tree per clone for no semantic benefit.
    #
    # Net effect at N=500 polymerize_64: ~150 ms → ~10 ms inside the loop.
    new_instances: list[PartInstance] = []
    new_joints:    list[AssemblyJoint] = []

    base_name_b = inst_b.name
    base_name_a = inst_a.name

    # Pre-compute per-additional per-step transforms.  Additionals get one
    # MORE clone than the primary chain extension so each pattern member
    # ends up with the same total count as the primary chain — the seed
    # pair contributes two existing primaries (seed_a + seed_b), but each
    # additional contributes only one existing instance, so an extra
    # clone is needed.  The extra clone is placed in the dominant
    # direction (forward for 'forward' and 'both', backward for
    # 'backward').
    add_n_forward  = n_forward  + (1 if body.direction != "backward" else 0)
    add_n_backward = n_backward + (1 if body.direction == "backward" else 0)
    add_forward_transforms:  dict[str, list[np.ndarray]] = {}
    add_backward_transforms: dict[str, list[np.ndarray]] = {}
    for add_inst in additional_instances:
        f, b = compute_additional_chain_transforms(
            inst_a.transform, inst_b.transform, add_inst.transform,
            add_n_forward, add_n_backward,
        )
        add_forward_transforms[add_inst.id]  = f
        add_backward_transforms[add_inst.id] = b

    forward_primary_ids:  list[str]                = []
    forward_add_ids:      dict[str, list[str]]     = {a.id: [] for a in additional_instances}
    backward_primary_ids: list[str]                = []
    backward_add_ids:     dict[str, list[str]]     = {a.id: [] for a in additional_instances}

    # ``_make_clone`` constructs a PartInstance for a polymerize clone with
    # the heavy ``source`` field shared by reference from the seed.  We use
    # ``model_construct`` (no validation) — every field is already validated
    # on the seed, and the only field-typed changes (id, name, transform,
    # representation) are well-formed Python primitives or pre-built
    # Mat4x4 objects.  Interface points are passed through; we DO need
    # independent IP lists per clone (a shallow ``list(union_ips)`` at the
    # call site) because IPs are appended to / mutated by add_connector
    # etc. downstream.  The IP OBJECTS inside the list are shared by
    # reference — safe ONLY because every add/remove path in this module
    # uses ``model_copy(update=...)`` rather than in-place mutation; if a
    # future code path mutates an IP in place, switch the call sites to
    # ``[ip.model_copy(deep=True) for ip in union_ips]``.
    def _make_clone(seed: PartInstance, *, new_id: str, name: str,
                    transform: Mat4x4, base_transform: Optional[Mat4x4],
                    interface_points: list,
                    representation: str = "cylinders") -> PartInstance:
        return PartInstance.model_construct(
            id=new_id,
            name=name,
            source=seed.source,                 # shared by reference (read-only downstream)
            transform=transform,
            base_transform=base_transform,
            mode=seed.mode,
            visible=seed.visible,
            representation=representation,
            fixed=seed.fixed,
            allow_part_joints=seed.allow_part_joints,
            joint_states=dict(seed.joint_states),
            cluster_transform_overrides=list(seed.cluster_transform_overrides),
            interface_points=interface_points,
        )

    # Each new forward primary clones inst_b's per-instance state (overrides,
    # representation, mode, fixed/visible, joint_states) but takes the unioned
    # connectors so it can mate on both sides.
    prev_inst_id = inst_b_updated.id
    for i, T_arr in enumerate(forward_T):
        T_mat = Mat4x4.from_array(T_arr)
        new_id = str(_uuid.uuid4())
        new_inst = _make_clone(
            inst_b,
            new_id=new_id,
            name=f"{base_name_b} {i + 1}",
            transform=T_mat,
            base_transform=T_mat,   # base_transform = transform at value=0
            interface_points=list(union_ips),
        )
        forward_primary_ids.append(new_id)
        axis_origin, axis_direction = forward_axes[i]
        new_jt = AssemblyJoint(
            name=f"{joint.name} +{i + 1}",
            joint_type=joint.joint_type,
            instance_a_id=prev_inst_id,
            instance_b_id=new_id,
            cluster_id_a=joint.cluster_id_a,
            cluster_id_b=joint.cluster_id_b,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            current_value=0.0,
            min_limit=joint.min_limit,
            max_limit=joint.max_limit,
            connector_a_label=joint.connector_a_label,
            connector_b_label=joint.connector_b_label,
            # Replicate the seed mate's full SE3 relative frame so resolve does
            # an orientation-aware snap (not just translation). Without this,
            # polymerized rigid mates resolved POSITION but not ORIENTATION.
            mate_relative_transform=joint.mate_relative_transform,
        )
        new_instances.append(new_inst)
        new_joints.append(new_jt)
        prev_inst_id = new_id

    # Spawn additional clones forward.  Each additional gets `add_n_forward`
    # entries, which is `n_forward + 1` for direction ∈ {forward, both} so
    # the additional's total instance count (1 existing + add_n_forward new)
    # matches the chain length N — fixing the off-by-one the user reported.
    for add_inst in additional_instances:
        ip_seed = list(add_inst.interface_points)
        for i, T_add in enumerate(add_forward_transforms[add_inst.id]):
            T_mat = Mat4x4.from_array(T_add)
            new_id = str(_uuid.uuid4())
            new_inst = _make_clone(
                add_inst,
                new_id=new_id,
                name=f"{add_inst.name} {i + 1}",
                transform=T_mat,
                base_transform=None,
                interface_points=list(ip_seed),
            )
            new_instances.append(new_inst)
            forward_add_ids[add_inst.id].append(new_id)

    # ── Backward side ────────────────────────────────────────────────────────
    # Reuse inst_a's per-instance state.  Each backward instance is appended
    # in the order "closest to A outward" so the new joint binds
    # (backward_step_i, backward_step_{i-1}) — except the first backward
    # joint, which binds (first_new_backward, original inst_a).  Connector
    # labels stay the same as the original mate.
    prev_inst_id = inst_a_updated.id
    for i, T_arr in enumerate(backward_T):
        T_mat = Mat4x4.from_array(T_arr)
        new_id = str(_uuid.uuid4())
        new_inst = _make_clone(
            inst_a,
            new_id=new_id,
            name=f"{base_name_a} -{i + 1}",
            transform=T_mat,
            base_transform=T_mat,
            interface_points=list(union_ips),
        )
        backward_primary_ids.append(new_id)
        axis_origin, axis_direction = backward_axes[i]
        # The mate's "natural" direction is (a → b).  For backward
        # chaining, the previous instance (closer to the original a) plays
        # the role of "b" relative to the new (further-back) instance.
        # Preserve the original connector labels by setting
        # (instance_a = new_inst, instance_b = prev_inst) so connector_a
        # lands on the freshly-added part and connector_b on the existing
        # one — same labels as the seed mate.
        new_jt = AssemblyJoint(
            name=f"{joint.name} -{i + 1}",
            joint_type=joint.joint_type,
            instance_a_id=new_id,
            instance_b_id=prev_inst_id,
            cluster_id_a=joint.cluster_id_a,
            cluster_id_b=joint.cluster_id_b,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            current_value=0.0,
            min_limit=joint.min_limit,
            max_limit=joint.max_limit,
            connector_a_label=joint.connector_a_label,
            connector_b_label=joint.connector_b_label,
            # Replicate the seed mate's full SE3 relative frame so resolve does
            # an orientation-aware snap (not just translation). Without this,
            # polymerized rigid mates resolved POSITION but not ORIENTATION.
            mate_relative_transform=joint.mate_relative_transform,
        )
        new_instances.append(new_inst)
        new_joints.append(new_jt)
        prev_inst_id = new_id

    # Spawn additional clones backward.  Same off-by-one fix as forward —
    # add_n_backward = n_backward + 1 when direction == 'backward', else
    # n_backward.  Each additional ends up with chain-length-many total
    # instances combining backward + forward.
    for add_inst in additional_instances:
        ip_seed = list(add_inst.interface_points)
        for i, T_add in enumerate(add_backward_transforms[add_inst.id]):
            T_mat = Mat4x4.from_array(T_add)
            new_id = str(_uuid.uuid4())
            new_inst = _make_clone(
                add_inst,
                new_id=new_id,
                name=f"{add_inst.name} -{i + 1}",
                transform=T_mat,
                base_transform=None,
                interface_points=list(ip_seed),
            )
            new_instances.append(new_inst)
            backward_add_ids[add_inst.id].append(new_id)

    # ── Pattern-mate replication ──────────────────────────────────────────────
    # For each mate inside the pattern unit (excluding the seed mate), emit
    # one new joint per chain step between the matching cloned instances.
    # The new joint's axis_origin / axis_direction are shifted by the same
    # delta^step that placed the new instances, so the world-space axis
    # lands at the right spot.

    def _clone_id_forward(orig_id: str, step1: int) -> Optional[str]:
        """Return the id of *orig_id*'s clone at 1-indexed forward step,
        or None if no clone exists at that step (e.g. the seed_b-side
        primary chain is exhausted before the additional chain).

        - seed_a (level 0) shifts to primary at level `step1`.
        - seed_b (level 1) shifts to primary at level `step1 + 1`.
        - additional X shifts to its own clone array entry.
        """
        if orig_id == joint.instance_a_id:
            if step1 == 1:
                return joint.instance_b_id
            idx = step1 - 2
            return forward_primary_ids[idx] if 0 <= idx < len(forward_primary_ids) else None
        if orig_id == joint.instance_b_id:
            idx = step1 - 1
            return forward_primary_ids[idx] if 0 <= idx < len(forward_primary_ids) else None
        ids = forward_add_ids.get(orig_id)
        if not ids:
            return None
        idx = step1 - 1
        return ids[idx] if 0 <= idx < len(ids) else None

    def _clone_id_backward(orig_id: str, step1: int) -> Optional[str]:
        """1-indexed backward step. seed_a / seed_b shift inverse-delta^step."""
        if orig_id == joint.instance_b_id:
            if step1 == 1:
                return joint.instance_a_id
            idx = step1 - 2
            return backward_primary_ids[idx] if 0 <= idx < len(backward_primary_ids) else None
        if orig_id == joint.instance_a_id:
            idx = step1 - 1
            return backward_primary_ids[idx] if 0 <= idx < len(backward_primary_ids) else None
        ids = backward_add_ids.get(orig_id)
        if not ids:
            return None
        idx = step1 - 1
        return ids[idx] if 0 <= idx < len(ids) else None

    # Iterate up to the EXTENDED additional count so the bonus clone at
    # the end of the chain also gets its mate replicated.  _clone_id_*
    # returns None when the primary chain has been exhausted at this step
    # (e.g. mate involves seed_b which only goes up to n_forward), in
    # which case we silently skip that step for that mate.
    fwd_max  = max(n_forward,  add_n_forward)
    back_max = max(n_backward, add_n_backward)
    for pm in pattern_mates:
        for step_idx in range(1, fwd_max + 1):
            new_a_id = _clone_id_forward(pm.instance_a_id, step_idx)
            new_b_id = _clone_id_forward(pm.instance_b_id, step_idx)
            if new_a_id is None or new_b_id is None:
                continue
            d = forward_delta_pow[step_idx - 1]
            ao, ad = transform_joint_axis(list(pm.axis_origin), list(pm.axis_direction), d)
            new_joints.append(AssemblyJoint(
                name=f"{pm.name} +{step_idx}",
                joint_type=pm.joint_type,
                instance_a_id=new_a_id,
                instance_b_id=new_b_id,
                cluster_id_a=pm.cluster_id_a,
                cluster_id_b=pm.cluster_id_b,
                axis_origin=ao,
                axis_direction=ad,
                current_value=0.0,
                min_limit=pm.min_limit,
                max_limit=pm.max_limit,
                connector_a_label=pm.connector_a_label,
                connector_b_label=pm.connector_b_label,
                # Replicate the intra-unit mate's full SE3 relative frame so
                # resolve snaps orientation, not just position (see primary
                # chain joints above).
                mate_relative_transform=pm.mate_relative_transform,
            ))
        for step_idx in range(1, back_max + 1):
            new_a_id = _clone_id_backward(pm.instance_a_id, step_idx)
            new_b_id = _clone_id_backward(pm.instance_b_id, step_idx)
            if new_a_id is None or new_b_id is None:
                continue
            d = backward_delta_pow[step_idx - 1]
            ao, ad = transform_joint_axis(list(pm.axis_origin), list(pm.axis_direction), d)
            new_joints.append(AssemblyJoint(
                name=f"{pm.name} -{step_idx}",
                joint_type=pm.joint_type,
                instance_a_id=new_a_id,
                instance_b_id=new_b_id,
                cluster_id_a=pm.cluster_id_a,
                cluster_id_b=pm.cluster_id_b,
                axis_origin=ao,
                axis_direction=ad,
                current_value=0.0,
                min_limit=pm.min_limit,
                max_limit=pm.max_limit,
                connector_a_label=pm.connector_a_label,
                connector_b_label=pm.connector_b_label,
                # Replicate the intra-unit mate's full SE3 relative frame so
                # resolve snaps orientation, not just position (see primary
                # chain joints above).
                mate_relative_transform=pm.mate_relative_transform,
            ))

    mutated = assembly.model_copy(update={
        "instances": existing_instances + new_instances,
        "joints":    list(assembly.joints)    + new_joints,
    })

    new_instance_ids = [i.id for i in new_instances]
    new_joint_ids    = [j.id for j in new_joints]
    extra_suffix = f", +{len(additional_instances)} pattern part(s)" if additional_instances else ""
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-polymerize",
        label=f"Polymerize {joint.name}: chain length {body.count} ({body.direction}){extra_suffix}",
        params={
            "joint_id":                body.joint_id,
            "count":                   body.count,
            "direction":               body.direction,
            "additional_instance_ids": [a.id for a in additional_instances],
            "new_instance_ids":        new_instance_ids,
            "new_joint_ids":           new_joint_ids,
        },
    )
    return _assembly_response(updated)


class PolymerizePeriodicRequest(BaseModel):
    instance_id: str
    count:       int                                          # total chain length, ≥ 2
    direction:   Literal["forward", "backward", "both"] = "forward"


@router.get("/assembly/instances/{instance_id}/periodic-closure", status_code=200)
def get_instance_periodic_closure(instance_id: str, count: int = 4) -> dict:
    """Return the polymer's ring-closure residual after ``count`` copies.

    Used by the polymerize-periodic panel to warn the user before they
    commit a chain that won't close. ``angle_deg`` is the rotational drift
    of δ**count from identity; ``translation_nm`` is the positional drift.
    Both should be near zero for a closed ring.

    Also returns ``suggested_curvature_deg_per_bp`` — the κ that *would* close
    the chain — when the design has exactly one bend op. The frontend's
    "snap to closing κ" button writes this back to the bend op.
    """
    from backend.core.periodic_polymer import (
        PeriodicSeamError, closure_residual, solve_closing_curvature,
    )
    assembly = assembly_state.get_or_404()
    seed = _find_instance(assembly, instance_id)
    design = _design_with_instance_overrides(seed, _assembly_source_path(assembly))
    if not any(getattr(fl, "is_periodic_seam", False) for fl in design.forced_ligations):
        raise HTTPException(422, detail="Part has no periodic seam.")
    try:
        angle_deg, trans_nm = closure_residual(design, count)
        suggested = solve_closing_curvature(design, count)
    except PeriodicSeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        "count":                              int(count),
        "rotation_residual_deg":              float(angle_deg),
        "translation_residual_nm":            float(trans_nm),
        "suggested_curvature_deg_per_bp":     None if suggested is None else float(suggested),
    }


@router.post("/assembly/polymerize-periodic", status_code=200)
def polymerize_periodic_assembly(body: PolymerizePeriodicRequest) -> dict:
    """Grow a polymer from a SINGLE periodic part — no hand-defined mate.

    The part's repeat transform is derived from its ``is_periodic_seam`` forced
    ligations (the end-to-end seam the user marked in the cadnano editor's
    periodic-boundary view) via :func:`derive_periodic_delta`.  Copy k is placed
    at ``T_seed @ delta**k`` (delta is part-local, so it left-multiplies the
    seed's world transform).  Consecutive copies are tied by synthesized rigid
    seam joints carrying a single replicated ``mate_relative_transform`` so the
    chain re-resolves on part edits and is feature-logged / undoable — mirroring
    :func:`polymerize_assembly`, but anchored on one instance instead of a pair.
    """
    from backend.core.assembly_polymer import _matrix_power
    from backend.core.periodic_polymer import (
        PeriodicSeamError, derive_periodic_delta, principal_seam_connectors,
    )

    if body.count < 2:
        raise HTTPException(400, detail="count must be at least 2.")

    assembly = assembly_state.get_or_404()
    seed = _find_instance(assembly, body.instance_id)

    # Resolve the seed's design with its cluster overrides.  NOT _display_design
    # — the seams reference real strands/helices, which display-only stripping
    # would not affect but we want the authoritative topology regardless.
    design = _design_with_instance_overrides(seed, _assembly_source_path(assembly))

    if not any(getattr(fl, "is_periodic_seam", False) for fl in design.forced_ligations):
        raise HTTPException(
            422,
            detail="Part has no periodic seam. Mark the end-to-end seam across "
                   "the cadnano editor's periodic-boundary mirror first.",
        )
    try:
        delta = derive_periodic_delta(design)                # 4×4 part-local SE3
        delta_inv = np.linalg.inv(delta)
    except PeriodicSeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except np.linalg.LinAlgError as exc:
        raise HTTPException(422, detail=f"Could not derive periodic repeat transform: {exc}") from exc

    specs = principal_seam_connectors(design)
    if specs is None:
        raise HTTPException(422, detail="Periodic seam did not resolve to helix geometry.")
    (p5, n5), (p3, n3) = specs

    # ── Chain split: count-1 NEW copies beyond the single seed ────────────────
    new_total = body.count - 1
    if body.direction == "forward":
        n_forward, n_backward = new_total, 0
    elif body.direction == "backward":
        n_forward, n_backward = 0, new_total
    else:  # both — extra on forward when odd
        n_forward = (new_total + 1) // 2
        n_backward = new_total - n_forward

    T_seed = seed.transform.to_array()
    forward_T  = [T_seed @ _matrix_power(delta, k)     for k in range(1, n_forward + 1)]
    backward_T = [T_seed @ _matrix_power(delta_inv, k) for k in range(1, n_backward + 1)]

    # ── Seam connectors (part-local; identical on seed + every clone) ─────────
    seam_ips = [
        InterfacePoint(label="seam0:5p",
                       position=Vec3(x=p5[0], y=p5[1], z=p5[2]),
                       normal=Vec3(x=n5[0], y=n5[1], z=n5[2]),
                       connection_type=ConnectionType.COVALENT),
        InterfacePoint(label="seam0:3p",
                       position=Vec3(x=p3[0], y=p3[1], z=p3[2]),
                       normal=Vec3(x=n3[0], y=n3[1], z=n3[2]),
                       connection_type=ConnectionType.COVALENT),
    ]
    # Fresh seam IPs win over any stale ones from a prior polymerize.
    base_ips  = [ip.model_copy(deep=True) for ip in seed.interface_points
                 if not ip.label.startswith("seam0:")]
    union_ips = base_ips + seam_ips

    seed_updated = seed.model_copy(update={"interface_points": list(union_ips)})
    existing_instances = [seed_updated if i.id == seed.id else i for i in assembly.instances]

    def _clone(new_id: str, name: str, T_arr: np.ndarray) -> PartInstance:
        T_mat = Mat4x4.from_array(T_arr)
        return PartInstance.model_construct(
            id=new_id,
            name=name,
            source=seed.source,                 # shared by reference (read-only downstream)
            transform=T_mat,
            base_transform=T_mat,
            mode=seed.mode,
            visible=seed.visible,
            representation="cylinders",
            fixed=seed.fixed,
            allow_part_joints=seed.allow_part_joints,
            joint_states=dict(seed.joint_states),
            cluster_transform_overrides=list(seed.cluster_transform_overrides),
            interface_points=list(union_ips),
        )

    new_instances: list[PartInstance] = []
    forward_ids:  list[str] = []
    backward_ids: list[str] = []
    for k, T_arr in enumerate(forward_T, start=1):
        nid = str(_uuid.uuid4())
        new_instances.append(_clone(nid, f"{seed.name} +{k}", T_arr))
        forward_ids.append(nid)
    for k, T_arr in enumerate(backward_T, start=1):
        nid = str(_uuid.uuid4())
        new_instances.append(_clone(nid, f"{seed.name} -{k}", T_arr))
        backward_ids.append(nid)

    inst_lookup = {i.id: i for i in [seed_updated] + new_instances}

    # ── mate_relative_transform: capture ONCE from the first consecutive pair ──
    # The chain is uniform, so one M = inv(F_a^3p_world) @ F_b^5p_world applies to
    # every junction (exactly as polymerize_assembly replicates one mate frame).
    if n_forward >= 1:
        low_inst, high_inst = seed_updated, inst_lookup[forward_ids[0]]
    else:
        low_inst, high_inst = inst_lookup[backward_ids[0]], seed_updated
    F_a = _get_connector_world_frame(low_inst, "seam0:3p", None)
    F_b = _get_connector_world_frame(high_inst, "seam0:5p", None)
    mate_M: 'list | None' = None
    if F_a is not None and F_b is not None:
        try:
            mate_M = (np.linalg.inv(F_a) @ F_b).flatten().tolist()
        except np.linalg.LinAlgError:
            mate_M = None

    def _seam_joint(name: str, a_id: str, b_id: str) -> AssemblyJoint:
        Fa = _get_connector_world_frame(inst_lookup[a_id], "seam0:3p", None)
        axis_o = Fa[:3, 3].tolist() if Fa is not None else [0.0, 0.0, 0.0]
        axis_d = Fa[:3, 2].tolist() if Fa is not None else [0.0, 0.0, 1.0]
        return AssemblyJoint(
            name=name,
            joint_type="rigid",
            instance_a_id=a_id,
            instance_b_id=b_id,
            axis_origin=axis_o,
            axis_direction=axis_d,
            current_value=0.0,
            connector_a_label="seam0:3p",
            connector_b_label="seam0:5p",
            mate_relative_transform=mate_M,
        )

    new_joints: list[AssemblyJoint] = []
    # Forward: seed(3p) → f1(5p), f1(3p) → f2(5p), …
    prev_id = seed_updated.id
    for k, nid in enumerate(forward_ids, start=1):
        new_joints.append(_seam_joint(f"Seam +{k}", prev_id, nid))
        prev_id = nid
    # Backward: b1(3p) → seed(5p), b2(3p) → b1(5p), …
    prev_id = seed_updated.id
    for k, nid in enumerate(backward_ids, start=1):
        new_joints.append(_seam_joint(f"Seam -{k}", nid, prev_id))
        prev_id = nid

    mutated = assembly.model_copy(update={
        "instances": existing_instances + new_instances,
        "joints":    list(assembly.joints) + new_joints,
    })
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-polymerize-periodic",
        label=f"Polymerize (periodic) {seed.name}: chain length {body.count} ({body.direction})",
        params={
            "instance_id":      body.instance_id,
            "count":            body.count,
            "direction":        body.direction,
            "new_instance_ids": [i.id for i in new_instances],
            "new_joint_ids":    [j.id for j in new_joints],
        },
    )
    return _assembly_response(updated)


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
    from backend.core.assembly_linker import parse_namespaced_helix_id, _world_axes_for_helix
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
        R          = T[:3, :3]
        local_axis = helix.axis_end.to_array() - helix.axis_start.to_array()
        world_axis = we - ws
        wx         = _frame_from_helix_axis(world_axis)[:, 0]
        correct_x  = R @ _frame_from_helix_axis(local_axis)[:, 0]
        z_hat      = world_axis / (float(np.linalg.norm(world_axis)) or 1.0)
        delta      = math.atan2(float(np.dot(np.cross(wx, correct_x), z_hat)),
                                float(np.dot(wx, correct_x)))
        aliased.append(helix.model_copy(update={
            "id":          namespaced_id,
            "axis_start":  Vec3.from_array(ws),
            "axis_end":    Vec3.from_array(we),
            "phase_offset": helix.phase_offset + delta,
            # Loop/skip records reference original-helix bp indices, which
            # don't apply to the cross-part complement (it's not part of
            # the OH's helix geometry pass). Drop them to keep the
            # synthetic pass clean.
            "loop_skips":  [],
        }))

    synthetic = Design(
        helices=list(assembly.assembly_helices) + aliased,
        strands=list(assembly.assembly_strands),
        lattice_type="HONEYCOMB",   # LatticeType enum value (lowercase 500s the endpoint)
        metadata=DesignMetadata(name="__linkers__"),
    )
    return {
        # include_linker_helices=True: render the world-space __lnk__ bridge
        # helix directly (the assembly synthetic design has no
        # overhang_connections, so _emit_bridge_nucs can't emit the bridge).
        "nucleotides":     _geometry_for_design(synthetic, include_linker_helices=True),
        "helix_axes":      deformed_helix_axes(synthetic),
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

    geo  = _linker_geometry_for_assembly(assembly)
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


# ── Part library (legacy — scans parts-library/ dir) ──────────────────────────

@router.get("/assembly/library", status_code=200)
def get_library() -> dict:
    """
    Scan the parts-library/ directory for *.nadoc files.

    Returns a list of PartLibraryEntry objects.  For each file, reads any
    interface_points from a Part wrapper if the file contains one; otherwise
    returns an empty list.  The sha256 digest is computed fresh on each call
    (files are small; caching is not worth the complexity yet).
    """
    from backend.core.models import Design
    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in sorted(_LIBRARY_DIR.glob("*.nadoc")):
        try:
            sha = _sha256_file(p)
            ipts: list = []
            try:
                Design.from_json(p.read_text(encoding="utf-8"))
                # Interface points may be stored on a Part wrapper or on the design itself
                # For now we return an empty list — Part wrapper not required
            except Exception:
                pass
            entries.append(PartLibraryEntry(
                name=p.stem,
                path=str(p.relative_to(_PROJECT_ROOT)),
                sha256=sha,
                interface_points=ipts,
            ).model_dump())
        except Exception:
            continue
    return {"entries": entries}


@router.post("/assembly/library/register", status_code=201)
def register_library_entry(body: RegisterLibraryRequest) -> dict:
    """Manually register a .nadoc file in the library by recording its path and hash."""
    p = Path(body.path)
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()
    if not p.is_file():
        raise HTTPException(400, detail=f"File not found: {body.path!r}")
    sha = _sha256_file(p)
    entry = PartLibraryEntry(
        name=body.name or p.stem,
        path=str(p.relative_to(_PROJECT_ROOT)),
        sha256=sha,
        tags=body.tags,
    )
    return {"entry": entry.model_dump()}


@router.post("/assembly/library/rescan", status_code=200)
def rescan_library() -> dict:
    """Re-hash all files in parts-library/ and report missing ones."""
    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    found = []
    for p in sorted(_LIBRARY_DIR.glob("*.nadoc")):
        found.append({"path": str(p.relative_to(_PROJECT_ROOT)), "sha256": _sha256_file(p)})
    return {"files": found, "count": len(found)}


# ── Instance design / geometry ────────────────────────────────────────────────

@router.get("/assembly/instances/{instance_id}/design", status_code=200)
def get_instance_design(instance_id: str) -> dict:
    """Resolve and return the base Design for a PartInstance (without cluster_transform_overrides).

    Used by the part-context editor and cluster panel — they need the source design as
    authored, not the assembly-level override positions.  For geometry rendering use the
    /geometry endpoint which applies overrides and includes "design" in the response.
    """
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    return {"design": design.to_dict()}


@router.get("/assembly/instances/{instance_id}/geometry", status_code=200)
def get_instance_geometry(instance_id: str) -> dict:
    """
    Compute and return nucleotide geometry for a PartInstance's Design.

    Geometry is returned in the instance's local frame (transform NOT applied).
    The frontend applies the Mat4x4 transform to the Three.js Group matrix.
    Uses the same _geometry_for_design / deformed_helix_axes functions as the
    main design geometry endpoint.

    Response shape: ``{ nucleotides_compact, helix_axes, design }``. The
    compact wire format is ~50% smaller than the dict-per-nuc form and
    parses ~50% faster in the browser — substantial when a single instance
    is a 60k-bp origami.

    Response includes "design" (with cluster_transform_overrides applied) so
    callers do not need a separate /design request.
    """
    from backend.api.crud import _geometry_for_design, _compact_geometry_from_nucleotides, _inject_joint_world_axes
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)

    key    = _geo_cache_key(inst)
    cached = _geo_cache_get(key) if key else None
    if cached:
        return {
            "nucleotides_compact": _compact_geometry_from_nucleotides(cached["nucleotides"]),
            "helix_axes":          cached["helix_axes"],
            "design":              cached.get("design"),
        }

    design      = _display_design(_design_with_instance_overrides(inst))
    nucleotides = _geometry_for_design(design)
    axes        = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    design_dict = design.to_dict()
    # Derive world-space cluster-joint axes (axis_origin / axis_direction) from the
    # local-frame storage, same as the design-view GET. Without this the assembly
    # part-joint drag reads undefined joint.axis_origin and throws.
    _inject_joint_world_axes(design_dict)
    if key:
        _geo_cache_set(key, {"nucleotides": nucleotides, "helix_axes": axes,
                             "design": design_dict})
    return {
        "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
        "helix_axes":          axes,
        "design":              design_dict,
    }


@router.get("/assembly/instances/{instance_id}/bend-centers", status_code=200)
def get_instance_bend_centers(instance_id: str) -> dict:
    """
    Return one connector per bend op for this part instance, at the bend's
    center of curvature with its normal along the bend axis.

    Used by the assembly editor's Define-Mate flow to expose bend centers as
    pickable connectors (CAD-style "mate two arcs by their circle centers").

    Geometry is in the instance's local frame — frontend applies the instance
    placement transform exactly like for blunt-end connectors.

    Response: ``{ bend_centers: [{label, position, normal, cluster_id, bend_index, radius_nm}] }``
    """
    from backend.core.deformation import compute_bend_centers
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _display_design(_design_with_instance_overrides(inst, _assembly_source_path(assembly)))
    return {"bend_centers": compute_bend_centers(design)}


@router.get("/assembly/instances/{instance_id}/atomistic-geometry", status_code=200)
def get_instance_atomistic_geometry(instance_id: str) -> dict:
    """
    Compute and return the heavy-atom all-atom model for a PartInstance's design.

    Geometry is returned in the instance's local frame — same convention as
    /assembly/instances/{id}/geometry.  The frontend applies the instance
    placement transform via the Three.js Group matrix.

    Response: { atoms: [...], bonds: [[i,j], ...], element_meta: {...} }
    Same schema as GET /api/design/atomistic.
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _display_design(_load_design_from_source(inst.source))
    return atomistic_to_json(build_atomistic_model(design))


@router.get("/assembly/instances/{instance_id}/surface-geometry", status_code=200)
def get_instance_surface_geometry(
    instance_id:    str,
    color_mode:     str   = "strand",
    grid_spacing:   float = 0.20,
    probe_radius:   float = 0.28,
    radius_inflate: float = 1.30,
    smooth:         int   = 15,
) -> dict:
    """
    Compute and return a triangulated molecular surface for a PartInstance's design.

    Geometry is returned in the instance's local frame — same convention as
    /assembly/instances/{id}/atomistic-geometry; the frontend instances the mesh
    at each placement transform.  Defaults match GET /api/design/surface
    (radius_inflate=1.30, smooth=15) so the visual matches the design view and
    the STL export.

    Response: { vertices, faces, vertex_colors, stats } — same schema as
    GET /api/design/surface.
    """
    import time
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _display_design(_load_design_from_source(inst.source))
    model    = build_atomistic_model(design)
    t0   = time.perf_counter()
    mesh = compute_surface(
        model.atoms,
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
    )
    mesh = smooth_mesh(mesh, iterations=smooth)
    t_ms = (time.perf_counter() - t0) * 1000.0
    return surface_to_json(mesh, design, color_mode=color_mode, t_ms=t_ms)


@router.get("/assembly/geometry", status_code=200)
def get_assembly_geometry() -> dict:
    """
    Batch geometry for all visible instances in one request.

    **Response shape (Phase-3 dedup):**
    ```
    {
      "sources":   { "<srcKey>": { "nucleotides_compact": {...}, "helix_axes": [...], "design": {...} } },
      "instances": { "<instId>": "<srcKey>", ... },
      "errors":    { "<instId>": "<message>", ... }   # only for instances that failed
    }
    ```

    Two N-clone instances of the same part share **one** source entry.
    The compact wire format is ~50% smaller than the per-nuc dict form
    and parses proportionally faster.

    Invisible instances are omitted. The per-instance route
    ``/assembly/instances/{id}/geometry`` is unchanged in shape (it returns
    one ``nucleotides_compact`` directly).
    """
    from backend.api.crud import _geometry_for_design, _compact_geometry_from_nucleotides
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    assembly = assembly_state.get_or_404()
    sources:        dict[str, dict] = {}
    instance_to_src: dict[str, str] = {}
    errors:         dict[str, str]  = {}

    def _source_key_for(inst) -> str:
        # Reuse the geometry-cache key (file path + mtime suffix, or
        # inline-design id, plus cluster-transform overrides hash) so two
        # instances of the same part with no overrides share one source.
        return _geo_cache_key(inst) or f"inst:{inst.id}"

    for inst in assembly.instances:
        if not inst.visible:
            continue
        try:
            src_key = _source_key_for(inst)
            instance_to_src[inst.id] = src_key
            if src_key in sources:
                continue  # already computed for an earlier identical-source instance

            key    = _geo_cache_key(inst)
            cached = _geo_cache_get(key) if key else None
            if cached:
                sources[src_key] = {
                    "nucleotides_compact": _compact_geometry_from_nucleotides(cached["nucleotides"]),
                    "helix_axes":          cached["helix_axes"],
                    "design":              cached.get("design"),
                }
                continue

            design      = _display_design(_design_with_instance_overrides(inst))
            nucleotides = _geometry_for_design(design)
            axes        = deformed_helix_axes(design)
            _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
            design_dict = design.to_dict()
            if key:
                _geo_cache_set(key, {
                    "nucleotides": nucleotides,
                    "helix_axes":  axes,
                    "design":      design_dict,
                })
            sources[src_key] = {
                "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
                "helix_axes":          axes,
                "design":              design_dict,
            }
        except Exception as exc:
            errors[inst.id] = str(exc)
    return {"sources": sources, "instances": instance_to_src, "errors": errors}


# ── Debug endpoints ───────────────────────────────────────────────────────────

@router.get("/debug/assembly", status_code=200)
def debug_assembly() -> dict:
    """Return the full active assembly JSON plus summary counts."""
    assembly = assembly_state.get_or_create()
    return {
        "assembly":       assembly.to_dict(),
        "instance_count": len(assembly.instances),
        "joint_count":    len(assembly.joints),
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
    joint    = _find_joint(assembly, joint_id)
    inst_b   = _find_instance(assembly, joint.instance_b_id)
    base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
    result   = _apply_revolute_joint(base_mat, joint.axis_origin, joint.axis_direction, angle)
    return {
        "joint_id":          joint_id,
        "angle_rad":         angle,
        "angle_deg":         math.degrees(angle),
        "instance_b_id":     joint.instance_b_id,
        "transform_preview": result.flatten().tolist(),
    }
