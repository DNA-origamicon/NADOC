"""Explicit repair-source inputs and bounded preparation, never construction.

Staging is restricted to a saved proposal's named command inputs. Restoring a
published binding is a different operation because it changes the recipe base.
Raw bytes and old-byte receipts are checked privately, outside the state lock.
"""

from dataclasses import dataclass
import hashlib
from types import SimpleNamespace
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import (
    MAX_ENCODED_BYTES, Digest, EmbeddedResolver, InputSource, command_source_bindings, embed,
)
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import command_input
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_inputs import RepairIdentity
from backend.core.part_repair_planning import plan_actions, validate_target
from backend.core.part_repair_proposal import DraftInputError


MAX_UPLOAD_BYTES = 350_000


class MissingBlob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    state: Literal["missing"]


class PresentBlob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    state: Literal["present"]
    # Length is encoded characters, matching the existing source-table budget;
    # the digest hashes UTF-8 with surrogatepass so corrupt strings are exact.
    encoded_size: StrictInt = Field(ge=0, le=MAX_ENCODED_BYTES)
    encoded_sha256: Digest


BlobExpectation = Annotated[MissingBlob | PresentBlob, Field(discriminator="state")]


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_repair_version: StrictInt = Field(ge=1, le=1)
    operation: Literal["stage_proposed", "restore_published"]
    expected_design_id: RepairIdentity
    expected_revision: StrictInt = Field(ge=0)
    expected_draft_id: RepairIdentity
    expected_generation: StrictInt = Field(ge=0)
    feature_id: RepairIdentity
    child_id: RepairIdentity | None = None
    parameter: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    source: InputSource

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value


class SourceMutation(SourceSelection):
    expected_blob: BlobExpectation


class RepairSourceError(CommandContractError):
    def __init__(self, detail, *, code, selection=None):
        super().__init__(detail, code=code)
        self.selection = selection

    def as_issue(self):
        issue = super().as_issue()
        if self.selection is not None:
            issue.update(feature_id=self.selection.feature_id, parameter_path=[self.selection.parameter])
            if self.selection.child_id is not None:
                issue["child_id"] = self.selection.child_id
            issue["references"] = [{"kind": "input_source", "identity": self.selection.source.sha256,
                                     "parameter_path": [self.selection.parameter]}]
        return issue


def parse_source_request(value, *, mutation=False):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    validate_operation_input(value)
    return (SourceMutation if mutation else SourceSelection).model_validate(value)


@dataclass(frozen=True)
class SourceCapture:
    definitions: object
    sources: dict


@dataclass(frozen=True)
class PreparedSource:
    sources: dict
    published_source_changed: bool


@dataclass(frozen=True)
class _CheckedSource:
    captured: SourceCapture
    request: SourceMutation


def capture_source_inputs(design, *, source_revision):
    """Lock-owned copy of bounded definitions and immutable source references.

    No source text is copied, hashed or decoded here. The independent source
    envelope retains the established table count/encoded-length bounds. This
    permits deliberate replacement of a corrupt large string without changing
    ordinary proof or draft-capture allowances.
    """
    EmbeddedResolver(design.input_sources)  # validates count/types/length only
    sources = dict(design.input_sources)
    view = SimpleNamespace(id=design.id, recipe_root=design.recipe_root,
        feature_log=design.feature_log, feature_log_cursor=design.feature_log_cursor,
        feature_log_sub_cursor=design.feature_log_sub_cursor, input_sources={})
    captured = capture_draft_inputs(view, source_revision=source_revision, draft=design.repair_draft)
    return SourceCapture(captured, sources)


def _fail(selection, detail, code):
    raise RepairSourceError(detail, code=code, selection=selection)


def select_source(captured, selection, *, dependencies, admit_descriptor):
    """Resolve a typed named binding, with no native builder or file parsing."""
    source = captured.definitions
    draft = source.draft
    if (source.id != selection.expected_design_id or source.source_revision != selection.expected_revision
            or draft is None or draft.draft_id != selection.expected_draft_id
            or draft.generation != selection.expected_generation):
        _fail(selection, "The captured part, revision or draft changed", "draft_conflict")
    if source.recipe_root is None or source.recipe_root.version != 1:
        _fail(selection, "Source repair requires a supported explicit root", "missing_or_unsupported_recipe_root")
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        _fail(selection, "Source repair requires the complete recipe", "historical_cursor")
    entries, identities, published = {}, set(), set()
    for entry in source.feature_log:
        children = entry.children if entry.feature_type == "routing-cluster" else []
        for item in [entry, *children]:
            if item.id in identities:
                _fail(selection, "Feature and routing-child identities must be unique", "ambiguous_feature_identity")
            identities.add(item.id)
        for item in children if entry.feature_type == "routing-cluster" else [entry]:
            key = (entry.id, item.id if entry.feature_type == "routing-cluster" else None)
            entries[key] = command_input(item)
            for _, descriptor in command_source_bindings(*entries[key]):
                published.add(descriptor.sha256)
    key = (selection.feature_id, selection.child_id)
    if key not in entries:
        _fail(selection, "The selected source-bearing feature no longer exists", "missing_feature")
    if selection.operation == "stage_proposed":
        if selection.source.sha256 in published:
            _fail(selection, "This digest is used by a published feature; explicitly restore that binding",
                  "restore_published_required")
        targets = plan_actions(source, draft.actions, dependencies=dependencies,
            error_type=DraftInputError, annotate_contract_errors=True)
        for target in targets.values():
            validate_target(target, dependencies, error_type=DraftInputError, annotate_contract_errors=True)
        target = targets.get(selection.child_id or selection.feature_id)
        if target is None:
            _fail(selection, "Staged bytes must be selected by an input in the saved proposal", "unreferenced_repair_source")
        kind, params = target.kind, target.params
    else:
        kind, params = entries[key]
    if not dependencies(kind, params).known:
        _fail(selection, "Source repair cannot promote a legacy or unknown command", "missing_proof_contract")
    binding = dict(command_source_bindings(kind, params)).get(selection.parameter)
    if binding != selection.source:
        _fail(selection, "The source descriptor does not match the selected named input", "source_binding_conflict")
    if binding.size_bytes > MAX_UPLOAD_BYTES:
        _fail(selection, "Source exceeds the repair-upload byte allowance", "source_limit")
    # API-owned command modules enforce their actual per-family format, version,
    # byte allowance and any fixed source identity. The global cap never expands
    # a smaller command's admission or interprets arbitrary JSON as construction.
    try:
        admit_descriptor(kind, params, selection.parameter, binding)
    except CommandContractError as error:
        _fail(selection, str(error), error.code)
    return binding


def blob_expectation(blob):
    """Explicit inspection receipt for exact old encoded bytes, including corruption."""
    if blob is None:
        return MissingBlob(state="missing")
    encoded = blob.data_b64
    if len(encoded) > MAX_ENCODED_BYTES:
        raise RepairSourceError("Input source exceeds its encoded allowance", code="source_limit")
    digest = hashlib.sha256()
    for offset in range(0, len(encoded), 65_536):
        digest.update(encoded[offset:offset + 65_536].encode("utf-8", errors="surrogatepass"))
    return PresentBlob(state="present", encoded_size=len(encoded), encoded_sha256=digest.hexdigest())


def check_blob_expectation(captured, request):
    if not isinstance(request, SourceMutation):
        raise TypeError("Source preparation requires a parsed mutation")
    actual = blob_expectation(captured.sources.get(request.source.sha256))
    if actual != request.expected_blob:
        _fail(request, "The existing source bytes differ from the explicit restoration/staging expectation",
              "source_blob_conflict")
    return _CheckedSource(captured, request)


def prepare_source(captured, request, raw):
    """Hash/encode original bytes and prepare a new table; publish nothing."""
    return _prepare_checked_source(check_blob_expectation(captured, request), raw)


def _prepare_checked_source(checked, raw):
    """Internal continuation of an exact receipt check over immutable capture.

    The upload host retains this private token while reading original bytes.
    No request flag can skip verification, and standalone preparation above
    always performs it. Final session/revision CAS rejects intervening writes.
    """
    if not isinstance(checked, _CheckedSource):
        raise TypeError("Source preparation requires a private checked receipt")
    captured, request = checked.captured, checked.request
    if type(raw) is not bytes or len(raw) > MAX_UPLOAD_BYTES:
        _fail(request, "Source upload must be bounded immutable original bytes", "source_limit")
    try:
        blob = embed(request.source, raw)
    except CommandContractError as error:
        _fail(request, str(error), error.code)
    if captured.sources.get(request.source.sha256) == blob:
        _fail(request, "The selected source already has these exact original bytes", "source_unchanged")
    sources = {**captured.sources, request.source.sha256: blob}
    EmbeddedResolver(sources)  # same entry/cumulative byte bounds as portability
    return PreparedSource(sources, request.operation == "restore_published")
