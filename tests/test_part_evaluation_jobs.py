"""Candidate lifecycle, race and publication invariants without solver sleeps."""

from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import crud, part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import evaluate


@pytest.fixture
def controlled(monkeypatch):
    token = set_current_doc("part-evaluation-job")
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21))
    state.get_or_404().annotations_enabled = False
    entered, released, completed, closed = Event(), Event(), Event(), Event()
    real_run = jobs._run

    class Worker:
        def __init__(self, source, operation):
            self.source, self.operation = source, operation

        def start(self):
            entered.set()

        def wait(self, timeout):
            return released.wait(timeout)

        def is_alive(self):
            return not closed.is_set()

        def result(self):
            return evaluate(self.source, self.operation)

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
    depth = state.undo_depth()
    identity = jobs.start({"operation": "edit", "index": 0, "params": {"length_bp": 28}})["job_id"]
    assert entered.wait(5)
    try:
        yield SimpleNamespace(id=identity, release=released, done=completed, closed=closed,
                              original=original, revision=revision, depth=depth)
    finally:
        released.set()
        assert completed.wait(5)
        with jobs._lock:
            jobs._jobs.pop(identity, None)
        state.close_session()
        reset_current_doc(token)


def ready(job):
    job.release.set()
    assert job.done.wait(5)
    result = jobs.inspect(job.id)
    assert result["result"]["status"] == "ready", result
    assert "candidate" not in result["result"]


def test_ready_candidate_is_private_and_commit_is_exact_atomic_and_idempotent(controlled):
    job = controlled
    ready(job)
    assert state.get_design_with_revision() == (job.original, job.revision)
    result = jobs.commit(job.id)
    updated = state.get_or_404()
    assert result["status"] == "committed"
    assert updated.helices[0].length_bp == 28
    assert updated.annotations_enabled is False
    assert state.undo_depth() == job.depth + 1
    assert jobs.commit(job.id)["revision"] == result["revision"]
    assert state.undo_depth() == job.depth + 1
    assert jobs.inspect(job.id, cancel=True)["status"] == "committed"
    state.undo()
    assert state.get_or_404().helices == job.original.helices
    state.redo()
    assert state.get_or_404().helices == updated.helices


def test_cancelled_candidate_cannot_be_committed(controlled):
    ready(controlled)
    result = jobs.inspect(controlled.id, cancel=True)
    assert result["result"]["status"] == "unverified"
    with pytest.raises(HTTPException) as exc:
        jobs.commit(controlled.id)
    assert exc.value.status_code == 409
    assert state.get_design_with_revision() == (controlled.original, controlled.revision)
    with jobs._lock:
        assert "candidate" not in jobs._jobs[controlled.id].result


def test_stale_ready_candidate_cannot_overwrite_intervening_work(controlled):
    ready(controlled)
    state.mutate_and_validate(lambda d: setattr(d.metadata, "name", "Intervening work"))
    current, revision = state.get_design_with_revision()
    assert jobs.inspect(controlled.id)["stale"]
    with pytest.raises(HTTPException) as exc:
        jobs.commit(controlled.id)
    assert exc.value.status_code == 409
    assert state.get_design_with_revision() == (current, revision)


def test_cancel_running_job_reaps_before_a_result_can_be_committed(controlled):
    job = controlled
    jobs.inspect(job.id, cancel=True)
    assert job.done.wait(5)
    assert job.closed.is_set()
    assert jobs.inspect(job.id)["result"]["issues"][0]["code"] == "cancelled"
    with pytest.raises(HTTPException):
        jobs.commit(job.id)


def test_job_is_document_scoped_and_shares_ordinary_admission(controlled):
    from backend.api.part_verification_jobs import start

    with pytest.raises(HTTPException) as busy:
        start()
    assert busy.value.status_code == 429
    token = set_current_doc("different-document")
    try:
        with pytest.raises(HTTPException) as missing:
            jobs.inspect(controlled.id)
        assert missing.value.status_code == 404
    finally:
        reset_current_doc(token)


def test_expired_candidate_is_discarded_without_publication(controlled, monkeypatch):
    ready(controlled)
    monkeypatch.setattr(jobs, "monotonic", lambda: 1e30)
    with pytest.raises(HTTPException) as exc:
        jobs.commit(controlled.id)
    assert exc.value.status_code == 410
    assert state.get_design_with_revision() == (controlled.original, controlled.revision)
    with jobs._lock:
        assert "candidate" not in jobs._jobs[controlled.id].result


def test_commit_revision_names_its_own_mutation_when_a_later_edit_races(controlled, monkeypatch):
    ready(controlled)
    original_set = state.set_design

    def publish_then_edit(*args, **kwargs):
        revision = original_set(*args, **kwargs)
        state.mutate_and_validate(lambda d: setattr(d.metadata, "name", "Later edit"))
        return revision

    monkeypatch.setattr(state, "set_design", publish_then_edit)
    result = jobs.commit(controlled.id)
    assert result["revision"] == controlled.revision + 1
    assert state.revision() == result["revision"] + 1
    assert state.get_or_404().metadata.name == "Later edit"


def test_decode_cannot_silently_change_evaluated_authoring(controlled):
    ready(controlled)
    with jobs._lock:
        data = jobs._jobs[controlled.id].result["candidate"]
        from backend.core.models import NucleotideTransform
        pose = NucleotideTransform(kind="base", helix_id=data["helices"][0]["id"],
                                   bp_index=0, direction="FORWARD").model_dump(mode="json")
        pose["rotation"] = [0, 0, 0, 2]
        data["nucleotide_transforms"] = [pose]
    with pytest.raises(HTTPException) as exc:
        jobs.commit(controlled.id)
    assert exc.value.status_code == 409
    assert jobs.inspect(controlled.id)["result"]["issues"] == [
        {"code": "candidate_decode_changed_authoring"},
    ]
    assert state.get_design_with_revision() == (controlled.original, controlled.revision)


def test_expiry_during_decode_prevents_publication(controlled, monkeypatch):
    from backend.core.models import Design

    ready(controlled)
    validate = Design.model_validate

    def expire_on_decode(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        monkeypatch.setattr(jobs, "monotonic", lambda: 1e30)
        return candidate

    monkeypatch.setattr(Design, "model_validate", expire_on_decode)
    with pytest.raises(HTTPException) as exc:
        jobs.commit(controlled.id)
    assert exc.value.status_code == 410
    assert state.get_design_with_revision() == (controlled.original, controlled.revision)


def test_http_job_routes_preserve_scope_private_results_and_revision_commit(controlled):
    from fastapi.testclient import TestClient
    from backend.api.main import app

    client = TestClient(app)
    headers = {"X-NADOC-Doc": "part-evaluation-job"}
    path = f"/api/design/features/evaluation/jobs/{controlled.id}"
    invalid = client.post("/api/design/features/evaluation/jobs", headers=headers,
                          json={"operation": "verify", "candidate": {}})
    assert invalid.status_code == 422
    assert client.get(path, headers={"X-NADOC-Doc": "other-doc"}).status_code == 404
    ready(controlled)
    result = client.get(path, headers=headers)
    assert result.status_code == 200
    assert "candidate" not in result.json()["result"]
    committed = client.post(f"{path}/commit", headers=headers)
    assert committed.status_code == 200, committed.text
    assert committed.json()["revision"] == controlled.revision + 1
    assert client.delete(path, headers=headers).json()["status"] == "committed"
