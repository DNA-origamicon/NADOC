"""Host session identity closes same-object/same-revision drop/reopen races."""

from copy import deepcopy
from threading import Event
from time import monotonic
from uuid import uuid4
from weakref import ref

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import part_evaluation_capture, part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_history_verification import _slot
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def document():
    doc = f"__evaluation_session__{uuid4()}"
    token = set_current_doc(doc)
    design = create_empty_part("Session identity", "HONEYCOMB")
    state.load_design(design)
    previous = set(jobs._jobs)
    try:
        yield doc, design, state.revision(), state._sessions[doc].identity
    finally:
        with jobs._lock:
            for identity in set(jobs._jobs) - previous:
                jobs._jobs.pop(identity)
        state.drop_doc(doc)
        reset_current_doc(token)


def replace_session(doc, design, revision):
    state.drop_doc(doc)
    state.restore_doc_design(doc, design)
    # Production restore starts at revision 1; tests intentionally use a new
    # session whose public source/revision exactly match the captured values.
    assert state.get_design_with_revision() == (design, revision)


def install_worker(monkeypatch, *, wait_event=None):
    calls, started, closed = [], Event(), Event()

    class Worker:
        def __init__(self, source, operation):
            calls.append("construct")
            self.source = source

        def start(self):
            calls.append("start")
            started.set()

        def wait(self, timeout):
            return True if wait_event is None else wait_event.wait(timeout)

        def is_alive(self):
            return not closed.is_set()

        def result(self):
            calls.append("result")
            return {"status": "ready", "issues": [], "candidate": self.source.model_dump(mode="json")}

        def close(self):
            calls.append("close")
            closed.set()

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    if wait_event is None:
        monkeypatch.setattr(jobs, "_submit", jobs._run)
    return calls, started, closed


def start():
    return jobs.start({"operation": "edit", "index": 0, "params": {}})["job_id"]


def test_session_identity_is_host_only_and_not_undo_or_file_content(document):
    doc, design, _revision, identity = document
    assert identity not in design.model_dump_json()
    state.set_design(design.model_copy(deep=True))
    state.undo()
    state.redo()
    assert state._sessions[doc].identity == identity
    assert identity not in state.get_or_404().to_json()
    state.drop_doc(doc)
    state.restore_doc_design(doc, design)
    assert state._sessions[doc].identity != identity


def test_capture_default_shape_stays_compatible_and_opt_in_token_is_same_lock(document, monkeypatch):
    doc, design, revision, identity = document
    capture = part_evaluation_capture.capture_for_evaluation

    def observed(*args, **kwargs):
        assert state._lock.locked()
        assert state._sessions[doc].identity == identity
        return capture(*args, **kwargs)

    monkeypatch.setattr(part_evaluation_capture, "capture_for_evaluation", observed)
    ordinary = state.capture_design_for_evaluation({"operation": "verify"})
    bound = state.capture_design_for_evaluation({"operation": "verify"}, include_session_identity=True,
        expected_source=design, expected_session_identity=identity)
    assert len(ordinary) == 3 and len(bound) == 4
    assert bound[0] is design and bound[1] is not design and bound[2:] == (revision, identity)


@pytest.mark.parametrize("mismatch", ["source", "session"])
def test_private_expected_context_rejects_before_capture_and_releases_admission(document, monkeypatch, mismatch):
    _doc, design, revision, identity = document
    monkeypatch.setattr(part_evaluation_capture, "capture_for_evaluation",
        lambda *_a, **_k: pytest.fail("Misbound source was copied"))
    guards = {"expected_source": design, "expected_session_identity": identity}
    guards["expected_source" if mismatch == "source" else "expected_session_identity"] = (
        design.model_copy(deep=True) if mismatch == "source" else str(uuid4()))
    with pytest.raises(HTTPException) as error:
        jobs.start({"operation": "verify"}, **guards)
    assert error.value.status_code == 409 and error.value.detail["code"] == "source_changed"
    assert state.get_design_with_revision() == (design, revision)
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_closed_before_trusted_capture_stays_absent(document, monkeypatch):
    doc, design, _revision, identity = document
    state.drop_doc(doc)
    monkeypatch.setattr(part_evaluation_capture, "capture_for_evaluation",
        lambda *_a, **_k: pytest.fail("Closed document was copied"))
    with pytest.raises(HTTPException) as error:
        jobs.start({"operation": "verify"}, expected_source=design, expected_session_identity=identity)
    assert error.value.status_code == 409 and error.value.detail["code"] == "source_changed"
    assert doc not in state.revision_map()
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_replacement_between_capture_and_admission_keeps_original_session_binding(document, monkeypatch):
    doc, design, revision, identity = document
    capture = state.capture_design_for_evaluation

    def capture_then_replace(*args, **kwargs):
        result = capture(*args, **kwargs)
        replace_session(doc, design, revision)
        return result

    calls, _started, _closed = install_worker(monkeypatch)
    monkeypatch.setattr(state, "capture_design_for_evaluation", capture_then_replace)
    job_id = start()
    assert jobs._jobs[job_id].session_identity == identity
    assert calls == []
    result = jobs.inspect(job_id)
    assert result["stale"] and result["result"]["issues"][0]["code"] == "source_changed"
    with pytest.raises(HTTPException):
        jobs.commit(job_id)
    assert state.get_design_with_revision() == (design, revision)


def test_matching_private_context_starts_a_bound_job_without_exporting_token(document, monkeypatch):
    _doc, design, _revision, identity = document
    install_worker(monkeypatch)
    result = jobs.start({"operation": "edit", "index": 0, "params": {}},
        expected_source=design, expected_session_identity=identity)
    assert jobs._jobs[result["job_id"]].session_identity == identity
    assert identity not in str(result)
    assert jobs.inspect(result["job_id"])["result"]["status"] == "ready"


def test_ready_job_cannot_commit_to_recreated_session_with_identical_source_and_revision(document, monkeypatch):
    doc, design, revision, identity = document
    install_worker(monkeypatch)
    job_id = start()
    assert jobs.inspect(job_id)["result"]["status"] == "ready"
    replace_session(doc, design, revision)
    assert state.verification_source_matches(doc, design, revision)  # Existing compatibility semantics.
    assert not state.verification_source_matches(doc, design, revision, expected_session_identity=identity)
    assert jobs.inspect(job_id)["stale"]
    monkeypatch.setattr(Design, "model_validate", lambda *_a, **_k: pytest.fail("Stale session decoded candidate"))
    with pytest.raises(HTTPException) as error:
        jobs.commit(job_id)
    assert error.value.status_code == 409
    assert state.get_design_with_revision() == (design, revision) and state.undo_depth() == 0


def test_running_worker_is_reaped_when_same_source_revision_reappears_in_new_session(document, monkeypatch):
    doc, design, revision, _identity = document
    release, done = Event(), Event()
    _calls, started, closed = install_worker(monkeypatch, wait_event=release)
    run = jobs._run

    def observed(*args):
        try:
            run(*args)
        finally:
            done.set()

    monkeypatch.setattr(jobs, "_run", observed)
    job_id = start()
    try:
        assert started.wait(5)
        replace_session(doc, design, revision)
        assert done.wait(5) and closed.is_set()
        result = jobs.inspect(job_id)
        assert result["stale"] and result["result"]["issues"][0]["code"] == "source_changed"
        assert _slot.acquire(blocking=False)
        _slot.release()
        with pytest.raises(HTTPException):
            jobs.commit(job_id)
    finally:
        release.set()
        assert done.wait(5)


def test_final_publication_guard_rejects_aba_during_candidate_decode(document, monkeypatch):
    doc, design, revision, _identity = document
    install_worker(monkeypatch)
    job_id = start()
    validate = Design.model_validate

    def decode_then_replace(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        replace_session(doc, design, revision)
        return candidate

    monkeypatch.setattr(Design, "model_validate", decode_then_replace)
    with pytest.raises(HTTPException) as error:
        jobs.commit(job_id)
    assert error.value.status_code == 409
    assert state.get_design_with_revision() == (design, revision) and state.undo_depth() == 0
    assert jobs._jobs[job_id].committed_revision is None


def test_closed_during_candidate_decode_stays_absent_after_rejected_commit(document, monkeypatch):
    doc, _design, _revision, _identity = document
    install_worker(monkeypatch)
    job_id = start()
    validate = Design.model_validate

    def decode_then_close(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        state.drop_doc(doc)
        return candidate

    monkeypatch.setattr(Design, "model_validate", decode_then_close)
    with pytest.raises(HTTPException) as error:
        jobs.commit(job_id)
    assert error.value.status_code == 409 and error.value.detail["code"] == "source_changed"
    assert doc not in state.revision_map() and jobs._jobs[job_id].committed_revision is None
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.mark.parametrize("context", [None, "", False])
def test_missing_or_invalid_host_context_cannot_publish_even_ready_worker_json(document, monkeypatch, context):
    doc, design, revision, _identity = document
    job_id = str(uuid4())
    jobs._jobs[job_id] = jobs.EvaluationJob(doc, ref(design), revision, created=monotonic(),
        admitted_operation="edit", session_identity=context, status="complete",
        result={"status": "ready", "issues": [], "session_identity": "worker-claim",
                "candidate": design.model_dump(mode="json")})
    monkeypatch.setattr(Design, "model_validate", lambda *_a, **_k: pytest.fail("Missing context decoded candidate"))
    with pytest.raises(HTTPException) as error:
        jobs.commit(job_id)
    assert error.value.status_code == 409 and error.value.detail["code"] == "invalid_evaluation_context"
    assert state.get_design_with_revision() == (design, revision) and state.undo_depth() == 0


def test_supervisor_does_not_retain_candidate_without_host_session_context(document, monkeypatch):
    doc, design, revision, _identity = document
    job = jobs.EvaluationJob(doc, ref(design), revision, admitted_operation="edit")
    monkeypatch.setattr(jobs, "supervise", lambda *_a, **_k: {"status": "ready", "issues": [],
        "candidate": design.model_dump(mode="json"), "session_identity": "worker-claim"})
    jobs._run(job, design, {})
    assert job.result["status"] == "unverified" and "candidate" not in job.result
    assert job.result["issues"] == [{"code": "invalid_evaluation_context"}]


@pytest.mark.parametrize("key", ["session_identity", "expected_session_identity", "expected_source"])
def test_public_request_cannot_supply_internal_session_or_source_authority(key):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "verify", key: "caller-claim"})


def test_context_never_crosses_worker_transport_or_job_polling(document, monkeypatch):
    _doc, _design, _revision, identity = document
    install_worker(monkeypatch)
    received = []
    run = jobs._run

    def submit(job, captured, operation):
        received.append(deepcopy(operation))
        run(job, captured, operation)

    monkeypatch.setattr(jobs, "_submit", submit)
    job_id = start()
    assert identity not in str(received) and identity not in str(jobs.inspect(job_id))
    assert jobs._jobs[job_id].session_identity == identity


def test_old_committed_handle_is_not_reused_by_a_recreated_session(document, monkeypatch):
    doc, design, revision, _identity = document
    install_worker(monkeypatch)
    job_id = start()
    first = jobs.commit(job_id)
    assert jobs.commit(job_id) == {"job_id": job_id, "status": "committed", "revision": first["revision"]}
    replace_session(doc, design, revision)
    assert jobs.inspect(job_id)["stale"]
    with pytest.raises(HTTPException) as error:
        jobs.commit(job_id)
    assert error.value.status_code == 409
    assert state.get_design_with_revision() == (design, revision) and state.undo_depth() == 0


def test_nonblocking_session_check_does_not_wait_for_busy_state_lock(document):
    doc, design, revision, identity = document
    with state._lock:
        assert state.evaluation_session_matches(doc, identity, blocking=False) is None
        assert state.verification_source_matches(doc, design, revision, blocking=False,
            expected_session_identity=identity) is None
