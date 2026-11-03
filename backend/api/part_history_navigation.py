"""Recipe-backed recovery for part navigation; snapshots are only an accelerator."""
from fastapi import HTTPException
from gzip import BadGzipFile
from zlib import error as ZlibError

from backend.core.part_history_proof import ProofBudgetExceeded, command_rows


def recovery_missing(design):
    for row in design.feature_log:
        if row.feature_type not in {"snapshot", "routing-cluster"}:
            continue
        pre = getattr(row, "pre_state_gz_b64", None) if row.feature_type == "routing-cluster" else row.design_snapshot_gz_b64
        if row.evicted or not pre or not row.post_state_gz_b64:
            return True
        if row.feature_type == "routing-cluster" and (row.diffs_evicted or any(
                not (child.diff_added_b64 or child.diff_removed_b64 or child.diff_modified_b64)
                for child in row.children)):
            return True
    return False


def seek_with_recovery(source, position, sub_position, recovery, *, optimized=None):
    from backend.api.part_group_recovery import _admit_organization_recovery
    # Keep the retired named-group model's admission boundary. Native cluster
    # history is independent of that parked rollout.
    _admit_organization_recovery(source.feature_log)
    if source.recipe_root is not None and recovery_missing(source):
        return seek_recipe(source, position, sub_position)
    try:
        return recovery(source, position, sub_position, optimized=optimized)
    except HTTPException as error:
        if source.recipe_root is None or error.status_code != 410:
            raise
    except (ValueError, BadGzipFile, EOFError, ZlibError):
        if source.recipe_root is None:
            raise
    # Invalid encoded recovery is no more authoritative than an evicted cache.
    # Unsupported recipes still fail explicitly in replay_prefix.
    return seek_recipe(source, position, sub_position)


def replay_prefix(source, log):
    from backend.api.part_proof_commands import dependencies, execute
    from backend.api.part_recipe_edit import CommandReplayError, regenerate
    from backend.core.part_structure_gate import require_valid_structure

    if source.recipe_root is None or source.recipe_root.version != 1:
        raise HTTPException(409, detail={"code": "history_recipe_unavailable",
            "detail": "This history has no supported recipe root for rebuilding this stage."})
    try:
        # Admit only the requested prefix: a broken later feature must not prevent
        # navigating to, or reverting to, the last good stage.
        for identity, kind, params in command_rows(source.copy_with(feature_log=log), 2000):
            if not dependencies(kind, params).known:
                raise HTTPException(409, detail={"code": "missing_proof_contract",
                    "feature_id": identity, "detail": f"Cannot rebuild history command {kind}."})
        candidate = regenerate(source, log, lambda: None, executor=execute,
                               attribute_failures=True, preserve_document=False)
        require_valid_structure(candidate)
        return candidate
    except CommandReplayError as error:
        raise HTTPException(409, detail={**error.issue, "feature_id": error.feature_id}) from error
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail=str(error)) from error
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(409, detail={"code": "history_recipe_invalid", "detail": str(error)}) from error


def _preserve(source, candidate, *, seek=False):
    from backend.core.part_recipe_publication import preserve_document_state
    from backend.core.part_history_contract import FIELD_ROLES
    # Atomistic reference output belongs to its recorded stage, never the later
    # live model. Native replay reconstructs it where the command owns it.
    restored = preserve_document_state(source, candidate).copy_with(
        atomistic_reference=candidate.atomistic_reference)
    if seek:
        # Scrubbing must not discard display overrides for temporarily absent
        # objects: they must still be present when seeking forward again.
        restored = restored.copy_with(**{name: getattr(source, name)
            for name, role in FIELD_ROLES.items() if role == "presentation"})
    return restored


def seek_recipe(source, position, sub_position=None):
    if position < -2:
        raise HTTPException(400, detail="Invalid history position")
    log = list(source.feature_log)
    count = 0 if position == -2 else len(log) if position == -1 else min(position + 1, len(log))
    active = log[:count]
    cursor = -1 if count == len(log) else position
    sub_cursor = None
    if sub_position is not None and 0 <= position < len(log):
        row = log[position]
        if row.feature_type == "routing-cluster":
            cursor, sub_cursor = position, sub_position
            if sub_position < -1:
                active = log[:position]
            elif 0 <= sub_position < len(row.children):
                active[-1] = row.model_copy(update={"children": row.children[:sub_position + 1]})
    rebuilt = _preserve(source, replay_prefix(source, active), seek=True)
    return rebuilt.copy_with(feature_log=log, feature_log_cursor=cursor,
                             feature_log_sub_cursor=sub_cursor)


def revert_recipe(source, index, sub_index=None):
    log = list(source.feature_log[:index])
    row = source.feature_log[index]
    if sub_index is not None:
        if row.feature_type != "routing-cluster" or not 0 <= sub_index < len(row.children):
            raise HTTPException(400, detail="Invalid Fine Routing sub_index")
        if sub_index:
            log.append(row.model_copy(update={"children": row.children[:sub_index]}))
    return _preserve(source, replay_prefix(source, log))
