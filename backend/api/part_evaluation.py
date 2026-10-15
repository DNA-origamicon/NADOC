"""Pure recipe job evaluation shared by isolated expensive authoring jobs."""

from dataclasses import asdict
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_recipe_repair import RepairRequest
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_operation_input import validate_operation_input


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["verify", "append", "edit", "delete", "repair"]
    kind: Literal["photoproduct-create", "photoproduct-relax", "duplex-relax"] | None = None
    params: dict | None = None
    index: StrictInt | None = Field(default=None, ge=0)
    sub_index: StrictInt | None = Field(default=None, ge=0)
    cascade: bool = False
    expected_revision: StrictInt | None = Field(default=None, ge=0)
    repair: RepairRequest | None = None

    @model_validator(mode="after")
    def complete_operation(self):
        validate_operation_input(self.params)
        if self.operation == "repair":
            if self.repair is None or self.kind is not None or self.params is not None or self.index is not None or self.sub_index is not None or self.cascade:
                raise ValueError("Repair needs its versioned repair request and no other operation inputs")
            if self.expected_revision is not None and self.expected_revision != self.repair.expected_revision:
                raise ValueError("Repair revision guards must agree")
        elif self.repair is not None:
            raise ValueError("Only a repair operation accepts repair actions")
        elif self.operation == "append":
            if self.kind is None or self.params is None or self.index is not None or self.sub_index is not None or self.cascade:
                raise ValueError("Append needs a supported long-operation kind and authored inputs only")
        elif self.operation in {"edit", "delete"}:
            if self.index is None or self.kind is not None:
                raise ValueError("Recipe edit/delete needs a feature index")
            if (self.operation == "edit") != (self.params is not None):
                raise ValueError("Only parameter edits accept params")
            if self.operation == "edit" and self.cascade:
                raise ValueError("Parameter edits do not cascade-delete features")
        elif self.kind is not None or self.params is not None or self.index is not None or self.sub_index is not None or self.cascade:
            raise ValueError("Verification does not accept mutation inputs")
        return self


def _append(source, request, header, executor, dependencies):
    from backend.api import state
    from backend.api.part_cpd_commands import prepare_command
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_history_proof import command_rows, root_design

    try:
        # Reserve the new row inside the same 2000-entry proof allowance before
        # spending any solver work. Routing group headers count toward it too.
        for _ in command_rows(source, 1999):
            pass
    except ValueError as exc:
        if str(exc) == "entry_limit":
            raise ProofBudgetExceeded("Appending a feature exceeds the recipe entry budget") from exc
        raise

    prefix = ReplayPrefix(source, len(source.feature_log))
    last = None

    def run(kind, current, params):
        nonlocal last
        last = prefix.execute(executor, kind, current, params)
        return last

    proof = assess_part_history(source, execute=run, dependencies=dependencies)
    if proof["status"] not in {"verified", "reproduced_import"}:
        return proof
    current = (last if last is not None else root_design(source.recipe_root, input_sources=source.input_sources)).copy_with(
        id=source.id, feature_log=prefix.log,
    )
    inputs = dict(request.params)
    if request.kind in {"photoproduct-create", "duplex-relax"}:
        inputs["history_seed"] = header["identity"]
    if request.kind == "duplex-relax":
        from backend.api.part_duplex_commands import prepare_command as prepare_duplex
        params = prepare_duplex(request.kind, current, inputs)
    else:
        params = prepare_command(request.kind, inputs)
    updated = executor(request.kind, current, params)
    pre, pre_size = state.encode_design_snapshot(current)
    post, post_size = state.encode_design_snapshot(updated)
    prefix.budget.charge(pre, post)
    entry = SnapshotLogEntry(
        id=header["identity"], timestamp=header["timestamp"],
        op_kind=request.kind,
        label={"photoproduct-create": "Convert native extra thymines to CPD",
               "photoproduct-relax": "Relax native CPD bonds",
               "duplex-relax": "Relax native duplex"}[request.kind],
        params=params, design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size,
    )
    return updated.copy_with(feature_log=[*prefix.log, entry], feature_log_cursor=-1,
                             feature_log_sub_cursor=None)


def _authoring_changes(source, candidate):
    """Bounded comparison metadata, never geometry or a validity certificate."""
    fields, counts = [], {}
    for name in sorted(AUTHORING_FIELDS):
        before, after = getattr(source, name), getattr(candidate, name)
        if before == after:
            continue
        fields.append(name)
        if isinstance(before, (list, dict)) and isinstance(after, (list, dict)):
            counts[name] = {"before": len(before), "after": len(after)}
    return {"basis": "captured_materialized_state", "changed_fields": fields, "record_counts": counts,
            "visual_comparison": False, "scientific_qualification": False}


def evaluate(source, operation, *, executor=None, dependency_resolver=None):
    """Return a result/candidate without touching a document or decoding recovery."""
    from backend.api.part_proof_commands import dependencies, execute_long
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.validator import validate_design

    executor = executor or execute_long
    dependency_resolver = dependency_resolver or dependencies
    header = operation["header"]
    request = EvaluationRequest.model_validate(operation["request"])
    metadata = {}
    try:
        if request.operation == "verify":
            return assess_part_history(source, execute=executor, dependencies=dependency_resolver)
        if request.operation == "repair":
            from backend.api.part_recipe_repair import prepare_repair

            # The request's revision is an expectation, never evidence of the
            # revision captured by the host. Do not fall back to caller values.
            if type(header.get("source_revision")) is not int or header.get("source_design_id") != source.id:
                raise CommandContractError("Repair is missing its trusted capture context", code="invalid_capture_context")
            result = prepare_repair(source, request.repair.model_dump(mode="json"),
                source_revision=header["source_revision"], executor=executor, dependency_resolver=dependency_resolver)
            if result["status"] != "ready":
                return result
            candidate, validation = result["candidate"], result["validation"]
            metadata["repair"] = {**result["repair"], "authoring_changes": _authoring_changes(source, candidate)}
        elif request.operation == "append":
            candidate = _append(source, request, header, executor, dependency_resolver)
            if isinstance(candidate, dict):
                return candidate
            validation = validate_design(candidate)
        else:
            result = prepare_change(
                source, source, request.index, lambda: None,
                params=request.params, sub_index=request.sub_index, cascade=request.cascade,
                executor=executor, dependency_resolver=dependency_resolver,
            )
            if isinstance(result, dict):
                return {"status": "preview", "issues": [], "preview": result}
            candidate, validation = result
        return {"status": "ready", "issues": [], "candidate": candidate.model_dump(mode="json"),
                "validation": {"passed": validation.passed, **asdict(validation)}, **metadata}
    except ProofBudgetExceeded as exc:
        return {"status": "unverified", "issues": [{"code": "command_limit", "detail": str(exc)}],
                "native_editable": False}
    except CommandContractError as exc:
        return {"status": exc.status, "issues": [exc.as_issue()], "native_editable": False}
    except ValueError as exc:
        return {"status": "failed", "issues": [{"code": "invalid_command_inputs", "detail": str(exc)[:2048]}],
                "native_editable": False}
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code") == "recipe_not_reproducible":
            return exc.detail["assessment"]
        return {"status": "unverified" if exc.status_code in {408, 413, 429} else "failed",
                "issues": [{"code": "evaluation_rejected", "detail": exc.detail,
                                                "http_status": exc.status_code}], "native_editable": False}
