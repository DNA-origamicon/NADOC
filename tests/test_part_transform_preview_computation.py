"""Deterministic async lease tests; numerical work stays in its real child API.

The scheduler is queued and the supervisor is replaced at its existing seam.
No child processes, sleeps, numerical fixtures or document publications are
mocked: the tiny native recipe still prepares, rebuilds, proves and commits.
"""

from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_publication_policy as policy
from backend.api import part_transform_preview_computation as computation
from backend.api import part_transform_preview_worker as worker
from backend.api.part_history_verification import _slot as proof_slot
from backend.core.models import Design
from tests.test_part_deformation_preview_sessions import cancellation, checkpoint, unchanged
from tests.test_part_transform_preview_sessions import (
    FAMILY, identity, opening, update, verified,
)

from tests import test_part_transform_preview_sessions as preview_sessions


document = preview_sessions.document


@pytest.fixture
def lane(document, monkeypatch):
    queued, calls = [], []
    clock = [100.0]

    class Request:
        def __init__(self, source, feature_id, *, params=None):
            self.source = source
            self.operation = {"action": "prepare" if params is None else "apply",
                              "feature_id": feature_id, "params": deepcopy(params)}

    def supervise(job, captured, worker_factory, seconds, **_kwargs):
        assert not proof_slot.acquire(blocking=False), "supervisor must receive admission"
        try:
            request = worker_factory(captured)
            calls.append(request.operation)
            result = (deepcopy(value.worker_result) if value.worker_result is not None
                      else worker.evaluate_operation(captured, request.operation))
            if value.after_result is not None:
                value.after_result()
            return {**result, "source_revision": job.revision, "design_id": captured.id}
        finally:
            proof_slot.release()

    monkeypatch.setattr(computation, "required", lambda _captured: True)
    monkeypatch.setattr(computation, "start_thread", queued.append)
    monkeypatch.setattr(computation, "TransformPreviewWorker", Request)
    monkeypatch.setattr(computation, "supervise", supervise)
    monkeypatch.setattr(computation, "monotonic", lambda: clock[0])
    monkeypatch.setattr(host, "monotonic", lambda: clock[0])

    def run():
        assert queued, "one admitted operation must be queued"
        queued.pop(0)()

    value = SimpleNamespace(doc=document, queued=queued, calls=calls, clock=clock, run=run,
                            worker_result=None, after_result=None)
    try:
        yield value
    finally:
        host.clear_for_testing()
        while queued:
            run()
        for slot in (host._work_slot, proof_slot):
            assert slot.acquire(blocking=False), "operation leaked admission"
            slot.release()


def status(opened):
    return host.status(cancellation(opened), family=FAMILY)


def ready(lane):
    ack = host.prepare(opening(), family=FAMILY)
    assert ack["status"] == "preparing"
    lane.run()
    result = status(ack)
    assert result["status"] == "ready", result
    return result["result"]


def test_prepare_ack_then_status_returns_owned_packet_with_fresh_ready_lease(lane):
    before = checkpoint()
    ack = host.prepare(opening(), family=FAMILY)
    identity(ack, "cluster_op")
    assert ack["status"] == "preparing" and ack["request_sequence"] == 0
    assert "candidate" not in ack and "result" not in ack
    assert ack["computation"]["version"] == 1
    assert ack["computation"]["operation"] == "prepare"
    assert ack["computation"]["request_sequence"] == 0
    assert ack["computation"]["remaining_seconds"] == 180
    assert len(lane.queued) == 1 and lane.calls == []
    unchanged(before)
    lane.clock[0] += 75
    assert status(ack)["status"] == "preparing"
    lane.run()
    result = status(ack)
    packet = result["result"]
    assert result["status"] == "ready" and result["remaining_seconds"] == 60
    assert packet["remaining_seconds"] == 60
    assert packet["lease_id"] == ack["lease_id"] and packet["doc_id"] == lane.doc
    identity(packet, "cluster_op")
    assert packet["before"] is not None and packet["candidate"] is not None
    assert packet["source_equivalence_checked"] is False
    assert packet["downstream_evaluated"] is False
    assert [call["action"] for call in lane.calls] == ["prepare"]
    unchanged(before)


def test_cancel_queued_prepare_signals_exact_operation_and_cannot_restore_it(lane):
    before = checkpoint()
    ack = host.prepare(opening(), family=FAMILY)
    operation = host._entries[lane.doc].computation
    assert not operation.cancelled.is_set()
    assert host.cancel(cancellation(ack), family=FAMILY)["status"] == "cancelled"
    assert operation.cancelled.is_set()
    lane.run()
    assert lane.doc not in host._entries and lane.calls == []
    with pytest.raises(HTTPException) as caught:
        status(ack)
    assert caught.value.status_code == 409
    unchanged(before)


def test_ready_status_polling_decreases_both_ttls_without_renewing(lane):
    opened = ready(lane)
    expires = host._entries[lane.doc].expires
    lane.clock[0] += 11
    first = status(opened)
    assert first["remaining_seconds"] == 49
    assert first["result"]["remaining_seconds"] == 49
    lane.clock[0] += 7
    second = status(opened)
    assert second["remaining_seconds"] == second["result"]["remaining_seconds"] == 42
    assert host._entries[lane.doc].expires == expires


def test_apply_ack_and_lost_result_recover_one_publication_and_one_undo(lane):
    opened = ready(lane)
    before = checkpoint()
    params = {"translation": [6, 2, 1]}
    ack = host.apply(update(opened, sequence=1, params=params), family=FAMILY)
    assert ack["status"] == "applying"
    assert ack["computation"]["operation"] == "apply"
    assert ack["computation"]["request_sequence"] == 1
    unchanged(before)
    lane.clock[0] += 75
    lane.run()  # Deliberately discard the result; status is the recovery path.
    receipt = status(opened)
    identity(receipt, "cluster_op")
    assert receipt["status"] == "applied" and receipt["request_sequence"] == 1
    assert receipt["revision"] == before["revision"] + 1
    assert receipt["remaining_seconds"] == 60
    assert "candidate" not in receipt and "result" not in receipt
    candidate = state.get_or_404()
    assert candidate.feature_log[1].translation == params["translation"]
    assert before["source"].model_dump(mode="json") == before["json"]
    assert state.undo_depth() == len(before["history"]) + 1
    verified(Design.from_json(candidate.to_json()))
    assert status(opened)["revision"] == receipt["revision"]
    assert host.cancel(cancellation(opened), family=FAMILY)["status"] == "applied"
    with pytest.raises(HTTPException):
        host.apply(update(opened, sequence=2, params=params), family=FAMILY)
    assert len(lane.calls) == 2
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_old_prepare_timer_cannot_expire_new_ready_deadline(lane):
    ack = host.prepare(opening(), family=FAMILY)
    old_timer = host._entries[lane.doc].timer
    lane.clock[0] += 150
    lane.run()
    current_timer = host._entries[lane.doc].timer
    assert current_timer is not old_timer and old_timer.cancelled
    lane.clock[0] += 31  # old computation deadline passed, ready lease did not
    old_timer.callback()  # simulate a callback already running when cancelled
    assert status(ack)["status"] == "ready"
    assert status(ack)["remaining_seconds"] == 29
    lane.clock[0] += 30
    current_timer.callback()
    assert lane.doc not in host._entries


def test_old_ready_and_apply_timers_cannot_expire_compute_or_publication(lane):
    opened = ready(lane)
    old_ready = host._entries[lane.doc].timer
    host.apply(update(opened), family=FAMILY)
    old_compute = host._entries[lane.doc].timer
    lane.clock[0] += 150
    old_ready.callback()
    assert status(opened)["status"] == "applying"
    lane.run()
    publication_timer = host._entries[lane.doc].timer
    lane.clock[0] += 31
    old_compute.callback()
    receipt = status(opened)
    assert receipt["status"] == "applied" and receipt["remaining_seconds"] == 29
    expires = host._entries[lane.doc].expires
    assert status(opened)["revision"] == receipt["revision"]
    assert host._entries[lane.doc].expires == expires
    lane.clock[0] += 30
    publication_timer.callback()
    assert lane.doc not in host._entries


@pytest.mark.parametrize("phase", ["prepare", "apply"])
def test_computation_expiry_signals_cancellation_before_queued_work(lane, phase):
    opened = ready(lane) if phase == "apply" else None
    before = checkpoint()
    ack = (host.apply(update(opened), family=FAMILY) if opened else
           host.prepare(opening(), family=FAMILY))
    entry = host._entries[lane.doc]
    operation = entry.computation
    calls = len(lane.calls)
    lane.clock[0] += 181
    entry.timer.callback()
    assert operation.cancelled.is_set()
    lane.run()
    assert len(lane.calls) == calls and lane.doc not in host._entries
    with pytest.raises(HTTPException):
        status(ack)
    unchanged(before)


@pytest.mark.parametrize("phase", ["prepare", "apply"])
def test_cancel_after_worker_result_cannot_adopt_or_publish(lane, phase):
    opened = ready(lane) if phase == "apply" else None
    before = checkpoint()
    ack = (host.apply(update(opened), family=FAMILY) if opened else
           host.prepare(opening(), family=FAMILY))
    operation = host._entries[lane.doc].computation
    responses = []
    lane.after_result = lambda: responses.append(host.cancel(cancellation(ack), family=FAMILY))
    lane.run()
    assert responses[0]["status"] == "cancelled" and operation.cancelled.is_set()
    assert lane.doc not in host._entries
    unchanged(before)


@pytest.mark.parametrize("phase", ["prepare", "apply"])
@pytest.mark.parametrize("change", ["revision", "same-revision-source", "session-aba", "policy"])
def test_completed_work_cannot_cross_source_session_or_policy_boundary(lane, monkeypatch, phase, change):
    opened = ready(lane) if phase == "apply" else None
    ack = (host.apply(update(opened), family=FAMILY) if opened else
           host.prepare(opening(), family=FAMILY))
    after_change = []

    def replace_origin():
        source, revision = state.get_design_with_revision()
        if change == "revision":
            state.set_design(source.copy_with())
        elif change == "same-revision-source":
            with state._lock:
                state._session().design = source.model_copy(deep=True)
        elif change == "session-aba":
            old_identity = state._sessions[lane.doc].identity
            state.drop_doc(lane.doc)
            with state._lock:
                session = state._session()
                session.design, session.revision = source, revision
                assert session.identity != old_identity
        else:
            configuration, generation = policy._configuration
            monkeypatch.setattr(policy, "_configuration", (configuration, generation + 1))
        after_change.append(checkpoint())

    lane.after_result = replace_origin
    lane.run()
    assert after_change
    unchanged(after_change[0])
    with pytest.raises(HTTPException) as caught:
        status(ack)
    assert caught.value.status_code == 409
    assert lane.doc not in host._entries


@pytest.mark.parametrize("slot_name", ["proof", "work"])
def test_busy_admission_does_not_queue_or_retain_an_opening(lane, slot_name):
    slot = proof_slot if slot_name == "proof" else host._work_slot
    before = checkpoint()
    assert slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as caught:
            host.prepare(opening(), family=FAMILY)
        assert caught.value.status_code == 429
        assert lane.queued == [] and lane.doc not in host._entries
    finally:
        slot.release()
    unchanged(before)


def test_failed_thread_start_releases_both_slots_and_reserved_opening(lane, monkeypatch):
    before = checkpoint()

    def fail_start(_callback):
        raise RuntimeError("Injected thread start failure")

    monkeypatch.setattr(computation, "start_thread", fail_start)
    with pytest.raises((RuntimeError, HTTPException)):
        host.prepare(opening(), family=FAMILY)
    assert lane.queued == [] and lane.doc not in host._entries
    for slot in (host._work_slot, proof_slot):
        assert slot.acquire(blocking=False)
        slot.release()
    unchanged(before)


def test_numerical_lane_is_not_used_when_closed_detector_says_ordinary(lane, monkeypatch):
    monkeypatch.setattr(computation, "required", lambda _captured: False)
    opened = host.prepare(opening(), family=FAMILY)
    assert "status" not in opened and "computation" not in opened
    assert lane.queued == [] and opened["candidate"] is not None
    receipt = host.apply(update(opened), family=FAMILY)
    assert receipt["status"] == "applied" and "computation" not in receipt
    assert lane.queued == []


def test_prepare_failure_is_terminal_without_a_fabricated_ready_prefix(lane):
    before = checkpoint()
    lane.worker_result = {"status": "unverified", "issues": [{
        "code": "numerical_environment_mismatch", "detail": "Pinned engine unavailable"}]}
    ack = host.prepare(opening(), family=FAMILY)
    lane.run()
    result = status(ack)
    assert result["status"] == "failed"
    assert result["failure"]["detail"]["code"] == "numerical_environment_mismatch"
    assert result["computation"]["operation"] == "prepare"
    assert "result" not in result and host._entries[lane.doc].prepared is None
    with pytest.raises(HTTPException):
        host.evaluate(update(ack), family=FAMILY)
    with pytest.raises(HTTPException):
        host.apply(update(ack), family=FAMILY)
    assert len(lane.calls) == 1
    unchanged(before)


def test_typed_apply_failure_keeps_same_draft_sequence_and_allows_explicit_retry(lane):
    opened = ready(lane)
    before = checkpoint()
    detail = {"code": "missing_reference", "detail": "Downstream owner is missing",
              "feature_id": "later-feature", "references": [{
                  "kind": "helix", "identity": "missing-helix",
                  "parameter_path": ["helix_id"]}]}
    lane.worker_result = {"status": "failed", "issues": [{
        "code": "evaluation_rejected", "http_status": 409, "detail": detail}]}
    params = {"translation": [7, 3, 2]}
    host.apply(update(opened, sequence=4, params=params), family=FAMILY)
    lane.clock[0] += 75
    lane.run()
    result = status(opened)
    assert result["status"] == "ready" and result["request_sequence"] == 4
    assert result["failure"] == {"status": 409, "detail": detail}
    assert result["computation"]["operation"] == "apply"
    assert result["computation"]["request_sequence"] == 4
    assert result["remaining_seconds"] == 60
    assert "result" not in result and host._entries[lane.doc].prepared is not None
    assert lane.queued == [] and lane.calls[-1]["params"] == params
    unchanged(before)
    with pytest.raises(HTTPException):
        host.apply(update(opened, sequence=4, params=params), family=FAMILY)
    lane.worker_result = None
    assert host.apply(update(opened, sequence=5, params=params), family=FAMILY)["status"] == "applying"
    lane.run()
    assert status(opened)["status"] == "applied"
    assert state.undo_depth() == len(before["history"]) + 1


@pytest.mark.parametrize("code,http_status", [("time_limit", 408), ("result_limit", 413),
                                              ("worker_input_limit", 413), ("preview_limit", 413)])
def test_apply_worker_limit_failure_is_typed_and_never_publishes(lane, code, http_status):
    opened = ready(lane)
    before = checkpoint()
    lane.worker_result = {"status": "unverified", "issues": [{"code": code}]}
    host.apply(update(opened), family=FAMILY)
    lane.run()
    result = status(opened)
    assert result["status"] == "ready"
    assert result["failure"] == {"status": http_status, "detail": {"code": code}}
    assert "result" not in result and lane.queued == []
    unchanged(before)


def test_slider_after_numerical_prepare_reuses_prefix_without_new_worker(lane):
    opened = ready(lane)
    before = checkpoint()
    for sequence in (1, 2):
        response = host.evaluate({**update(opened, sequence=sequence,
            params={"translation": [sequence, 2, 3]}), "include_geometry": False}, family=FAMILY)
        assert response["candidate"] is None and response["request_sequence"] == sequence
    assert [call["action"] for call in lane.calls] == ["prepare"]
    assert lane.queued == [] and host._entries[lane.doc].payload is None
    unchanged(before)


def test_failed_apply_thread_start_keeps_existing_prefix_and_does_not_publish(lane, monkeypatch):
    opened = ready(lane)
    before = checkpoint()
    original_prefix = host._entries[lane.doc].prepared

    def fail_start(_callback):
        raise RuntimeError("Injected Apply thread start failure")

    monkeypatch.setattr(computation, "start_thread", fail_start)
    with pytest.raises((RuntimeError, HTTPException)):
        host.apply(update(opened), family=FAMILY)
    assert host._entries[lane.doc].prepared is original_prefix
    assert status(opened)["status"] == "ready"
    assert lane.queued == []
    unchanged(before)


def test_background_starter_preserves_named_document_context(document, monkeypatch):
    scheduled, observed = [], []

    class Thread:
        def __init__(self, *, target, args, name, daemon):
            assert daemon is False
            self.target, self.args = target, args

        def start(self):
            scheduled.append(lambda: self.target(*self.args))

    monkeypatch.setattr(computation, "Thread", Thread)
    computation.start_thread(lambda: observed.append(doc_context.get_current_doc()))
    token = doc_context.set_current_doc("another-request")
    try:
        scheduled.pop()()
        assert observed == [document]
        assert doc_context.get_current_doc() == "another-request"
    finally:
        doc_context.reset_current_doc(token)


def test_begin_apply_refuses_older_request_even_when_entry_has_newer_sequence(lane):
    from backend.core.part_verification_capture import capture
    from backend.core.part_history_proof import digest

    opened = ready(lane)
    request = host._parse(host.Change, update(opened, sequence=1))
    host.evaluate({**update(opened, sequence=2), "include_geometry": False}, family=FAMILY)
    entry = host._entries[lane.doc]
    captured = capture(state.get_or_404(), preserve_entry_types=True)
    before = checkpoint()
    assert host._work_slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as caught:
            computation.begin_apply(host, entry, captured, request, {}, None,
                                    digest(request.model_dump(mode="json")))
        assert caught.value.status_code == 409
        assert lane.queued == []
    finally:
        # On the red implementation an invalid worker is queued; still honor
        # its admission ownership while cleaning up the failed regression.
        if lane.queued:
            host.cancel(cancellation(opened), family=FAMILY)
            lane.run()
        else:
            host._work_slot.release()
    unchanged(before)


def test_busy_claim_retains_completed_numerical_result_until_work_is_released(lane):
    opened = ready(lane)
    entry = host._entries[lane.doc]
    payload, operation, sequence = entry.payload, entry.computation, entry.sequence
    assert operation.finished is not None
    # Completion is visible just before the supervisor's finally releases the
    # work slot. A client can already have received the ready polling response.
    assert host._work_slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as caught:
            host.evaluate(update(opened, sequence=1), family=FAMILY)
        assert caught.value.status_code == 429
        assert entry.payload is payload and entry.computation is operation
        assert entry.sequence == sequence
        assert status(opened)["result"]["request_sequence"] == sequence
    finally:
        host._work_slot.release()


def test_receipt_timer_start_failure_cannot_demote_successful_publication(lane, monkeypatch):
    opened = ready(lane)
    before = checkpoint()
    original_timer = host.Timer

    class FailingReceiptTimer(original_timer):
        def start(self):
            if host._entries[lane.doc].phase == "applied":
                raise RuntimeError("Injected receipt timer start failure after publication")
            super().start()

    monkeypatch.setattr(host, "Timer", FailingReceiptTimer)
    host.apply(update(opened), family=FAMILY)
    lane.run()
    assert state.get_design_with_revision()[1] == before["revision"] + 1
    assert state.undo_depth() == len(before["history"]) + 1
    receipt = status(opened)
    assert receipt["status"] == "applied" and receipt["request_sequence"] == 1
    assert "failure" not in receipt
    assert host.cancel(cancellation(opened), family=FAMILY)["status"] == "applied"
    with pytest.raises(HTTPException):
        host.apply(update(opened, sequence=2), family=FAMILY)
    assert [call["action"] for call in lane.calls] == ["prepare", "apply"]


def test_prepare_ready_timer_failure_drops_prefix_and_result_before_terminal_failure(lane, monkeypatch):
    before = checkpoint()
    original_timer = host.Timer
    failed = []

    class FailingReadyTimer(original_timer):
        def start(self):
            if host._entries[lane.doc].phase == "ready" and not failed:
                failed.append(True)
                raise RuntimeError("Injected first ready timer start failure")
            super().start()

    monkeypatch.setattr(host, "Timer", FailingReadyTimer)
    ack = host.prepare(opening(), family=FAMILY)
    lane.run()
    assert failed == [True]
    result = status(ack)
    assert result["status"] == "failed"
    assert result["failure"] == {"status": 500, "detail": {"code": "preview_computation_error"}}
    assert "result" not in result
    assert host._entries[lane.doc].prepared is None
    assert host._entries[lane.doc].payload is None
    assert result["remaining_seconds"] == 60
    unchanged(before)
