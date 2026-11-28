"""Recover omitted UI loadout bodies without inventing inactive branch content."""

from backend.core.design_loadouts import encode_snapshot


def restore_missing_snapshots(design, store):
    """Use an exact revision, or the live editable branch, never another branch."""
    from backend.core.project_revisions import BranchConflict

    restored = []
    for branch in design.loadouts:
        if branch.design_snapshot_gz_b64:
            restored.append(branch)
            continue
        active = branch.id == design.active_loadout_id and not branch.protected
        if branch.head_revision_id and not branch.snapshot_dirty:
            try:
                snapshot = store.load_design(design.id, branch.head_revision_id)
            except (FileNotFoundError, ValueError) as exc:
                raise ValueError(
                    f"Loadout {branch.name!r} is missing its saved revision snapshot"
                ) from exc
        elif active:
            head = store.branch_head(design.id, branch.id)
            if head != branch.head_revision_id:
                raise BranchConflict(branch.id, branch.head_revision_id, head)
            snapshot = design
        else:
            raise ValueError(
                f"Loadout {branch.name!r} has no recoverable snapshot; reopen the complete saved document"
            )
        payload, size = encode_snapshot(snapshot)
        restored.append(
            branch.model_copy(
                update={
                    "design_snapshot_gz_b64": payload,
                    "snapshot_size_bytes": size,
                }
            )
        )
    return design.model_copy(update={"loadouts": restored})


def response_loadouts(design):
    """Retain revision identity for browser recovery while omitting large bodies."""
    return [
        branch.model_dump(exclude={"design_snapshot_gz_b64"})
        for branch in design.loadouts
    ]


def prepare_save_loadouts(design, store, known_heads):
    """Undo rewinds content, but only session-observed save cursors may advance."""
    branches = []
    for branch in design.loadouts:
        head = store.branch_head(design.id, branch.id)
        if head and head in known_heads.get(branch.id, set()):
            branch = branch.model_copy(update={"head_revision_id": head})
        branches.append(branch)
    return restore_missing_snapshots(
        design.model_copy(update={"loadouts": branches}), store
    )
