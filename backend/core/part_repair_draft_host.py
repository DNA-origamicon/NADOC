"""Pure metadata preparation for creating, editing, rebasing or discarding drafts.

No session mutation, source upload, command execution or geometry validation is
performed here. A host must atomically publish the returned proposal only after
rechecking its captured document/revision/draft identity and generation.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, model_validator

from backend.core.part_input_sources import command_source_bindings
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from backend.core.part_repair_inputs import RepairActions, RepairIdentity
from backend.core.part_repair_proposal import DraftInputError, proposed_inputs


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    draft_version: StrictInt = Field(ge=1, le=1)
    expected_design_id: RepairIdentity
    expected_revision: StrictInt = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value


class CreateDraft(_Request):
    operation: Literal["create"]
    expected_draft_id: None
    expected_generation: None
    actions: RepairActions


class _ExistingDraft(_Request):
    expected_draft_id: RepairIdentity
    expected_generation: StrictInt = Field(ge=0)


class UpdateDraft(_ExistingDraft):
    operation: Literal["update"]
    actions: RepairActions


class RebaseDraft(_ExistingDraft):
    operation: Literal["rebase"]
    # None rechecks saved expectations. Replacement actions must come explicitly
    # from the caller; this helper never substitutes current values for old ones.
    actions: RepairActions | None = None


class DiscardDraft(_ExistingDraft):
    operation: Literal["discard"]


DraftRequest = Annotated[CreateDraft | UpdateDraft | RebaseDraft | DiscardDraft, Field(discriminator="operation")]
_ADAPTER = TypeAdapter(DraftRequest)


def parse_draft_request(value):
    validate_operation_input(value)
    return _ADAPTER.validate_python(value)


def _conflict(detail):
    raise DraftInputError(detail, code="draft_conflict")


def prepare_draft(captured, request, *, dependencies, new_draft_id=None, checkpoint=lambda: None):
    """Return a new RepairDraft or None; caller owns final compare-and-swap.

    The injected dependencies resolver must perform cheap schema admission only.
    No numerical pin provider or executor is called. Source availability is not
    required to save a proposal, but source descriptors must be structurally valid.
    """
    if not isinstance(request, (CreateDraft, UpdateDraft, RebaseDraft, DiscardDraft)):
        request = parse_draft_request(request)
    checkpoint()
    if request.expected_design_id != captured.id or request.expected_revision != captured.source_revision:
        _conflict("The part or captured revision changed before draft preparation")
    previous = captured.draft
    if isinstance(request, CreateDraft):
        if previous is not None:
            _conflict("A repair draft already exists")
    elif previous is None or previous.draft_id != request.expected_draft_id or previous.generation != request.expected_generation:
        _conflict("The repair draft was replaced, changed or discarded")
    if isinstance(request, DiscardDraft):
        return None
    if not callable(dependencies):
        raise TypeError("Draft preparation requires a cheap native command schema resolver")
    if not captured.definitions_captured:
        raise ValueError("Draft preparation requires captured definitions")
    if captured.recipe_root is None or captured.recipe_root.version != 1:
        raise DraftInputError("Repair drafts require a supported explicit root", code="missing_or_unsupported_recipe_root")
    if captured.feature_log_cursor != -1 or captured.feature_log_sub_cursor is not None:
        raise DraftInputError("Repair drafts require the complete recipe", code="historical_cursor")
    if not isinstance(request, CreateDraft) and previous.base_design_id != captured.id and not isinstance(request, RebaseDraft):
        _conflict("The draft belongs to a different part identity; explicitly rebase it")
    base = repair_base_fingerprint(captured, checkpoint=checkpoint)
    if isinstance(request, UpdateDraft) and previous.base != base:
        raise DraftInputError("Published definitions changed; explicitly rebase the draft", code="draft_rebase_required")
    actions = previous.actions if isinstance(request, RebaseDraft) and request.actions is None else request.actions
    for kind, params in proposed_inputs(captured, actions, dependencies=dependencies):
        checkpoint()
        command_source_bindings(kind, params)  # source bytes may still be missing
    if isinstance(request, CreateDraft) and new_draft_id is None:
        raise ValueError("The host must allocate a draft identity for creation")
    result = RepairDraft.model_validate({
        "version": 1, "draft_id": new_draft_id if isinstance(request, CreateDraft) else previous.draft_id,
        "generation": 0 if isinstance(request, CreateDraft) else previous.generation + 1,
        "base_design_id": captured.id, "base": base.model_dump(mode="json"), "repair_version": 1,
        "actions": [action.model_dump(mode="json") for action in actions],
    })
    checkpoint()
    return result
