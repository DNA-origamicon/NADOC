"""Compile a saved proposal into the existing repair request, without replay.

This explicit base check never rebases a draft, changes expected_old, resolves
numerical pins, or interprets a matching fingerprint as a validity certificate.
"""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_operation_input import validate_operation_input
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from backend.core.part_repair_inputs import RepairIdentity, RepairRequest
from backend.core.part_repair_proposal import DraftInputError


class DraftEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    draft_version: StrictInt = Field(ge=1, le=1)
    expected_design_id: RepairIdentity
    expected_revision: StrictInt = Field(ge=0)
    expected_draft_id: RepairIdentity
    expected_generation: StrictInt = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value


def parse_evaluation_request(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    validate_operation_input(value)
    return DraftEvaluationRequest.model_validate(value)


def compile_draft_evaluation(captured, request, *, checkpoint=lambda: None):
    """Return owned actions; caller starts one ordinary, isolated repair job.

    The captured input includes only published source references, since proposed
    bytes do not define the published base. Job capture subsequently includes
    the current source table under its established, unchanged admission policy.
    The normal repair worker owns action planning, numerical selection, prefix
    replay and downstream diagnostics; none is duplicated here.
    """
    request = parse_evaluation_request(request)
    checkpoint()
    previous = captured.draft
    if (captured.id != request.expected_design_id or captured.source_revision != request.expected_revision
            or previous is None or previous.draft_id != request.expected_draft_id
            or previous.generation != request.expected_generation):
        raise DraftInputError("The part, revision or saved proposal changed", code="draft_conflict")
    if not captured.definitions_captured:
        raise ValueError("Draft evaluation requires captured published definitions")
    if captured.recipe_root is None or captured.recipe_root.version != 1:
        raise DraftInputError("Draft evaluation requires a supported explicit root",
                              code="missing_or_unsupported_recipe_root")
    if captured.feature_log_cursor != -1 or captured.feature_log_sub_cursor is not None:
        raise DraftInputError("Draft evaluation requires the complete recipe", code="historical_cursor")
    if previous.base_design_id != captured.id:
        raise DraftInputError("The saved proposal belongs to another part; explicitly rebase it",
                              code="draft_rebase_required")
    current = repair_base_fingerprint(captured, checkpoint=checkpoint)
    if current != previous.base:
        raise DraftInputError("Published definitions or source evidence changed; explicitly rebase the proposal",
                              code="draft_rebase_required")
    result = RepairRequest.model_validate({"repair_version": previous.repair_version,
        "expected_design_id": captured.id, "expected_revision": captured.source_revision,
        "actions": [action.model_dump(mode="json") for action in previous.actions]})
    checkpoint()
    return result
