"""Rebuild versioned part recipes and their recovery data before publication."""

from time import monotonic

from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.design_diff import encode_child_diff
from backend.core.part_command_errors import CommandContractError
from backend.core.part_edit_identity import preserve_proof_identity
from backend.core.part_history_contract import assess_part_history
from backend.core.part_recipe_publication import preserve_document_state
from backend.core.part_overlay_commands import (
    KINDS as OVERLAY_KINDS,
    command_input,
    edit_entry,
    proof_version_supported,
)
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows, root_design
from backend.core.part_verification_capture import CaptureLimit
from backend.core.validator import validate_design


def is_versioned(entry):
    children = entry.children if entry.feature_type == "routing-cluster" else [entry]
    return any(proof_version_supported(kind, params.get("_proof_version"))
               for kind, params in map(command_input, children))


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
        self.issue = reason.as_issue() if isinstance(reason, CommandContractError) else {
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


def regenerate(source, log, checkpoint, *, identify_failures=False, attribute_failures=False,
               prefix=None, executor=None):
    """Execute input commands only; replace every recovery snapshot and child diff."""

    executor = executor or execute
    from backend.api.part_recovery_budget import RecoveryBudget
    budget = prefix.budget if prefix is not None else RecoveryBudget()

    def run(entry, current):
        kind, arguments = command_input(entry)
        try:
            return executor(kind, current, arguments)
        except (ValueError, HTTPException) as exc:
            if (isinstance(exc, CommandContractError) and exc.status == "unverified") or not (
                identify_failures or attribute_failures
            ) or (
                isinstance(exc, HTTPException) and exc.status_code in {408, 413, 429}
            ):
                raise
            raise CommandReplayError(entry.id, exc) from exc

    current = (
        prefix.design.model_copy(deep=True)
        if prefix is not None
        else root_design(source.recipe_root, input_sources=source.input_sources).copy_with(id=source.id)
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
        budget.charge(pre)
        if entry.feature_type == "routing-cluster":
            children = []
            for child in entry.children:
                checkpoint()
                updated = run(child, current)
                a, r, m, size = encode_child_diff(current, updated)
                budget.charge(a, r, m)
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
        budget.charge(post)
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
    return preserve_document_state(source, current).copy_with(
        feature_log=rebuilt_log,
        feature_log_cursor=-1,
        feature_log_sub_cursor=None,
    )


def prepare_change(source, captured, index, checkpoint, *, params=None, sub_index=None,
                   cascade=False, executor=None, dependency_resolver=None, input_binder=None):
    """Build an isolated candidate or cascade preview; never publish session state.

    The ordinary editor and bounded process jobs share exactly this evaluator.
    Recovery payloads are re-encoded from execution, never consumed as inputs.
    """
    executor = executor or execute
    dependency_resolver = dependency_resolver or dependencies
    if index < 0 or index >= len(source.feature_log):
        raise HTTPException(400, detail="Feature index out of range")
    from backend.api.part_recipe_prefix import ReplayPrefix

    prefix = ReplayPrefix(source, index, sub_index=sub_index if params is not None else None)
    proof = assess_part_history(
        captured,
        execute=lambda kind, d, p: prefix.execute(executor, kind, d, p),
        dependencies=dependency_resolver,
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
            kind = command_input(child)[0]
            try:
                from backend.api.part_routing_edit_inputs import KINDS as ROUTING_EDIT_KINDS, normalize, bind_prefix
                changed = {**child.params, **params}
                if kind in ROUTING_EDIT_KINDS:
                    changed = (input_binder(kind, changed, prefix.child_design)
                               if input_binder is not None else
                               bind_prefix(kind, normalize(kind, child.params, params), prefix.child_design))
                elif input_binder is not None:
                    raise CommandContractError("Unsupported owned routing child",
                                               code="invalid_routing_input")
            except CommandContractError as exc:
                raise HTTPException(409, detail={**exc.as_issue(), "feature_id": child.id}) from exc
            children[sub_index] = child.model_copy(
                update={
                    "params": preserve_proof_identity(
                        child.params, changed, kind=kind
                    )
                }
            )
            log[index] = entry.model_copy(update={"children": children})
        elif entry.feature_type in OVERLAY_KINDS:
            try:
                if entry.feature_type == "cluster_op":
                    from backend.api.part_transform_inputs import edit_transform_entry

                    log[index] = edit_transform_entry(entry, params, prefix.design)
                else:
                    log[index] = edit_entry(entry, params, prefix=prefix.design)
            except CommandContractError as exc:
                raise HTTPException(409, detail={**exc.as_issue(), "feature_id": entry.id}) from exc
        elif entry.feature_type == "snapshot":
            if entry.op_kind in {"placement-poses", "nucleotide-transform", "nucleotide-transform-batch",
                                  "nucleotide-transform-delete"}:
                from backend.api.part_transform_inputs import edit_transform_entry

                try:
                    log[index] = edit_transform_entry(entry, params, prefix.design)
                except CommandContractError as exc:
                    raise HTTPException(409, detail={**exc.as_issue(), "feature_id": entry.id}) from exc
            else:
                log[index] = entry.model_copy(
                    update={
                        "params": preserve_proof_identity(
                            entry.params, {**entry.params, **params}, kind=entry.op_kind
                        )
                    }
                )
            if input_binder is not None:
                # Private owned-editor binding, after identity preservation and
                # original input proof. Untouched rows keep their saved receipts.
                bound = input_binder(entry.op_kind, log[index].params, prefix.design)
                log[index] = log[index].model_copy(update={"params": bound})
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
                    prefix=prefix, executor=executor,
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
            candidate = regenerate(source, log, checkpoint, prefix=prefix, executor=executor,
                                   attribute_failures=True)
        from backend.core.part_structure_gate import require_valid_structure
        require_valid_structure(candidate, checkpoint=checkpoint)
    except CommandReplayError as exc:
        raise HTTPException(409, detail={**exc.issue, "feature_id": exc.feature_id}) from exc
    except CommandContractError as exc:
        raise HTTPException(409, detail=exc.as_issue()) from exc
    except ValidationError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except (HTTPException, ProofBudgetExceeded):
        raise
    except Exception as exc:
        raise HTTPException(
            409, detail={"code": "regeneration_failed", "message": str(exc)}
        ) from exc
    report = validate_design(candidate)
    checkpoint()
    return candidate, report


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

        prepared = prepare_change(source, captured, index, checkpoint,
                                  params=params, sub_index=sub_index, cascade=cascade)
        if isinstance(prepared, dict):
            return prepared
        candidate, report = prepared
        state.set_design(candidate, expected_revision=revision, expected_source=source)
        return _design_replace_response(source, candidate, report)
    except ValidationError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except (CaptureLimit, ProofBudgetExceeded) as exc:
        raise HTTPException(413, detail=str(exc)) from exc
    finally:
        _slot.release()
