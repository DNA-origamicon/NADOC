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
    AnimationKeyframe,
    AssemblyJoint,
    DesignAnimation,
    DesignMetadata,
    Helix,
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


def _mat4_to_model(m: np.ndarray) -> Mat4x4:
    """Convert a 4×4 numpy array (row-major) to Mat4x4."""
    return Mat4x4(values=m.flatten().tolist())


def _mat4_from_model(m: Mat4x4) -> np.ndarray:
    """Convert a Mat4x4 (row-major values list) to a 4×4 numpy array."""
    return np.array(m.values, dtype=float).reshape(4, 4)


# ── Request bodies ────────────────────────────────────────────────────────────

class AddInstanceRequest(BaseModel):
    source: dict                         # raw dict; validated below
    name: str = "Part"
    transform: Optional[dict] = None     # Mat4x4 dict; defaults to identity


class PatchInstanceRequest(BaseModel):
    name: Optional[str] = None
    transform: Optional[dict] = None
    mode: Optional[str] = None
    visible: Optional[bool] = None
    joint_states: Optional[dict] = None


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


class PatchJointRequest(BaseModel):
    name: Optional[str] = None
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


@router.patch("/assembly/instances/{instance_id}", status_code=200)
def patch_instance(instance_id: str, body: PatchInstanceRequest) -> dict:
    """Update fields on a PartInstance."""
    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)

    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.transform is not None:
        updates["transform"] = Mat4x4.model_validate(body.transform)
        # Null out base_transform whenever the placement transform is overwritten
        # externally (e.g. gizmo drag).  Leaving a stale base_transform would
        # cause the next joint drive to compute its rotation from the old origin.
        updates["base_transform"] = None
    if body.mode is not None:
        if body.mode not in ("rigid", "flexible"):
            raise HTTPException(400, detail="mode must be 'rigid' or 'flexible'")
        updates["mode"] = body.mode
    if body.visible is not None:
        updates["visible"] = body.visible
    if body.joint_states is not None:
        updates["joint_states"] = body.joint_states

    if not updates:
        return _assembly_response(assembly)

    new_inst = inst.model_copy(update=updates)
    new_instances = [new_inst if i.id == instance_id else i for i in assembly.instances]

    assembly_state.snapshot()
    assembly_state.set_assembly_silent(assembly.model_copy(update={"instances": new_instances}))
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
    """Add an AssemblyJoint and snapshot instance_b's base_transform."""
    assembly = assembly_state.get_or_404()
    # Validate referenced instances exist
    _find_instance(assembly, body.instance_b_id)
    if body.instance_a_id is not None:
        _find_instance(assembly, body.instance_a_id)

    joint = AssemblyJoint(
        name=body.name,
        joint_type=body.joint_type,
        instance_a_id=body.instance_a_id,
        cluster_id_a=body.cluster_id_a,
        instance_b_id=body.instance_b_id,
        cluster_id_b=body.cluster_id_b,
        axis_origin=body.axis_origin,
        axis_direction=body.axis_direction,
        current_value=body.current_value,
        min_limit=body.min_limit,
        max_limit=body.max_limit,
    )

    # Snapshot instance_b's current transform as base_transform (value=0 reference)
    inst_b = _find_instance(assembly, body.instance_b_id)
    new_inst_b = inst_b.model_copy(update={"base_transform": inst_b.transform.model_copy()})
    new_instances = [new_inst_b if i.id == inst_b.id else i for i in assembly.instances]
    new_joints    = list(assembly.joints) + [joint]

    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"instances": new_instances, "joints": new_joints})
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

    # Recompute instance_b transform when driving a revolute joint
    new_instances = list(assembly.instances)
    if value_changed and new_joint.joint_type == "revolute":
        inst_b = _find_instance(assembly, joint.instance_b_id)
        # Use base_transform as the reference; fall back to current transform if not yet set
        base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
        new_mat  = _apply_revolute_joint(
            base_mat,
            new_joint.axis_origin,
            new_joint.axis_direction,
            new_joint.current_value,
        )
        new_inst_b    = inst_b.model_copy(update={"transform": _mat4_to_model(new_mat)})
        new_instances = [new_inst_b if i.id == inst_b.id else i for i in assembly.instances]

    silent = body.silent  # True during animation playback
    if not silent:
        assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"instances": new_instances, "joints": new_joints})
    )
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
    """Resolve and return the Design for a PartInstance."""
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
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _load_design_from_source(inst.source)
    return {
        "nucleotides": _geometry_for_design(design),
        "helix_axes":  deformed_helix_axes(design),
    }


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
    from backend.core.deformation import deformed_helix_axes
    assembly = assembly_state.get_or_404()
    result: dict[str, dict] = {}
    for inst in assembly.instances:
        if not inst.visible:
            continue
        try:
            design = _load_design_from_source(inst.source)
            result[inst.id] = {
                "nucleotides": _geometry_for_design(design),
                "helix_axes":  deformed_helix_axes(design),
                "design":      design.to_dict(),
            }
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
    hold_duration_s: float = 1.0
    transition_duration_s: float = 0.5
    easing: str = "ease-in-out"


class PatchAssemblyKeyframeBody(BaseModel):
    name: Optional[str] = None
    camera_pose_id: Optional[str] = None
    hold_duration_s: Optional[float] = None
    transition_duration_s: Optional[float] = None
    easing: Optional[str] = None
    joint_values: Optional[dict] = None


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
    patch    = body.model_dump(exclude_none=True)
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
        hold_duration_s=body.hold_duration_s,
        transition_duration_s=body.transition_duration_s,
        easing=body.easing,
        joint_values=joint_values,
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
    patch    = body.model_dump(exclude_none=True)
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
