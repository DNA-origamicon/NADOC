"""Numerical work owned by an existing preview lease, never a second job registry.

Only histories containing fixed native numerical commands enter this lane. The
host retains source checks and publication; this owner retains both admissions
until child cleanup, decode and adoption finish. Polling cannot renew a lease.
"""

from contextvars import copy_context
from dataclasses import dataclass
from threading import Thread
from time import monotonic

from fastapi import HTTPException

from backend.api.part_history_verification import _slot as proof_slot
from backend.api.part_transform_preview_worker import (
    NUMERICAL_KINDS, TransformPreviewWorker, decode_applied, decode_prepared,
)
from backend.api.part_verification_jobs import Job, supervise
from backend.core.models import SnapshotLogEntry


COMPUTE_SECONDS = 180.0


@dataclass
class Computation(Job):
    operation: str = "prepare"
    sequence: int = 0
    started: float = 0
    deadline: float = 0
    finished: float | None = None
    session_identity: str = ""
    policy_generation: int = -1


def required(captured):
    # Capture has already bounded the typed graph. Full native contract
    # admission still runs before selecting a worker or executing any command.
    return any(type(row) is SnapshotLogEntry and row.op_kind in NUMERICAL_KINDS
               for parent in captured.feature_log
               for row in ([parent, *parent.children] if parent.feature_type == "routing-cluster" else [parent]))


def start_thread(callback):
    context = copy_context()
    Thread(target=context.run, args=(callback,), name="transform-preview-supervisor", daemon=False).start()


def fields(operation):
    now = monotonic() if operation.finished is None else operation.finished
    return {"version": 1, "operation": operation.operation,
            "request_sequence": operation.sequence,
            "elapsed_seconds": max(0, now - operation.started),
            "remaining_seconds": max(0, operation.deadline - now)}


def _result(result, entry):
    # The supervisor adds these trusted scalars; every child field still goes
    # through the closed exact-result decoder, including unknown-field refusal.
    value = dict(result)
    if (value.pop("source_revision", None) != entry.request.expected_revision
            or value.pop("design_id", None) != entry.request.expected_design_id):
        raise HTTPException(409, detail={"code": "source_changed"})
    if value.get("issues"):
        issue = value["issues"][0]
        code = issue.get("code")
        status = (issue.get("http_status", 422) if code == "evaluation_rejected" else
                  408 if code == "time_limit" else
                  409 if code in {"cancelled", "source_changed", "policy_changed", "source_busy"} else
                  413 if code in {"worker_input_limit", "worker_output_limit", "result_limit", "preview_limit"} else 422)
        raise HTTPException(status, detail=issue.get("detail", issue) if code == "evaluation_rejected" else issue)
    return value


def _failure(host, entry, operation, error):
    from backend.api.part_model_serialization import admit_model_serialization

    failure = {"status": error.status_code, "detail": error.detail}
    try:
        admit_model_serialization(failure, max_bytes=32_000, max_nodes=2000, label="Preview failure")
    except (ValueError, TypeError):
        failure = {"status": 500, "detail": {"code": "preview_failure_limit"}}
    # Cancellation, replacement, session/policy changes and expiry cannot
    # resurrect a prefix. A native refusal on a current source keeps the draft.
    try:
        with host.state._lock:
            host._source_current(entry)
            with host._lock:
                host._catalog_current(entry, operation.sequence)
                if entry.publication is not None:
                    return  # Publication is authoritative even if later cleanup fails.
                if operation.operation == "prepare":
                    entry.prepared = entry.payload = None
                entry.failure = failure
                entry.phase = "ready" if operation.operation == "apply" else "failed"
                operation.finished = monotonic()
                host._renew(entry, host.TTL_SECONDS)
    except HTTPException:
        with host._lock:
            if host._entries.get(entry.doc) is entry:
                host._remove(entry)


def _run(host, entry, operation, captured, request, params, admission, request_sha256):
    supervised = False
    try:
        with host._mapped_errors():
            host._current(entry, operation.sequence)
            if operation.cancelled.is_set():
                raise HTTPException(409, detail={"code": "cancelled"})
            supervised = True  # supervise owns proof admission through cleanup.
            result = supervise(operation, captured,
                lambda source: TransformPreviewWorker(source, entry.request.feature_id, params=params),
                max(0, operation.deadline - monotonic()), status_lock=host._lock)
            result = _result(result, entry)
            host._current(entry, operation.sequence)
            if operation.operation == "prepare":
                prepared = decode_prepared(captured, entry.request.feature_id, result)
                evaluated = host.family_work.evaluate_original(entry.family, prepared)
                # Project outside owner locks, then start the ready lease only
                # after the final origin check. The cached packet owns no model.
                envelope = host._envelope(entry, 0, prepared=prepared)
                envelope["remaining_seconds"] = host.TTL_SECONDS
                payload = host.family_work.prepare_display(entry.family, prepared, evaluated, envelope=envelope)
                from backend.api.part_transform_preview_dto import _bounded
                _bounded({**envelope, "status": "ready", "computation": fields(operation), "result": payload})
                with host.state._lock:
                    host._source_current(entry)
                    with host._lock:
                        host._catalog_current(entry, operation.sequence)
                        entry.prepared, entry.payload, entry.phase = prepared, payload, "ready"
                        operation.finished = monotonic()
                        host._renew(entry, host.TTL_SECONDS)
            else:
                candidate = decode_applied(captured, entry.request.feature_id, result, params=params)
                host._publish(entry, request, candidate, operation.deadline, admission,
                              request_sha256, renew_receipt=True)
                operation.finished = monotonic()
    except HTTPException as error:
        _failure(host, entry, operation, error)
    except Exception:
        # No traceback, model or unbounded native exception enters a response.
        _failure(host, entry, operation, HTTPException(500, detail={"code": "preview_computation_error"}))
    finally:
        operation.result = None
        with host._lock:
            if entry.applying_sequence == operation.sequence:
                entry.applying_sequence = None
        if not supervised:
            proof_slot.release()
        host._work_slot.release()


def _begin(host, entry, captured, *, request=None, params=None, admission=None, request_sha256=None):
    if not proof_slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    previous_expiry = entry.expires
    try:
        sequence = 0 if request is None else request.request_sequence
        host._current(entry, sequence)
        started = monotonic()
        operation = Computation(entry.doc, entry.source, entry.request.expected_revision,
            operation="prepare" if request is None else "apply", sequence=sequence,
            started=started, deadline=started + COMPUTE_SECONDS,
            session_identity=entry.session_identity, policy_generation=entry.policy_generation)
        with host._lock:
            host._catalog_current(entry, operation.sequence)
            entry.computation, entry.numerical = operation, True
            entry.phase = "preparing" if request is None else "applying"
            entry.payload = entry.failure = None
            host._renew(entry, COMPUTE_SECONDS)
            ack = {**host._envelope(entry, operation.sequence), "status": entry.phase,
                   "computation": fields(operation)}
        start_thread(lambda: _run(host, entry, operation, captured, request, params, admission, request_sha256))
        return ack
    except BaseException:
        proof_slot.release()
        with host._lock:
            if host._entries.get(entry.doc) is entry:
                entry.computation = None
                entry.phase = "ready" if request is not None else "preparing"
                host._renew(entry, max(0, previous_expiry - monotonic()))
        raise


def begin_prepare(host, entry, captured, kind):
    entry.identity = {"family": "transform", "command_kind": kind}
    return _begin(host, entry, captured)


def begin_apply(host, entry, captured, request, params, admission, request_sha256):
    return _begin(host, entry, captured, request=request, params=params,
                  admission=admission, request_sha256=request_sha256)
