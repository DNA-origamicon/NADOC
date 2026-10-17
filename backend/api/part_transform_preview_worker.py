"""Private numerical transform preparation and full edit in disposable children.

This pair is deliberately not connected to the editor lease host yet. A live
cutover needs separate computation/ready/receipt lifetimes and visible Cancel.
Ordinary Prepare/Evaluate/Apply keep their existing deadlines and executors.
The caller owns admission, supervision, source checks and publication; a child
result is neither a lease nor a proof certificate for a later source revision.
"""

from copy import deepcopy

from fastapi import HTTPException

from backend.api import part_deformation_preview as preview
from backend.api.part_evaluation_candidate import decode_candidate
from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES, native_thread_limit, run_operation
from backend.api.part_model_serialization import SerializationShapeError, admit_model_serialization
from backend.api.part_proof_commands import execute_long
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_transform_preview import bind_prepared, select_from_capture
from backend.api.part_verification_worker import VerificationWorker
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_verification_capture import CaptureLimit


NUMERICAL_KINDS = frozenset({"photoproduct-create", "photoproduct-relax", "duplex-relax"})
MAX_PREFIX_BYTES = 2_000_000
MAX_PREFIX_NODES = 30_000


def _fail(detail, code="invalid_transform_worker_result"):
    raise CommandContractError(detail, code=code)


def _check():
    # The disposable child's supervising owner enforces the wall-clock limit.
    # Native solvers need process termination, not an in-process callback timer.
    pass


def _binding(source, selected, kind, operation):
    _serialization_budget(source)
    return {"design_id": source.id, "feature_id": selected.id, "kind": kind,
            "definition_sha256": digest(selected.model_dump(mode="json")),
            "capture_sha256": digest(source.model_dump(mode="json")),
            "request_sha256": digest(operation)}


def _request(value):
    validate_operation_input(value)
    if (type(value) is not dict or set(value) != {"action", "feature_id", "params"}
            or type(value["action"]) is not str or value["action"] not in {"prepare", "apply"}
            or (value["params"] is not None if value["action"] == "prepare"
                else type(value["params"]) is not dict)):
        _fail("Unknown private transform worker operation", "invalid_transform_worker_request")
    preview._identity(value["feature_id"])
    return value


def _run(kind, design, params, check):
    if kind not in NUMERICAL_KINDS:
        return preview._run(kind, design, params, check)
    # Bound the actual native substrate before any atomistic or relaxation work.
    # These operations change poses, not material; conversion adds one junction
    # and at most two residue poses. Engine/reference checks remain native.
    preview._admit(design, check)
    preview._work(design, check)
    if "_generated_scope" in params:
        _fail("Generated numerical scope is not admitted", "unsupported_preview_scope")
    if (len(design.photoproduct_junctions) + (kind == "photoproduct-create") > preview.MAX_SLOTS
            or len(design.nucleotide_transforms) + (2 if kind == "photoproduct-create" else 0) > preview.MAX_SLOTS):
        _fail("Numerical placement exceeds the preview object allowance", "preview_limit")
    result = execute_long(kind, design, params)
    preview._admit(result, check)
    preview._work(result, check)
    return result


class _PrefixFailure(CommandContractError):
    def __init__(self, feature_id, error):
        super().__init__(str(error), code=error.code)
        self.status = error.status
        self.issue = {**error.as_issue(), "feature_id": feature_id}

    def as_issue(self):
        return self.issue


def _run_prefix(feature_id, kind, design, params, check):
    try:
        return _run(kind, design, params, check)
    except CommandContractError as error:
        raise _PrefixFailure(feature_id, error) from error


def evaluate_operation(source, operation):
    """Fixed child entry; never accepts an arbitrary callback or public job kind."""
    try:
        operation = _request(operation)
        feature, rows, selected, kind = select_from_capture(source, operation["feature_id"], _check)
        binding = _binding(source, selected, kind, operation)
        with native_thread_limit():
            if operation["action"] == "prepare":
                prefix = preview._replay_prefix(source, rows, _check, stop=feature, runner=_run_prefix)
                prepared = bind_prepared(source, feature, kind, selected, prefix, _check)
                _serialization_budget(prepared._prefix)
                return {"status": "prepared", "issues": [], "binding": binding,
                        "prefix": prepared._prefix.model_dump(mode="json"),
                        "entry": prepared._entry.model_dump(mode="json")}
            indices = [i for i, row in enumerate(source.feature_log) if row.id == feature]
            if len(indices) != 1:
                _fail("Select one top-level transform feature", "ambiguous_feature")
            candidate, report = prepare_change(source, source, indices[0], _check,
                params=operation["params"], executor=lambda k, d, p: _run(k, d, p, _check))
            _serialization_budget(candidate, max_bytes=MAX_CANDIDATE_BYTES, max_nodes=None)
            return {"status": "ready", "issues": [], "binding": binding,
                    "candidate": candidate.model_dump(mode="json"),
                    "validation": {"passed": report.passed, "results": [
                        {"ok": row.ok, "message": row.message} for row in report.results]}}
    except CommandContractError as error:
        return {"status": error.status, "issues": [error.as_issue()]}
    except HTTPException as error:
        # Preserve feature IDs, reference paths and failure status for the owner.
        return {"status": "failed", "issues": [{"code": "evaluation_rejected",
                "http_status": error.status_code, "detail": error.detail}]}


def _prepare(input_name, input_size, output_name):
    run_operation(input_name, input_size, output_name, evaluate_operation, MAX_PREFIX_BYTES)


def _apply(input_name, input_size, output_name):
    run_operation(input_name, input_size, output_name, evaluate_operation, MAX_CANDIDATE_BYTES)


class TransformPreviewWorker(VerificationWorker):
    """One closed operation, existing input cap, independent finite output caps."""

    def __init__(self, source, feature_id, *, params=None):
        operation = _request({"action": "prepare" if params is None else "apply",
                              "feature_id": feature_id, "params": params})
        self.action = operation["action"]
        super().__init__({"source": source, "operation": deepcopy(operation)},
            _target=_prepare if self.action == "prepare" else _apply,
            _result_limit=MAX_PREFIX_BYTES if self.action == "prepare" else MAX_CANDIDATE_BYTES,
            _name="nadoc-transform-preview")

    def result(self):
        result = self._read_result()
        if result.get("status") not in {"prepared", "ready", "failed", "mismatch", "unverified"}:
            _fail("Unknown private transform worker result status")
        if result["status"] == ("ready" if self.action == "prepare" else "prepared"):
            _fail("Result belongs to a different transform worker operation")
        return result


def _serialization_budget(value, *, max_bytes=MAX_PREFIX_BYTES, max_nodes=MAX_PREFIX_NODES):
    """Reuse occurrence-based model/JSON admission before dump/hash or decode.

    Worker responses have already crossed the strict JSON transport. Captured
    model graphs can share values, so graph capture alone cannot bound a dump.
    """
    try:
        admit_model_serialization(value, max_bytes=max_bytes, max_nodes=max_nodes,
                                  label="Transform worker serialization")
    except CaptureLimit as error:
        _fail(str(error), "preview_limit")
    except SerializationShapeError as error:
        _fail(str(error))


def decode_prepared(captured, feature_id, result):
    """Check child binding and exact decode, then rebind cheap original inputs.

    No source equivalence is inferred here. Apply independently proves the full
    source and suffix; the eventual host must also enforce its live-source CAS.
    """
    _serialization_budget(result)
    check = preview._checkpoint()
    feature, _rows, selected, kind = select_from_capture(captured, feature_id, check)
    operation = _request({"action": "prepare", "feature_id": feature_id, "params": None})
    if (type(result) is not dict or set(result) != {"status", "issues", "binding", "prefix", "entry"}
            or result["status"] != "prepared" or result["issues"] != []
            or result["binding"] != _binding(captured, selected, kind, operation)):
        _fail("Prepared transform does not match the exact captured selection")
    prefix, _authoring, _recipe = decode_candidate(result["prefix"])
    if digest(prefix.model_dump(mode="json")) != digest(result["prefix"]):
        _fail("Prepared prefix changed during decoding")
    if (prefix.id != captured.id or prefix.recipe_root != captured.recipe_root
            or prefix.feature_log or prefix.input_sources or prefix.feature_log_cursor != -1
            or prefix.feature_log_sub_cursor is not None):
        _fail("Prepared prefix contains a different root or retained history")
    preview._work(prefix, check)
    prepared = bind_prepared(captured, feature, kind, selected, prefix, check)
    if digest(prepared._entry.model_dump(mode="json")) != digest(result["entry"]):
        _fail("Prepared transform inputs differ from their prefix binding")
    return prepared


def decode_applied(captured, feature_id, result, *, params):
    """Check the original definition and reuse exact candidate decode parity."""
    _feature, _rows, selected, kind = select_from_capture(captured, feature_id, preview._checkpoint())
    operation = _request({"action": "apply", "feature_id": feature_id, "params": params})
    if (type(result) is not dict
            or set(result) != {"status", "issues", "binding", "candidate", "validation"}
            or result["status"] != "ready" or result["issues"] != []
            or result["binding"] != _binding(captured, selected, kind, operation)):
        _fail("Edited transform does not match the exact captured selection")
    candidate = decode_candidate(result["candidate"])[0]
    if (candidate.id != captured.id or candidate.recipe_root != captured.recipe_root
            or [row.id for row in candidate.feature_log] != [row.id for row in captured.feature_log]
            or candidate.feature_log_cursor != -1 or candidate.feature_log_sub_cursor is not None):
        _fail("Edited transform changed the captured document/history identity")
    row = next(row for row in candidate.feature_log if row.id == feature_id)
    from backend.core.part_overlay_commands import command_input
    expected_kind = ("placement-poses" if kind == "cluster_op"
                     and params.get("upgrade_to") == "placement-poses-v1" else kind)
    if command_input(row)[0] != expected_kind:
        _fail("Edited transform changed the selected command role")
    return candidate
