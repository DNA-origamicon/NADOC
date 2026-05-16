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
import uuid as _uuid
from collections import OrderedDict
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

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
    Direction,
    Helix,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartLibraryEntry,
    PartSourceFile,
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


def _assembly_source_path(assembly: Assembly) -> str | None:
    return getattr(assembly.metadata, "source_path", None)


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
    patched_ids: set = set()
    for item in body.patches:
        inst = next((i for i in assembly.instances if i.id == item.id), None)
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

    _replace_instance_design(assembly, inst, design)
    return _assembly_response(assembly_state.get_or_404())


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
    """
    from backend.core.models import SnapshotLogEntry

    pre_assembly = assembly_state.get_or_404()
    pre_payload, pre_size   = assembly_state.encode_assembly_snapshot(pre_assembly)
    post_payload, post_size = assembly_state.encode_assembly_snapshot(mutated)

    timestamp = _dt.now(_tz.utc).isoformat()
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


@router.post("/assembly/instances/{instance_id}/features/seek", status_code=200)
def seek_instance_features(instance_id: str, body: InstanceSeekFeaturesRequest) -> dict:
    """Replay one part instance's feature log and persist the resulting part design."""
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    updated_design = crud_api._seek_feature_log(design, body.position, body.sub_position)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


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
        raise HTTPException(400, detail=f"overhang_a_attach must be 'root' or 'free_end'.")
    if fields.get("overhang_b_attach") not in (None, "root", "free_end"):
        raise HTTPException(400, detail=f"overhang_b_attach must be 'root' or 'free_end'.")
    if fields.get("linker_type") not in (None, "ss", "ds"):
        raise HTTPException(400, detail=f"linker_type must be 'ss' or 'ds'.")
    if fields.get("length_unit") not in (None, "bp", "nm"):
        raise HTTPException(400, detail=f"length_unit must be 'bp' or 'nm'.")
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
            first_entry = full_log[0]
            if not first_entry.design_snapshot_gz_b64:
                # No payload available; fall back to current display state.
                new_state = current
            else:
                new_state = assembly_state.decode_assembly_snapshot(
                    first_entry.design_snapshot_gz_b64,
                )
        new_cursor = -2
    elif target_pos == -1:
        # End of log — post-state of the LAST entry.
        if not full_log:
            new_state = current
        else:
            last_entry = full_log[-1]
            if not last_entry.post_state_gz_b64:
                new_state = current
            else:
                new_state = assembly_state.decode_assembly_snapshot(
                    last_entry.post_state_gz_b64,
                )
        new_cursor = -1
    else:
        # Explicit entry index — post-state of that entry.
        if target_pos < 0 or target_pos >= log_len:
            raise HTTPException(
                400,
                detail=f"feature index {target_pos} out of range (log length {log_len}).",
            )
        entry = full_log[target_pos]
        if not entry.post_state_gz_b64:
            new_state = current
        else:
            new_state = assembly_state.decode_assembly_snapshot(entry.post_state_gz_b64)
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


def _decode_entry_pre_state(entry) -> Assembly:
    if not entry.design_snapshot_gz_b64:
        raise HTTPException(
            422,
            detail="This entry has no embedded pre-state snapshot — it was "
                   "created before per-entry actions were supported. Use the "
                   "slider / Ctrl-Z to navigate around it.",
        )
    try:
        return assembly_state.decode_assembly_snapshot(entry.design_snapshot_gz_b64)
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to decode snapshot: {exc}") from exc


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
    entry = assembly.feature_log[index]
    pre_assembly = _decode_entry_pre_state(entry)
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
    entry = assembly.feature_log[index]
    pre_assembly = _decode_entry_pre_state(entry)

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
            "design_snapshot_gz_b64": pre_b64,
            "snapshot_size_bytes":    pre_size,
            "post_state_gz_b64":      post_b64,
            "post_state_size_bytes":  post_size,
            "evicted":                False,
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
    pre_assembly = _decode_entry_pre_state(entry)
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
    mutated = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-instance",
        label=f"Delete part: {target.name}",
        params={"instance_id": instance_id, "name": target.name},
    )
    assembly_state.forget_instance_display(instance_id)
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
    new_assembly = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # Propagate snap to inst_b's kinematic children (so they follow the alignment)
    if snap_delta is not None:
        snap_vis: set = {body.instance_b_id}
        _fk_expand_rigid_group(new_assembly, body.instance_b_id, snap_delta, snap_vis, [])
        _fk_propagate(new_assembly, snap_vis.copy(), snap_delta, snap_vis)

    inst_a_name = (_find_instance(new_assembly, body.instance_a_id).name
                    if body.instance_a_id else "world")
    inst_b_name = _find_instance(new_assembly, body.instance_b_id).name
    label_str = f"Add mate: {inst_a_name} ↔ {inst_b_name}"

    _apply_assembly_mutation_with_feature_log(
        new_assembly,
        op_kind="assembly-add-joint",
        label=label_str,
        params={
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
    target   = _find_joint(assembly, joint_id)
    new_joints = [j for j in assembly.joints if j.id != joint_id]
    mutated = assembly.model_copy(update={"joints": new_joints})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-joint",
        label=f"Delete mate: {target.name}",
        params={"joint_id": joint_id, "name": target.name},
    )
    return _assembly_response(assembly_state.get_or_404())


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

    # Each new forward primary clones inst_b's per-instance state (overrides,
    # representation, mode, fixed/visible, joint_states) but takes the unioned
    # connectors so it can mate on both sides.  Source is deep-copied via
    # Pydantic so subsequent edits don't entangle clones with the original.
    prev_inst = inst_b_updated
    for i, T_arr in enumerate(forward_T):
        new_inst = inst_b.model_copy(deep=True, update={
            "id":               str(_uuid.uuid4()),
            "name":             f"{base_name_b} {i + 1}",
            "transform":        Mat4x4.from_array(T_arr),
            "base_transform":   None,
            "interface_points": [ip.model_copy(deep=True) for ip in union_ips],
            # New polymerize clones default to a cheap renderer because
            # polymer chains are usually previewed at scale; rendering N
            # heavy origamis at 'full' OOMs the browser fast.  Users can
            # upgrade individual clones via the rep picker if needed.
            "representation":   "cylinders",
        })
        forward_primary_ids.append(new_inst.id)
        axis_origin, axis_direction = forward_axes[i]
        new_jt = AssemblyJoint(
            name=f"{joint.name} +{i + 1}",
            joint_type=joint.joint_type,
            instance_a_id=prev_inst.id,
            instance_b_id=new_inst.id,
            cluster_id_a=joint.cluster_id_a,
            cluster_id_b=joint.cluster_id_b,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            current_value=0.0,
            min_limit=joint.min_limit,
            max_limit=joint.max_limit,
            connector_a_label=joint.connector_a_label,
            connector_b_label=joint.connector_b_label,
        )
        # base_transform mirrors POST /assembly/joints — the joint's
        # "value=0" pose is the new instance's transform itself.
        new_inst = new_inst.model_copy(update={"base_transform": Mat4x4.from_array(T_arr)})
        new_instances.append(new_inst)
        new_joints.append(new_jt)
        prev_inst = new_inst

    # Spawn additional clones forward.  Each additional gets `add_n_forward`
    # entries, which is `n_forward + 1` for direction ∈ {forward, both} so
    # the additional's total instance count (1 existing + add_n_forward new)
    # matches the chain length N — fixing the off-by-one the user reported.
    for add_inst in additional_instances:
        for i, T_add in enumerate(add_forward_transforms[add_inst.id]):
            new_add = add_inst.model_copy(deep=True, update={
                "id":             str(_uuid.uuid4()),
                "name":           f"{add_inst.name} {i + 1}",
                "transform":      Mat4x4.from_array(T_add),
                "base_transform": None,
                "interface_points": [
                    ip.model_copy(deep=True) for ip in add_inst.interface_points
                ],
                "representation": "cylinders",
            })
            new_instances.append(new_add)
            forward_add_ids[add_inst.id].append(new_add.id)

    # ── Backward side ────────────────────────────────────────────────────────
    # Reuse inst_a's per-instance state.  Each backward instance is appended
    # in the order "closest to A outward" so the new joint binds
    # (backward_step_i, backward_step_{i-1}) — except the first backward
    # joint, which binds (first_new_backward, original inst_a).  Connector
    # labels stay the same as the original mate.
    prev_inst = inst_a_updated
    for i, T_arr in enumerate(backward_T):
        new_inst = inst_a.model_copy(deep=True, update={
            "id":               str(_uuid.uuid4()),
            "name":             f"{base_name_a} -{i + 1}",
            "transform":        Mat4x4.from_array(T_arr),
            "base_transform":   None,
            "interface_points": [ip.model_copy(deep=True) for ip in union_ips],
            "representation":   "cylinders",
        })
        backward_primary_ids.append(new_inst.id)
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
            instance_a_id=new_inst.id,
            instance_b_id=prev_inst.id,
            cluster_id_a=joint.cluster_id_a,
            cluster_id_b=joint.cluster_id_b,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            current_value=0.0,
            min_limit=joint.min_limit,
            max_limit=joint.max_limit,
            connector_a_label=joint.connector_a_label,
            connector_b_label=joint.connector_b_label,
        )
        new_inst = new_inst.model_copy(update={"base_transform": Mat4x4.from_array(T_arr)})
        new_instances.append(new_inst)
        new_joints.append(new_jt)
        prev_inst = new_inst

    # Spawn additional clones backward.  Same off-by-one fix as forward —
    # add_n_backward = n_backward + 1 when direction == 'backward', else
    # n_backward.  Each additional ends up with chain-length-many total
    # instances combining backward + forward.
    for add_inst in additional_instances:
        for i, T_add in enumerate(add_backward_transforms[add_inst.id]):
            new_add = add_inst.model_copy(deep=True, update={
                "id":             str(_uuid.uuid4()),
                "name":           f"{add_inst.name} -{i + 1}",
                "transform":      Mat4x4.from_array(T_add),
                "base_transform": None,
                "interface_points": [
                    ip.model_copy(deep=True) for ip in add_inst.interface_points
                ],
                "representation": "cylinders",
            })
            new_instances.append(new_add)
            backward_add_ids[add_inst.id].append(new_add.id)

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
    mutated = assembly.model_copy(update={"instances": new_instances})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-add-connector",
        label=f"Add connector {label} on {inst.name}",
        params={
            "instance_id": instance_id,
            "label":       label,
            "position":    list(body.position),
            "normal":      list(body.normal),
            "cluster_id":  body.cluster_id,
        },
    )
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
    mutated = assembly.model_copy(update={"instances": new_instances})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-connector",
        label=f"Delete connector {label} on {inst.name}",
        params={"instance_id": instance_id, "label": label},
    )
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

    Builds a synthetic Design from assembly_helices + assembly_strands plus
    *world-space alias helices* for every cross-part complement domain
    (helix ids of the form ``<inst_id>::<orig_helix_id>``), and runs the
    same geometry pipeline as the main design endpoint.  Returns
    ``{nucleotides, helix_axes, aliased_helices}`` — ``aliased_helices``
    carries the synthesised cross-part helices so the frontend renderer
    can resolve them.

    Returns empty arrays when there are no linker helices.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.assembly_linker import parse_namespaced_helix_id, _world_axes_for_helix
    from backend.core.deformation import deformed_helix_axes
    from backend.core.models import Design

    assembly = assembly_state.get_or_404()
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
        aliased.append(helix.model_copy(update={
            "id":          namespaced_id,
            "axis_start":  Vec3.from_array(ws),
            "axis_end":    Vec3.from_array(we),
            # Loop/skip records reference original-helix bp indices, which
            # don't apply to the cross-part complement (it's not part of
            # the OH's helix geometry pass). Drop them to keep the
            # synthetic pass clean.
            "loop_skips":  [],
        }))

    synthetic = Design(
        helices=list(assembly.assembly_helices) + aliased,
        strands=list(assembly.assembly_strands),
        lattice_type="honeycomb",
        metadata=DesignMetadata(name="__linkers__"),
    )
    return {
        "nucleotides":     _geometry_for_design(synthetic),
        "helix_axes":      deformed_helix_axes(synthetic),
        "aliased_helices": [h.model_dump(mode="json") for h in aliased],
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
    from backend.api.crud import _geometry_for_design, _compact_geometry_from_nucleotides
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

    design      = _design_with_instance_overrides(inst)
    nucleotides = _geometry_for_design(design)
    axes        = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    design_dict = design.to_dict()
    if key:
        _geo_cache_set(key, {"nucleotides": nucleotides, "helix_axes": axes,
                             "design": design_dict})
    return {
        "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
        "helix_axes":          axes,
        "design":              design_dict,
    }


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

            design      = _design_with_instance_overrides(inst)
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
    spin_axis: Optional[str] = None
    spin_rotations: float = 0.0
    spin_invert: bool = False
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
    spin_axis: Optional[str] = None
    spin_rotations: Optional[float] = None
    spin_invert: Optional[bool] = None
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
        spin_axis=body.spin_axis,
        spin_rotations=body.spin_rotations,
        spin_invert=body.spin_invert,
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
