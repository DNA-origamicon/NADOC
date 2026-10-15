"""Only the operation admitted by the host can authorize candidate publication."""

from copy import deepcopy
from time import monotonic
from uuid import uuid4
from weakref import ref

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_history_verification import _slot
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def document():
    doc = f"__evaluation_admission__{uuid4()}"
    token = set_current_doc(doc)
    source = create_empty_part("Admitted operation", "HONEYCOMB")
    state.load_design(source)
    before = set(jobs._jobs)
    try:
        yield doc, source, state.revision()
    finally:
        with jobs._lock:
            for identity in set(jobs._jobs) - before:
                jobs._jobs.pop(identity)
        state.drop_doc(doc)
        reset_current_doc(token)


def request(operation, design, revision):
    if operation == "repair":
        return {"operation": operation, "repair": {"repair_version": 1,
            "expected_design_id": design.id, "expected_revision": revision,
            "actions": [{"action": "set_input", "feature_id": "row", "parameter_path": ["diameter_nm"],
                         "expected_old": 10., "value": 11.}]}}
    if operation == "selection":
        return {"operation": operation, "selection": {"selection_version": 1,
            "expected_design_id": design.id, "expected_revision": revision,
            "feature_id": "row", "parameter_path": ["nanoparticle_id"], "expected_old": "gold"}}
    if operation == "append":
        return {"operation": operation, "kind": "duplex-relax", "params": {}}
    if operation == "edit":
        return {"operation": operation, "index": 0, "params": {}}
    if operation == "delete":
        return {"operation": operation, "index": 0}
    return {"operation": operation}


def install_worker(monkeypatch, result, *, mutate_operation=False):
    calls = []

    class Worker:
        def __init__(self, source, operation):
            self.operation = operation

        def start(self):
            calls.append("start")

        def wait(self, _timeout):
            return True

        def is_alive(self):
            return False

        def result(self):
            calls.append("result")
            if mutate_operation:
                self.operation["request"]["operation"] = "edit"
            return deepcopy(result)

        def close(self):
            calls.append("close")

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    return calls


@pytest.mark.parametrize("operation,code", [("verify", "invalid_verification_result"),
                                             ("selection", "invalid_selection_result")])
@pytest.mark.parametrize("result", [{"status": "ready", "issues": [], "candidate": {}},
                                   {"status": "ready", "issues": []},
                                   {"status": "verified", "issues": [], "candidate": {}}])
def test_nonpublishing_worker_results_are_discarded_before_retention(document, monkeypatch, operation, code, result):
    _doc, design, revision = document
    install_worker(monkeypatch, {**result, "admitted_operation": "edit"})
    identity = jobs.start(request(operation, design, revision))["job_id"]
    polled = jobs.inspect(identity)["result"]
    assert polled["status"] == "unverified" and polled["issues"] == [{"code": code}]
    with jobs._lock:
        assert jobs._jobs[identity].admitted_operation == operation
        assert "candidate" not in jobs._jobs[identity].result
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409 and "nonpublishing" in error.value.detail
    assert state.get_design_with_revision() == (design, revision)
    assert state.undo_depth() == state.redo_depth() == 0


def test_valid_verification_assessment_is_preserved_but_cannot_commit(document, monkeypatch):
    _doc, design, revision = document
    install_worker(monkeypatch, {"status": "verified", "issues": [], "checked_commands": 0})
    identity = jobs.start({"operation": "verify"})["job_id"]
    assert jobs.inspect(identity)["result"]["status"] == "verified"
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state.get_design_with_revision() == (design, revision)


def test_worker_operation_or_result_labels_cannot_upgrade_admitted_verification(document, monkeypatch):
    _doc, design, _revision = document
    calls = install_worker(monkeypatch, {"status": "ready", "issues": [],
        "candidate": design.model_dump(mode="json"), "admitted_operation": "edit"}, mutate_operation=True)
    identity = jobs.start({"operation": "verify"})["job_id"]
    assert jobs._jobs[identity].admitted_operation == "verify"
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert calls == ["start", "result", "close"]


@pytest.mark.parametrize("operation", ["verify", "selection", None, "unknown", "future-operation"])
def test_commit_rechecks_host_admission_even_when_retained_result_is_replaced(document, monkeypatch, operation):
    doc, design, revision = document
    identity = str(uuid4())
    job = jobs.EvaluationJob(doc, ref(design), revision, created=monotonic(),
        admitted_operation=operation, session_identity=state._sessions[doc].identity,
        status="complete", result={"status": "ready", "issues": [],
            "admitted_operation": "edit", "candidate": design.model_dump(mode="json")})
    with jobs._lock:
        jobs._jobs[identity] = job
    monkeypatch.setattr(Design, "model_validate", lambda *_a, **_k: pytest.fail("Rejected operation decoded a candidate"))
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409
    assert state.get_design_with_revision() == (design, revision)
    assert state.undo_depth() == state.redo_depth() == 0
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.mark.parametrize("admission", [None, "unknown", "future-operation"])
def test_missing_or_unknown_admission_discards_worker_result_in_supervisor(document, monkeypatch, admission):
    doc, design, revision = document
    job = jobs.EvaluationJob(doc, ref(design), revision, admitted_operation=admission,
        session_identity=state._sessions[doc].identity)
    monkeypatch.setattr(jobs, "supervise", lambda *_a, **_k: {"status": "ready", "issues": [],
        "admitted_operation": "edit", "candidate": design.model_dump(mode="json")})
    jobs._run(job, design, {"request": {"operation": "edit"}})
    assert job.result["status"] == "unverified"
    assert job.result["issues"] == [{"code": "invalid_operation_admission"}]
    assert "candidate" not in job.result


@pytest.mark.parametrize("operation", ["append", "edit", "delete", "repair"])
def test_each_current_admitted_mutation_retains_one_exact_commit_without_solver_repeat(document, monkeypatch, operation):
    _doc, design, revision = document
    calls = install_worker(monkeypatch, {"status": "ready", "issues": [],
        "candidate": design.model_dump(mode="json")})
    identity = jobs.start(request(operation, design, revision))["job_id"]
    assert jobs._jobs[identity].admitted_operation == operation
    assert jobs.inspect(identity)["result"]["status"] == "ready"
    assert jobs.commit(identity)["revision"] == revision + 1
    assert jobs.commit(identity)["revision"] == revision + 1
    assert state.undo_depth() == 1 and state.redo_depth() == 0
    assert calls == ["start", "result", "close"]


@pytest.mark.parametrize("key", ["admitted_operation", "selection_only", "publication_permit"])
def test_public_envelope_cannot_claim_host_admission(key):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "verify", key: "edit"})


def test_late_admission_change_is_rechecked_before_atomic_publication(document, monkeypatch):
    _doc, design, revision = document
    install_worker(monkeypatch, {"status": "ready", "issues": [], "candidate": design.model_dump(mode="json")})
    identity = jobs.start(request("edit", design, revision))["job_id"]
    validate = Design.model_validate

    def decode(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        jobs._jobs[identity].admitted_operation = "verify"
        return candidate

    monkeypatch.setattr(Design, "model_validate", decode)
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state.get_design_with_revision() == (design, revision)
    assert state.undo_depth() == state.redo_depth() == 0
