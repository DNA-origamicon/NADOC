"""Record a duplex pivot choice as the existing absolute group-pose input."""

from fastapi import HTTPException

from backend.api import state
from backend.api.part_group_geometry_budget import require_group_geometry_budget
from backend.api.part_group_recording import (
    _identity,
    _publish,
    _reference_error,
    capture_group_source,
    prepare_group_update,
    require_group_source_current,
)


def record_rotation_point(cluster_id, body):
    """Compute privately, then atomically record the native pivot rebase.

    Choosing a point is a one-time convenience, not a constraint that follows
    that root on later edits. Replay uses the complete absolute pose, without
    rerunning the point picker or relying on a recovery snapshot.
    """
    from backend.core.duplex_cluster import (
        duplex_cluster_rotation_points,
        set_duplex_cluster_pivot,
    )

    _identity(cluster_id)
    if body.kind not in {"overhang_root", "centroid"}:
        raise HTTPException(422, detail="Unknown rotation point kind.")
    admission = capture_group_source("group_rotation_point")
    private = admission.captured
    matches = [group for group in private.cluster_transforms if group.id == cluster_id]
    if len(matches) != 1:
        _reference_error("cluster", cluster_id, ["cluster_id"],
                         ambiguous=bool(matches), status=409 if matches else 404)
    group = matches[0]
    if group.overhang_duplex_driver_id is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} is not an overhang-duplex cluster.")
    require_group_geometry_budget(private)
    points = duplex_cluster_rotation_points(private, group)
    match = next((point for point in points if point["kind"] == body.kind
                  and (body.kind != "overhang_root" or point["overhang_id"] == body.overhang_id)), None)
    if match is None:
        raise HTTPException(422, detail=f"No rotation point {body.kind!r}"
                            + (f" for overhang {body.overhang_id!r}" if body.overhang_id else "") + ".")
    rebased = set_duplex_cluster_pivot(private, cluster_id, match["point"])
    pose = next(group for group in rebased.cluster_transforms if group.id == cluster_id)
    fields = {name: list(getattr(pose, name)) for name in ("translation", "rotation", "pivot")}
    # Build against the bounded capture, then merge only the fields owned by
    # this command. Presentation, physics and recovery payloads stay intact.
    prepared, entry = prepare_group_update(private, cluster_id, fields, entry_source="rotation-point")
    with state._lock:
        require_group_source_current(admission)
        candidate = admission.source.copy_with(
            cluster_transforms=prepared.cluster_transforms,
            feature_log=[*admission.source.feature_log, entry],
        )
        return _publish(admission.session, admission.source, admission.revision, admission.identity, candidate)
