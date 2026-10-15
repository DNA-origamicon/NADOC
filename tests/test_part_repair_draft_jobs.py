"""Saved proposals use the existing bounded evaluation lifecycle and publication."""

from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, part_evaluation_jobs as jobs, part_repair_draft_evaluation as host, state
from backend.api.part_evaluation import evaluate
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_history_verification import _slot
from backend.api.routes_feature_log import router
from backend.core.models import DesignLoadout
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture
from tests.test_part_recipe_repair import set_input, source as broken_source
from tests.test_part_repair_draft_evaluation import source


PATH = "/api/design/features/repair-draft"
JOBS = "/api/design/features/evaluation/jobs"


@pytest.fixture
def document():
    identity = f"__saved_draft_job__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    state.load_design(source())
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    try:
        with TestClient(app) as client:
            yield client, {"X-NADOC-Doc": identity}, identity
    finally:
        with jobs._lock:
            for key, job in list(jobs._jobs.items()):
                if job.doc == identity:
                    job.cancelled.set()
                    jobs._jobs.pop(key, None)
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)


def request(**changes):
    design, revision = state.get_design_with_revision()
    draft = design.repair_draft
    return {"draft_version": 1, "expected_design_id": design.id, "expected_revision": revision,
        "expected_draft_id": draft.draft_id, "expected_generation": draft.generation, **changes}


def test_host_passes_trusted_same_capture_identity_and_owned_actions(document, monkeypatch):
    source, revision = state.get_design_with_revision()
    session_identity = state._sessions[document[2]].identity
    def start(value, **guards):
        assert guards == {"expected_source": source, "expected_session_identity": session_identity}
        assert value["operation"] == "repair" and value["repair"]["actions"][0] == {**set_input(), "child_id": None}
        assert value["expected_revision"] == value["repair"]["expected_revision"] == revision
        value["repair"]["actions"][0]["value"] = "mutated worker request"
        return {"job_id": "ordinary-catalog-job", "status": "running"}
    monkeypatch.setattr(jobs, "start", start)
    result = host.start_draft_evaluation(request())
    assert result["repair_draft"] == {"draft_id": source.repair_draft.draft_id, "generation": 3}
    assert source.repair_draft.actions[0].value == "gold"
    assert state.get_or_404() is source and state.revision() == revision


@pytest.mark.parametrize("field,value", [("expected_generation", 2), ("expected_draft_id", "old"),
    ("expected_revision", 0), ("expected_design_id", "other")])
def test_stale_metadata_guards_reject_before_capture(document, monkeypatch, field, value):
    monkeypatch.setattr(host, "capture_draft_inputs", lambda *_a, **_k: pytest.fail("Stale draft captured definitions"))
    client, headers, _ = document
    result = client.post(f"{PATH}/evaluate", headers=headers, json=request(**{field: value}))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "draft_conflict"


def test_fingerprint_runs_outside_lock_without_proposed_action_planning(document, monkeypatch):
    original = host.compile_draft_evaluation
    def compile_(captured, value):
        assert not state._lock.locked()
        return original(captured, value)
    monkeypatch.setattr(host, "compile_draft_evaluation", compile_)
    monkeypatch.setattr("backend.core.part_repair_planning.plan_actions",
                        lambda *_a, **_k: pytest.fail("Host replanned saved actions"))
    monkeypatch.setattr(jobs, "start", lambda *_a, **_k: {"job_id": "not-executed"})
    host.start_draft_evaluation(request())


@pytest.mark.parametrize("change", ["source", "revision", "session_aba"])
def test_change_between_fingerprint_and_job_capture_rejects_before_geometry_copy(document, monkeypatch, change):
    original = host.compile_draft_evaluation
    def compile_(captured, value):
        result = original(captured, value)
        with state._lock:
            session = state._session()
            if change == "source":
                session.design = session.design.model_copy()
            elif change == "revision":
                session.revision += 1
            else:
                state._sessions[document[2]] = state._DesignSession(design=session.design, revision=session.revision)
        return result
    monkeypatch.setattr(host, "compile_draft_evaluation", compile_)
    monkeypatch.setattr("backend.api.part_evaluation_capture.capture",
                        lambda *_a, **_k: pytest.fail("Stale identity captured molecular model"))
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Stale identity submitted a worker"))
    with pytest.raises(HTTPException) as error:
        host.start_draft_evaluation(request())
    assert error.value.status_code == 409
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_changed_base_requires_explicit_rebase_without_starting_job(document, monkeypatch):
    state.get_or_404().feature_log[0].params["diameter_nm"] = 11.0
    monkeypatch.setattr(jobs, "start", lambda *_a, **_k: pytest.fail("Unrebased draft started job"))
    with pytest.raises(HTTPException) as error:
        host.start_draft_evaluation(request())
    assert error.value.status_code == 409 and error.value.detail["code"] == "draft_rebase_required"


def test_protected_branch_refuses_evaluation_before_capture(document, monkeypatch):
    design = state.get_or_404()
    design.loadouts = [DesignLoadout(id="simulation", name="Simulation", protected=True)]
    design.active_loadout_id = "simulation"
    monkeypatch.setattr(host, "capture_draft_inputs", lambda *_a, **_k: pytest.fail("Protected branch captured"))
    with pytest.raises(HTTPException) as error:
        host.start_draft_evaluation(request())
    assert error.value.detail["code"] == "protected_simulation_loadout"


def test_http_saved_broken_draft_replays_privately_commits_once_and_cold_verifies(document, monkeypatch):
    client, headers, _ = document
    state.load_design(broken_source())
    original, revision = state.get_design_with_revision()
    create = {"draft_version": 1, "operation": "create", "expected_design_id": original.id,
        "expected_revision": revision, "expected_draft_id": None, "expected_generation": None,
        "actions": [set_input()]}
    saved = client.post(PATH, headers=headers, json=create)
    assert saved.status_code == 200, saved.text
    original, revision = state.get_design_with_revision()
    draft, original_authoring = original.repair_draft, original.model_dump(mode="json", include=AUTHORING_FIELDS)
    done = Event()
    real_run = jobs._run
    def run(*args):
        try:
            real_run(*args)
        finally:
            done.set()
    monkeypatch.setattr(jobs, "_run", run)
    started = client.post(f"{PATH}/evaluate", headers=headers, json=request())
    assert started.status_code == 202, started.text
    identity = started.json()["job_id"]
    assert started.json()["repair_draft"] == {"draft_id": draft.draft_id, "generation": draft.generation}
    assert done.wait(20), "Tiny saved draft exceeded its focused worker allowance"
    result = client.get(f"{JOBS}/{identity}", headers=headers)
    assert result.status_code == 200 and result.json()["result"]["status"] == "ready", result.text
    assert "candidate" not in result.json()["result"]
    assert state.get_or_404() is original and state.revision() == revision and state.undo_depth() == 0
    committed = client.post(f"{JOBS}/{identity}/commit", headers=headers)
    assert committed.status_code == 200, committed.text
    candidate = state.get_or_404()
    assert state.revision() == revision + 1 and state.undo_depth() == 1
    assert candidate.repair_draft is draft and candidate.feature_log[1].params["nanoparticle_id"] == "gold"
    assert candidate.nanoparticles[0].id == "gold" and candidate.nanoparticles[0].diameter_nm == 12.0
    again = client.post(f"{JOBS}/{identity}/commit", headers=headers)
    assert again.status_code == 200 and state.undo_depth() == 1
    stale = client.post(f"{PATH}/evaluate", headers=headers, json=request())
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "draft_rebase_required"
    rebase = {**request(), "operation": "rebase"}
    rejected = client.post(PATH, headers=headers, json=rebase)
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "repair_conflict"
    assert candidate.repair_draft is draft and draft.actions[0].expected_old == "missing"
    # A second fresh process proves regeneration without saved geometry and
    # without the draft entering the worker's source model.
    cold = candidate.model_copy(deep=True)
    for entry in cold.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned output"
    worker = EvaluationWorker(capture(cold, preserve_entry_types=True),
        {"request": {"operation": "verify"}, "header": {}})
    try:
        worker.start()
        assert worker.wait(20)
        proof = worker.result()
        assert proof["status"] == "verified", proof
    finally:
        worker.close()
    state.undo()
    assert state.get_or_404().model_dump(mode="json", include=AUTHORING_FIELDS) == original_authoring
    assert state.get_or_404().repair_draft is draft


@pytest.fixture
def controlled(document, monkeypatch):
    entered, released, completed, closed = Event(), Event(), Event(), Event()
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
            completed.set()
    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_run", run)
    original, revision = state.get_design_with_revision()
    started = host.start_draft_evaluation(request())
    assert entered.wait(5)
    try:
        yield SimpleNamespace(id=started["job_id"], release=released, done=completed,
            original=original, revision=revision)
    finally:
        released.set()
        assert completed.wait(5)


@pytest.mark.parametrize("failure", ["cancel", "expiry", "new_draft", "session_aba"])
def test_saved_draft_jobs_keep_existing_cancel_expiry_generation_and_session_guards(controlled, document, monkeypatch, failure):
    job = controlled
    job.release.set()
    assert job.done.wait(5)
    assert jobs.inspect(job.id)["result"]["status"] == "ready"
    if failure == "cancel":
        jobs.inspect(job.id, cancel=True)
    elif failure == "expiry":
        monkeypatch.setattr(jobs, "monotonic", lambda: 1e30)
    elif failure == "new_draft":
        body = {**request(), "operation": "update", "actions": [set_input(value="future")]}
        state.mutate_repair_draft(body)
    else:
        with state._lock:
            session = state._session()
            state._sessions[document[2]] = state._DesignSession(design=session.design, revision=session.revision)
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        jobs.commit(job.id)
    assert error.value.status_code == (410 if failure == "expiry" else 409)
    assert state.get_or_404() is before and state.revision() == revision and state.undo_depth() == 0
