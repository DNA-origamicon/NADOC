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

import asyncio
import hashlib
import json
import math
import os
import shutil
from collections import OrderedDict
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api import state as design_state
from backend.core.models import (
    Assembly,
    AssemblyConfigurationSnapshot,
    AssemblyInstanceConfigState,
    AssemblyJointConfigState,
    AnimationKeyframe,
    AssemblyJoint,
    CameraPose,
    ClusterRigidTransform,
    ConnectionType,
    DesignAnimation,
    DesignMetadata,
    Helix,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartLibraryEntry,
    PartSourceFile,
    PartSourceInline,
    Strand,
    Vec3,
)

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
    """Standard response shape for assembly mutations."""
    return {"assembly": assembly.to_dict()}


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


def _safe_workspace_path(rel_path: str) -> Path:
    """Resolve rel_path within _WORKSPACE_DIR, rejecting path traversal attempts."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = (_WORKSPACE_DIR / rel_path).resolve()
    if not resolved.is_relative_to(_WORKSPACE_DIR.resolve()):
        raise HTTPException(400, detail="Invalid path: outside workspace")
    return resolved


def _dedup_filename(stem: str, suffix: str) -> str:
    """Return a filename that does not already exist in _WORKSPACE_DIR."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = f"{stem}{suffix}"
    if not (_WORKSPACE_DIR / candidate).exists():
        return candidate
    n = 2
    while (_WORKSPACE_DIR / f"{stem}_{n}{suffix}").exists():
        n += 1
    return f"{stem}_{n}{suffix}"


def _patch_references(old_ref: str, new_ref: str) -> list[str]:
    """Cascade-update PartSourceFile.path across all on-disk .nass files and the
    in-memory assembly.

    old_ref / new_ref:
      - file rename/move  → plain paths, e.g. "parts/2hb.nadoc"
      - folder rename/move → paths ending with "/", e.g. "old_dir/" → "new_dir/"
    """
    is_folder = old_ref.endswith("/")
    patched: list[str] = []

    def _remap(sp: str) -> str | None:
        if is_folder:
            return (new_ref + sp[len(old_ref):]) if sp.startswith(old_ref) else None
        return new_ref if sp == old_ref else None

    # ── On-disk .nass files ────────────────────────────────────────────────────
    for nass_file in _WORKSPACE_DIR.rglob("*.nass"):
        try:
            raw  = nass_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            changed = False
            for inst in data.get("instances", []):
                src = inst.get("source", {})
                if src.get("type") == "file":
                    new_sp = _remap(src.get("path", ""))
                    if new_sp is not None:
                        src["path"] = new_sp
                        changed = True
            if changed:
                nass_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                patched.append(str(nass_file.relative_to(_WORKSPACE_DIR)))
        except Exception:
            continue

    # ── In-memory assembly ─────────────────────────────────────────────────────
    asm = assembly_state.get_assembly()
    if asm:
        new_insts = list(asm.instances)
        changed = False
        for idx, inst in enumerate(new_insts):
            if inst.source.type == "file":
                new_sp = _remap(inst.source.path)
                if new_sp is not None:
                    new_insts[idx] = inst.model_copy(
                        update={"source": PartSourceFile(path=new_sp)}
                    )
                    changed = True
        if changed:
            assembly_state.set_assembly_silent(
                asm.model_copy(update={"instances": new_insts})
            )

    return patched


def _apply_revolute_joint(
    base_mat: np.ndarray,         # 4×4 row-major base transform of instance_b
    axis_origin: list[float],
    axis_direction: list[float],
    angle_rad: float,
) -> np.ndarray:
    """
    Return a new 4×4 row-major transform for instance_b after applying a
    revolute joint rotation of *angle_rad* about the given world-space axis.

    The axis is fixed in world space: points on the axis do not move.
    Formula: p_new = o + R @ (p_base_origin - o) where p_base_origin is the
    world-space origin of instance_b at angle=0 (from base_mat).
    """
    from scipy.spatial.transform import Rotation
    o = np.array(axis_origin, dtype=float)
    d = np.array(axis_direction, dtype=float)
    d_norm = np.linalg.norm(d)
    if d_norm < 1e-9:
        return base_mat
    d = d / d_norm

    R = Rotation.from_rotvec(d * angle_rad).as_matrix()  # 3×3

    # Build 4×4 result.  The rotation is applied in world space about axis_origin.
    # Translation component: t_new = o + R @ (t_base - o)
    t_base = base_mat[:3, 3]   # column 3 in row-major = last column
    t_new  = o + R @ (t_base - o)

    # Rotation component: R_new = R @ R_base
    R_base = base_mat[:3, :3]
    R_new  = R @ R_base

    result = np.eye(4)
    result[:3, :3] = R_new
    result[:3, 3]  = t_new
    return result


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

def _fk_apply_to_joint(joint, delta: np.ndarray) -> None:
    """Apply a world-space delta to a joint's axis_origin and axis_direction."""
    o = np.append(joint.axis_origin, 1.0)
    joint.axis_origin = (delta @ o)[:3].tolist()
    d = np.append(joint.axis_direction, 0.0)
    d_new = (delta @ d)[:3]
    norm = np.linalg.norm(d_new)
    joint.axis_direction = (d_new / norm if norm > 1e-9 else d_new).tolist()


def _fk_expand_rigid_group(assembly, instance_id: str, delta: np.ndarray,
                            visited: set, queue: list) -> None:
    """BFS over rigid joints (bidirectional); apply delta to each new member."""
    bfs = [instance_id]
    while bfs:
        cur = bfs.pop(0)
        for j in assembly.joints:
            if j.joint_type != 'rigid' or not j.instance_a_id or not j.instance_b_id:
                continue
            if j.instance_a_id == cur:
                nxt = j.instance_b_id
            elif j.instance_b_id == cur:
                nxt = j.instance_a_id
            else:
                continue
            if nxt in visited:
                continue
            m = next((i for i in assembly.instances if i.id == nxt), None)
            if not m or m.fixed:
                continue
            m.transform = Mat4x4.from_array(delta @ m.transform.to_array())
            if m.base_transform:
                m.base_transform = Mat4x4.from_array(delta @ m.base_transform.to_array())
            visited.add(nxt)
            queue.append(nxt)
            bfs.append(nxt)


def _fk_propagate(assembly, parent_ids: set, delta: np.ndarray, visited: set) -> None:
    """BFS FK propagation from parent_ids through all non-rigid kinematic children."""
    queue = list(parent_ids)
    while queue:
        pid = queue.pop(0)
        for j in assembly.joints:
            if j.instance_a_id != pid or j.joint_type == 'rigid':
                continue
            cid = j.instance_b_id
            if not cid or cid in visited:
                continue
            child = next((i for i in assembly.instances if i.id == cid), None)
            if not child or child.fixed:
                # Fixed child: do NOT update axis_origin — it must remain anchored at the
                # fixed child's connector, not drift with the parent's motion.
                continue
            _fk_apply_to_joint(j, delta)
            child.transform = Mat4x4.from_array(delta @ child.transform.to_array())
            if child.base_transform:
                child.base_transform = Mat4x4.from_array(delta @ child.base_transform.to_array())
            visited.add(cid)
            _fk_expand_rigid_group(assembly, cid, delta, visited, queue)
            queue.append(cid)


def _move_instance_with_fk_delta(assembly, instance_id: str, delta: np.ndarray, visited: set) -> bool:
    inst = next((i for i in assembly.instances if i.id == instance_id), None)
    if not inst or inst.fixed or instance_id in visited:
        return False
    inst.transform = Mat4x4.from_array(delta @ inst.transform.to_array())
    if inst.base_transform:
        inst.base_transform = Mat4x4.from_array(delta @ inst.base_transform.to_array())
    visited.add(instance_id)
    _fk_expand_rigid_group(assembly, instance_id, delta, visited, [])
    _fk_propagate(assembly, {instance_id}, delta, visited)
    return True


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
    moved_any = False
    for j in assembly.joints:
        other_id = None
        if j.instance_a_id == instance_id and cluster_id in _joint_side_cluster_ids(assembly, j, "a"):
            other_id = j.instance_b_id
        elif j.instance_b_id == instance_id and cluster_id in _joint_side_cluster_ids(assembly, j, "b"):
            other_id = j.instance_a_id
        if not other_id:
            continue
        if _move_instance_with_fk_delta(assembly, other_id, delta, visited):
            moved_any = True
            _fk_apply_to_joint(j, delta)
    if moved_any:
        _enforce_connector_coincidence(assembly, visited)
    return visited


def _get_connector_world(instance: 'PartInstance', label: str) -> 'np.ndarray | None':
    """World-space position of a named InterfacePoint on an instance, or None."""
    ip = next((p for p in instance.interface_points if p.label == label), None)
    if ip is None:
        return None
    T = _mat4_from_model(instance.transform)
    return (T @ np.array([ip.position.x, ip.position.y, ip.position.z, 1.0], dtype=float))[:3]


def _enforce_connector_coincidence(assembly, visited: set) -> None:
    """
    Post-pass: for every rigid/revolute joint where instance_b moved but instance_a
    did not, translate instance_b so connector_b coincides with connector_a.

    Keeps axis_origin in sync and propagates any residual snap to inst_b's subtree.
    This prevents free-drags of constrained children from separating mated connectors.
    """
    for cid in list(visited):
        for j in assembly.joints:
            if j.instance_b_id != cid:
                continue
            if j.joint_type not in ('rigid', 'revolute'):
                continue
            if not j.connector_a_label or not j.connector_b_label:
                continue
            if j.instance_a_id in visited:
                continue  # parent moved too — delta already preserves coincidence
            if not j.instance_a_id:
                continue  # world-anchored joints have no parent instance to align to
            inst_b = next((i for i in assembly.instances if i.id == cid), None)
            inst_a = next((i for i in assembly.instances if i.id == j.instance_a_id), None)
            if not inst_b or not inst_a:
                continue
            cb = _get_connector_world(inst_b, j.connector_b_label)
            ca = _get_connector_world(inst_a, j.connector_a_label)
            if cb is None or ca is None:
                continue
            snap = ca - cb
            if np.linalg.norm(snap) < 1e-6:
                continue
            snap_d = np.eye(4, dtype=float)
            snap_d[:3, 3] = snap
            T_b = _mat4_from_model(inst_b.transform)
            inst_b.transform = Mat4x4.from_array(snap_d @ T_b)
            if inst_b.base_transform:
                inst_b.base_transform = Mat4x4.from_array(
                    snap_d @ _mat4_from_model(inst_b.base_transform))
            j.axis_origin = ca.tolist()
            # Propagate snap down inst_b's kinematic subtree
            snap_vis: set = {cid}
            _fk_expand_rigid_group(assembly, cid, snap_d, snap_vis, [])
            _fk_propagate(assembly, {cid}, snap_d, snap_vis)


# ── Request bodies ────────────────────────────────────────────────────────────

class AddInstanceRequest(BaseModel):
    source: dict                         # raw dict; validated below
    name: str = "Part"
    transform: Optional[dict] = None     # Mat4x4 dict; defaults to identity


_VALID_REPRESENTATIONS = ('full', 'beads', 'cylinders', 'vdw', 'ballstick', 'hull-prism')

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


class PatchJointRequest(BaseModel):
    name: Optional[str] = None
    joint_type: Optional[str] = None  # changing type resets current_value to 0
    current_value: Optional[float] = None
    axis_origin: Optional[list[float]] = None
    axis_direction: Optional[list[float]] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    silent: Optional[bool] = None  # True during animation playback (suppress undo push)


class AddLinkerHelixRequest(BaseModel):
    axis_start: list[float]         # [x, y, z] nm
    axis_end:   list[float]         # [x, y, z] nm
    length_bp:  int
    phase_offset: float = 0.0
    id: Optional[str] = None        # auto-generated if omitted


class AddLinkerStrandRequest(BaseModel):
    id: Optional[str] = None        # prefix with "__vsc__" for virtual scaffold connections
    strand_type: str = "staple"
    domains: list[dict] = []
    color: Optional[str] = None
    notes: Optional[str] = None     # JSON string; VSC metadata stored here


class AssemblyLoadRequest(BaseModel):
    path: str


class CreateAssemblyRequest(BaseModel):
    name: str = "Untitled"


class AssemblyImportRequest(BaseModel):
    content: str   # raw JSON string


class PatchInstanceDesignRequest(BaseModel):
    content: str  # raw Design JSON


class RegisterLibraryRequest(BaseModel):
    path: str
    name: Optional[str] = None
    tags: list[str] = []


class UploadFileRequest(BaseModel):
    content: str              # raw JSON string
    filename: str             # e.g. "my_part.nadoc"
    dest_path: Optional[str] = None   # explicit workspace-relative path (skips auto-dedup)
    overwrite: bool = False


class SaveAssemblyRequest(BaseModel):
    filename: Optional[str] = None   # stem only (backward compat)
    path: Optional[str] = None       # full workspace-relative path, takes priority over filename
    overwrite: bool = True


class SaveDesignWorkspaceRequest(BaseModel):
    path: str
    overwrite: bool = True


class MkdirRequest(BaseModel):
    path: str   # workspace-relative folder path to create


class RenameRequest(BaseModel):
    path: str       # current workspace-relative path (file or folder)
    new_name: str   # basename only — no path separators


class MoveRequest(BaseModel):
    path: str           # current workspace-relative path
    dest_folder: str    # destination folder (workspace-relative), "" = workspace root


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
    assembly_state.clear_history()
    assembly_state.set_assembly(assembly)
    return _assembly_response(assembly)


@router.post("/assembly/import", status_code=200)
def import_assembly(body: AssemblyImportRequest) -> dict:
    """Load an assembly from raw JSON content sent by the browser."""
    try:
        assembly = Assembly.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to parse assembly: {exc}") from exc
    assembly_state.clear_history()
    assembly_state.set_assembly(assembly)
    return _assembly_response(assembly)


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
    assembly_state.snapshot()
    new_instances = list(assembly.instances) + [inst]
    assembly_state.set_assembly_silent(assembly.model_copy(update={"instances": new_instances}))
    return _assembly_response(assembly_state.get_or_404())


class PropagateFKRequest(BaseModel):
    instance_id: str
    transform: dict   # {values: [16 floats], row-major}


@router.post("/assembly/propagate_fk", status_code=200)
def propagate_fk(body: PropagateFKRequest) -> dict:
    """Move one instance to a new world transform and propagate FK to all kinematic descendants.

    The root instance has its base_transform nulled (user directly placed it).
    All descendant instances have their transforms and base_transforms updated by
    the same delta, so joint values remain visually unchanged.
    Joint axes along the propagation path are also updated.
    """
    assembly = assembly_state.get_or_404()
    inst = next((i for i in assembly.instances if i.id == body.instance_id), None)
    if not inst:
        raise HTTPException(404, detail=f"Instance {body.instance_id} not found")
    if inst.fixed:
        raise HTTPException(400, detail=f"Instance {body.instance_id} is fixed and cannot be moved")
    assembly_state.snapshot()

    old_T = inst.transform.to_array()
    new_T = np.array(body.transform["values"], dtype=float).reshape(4, 4)
    try:
        delta = new_T @ np.linalg.inv(old_T)
    except np.linalg.LinAlgError:
        raise HTTPException(400, detail="Instance transform is singular")

    # Root: directly moved by user — null base_transform so next joint drive uses new position
    inst.transform = Mat4x4(values=[float(v) for v in new_T.flatten()])
    inst.base_transform = None

    # Expand root's rigid group and propagate FK to all kinematic descendants
    visited = {body.instance_id}
    _fk_expand_rigid_group(assembly, body.instance_id, delta, visited, [])
    _fk_propagate(assembly, visited.copy(), delta, visited)

    # Re-snap any rigid/revolute joint children that moved without their parent,
    # ensuring mated connectors remain coincident after the move.
    _enforce_connector_coincidence(assembly, visited)

    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly)


@router.post("/assembly/resolve", status_code=200)
def resolve_assembly() -> dict:
    """Re-apply all joint constraints in topological order (BFS from fixed/root instances).

    Returns the updated assembly plus solve_status: {joint_id: {satisfied, discrepancy}}
    reflecting the state *before* re-applying — i.e. which joints were out of sync.
    """
    assembly = assembly_state.get_or_404()

    # ── Pre-resolve satisfaction check ───────────────────────────────────────
    solve_status: dict = {}
    for joint in assembly.joints:
        if joint.joint_type not in ("revolute", "prismatic"):
            solve_status[joint.id] = {"satisfied": True, "discrepancy": 0.0}
            continue
        inst_b = next((i for i in assembly.instances if i.id == joint.instance_b_id), None)
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
            inst_b = next((i for i in assembly.instances if i.id == child_id), None)
            if not inst_b:
                visited.add(child_id)
                continue

            if joint.joint_type in ("revolute", "prismatic"):
                # Re-derive axis_origin from the live connector_a world position so that
                # any prior axis drift is corrected before re-applying the joint formula.
                # BFS processes parents before children, so inst_a.transform is already correct.
                if joint.connector_a_label and joint.instance_a_id:
                    inst_a_live = next((i for i in assembly.instances if i.id == joint.instance_a_id), None)
                    if inst_a_live:
                        ca = _get_connector_world(inst_a_live, joint.connector_a_label)
                        if ca is not None:
                            joint.axis_origin = ca.tolist()
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
                    _fk_expand_rigid_group(assembly, child_id, delta, fk_vis, [])
                    _fk_propagate(assembly, fk_vis.copy(), delta, fk_vis)
                    visited.update(fk_vis)
                    for nxt in fk_vis - {child_id}:
                        if nxt not in visited:
                            queue.append(nxt)
                except np.linalg.LinAlgError:
                    pass

            visited.add(child_id)
            queue.append(child_id)

    assembly_state.set_assembly(assembly)
    resp = _assembly_response(assembly)
    resp["solve_status"] = solve_status
    return resp


class BatchPatchItem(BaseModel):
    id: str
    transform: Optional[dict] = None


class BatchPatchRequest(BaseModel):
    patches: list[BatchPatchItem]


@router.patch("/assembly/instances/batch", status_code=200)
def batch_patch_instances(body: BatchPatchRequest) -> dict:
    """Patch transforms on multiple instances atomically. Single undo entry."""
    assembly = assembly_state.get_or_404()
    patched_ids: set = set()
    for item in body.patches:
        inst = next((i for i in assembly.instances if i.id == item.id), None)
        if not inst:
            raise HTTPException(404, detail=f"Instance {item.id} not found")
        if item.transform:
            inst.transform = Mat4x4(**item.transform)
            inst.base_transform = None
            patched_ids.add(item.id)
    if patched_ids:
        _enforce_connector_coincidence(assembly, patched_ids)
    assembly_state.set_assembly(assembly)
    return _assembly_response(assembly)


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
    if body.fixed is not None:
        meta_updates["fixed"] = body.fixed
    if body.representation is not None:
        if body.representation not in _VALID_REPRESENTATIONS:
            raise HTTPException(400, detail=f"representation must be one of {_VALID_REPRESENTATIONS}")
        meta_updates["representation"] = body.representation
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
    if body.transform is not None:
        old_T = _mat4_from_model(inst.transform)
        new_T = np.array(body.transform["values"], dtype=float).reshape(4, 4)
        inst.transform      = Mat4x4(values=[float(v) for v in new_T.flatten()])
        inst.base_transform = None
        try:
            delta   = new_T @ np.linalg.inv(old_T)
            visited = {instance_id}
            _fk_expand_rigid_group(assembly, instance_id, delta, visited, [])
            _fk_propagate(assembly, visited.copy(), delta, visited)
            _enforce_connector_coincidence(assembly, visited)
        except np.linalg.LinAlgError:
            pass  # singular old transform — skip FK

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
    new_instances = [new_inst if i.id == instance_id else i for i in assembly.instances]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(assembly.model_copy(update={"instances": new_instances}))
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/instances/{instance_id}", status_code=200)
def delete_instance(instance_id: str) -> dict:
    """Remove a PartInstance and any joints that reference it."""
    assembly = assembly_state.get_or_404()
    _find_instance(assembly, instance_id)  # raises 404 if missing

    new_instances = [i for i in assembly.instances if i.id != instance_id]
    new_joints    = [j for j in assembly.joints
                     if j.instance_a_id != instance_id and j.instance_b_id != instance_id]

    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"instances": new_instances, "joints": new_joints})
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Joint routes ──────────────────────────────────────────────────────────────

@router.post("/assembly/joints", status_code=201)
def add_joint(body: AddJointRequest) -> dict:
    """Add an AssemblyJoint, snap instance_b to connector_a, and snapshot base_transform."""
    assembly = assembly_state.get_or_404()
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
    if body.connector_b_label:
        ip_b = next((p for p in inst_b.interface_points if p.label == body.connector_b_label), None)
        if ip_b is not None:
            if cluster_id_b is None:
                cluster_id_b = (_infer_cluster_ids_for_connector_label(inst_b, body.connector_b_label) or [ip_b.cluster_id])[0]
            T_b      = _mat4_from_model(inst_b.transform)
            cb_world = (T_b @ np.array([ip_b.position.x, ip_b.position.y,
                                        ip_b.position.z, 1.0], dtype=float))[:3]
            if body.connector_a_label and body.instance_a_id:
                inst_a = _find_instance(assembly, body.instance_a_id)
                ip_a   = next((p for p in inst_a.interface_points
                               if p.label == body.connector_a_label), None)
                if ip_a is not None:
                    if cluster_id_a is None:
                        cluster_id_a = (_infer_cluster_ids_for_connector_label(inst_a, body.connector_a_label) or [ip_a.cluster_id])[0]
                    T_a      = _mat4_from_model(inst_a.transform)
                    ca_world = (T_a @ np.array([ip_a.position.x, ip_a.position.y,
                                                ip_a.position.z, 1.0], dtype=float))[:3]
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

    assembly_state.snapshot()
    new_assembly = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # Propagate snap to inst_b's kinematic children (so they follow the alignment)
    if snap_delta is not None:
        snap_vis: set = {body.instance_b_id}
        _fk_expand_rigid_group(new_assembly, body.instance_b_id, snap_delta, snap_vis, [])
        _fk_propagate(new_assembly, snap_vis.copy(), snap_delta, snap_vis)

    assembly_state.set_assembly_silent(new_assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/joints/{joint_id}", status_code=200)
def patch_joint(joint_id: str, body: PatchJointRequest) -> dict:
    """
    Update joint fields.  When current_value changes on a revolute joint,
    recomputes instance_b.transform from base_transform to avoid accumulation.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)

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
    if body.min_limit is not None:
        joint_updates["min_limit"] = body.min_limit
    if body.max_limit is not None:
        joint_updates["max_limit"] = body.max_limit

    value_changed = body.current_value is not None and body.current_value != joint.current_value
    if body.current_value is not None:
        # Clamp to limits if set
        val = body.current_value
        lo  = joint.min_limit if joint.min_limit is not None else -math.inf
        hi  = joint.max_limit if joint.max_limit is not None else  math.inf
        joint_updates["current_value"] = max(lo, min(hi, val))

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
            _fk_expand_rigid_group(new_assembly, new_joint.instance_b_id, delta, visited, [])
            _fk_propagate(new_assembly, visited.copy(), delta, visited)
            _enforce_connector_coincidence(new_assembly, visited)
        except np.linalg.LinAlgError:
            pass  # singular old transform — skip FK propagation

    assembly_state.set_assembly_silent(new_assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/joints/{joint_id}", status_code=200)
def delete_joint(joint_id: str) -> dict:
    """Remove an AssemblyJoint."""
    assembly = assembly_state.get_or_404()
    _find_joint(assembly, joint_id)  # raises 404 if missing
    new_joints = [j for j in assembly.joints if j.id != joint_id]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(assembly.model_copy(update={"joints": new_joints}))
    return _assembly_response(assembly_state.get_or_404())


# ── Instance connectors (InterfacePoints) ─────────────────────────────────────

class AddConnectorRequest(BaseModel):
    label: Optional[str] = None
    position: list[float]
    normal: list[float]
    cluster_id: Optional[str] = None


class CreateAssemblyConfigurationBody(BaseModel):
    name: Optional[str] = None


class PatchAssemblyConfigurationBody(BaseModel):
    name: Optional[str] = None
    overwrite_current: Optional[bool] = None


class CreateAssemblyCameraPoseBody(BaseModel):
    name: str = "Camera Pose"
    position: list[float]
    target: list[float]
    up: list[float]
    fov: float = 55.0
    orbit_mode: str = "trackball"


class PatchAssemblyCameraPoseBody(BaseModel):
    name: Optional[str] = None
    position: Optional[list[float]] = None
    target: Optional[list[float]] = None
    up: Optional[list[float]] = None
    fov: Optional[float] = None
    orbit_mode: Optional[str] = None


class ReorderAssemblyCameraPosesBody(BaseModel):
    ordered_ids: list[str]


@router.post("/assembly/instances/{instance_id}/connectors", status_code=201)
def add_connector(instance_id: str, body: AddConnectorRequest) -> dict:
    """Append an InterfacePoint (connector) to a PartInstance."""
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)

    # Auto-label if not supplied
    existing = {ip.label for ip in inst.interface_points}
    label    = body.label or next(
        f"C{i}" for i in range(1, 999) if f"C{i}" not in existing
    )
    if label in existing:
        raise HTTPException(400, detail=f"Connector label {label!r} already exists on this instance.")

    ip = InterfacePoint(
        label=label,
        position=Vec3(x=body.position[0], y=body.position[1], z=body.position[2]),
        normal=Vec3(x=body.normal[0], y=body.normal[1], z=body.normal[2]),
        connection_type=ConnectionType.COVALENT,
        cluster_id=body.cluster_id,
    )
    new_instances = [
        i.model_copy(update={"interface_points": [*i.interface_points, ip]})
        if i.id == instance_id else i
        for i in assembly.instances
    ]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(assembly.model_copy(update={"instances": new_instances}))
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/instances/{instance_id}/connectors/{label}", status_code=200)
def delete_connector(instance_id: str, label: str) -> dict:
    """Remove a named InterfacePoint from a PartInstance."""
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    if not any(ip.label == label for ip in inst.interface_points):
        raise HTTPException(404, detail=f"Connector {label!r} not found on instance {instance_id!r}.")
    new_instances = [
        i.model_copy(update={"interface_points": [ip for ip in i.interface_points if ip.label != label]})
        if i.id == instance_id else i
        for i in assembly.instances
    ]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(assembly.model_copy(update={"instances": new_instances}))
    return _assembly_response(assembly_state.get_or_404())


# ── Assembly configurations ──────────────────────────────────────────────────

def _capture_assembly_configuration(assembly: Assembly, name: str) -> AssemblyConfigurationSnapshot:
    return AssemblyConfigurationSnapshot(
        name=name,
        instance_states=[
            AssemblyInstanceConfigState(
                instance_id=inst.id,
                name=inst.name,
                transform=inst.transform,
                base_transform=inst.base_transform,
                joint_states=dict(inst.joint_states),
                cluster_transform_overrides=list(inst.cluster_transform_overrides),
            )
            for inst in assembly.instances
        ],
        joint_states=[
            AssemblyJointConfigState(
                joint_id=j.id,
                current_value=j.current_value,
                axis_origin=list(j.axis_origin),
                axis_direction=list(j.axis_direction),
            )
            for j in assembly.joints
        ],
    )


@router.post("/assembly/configurations", status_code=200)
def create_assembly_configuration(body: CreateAssemblyConfigurationBody = None) -> dict:
    """Capture current assembly instance/joint state as a named configuration."""
    assembly = assembly_state.get_or_create()
    idx = len(assembly.configurations) + 1
    cfg = _capture_assembly_configuration(assembly, (body.name if body and body.name else f"Config {idx}"))
    updated = assembly.model_copy(
        update={
            "configurations": [*assembly.configurations, cfg],
            "configuration_cursor": cfg.id,
        },
        deep=True,
    )
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.post("/assembly/configurations/{config_id}/restore", status_code=200)
def restore_assembly_configuration(config_id: str) -> dict:
    """Restore saved positions for instances present in the configuration.

    Instances and joints added after the configuration was captured are left as-is.
    """
    assembly = assembly_state.get_or_404()
    cfg = next((c for c in assembly.configurations if c.id == config_id), None)
    if cfg is None:
        raise HTTPException(404, detail=f"Configuration {config_id!r} not found.")

    state_by_id = {s.instance_id: s for s in cfg.instance_states}
    joint_by_id = {s.joint_id: s for s in cfg.joint_states}

    new_instances = []
    for inst in assembly.instances:
        state = state_by_id.get(inst.id)
        if state is None:
            new_instances.append(inst)
            continue
        new_instances.append(inst.model_copy(update={
            "transform": state.transform,
            "base_transform": state.base_transform,
            "joint_states": dict(state.joint_states),
            "cluster_transform_overrides": list(state.cluster_transform_overrides),
        }, deep=True))

    new_joints = []
    for joint in assembly.joints:
        state = joint_by_id.get(joint.id)
        if state is None:
            new_joints.append(joint)
            continue
        new_joints.append(joint.model_copy(update={
            "current_value": state.current_value,
            "axis_origin": list(state.axis_origin),
            "axis_direction": list(state.axis_direction),
        }, deep=True))

    updated = assembly.model_copy(update={
        "instances": new_instances,
        "joints": new_joints,
        "configuration_cursor": cfg.id,
    }, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.patch("/assembly/configurations/{config_id}", status_code=200)
def update_assembly_configuration(config_id: str, body: PatchAssemblyConfigurationBody) -> dict:
    """Rename a configuration or overwrite it with the current assembly state."""
    assembly = assembly_state.get_or_404()
    configs = list(assembly.configurations)
    idx = next((i for i, c in enumerate(configs) if c.id == config_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Configuration {config_id!r} not found.")

    current = configs[idx]
    if body.overwrite_current:
        replacement = _capture_assembly_configuration(assembly, body.name or current.name)
        replacement = replacement.model_copy(update={"id": current.id})
    else:
        patch = {}
        if body.name is not None:
            patch["name"] = body.name
        replacement = current.model_copy(update=patch)
    configs[idx] = replacement

    updated = assembly.model_copy(update={
        "configurations": configs,
        "configuration_cursor": replacement.id if body.overwrite_current else assembly.configuration_cursor,
    }, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.delete("/assembly/configurations/{config_id}", status_code=200)
def delete_assembly_configuration(config_id: str) -> dict:
    assembly = assembly_state.get_or_404()
    configs = [c for c in assembly.configurations if c.id != config_id]
    if len(configs) == len(assembly.configurations):
        raise HTTPException(404, detail=f"Configuration {config_id!r} not found.")
    cursor = assembly.configuration_cursor
    if cursor == config_id:
        cursor = configs[-1].id if configs else None
    updated = assembly.model_copy(update={
        "configurations": configs,
        "configuration_cursor": cursor,
    }, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


# ── Assembly camera poses ────────────────────────────────────────────────────

@router.post("/assembly/camera-poses", status_code=200)
def create_assembly_camera_pose(body: CreateAssemblyCameraPoseBody) -> dict:
    assembly = assembly_state.get_or_create()
    pose = CameraPose(
        name=body.name,
        position=body.position,
        target=body.target,
        up=body.up,
        fov=body.fov,
        orbit_mode=body.orbit_mode,
    )
    updated = assembly.model_copy(update={"camera_poses": [*assembly.camera_poses, pose]}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.patch("/assembly/camera-poses/{pose_id}", status_code=200)
def update_assembly_camera_pose(pose_id: str, body: PatchAssemblyCameraPoseBody) -> dict:
    assembly = assembly_state.get_or_create()
    poses = list(assembly.camera_poses)
    idx = next((i for i, p in enumerate(poses) if p.id == pose_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")
    poses[idx] = poses[idx].model_copy(update=body.model_dump(exclude_none=True))
    updated = assembly.model_copy(update={"camera_poses": poses}, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.delete("/assembly/camera-poses/{pose_id}", status_code=200)
def delete_assembly_camera_pose(pose_id: str) -> dict:
    assembly = assembly_state.get_or_create()
    poses = [p for p in assembly.camera_poses if p.id != pose_id]
    if len(poses) == len(assembly.camera_poses):
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")
    updated = assembly.model_copy(update={"camera_poses": poses}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.put("/assembly/camera-poses/reorder", status_code=200)
def reorder_assembly_camera_poses(body: ReorderAssemblyCameraPosesBody) -> dict:
    assembly = assembly_state.get_or_create()
    pose_map = {p.id: p for p in assembly.camera_poses}
    missing = [pid for pid in body.ordered_ids if pid not in pose_map]
    if missing:
        raise HTTPException(400, detail=f"Unknown pose IDs: {missing}")
    listed = set(body.ordered_ids)
    poses = [pose_map[pid] for pid in body.ordered_ids]
    poses += [p for p in assembly.camera_poses if p.id not in listed]
    updated = assembly.model_copy(update={"camera_poses": poses}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


# ── Linker helices ────────────────────────────────────────────────────────────

@router.post("/assembly/linker-helices", status_code=201)
def add_linker_helix(body: AddLinkerHelixRequest) -> dict:
    """Append a linker Helix to assembly.assembly_helices."""
    import uuid as _uuid
    assembly = assembly_state.get_or_404()
    helix = Helix(
        id=body.id or str(_uuid.uuid4()),
        axis_start=Vec3(x=body.axis_start[0], y=body.axis_start[1], z=body.axis_start[2]),
        axis_end=Vec3(x=body.axis_end[0], y=body.axis_end[1], z=body.axis_end[2]),
        length_bp=body.length_bp,
        phase_offset=body.phase_offset,
    )
    new_helices = list(assembly.assembly_helices) + [helix]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_helices": new_helices})
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/linker-helices/{helix_id}", status_code=200)
def delete_linker_helix(helix_id: str) -> dict:
    """Remove a linker helix by id."""
    assembly = assembly_state.get_or_404()
    new_helices = [h for h in assembly.assembly_helices if h.id != helix_id]
    if len(new_helices) == len(assembly.assembly_helices):
        raise HTTPException(404, detail=f"Linker helix {helix_id!r} not found.")
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_helices": new_helices})
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Linker strands ────────────────────────────────────────────────────────────

@router.post("/assembly/linker-strands", status_code=201)
def add_linker_strand(body: AddLinkerStrandRequest) -> dict:
    """
    Append a linker Strand to assembly.assembly_strands.

    Virtual scaffold connections use ids prefixed with '__vsc__' and encode
    endpoint metadata in the notes field as a JSON string.
    """
    import uuid as _uuid
    from backend.core.models import Domain, StrandType
    assembly = assembly_state.get_or_404()

    strand_id = body.id or str(_uuid.uuid4())
    try:
        stype = StrandType(body.strand_type)
    except ValueError:
        stype = StrandType.STAPLE

    domains = []
    for d in (body.domains or []):
        try:
            domains.append(Domain(**d))
        except Exception:
            pass

    strand = Strand(
        id=strand_id,
        strand_type=stype,
        domains=domains,
        color=body.color,
        notes=body.notes,
    )
    new_strands = list(assembly.assembly_strands) + [strand]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_strands": new_strands})
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/linker-strands/{strand_id}", status_code=200)
def delete_linker_strand(strand_id: str) -> dict:
    """Remove a linker strand by id."""
    assembly = assembly_state.get_or_404()
    new_strands = [s for s in assembly.assembly_strands if s.id != strand_id]
    if len(new_strands) == len(assembly.assembly_strands):
        raise HTTPException(404, detail=f"Linker strand {strand_id!r} not found.")
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_strands": new_strands})
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Linker geometry ───────────────────────────────────────────────────────────

@router.get("/assembly/linker-geometry", status_code=200)
def get_linker_geometry() -> dict:
    """
    Compute nucleotide geometry for the assembly's linker helices and strands.

    Builds a synthetic Design from assembly_helices + assembly_strands and
    runs the same geometry pipeline as the main design endpoint.  Returns
    {nucleotides, helix_axes} in the same format as instance geometry.

    Returns empty arrays when there are no linker helices.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes
    from backend.core.models import Design

    assembly = assembly_state.get_or_404()
    if not assembly.assembly_helices:
        return {"nucleotides": [], "helix_axes": {}}

    synthetic = Design(
        helices=list(assembly.assembly_helices),
        strands=list(assembly.assembly_strands),
        lattice_type="honeycomb",
        metadata=DesignMetadata(name="__linkers__"),
    )
    return {
        "nucleotides": _geometry_for_design(synthetic),
        "helix_axes":  deformed_helix_axes(synthetic),
    }


# ── Undo / Redo ───────────────────────────────────────────────────────────────

@router.post("/assembly/undo", status_code=200)
def undo_assembly() -> dict:
    """Undo the last assembly-level operation."""
    return _assembly_response(assembly_state.undo())


@router.post("/assembly/redo", status_code=200)
def redo_assembly() -> dict:
    """Redo the last undone assembly-level operation."""
    return _assembly_response(assembly_state.redo())


# ── Workspace library ─────────────────────────────────────────────────────────

@router.get("/library/files", status_code=200)
def list_library_files() -> list:
    """Scan workspace for .nadoc / .nass files and subdirectories, sorted by mtime desc."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in _WORKSPACE_DIR.rglob("*"):
        # Skip hidden files / system dirs
        rel_parts = p.relative_to(_WORKSPACE_DIR).parts
        if any(part.startswith(".") or part.startswith("__") for part in rel_parts):
            continue
        try:
            stat     = p.stat()
            rel      = str(p.relative_to(_WORKSPACE_DIR))
            mtime    = _dt.fromtimestamp(stat.st_mtime, tz=_tz.utc).isoformat()
            if p.is_dir():
                entries.append({
                    "name":       p.name,
                    "path":       rel,
                    "type":       "folder",
                    "mtime_iso":  mtime,
                    "size_bytes": 0,
                })
            elif p.suffix in (".nadoc", ".nass"):
                entries.append({
                    "name":       p.stem,
                    "path":       rel,
                    "type":       "assembly" if p.suffix == ".nass" else "part",
                    "mtime_iso":  mtime,
                    "size_bytes": stat.st_size,
                })
        except OSError:
            continue
    entries.sort(key=lambda e: e["mtime_iso"], reverse=True)
    return entries


@router.post("/library/upload", status_code=201)
def upload_library_file(body: UploadFileRequest) -> dict:
    """Save a .nadoc or .nass file to the workspace directory.

    If dest_path is given, write to that exact workspace-relative path (with
    optional overwrite check).  Otherwise auto-dedup in the workspace root.
    """
    fn = body.filename.strip()
    if not fn:
        raise HTTPException(400, detail="filename is required")
    p = Path(fn)
    if p.suffix not in (".nadoc", ".nass"):
        raise HTTPException(400, detail="filename must end with .nadoc or .nass")

    if body.dest_path:
        dest = _safe_workspace_path(body.dest_path)
        if dest.suffix not in (".nadoc", ".nass"):
            raise HTTPException(400, detail="dest_path must end with .nadoc or .nass")
        if not body.overwrite and dest.exists():
            raise HTTPException(409, detail=f"File already exists: {body.dest_path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_rel = body.dest_path
    else:
        safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in p.stem)
        if not safe_stem:
            safe_stem = "file"
        out_rel = _dedup_filename(safe_stem, p.suffix)
        dest = _WORKSPACE_DIR / out_rel

    dest.write_text(body.content, encoding="utf-8")
    return {
        "path": out_rel,
        "name": Path(out_rel).stem,
        "type": "assembly" if p.suffix == ".nass" else "part",
    }


@router.get("/library/content", status_code=200)
def get_library_file_content(path: str) -> dict:
    """Return the raw JSON content of a workspace file (path relative to workspace)."""
    dest = _safe_workspace_path(path)
    if not dest.is_file():
        raise HTTPException(404, detail=f"File not found in workspace: {path!r}")
    return {"content": dest.read_text(encoding="utf-8")}


@router.post("/library/mkdir", status_code=201)
def library_mkdir(body: MkdirRequest) -> dict:
    """Create a folder (and any missing parents) in the workspace."""
    dest = _safe_workspace_path(body.path)
    if dest.exists() and not dest.is_dir():
        raise HTTPException(400, detail=f"A file already exists at {body.path!r}.")
    dest.mkdir(parents=True, exist_ok=True)
    return {"path": body.path}


@router.patch("/library/rename", status_code=200)
def library_rename(body: RenameRequest) -> dict:
    """Rename a workspace file or folder; auto-patches all .nass references."""
    if "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(400, detail="new_name must be a plain basename (no path separators).")
    src = _safe_workspace_path(body.path)
    if not src.exists():
        raise HTTPException(404, detail=f"Not found: {body.path!r}")
    dest = src.parent / body.new_name
    if dest.exists() and dest.resolve() != src.resolve():
        raise HTTPException(409, detail=f"{body.new_name!r} already exists in the same folder.")
    is_dir   = src.is_dir()
    old_rel  = str(src.relative_to(_WORKSPACE_DIR))
    new_rel  = str((src.parent / body.new_name).relative_to(_WORKSPACE_DIR))
    src.rename(dest)
    old_ref  = old_rel + "/" if is_dir else old_rel
    new_ref  = new_rel + "/" if is_dir else new_rel
    patched  = _patch_references(old_ref, new_ref)
    return {"old_path": old_rel, "new_path": new_rel, "patched_assemblies": patched}


@router.post("/library/move", status_code=200)
def library_move(body: MoveRequest) -> dict:
    """Move a workspace file or folder to a new directory; auto-patches .nass references."""
    src = _safe_workspace_path(body.path)
    if not src.exists():
        raise HTTPException(404, detail=f"Not found: {body.path!r}")
    if body.dest_folder:
        dest_dir = _safe_workspace_path(body.dest_folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = _WORKSPACE_DIR
    dest = dest_dir / src.name
    if dest.resolve() == src.resolve():
        old_rel = str(src.relative_to(_WORKSPACE_DIR))
        return {"old_path": old_rel, "new_path": old_rel, "patched_assemblies": []}
    if dest.exists():
        raise HTTPException(409, detail=f"{src.name!r} already exists in the destination folder.")
    is_dir  = src.is_dir()
    old_rel = str(src.relative_to(_WORKSPACE_DIR))
    shutil.move(str(src), str(dest))
    new_rel = str(dest.relative_to(_WORKSPACE_DIR))
    old_ref = old_rel + "/" if is_dir else old_rel
    new_ref = new_rel + "/" if is_dir else new_rel
    patched = _patch_references(old_ref, new_ref)
    return {"old_path": old_rel, "new_path": new_rel, "patched_assemblies": patched}


@router.delete("/library/file", status_code=200)
def library_delete(path: str) -> dict:
    """Delete a workspace file or folder (folders are deleted recursively)."""
    dest = _safe_workspace_path(path)
    if not dest.exists():
        raise HTTPException(404, detail=f"Not found: {path!r}")
    if dest.is_dir():
        shutil.rmtree(str(dest))
    else:
        dest.unlink()
    return {"path": path}


@router.post("/design/save-workspace", status_code=200)
def save_design_to_workspace(body: SaveDesignWorkspaceRequest) -> dict:
    """Write the active in-memory design to a workspace file."""
    design = design_state.get_or_404()
    dest = _safe_workspace_path(body.path)
    if not body.overwrite and dest.exists():
        raise HTTPException(409, detail=f"File already exists: {body.path!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(design.to_json(), encoding="utf-8")
    return {"path": body.path}


@router.post("/assembly/save", status_code=200)
def save_assembly(body: SaveAssemblyRequest = None) -> dict:
    """Save the active assembly to the workspace as a .nass file.

    Inline PartInstances are auto-converted: their designs are saved as individual
    .nadoc files in the workspace and the instance source is updated to PartSourceFile.
    Returns the updated assembly (with file-backed sources) and the saved path.
    """
    assembly = assembly_state.get_or_404()
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Convert any inline instances to file-backed
    new_instances = list(assembly.instances)
    changed = False
    for idx, inst in enumerate(new_instances):
        if inst.source.type == "inline":
            design    = inst.source.design
            safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_"
                                for c in (design.metadata.name or inst.name or "part"))
            filename  = _dedup_filename(safe_stem, ".nadoc")
            (_WORKSPACE_DIR / filename).write_text(design.to_json(), encoding="utf-8")
            new_instances[idx] = inst.model_copy(update={"source": PartSourceFile(path=filename)})
            changed = True

    if changed:
        assembly = assembly.model_copy(update={"instances": new_instances})
        assembly_state.set_assembly_silent(assembly)

    # Determine output path
    if body and body.path:
        if not body.path.endswith(".nass"):
            raise HTTPException(400, detail="path must end with .nass")
        dest    = _safe_workspace_path(body.path)
        if not body.overwrite and dest.exists():
            raise HTTPException(409, detail=f"File already exists: {body.path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_rel = body.path
    else:
        asm_name  = (body.filename if body and body.filename else None) or assembly.metadata.name or "assembly"
        safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in asm_name)
        out_rel   = f"{safe_stem}.nass"
        dest      = _WORKSPACE_DIR / out_rel

    dest.write_text(assembly.to_json(), encoding="utf-8")
    return {"path": out_rel, **_assembly_response(assembly)}


@router.get("/library/events", status_code=200)
async def library_events_stream():
    """SSE stream: pushes file-changed / file-deleted events for workspace files."""
    from backend.api import library_events

    async def _generator():
        q: asyncio.Queue = asyncio.Queue()
        library_events.subscribe(q)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"ping"}\n\n'
        finally:
            library_events.unsubscribe(q)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
                design = Design.from_json(p.read_text(encoding="utf-8"))
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
    design   = _load_design_from_source(inst.source)
    return {"design": design.to_dict()}


@router.get("/assembly/instances/{instance_id}/geometry", status_code=200)
def get_instance_geometry(instance_id: str) -> dict:
    """
    Compute and return nucleotide geometry for a PartInstance's Design.

    Geometry is returned in the instance's local frame (transform NOT applied).
    The frontend applies the Mat4x4 transform to the Three.js Group matrix.
    Uses the same _geometry_for_design / deformed_helix_axes functions as the
    main design geometry endpoint.

    Response includes "design" (with cluster_transform_overrides applied) so
    callers do not need a separate /design request.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)

    key    = _geo_cache_key(inst)
    cached = _geo_cache_get(key) if key else None
    if cached:
        return {"nucleotides": cached["nucleotides"], "helix_axes": cached["helix_axes"],
                "design": cached.get("design")}

    design      = _design_with_instance_overrides(inst)
    nucleotides = _geometry_for_design(design)
    axes        = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    design_dict = design.to_dict()
    if key:
        _geo_cache_set(key, {"nucleotides": nucleotides, "helix_axes": axes,
                             "design": design_dict})
    return {"nucleotides": nucleotides, "helix_axes": axes, "design": design_dict}


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
    design   = _load_design_from_source(inst.source)
    return atomistic_to_json(build_atomistic_model(design))


@router.get("/assembly/geometry", status_code=200)
def get_assembly_geometry() -> dict:
    """
    Batch geometry for all visible instances in one request.

    Returns a dict keyed by instance ID:
      { "instances": { "<id>": { "nucleotides": [...], "helix_axes": [...], "design": {...} } } }

    Invisible instances are omitted. The per-instance routes remain available for
    backward compatibility and single-instance refreshes.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    assembly = assembly_state.get_or_404()
    result: dict[str, dict] = {}
    for inst in assembly.instances:
        if not inst.visible:
            continue
        try:
            key    = _geo_cache_key(inst)
            cached = _geo_cache_get(key) if key else None
            if cached:
                result[inst.id] = cached
                continue
            design      = _design_with_instance_overrides(inst)
            nucleotides = _geometry_for_design(design)
            axes        = deformed_helix_axes(design)
            _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
            entry = {
                "nucleotides": nucleotides,
                "helix_axes":  axes,
                "design":      design.to_dict(),
            }
            if key:
                _geo_cache_set(key, entry)
            result[inst.id] = entry
        except Exception as exc:
            # Surface per-instance errors without aborting the whole batch
            result[inst.id] = {"error": str(exc)}
    return {"instances": result}


# ── Animation CRUD ───────────────────────────────────────────────────────────

class CreateAssemblyAnimationBody(BaseModel):
    name: str = "Animation"
    fps: int = 30
    loop: bool = False


class PatchAssemblyAnimationBody(BaseModel):
    name: Optional[str] = None
    fps: Optional[int] = None
    loop: Optional[bool] = None


class CreateAssemblyKeyframeBody(BaseModel):
    name: str = ""
    camera_pose_id: Optional[str] = None
    configuration_id: Optional[str] = None
    hold_duration_s: float = 1.0
    transition_duration_s: float = 0.5
    easing: str = "ease-in-out"
    text: str = ""
    text_font_family: str = "sans-serif"
    text_font_size_px: int = 24
    text_color: str = "#ffffff"
    text_bold: bool = False
    text_italic: bool = False
    text_align: str = "center"


class PatchAssemblyKeyframeBody(BaseModel):
    name: Optional[str] = None
    camera_pose_id: Optional[str] = None
    configuration_id: Optional[str] = None
    hold_duration_s: Optional[float] = None
    transition_duration_s: Optional[float] = None
    easing: Optional[str] = None
    joint_values: Optional[dict] = None
    text: Optional[str] = None
    text_font_family: Optional[str] = None
    text_font_size_px: Optional[int] = None
    text_color: Optional[str] = None
    text_bold: Optional[bool] = None
    text_italic: Optional[bool] = None
    text_align: Optional[str] = None


class ReorderAssemblyKeyframesBody(BaseModel):
    ordered_ids: list[str]


def _find_animation(assembly: Assembly, anim_id: str) -> DesignAnimation:
    anim = next((a for a in assembly.animations if a.id == anim_id), None)
    if anim is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    return anim


@router.post("/assembly/animations", status_code=200)
def create_assembly_animation(body: CreateAssemblyAnimationBody) -> dict:
    """Create a new named animation on the assembly."""
    assembly = assembly_state.get_or_create()
    anim     = DesignAnimation(name=body.name, fps=body.fps, loop=body.loop)
    updated  = assembly.model_copy(
        update={"animations": list(assembly.animations) + [anim]}, deep=True,
    )
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.patch("/assembly/animations/{anim_id}", status_code=200)
def update_assembly_animation(anim_id: str, body: PatchAssemblyAnimationBody) -> dict:
    """Update animation metadata (name / fps / loop)."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    idx      = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    patch    = body.model_dump(include=body.model_fields_set)
    anims[idx] = anims[idx].model_copy(update=patch)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.delete("/assembly/animations/{anim_id}", status_code=200)
def delete_assembly_animation(anim_id: str) -> dict:
    """Remove an animation from the assembly."""
    assembly = assembly_state.get_or_create()
    anims    = [a for a in assembly.animations if a.id != anim_id]
    if len(anims) == len(assembly.animations):
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.post("/assembly/animations/{anim_id}/keyframes", status_code=200)
def create_assembly_keyframe(anim_id: str, body: CreateAssemblyKeyframeBody) -> dict:
    """
    Append a keyframe to an assembly animation.
    Automatically captures all assembly joint current_values into joint_values.
    """
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    idx      = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    # Auto-capture current joint values
    joint_values = {j.id: j.current_value for j in assembly.joints}

    kf = AnimationKeyframe(
        name=body.name,
        camera_pose_id=body.camera_pose_id,
        configuration_id=body.configuration_id,
        hold_duration_s=body.hold_duration_s,
        transition_duration_s=body.transition_duration_s,
        easing=body.easing,
        joint_values=joint_values,
        text=body.text,
        text_font_family=body.text_font_family,
        text_font_size_px=body.text_font_size_px,
        text_color=body.text_color,
        text_bold=body.text_bold,
        text_italic=body.text_italic,
        text_align=body.text_align,
    )
    anims[idx] = anims[idx].model_copy(
        update={"keyframes": list(anims[idx].keyframes) + [kf]}, deep=True,
    )
    updated = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.patch("/assembly/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def update_assembly_keyframe(anim_id: str, kf_id: str, body: PatchAssemblyKeyframeBody) -> dict:
    """Update a keyframe's properties (silent — no undo push for playback frames)."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    kfs      = list(anims[anim_idx].keyframes)
    kf_idx   = next((i for i, k in enumerate(kfs) if k.id == kf_id), None)
    if kf_idx is None:
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")
    patch    = body.model_dump(include=body.model_fields_set)
    kfs[kf_idx] = kfs[kf_idx].model_copy(update=patch)
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.delete("/assembly/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def delete_assembly_keyframe(anim_id: str, kf_id: str) -> dict:
    """Remove a keyframe from an assembly animation."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    kfs = [k for k in anims[anim_idx].keyframes if k.id != kf_id]
    if len(kfs) == len(anims[anim_idx].keyframes):
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.put("/assembly/animations/{anim_id}/keyframes/reorder", status_code=200)
def reorder_assembly_keyframes(anim_id: str, body: ReorderAssemblyKeyframesBody) -> dict:
    """Reorder keyframes by supplying a new ordered list of IDs."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    kf_map   = {k.id: k for k in anims[anim_idx].keyframes}
    reordered = [kf_map[id] for id in body.ordered_ids if id in kf_map]
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": reordered}, deep=True)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


# ── Assembly validation ───────────────────────────────────────────────────────

def _validate_assembly(assembly: "Assembly") -> dict:
    """
    Run all validation checks on an assembly and return a structured report.
    """
    from backend.core.assembly_flatten import flatten_assembly, _load_design

    results = []

    # 1. File sources exist
    for inst in assembly.instances:
        if hasattr(inst.source, "path"):
            try:
                _load_design(inst.source)
                results.append({"check": "file_sources_exist", "ok": True})
            except FileNotFoundError:
                results.append({
                    "check": "file_sources_exist",
                    "ok": False,
                    "message": f"{inst.source.path!r} not found",
                })
        else:
            results.append({"check": "file_sources_exist", "ok": True})

    # 2. Joint instance refs valid
    inst_ids = {i.id for i in assembly.instances}
    for joint in assembly.joints:
        ok = joint.instance_b_id in inst_ids
        entry: dict = {"check": "joint_instance_refs_valid", "ok": ok}
        if not ok:
            entry["message"] = f"Joint {joint.name!r}: instance_b_id {joint.instance_b_id!r} not found"
        results.append(entry)

    # 3. Joint limits not exceeded
    for joint in assembly.joints:
        exceeded = False
        msg = ""
        if joint.min_limit is not None and joint.current_value < joint.min_limit:
            exceeded = True
            msg = f"Joint {joint.name!r}: current_value {joint.current_value} < min_limit {joint.min_limit}"
        elif joint.max_limit is not None and joint.current_value > joint.max_limit:
            exceeded = True
            msg = f"Joint {joint.name!r}: current_value {joint.current_value} > max_limit {joint.max_limit}"
        entry = {"check": "joint_limits_not_exceeded", "ok": not exceeded}
        if exceeded:
            entry["message"] = msg
        results.append(entry)

    # 4. Instance IDs unique
    all_inst_ids = [i.id for i in assembly.instances]
    ids_unique = len(all_inst_ids) == len(set(all_inst_ids))
    results.append({"check": "instance_ids_unique", "ok": ids_unique})

    # 5. Flattened IDs unique
    try:
        flatten_assembly(assembly)
        results.append({"check": "flattened_ids_unique", "ok": True})
    except ValueError as exc:
        results.append({"check": "flattened_ids_unique", "ok": False, "message": str(exc)})
    except FileNotFoundError:
        # Missing file already caught above
        results.append({"check": "flattened_ids_unique", "ok": True})

    # Deduplicate results with the same check name + ok=True (collapse multiple instances)
    seen_ok: dict[str, bool] = {}
    deduped = []
    for r in results:
        key = r["check"]
        if not r["ok"]:
            deduped.append(r)
            seen_ok[key] = False
        elif key not in seen_ok:
            deduped.append(r)
            seen_ok[key] = True

    passed = all(r["ok"] for r in deduped)
    return {"passed": passed, "results": deduped}


@router.get("/assembly/validate", status_code=200)
def validate_assembly() -> dict:
    """Validate the active assembly and return a structured report."""
    assembly = assembly_state.get_or_create()
    return _validate_assembly(assembly)


# ── Flatten to Design ────────────────────────────────────────────────────────

@router.get("/assembly/flatten", status_code=200)
def get_assembly_flatten() -> dict:
    """
    Return the active assembly flattened into a single merged Design JSON.
    Does not alter any state — preview only.
    """
    from backend.core.assembly_flatten import flatten_assembly
    assembly = assembly_state.get_or_create()
    try:
        design = flatten_assembly(assembly)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, detail=str(exc))
    return {"design": design.to_dict()}


@router.post("/assembly/flatten/load-as-design", status_code=200)
def flatten_load_as_design() -> dict:
    """
    Flatten the assembly into a single Design and load it as the active design.
    Clears assembly mode flag on the frontend side (response includes assemblyActive=False).
    """
    from backend.core.assembly_flatten import flatten_assembly
    from backend.core.validator import validate_design
    assembly = assembly_state.get_or_create()
    try:
        design = flatten_assembly(assembly)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, detail=str(exc))
    design_state.set_design(design)
    report = validate_design(design)
    from backend.api.crud import _design_response
    return _design_response(design, report)


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
