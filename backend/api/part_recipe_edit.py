"""Rebuild versioned part recipes and their recovery data before publication."""

from time import monotonic

from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.design_diff import encode_child_diff
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.feature_identity import preserve_proof_identity
from backend.core.part_history_contract import FIELD_ROLES, assess_part_history
from backend.core.part_overlay_commands import (
    KINDS as OVERLAY_KINDS,
    command_input,
    edit_entry,
)
from backend.core.part_history_proof import command_rows, root_design
from backend.core.part_verification_capture import CaptureLimit
from backend.core.validator import validate_design


def is_versioned(entry):
    children = entry.children if entry.feature_type == "routing-cluster" else [entry]
    return any(command_input(child)[1].get("_proof_version") == 1 for child in children)


def supports_recipe_edit(design, entry):
    """Keep recovery editors available until every row has an audited contract."""
    if (
        design.recipe_root is None
        or not is_versioned(entry)
        or design.feature_log_cursor != -1
        or design.feature_log_sub_cursor is not None
    ):
        return False
    try:
        return all(
            dependencies(kind, params).known
            for _, kind, params in command_rows(design, 2000)
        )
    except (ValueError, KeyError, TypeError):
        return False


class CommandReplayError(Exception):
    def __init__(self, feature_id, reason):
        self.feature_id = feature_id
        self.reason = str(reason)
        self.issue = reason.as_issue() if isinstance(reason, ReferenceResolutionError) else {
            "code": "command_failed", "detail": self.reason,
        }
        super().__init__(self.reason)


def without_commands(log, removed):
    retained = []
    for entry in log:
        if entry.feature_type == "routing-cluster":
            children = [c for c in entry.children if c.id not in removed]
            if children:
                retained.append(entry.model_copy(update={"children": children}))
        elif entry.id not in removed:
            retained.append(entry)
    return retained


def regenerate(source, log, checkpoint, *, identify_failures=False, prefix=None):
    """Execute input commands only; replace every recovery snapshot and child diff."""

    def run(entry, current):
        kind, arguments = command_input(entry)
        try:
            return execute(kind, current, arguments)
        except (ValueError, HTTPException) as exc:
            if not identify_failures or (
                isinstance(exc, HTTPException) and exc.status_code in {408, 429}
            ):
                raise
            raise CommandReplayError(entry.id, exc) from exc

    current = (
        prefix.design.model_copy(deep=True)
        if prefix is not None
        else root_design(source.recipe_root).copy_with(id=source.id)
    )
    rebuilt_log = list(prefix.log) if prefix is not None else []
    for entry in log[len(rebuilt_log) :]:
        checkpoint()
        if entry.feature_type in OVERLAY_KINDS:
            kind, arguments = command_input(entry)
            current = run(entry, current).copy_with(id=source.id)
            if kind == "deformation":
                entry = entry.model_copy(
                    update={"op_snapshot": current.deformations[-1]}
                )
            rebuilt_log.append(entry)
            current = current.copy_with(feature_log=list(rebuilt_log))
            continue
        before = current.copy_with(feature_log=list(rebuilt_log))
        pre, pre_size = state.encode_design_snapshot(before)
        if entry.feature_type == "routing-cluster":
            children = []
            for child in entry.children:
                checkpoint()
                updated = run(child, current)
                a, r, m, size = encode_child_diff(current, updated)
                children.append(
                    child.model_copy(
                        update={
                            "diff_added_b64": a,
                            "diff_removed_b64": r,
                            "diff_modified_b64": m,
                            "diff_size_bytes": size,
                        }
                    )
                )
                current = updated.copy_with(id=source.id)
            changes = {
                "children": children,
                "pre_state_gz_b64": pre,
                "pre_state_size_bytes": pre_size,
                "diffs_evicted": False,
            }
        else:
            current = run(entry, current).copy_with(id=source.id)
            changes = {
                "design_snapshot_gz_b64": pre,
                "snapshot_size_bytes": pre_size,
                "diff_added_b64": "",
                "diff_removed_ids": [],
                "diff_modified_b64": "",
                "pre_state_from_previous": False,
            }
        post, post_size = state.encode_design_snapshot(current)
        rebuilt_log.append(
            entry.model_copy(
                update={
                    **changes,
                    "post_state_gz_b64": post,
                    "post_state_size_bytes": post_size,
                    "evicted": False,
                }
            )
        )
        current = current.copy_with(feature_log=list(rebuilt_log))
    preserved = {
        name: getattr(source, name)
        for name, role in FIELD_ROLES.items()
        if role in {"presentation", "physical", "document_identity"}
    }
    return current.copy_with(
        **preserved,
        feature_log=rebuilt_log,
        feature_log_cursor=-1,
        feature_log_sub_cursor=None,
    )


def change_recipe(index, *, params=None, sub_index=None, cascade=False):
    from backend.api.crud import _design_replace_response
    from backend.api.part_history_verification import _slot

    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    try:
        source, captured, revision = state.capture_design_for_verification()
        deadline = monotonic() + 5

        def checkpoint():
            if monotonic() > deadline:
                raise HTTPException(408, detail="Recipe regeneration time limit")

        if index < 0 or index >= len(source.feature_log):
            raise HTTPException(400, detail="Feature index out of range")
        from backend.api.part_recipe_prefix import ReplayPrefix

        prefix = ReplayPrefix(source, index)
        proof = assess_part_history(
            captured,
            execute=lambda kind, d, p: prefix.execute(execute, kind, d, p),
            dependencies=dependencies,
            checkpoint=checkpoint,
        )
        if proof["status"] not in {"verified", "reproduced_import"}:
            raise HTTPException(
                409, detail={"code": "recipe_not_reproducible", "assessment": proof}
            )
        # Original entries supply labels/provenance only. Recovery bytes are never decoded.
        log = list(source.feature_log)
        if index < 0 or index >= len(log):
            raise HTTPException(400, detail="Feature index out of range")
        entry = log[index]
        candidate = None
        if params is not None:
            if sub_index is not None:
                if entry.feature_type != "routing-cluster" or not 0 <= sub_index < len(
                    entry.children
                ):
                    raise HTTPException(400, detail="Routing child index out of range")
                child = entry.children[sub_index]
                children = list(entry.children)
                children[sub_index] = child.model_copy(
                    update={
                        "params": preserve_proof_identity(
                            child.params, {**child.params, **params}
                        )
                    }
                )
                log[index] = entry.model_copy(update={"children": children})
            elif entry.feature_type in OVERLAY_KINDS:
                log[index] = edit_entry(entry, params)
            elif entry.feature_type == "snapshot":
                log[index] = entry.model_copy(
                    update={
                        "params": preserve_proof_identity(
                            entry.params, {**entry.params, **params}, kind=entry.op_kind
                        )
                    }
                )
            else:
                raise HTTPException(
                    400, detail="Use a child target to edit a routing command"
                )
            if entry.feature_type == "snapshot" and entry.op_kind == "sweep":
                from backend.core.sweep import SweepRequest

                normalized = SweepRequest.model_validate(log[index].params).model_dump(
                    mode="json"
                )
                log[index] = log[index].model_copy(
                    update={"params": preserve_proof_identity(entry.params, normalized)}
                )
        else:
            if sub_index is not None:
                if entry.feature_type != "routing-cluster" or not 0 <= sub_index < len(
                    entry.children
                ):
                    raise HTTPException(400, detail="Routing child index out of range")
                targets = {entry.children[sub_index].id}
            else:
                targets = (
                    {c.id for c in entry.children}
                    if entry.feature_type == "routing-cluster"
                    else {entry.id}
                )
            removed, reasons, issues = set(targets), {}, {}
            # Conservative graph edges describe possible effects, not commands
            # that must be deleted. Replay survivors to resolve actual failures.
            # A failed builder may mutate its candidate; restart from the root
            # after removing that row, never continue from partially changed data.
            while True:
                checkpoint()
                try:
                    candidate = regenerate(
                        source,
                        without_commands(log, removed),
                        checkpoint,
                        identify_failures=True,
                        prefix=prefix,
                    )
                    break
                except CommandReplayError as exc:
                    removed.add(exc.feature_id)
                    reasons[exc.feature_id] = exc.reason
                    issues[exc.feature_id] = exc.issue
            if removed - targets and not cascade:
                return {
                    "needs_cascade_decision": True,
                    "target_index": index,
                    "target_label": getattr(entry, "label", entry.feature_type),
                    "dependents": [
                        {
                            "index": i,
                            "label": getattr(e, "label", e.feature_type),
                            "feature_ids": sorted(ids & (removed - targets)),
                            "reasons": {
                                fid: reasons[fid] for fid in ids & reasons.keys()
                            },
                            "issues": {
                                fid: issues[fid] for fid in ids & issues.keys()
                            },
                        }
                        for i, e in enumerate(log)
                        if (
                            ids := (
                                {c.id for c in e.children}
                                if e.feature_type == "routing-cluster"
                                else {e.id}
                            )
                        )
                        & (removed - targets)
                    ],
                }
        try:
            if candidate is None:
                candidate = regenerate(source, log, checkpoint, prefix=prefix)
        except ValidationError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                409, detail={"code": "regeneration_failed", "message": str(exc)}
            ) from exc
        report = validate_design(candidate)
        checkpoint()
        state.set_design(candidate, expected_revision=revision, expected_source=source)
        return _design_replace_response(source, candidate, report)
    except ValidationError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except CaptureLimit as exc:
        raise HTTPException(413, detail=str(exc)) from exc
    finally:
        _slot.release()
