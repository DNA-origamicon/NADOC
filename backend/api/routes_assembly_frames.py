"""
API layer — assembly connector/joint **frame inspection** route handlers
(extracted from assembly.py).

These three routes are read-only: they resolve the live world-space frames of
connectors and joints so the frontend's 3D overlay (connector indicator dots,
mate highlight markers, the debug "which interpretation matches the DNA blunt
end" panel) agrees with the backend's snap / resolve / cluster-aware math. They
never mutate the assembly — they load each instance's design-with-overrides,
build the connector frames, and return plain position/normal dicts. That single
read-only "frame visualization" reason-to-change is what makes them a cohesive
unit, distinct from the joint-CRUD mutators that share the same banner.

Routes
------
  GET /assembly/connector-frames                       — every IP's world frame, all instances
  GET /assembly/joints/{joint_id}/debug-frames         — side-by-side candidate positions for a joint
  GET /assembly/joints/{joint_id}/connector-frames     — live world frames of a joint's two connectors

Back-imports (B=6, all shared read-kernel infrastructure, bespoke-B=0):
``_assembly_source_path``, ``_geo_cache_key``, ``_design_with_instance_overrides``
(load the per-instance design-with-overrides + its geometry cache key — file-IO,
L4-blocked from core, 30+ shared callers), ``_find_joint`` / ``_find_instance``
(the trivial joint/instance lookups, the ``_design_response`` twins of shared
lookups), and ``_mat4_from_model`` (the SE3 converter, 26+ unrelated callers). The
frame math itself (``_build_inst_by_id``, ``_build_world_connector_frames``,
``_get_connector_world_frame``) lives in ``backend/core`` and is imported from
there directly, not back from the god-file. ``_cluster_se3`` (pure SE3 resolution
of an instance's active cluster transform, used only by the debug-frames route)
moved IN with the routes.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException

from backend.api import assembly_state
from backend.api.assembly import (
    _assembly_source_path,
    _design_with_instance_overrides,
    _find_instance,
    _find_joint,
    _geo_cache_key,
    _mat4_from_model,
)
from backend.core.assembly_connectors import (
    _build_world_connector_frames,
    _get_connector_world_frame,
)
from backend.core.assembly_fk import _build_inst_by_id
from backend.core.models import Design, PartInstance

router = APIRouter()


def _cluster_se3(instance: 'PartInstance', cluster_id: str,
                 design: 'Optional[Design]') -> 'np.ndarray':
    """Resolve the SE3 cluster transform currently active on an instance.

    Per-instance override wins over the design's default. Returns identity
    when nothing matches. Encodes ``ClusterRigidTransform``'s rotate-around-
    pivot-then-translate semantics as a single 4x4 matrix:
    x_world = R (x - pivot) + pivot + translation = R @ x + (-R@pivot + pivot + translation).
    """
    if not cluster_id:
        return np.eye(4, dtype=float)
    override = next((ct for ct in (instance.cluster_transform_overrides or [])
                      if ct.id == cluster_id), None)
    ct = override
    if ct is None and design is not None:
        ct = next((c for c in (design.cluster_transforms or [])
                    if c.id == cluster_id), None)
    if ct is None:
        return np.eye(4, dtype=float)
    from scipy.spatial.transform import Rotation as _R
    R = _R.from_quat(list(ct.rotation)).as_matrix()
    pivot = np.array(ct.pivot, dtype=float)
    trans = np.array(ct.translation, dtype=float)
    M = np.eye(4, dtype=float)
    M[:3, :3] = R
    M[:3, 3] = -R @ pivot + pivot + trans
    return M


@router.get("/assembly/connector-frames", status_code=200)
def get_all_connector_frames() -> dict:
    """Return cluster-aware world frames for every InterfacePoint on every
    instance in the current assembly.

    Single source of truth so the frontend's connector indicators, mate-
    pre-align math, and click-pick targets agree with the rest of the
    pipeline (DNA geometry rendering, backend snap math, mate-highlight
    markers, ``mate_relative_transform`` capture). Without this the
    frontend computes ``T_inst @ p_local`` locally and silently ignores
    each IP's cluster transform — leaving the small connector dots
    several nm away from the actual DNA blunt ends whenever an IP's
    ``cluster_id`` references a non-identity cluster.

    Response shape: ``{instance_id: {label: {pos, normal}}, ...}``.
    Returns an empty object when no assembly is loaded.
    """
    try:
        assembly = assembly_state.get_or_404()
    except HTTPException:
        return {}
    asm_path = _assembly_source_path(assembly)

    # Reuse the same per-(design, label) local-frame cache as resolve_assembly's
    # Phase 4e helper. Naively iterating instance×IP and calling
    # _get_connector_world_frame each time re-runs `deformed_helix_axes` per
    # call — ~17ms per call × (N_instances × ~2 IPs) = 27 seconds at N=500
    # before this change; cached version is ~30ms total at N=500.
    inst_by_id = _build_inst_by_id(assembly)
    design_cache: dict[str, 'Design'] = {}
    def _design_for(inst) -> 'Optional[Design]':
        if not inst.interface_points:
            return None
        key = _geo_cache_key(inst) or inst.id
        d = design_cache.get(key)
        if d is None:
            try:
                d = _design_with_instance_overrides(inst, asm_path)
            except Exception:
                d = None
            design_cache[key] = d
        return d

    labels_by_inst: dict[str, set[str]] = {}
    for inst in assembly.instances:
        if not inst.interface_points:
            continue
        labels_by_inst[inst.id] = {ip.label for ip in inst.interface_points}

    # One-shot endpoint — discard the local_cache; no subsequent refresh.
    frames_by_conn, _ = _build_world_connector_frames(inst_by_id, labels_by_inst, _design_for)

    out: dict = {}
    for (inst_id, label), F in frames_by_conn.items():
        per_inst = out.setdefault(inst_id, {})
        per_inst[label] = {
            "pos":    F[:3, 3].tolist(),
            "normal": F[:3, 2].tolist(),
        }
    return out


@router.get("/assembly/joints/{joint_id}/debug-frames", status_code=200)
def get_joint_debug_frames(joint_id: str) -> dict:
    """Return MULTIPLE candidate world positions for a joint's two connectors
    side by side. Lets the user (and us) see which interpretation of
    "connector position" matches the actual DNA blunt end in the scene.

    For each side (a / b) returns:
      - ``raw_local``           — ip.position in instance-local frame (no transforms applied).
      - ``T_inst_only``         — T_inst @ ip.position. THIS IS the "stored" world position
                                  used by every code path (dots, highlights, snap, resolve).
      - ``T_inst_and_Ct``       — T_inst @ Ct @ ip.position. The double-cluster position;
                                  what cluster-aware code WOULD compute, included so we can
                                  see by how much it differs.
      - ``Ct_translation`` / ``Ct_rotation_quat`` / ``Ct_pivot`` — the matching cluster's
                                  parameters if the IP carries a non-identity cluster_id.
      - ``instance_id`` / ``label`` / ``cluster_id`` — provenance.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)
    asm_path = _assembly_source_path(assembly)
    out: dict = {"a": None, "b": None}

    def _side(inst_id: 'Optional[str]', label: 'Optional[str]') -> 'Optional[dict]':
        if not inst_id or not label:
            return None
        try:
            inst = _find_instance(assembly, inst_id)
        except HTTPException:
            return None
        ip = next((p for p in inst.interface_points if p.label == label), None)
        if ip is None:
            return {"instance_id": inst_id, "label": label, "missing": True}
        raw_local = np.array([ip.position.x, ip.position.y, ip.position.z], dtype=float)
        T = _mat4_from_model(inst.transform)
        p_h = np.append(raw_local, 1.0)
        T_inst_only = (T @ p_h)[:3].tolist()

        info: dict = {
            "instance_id":   inst_id,
            "label":         label,
            "cluster_id":    ip.cluster_id,
            "raw_local":     raw_local.tolist(),
            "T_inst_only":   T_inst_only,
        }
        design = _design_with_instance_overrides(inst, asm_path)
        if ip.cluster_id and design is not None:
            override = next((ct for ct in (inst.cluster_transform_overrides or [])
                              if ct.id == ip.cluster_id), None)
            ct = override or next((c for c in (design.cluster_transforms or [])
                                    if c.id == ip.cluster_id), None)
            if ct is not None:
                info["Ct_translation"]    = list(ct.translation)
                info["Ct_rotation_quat"]  = list(ct.rotation)
                info["Ct_pivot"]          = list(ct.pivot)
                Ct = _cluster_se3(inst, ip.cluster_id, design)
                info["T_inst_and_Ct"] = (T @ Ct @ p_h)[:3].tolist()
        return info

    out["a"] = _side(joint.instance_a_id, joint.connector_a_label)
    out["b"] = _side(joint.instance_b_id, joint.connector_b_label)
    out["axis_origin"] = list(joint.axis_origin)
    if joint.mate_relative_transform is not None:
        out["mate_relative_transform"] = list(joint.mate_relative_transform)
    return out


@router.get("/assembly/joints/{joint_id}/connector-frames", status_code=200)
def get_joint_connector_frames(joint_id: str) -> dict:
    """Return the live world-space frames of a joint's two connectors.

    Cluster-aware — uses the same ``_get_connector_world_frame`` path as
    add_joint and resolve_assembly, so the returned positions match what the
    backend considers the connector locations after any internal Relax Bond /
    cluster drag. Used by the assembly panel to render highlight markers when
    the user clicks a mate row in the sidebar (sanity-checks the joint
    indicator placement vs. where the connectors actually are).

    Response: ``{a: {pos, normal} | null, b: {pos, normal} | null}``. Either
    side can be null when the joint references a missing instance / label or
    when the connector frame is degenerate.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)

    def _frame_to_pos_normal(F):
        if F is None:
            return None
        pos = F[:3, 3].tolist()
        norm = F[:3, 2].tolist()  # Z axis of the built frame == connector tangent
        return {"pos": pos, "normal": norm}

    out: dict = {"a": None, "b": None}
    if joint.instance_a_id and joint.connector_a_label:
        try:
            inst_a = _find_instance(assembly, joint.instance_a_id)
            design_a = _design_with_instance_overrides(inst_a, _assembly_source_path(assembly))
            F_a = _get_connector_world_frame(inst_a, joint.connector_a_label, design_a)
            out["a"] = _frame_to_pos_normal(F_a)
        except HTTPException:
            pass
    if joint.instance_b_id and joint.connector_b_label:
        try:
            inst_b = _find_instance(assembly, joint.instance_b_id)
            design_b = _design_with_instance_overrides(inst_b, _assembly_source_path(assembly))
            F_b = _get_connector_world_frame(inst_b, joint.connector_b_label, design_b)
            out["b"] = _frame_to_pos_normal(F_b)
        except HTTPException:
            pass
    return out
