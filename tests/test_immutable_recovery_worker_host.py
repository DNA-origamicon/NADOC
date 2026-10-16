"""Tests-first recovery handoff: exact worker observation, never saved authority.

One real spawned recovery uses a small pytest-owned gold cache record. Remaining
cases control transport timing on actual RecoveryWorker instances; their normal
result and revision-taking methods are never replaced with a seal factory.
"""

from collections import OrderedDict
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from multiprocessing.shared_memory import SharedMemory
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api import doc_context, part_evaluation_jobs as jobs, session_cache, state
from backend.api import part_immutable_recovery as recovery
from backend.api import part_immutable_recovery_inputs as inputs
from backend.api import part_immutable_recovery_worker as transport
from backend.api import part_immutable_revision as revisions
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api import part_verification_jobs as supervision
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_persistence import StrictPersistence
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from tests.test_immutable_recovery_worker import _design


@pytest.fixture
def document(tmp_path, monkeypatch):
    # All fallible ordinary setup precedes changing request/global state.
    doc = "__recovery_worker_host__" + uuid4().hex
    previous = policy.current_configuration()
    owner = StrictPersistence(tmp_path)
    original = revisions.prepare_revision(_design(annotations=False))
    owner.cache.write(owner.reserve_empty(doc), original)
    read_pending = owner.read_pending
    reads = []

    def observed_read(identity):
        value = read_pending(identity)
        reads.append(value)
        return value

    with ExitStack() as cleanup:
        token = doc_context.set_current_doc(doc)
        cleanup.callback(doc_context.reset_current_doc, token)
        cleanup.callback(host.configure, previous)
        cleanup.callback(state.drop_doc, doc)
        host.configure(policy.HostPolicyConfiguration(default_mode=previous.default_mode,
            document_modes={**previous.document_modes, doc: "registered_only"}))
        monkeypatch.setattr(session_cache, "_strict_persistence", owner)
        monkeypatch.setattr(jobs, "_jobs", OrderedDict())
        monkeypatch.setattr(recovery, "_submit", recovery._run)
        monkeypatch.setattr(owner, "read_pending", observed_read)
        yield SimpleNamespace(doc=doc, owner=owner, original=original, reads=reads,
            read_pending=read_pending, cleanup=cleanup, workers=[])
    assert _slot.acquire(blocking=False), "Recovery leaked its shared native-operation slot"
    _slot.release()


def start():
    response = recovery.start({"expected_revision": 0})
    return response["job_id"], jobs._jobs[response["job_id"]]


def assert_no_candidate(document, job, code=None):
    assert job.status == "complete"
    assert job.result["status"] != "ready", job.result
    if code is not None:
        assert code in {issue["code"] for issue in job.result["issues"]}, job.result
    assert job.candidate is job.qualification is job.lease is None
    current = state._sessions.get(document.doc)
    assert current is None or current.design is None
    assert document.read_pending(document.doc).payload == document.original.payload


def controlled_worker(document, monkeypatch, *, on_construct=None, on_start=None, on_close=None,
                      close_failure=False):
    """Control process events, retaining real ticket/result/completion validation."""
    events = SimpleNamespace(constructed=0, started=0, results=0, closed=0, take=0)

    def construct(ticket):
        worker = transport.RecoveryWorker(ticket)
        document.workers.append(worker)
        document.cleanup.callback(VerificationWorker.close, worker)
        # No process is started in these deterministic host-race cases. The
        # report comes from the existing pure child implementation, not from
        # a test-created proof label or a manufactured completion observation.
        parts, _binding = transport.encode_input(ticket)
        report = transport.evaluate_payload(b"".join(parts))
        assert report["result"]["status"] == "verified", report
        worker._process.close()
        worker._process = SimpleNamespace(pid=None, exitcode=0, is_alive=lambda: False, close=lambda: None)
        events.constructed += 1

        def begin():
            events.started += 1
            if on_start is not None:
                on_start()

        worker.start = begin
        worker.wait = lambda _timeout: True
        worker._read_result = lambda: deepcopy(report)
        result, close, take = worker.result, worker.close, worker.take_revision

        def observed_result():
            value = result()
            events.results += 1
            return value

        def observed_close():
            close()
            events.closed += 1
            if events.closed == 1:
                if on_close is not None:
                    on_close()
                if close_failure:
                    raise RuntimeError("Injected cleanup failure after transport release")

        def observed_take(*args, **kwargs):
            events.take += 1
            return take(*args, **kwargs)

        worker.result, worker.close, worker.take_revision = observed_result, observed_close, observed_take
        if on_construct is not None:
            on_construct()
        return worker

    # Before the stage-two integration this proposed import seam is unused;
    # tests must fail on missing behavior, not collection or monkeypatch setup.
    monkeypatch.setattr(recovery, "RecoveryWorker", construct, raising=False)
    return events


def test_real_spawned_recovery_keeps_exact_read_bytes_and_lease_without_parent_preparation(document, monkeypatch):
    expected = asdict(revisions.revision_metadata(document.original))
    workers, names, parent_calls = [], [], []

    def observed_worker(ticket):
        worker = transport.RecoveryWorker(ticket)
        workers.append(worker)
        names.extend(buffer.name for buffer in worker._buffers)
        document.cleanup.callback(VerificationWorker.close, worker)
        return worker

    def forbidden(*_args, **_kwargs):
        parent_calls.append(True)
        raise AssertionError("Recovery decoded or re-prepared its original source in the parent")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "RecoveryWorker", observed_worker, raising=False)
        for module, name in ((recovery, "prepare_stored"), (inputs, "prepare_stored"),
                (revisions, "prepare_revision"), (revisions, "_decoded_exact"),
                (revisions, "_canonical_payload"), (revisions, "digest"),
                (Design, "model_validate"), (Design, "model_validate_json")):
            patch.setattr(module, name, forbidden, raising=False)
        identity, job = start()
        assert job.result["status"] == "ready", job.result
        assert len(workers) == len(document.reads) == 1
        assert workers[0]._closed and workers[0]._process_closed
        assert job.candidate.payload is document.reads[0].payload
        assert job.lease is document.reads[0].lease
        assert asdict(revisions.revision_metadata(job.candidate)) == expected
        assert job.result["restoration_assessment"]["status"] == "verified"
        assert "candidate" not in jobs.inspect(identity)["result"]
        assert state._sessions[document.doc].design is None
        first = jobs.commit(identity)
        assert jobs.commit(identity)["revision"] == first["revision"] == 1
        assert state._sessions[document.doc].design.payload is document.reads[0].payload
        assert not state._sessions[document.doc].history and not state._sessions[document.doc].redo
        assert parent_calls == []
    assert document.read_pending(document.doc).payload == document.original.payload
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)


def test_controlled_handoff_uses_real_result_validation_and_seals_only_after_close(document, monkeypatch):
    events = controlled_worker(document, monkeypatch)
    _identity, job = start()
    assert job.result["status"] == "ready", job.result
    assert events.constructed == events.started == events.results == events.closed == events.take == 1
    assert document.workers[0]._closed and document.workers[0]._process_closed
    assert job.candidate.payload is document.reads[0].payload
    assert job.lease is document.reads[0].lease
    recovery.require_qualification(job.qualification, job.admission, job.candidate)


@pytest.mark.parametrize("change,code", [("cancel", "cancelled"), ("session_aba", "source_changed"),
    ("policy", "policy_changed"), ("storage_owner", "strict_cache_changed")])
def test_post_result_context_change_prevents_revision_take_and_qualification(
    document, monkeypatch, tmp_path, change, code,
):
    replacement_path = tmp_path / "replacement"
    replacement_path.mkdir()
    replacement_owner = StrictPersistence(replacement_path)

    def alter():
        job = next(iter(jobs._jobs.values()))
        if change == "cancel":
            job.cancelled.set()
        elif change == "session_aba":
            previous = state._sessions[document.doc]
            state.drop_doc(document.doc)
            with state._lock:
                current = state._session()
            assert current is not previous and current.identity != previous.identity
            assert current.revision == previous.revision == 0 and current.design is None
        elif change == "policy":
            host.configure(policy.current_configuration())
        else:
            monkeypatch.setattr(session_cache, "_strict_persistence", replacement_owner)

    events = controlled_worker(document, monkeypatch)
    supervise = recovery.supervise

    def alter_after_supervision(job, *args, **kwargs):
        result = supervise(job, *args, **kwargs)
        assert result["status"] == "verified" and document.workers[0]._closed
        alter()  # After the shared supervisor's final context checkpoint.
        return result

    monkeypatch.setattr(recovery, "supervise", alter_after_supervision)
    _identity, job = start()
    assert events.results == events.closed == 1 and events.take == 0
    assert_no_candidate(document, job, code)


def test_original_deadline_includes_record_read_before_worker_creation(document, monkeypatch):
    clock = SimpleNamespace(now=100.)
    monkeypatch.setattr(recovery, "monotonic", lambda: clock.now)
    monkeypatch.setattr(supervision, "monotonic", lambda: clock.now)
    read = document.owner.read_pending

    def slow_read(identity):
        value = read(identity)
        clock.now += 5.001
        return value

    monkeypatch.setattr(document.owner, "read_pending", slow_read)
    events = controlled_worker(document, monkeypatch)
    _identity, job = start()
    assert recovery.TIME_BUDGET == 5.0
    assert events.constructed == events.started == events.take == 0
    assert_no_candidate(document, job, "time_limit")


@pytest.mark.parametrize("phase", ["construct", "start", "cleanup", "handoff"])
def test_original_deadline_is_not_restarted_after_read_or_worker_start(document, monkeypatch, phase):
    clock, remaining = SimpleNamespace(now=100.), []
    monkeypatch.setattr(recovery, "monotonic", lambda: clock.now)
    monkeypatch.setattr(supervision, "monotonic", lambda: clock.now)
    read, supervise = document.owner.read_pending, recovery.supervise

    def prior_read(identity):
        value = read(identity)
        clock.now += 2.0
        return value

    def elapsed():
        clock.now += 3.001

    def observed_supervise(job, source, worker_factory, seconds, **kwargs):
        remaining.append(seconds)
        result = supervise(job, source, worker_factory, seconds, **kwargs)
        if phase == "handoff":
            assert result["status"] == "verified"
            elapsed()
        return result

    monkeypatch.setattr(document.owner, "read_pending", prior_read)
    monkeypatch.setattr(recovery, "supervise", observed_supervise)
    events = controlled_worker(document, monkeypatch,
        on_construct=elapsed if phase == "construct" else None,
        on_start=elapsed if phase == "start" else None,
        on_close=elapsed if phase == "cleanup" else None)
    _identity, job = start()
    assert remaining == [pytest.approx(3.0)] and recovery.TIME_BUDGET == 5.0
    assert events.constructed == events.closed == 1 and events.take == 0
    assert events.started == (0 if phase == "construct" else 1)
    assert events.results == (1 if phase in {"cleanup", "handoff"} else 0)
    assert_no_candidate(document, job, "time_limit")


def test_cleanup_failure_after_verified_result_never_takes_or_qualifies_revision(document, monkeypatch):
    events = controlled_worker(document, monkeypatch, close_failure=True)
    _identity, job = start()
    assert events.results == 1 and events.closed == 2 and events.take == 0
    assert document.workers[0]._closed and document.workers[0]._process_closed
    assert_no_candidate(document, job, "worker_cleanup_error")


def test_eviction_after_supervision_cannot_resurrect_retained_candidate(document, monkeypatch):
    events = controlled_worker(document, monkeypatch)
    supervise, evicted = recovery.supervise, []

    def remove_after_cleanup(job, *args, **kwargs):
        result = supervise(job, *args, **kwargs)
        assert result["status"] == "verified" and document.workers[0]._closed
        # Model the existing bounded catalog eviction in the short interval
        # after supervise releases its slot and before host final retention.
        with jobs._lock:
            identity = next(key for key, value in jobs._jobs.items() if value is job)
            evicted.append(jobs._jobs.pop(identity))
            jobs._discard_candidate(job)
        return result

    monkeypatch.setattr(recovery, "supervise", remove_after_cleanup)
    response = recovery.start({"expected_revision": 0})
    assert len(evicted) == events.results == 1
    assert response["job_id"] not in jobs._jobs
    assert_no_candidate(document, evicted[0])
