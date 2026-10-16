"""Owned ordinary pattern append/edit through the existing isolated evaluator.

Only the two native pattern families enter this host. A fresh bounded capture
and full input proof precede publication; recovery is never a construction
input. The synchronous route retains the ordinary five-second operation budget
and one undo, with no parent-process numerical replay or new worker lifecycle.
"""

import json
from datetime import datetime, timezone
from threading import Event
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as policy
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_evaluation_candidate import CandidateDecodeError, decode_candidate
from backend.api.part_evaluation_jobs import EvaluationJob
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_history_verification import _slot
from backend.api.part_native_commands import PATTERN_COMMANDS
from backend.api.part_replacement_transaction import publish_replacement
from backend.api.part_verification_jobs import supervise
from backend.api.pattern_features import CircularPatternBody, LinearPatternBody
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows, digest
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_recipe_publication import preserve_document_state
from backend.core.part_recovery_storage import retained_recovery_bytes
from backend.core.part_structure_gate import require_valid_structure
from backend.core.part_verification_capture import CaptureLimit, admit, capture
from backend.core.validator import ValidationReport, ValidationResult


TIME_BUDGET = 5.0
MAX_HISTORY_ROWS = 2_000


def _refuse(message, *, code="pattern_conflict", status=409):
    raise HTTPException(status, detail={"code": code, "detail": message})


def _expectations(design_id, revision, cancelled):
    if type(design_id) is not str or not 1 <= len(design_id) <= 512:
        _refuse("An exact part identity is required", code="invalid_pattern_input", status=422)
    if type(revision) is not int or revision < 0:
        _refuse("An exact nonnegative revision is required", code="invalid_pattern_input", status=422)
    if cancelled is not None and not isinstance(cancelled, Event):
        _refuse("Cancellation must be a private host event", code="invalid_pattern_input", status=422)


def _inputs(kind, inputs, *, previous=None):
    """Own JSON choices; identity/version slots always come from the host/row."""
    from backend.core.part_pattern_organization import parse_organization_copy

    if type(kind) is not str or kind not in PATTERN_COMMANDS or type(inputs) is not dict:
        _refuse("Select a supported native pattern", code="invalid_pattern_input", status=422)
    validate_operation_input(inputs)
    schema = CircularPatternBody if kind == "circular-pattern" else LinearPatternBody
    fields = {field.alias or name for name, field in schema.model_fields.items()
              if name not in {"expected_revision", "expected_design_id"}}
    identities = {"history_seed", "_proof_version"}
    if set(inputs) - fields - (identities if previous is not None else set()):
        _refuse("Pattern input has unknown fields", code="invalid_pattern_input", status=422)
    if previous is not None:
        if any(key in inputs and inputs[key] != previous.get(key) for key in identities):
            _refuse("Pattern output identities and proof version cannot be changed")
        merged = {key: value for key, value in previous.items() if key in fields}
        merged.update({key: value for key, value in inputs.items() if key in fields})
    else:
        merged = inputs
    validate_operation_input(merged)
    body = schema.model_validate_json(json.dumps(merged, allow_nan=False))
    normalized = body.model_dump(mode="json", by_alias=True,
                                 exclude={"expected_revision", "expected_design_id"})
    contract = parse_organization_copy(normalized.get("_organization_copy"))
    if contract is None:
        _refuse("Choose copied groups explicitly, including an empty list for none",
                code="organization_copy_required", status=422)
    return normalized


def _editable(source):
    if source is None or source.group_organization is None:
        _refuse("Owned pattern work requires an organized part")
    state._assert_active_loadout_editable(source)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        _refuse("Return to the latest feature before changing a pattern")


def _current(context, session, deadline, cancelled):
    gate.require_group_edit_enabled()
    if cancelled.is_set():
        _refuse("Pattern operation was cancelled", code="cancelled")
    if monotonic() >= deadline:
        _refuse("Pattern recipe regeneration time limit", code="time_limit", status=408)
    doc = doc_context.get_current_doc()
    if (doc != context.doc_id or state._sessions.get(doc) is not session
            or not permits.context_matches(context, doc, session)):
        _refuse("The captured part, session, revision or construction policy changed", code="source_changed")
    policy.require_compatibility(doc, "owned_recipe_rebuild")
    _editable(session.design)


def _validation(value):
    if (type(value) is not dict or set(value) != {"passed", "results"}
            or type(value["passed"]) is not bool or type(value["results"]) is not list):
        _refuse("Worker validation report is malformed", code="invalid_pattern_result")
    results = []
    for row in value["results"]:
        if (type(row) is not dict or set(row) != {"ok", "message"}
                or type(row["ok"]) is not bool or type(row["message"]) is not str):
            _refuse("Worker validation item is malformed", code="invalid_pattern_result")
        results.append(ValidationResult(**row))
    report = ValidationReport(results=results)
    if report.passed != value["passed"]:
        _refuse("Worker validation summary differs", code="invalid_pattern_result")
    return report


def _run(kind, inputs, *, expected_design_id, expected_revision, index=None,
         expected_feature_id=None, cancelled=None):
    gate.require_group_edit_enabled()
    doc = doc_context.get_current_doc()
    policy.require_compatibility(doc, "owned_recipe_rebuild")
    _expectations(expected_design_id, expected_revision, cancelled)
    cancelled = cancelled if cancelled is not None else Event()
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    slot_owned = True
    deadline = monotonic() + TIME_BUDGET
    try:
        with state._lock:
            gate.require_group_edit_enabled()
            policy.require_compatibility(doc, "owned_recipe_rebuild")
            session = state._sessions.get(doc)
            if session is None or session.design is None:
                _refuse("No current part")
            source = session.design
            if source.id != expected_design_id or session.revision != expected_revision:
                _refuse("Pattern request belongs to another part or revision", code="source_changed")
            _editable(source)
            if cancelled.is_set():
                _refuse("Pattern operation was cancelled", code="cancelled")
            previous = None
            if index is not None:
                if (type(index) is not int or not 0 <= index < len(source.feature_log)
                        or type(expected_feature_id) is not str):
                    _refuse("Select the original native pattern feature")
                entry = source.feature_log[index]
                if (entry.id != expected_feature_id or entry.feature_type != "snapshot"
                        or entry.op_kind not in PATTERN_COMMANDS
                        or type(entry.params.get("_proof_version")) is not int
                        or entry.params["_proof_version"] != 1):
                    _refuse("The selected native pattern feature changed", code="source_changed")
                kind, previous = entry.op_kind, entry.params
            choices = _inputs(kind, inputs, previous=previous)
            retained_recovery_bytes(source.feature_log, max_rows=MAX_HISTORY_ROWS)
            for _ in command_rows(source, MAX_HISTORY_ROWS - (index is None)):
                pass
            request = EvaluationRequest(operation="append" if index is None else "edit",
                kind=kind if index is None else None, params=choices, index=index,
                expected_revision=expected_revision)
            definition = request.model_dump(mode="json")
            request_hash = digest({"request": definition, "expected_design_id": expected_design_id,
                                   "expected_feature_id": expected_feature_id})
            captured = capture(source, preserve_entry_types=True)
            admission = permits.admit_organized_recipe(doc, session, operation="pattern", request_sha256=request_hash)
            context = permits.admission_context(admission)
            _current(context, session, deadline, cancelled)
            identity = str(uuid4()) if index is None else source.feature_log[index].id
            operation = {"request": definition, "header": {"pattern_recording_version": 1,
                "identity": identity, "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_revision": expected_revision, "source_design_id": source.id,
                "expected_feature_id": expected_feature_id}}
            job = EvaluationJob(doc, ref(source), expected_revision, cancelled=cancelled,
                admitted_operation="pattern", session_identity=session.identity,
                admission=admission, request_sha256=request_hash)

        # The existing supervisor owns the shared slot until reaping/cleanup.
        # Its remaining deadline includes this host's capture/admission time.
        slot_owned = False
        result = supervise(job, captured, lambda design: EvaluationWorker(design, operation),
                           max(0.0, deadline - monotonic()))
        if result.get("status") != "ready":
            issues = result.get("issues", [])
            code = issues[0].get("code") if issues and type(issues[0]) is dict else "pattern_not_reproducible"
            status = 408 if code == "time_limit" else 413 if code in {"worker_input_limit", "result_limit"} else 409
            raise HTTPException(status, detail={"code": code, "assessment": result})
        with state._lock:
            _current(context, session, deadline, cancelled)
        candidate, _authoring_digest, _recipe_digest = decode_candidate(result["candidate"])
        admit(candidate, preserve_entry_types=True)
        require_valid_structure(candidate)
        report = _validation(result.get("validation"))
        if "pattern_report" not in result:
            _refuse("Native copy report is missing", code="invalid_pattern_result")
        copy_report = result["pattern_report"]
        validate_operation_input(copy_report)
        with state._lock:
            _current(context, session, deadline, cancelled)
            candidate = preserve_document_state(session.design, candidate)
            state._assert_active_loadout_editable(session.design, candidate)
            state._assert_photoproduct_dependencies(candidate)
            permit = permits.issue_organized_recipe_permit(admission, candidate,
                request_sha256=request_hash, expires=deadline, cancelled=cancelled)
            publish_replacement(session, candidate, publication_permit=permit)
            entry = candidate.feature_log[-1 if index is None else index]
            doc_context.set_request_feature_log_entry_id(entry.id)
        return candidate, report, entry, copy_report
    except CandidateDecodeError as error:
        _refuse(str(error), code=error.code)
    except (CaptureLimit, ProofBudgetExceeded) as error:
        _refuse(str(error), code="pattern_capture_limit", status=413)
    except CommandContractError as error:
        raise HTTPException(422, detail=error.as_issue()) from error
    except (ValidationError, ValueError, KeyError, TypeError) as error:
        _refuse(str(error)[:2048], code="invalid_pattern_input", status=422)
    finally:
        if slot_owned:
            _slot.release()


def create(kind, inputs, *, expected_design_id, expected_revision, cancelled=None):
    return _run(kind, inputs, expected_design_id=expected_design_id,
                expected_revision=expected_revision, cancelled=cancelled)


def edit(index, params, *, expected_feature_id, expected_design_id, expected_revision, cancelled=None):
    return _run(None, params, index=index, expected_feature_id=expected_feature_id,
                expected_design_id=expected_design_id, expected_revision=expected_revision, cancelled=cancelled)
