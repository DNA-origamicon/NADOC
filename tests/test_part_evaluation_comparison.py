"""The existing evaluation owner leases a private projection without publication."""

from copy import deepcopy
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, part_evaluation_comparison as comparison, part_evaluation_jobs as jobs, state
from backend.api import part_publication_policy as policy
from backend.api.part_evaluation import evaluate
from backend.core.part_comparison_projection import compare
from tests.test_part_repair_draft_evaluation import source as saved_source


@pytest.fixture
def ready(monkeypatch, request):
    identity = f"__comparison__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    job_id = None

    def cleanup():
        try:
            with jobs._lock:
                if job_id is not None:
                    jobs._jobs.pop(job_id, None)
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)

    # Setup can fail (for example at capture admission) before reaching yield.
    # Register cleanup immediately so following tests cannot inherit this doc.
    request.addfinalizer(cleanup)
    source = saved_source()
    state.load_design(source)
    revision = state.revision()
    def submit(job, captured, operation):
        try:
            job.result = evaluate(captured, operation)
            assert job.result["status"] == "ready", job.result
            job.status = "complete"
        finally:
            jobs._slot.release()
    monkeypatch.setattr(jobs, "_submit", submit)
    payload = {"operation": "repair", "expected_revision": revision,
        "repair": {"repair_version": 1, "expected_design_id": source.id, "expected_revision": revision,
                   "actions": [action.model_dump(mode="json") for action in source.repair_draft.actions]}}
    job_id = jobs.start(payload)["job_id"]
    lease = {"projection_version": 1, "expected_design_id": source.id, "expected_revision": revision,
             "expected_draft_id": source.repair_draft.draft_id, "expected_generation": source.repair_draft.generation}
    with jobs._lock:
        job = jobs._jobs[job_id]
    h = SimpleNamespace(doc=identity, source=source, revision=revision, id=job_id, job=job,
                        body=lease, opened=0, closed=0, before_result=lambda: None)

    class Worker:
        def __init__(self, captured, candidate):
            assert captured is not source
            assert not state._lock.locked() and not jobs._lock.locked()
            self.source, self.candidate = captured, deepcopy(candidate)
            self.alive = False
            h.captured = captured
            h.opened += 1

        def start(self):
            self.alive = True

        def wait(self, _timeout):
            self.alive = False
            return True

        def is_alive(self):
            return self.alive

        def result(self):
            result = compare(self.source, self.candidate)
            h.before_result()
            return result

        def close(self):
            assert not jobs._lock.locked()
            self.alive = False
            h.closed += 1

    monkeypatch.setattr(comparison, "ComparisonWorker", Worker)
    yield h


def test_projection_is_private_uses_one_catalog_and_keeps_candidate_committable(ready):
    h = ready
    original = h.source.model_dump_json()
    candidate = h.job.result["candidate"]
    identities = tuple(jobs._jobs)
    result = jobs.comparison(h.id, h.body)
    assert result["status"] == "projected" and result["job_id"] == h.id
    assert 0 < result["expires_in_seconds"] <= jobs.RESULT_TTL
    assert result["repair_draft"] == {"draft_id": h.body["expected_draft_id"], "generation": 3}
    assert result["published"]["particles"][0]["diameter_nm"] == 99.
    assert result["proposed"]["particles"][0]["diameter_nm"] == 12.
    assert not ({"candidate", "design", "candidate_digests", "feature_log"} & result.keys())
    assert state.get_design_with_revision() == (h.source, h.revision)
    assert h.source.model_dump_json() == original and state.undo_depth() == 0
    assert h.captured.repair_draft is None
    assert h.captured.nanoparticles[0] is not h.source.nanoparticles[0]
    assert tuple(jobs._jobs) == identities and h.job.result["candidate"] is candidate
    assert h.opened == h.closed == 1
    committed = jobs.commit(h.id)
    assert committed["revision"] == h.revision + 1 and state.undo_depth() == 1


def test_display_lease_uses_remaining_lifetime_after_projection_not_a_new_ttl(ready, monkeypatch):
    def finish_late():
        monkeypatch.setattr(jobs, "monotonic", lambda: ready.job.created + jobs.RESULT_TTL - 7.)
    ready.before_result = finish_late
    result = jobs.comparison(ready.id, ready.body)
    assert result["expires_in_seconds"] == 7.
    assert ready.job.result["status"] == "ready" and ready.closed == 1


def test_expiry_at_the_final_guard_returns_no_display_lease(ready, monkeypatch):
    original = comparison._final_source_guard
    def expire_after_guard(job, request):
        original(job, request)
        monkeypatch.setattr(jobs, "monotonic", lambda: job.created + jobs.RESULT_TTL)
    monkeypatch.setattr(comparison, "_final_source_guard", expire_after_guard)
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 410 and error.value.detail["code"] == "comparison_expired"
    assert ready.closed == 1
    assert jobs._slot.acquire(blocking=False)
    jobs._slot.release()


@pytest.mark.parametrize("field,value", [("expected_revision", 0), ("expected_design_id", "another"),
    ("expected_draft_id", "another"), ("expected_generation", 2)])
def test_stale_request_refuses_before_source_capture(ready, monkeypatch, field, value):
    monkeypatch.setattr(comparison, "capture", lambda *_a, **_k: pytest.fail("Stale context was copied"))
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, {**ready.body, field: value})
    assert error.value.status_code == 409 and ready.opened == 0
    assert jobs._slot.acquire(blocking=False)
    jobs._slot.release()


def test_unrelated_repair_request_cannot_be_presented_as_the_saved_proposal(ready):
    ready.source.repair_draft.actions[0].value = "future"
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 409 and ready.opened == 0


@pytest.mark.parametrize("operation", ["verify", "selection", "append", "batch", None])
def test_nonrepair_jobs_cannot_expose_a_comparison_candidate(ready, operation):
    ready.job.admitted_operation = operation
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 409 and ready.opened == 0


@pytest.mark.parametrize("change", ["cancel", "expire", "source", "session", "generation", "evict", "candidate", "contents"])
def test_change_during_projection_never_releases_a_stale_comparison(ready, monkeypatch, change):
    h = ready
    def change_context():
        if change == "cancel":
            jobs.inspect(h.id, cancel=True)
        elif change == "expire":
            monkeypatch.setattr(jobs, "monotonic", lambda: 1e30)
        elif change in {"source", "session", "generation"}:
            with state._lock:
                session = state._sessions[h.doc]
                if change == "source":
                    session.design = h.source.model_copy()
                elif change == "session":
                    state._sessions[h.doc] = state._DesignSession(design=h.source, revision=h.revision)
                else:
                    h.source.repair_draft = h.source.repair_draft.model_copy(update={"generation": 4})
        elif change == "evict":
            with jobs._lock:
                jobs._jobs.pop(h.id)
        elif change == "candidate":
            h.job.result["candidate"] = deepcopy(h.job.result["candidate"])
        else:
            h.job.result["candidate"]["nanoparticles"][0]["diameter_nm"] = 33.
    h.before_result = change_context
    with pytest.raises(HTTPException) as error:
        jobs.comparison(h.id, h.body)
    assert error.value.status_code in {404, 409, 410}
    assert h.closed == 1
    assert jobs._slot.acquire(blocking=False)
    jobs._slot.release()


def test_busy_slot_refuses_without_copy_or_queue(ready, monkeypatch):
    monkeypatch.setattr(comparison, "_capture_source", lambda *_a: pytest.fail("Busy comparison captured"))
    assert jobs._slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as error:
            jobs.comparison(ready.id, ready.body)
        assert error.value.status_code == 429
    finally:
        jobs._slot.release()


def test_busy_source_refuses_without_waiting_or_releasing_an_unowned_lock(ready):
    with state._lock:
        with pytest.raises(HTTPException) as error:
            jobs.comparison(ready.id, ready.body)
        assert error.value.status_code == 409 and error.value.detail["code"] == "source_busy"
        assert state._lock.locked()
    assert ready.opened == 0


def test_request_is_document_scoped(ready):
    token = doc_context.set_current_doc(f"other-{uuid4()}")
    try:
        with pytest.raises(HTTPException) as error:
            jobs.comparison(ready.id, ready.body)
        assert error.value.status_code == 404 and ready.opened == 0
    finally:
        doc_context.reset_current_doc(token)


def test_capture_and_decode_limits_never_publish_or_drop_original_candidate(ready, monkeypatch):
    monkeypatch.setattr(comparison, "CAPTURE_BYTES", 32)
    candidate = ready.job.result["candidate"]
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 413
    assert ready.job.result["candidate"] is candidate and ready.opened == 0
    assert state.revision() == ready.revision


def test_scope_checks_spend_the_same_capture_deadline_before_copying(ready, monkeypatch):
    from backend.core import part_repair_capture
    now = [100.]
    monkeypatch.setattr(part_repair_capture, "monotonic", lambda: now[0])
    monkeypatch.setattr(comparison, "monotonic", lambda: now[0])
    original = comparison.check_scope
    def delayed_scope(source, **options):
        now[0] += comparison.CAPTURE_SECONDS + 0.001
        return original(source, **options)
    monkeypatch.setattr(comparison, "check_scope", delayed_scope)
    monkeypatch.setattr(comparison, "capture", lambda *_a, **_k: pytest.fail("Expired scope copied the source"))
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 413 and ready.opened == 0


def test_source_capture_does_not_visit_recovery_physical_or_presentation_state(ready):
    ready.source.feature_log[0].post_state_gz_b64 = "poisoned recovery" * 1000
    ready.source.annotations = [{"unreviewed": object()}]
    ready.source.atomistic_reference = object()
    result = jobs.comparison(ready.id, ready.body)
    assert result["status"] == "projected"
    assert ready.captured.annotations == [] and ready.captured.atomistic_reference is None
    assert ready.captured.feature_log[0].post_state_gz_b64 == ""


def test_strict_policy_refuses_before_capture_even_for_an_existing_repair(ready, monkeypatch):
    previous = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    monkeypatch.setattr(comparison, "_capture_source", lambda *_a: pytest.fail("Strict comparison captured"))
    try:
        with pytest.raises(HTTPException) as error:
            jobs.comparison(ready.id, ready.body)
        assert error.value.status_code == 403 and ready.opened == 0
    finally:
        state.configure_part_publication_policy(previous)


def test_worker_start_failure_cleans_up_without_damaging_ready_candidate(ready, monkeypatch):
    base = comparison.ComparisonWorker
    class BrokenStart(base):
        def start(self):
            raise RuntimeError("Cannot start display worker")
    monkeypatch.setattr(comparison, "ComparisonWorker", BrokenStart)
    candidate = ready.job.result["candidate"]
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 422 and ready.closed == 1
    assert ready.job.result["candidate"] is candidate and ready.job.result["status"] == "ready"
    assert jobs._slot.acquire(blocking=False)
    jobs._slot.release()


def test_comparison_deadline_refuses_without_removing_the_ready_job(ready, monkeypatch):
    monkeypatch.setattr(comparison, "TIME_BUDGET", 0)
    with pytest.raises(HTTPException) as error:
        jobs.comparison(ready.id, ready.body)
    assert error.value.status_code == 504 and error.value.detail["code"] == "time_limit"
    assert ready.job.status == "complete" and ready.job.result["status"] == "ready"
    assert jobs._slot.acquire(blocking=False)
    jobs._slot.release()


def test_cancel_blocked_projection_reaps_before_releasing_shared_admission(ready, monkeypatch):
    entered, closed, finished = Event(), Event(), Event()
    errors = []
    class Blocking:
        def __init__(self, *_):
            pass
        def start(self):
            entered.set()
        def wait(self, timeout):
            finished.wait(timeout)
            return False
        def is_alive(self):
            return not closed.is_set()
        def close(self):
            assert not jobs._slot.acquire(blocking=False)
            closed.set()
    monkeypatch.setattr(comparison, "ComparisonWorker", Blocking)
    def run():
        token = doc_context.set_current_doc(ready.doc)
        try:
            jobs.comparison(ready.id, ready.body)
        except HTTPException as error:
            errors.append(error)
        finally:
            doc_context.reset_current_doc(token)
            finished.set()
    thread = Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5)
        jobs.inspect(ready.id, cancel=True)
        assert finished.wait(5)
        assert closed.is_set() and errors[0].detail["code"] == "cancelled"
        assert jobs._slot.acquire(blocking=False)
        jobs._slot.release()
    finally:
        ready.job.cancelled.set()
        thread.join(5)
        assert not thread.is_alive()
