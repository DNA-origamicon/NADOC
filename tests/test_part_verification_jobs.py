"""Job lifecycle tests use barriers, not timing sleeps or real model work."""
from threading import Event

import pytest
from fastapi import HTTPException

from backend.api import part_verification_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def controlled_job(monkeypatch):
    token = set_current_doc("verification-job-test")
    state.load_design(create_empty_part("Part", "SQUARE"))
    entered, release, completed = Event(), Event(), Event()
    real_run = jobs._run

    def assess(design, **kwargs):
        entered.set()
        assert release.wait(5)
        kwargs["checkpoint"]()
        return {"status": "verified", "issues": []}

    def run(*args):
        try:
            real_run(*args)
        finally:
            completed.set()

    monkeypatch.setattr(jobs, "assess_part_history", assess)
    monkeypatch.setattr(jobs, "_run", run)
    job_id = jobs.start()["job_id"]
    assert entered.wait(5)
    try:
        yield job_id, release, completed
    finally:
        release.set()
        assert completed.wait(5)
        with jobs._lock:
            jobs._jobs.pop(job_id, None)
        state.close_session()
        reset_current_doc(token)


def test_job_cancellation_prevents_green_publication(controlled_job):
    job_id, release, completed = controlled_job
    assert jobs.inspect(job_id, cancel=True)["status"] == "running"
    release.set()
    assert completed.wait(5)
    result = jobs.inspect(job_id)["result"]
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "cancelled"


def test_single_admission_has_no_unbounded_work_queue(controlled_job):
    with pytest.raises(HTTPException) as exc:
        jobs.start()
    assert exc.value.status_code == 429


def test_jobs_are_scoped_to_the_request_document(controlled_job):
    token = set_current_doc("another-document")
    try:
        with pytest.raises(HTTPException) as exc:
            jobs.inspect(controlled_job[0], cancel=True)
        assert exc.value.status_code == 404
    finally:
        reset_current_doc(token)


def test_revision_change_during_job_invalidates_result(controlled_job):
    job_id, release, completed = controlled_job
    state.mutate_and_validate(lambda d: setattr(d.metadata, "name", "Edited"))
    release.set()
    assert completed.wait(5)
    result = jobs.inspect(job_id)
    assert result["stale"]
    assert result["result"]["status"] == "unverified"


def test_later_edit_invalidates_already_completed_result(controlled_job):
    job_id, release, completed = controlled_job
    release.set()
    assert completed.wait(5)
    assert jobs.inspect(job_id)["result"]["status"] == "verified"
    state.mutate_and_validate(lambda d: setattr(d.metadata, "name", "Later edit"))
    assert jobs.inspect(job_id)["result"]["status"] == "unverified"
    assert jobs.inspect(job_id)["result"]["native_editable"] is False


def test_time_limit_is_a_nonverified_result(controlled_job, monkeypatch):
    job_id, release, completed = controlled_job
    clock = jobs.monotonic()
    monkeypatch.setattr(jobs, "monotonic", lambda: clock + 60)
    release.set()
    assert completed.wait(5)
    result = jobs.inspect(job_id)["result"]
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "time_limit"


def test_worker_failure_releases_admission_and_results_are_bounded(monkeypatch):
    class ImmediateExecutor:
        def submit(self, fn, *args):
            fn(*args)
    token = set_current_doc("job-retention-test")
    state.load_design(create_empty_part("Part", "SQUARE"))
    monkeypatch.setattr(jobs, "_executor", ImmediateExecutor())
    monkeypatch.setattr(jobs, "MAX_RESULTS", 2)
    def fail(*args, **kwargs):
        raise RuntimeError("Injected verifier failure")
    monkeypatch.setattr(jobs, "assess_part_history", fail)
    ids = []
    try:
        for _ in range(3):
            job_id = jobs.start()["job_id"]
            ids.append(job_id)
            assert jobs.inspect(job_id)["result"]["status"] == "unverified"
        with pytest.raises(HTTPException) as exc:
            jobs.inspect(ids[0])
        assert exc.value.status_code == 404
    finally:
        with jobs._lock:
            for job_id in ids:
                jobs._jobs.pop(job_id, None)
        state.close_session()
        reset_current_doc(token)
