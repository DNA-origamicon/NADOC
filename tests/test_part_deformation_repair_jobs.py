"""Private enabled lifecycle of saved named-group repairs through ordinary jobs.

The worker double runs the actual pure evaluator on captured input in the job
thread. No new process, files, lifespan, or production enablement is introduced.
"""

from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, part_evaluation_jobs as jobs, state
from backend.api import part_group_organization_gate as gate, part_publication_permit as permits
from backend.api import part_repair_drafts as drafts
from backend.api.part_evaluation import evaluate
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_feature_log import router
from backend.core import models as m
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from tests.test_part_deformation_repair import action, source


DRAFT = "/api/design/features/repair-draft"
JOBS = "/api/design/features/evaluation/jobs"


@pytest.fixture
def document(monkeypatch):
    design = source()
    design.annotations_enabled = False
    identity = f"__named_repair__{uuid4()}"
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(identity)
    try:
        state.load_design(design)
        app = FastAPI()
        app.add_middleware(doc_context.DocContextMiddleware)
        app.include_router(router, prefix="/api")
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, headers={"X-NADOC-Doc": identity}, doc=identity)
    finally:
        try:
            with jobs._lock:
                for key, job in list(jobs._jobs.items()):
                    if job.doc == identity:
                        job.cancelled.set()
                        jobs._jobs.pop(key, None)
            state.drop_doc(identity)
        finally:
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)
            doc_context.reset_current_doc(token)


def draft_body(operation="create"):
    design, revision = state.get_design_with_revision()
    draft = design.repair_draft
    result = {"draft_version": 1, "operation": operation,
        "expected_design_id": design.id, "expected_revision": revision,
        "expected_draft_id": None if draft is None else draft.draft_id,
        "expected_generation": None if draft is None else draft.generation}
    if operation in {"create", "update"}:
        result["actions"] = [action()]
    return result


def evaluation_body():
    body = draft_body("rebase")
    body.pop("operation")
    return body


def post(document, path, body=None):
    return document.client.post(path, headers=document.headers, json=body)


@pytest.fixture
def controlled(document, monkeypatch):
    saved = post(document, DRAFT, draft_body())
    assert saved.status_code == 200, saved.text
    entered, released, done, closed = Event(), Event(), Event(), Event()
    real_run = jobs._run

    class Worker:
        def __init__(self, design, operation):
            self.design, self.operation = design, operation

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
            done.set()

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_run", run)
    started = post(document, f"{DRAFT}/evaluate", evaluation_body())
    assert started.status_code == 202, started.text
    identity = started.json()["job_id"]
    try:
        assert entered.wait(5)
        yield SimpleNamespace(id=identity, doc=document, release=released, done=done, closed=closed,
            source=state.get_or_404(), revision=state.revision(), depth=state.undo_depth())
    finally:
        released.set()
        assert done.wait(10), "Tiny named repair worker did not finish cleanup"


def finish(job):
    job.release.set()
    assert job.done.wait(10)
    result = jobs.inspect(job.id)
    assert result["result"]["status"] == "ready", result
    assert job.closed.is_set()
    return result


def unchanged(job):
    assert state.get_or_404() is job.source
    assert state.revision() == job.revision
    assert state.undo_depth() == job.depth and state.redo_depth() == 0


def test_saved_repair_gets_owned_recipe_scope_and_one_atomic_commit_with_cold_replay(controlled):
    job = controlled
    result = finish(job)
    assert "candidate" not in result["result"]
    context = permits.admission_context(jobs._jobs[job.id].admission)
    assert context.scope_tag == "organized_recipe_v1" and context.operation == "repair"
    unchanged(job)
    committed = post(job.doc, f"{JOBS}/{job.id}/commit")
    assert committed.status_code == 200, committed.text
    candidate = state.get_or_404()
    assert candidate.repair_draft is job.source.repair_draft
    assert candidate.annotations_enabled is False
    assert candidate.feature_log[-2].op_snapshot.targets == [{"kind": "part_group", "id": "replacement"}]
    assert state.revision() == job.revision + 1 and state.undo_depth() == job.depth + 1
    assert jobs.commit(job.id)["revision"] == state.revision() and state.undo_depth() == job.depth + 1
    loaded = m.Design.from_json(candidate.to_json())
    for entry in loaded.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned"
    assert assess_part_history(loaded, execute=execute, dependencies=dependencies)["status"] == "verified"
    state.undo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == job.source.model_dump(include=AUTHORING_FIELDS)
    assert state.get_or_404().repair_draft is job.source.repair_draft
    state.redo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == candidate.model_dump(include=AUTHORING_FIELDS)


def test_closed_live_gate_refuses_saved_proposal_before_capture(document, monkeypatch):
    source, revision = state.get_design_with_revision()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    monkeypatch.setattr(drafts, "capture_draft_inputs", lambda *_a, **_k: pytest.fail("Disabled capture"))
    response = post(document, DRAFT, draft_body())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "group_organization_not_enabled"
    assert state.get_or_404() is source and state.revision() == revision and state.undo_depth() == 0


def test_gate_rechecks_after_unlocked_draft_preparation_before_metadata_publication(document, monkeypatch):
    source, revision = state.get_design_with_revision()
    prepare = drafts.prepare_draft

    def flip(*args, **kwargs):
        assert not state._lock.locked()
        result = prepare(*args, **kwargs)
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
        return result

    monkeypatch.setattr(drafts, "prepare_draft", flip)
    response = post(document, DRAFT, draft_body())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "group_organization_not_enabled"
    assert state.get_or_404() is source and state.revision() == revision and state.undo_depth() == 0


def test_ready_active_repair_cannot_commit_after_live_gate_closes(controlled, monkeypatch):
    finish(controlled)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    with pytest.raises(HTTPException) as caught:
        jobs.commit(controlled.id)
    assert caught.value.status_code == 409
    unchanged(controlled)


@pytest.mark.parametrize("change", ["source", "session-aba"])
def test_original_source_and_session_incarnation_bind_active_recipe_permit(controlled, change):
    finish(controlled)
    with state._lock:
        session = state._sessions[controlled.doc.doc]
        if change == "source":
            session.design = session.design.model_copy()
        else:
            state._sessions[controlled.doc.doc] = state._DesignSession(
                design=session.design, revision=session.revision)
        current = state._sessions[controlled.doc.doc]
    with pytest.raises(HTTPException) as caught:
        jobs.commit(controlled.id)
    assert caught.value.status_code == 409
    assert state.get_or_404() is current.design and state.revision() == current.revision
    assert state.undo_depth() == 0 and state.redo_depth() == 0


def test_failed_revision_publication_keeps_same_source_draft_and_retryable_job(controlled, monkeypatch):
    finish(controlled)

    def fail(session):
        session.revision += 1
        doc_context.set_request_revision(session.revision)
        raise RuntimeError("Injected publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(state, "_bump_revision", fail)
        with pytest.raises(RuntimeError, match="Injected publication"):
            jobs.commit(controlled.id)
    unchanged(controlled)
    assert jobs.inspect(controlled.id)["status"] == "complete"
    assert jobs.commit(controlled.id)["revision"] == controlled.revision + 1


def test_committed_draft_remains_pending_and_requires_explicit_new_expectation(controlled):
    finish(controlled)
    jobs.commit(controlled.id)
    draft = state.get_or_404().repair_draft
    rejected = post(controlled.doc, f"{DRAFT}/evaluate", evaluation_body())
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "draft_rebase_required"
    rebased = post(controlled.doc, DRAFT, draft_body("rebase"))
    assert rebased.status_code == 409 and rebased.json()["detail"]["code"] == "repair_conflict"
    assert state.get_or_404().repair_draft is draft and draft.actions[0].expected_old == "missing"
