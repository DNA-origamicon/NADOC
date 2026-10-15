"""Selection shares bounded jobs but can never publish or offer stale choices."""

from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import evaluate
from backend.api.part_history_verification import _slot
from tests.test_part_recipe_repair import gold_params, row, source
from tests.test_part_repair_selection import request as selection_request


@pytest.fixture
def document():
    token = set_current_doc("part-selection-job")
    state.load_design(source())
    state.get_or_404().annotations_enabled = False
    state.set_design(state.get_or_404().model_copy(deep=True))
    state.undo()
    try:
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def body():
    return {"operation": "selection", "selection": selection_request(
        expected_design_id=state.get_or_404().id, expected_revision=state.revision())}


@pytest.fixture
def controlled(document, monkeypatch, request):
    entered, released, completed, closed = Event(), Event(), Event(), Event()
    real_run = jobs._run
    received = []
    mode = getattr(request, "param", None)
    if mode == "failure":
        state.get_or_404().feature_log.insert(1, row("broken-prefix", "nanoparticle-delete", gold_params("gone")))

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
            if mode == "invalid-worker-result":
                return {"status": "ready", "issues": [], "candidate": {}}
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
    identity = jobs.start(body())["job_id"]
    assert entered.wait(5)
    try:
        yield SimpleNamespace(id=identity, release=released, done=completed, closed=closed, received=received,
            original=original, before=original.model_dump_json(), revision=revision, depth=depth, redo=redo)
    finally:
        released.set()
        assert completed.wait(5)
        with jobs._lock:
            jobs._jobs.pop(identity, None)


def finish(job):
    job.release.set()
    assert job.done.wait(5)
    return jobs.inspect(job.id)


def unchanged(job):
    assert state.get_or_404().model_dump_json() == job.before
    assert (state.revision(), state.undo_depth(), state.redo_depth()) == (job.revision, job.depth, job.redo)


def test_selection_poll_returns_descriptors_and_never_has_a_commit_phase(controlled):
    job = controlled
    result = finish(job)
    assert result["result"]["status"] == "preview", result
    assert result["result"]["selection"]["candidates"][0]["identity"] == "gold"
    assert "candidate" not in result["result"]
    assert job.received[0]["header"]["source_revision"] == job.revision
    assert job.received[0]["header"]["source_design_id"] == job.original.id
    with jobs._lock:
        assert jobs._jobs[job.id].selection_only and "candidate" not in jobs._jobs[job.id].result
    with pytest.raises(HTTPException) as error:
        jobs.commit(job.id)
    assert error.value.status_code == 409
    unchanged(job)


@pytest.mark.parametrize("controlled", ["invalid-worker-result"], indirect=True)
def test_host_discards_candidate_from_an_invalid_selection_worker_result(controlled):
    result = finish(controlled)["result"]
    assert result["status"] == "unverified" and result["issues"] == [{"code": "invalid_selection_result"}]
    with jobs._lock:
        assert "candidate" not in jobs._jobs[controlled.id].result
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 409
    unchanged(controlled)


def test_commit_checks_host_operation_even_if_result_is_later_corrupted(controlled):
    finish(controlled)
    with jobs._lock:
        jobs._jobs[controlled.id].result = {"status": "ready", "issues": [], "candidate": {}}
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 409 and "nonpublishing" in error.value.detail
    unchanged(controlled)


@pytest.mark.parametrize("controlled", ["failure"], indirect=True)
def test_failed_prefix_poll_keeps_diagnostics_and_both_undo_stacks(controlled):
    result = finish(controlled)["result"]
    assert result["status"] == "failed" and result["issues"][0]["feature_id"] == "broken-prefix"
    assert result["selection"]["completed_prefix"] == ["create"]
    assert result["selection"]["not_evaluated"] == ["patch", "later"]
    assert result["selection"]["candidates"] == []
    unchanged(controlled)


@pytest.mark.parametrize("when", ["running", "complete"])
def test_cancelled_selection_reaps_and_hides_any_completed_choices(controlled, when):
    if when == "complete":
        finish(controlled)
    jobs.inspect(controlled.id, cancel=True)
    assert controlled.done.wait(5) and controlled.closed.is_set()
    result = jobs.inspect(controlled.id)["result"]
    assert result["status"] == "unverified"
    assert not result.get("selection", {}).get("candidates")
    if when == "complete":
        assert result["selection"]["candidates_invalidated"]
    unchanged(controlled)
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.mark.parametrize("change", ["edit", "reload", "close"])
def test_edit_reload_or_close_invalidates_completed_choice_list(controlled, change):
    finish(controlled)
    if change == "edit":
        state.set_design(state.get_or_404().model_copy(deep=True))
    elif change == "reload":
        state.load_design(state.get_or_404().model_copy(deep=True))
    else:
        state.close_session()
    current, revision = state.get_design_with_revision()
    depth, redo = state.undo_depth(), state.redo_depth()
    polled = jobs.inspect(controlled.id)
    assert polled["stale"] and polled["result"]["status"] == "unverified"
    assert polled["result"]["selection"]["candidates"] == []
    assert polled["result"]["selection"]["candidates_invalidated"]
    assert "eligible_count" not in polled["result"]["selection"]
    with pytest.raises(HTTPException):
        jobs.commit(controlled.id)
    assert state.get_design_with_revision() == (current, revision)
    assert (state.undo_depth(), state.redo_depth()) == (depth, redo)


def test_busy_source_hides_choices_without_mutating_stored_preview(controlled, monkeypatch):
    finish(controlled)
    monkeypatch.setattr(state, "verification_source_matches", lambda *_a, **_k: None)
    polled = jobs.inspect(controlled.id)
    assert polled["source_busy"] and not polled["stale"]
    assert polled["result"]["selection"]["candidates"] == []
    with jobs._lock:
        assert jobs._jobs[controlled.id].result["selection"]["candidates"]
    unchanged(controlled)


def test_selection_is_document_scoped_shares_admission_and_expires(controlled, monkeypatch):
    from backend.api.part_verification_jobs import start
    with pytest.raises(HTTPException) as busy:
        start()
    assert busy.value.status_code == 429
    finish(controlled)
    token = set_current_doc("other-selection-document")
    try:
        with pytest.raises(HTTPException) as missing:
            jobs.inspect(controlled.id)
        assert missing.value.status_code == 404
    finally:
        reset_current_doc(token)
    monkeypatch.setattr(jobs, "monotonic", lambda: 1e30)
    with pytest.raises(HTTPException) as expired:
        jobs.inspect(controlled.id)
    assert expired.value.status_code == 410
    unchanged(controlled)


@pytest.mark.parametrize("change", ["design", "revision"])
def test_misbound_request_fails_before_submit_and_releases_admission(document, monkeypatch, change):
    request = body()
    key = "expected_design_id" if change == "design" else "expected_revision"
    request["selection"][key] = "other" if change == "design" else state.revision() - 1
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Misbound selection submitted"))
    before = state.get_or_404().model_dump_json()
    revision, depth, redo = state.revision(), state.undo_depth(), state.redo_depth()
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 409 and error.value.detail["code"] == "selection_conflict"
    assert state.get_or_404().model_dump_json() == before
    assert (state.revision(), state.undo_depth(), state.redo_depth()) == (revision, depth, redo)
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_missing_document_is_not_created_for_selection(document):
    request = body()
    state.close_session()
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 404
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_http_selection_schema_poll_cancel_and_commit_rejection(controlled):
    from backend.api.routes_feature_log import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        properties = schema["components"]["schemas"]["EvaluationRequest"]["properties"]
        assert "selection" in properties["operation"]["enum"] and "selection" in properties
        invalid = client.post("/api/design/features/evaluation/jobs", json={"operation": "selection", "selection": {}})
        assert invalid.status_code == 422
        finish(controlled)
        path = f"/api/design/features/evaluation/jobs/{controlled.id}"
        polled = client.get(path)
        assert polled.status_code == 200 and polled.json()["result"]["status"] == "preview"
        assert "candidate" not in polled.json()["result"]
        assert client.post(f"{path}/commit").status_code == 409
        cancelled = client.delete(path)
        assert cancelled.status_code == 200
        assert cancelled.json()["result"]["selection"]["candidates"] == []
    unchanged(controlled)


def test_http_start_passes_a_bounded_parsed_selection_to_existing_job_handler(document, monkeypatch):
    from backend.api.routes_feature_log import router
    received = []

    def start(parsed):
        received.append(parsed)
        return {"job_id": "selection", "status": "running", "source_revision": state.revision()}

    monkeypatch.setattr(jobs, "start", start)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        response = client.post("/api/design/features/evaluation/jobs", json=body())
    assert response.status_code == 202
    assert len(received) == 1 and received[0].operation == "selection"
    assert received[0].selection.parameter_path == ["nanoparticle_id"]
    assert received[0].selection.expected_revision == state.revision()
