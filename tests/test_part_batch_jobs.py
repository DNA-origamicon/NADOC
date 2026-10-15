"""Registered batches reuse admission, bounded jobs and one atomic publication."""

from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import part_batch_evaluation, part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import evaluate
from backend.api.part_history_verification import _slot
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import CaptureLimit, capture
from tests.test_part_registered_batch import GOLD, command, gold, helix, request as batch_request, source


@pytest.fixture
def document(monkeypatch):
    doc = f"__registered_batch_jobs__{uuid4()}"
    token = set_current_doc(doc)
    state.load_design(source())
    state.get_or_404().annotations_enabled = False
    state.set_design(state.get_or_404().model_copy(deep=True))
    state.undo()
    previous = set(jobs._jobs)
    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", True)
    try:
        yield
    finally:
        with jobs._lock:
            for identity in set(jobs._jobs) - previous:
                jobs._jobs.pop(identity)
        state.drop_doc(doc)
        reset_current_doc(token)


def body(*commands):
    return {"operation": "batch", "batch": batch_request(*(commands or [gold()]),
        expected_design_id=state.get_or_404().id, expected_revision=state.revision())}


@pytest.fixture
def controlled(document, monkeypatch, request):
    entered, released, completed, closed = Event(), Event(), Event(), Event()
    real_run, received, calls = jobs._run, [], []

    class Worker:
        def __init__(self, design, operation):
            self.design, self.operation = design, operation
            received.append(operation)

        def start(self):
            entered.set()

        def wait(self, timeout):
            return released.wait(timeout)

        def is_alive(self):
            return not closed.is_set()

        def result(self):
            calls.append("evaluate")
            return evaluate(self.design, self.operation)

        def close(self):
            closed.set()

    def run(*args):
        try:
            real_run(*args)
        finally:
            completed.set()

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_run", run)
    original, revision = state.get_design_with_revision()
    depth, redo = state.undo_depth(), state.redo_depth()
    commands = [gold(), command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 12.})]
    if getattr(request, "param", None) == "failure":
        commands = [gold(), command("nanoparticle-delete", {"nanoparticle_id": "missing"}), helix()]
    identity = jobs.start(body(*commands))["job_id"]
    assert entered.wait(5)
    try:
        yield SimpleNamespace(id=identity, release=released, done=completed, closed=closed,
            received=received, calls=calls, original=original, before=original.model_dump_json(),
            revision=revision, depth=depth, redo=redo)
    finally:
        released.set()
        assert completed.wait(5)


def finish(job):
    job.release.set()
    assert job.done.wait(5)
    return jobs.inspect(job.id)


def unchanged(job):
    assert state.get_or_404() is job.original
    assert state.get_or_404().model_dump_json() == job.before
    assert (state.revision(), state.undo_depth(), state.redo_depth()) == (job.revision, job.depth, job.redo)


def test_batch_candidate_is_private_until_one_exact_commit_and_undo_redo(controlled):
    job = controlled
    result = finish(job)["result"]
    assert result["status"] == "ready", result
    assert "candidate" not in result
    assert result["source_assessment"]["status"] == "verified"
    assert result["batch"]["candidate_replay_verified"] is False
    assert result["batch"]["authoring_changes"]["changed_fields"] == ["nanoparticles"]
    assert job.received[0]["header"]["source_revision"] == job.revision
    assert job.received[0]["header"]["source_design_id"] == job.original.id
    assert jobs._jobs[job.id].admitted_operation == "batch"
    unchanged(job)
    committed = jobs.commit(job.id)
    candidate = state.get_or_404()
    assert committed["revision"] == job.revision + 1
    assert candidate.nanoparticles[0].diameter_nm == 12.
    assert candidate.annotations_enabled is False
    assert len(candidate.feature_log) == 2
    assert (state.undo_depth(), state.redo_depth()) == (job.depth + 1, 0)
    assert jobs.commit(job.id)["revision"] == committed["revision"]
    assert job.calls == ["evaluate"]
    reloaded = Design.from_json(candidate.to_json())
    assert assess_part_history(reloaded, execute=execute, dependencies=dependencies)["status"] == "verified"
    state.undo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == job.original.model_dump(include=AUTHORING_FIELDS)
    assert state.get_or_404().feature_log == []
    state.redo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == candidate.model_dump(include=AUTHORING_FIELDS)


@pytest.mark.parametrize("controlled", ["failure"], indirect=True)
def test_later_command_failure_keeps_source_and_both_undo_stacks(controlled):
    result = finish(controlled)["result"]
    assert result["status"] == "failed", result
    assert result["issues"][0]["command_index"] == 1
    assert result["issues"][0]["code"] == "missing_reference"
    assert len(result["batch"]["completed"]) == len(result["batch"]["not_evaluated"]) == 1
    assert "candidate" not in jobs._jobs[controlled.id].result
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 409
    unchanged(controlled)


@pytest.mark.parametrize("when", ["running", "ready"])
def test_cancelled_batch_never_publishes_and_reaps_before_admission_release(controlled, when):
    if when == "ready":
        finish(controlled)
    jobs.inspect(controlled.id, cancel=True)
    assert controlled.done.wait(5) and controlled.closed.is_set()
    assert jobs.inspect(controlled.id)["result"]["status"] == "unverified"
    with pytest.raises(HTTPException):
        jobs.commit(controlled.id)
    unchanged(controlled)
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.mark.parametrize("change", ["edit", "reload", "close"])
def test_source_identity_or_revision_change_invalidates_batch(controlled, change):
    finish(controlled)
    if change == "edit":
        state.set_design(state.get_or_404().model_copy(deep=True))
    elif change == "reload":
        state.load_design(Design.from_json(state.get_or_404().to_json()))
    else:
        state.close_session()
    current, revision = state.get_design_with_revision()
    depth, redo = state.undo_depth(), state.redo_depth()
    assert jobs.inspect(controlled.id)["stale"]
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 409
    assert state.get_design_with_revision() == (current, revision)
    assert (state.undo_depth(), state.redo_depth()) == (depth, redo)


def test_batch_retention_is_document_scoped_and_expires(controlled, monkeypatch):
    finish(controlled)
    token = set_current_doc("other-batch-document")
    try:
        with pytest.raises(HTTPException) as error:
            jobs.commit(controlled.id)
        assert error.value.status_code == 404
    finally:
        reset_current_doc(token)
    monkeypatch.setattr(jobs, "monotonic", lambda: 1e30)
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 410
    unchanged(controlled)


@pytest.mark.parametrize("change", ["design", "revision"])
def test_nested_guards_fail_before_copy_or_submit(document, monkeypatch, change):
    request = body()
    key = "expected_design_id" if change == "design" else "expected_revision"
    request["batch"][key] = "other" if change == "design" else state.revision() - 1
    from backend.core import part_verification_capture
    monkeypatch.setattr(part_verification_capture, "capture", lambda *_a, **_k: pytest.fail("Stale batch copied"))
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Stale batch submitted"))
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 409 and error.value.detail["code"] == "batch_conflict"
    assert state.get_design_with_revision() == (before, revision)
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_unqualified_gate_fails_before_capture_and_cannot_be_enabled_by_request(document, monkeypatch):
    from backend.core import part_verification_capture
    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", False)
    monkeypatch.setattr(part_verification_capture, "capture", lambda *_a, **_k: pytest.fail("Disabled batch copied"))
    with pytest.raises(HTTPException) as error:
        jobs.start(body())
    assert error.value.status_code == 422 and error.value.detail["code"] == "registered_batch_unavailable"
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_busy_admission_precedes_batch_capture(controlled, monkeypatch):
    monkeypatch.setattr(state, "capture_design_for_evaluation", lambda *_a: pytest.fail("Busy batch copied"))
    with pytest.raises(HTTPException) as error:
        jobs.start(body())
    assert error.value.status_code == 429
    unchanged(controlled)


def test_missing_document_is_not_created_for_batch(document):
    request = body()
    state.close_session()
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 404
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_batch_uses_ordinary_capture_profile_without_coating_classification(document, monkeypatch):
    from backend.api import part_evaluation_capture
    from backend.core import part_verification_capture
    from backend.api.part_evaluation import EvaluationRequest
    calls = []

    def ordinary(design, **kwargs):
        calls.append((design, kwargs))
        return capture(design, **kwargs)

    monkeypatch.setattr(part_evaluation_capture, "_coating_intent", lambda *_a: pytest.fail("Batch inspected coating history"))
    monkeypatch.setattr(part_verification_capture, "capture", ordinary)
    source_design, captured, revision = state.capture_design_for_evaluation(EvaluationRequest.model_validate(body()))
    assert calls == [(source_design, {"preserve_entry_types": True})]
    assert captured is not source_design and captured.id == source_design.id and revision == state.revision()


def test_batch_capture_limit_is_413_without_worker_or_retry(document, monkeypatch):
    from backend.core import part_verification_capture
    calls = []

    def exhausted(*_a, **_k):
        calls.append("capture")
        raise CaptureLimit("Capture work budget exceeded")

    monkeypatch.setattr(part_verification_capture, "capture", exhausted)
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Oversized batch submitted"))
    with pytest.raises(HTTPException) as error:
        jobs.start(body())
    assert error.value.status_code == 413 and calls == ["capture"]
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_existing_http_schema_rejects_hidden_payloads_and_keeps_candidate_out_of_polling(controlled):
    from backend.api.routes_feature_log import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        properties = schema["components"]["schemas"]["EvaluationRequest"]["properties"]
        assert "batch" in properties["operation"]["enum"] and "batch" in properties
        invalid = body()
        invalid["batch"]["commands"][0]["params"]["design_snapshot_gz_b64"] = "private"
        assert client.post("/api/design/features/evaluation/jobs", json=invalid).status_code == 422
        finish(controlled)
        path = f"/api/design/features/evaluation/jobs/{controlled.id}"
        result = client.get(path).json()["result"]
        assert "candidate" not in result and "geometry" not in result
        assert result["batch"]["authoring_changes"]["visual_comparison"] is False
        assert client.post(f"{path}/commit").json()["status"] == "committed"


def test_spawned_batch_job_commits_once_then_reloads_and_cold_replays(document, monkeypatch):
    completed, real_run = Event(), jobs._run

    def run(*args):
        try:
            real_run(*args)
        finally:
            completed.set()

    monkeypatch.setattr(jobs, "_run", run)
    original, revision = state.get_design_with_revision()
    before, depth = original.model_dump_json(), state.undo_depth()
    identity = jobs.start(body(gold(), command("nanoparticle-patch", {
        "nanoparticle_id": GOLD, "diameter_nm": 13.})))["job_id"]
    try:
        assert completed.wait(5)
        result = jobs.inspect(identity)
        assert result["result"]["status"] == "ready", result
        assert state.get_or_404() is original and original.model_dump_json() == before
        assert jobs.commit(identity)["revision"] == revision + 1
        assert jobs.commit(identity)["revision"] == revision + 1
        assert state.undo_depth() == depth + 1
        reloaded = Design.from_json(state.get_or_404().to_json())
        for entry in reloaded.feature_log:
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poison"
        verifier = VerificationWorker(capture(reloaded))
        try:
            verifier.start()
            assert verifier.wait(5)
            proof = verifier.result()
            assert proof["status"] == "verified" and proof["checked_commands"] == 2, proof
        finally:
            verifier.close()
    finally:
        if not completed.is_set():
            jobs.inspect(identity, cancel=True)
            assert completed.wait(5)
