"""Admit group timeline recovery before any snapshot decode or publication.

This compatibility reader deliberately requires all dissolution recovery bodies.
Native input regeneration is a separate path and has no such requirement.
"""

from fastapi import HTTPException

from backend.core.feature_history_clusters import group_pose_windows, has_group_dissolution


def prepare_group_seek(design, position):
    if not has_group_dissolution(design.feature_log):
        return {}
    try:
        windows = group_pose_windows(design, position)
    except ValueError as exc:
        raise HTTPException(409, detail={
            "code": "group_recovery_invalid", "detail": str(exc),
        }) from exc
    for entry in design.feature_log:
        if (entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve"
                and (entry.evicted or not entry.design_snapshot_gz_b64 or not entry.post_state_gz_b64)):
            # Another surviving snapshot may describe a different incarnation
            # of the same ID. Do not infer a valid baseline from its presence.
            raise HTTPException(410, detail={
                "code": "group_recovery_unavailable",
                "feature_id": entry.id,
                "detail": "Group dissolution recovery data is unavailable. Timeline seeking is disabled "
                    "for this history; restore a complete saved copy or use input regeneration when supported.",
            })
    return windows


def restore_group_patterns(design, decode_snapshot, pose_windows):
    from backend.core.circular_pattern import pattern_history_overlays
    from backend.core.part_command_errors import CommandContractError

    try:
        return pattern_history_overlays(design, decode_snapshot, pose_windows=pose_windows)
    except CommandContractError as exc:
        raise HTTPException(409, detail=exc.as_issue()) from exc
