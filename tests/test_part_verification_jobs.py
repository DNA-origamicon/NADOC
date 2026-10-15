"""Job lifecycle tests use barriers, not timing sleeps or real model work."""
from threading import Event
from types import SimpleNamespace

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
    closing, cleanup, closed = Event(), Event(), Event()
    cleanup.set()
    real_run = jobs._run

    class ControlledWorker:
        def __init__(self, design):
            pass

        def start(self):
            entered.set()

        def wait(self, timeout):
            return release.wait(timeout)

        def is_alive(self):
            return not closed.is_set()

        def result(self):
            return {"status": "verified", "native_editable": True, "issues": []}

        def close(self):
            closing.set()
            assert cleanup.wait(5)
            closed.set()

    def run(*args):
        try:
            real_run(*args)
        finally:
            completed.set()

    monkeypatch.setattr(jobs, "VerificationWorker", ControlledWorker)
    monkeypatch.setattr(jobs, "_run", run)
    job_id = jobs.start()["job_id"]
    assert entered.wait(5)
    try:
        yield SimpleNamespace(id=job_id, release=release, completed=completed,
                              closing=closing, cleanup=cleanup, closed=closed,
                              worker_type=ControlledWorker)
    finally:
        release.set()
        cleanup.set()
        assert completed.wait(5)
        with jobs._lock:
            jobs._jobs.pop(job_id, None)
        state.close_session()
        reset_current_doc(token)


def test_job_cancellation_prevents_green_publication(controlled_job):
    job = controlled_job
    assert jobs.inspect(job.id, cancel=True)["status"] == "running"
    # Cancellation stops work even when the worker never returns a result.
    assert job.completed.wait(5)
    assert job.closed.is_set()
    result = jobs.inspect(job.id)["result"]
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
            jobs.inspect(controlled_job.id, cancel=True)
        assert exc.value.status_code == 404
    finally:
        reset_current_doc(token)


def test_revision_change_during_job_invalidates_result(controlled_job):
    job = controlled_job
    state.mutate_and_validate(lambda d: setattr(d.metadata, "name", "Edited"))
    assert job.completed.wait(5)
    assert job.closed.is_set()
    result = jobs.inspect(job.id)
    assert result["stale"]
    assert result["result"]["status"] == "unverified"


def test_later_edit_invalidates_already_completed_result(controlled_job):
    job = controlled_job
    job.release.set()
    assert job.completed.wait(5)
    assert jobs.inspect(job.id)["result"]["status"] == "verified"
    state.mutate_and_validate(lambda d: setattr(d.metadata, "name", "Later edit"))
    assert jobs.inspect(job.id)["result"]["status"] == "unverified"
    assert jobs.inspect(job.id)["result"]["native_editable"] is False


def test_time_limit_is_a_nonverified_result(controlled_job, monkeypatch):
    job = controlled_job
    clock = jobs.monotonic()
    monkeypatch.setattr(jobs, "monotonic", lambda: clock + 60)
    assert job.completed.wait(5)
    assert job.closed.is_set()
    result = jobs.inspect(job.id)["result"]
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "time_limit"


def test_admission_remains_held_until_worker_is_reaped(controlled_job):
    job = controlled_job
    job.cleanup.clear()
    jobs.inspect(job.id, cancel=True)
    assert job.closing.wait(5)
    assert not job.completed.is_set()
    with pytest.raises(HTTPException) as exc:
        jobs.start()
    assert exc.value.status_code == 429
    job.cleanup.set()
    assert job.completed.wait(5)


def test_live_cleanup_failure_is_visible_and_retried(controlled_job, monkeypatch):
    job = controlled_job
    attempted, retry_allowed = Event(), Event()
    failed = Event()
    original_close = job.worker_type.close
    original_alive = job.worker_type.is_alive

    def failing_close(worker):
        if not retry_allowed.is_set():
            failed.set()
            raise OSError("Injected process cleanup failure")
        original_close(worker)

    def observed_alive(worker):
        # Cleanup checks liveness only after publishing its failure status.
        if failed.is_set():
            attempted.set()
        return original_alive(worker)

    monkeypatch.setattr(job.worker_type, "close", failing_close)
    monkeypatch.setattr(job.worker_type, "is_alive", observed_alive)
    try:
        jobs.inspect(job.id, cancel=True)
        assert attempted.wait(5)
        result = jobs.inspect(job.id)
        assert result["status"] == "stopping"
        assert result["result"]["status"] == "unverified"
        assert result["result"]["issues"][0]["code"] == "worker_cleanup_error"
        with pytest.raises(HTTPException) as exc:
            jobs.start()
        assert exc.value.status_code == 429
    finally:
        retry_allowed.set()
        assert job.completed.wait(5)
    assert job.closed.is_set()


@pytest.fixture
def immediate_jobs(monkeypatch):
    token = set_current_doc("job-failure-window-test")
    state.load_design(create_empty_part("Part", "SQUARE"))
    monkeypatch.setattr(jobs, "_submit", lambda job, captured: jobs._run(job, captured))
    try:
        yield
    finally:
        with jobs._lock:
            for job_id, job in list(jobs._jobs.items()):
                if job.doc == "job-failure-window-test":
                    jobs._jobs.pop(job_id)
        state.close_session()
        reset_current_doc(token)


def test_submit_failure_removes_unstarted_job_and_releases_admission(immediate_jobs, monkeypatch):
    def failed_submit(*args):
        raise RuntimeError("Injected submit failure")

    monkeypatch.setattr(jobs, "_submit", failed_submit)
    with jobs._lock:
        previous = set(jobs._jobs)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="submit failure"):
            jobs.start()
        with jobs._lock:
            assert set(jobs._jobs) == previous


@pytest.mark.parametrize("stage", ["start", "close"])
def test_worker_failure_after_construction_finishes_and_releases_slot(immediate_jobs, monkeypatch, stage):
    closed = []

    class FailingWorker:
        def __init__(self, design):
            pass

        def start(self):
            if stage == "start":
                raise RuntimeError("Injected start failure")

        def wait(self, timeout):
            return True

        def result(self):
            return {"status": "verified", "native_editable": True, "issues": []}

        def is_alive(self):
            return False

        def close(self):
            closed.append(True)
            if stage == "close":
                raise RuntimeError("Injected cleanup failure after exit")

    monkeypatch.setattr(jobs, "VerificationWorker", FailingWorker)
    for _ in range(2):
        result = jobs.inspect(jobs.start()["job_id"])
        assert result["status"] == "complete"
        assert result["result"]["status"] == "unverified"
        expected = "worker_cleanup_error" if stage == "close" else "verification_error"
        assert result["result"]["issues"][0]["code"] == expected
    assert len(closed) == 2


def test_worker_failure_releases_admission_and_results_are_bounded(monkeypatch):
    token = set_current_doc("job-retention-test")
    state.load_design(create_empty_part("Part", "SQUARE"))
    monkeypatch.setattr(jobs, "_submit", lambda job, captured: jobs._run(job, captured))
    monkeypatch.setattr(jobs, "MAX_RESULTS", 2)
    def fail(*args, **kwargs):
        raise RuntimeError("Injected verifier failure")
    monkeypatch.setattr(jobs, "VerificationWorker", fail)
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
