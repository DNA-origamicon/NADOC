"""Connector-frame resolution for assembly mating (pure, api-free).

Given a part's geometry (``Design``) + a ``PartInstance`` + a connector label,
resolve that connector's LOCAL / WORLD SE3 frame (or bare position). This is the
read-only geometry kernel used by the assembly resolve / FK pipeline and the
connector-highlight markers.

Lifted verbatim out of ``backend/api/assembly.py`` (carve-up Refactor #12); the
only adaptation is ``_mat4_from_model(x)`` -> ``x.to_array()`` (the api free
function is byte-identical to ``Mat4x4.to_array``), which drops the last api
dependency so this module imports **nothing** from ``backend.api`` (the
dependency arrow is api -> core).

``_enforce_connector_coincidence`` (the write-side twin of these resolvers — it
re-docks a constrained child whose mated connector drifted) also lives here: it
is pure graph-mutation over the core models, its only adaptation being
``_mat4_from_model(x)`` -> ``x.to_array()`` (byte-identical), so it too imports
nothing from ``backend.api``. The cluster-inference helpers that genuinely need
the api layer (``_design_with_instance_overrides`` -> file-IO design loading;
``_propagate_cluster_delta_to_mates`` -> uses that loader) stay in
``backend/api/assembly.py`` and call these functions back.
"""
from __future__ import annotations

from typing import Optional  # noqa: F401  (used in quoted annotations)

import numpy as np

from backend.core.models import Design, Mat4x4, PartInstance  # noqa: F401  (quoted annotations)
from backend.core.assembly_fk import (
    _build_inst_by_id,
    _fk_expand_rigid_group,
    _fk_propagate,
)


def _build_frame_from_normal(position: np.ndarray, normal: np.ndarray) -> 'np.ndarray | None':
    """Build a 4x4 SE3 frame from a position + normal pair.

    The Z axis is the unit normal. The X axis is chosen deterministically as
    (Z × ref) / |Z × ref| with ref = part-local +Y, falling back to part-local
    +X when Z is nearly parallel to +Y. Y completes the right-handed frame.
    Returns None when the normal is degenerate (zero-length).
    """
    z = np.array(normal, dtype=float)
    n = float(np.linalg.norm(z))
    if n < 1e-9:
        return None
    z = z / n
    ref = np.array([0.0, 1.0, 0.0], dtype=float)
    if abs(float(np.dot(z, ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0], dtype=float)
    x = np.cross(z, ref)
    xn = float(np.linalg.norm(x))
    if xn < 1e-9:
        return None
    x = x / xn
    y = np.cross(z, x)
    F = np.eye(4, dtype=float)
    F[:3, 0] = x
    F[:3, 1] = y
    F[:3, 2] = z
    F[:3, 3] = np.array(position, dtype=float)
    return F


def _resolve_blunt_label_local(
    design: 'Design',
    label: str,
) -> 'tuple[np.ndarray, np.ndarray] | None':
    """For a ``blunt:<helix_id>:<bp_spec>`` label, return the bp's CURRENT
    cluster-aware position + outward normal in instance-local coordinates.

    Bypasses the stored ip.position (which is a snapshot from registration
    time and goes stale when clusters change). Pulls live geometry from
    ``deformed_helix_axes`` / ``deformed_nucleotide_positions`` so a hinge
    angle edit (cluster transform change) propagates straight to mate
    resolve + the highlight markers without requiring IP re-registration.

    Returns None for non-parseable labels or unknown helices — caller
    should fall back to ``T_inst @ ip.position``.
    """
    if not label or not label.startswith("blunt:"):
        return None
    parts = label.split(":", 2)
    if len(parts) != 3:
        return None
    _, helix_id, bp_spec = parts
    helix = next((h for h in (design.helices or []) if h.id == helix_id), None)
    if helix is None:
        return None

    # Endpoint labels (start / end): use the helix's current axis endpoints,
    # which deformed_helix_axes computes already cluster-transformed.
    if bp_spec in ("start", "end"):
        try:
            from backend.core.deformation import deformed_helix_axes
            axes_list = deformed_helix_axes(design)
        except Exception:
            return None
        ax = next((a for a in axes_list if a.get("helix_id") == helix_id), None)
        if ax is None:
            return None
        pos = np.array(ax["start" if bp_spec == "start" else "end"], dtype=float)
        # Outward normal: at start the strand exits toward LOWER bp (so
        # -axis_dir); at end it exits toward HIGHER bp (so +axis_dir).
        axis_dir = np.array(ax["end"], dtype=float) - np.array(ax["start"], dtype=float)
        n = float(np.linalg.norm(axis_dir))
        if n < 1e-9:
            return None
        axis_dir /= n
        normal = -axis_dir if bp_spec == "start" else axis_dir
        return pos, normal

    # Interior bp label "bpN": use deformed_nucleotide_positions and look up
    # the matching bp_index.
    if bp_spec.startswith("bp"):
        try:
            target_bp = int(bp_spec[2:])
        except ValueError:
            return None
        try:
            from backend.core.deformation import deformed_nucleotide_positions
            positions = deformed_nucleotide_positions(helix, design)
        except Exception:
            return None
        # Two NucleotidePosition entries share a bp_index (forward + reverse);
        # the axis-centerline position is the same for both, just take the first.
        nuc = next((p for p in positions if p.bp_index == target_bp), None)
        if nuc is None:
            return None
        pos = np.array(nuc.position, dtype=float)
        # axis_tangent points along the helix axis at this bp; for an interior
        # blunt-end the strand exits in either direction depending on whether
        # this is the strand's terminal-low or terminal-high bp. We don't
        # know that here — default to +tangent (interior overhang convention).
        tangent = getattr(nuc, "axis_tangent", None)
        if tangent is None:
            normal = np.array([0.0, 0.0, 1.0], dtype=float)
        else:
            normal = np.array(tangent, dtype=float)
            n = float(np.linalg.norm(normal))
            if n > 1e-9:
                normal /= n
        return pos, normal

    return None


def _resolve_seam_label_local(
    design: 'Design',
    label: str,
) -> 'tuple[np.ndarray, np.ndarray] | None':
    """For a synthesized periodic-seam connector label (``seam0:5p`` /
    ``seam0:3p``), return the seam cross-section anchor's CURRENT position +
    axis-tangent normal in instance-local coordinates, recomputed live from the
    part's geometry.

    Periodic polymerization (``polymerize_periodic_assembly``) bakes these
    connectors as static ``ip.position`` snapshots taken at polymerize time. If
    the part's geometry later changes (e.g. a new / edited deformation moves the
    seam cross-section), the baked positions go stale and the chain stays frozen
    at the polymerize-time pose. Resolving them live — exactly as
    :func:`_resolve_blunt_label_local` does for ``blunt:`` ends — lets the rigid
    seam joints re-dock the chain to the updated geometry on the next resolve.

    Only the principal seam (``seam0``) is synthesized today; other indices
    return None so the caller falls back to the stored ``ip.position``.
    """
    if not label or not label.startswith("seam0:"):
        return None
    side = label.split(":", 1)[1]
    if side not in ("5p", "3p"):
        return None
    try:
        from backend.core.periodic_polymer import principal_seam_connectors
        specs = principal_seam_connectors(design)
    except Exception:
        return None
    if specs is None:
        return None
    (p5, n5), (p3, n3) = specs
    pos, normal = (p5, n5) if side == "5p" else (p3, n3)
    return np.array(pos, dtype=float), np.array(normal, dtype=float)


def _resolve_live_connector_local(
    design: 'Design',
    label: str,
) -> 'tuple[np.ndarray, np.ndarray] | None':
    """Live (geometry-derived) local anchor + normal for connector labels that
    must track the part's current geometry: ``blunt:helix:bp`` ends and
    synthesized periodic ``seam0:*`` connectors. Returns ``(pos, normal)`` or
    ``None`` (caller falls back to the stored ``ip.position``)."""
    live = _resolve_blunt_label_local(design, label)
    if live is not None:
        return live
    return _resolve_seam_label_local(design, label)


def _get_connector_world_frame(
    instance: 'PartInstance',
    label: str,
    design: 'Optional[Design]' = None,
) -> 'np.ndarray | None':
    """Full SE3 world frame of a named InterfacePoint on an instance.

    For a ``blunt:helix:bp`` label with the design available, the bp's
    CURRENT cluster-aware position+tangent is pulled live from the helix
    geometry pipeline so cluster changes (e.g. a hinge angle edit)
    propagate to resolve / highlight markers automatically — no IP re-
    registration needed.

    For non-parseable labels (e.g. manually-defined ``C1`` connectors) or
    unknown helices, falls back to ``T_inst @ ip.position``. The stored
    ip.position is itself cluster-baked at registration time, so Ct is NOT
    re-applied in the fallback path.
    """
    p_local: 'np.ndarray | None' = None
    n_local: 'np.ndarray | None' = None
    if design is not None:
        live = _resolve_live_connector_local(design, label)
        if live is not None:
            p_local, n_local = live
    if p_local is None:
        ip = next((p for p in instance.interface_points if p.label == label), None)
        if ip is None:
            return None
        p_local = np.array([ip.position.x, ip.position.y, ip.position.z], dtype=float)
        n_local = np.array([ip.normal.x, ip.normal.y, ip.normal.z], dtype=float)
    F_local = _build_frame_from_normal(p_local, n_local)
    if F_local is None:
        return None
    T = instance.transform.to_array()
    return T @ F_local


def _get_connector_world(
    instance: 'PartInstance',
    label: str,
    design: 'Optional[Design]' = None,
) -> 'np.ndarray | None':
    """World-space position of a named InterfacePoint on an instance.

    For a ``blunt:helix:bp`` label with the design available, pulls the
    CURRENT cluster-aware bp position from the helix geometry pipeline —
    cluster changes propagate automatically. Falls back to
    ``T_inst @ ip.position`` for non-parseable labels (manually-defined
    connectors) or unknown helices.

    Returns ``None`` when no resolution path matches.
    """
    p_local: 'np.ndarray | None' = None
    if design is not None:
        live = _resolve_live_connector_local(design, label)
        if live is not None:
            p_local = live[0]
    if p_local is None:
        ip = next((p for p in instance.interface_points if p.label == label), None)
        if ip is None:
            return None
        p_local = np.array([ip.position.x, ip.position.y, ip.position.z], dtype=float)
    T = instance.transform.to_array()
    p_h = np.array([p_local[0], p_local[1], p_local[2], 1.0], dtype=float)
    return (T @ p_h)[:3]


def _local_frame_for_label(
    inst: 'PartInstance',
    label: str,
    design: 'Optional[Design]',
) -> 'np.ndarray | None':
    """Compute a connector's frame in the instance's LOCAL space.

    Mirrors the local-frame portion of :func:`_get_connector_world_frame`
    (everything up to but excluding the ``T = inst.transform.to_array()``
    multiplication). Pulled out so :func:`_build_connector_frames` can
    cache local frames by ``(design_key, label)`` and reuse them across
    many instances that share the same source — instances differ only in
    their world transform, and the local frame depends only on the
    design's deformation state.

    Returns ``None`` when no resolution path matches (matches the upstream
    contract).
    """
    p_local: 'np.ndarray | None' = None
    n_local: 'np.ndarray | None' = None
    if design is not None:
        live = _resolve_live_connector_local(design, label)
        if live is not None:
            p_local, n_local = live
    if p_local is None:
        ip = next((p for p in inst.interface_points if p.label == label), None)
        if ip is None:
            return None
        p_local = np.array([ip.position.x, ip.position.y, ip.position.z], dtype=float)
        n_local = np.array([ip.normal.x, ip.normal.y, ip.normal.z], dtype=float)
    return _build_frame_from_normal(p_local, n_local)


def _build_connector_frames(
    assembly,
    inst_by_id: dict,
    design_for,
) -> tuple[dict, dict, dict]:
    """Pre-compute ``{(instance_id, label): 4x4 world frame}`` for every
    (instance, connector_label) referenced by an assembly joint.

    Returns ``(frames_by_conn, labels_by_inst, local_cache)``. The caller
    MUST keep ``local_cache`` alive across subsequent
    :func:`_refresh_connector_frames_for_instance` calls (otherwise each
    refresh re-runs ``deformed_helix_axes`` ~17 ms — a BFS that moves
    180 instances pays 3 s in waste alone).

    Internally, local frames are cached by ``(design_id, label)``. When N
    instances share one source design (the common polymer / crystal case)
    the per-bp deformation math runs once per label total rather than
    once per (instance, label) pair — the dominant speed-up.

    Falls back to a translation-only 4x4 when the frame is degenerate but
    a position can still be resolved (matches the fallback hierarchy used
    inline at the existing call sites).
    """
    # Collect (instance_id, label) pairs touched by any joint (both sides).
    labels_by_inst: dict[str, set[str]] = {}
    for joint in assembly.joints:
        if joint.instance_a_id and joint.connector_a_label:
            labels_by_inst.setdefault(joint.instance_a_id, set()).add(joint.connector_a_label)
        if joint.instance_b_id and joint.connector_b_label:
            labels_by_inst.setdefault(joint.instance_b_id, set()).add(joint.connector_b_label)

    frames_by_conn, local_cache = _build_world_connector_frames(inst_by_id, labels_by_inst, design_for)
    return frames_by_conn, labels_by_inst, local_cache


def _build_world_connector_frames(
    inst_by_id: dict,
    labels_by_inst: dict,
    design_for,
) -> tuple[dict, dict]:
    """Compute ``{(instance_id, label): 4x4 world frame}`` for the given
    (instance, label) set, caching local frames by ``(design_object_id,
    label)`` so N instances sharing one source pay the per-bp deformation
    cost ONCE per label total.

    Returns ``(frames_by_conn, local_cache)``. The local cache MUST be
    kept alive by the caller across any subsequent refresh-on-write
    invocations (see :func:`_refresh_connector_frames_for_instance`) —
    otherwise refresh re-runs ``deformed_helix_axes`` per moved instance
    (~17 ms each) and resolve scales catastrophically. Was the resolve
    regression caught by N=200 bench at 6700 ms (vs Phase 4e's 372 ms
    at N=500) before this fix.
    """
    # (design_object_id, label) -> 4x4 local frame. Local frames depend on
    # the design (cluster transforms, helix geometry), not on the
    # instance's world transform, so we can share them across instances
    # whose ``design_for(inst)`` returns the same Design object.
    local_cache: dict[tuple[int, str], 'np.ndarray | None'] = {}

    frames_by_conn: dict[tuple[str, str], np.ndarray] = {}
    for inst_id, labels in labels_by_inst.items():
        inst = inst_by_id.get(inst_id)
        if inst is None:
            continue
        design = design_for(inst)
        d_key = id(design) if design is not None else 0
        T = inst.transform.to_array()
        for label in labels:
            ck = (d_key, label)
            if ck in local_cache:
                F_local = local_cache[ck]
            else:
                F_local = _local_frame_for_label(inst, label, design)
                local_cache[ck] = F_local
            if F_local is not None:
                frames_by_conn[(inst_id, label)] = T @ F_local
                continue
            # Final fallback: position-only.
            pos = _get_connector_world(inst, label, design)
            if pos is None:
                continue
            frame = np.eye(4, dtype=float)
            frame[:3, 3] = pos
            frames_by_conn[(inst_id, label)] = frame
    return frames_by_conn, local_cache


def _refresh_connector_frames_for_instance(
    frames_by_conn: dict,
    labels_by_inst: dict,
    inst_by_id: dict,
    inst_id: str,
    design_for,
    local_cache: dict | None = None,
) -> None:
    """Recompute all cache entries for one instance after its transform
    changed. Used by the BFS in :func:`resolve_assembly`.

    Only the world multiplication redoes — the design-local frames don't
    change with the instance's pose, so we just re-multiply the current
    ``inst.transform``. With ``local_cache`` (the dict returned by
    :func:`_build_world_connector_frames`), this is a few µs per instance.
    Without it, we'd re-run ``deformed_helix_axes`` per refresh (~17 ms).
    A BFS that moves 180 instances → 3 s wasted ⇒ catastrophic.

    ``local_cache`` is optional for backwards-compat callers, but the
    BFS path MUST pass it.
    """
    labels = labels_by_inst.get(inst_id)
    if not labels:
        return
    inst = inst_by_id.get(inst_id)
    if inst is None:
        for label in labels:
            frames_by_conn.pop((inst_id, label), None)
        return
    design = design_for(inst)
    d_key = id(design) if design is not None else 0
    T = inst.transform.to_array()
    for label in labels:
        # Local-frame cache hit path: just re-multiply. Cache miss falls
        # through to a one-time _local_frame_for_label + memoize. This
        # path is the difference between O(N) and O(N × deformed_helix_axes)
        # for the BFS.
        if local_cache is not None:
            ck = (d_key, label)
            if ck in local_cache:
                F_local = local_cache[ck]
            else:
                F_local = _local_frame_for_label(inst, label, design)
                local_cache[ck] = F_local
        else:
            F_local = _local_frame_for_label(inst, label, design)
        if F_local is not None:
            frames_by_conn[(inst_id, label)] = T @ F_local
            continue
        pos = _get_connector_world(inst, label, design)
        if pos is None:
            frames_by_conn.pop((inst_id, label), None)
            continue
        frame = np.eye(4, dtype=float)
        frame[:3, 3] = pos
        frames_by_conn[(inst_id, label)] = frame


def _enforce_connector_coincidence(assembly, visited: set,
                                      inst_by_id: dict | None = None) -> None:
    """
    Post-pass: for every rigid/revolute joint where instance_b moved but instance_a
    did not, translate instance_b so connector_b coincides with connector_a.

    Keeps axis_origin in sync and propagates any residual snap to inst_b's subtree.
    This prevents free-drags of constrained children from separating mated connectors.
    """
    if inst_by_id is None:
        inst_by_id = _build_inst_by_id(assembly)
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
            inst_b = inst_by_id.get(cid)
            inst_a = inst_by_id.get(j.instance_a_id)
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
            T_b = inst_b.transform.to_array()
            inst_b.transform = Mat4x4.from_array(snap_d @ T_b)
            if inst_b.base_transform:
                inst_b.base_transform = Mat4x4.from_array(
                    snap_d @ inst_b.base_transform.to_array())
            j.axis_origin = ca.tolist()
            # Propagate snap down inst_b's kinematic subtree
            snap_vis: set = {cid}
            _fk_expand_rigid_group(assembly, cid, snap_d, snap_vis, [], inst_by_id)
            _fk_propagate(assembly, {cid}, snap_d, snap_vis, inst_by_id)
