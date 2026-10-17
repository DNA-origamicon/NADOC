"""One owned transaction for closed native construction families.

The closed families share capture, isolated input proof, exact source CAS and
one undo. This is not a generic operation/callback host. Extrusion edits also
admit compatibility documents; organized publication retains its explicit permit.
"""

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
from backend.api.part_source_bound_route import require_current as require_http_source
from backend.api.part_verification_jobs import supervise
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


def _refuse(message, *, code="recipe_conflict", status=409):
    raise HTTPException(status, detail={"code": code, "detail": message})


def _expectations(design_id, revision, cancelled, *, code):
    if type(design_id) is not str or not 1 <= len(design_id) <= 512:
        _refuse("An exact part identity is required", code=code, status=422)
    if type(revision) is not int or revision < 0:
        _refuse("An exact nonnegative revision is required", code=code, status=422)
    if cancelled is not None and not isinstance(cancelled, Event):
        _refuse("Cancellation must be a private host event", code=code, status=422)


def _editable(source, family):
    if source is None:
        _refuse("No current part")
    if family in {"pattern", "connection"} and source.group_organization is None:
        _refuse("This owned operation requires an organized part")
    if family == "pattern" or source.group_organization is not None:
        gate.require_group_edit_enabled()
    state._assert_active_loadout_editable(source)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        _refuse("Return to the latest feature before changing construction inputs")


def _current(context, session, deadline, cancelled, family):
    require_http_source()
    if cancelled.is_set():
        _refuse("Recipe operation was cancelled", code="cancelled")
    if monotonic() >= deadline:
        _refuse("Recipe regeneration time limit", code="time_limit", status=408)
    doc = doc_context.get_current_doc()
    if (doc != context.doc_id or state._sessions.get(doc) is not session
            or not permits.context_matches(context, doc, session)):
        _refuse("The captured part, session, revision or construction policy changed", code="source_changed")
    policy.require_compatibility(doc, "owned_recipe_rebuild")
    _editable(session.design, family)


def _validation(value, *, code):
    if (type(value) is not dict or set(value) != {"passed", "results"}
            or type(value["passed"]) is not bool or type(value["results"]) is not list):
        _refuse("Worker validation report is malformed", code=code)
    results = []
    for row in value["results"]:
        if (type(row) is not dict or set(row) != {"ok", "message"}
                or type(row["ok"]) is not bool or type(row["message"]) is not str):
            _refuse("Worker validation item is malformed", code=code)
        results.append(ValidationResult(**row))
    report = ValidationReport(results=results)
    if report.passed != value["passed"]:
        _refuse("Worker validation summary differs", code=code)
    return report


def _run(family, kind, inputs, *, expected_design_id, expected_revision, index=None,
         expected_feature_id=None, sub_index=None, expected_child_id=None,
         inputs_only=False, cancelled=None):
    if family not in {"pattern", "extrusion_edit", "routing_edit", "connection"}:
        _refuse("Unknown owned recipe family", code="invalid_operation_admission")
    error_prefix = {"pattern": "pattern", "extrusion_edit": "extrusion", "routing_edit": "routing", "connection": "connection"}[family]
    if family == "pattern":
        gate.require_group_edit_enabled()
        allowed = PATTERN_COMMANDS
    elif family == "connection":
        gate.require_group_edit_enabled()
        allowed = {"overhang-bulk"}
    elif family == "extrusion_edit":
        from backend.api.part_extrusion_edit_inputs import KINDS
        allowed = KINDS
        if index is None:
            _refuse("Extrusion admission is edit-only", code="invalid_operation_admission")
    else:
        from backend.api.part_routing_edit_inputs import KINDS
        allowed = KINDS
        if index is None or type(sub_index) is not int or sub_index < 0:
            _refuse("Select an exact routing child", code="invalid_operation_admission")
    if family != "routing_edit" and (sub_index is not None or expected_child_id is not None or inputs_only):
        _refuse("Only routing admission accepts a child or input preview", code="invalid_operation_admission")
    doc = doc_context.get_current_doc()
    policy.require_compatibility(doc, "owned_recipe_rebuild")
    _expectations(expected_design_id, expected_revision, cancelled,
                  code=f"invalid_{error_prefix}_input")
    cancelled = cancelled if cancelled is not None else Event()
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    slot_owned = True
    deadline = monotonic() + TIME_BUDGET
    try:
        with state._lock:
            require_http_source()
            policy.require_compatibility(doc, "owned_recipe_rebuild")
            session = state._sessions.get(doc)
            if session is None or session.design is None:
                _refuse("No current part")
            source = session.design
            if source.id != expected_design_id or session.revision != expected_revision:
                _refuse("Recipe request belongs to another part or revision", code="source_changed")
            _editable(source, family)
            if cancelled.is_set():
                _refuse("Recipe operation was cancelled", code="cancelled")
            previous = None
            if index is not None:
                if (type(index) is not int or not 0 <= index < len(source.feature_log)
                        or type(expected_feature_id) is not str):
                    _refuse("Select the original native feature")
                entry = source.feature_log[index]
                if family == "routing_edit":
                    from backend.api.part_routing_edit_evaluation import selected_child
                    child = selected_child(source, index, sub_index,
                        expected_feature_id=expected_feature_id, expected_child_id=expected_child_id)
                    kind, previous = child.op_subtype, child.params
                elif (entry.id != expected_feature_id or entry.feature_type != "snapshot"
                        or entry.op_kind not in allowed
                        or type(entry.params.get("_proof_version")) is not int
                        or entry.params["_proof_version"] != 1
                        or (family == "extrusion_edit" and
                            ("_generated_scope" in entry.params or "_generator" in entry.params))):
                    _refuse("The selected native feature changed", code="source_changed")
                else:
                    kind, previous = entry.op_kind, entry.params
            added_ids = []
            if family == "pattern":
                from backend.api.part_pattern_recording import _inputs
                choices = _inputs(kind, inputs, previous=previous)
            elif family == "connection":
                from backend.api.part_connection_recipe_recording import normalize
                choices = normalize(kind, inputs, previous=previous)
            elif family == "extrusion_edit":
                from backend.api.part_extrusion_edit_inputs import normalize
                choices = normalize(kind, previous, inputs)
            else:
                from backend.api.part_routing_edit_inputs import allocate_output_slots, normalize
                allocated = allocate_output_slots(kind, previous, {} if inputs_only else inputs)
                added_ids = allocated["added_ids"]
                choices = normalize(kind, previous, allocated["changes"], added_output_ids=added_ids)
            retained_recovery_bytes(source.feature_log, max_rows=MAX_HISTORY_ROWS)
            for _ in command_rows(source, MAX_HISTORY_ROWS - (index is None)):
                pass
            request = EvaluationRequest(operation="append" if index is None else "edit",
                kind=kind if index is None else None, params=choices, index=index, sub_index=sub_index,
                expected_revision=expected_revision)
            definition = request.model_dump(mode="json")
            request_hash = digest({"request": definition, "expected_design_id": expected_design_id,
                                   "expected_feature_id": expected_feature_id,
                                   "expected_child_id": expected_child_id, "inputs_only": inputs_only,
                                   "added_output_ids": added_ids})
            captured = capture(source, preserve_entry_types=True)
            if family == "routing_edit":
                from backend.api.part_group_geometry_budget import require_group_geometry_budget
                require_group_geometry_budget(captured)
            organized = source.group_organization is not None
            admission = (permits.admit_organized_recipe(doc, session,
                operation=family, request_sha256=request_hash) if organized else
                permits.admit_evaluation(doc, session, operation="edit", request_sha256=request_hash))
            context = permits.admission_context(admission)
            _current(context, session, deadline, cancelled, family)
            identity = str(uuid4()) if index is None else source.feature_log[index].id
            operation = {"request": definition, "header": {
                "identity": identity, "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_revision": expected_revision, "source_design_id": source.id,
                "expected_feature_id": expected_feature_id}}
            if family == "pattern":
                operation["header"]["pattern_recording_version"] = 1
            elif family == "connection":
                operation["header"]["connection_recording_version"] = 1
            elif family == "extrusion_edit":
                operation["header"].update(extrusion_recording_version=1, expected_kind=kind)
            else:
                operation["header"].update(routing_recording_version=1, expected_kind=kind,
                    expected_child_id=expected_child_id, routing_inputs_only=inputs_only,
                    added_output_ids=added_ids)
            job = EvaluationJob(doc, ref(source), expected_revision, cancelled=cancelled,
                admitted_operation=family if organized else "edit", session_identity=session.identity,
                admission=admission, request_sha256=request_hash)

        # The existing supervisor owns the shared slot until reaping/cleanup.
        # Its remaining deadline includes this host's capture/admission time.
        slot_owned = False
        result = supervise(job, captured, lambda design: EvaluationWorker(design, operation),
                           max(0.0, deadline - monotonic()))
        if result.get("status") != ("preview" if inputs_only else "ready"):
            issues = result.get("issues", [])
            code = issues[0].get("code") if issues and type(issues[0]) is dict else "recipe_not_reproducible"
            status = 408 if code == "time_limit" else 413 if code in {"worker_input_limit", "result_limit"} else 409
            raise HTTPException(status, detail={"code": code, "assessment": result})
        with state._lock:
            _current(context, session, deadline, cancelled, family)
        if inputs_only:
            from backend.api.part_routing_edit_context import validate_packet
            packet = validate_packet(result.get("routing_inputs"), kind=kind,
                design_id=expected_design_id, revision=expected_revision,
                feature_id=expected_feature_id, child_id=expected_child_id, expected_params=choices)
            with state._lock:
                _current(context, session, deadline, cancelled, family)
            return packet
        candidate, _authoring_digest, _recipe_digest = decode_candidate(result["candidate"])
        admit(candidate, preserve_entry_types=True)
        require_valid_structure(candidate)
        if family == "routing_edit":
            require_group_geometry_budget(candidate)
        report = _validation(result.get("validation"),
            code=f"invalid_{error_prefix}_result")
        copy_report = None
        if family == "pattern":
            if "pattern_report" not in result:
                _refuse("Native copy report is missing", code="invalid_pattern_result")
            copy_report = result["pattern_report"]
            validate_operation_input(copy_report)
        with state._lock:
            _current(context, session, deadline, cancelled, family)
            candidate = preserve_document_state(session.design, candidate)
            state._assert_active_loadout_editable(session.design, candidate)
            state._assert_photoproduct_dependencies(candidate)
            _current(context, session, deadline, cancelled, family)
            permit = (permits.issue_organized_recipe_permit(admission, candidate,
                request_sha256=request_hash, expires=deadline, cancelled=cancelled) if organized else None)
            publish_replacement(session, candidate, publication_permit=permit)
            entry = candidate.feature_log[-1 if index is None else index]
            doc_context.set_request_feature_log_entry_id(entry.id)
        return candidate, report, entry, copy_report
    except CandidateDecodeError as error:
        _refuse(str(error), code=error.code)
    except (CaptureLimit, ProofBudgetExceeded) as error:
        _refuse(str(error), code=f"{error_prefix}_capture_limit", status=413)
    except CommandContractError as error:
        raise HTTPException(409 if error.code == "source_changed" else 422, detail=error.as_issue()) from error
    except (ValidationError, ValueError, KeyError, TypeError) as error:
        _refuse(str(error)[:2048], code=f"invalid_{error_prefix}_input", status=422)
    finally:
        if slot_owned:
            _slot.release()


def run_pattern(kind, inputs, *, expected_design_id, expected_revision, index=None,
                expected_feature_id=None, cancelled=None):
    return _run("pattern", kind, inputs, expected_design_id=expected_design_id,
                expected_revision=expected_revision, index=index,
                expected_feature_id=expected_feature_id, cancelled=cancelled)


def edit_extrusion(index, params, *, expected_feature_id, expected_design_id, expected_revision, cancelled=None):
    candidate, report, entry, _ = _run("extrusion_edit", None, params,
        index=index, expected_feature_id=expected_feature_id,
        expected_design_id=expected_design_id, expected_revision=expected_revision,
        cancelled=cancelled)
    return candidate, report, entry


def edit_routing(index, sub_index, params, *, expected_feature_id, expected_child_id,
                 expected_design_id, expected_revision, cancelled=None):
    candidate, report, entry, _ = _run("routing_edit", None, params,
        index=index, sub_index=sub_index, expected_feature_id=expected_feature_id,
        expected_child_id=expected_child_id, expected_design_id=expected_design_id,
        expected_revision=expected_revision, cancelled=cancelled)
    return candidate, report, entry


def routing_inputs(index, sub_index, *, expected_feature_id, expected_child_id,
                   expected_design_id, expected_revision, cancelled=None):
    return _run("routing_edit", None, {}, inputs_only=True, index=index, sub_index=sub_index,
        expected_feature_id=expected_feature_id, expected_child_id=expected_child_id,
        expected_design_id=expected_design_id, expected_revision=expected_revision, cancelled=cancelled)


def run_connection(inputs, *, expected_design_id, expected_revision, index=None,
                   expected_feature_id=None, cancelled=None):
    return _run("connection", "overhang-bulk", inputs,
                expected_design_id=expected_design_id, expected_revision=expected_revision,
                index=index, expected_feature_id=expected_feature_id, cancelled=cancelled)
