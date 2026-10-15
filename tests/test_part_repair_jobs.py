"""Repair publication reuses the existing bounded, revision-bound job lifecycle."""

from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import evaluate
from backend.api.part_history_verification import _slot
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from tests.test_part_recipe_repair import request as repair_request, set_input, source


@pytest.fixture
def document():
    token = set_current_doc("part-repair-job")
    state.load_design(source())
    state.get_or_404().annotations_enabled = False
    # A failed repair must preserve both stacks, including an existing redo.
    state.set_design(state.get_or_404().model_copy(deep=True))
    state.undo()
    try:
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def body(*actions):
    return {"operation": "repair", "repair": repair_request(*actions,
        expected_design_id=state.get_or_404().id, expected_revision=state.revision())}


@pytest.fixture
def controlled(document, monkeypatch, request):
    entered, released, completed, closed = Event(), Event(), Event(), Event()
    real_run = jobs._run
    received = []

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
    selected = set_input(value="future") if getattr(request, "param", None) == "failure" else set_input()
    identity = jobs.start(body(selected))["job_id"]
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
    assert state.revision() == job.revision
    assert (state.undo_depth(), state.redo_depth()) == (job.depth, job.redo)


def test_ready_repair_has_compact_comparison_then_one_atomic_commit_and_undo_redo(controlled):
    job = controlled
    result = finish(job)
    assert result["result"]["status"] == "ready", result
    assert "candidate" not in result["result"]
    assert result["result"]["repair"]["authoring_changes"]["changed_fields"] == ["nanoparticles"]
    assert job.received[0]["header"]["source_revision"] == job.revision
    assert job.received[0]["header"]["source_design_id"] == job.original.id
    unchanged(job)
    committed = jobs.commit(job.id)
    candidate = state.get_or_404()
    assert committed["revision"] == job.revision + 1
    assert state.undo_depth() == job.depth + 1 and state.redo_depth() == 0
    assert candidate.annotations_enabled is False
    assert [item.id for item in candidate.feature_log] == [item.id for item in job.original.feature_log]
    assert candidate.feature_log[1].params["nanoparticle_id"] == "gold"
    assert jobs.commit(job.id)["revision"] == committed["revision"]
    assert state.undo_depth() == job.depth + 1
    reloaded = Design.from_json(candidate.to_json())
    assert assess_part_history(reloaded, execute=execute, dependencies=dependencies)["status"] == "verified"
    state.undo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == job.original.model_dump(include=AUTHORING_FIELDS)
    assert state.get_or_404().feature_log[1].params["nanoparticle_id"] == "missing"
    state.redo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == candidate.model_dump(include=AUTHORING_FIELDS)


@pytest.mark.parametrize("controlled", ["failure"], indirect=True)
def test_failed_repair_preserves_geometry_history_redo_and_first_failure_metadata(controlled):
    result = finish(controlled)["result"]
    assert result["status"] == "failed", result
    assert result["issues"][0]["code"] == "missing_reference"
    assert result["repair"]["completed_prefix"] == ["create"]
    assert result["repair"]["not_evaluated"] == ["later"]
    with jobs._lock:
        assert "candidate" not in jobs._jobs[controlled.id].result
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 409
    unchanged(controlled)


@pytest.mark.parametrize("when", ["running", "ready"])
def test_cancelled_repair_never_publishes_and_reaps_before_releasing_admission(controlled, when):
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
def test_intervening_edit_reload_or_close_invalidates_ready_repair(controlled, change):
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


def test_expired_and_other_document_repairs_are_not_publishable(controlled, monkeypatch):
    finish(controlled)
    token = set_current_doc("other-part-repair-job")
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
def test_misbound_request_is_rejected_before_submit_and_admission_is_released(document, monkeypatch, change):
    request = body()
    if change == "design":
        request["repair"]["expected_design_id"] = "other"
    else:
        request["repair"]["expected_revision"] -= 1
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Stale repair was submitted"))
    before = state.get_or_404().model_dump_json()
    revision, depth, redo = state.revision(), state.undo_depth(), state.redo_depth()
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 409 and error.value.detail["code"] == "repair_conflict"
    assert state.get_or_404().model_dump_json() == before
    assert (state.revision(), state.undo_depth(), state.redo_depth()) == (revision, depth, redo)
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.mark.parametrize("field", ["feature_identity", "root"])
def test_decode_cannot_change_evaluated_repair_definitions(controlled, monkeypatch, field):
    finish(controlled)
    validate = Design.model_validate

    def changed(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        if field == "feature_identity":
            candidate.feature_log[1].id = "different-command"
        else:
            candidate.recipe_root = candidate.recipe_root.model_copy(update={"initial_name": "Changed root"})
        return candidate

    monkeypatch.setattr(Design, "model_validate", changed)
    with pytest.raises(HTTPException) as error:
        jobs.commit(controlled.id)
    assert error.value.status_code == 409
    assert jobs.inspect(controlled.id)["result"]["issues"] == [{"code": "candidate_decode_changed_recipe"}]
    unchanged(controlled)


def test_existing_http_job_routes_accept_repair_and_keep_geometry_out_of_polling(controlled):
    from backend.api.routes_feature_log import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        assert "repair" in schema["components"]["schemas"]["EvaluationRequest"]["properties"]["operation"]["enum"]
        invalid = client.post("/api/design/features/evaluation/jobs", json={"operation": "repair", "repair": {}})
        assert invalid.status_code == 422
        finish(controlled)
        path = f"/api/design/features/evaluation/jobs/{controlled.id}"
        polled = client.get(path)
        assert polled.status_code == 200, polled.text
        result = polled.json()["result"]
        assert "candidate" not in result and "geometry" not in result
        assert result["repair"]["authoring_changes"]["visual_comparison"] is False
        committed = client.post(f"{path}/commit")
        assert committed.status_code == 200 and committed.json()["status"] == "committed"
