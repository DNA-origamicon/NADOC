"""Pure recipe job evaluation shared by isolated expensive authoring jobs."""

from dataclasses import asdict
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_recipe_repair import RepairRequest
from backend.api.part_repair_selection import SelectionRequest
from backend.core.part_batch_inputs import BatchRequest
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_operation_input import validate_operation_input


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["verify", "append", "edit", "delete", "repair", "selection", "batch"]
    kind: Literal["photoproduct-create", "photoproduct-relax", "duplex-relax", "streptavidin-coating",
                  "linear-pattern", "circular-pattern"] | None = None
    params: dict | None = None
    index: StrictInt | None = Field(default=None, ge=0)
    sub_index: StrictInt | None = Field(default=None, ge=0)
    cascade: bool = False
    expected_revision: StrictInt | None = Field(default=None, ge=0)
    repair: RepairRequest | None = None
    selection: SelectionRequest | None = None
    batch: BatchRequest | None = None

    @model_validator(mode="after")
    def complete_operation(self):
        validate_operation_input(self.params)
        if self.operation == "batch":
            if (self.batch is None or self.repair is not None or self.selection is not None
                    or self.kind is not None or self.params is not None or self.index is not None
                    or self.sub_index is not None or self.cascade):
                raise ValueError("Batch needs its versioned commands and no other operation inputs")
            if self.expected_revision is not None and self.expected_revision != self.batch.expected_revision:
                raise ValueError("Batch revision guards must agree")
        elif self.batch is not None:
            raise ValueError("Only batch operations accept a nested batch request")
        elif self.operation == "repair":
            if self.repair is None or self.selection is not None or self.kind is not None or self.params is not None or self.index is not None or self.sub_index is not None or self.cascade:
                raise ValueError("Repair needs its versioned repair request and no other operation inputs")
            if self.expected_revision is not None and self.expected_revision != self.repair.expected_revision:
                raise ValueError("Repair revision guards must agree")
        elif self.operation == "selection":
            if self.selection is None or self.repair is not None or self.kind is not None or self.params is not None or self.index is not None or self.sub_index is not None or self.cascade:
                raise ValueError("Selection needs its versioned reference request and no mutation inputs")
            if self.expected_revision is not None and self.expected_revision != self.selection.expected_revision:
                raise ValueError("Selection revision guards must agree")
        elif self.repair is not None or self.selection is not None:
            raise ValueError("Only repair or selection operations accept their nested requests")
        elif self.operation == "append":
            if self.kind is None or self.params is None or self.index is not None or self.sub_index is not None or self.cascade:
                raise ValueError("Append needs a supported long-operation kind and authored inputs only")
            if self.kind == "streptavidin-coating":
                from backend.api.part_coating_append import parse_request
                if self.expected_revision is None:
                    raise ValueError("Coating append requires expected_revision")
                parse_request(self.params)
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
    """Closed owned hosts add target guards or a native pattern report observer."""
    header = operation["header"]
    if "extrusion_recording_version" in header:
        return _evaluate_extrusion(source, operation, executor=executor,
                                   dependency_resolver=dependency_resolver)
    if "pattern_recording_version" not in header:
        return _evaluate(source, operation, executor=executor, dependency_resolver=dependency_resolver)
    from backend.api.pattern_features import collect_pattern_report
    from backend.api.part_native_commands import PATTERN_COMMANDS

    try:
        request = EvaluationRequest.model_validate(operation["request"])
        if (type(header["pattern_recording_version"]) is not int or header["pattern_recording_version"] != 1
                or source.group_organization is None
                or type(header.get("source_revision")) is not int
                or header["source_revision"] != request.expected_revision
                or header.get("source_design_id") != source.id):
            raise CommandContractError("Pattern work lacks its exact captured context", code="invalid_capture_context")
        if request.operation == "append" and request.kind in PATTERN_COMMANDS:
            seed = header["identity"]
        elif request.operation == "edit" and request.sub_index is None and request.index < len(source.feature_log):
            entry = source.feature_log[request.index]
            if (entry.feature_type != "snapshot" or entry.op_kind not in PATTERN_COMMANDS
                    or entry.id != header.get("expected_feature_id")):
                raise CommandContractError("Pattern edit target changed", code="source_changed")
            seed = entry.params.get("history_seed")
        else:
            raise CommandContractError("Unknown owned pattern operation", code="invalid_operation_admission")
        with collect_pattern_report(seed) as collected:
            result = _evaluate(source, operation, executor=executor, dependency_resolver=dependency_resolver)
        if result.get("status") == "ready":
            if "report" not in collected:
                raise CommandContractError("Native pattern execution did not return its copy report",
                                           code="pattern_report_missing")
            validate_operation_input(collected["report"])
            result["pattern_report"] = collected["report"]
        return result
    except CommandContractError as error:
        return {"status": error.status, "issues": [error.as_issue()], "native_editable": False}
    except (ValueError, KeyError, TypeError) as error:
        return {"status": "failed", "issues": [{"code": "invalid_command_inputs", "detail": str(error)[:2048]}],
                "native_editable": False}


def _evaluate_extrusion(source, operation, *, executor=None, dependency_resolver=None):
    from backend.api.part_extrusion_edit_inputs import KINDS, bind_prefix

    try:
        header = operation["header"]
        request = EvaluationRequest.model_validate(operation["request"])
        if (type(header["extrusion_recording_version"]) is not int
                or header["extrusion_recording_version"] != 1
                or "pattern_recording_version" in header
                or type(header.get("source_revision")) is not int
                or header["source_revision"] != request.expected_revision
                or header.get("source_design_id") != source.id):
            raise CommandContractError("Extrusion edit lacks its exact captured context",
                                       code="invalid_capture_context")
        if (request.operation != "edit" or request.sub_index is not None
                or request.index >= len(source.feature_log)):
            raise CommandContractError("Unknown owned extrusion operation",
                                       code="invalid_operation_admission")
        entry = source.feature_log[request.index]
        if (entry.feature_type != "snapshot" or entry.op_kind not in KINDS
                or header.get("expected_kind") != entry.op_kind
                or header.get("expected_feature_id") != entry.id
                or type(entry.params.get("_proof_version")) is not int
                or entry.params["_proof_version"] != 1
                or "_generated_scope" in entry.params or "_generator" in entry.params):
            raise CommandContractError("The selected native extrusion feature changed",
                                       code="source_changed")
        return _evaluate(source, operation, executor=executor,
                         dependency_resolver=dependency_resolver, input_binder=bind_prefix)
    except CommandContractError as error:
        return {"status": error.status, "issues": [error.as_issue()], "native_editable": False}
    except (ValueError, KeyError, TypeError) as error:
        return {"status": "failed", "issues": [{"code": "invalid_command_inputs", "detail": str(error)[:2048]}],
                "native_editable": False}


def _evaluate(source, operation, *, executor=None, dependency_resolver=None, input_binder=None):
    """Return a result/candidate without touching a document or decoding recovery."""
    from backend.api.part_proof_commands import dependencies, execute, execute_long
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.validator import validate_design

    dependency_resolver = dependency_resolver or dependencies
    header = operation["header"]
    request = EvaluationRequest.model_validate(operation["request"])
    # Batches expose only the reviewed ordinary catalog. They cannot cause a
    # long native prefix to run merely by entering the longer-lived job host.
    executor = executor or (execute if request.operation == "batch" else execute_long)
    metadata = {}
    try:
        if request.operation == "verify":
            return assess_part_history(source, execute=executor, dependencies=dependency_resolver)
        if request.operation == "selection":
            from backend.api.part_repair_selection import prepare_selection

            if type(header.get("source_revision")) is not int or header.get("source_design_id") != source.id:
                raise CommandContractError("Selection is missing its trusted capture context", code="invalid_capture_context")
            # A prefix preview has no authoring candidate, validation pass or
            # publication phase. Candidate filtering never calls an executor.
            return prepare_selection(source, request.selection.model_dump(mode="json"),
                source_revision=header["source_revision"], executor=executor, dependency_resolver=dependency_resolver)
        if request.operation == "batch":
            from backend.api.part_batch_evaluation import evaluate_batch

            result = evaluate_batch(source, request.batch, header,
                executor=executor, dependency_resolver=dependency_resolver)
            if result["status"] != "ready":
                return result
            candidate, validation = result["candidate"], result["validation"]
            metadata["batch"] = {**result["batch"], "authoring_changes": _authoring_changes(source, candidate)}
            metadata["source_assessment"] = result["source_assessment"]
        elif request.operation == "repair":
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
            from backend.api.part_evaluation_append import append_features

            candidate = append_features(source, request, header, executor, dependency_resolver, metadata=metadata)
            if isinstance(candidate, dict):
                return candidate
            validation = validate_design(candidate)
        else:
            result = prepare_change(
                source, source, request.index, lambda: None,
                params=request.params, sub_index=request.sub_index, cascade=request.cascade,
                executor=executor, dependency_resolver=dependency_resolver,
                input_binder=input_binder,
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
