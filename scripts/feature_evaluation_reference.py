"""Frozen pre-optimization evaluator for A/B timing and equivalence only.

Source revision: a03cf813c514bc3969735c68f364811f0e9c0268
Do not import from production code or update this oracle to match an optimization.
Shared model/geometry helpers stay current; snapshot selection and replay loops
are the original implementation, so shared dispatch overhead is measured too.
"""
from __future__ import annotations

from fastapi import HTTPException
from backend.api import state as design_state
from backend.api.crud import (
    Design, ClusterOpLogEntry, _topology_substitute, _rebase_joints_to_cts,
    _compact_geometry_for_design, _replay_minor_op,
)
from backend.api.routes_feature_log import GeometryBatchBody, SurfaceBatchBody
from backend.core.deformation import deformed_helix_axes

def _state_at_child_boundary(entry, k: int) -> "Design":
    """Return the design state AFTER ``entry.children[0..k-1]`` of a Fine Routing
    cluster (``k == 0`` → the cluster's pre-state).

    Decodes ``pre_state`` then, for each of the first ``k`` children, applies its
    recorded topology diff forward (works for ANY op type) — or falls back to
    ``_replay_minor_op`` for legacy children with no diff. Raises HTTP 410 if the
    pre-state is evicted/missing, HTTP 422 if a legacy child's op can't be
    replayed.

    Non-defensive: the prefix 0..k-1 is internally consistent. NEVER
    re-reconciles — diffs already include reconcile + ligation-retry effects
    (captured post-reconcile in ``mutate_with_minor_log``).
    """
    from backend.core.design_diff import apply_child_diff_forward, is_diff_child

    if entry.evicted or not entry.pre_state_gz_b64:
        raise HTTPException(
            410,
            detail="Fine Routing cluster snapshot was evicted to save space and can no "
            "longer be edited per sub-step.",
        )
    try:
        state = design_state.decode_design_snapshot(entry.pre_state_gz_b64)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(500, detail=f"Failed to decode Fine Routing pre-state: {e}")

    for child in entry.children[:k]:
        if is_diff_child(child):
            state, _w = apply_child_diff_forward(
                state,
                child.diff_added_b64,
                child.diff_removed_b64,
                child.diff_modified_b64,
            )
        else:
            try:
                state = _replay_minor_op(state, child.op_subtype, child.params)
            except NotImplementedError:
                raise HTTPException(
                    422,
                    detail="Cannot reconstruct this sub-step: an earlier sub-step predates "
                    "per-step history and uses an operation that can't be replayed. "
                    "Revert or delete the whole Fine Routing cluster instead.",
                )
    return state

def _seek_snapshot_base(
    design: Design, position: int, sub_position: int | None = None
) -> Design:
    """Choose the design whose strand/helix/crossover topology represents the
    state at the requested feature-log position.

    Slider-seek is destructive — each call writes the result back to the
    active design — so we cannot rely on the live ``design.strands`` to
    represent the latest state after a back-seek. Instead we re-derive the
    topology from the appropriate snapshot every time.

    Strategy:
      * Find the largest index ``sj`` of a non-evicted PAYLOAD-BEARING entry
        (SnapshotLogEntry OR RoutingClusterLogEntry) with ``sj <= position``.
        - If found and the entry is a SnapshotLogEntry: substitute
          snapshot ``sj``'s POST-state (the state immediately after op
          ``sj`` ran).
        - If found and the entry is a RoutingClusterLogEntry:
          * ``sj < position`` OR ``sub_position is None`` → use cluster's
            POST-state (cluster fully active).
          * ``sj == position`` AND ``sub_position == -2`` → use cluster's
            PRE-state (seeking to before the cluster started).
          * ``sj == position`` AND ``0 <= sub_position < len(children)`` →
            use cluster's PRE-state, then replay children[0..sub_position]
            via :func:`_replay_minor_op`.
      * If no such ``sj`` exists but at least one later payload entry does:
        ``position`` precedes every payload entry — substitute the FIRST
        payload entry's PRE-state (the F0 baseline).
      * If the log has no payload-bearing entries at all, return ``design``
        unchanged (delta-only history; live topology is correct).

    Only topology-bearing fields are substituted; deformations,
    cluster_transforms, overhangs etc. are left to the existing delta-replay
    logic that runs after this helper.

    LIMITATION: assumes strands/helices/crossovers are mutated only by
    snapshot-emitting auto-ops or routing-cluster minor ops. The cluster
    children's replay relies on order-preserving, idempotent application
    via :func:`_replay_minor_op`; if a mid-cluster replay fails the helper
    surfaces the partial state with the failed sub_index logged separately.
    """
    from backend.core.models import (
        RoutingClusterLogEntry as _RoutingClusterLogEntry,
        SnapshotLogEntry as _SnapshotLogEntry,
    )

    log = list(design.feature_log)

    def _has_pre(e: object) -> bool:
        if isinstance(e, _SnapshotLogEntry):
            return not e.evicted and bool(e.design_snapshot_gz_b64)
        if isinstance(e, _RoutingClusterLogEntry):
            return not e.evicted and bool(e.pre_state_gz_b64)
        return False

    def _has_post(e: object) -> bool:
        if isinstance(e, _SnapshotLogEntry):
            return not e.evicted and bool(e.post_state_gz_b64)
        if isinstance(e, _RoutingClusterLogEntry):
            return not e.evicted and bool(e.post_state_gz_b64)
        return False

    pre_indices = [i for i, e in enumerate(log) if _has_pre(e)]
    post_indices = [i for i, e in enumerate(log) if _has_post(e)]
    if not pre_indices and not post_indices:
        return design

    # Determine the effective position for payload lookup.
    # -1 / overshoot ⇒ end-of-log.
    if position == -1 or position >= len(log) - 1:
        eff_position = len(log) - 1
    elif position == -2:
        eff_position = -1  # before everything
    else:
        eff_position = position

    # Largest non-evicted POST index <= eff_position.
    sj: int | None = None
    for s_idx in reversed(post_indices):
        if s_idx <= eff_position:
            sj = s_idx
            break

    if sj is None:
        # eff_position precedes every payload entry — fall back to the first
        # payload entry's PRE-state (= F0 baseline).
        if not pre_indices:
            return design
        first = log[pre_indices[0]]
        snap_design = design_state.decode_design_snapshot(
            first.design_snapshot_gz_b64
            if isinstance(first, _SnapshotLogEntry)
            else first.pre_state_gz_b64
        )
        return _topology_substitute(design, snap_design)

    payload_entry = log[sj]

    # Cluster + sub_position handling: only honored when seeking exactly INTO
    # the cluster (sj == eff_position) AND sub_position is specified.
    if (
        isinstance(payload_entry, _RoutingClusterLogEntry)
        and sj == eff_position
        and sub_position is not None
    ):
        # -2 = pre-cluster (no children active)
        if sub_position == -2 or sub_position < -1:
            snap_design = design_state.decode_design_snapshot(
                payload_entry.pre_state_gz_b64
            )
            return _topology_substitute(design, snap_design)
        # 0..M-1 = first sub_position+1 children active
        n_children = len(payload_entry.children)
        if 0 <= sub_position < n_children:
            from backend.core.design_diff import apply_child_diff_forward, is_diff_child

            try:
                snap_design = design_state.decode_design_snapshot(
                    payload_entry.pre_state_gz_b64
                )
                for child in payload_entry.children[: sub_position + 1]:
                    if is_diff_child(child):
                        # Diff-based: works for any op type, no replay needed.
                        snap_design, _w = apply_child_diff_forward(
                            snap_design,
                            child.diff_added_b64,
                            child.diff_removed_b64,
                            child.diff_modified_b64,
                        )
                    else:
                        snap_design = _replay_minor_op(
                            snap_design, child.op_subtype, child.params
                        )
                return _topology_substitute(design, snap_design)
            except NotImplementedError:
                # Legacy child with a non-replayable op AND no diff. Gracefully
                # fall back to the cluster's post-state (whole cluster active —
                # same as sub_position=None).
                pass
        # sub_position == -1 or out-of-range → fall through to post-state.

    # Default: use POST-state of the chosen payload entry.
    if isinstance(payload_entry, _SnapshotLogEntry):
        snap_design = design_state.decode_design_snapshot(
            payload_entry.post_state_gz_b64
        )
    else:
        snap_design = design_state.decode_design_snapshot(
            payload_entry.post_state_gz_b64
        )
    return _topology_substitute(design, snap_design)

def _seek_feature_log(
    design: Design, position: int, sub_position: int | None = None
) -> Design:
    """Replay feature_log[0..position] to compute effective deformations + cluster states.

    position = -1 means 'seek to end' (all entries active).
    sub_position is honored only when ``position`` indexes a
    RoutingClusterLogEntry; see :func:`_seek_snapshot_base` for the full rules.

    Deformations are reconstructed from op_snapshot (if present) or by looking up
    deformation_id in design.deformations (backward compat for old log entries).
    Cluster transforms are set to the last cluster_op state in the active window,
    or identity if no op exists for a cluster in the active range.

    Snapshot + routing-cluster entries are handled by :func:`_seek_snapshot_base`,
    which substitutes the topology-bearing fields (helices/strands/crossovers)
    so that seeking past an auto-op or mid-cluster rolls back the topology too
    — not just deformations and cluster states.
    """
    log = list(design.feature_log)

    # Substitute topology to match the requested position. Subsequent delta
    # logic operates on this topology-corrected base, so the existing
    # rebuild-from-log logic Just Works for snapshot-bearing histories.
    design = _seek_snapshot_base(design, position, sub_position)
    log = list(design.feature_log)

    if position == -2:
        # Seeking to empty state — no features active.
        # Reset cluster transforms for any cluster that has ops in the log.
        clusters_with_any_op = {
            e.cluster_id for e in log if e.feature_type == "cluster_op"
        }
        new_cts = [
            ct.model_copy(
                update={
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                }
            )
            if ct.id in clusters_with_any_op
            else ct
            for ct in design.cluster_transforms
        ]
        new_joints = _rebase_joints_to_cts(design, new_cts)
        # Reset overhang rotations + sub-domain (theta, phi) for any
        # overhang that has ops in the log.
        ovhgs_with_any_op: set = set()
        sd_pairs_with_any_op: set[tuple[str, str]] = set()
        for e in log:
            if e.feature_type != "overhang_rotation":
                continue
            sd_ids = e.sub_domain_ids
            for i, oid in enumerate(e.overhang_ids):
                sd_id_i = sd_ids[i] if i < len(sd_ids) else None
                if sd_id_i is None:
                    ovhgs_with_any_op.add(oid)
                else:
                    sd_pairs_with_any_op.add((oid, sd_id_i))
        new_overhangs = []
        for ovhg in design.overhangs:
            update: dict = {}
            if ovhg.id in ovhgs_with_any_op:
                update["rotation"] = [0.0, 0.0, 0.0, 1.0]
            sds_touched = {
                sd_id for (oid, sd_id) in sd_pairs_with_any_op if oid == ovhg.id
            }
            if sds_touched:
                update["sub_domains"] = [
                    sd.model_copy(
                        update={
                            "rotation_theta_deg": 0.0,
                            "rotation_phi_deg": 0.0,
                        }
                    )
                    if sd.id in sds_touched
                    else sd
                    for sd in ovhg.sub_domains
                ]
            new_overhangs.append(ovhg.model_copy(update=update) if update else ovhg)
        return design.copy_with(
            deformations=[],
            cluster_transforms=new_cts,
            cluster_joints=new_joints,
            overhangs=new_overhangs,
            feature_log_cursor=-2,
            feature_log_sub_cursor=None,
        )

    if not log:
        return design.copy_with(feature_log_cursor=-1, feature_log_sub_cursor=None)

    # When sub_position is provided, the cursor MUST be the explicit cluster
    # index (not -1 / end-of-log). Otherwise the slider thumb can't reflect
    # mid-cluster state and snaps to whichever notch happens to be at the
    # end of the array (which, for an expanded cluster, is the LAST
    # sub-notch — exactly the user-reported snap bug).
    if sub_position is not None and 0 <= position <= len(log) - 1:
        cursor_val = position
        active = log[: position + 1]
    elif position == -1 or position >= len(log) - 1:
        # Seeking to end — restore all deformations from log and latest cluster states.
        cursor_val = -1
        active = log
    else:
        cursor_val = position
        active = log[: position + 1]

    # Rebuild deformation list from active entries.
    deform_map = {d.id: d for d in design.deformations}
    new_deformations = []
    for entry in active:
        if entry.feature_type == "deformation":
            op = entry.op_snapshot or deform_map.get(entry.deformation_id)
            if op:
                new_deformations.append(op)

    # Rebuild cluster states: use the last cluster_op per cluster in the active window.
    cluster_last: dict[str, ClusterOpLogEntry] = {}
    for entry in active:
        if entry.feature_type == "cluster_op":
            cluster_last[entry.cluster_id] = entry

    # Collect cluster IDs that have ANY cluster_op anywhere in the full log.
    clusters_with_ops = {e.cluster_id for e in log if e.feature_type == "cluster_op"}

    new_cts = []
    for ct in design.cluster_transforms:
        if ct.id in cluster_last:
            op = cluster_last[ct.id]
            ct = ct.model_copy(
                update={
                    "translation": op.translation,
                    "rotation": op.rotation,
                    "pivot": op.pivot,
                }
            )
        elif ct.id in clusters_with_ops:
            # Cluster has ops in the log but none in the active window → identity.
            ct = ct.model_copy(
                update={
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                }
            )
        new_cts.append(ct)

    new_joints = _rebase_joints_to_cts(design, new_cts)

    # Rebuild overhang rotations: last rotation per overhang_id in active window.
    # Phase 4 — also track per-sub-domain (theta, phi) state.
    ovhg_last_rot: dict = {}
    sd_last_angles: dict[tuple[str, str], tuple[float, float]] = {}
    ovhgs_with_ops: set = set()
    sd_pairs_with_ops: set[tuple[str, str]] = set()
    for entry in active:
        if entry.feature_type != "overhang_rotation":
            continue
        sd_ids = entry.sub_domain_ids
        thetas = entry.sub_domain_thetas_deg
        phis = entry.sub_domain_phis_deg
        for i, oid in enumerate(entry.overhang_ids):
            sd_id_i = sd_ids[i] if i < len(sd_ids) else None
            if sd_id_i is None:
                ovhg_last_rot[oid] = entry.rotations[i]
            else:
                sd_last_angles[(oid, sd_id_i)] = (float(thetas[i]), float(phis[i]))
    for e in log:
        if e.feature_type != "overhang_rotation":
            continue
        sd_ids = e.sub_domain_ids
        for i, oid in enumerate(e.overhang_ids):
            sd_id_i = sd_ids[i] if i < len(sd_ids) else None
            if sd_id_i is None:
                ovhgs_with_ops.add(oid)
            else:
                sd_pairs_with_ops.add((oid, sd_id_i))

    new_overhangs = []
    for ovhg in design.overhangs:
        if ovhg.id in ovhg_last_rot:
            ovhg = ovhg.model_copy(update={"rotation": ovhg_last_rot[ovhg.id]})
        elif ovhg.id in ovhgs_with_ops:
            ovhg = ovhg.model_copy(update={"rotation": [0.0, 0.0, 0.0, 1.0]})

        sub_doms_touched = [
            sd_id for (oid, sd_id) in sd_pairs_with_ops if oid == ovhg.id
        ]
        if sub_doms_touched:
            new_sds = []
            for sd in ovhg.sub_domains:
                key = (ovhg.id, sd.id)
                if key in sd_last_angles:
                    theta, phi = sd_last_angles[key]
                    sd = sd.model_copy(
                        update={
                            "rotation_theta_deg": theta,
                            "rotation_phi_deg": phi,
                        }
                    )
                elif sd.id in sub_doms_touched:
                    sd = sd.model_copy(
                        update={
                            "rotation_theta_deg": 0.0,
                            "rotation_phi_deg": 0.0,
                        }
                    )
                new_sds.append(sd)
            ovhg = ovhg.model_copy(update={"sub_domains": new_sds})

        new_overhangs.append(ovhg)

    return design.copy_with(
        deformations=new_deformations,
        cluster_transforms=new_cts,
        cluster_joints=new_joints,
        overhangs=new_overhangs,
        feature_log_cursor=cursor_val,
        feature_log_sub_cursor=sub_position,
    )

def geometry_batch(body: GeometryBatchBody) -> dict:
    """Return pre-computed geometry for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake keyframe states before playback so that
    all geometry interpolation is client-side and frame-accurate.

    Geometry is shipped in COMPACT per-helix-per-direction parallel-array form
    (``nucleotides_compact``) — ~50% smaller wire and ~50% faster to parse than
    the legacy per-nuc dict list. Frontend ``animation_player`` re-materialises
    the lookup maps it actually needs (posMap / bnMap / strandSet / helixSet).

    Returns: { "<position>": { nucleotides_compact, helix_axes }, ... }
    """
    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        result[str(position)] = {
            "nucleotides_compact": _compact_geometry_for_design(
                d, junction_balance=True
            ),
            "helix_axes": deformed_helix_axes(d),
        }
    return result


def atomistic_batch(body: GeometryBatchBody) -> dict:
    """Return flat atom-position arrays for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake atomistic states before playback.

    Returns: { "<position>": [x0,y0,z0, x1,y1,z1, ...], ... }
    Positions are indexed by atom serial (same order as GET /design/atomistic).
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_positions_flat

    design = design_state.get_or_404()
    result: dict[str, list] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        model = build_atomistic_model(d)
        result[str(position)] = atomistic_positions_flat(model)
    return result


def surface_batch(body: SurfaceBatchBody) -> dict:
    """Return full mesh data for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake surface states before playback.

    Returns { "<position>": { vertices, faces, vertex_colors? }, ... }.
    Both vertices and faces are included because different feature-log positions can
    produce different marching-cubes topologies (different vertex counts), so the
    frontend needs to rebuild the geometry buffer when topology changes mid-animation.

    When color_mode='strand', per-vertex RGB triples are included so the surface
    mesh keeps its strand-coloured look through topology rebuilds during animation
    playback — without this, _rebuildTopology has nothing to attach as a color
    attribute and would fall back to uniform grey.
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json

    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        model = build_atomistic_model(d)
        mesh = compute_surface(
            model.atoms,
            grid_spacing=body.grid_spacing,
            probe_radius=body.probe_radius,
            radius_scale=1.2 * body.radius_inflate,
        )
        mesh = smooth_mesh(mesh, iterations=body.smooth)
        verts = [round(float(v), 5) for v in mesh.vertices.ravel()]
        faces = [int(f) for f in mesh.faces.ravel()]
        entry: dict = {"vertices": verts, "faces": faces}
        if body.color_mode == "strand":
            full = surface_to_json(mesh, d, color_mode="strand")
            vc = full.get("vertex_colors")
            if vc:
                # 4 decimals is more than enough for 8-bit display precision and
                # keeps the bake payload compact for many-keyframe animations.
                entry["vertex_colors"] = [round(float(c), 4) for c in vc]
        result[str(position)] = entry
    return result
