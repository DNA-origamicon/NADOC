"""Strict jobs retain sealed sources while private work stays outside state lock."""

from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, part_batch_evaluation, part_evaluation_jobs as jobs, state
from backend.api import part_immutable_evaluation as immutable
from backend.api import part_immutable_revision as revisions, part_publication_host as host
from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_history_verification import _slot
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import CaptureLimit
from tests.test_part_registered_batch import gold, request as batch_request


@pytest.fixture
def document(monkeypatch):
    doc = f"__immutable_jobs__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    previous = policy.current_configuration()
    host.configure(policy.HostPolicyConfiguration(default_mode=previous.default_mode,
        document_modes={**previous.document_modes, doc: "registered_only"}))
    source, _revision = host.create_immutable_empty("Strict evaluation")
    existing = set(jobs._jobs)
    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", True)
    try:
        yield doc, source
    finally:
        with jobs._lock:
            for identity in set(jobs._jobs) - existing:
                jobs._jobs.pop(identity)
        state.drop_doc(doc)
        host.configure(previous)
        doc_context.reset_current_doc(token)


def body(source):
    return {"operation": "batch", "batch": batch_request(gold(),
        expected_design_id=revisions.revision_metadata(source).design_id, expected_revision=state.revision())}


def unlocked():
    assert state._lock.acquire(blocking=False), "Private molecular work held the shared state lock"
    state._lock.release()


def slot_available():
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.fixture
def immediate(document, monkeypatch):
    class Worker:
        def __init__(self, design, operation):
            self.design, self.operation = design, operation

        def start(self):
            unlocked()

        def wait(self, timeout):
            return True

        def is_alive(self):
            return False

        def result(self):
            return evaluate(self.design, self.operation)

        def close(self):
            pass

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    return document


@pytest.mark.parametrize("admission,identity", [(False, False), (False, True), (True, False)])
def test_owned_capture_preserves_actual_handle_and_outside_lock_work(document, monkeypatch, admission, identity):
    doc, source = document
    from backend.core import part_capture_inputs

    seen = []
    original_decode, original_capture = immutable.materialize_revision, part_capture_inputs.visit_inputs

    def decode(value):
        unlocked()
        assert value is source
        seen.append("decode")
        return original_decode(value)

    def capture(value, **kwargs):
        unlocked()
        assert type(value) is Design
        seen.append("capture")
        return original_capture(value, **kwargs)

    monkeypatch.setattr(immutable, "materialize_revision", decode)
    monkeypatch.setattr(part_capture_inputs, "visit_inputs", capture)
    result = state.capture_design_for_evaluation(EvaluationRequest.model_validate(body(source)),
        include_admission=admission, include_session_identity=identity)
    assert result[0] is state._sessions[doc].design is source
    assert type(result[1]) is Design and seen == ["decode", "capture"]
    result[1].metadata.name = "private edit"
    assert revisions.revision_metadata(source).name == "Strict evaluation"
    assert len(result) == (5 if admission else 4 if identity else 3)
    if admission:
        context = permits.admission_context(result[4])
        assert context.source() is source and context.session_identity == state._sessions[doc].identity


@pytest.mark.parametrize("change", ["revision", "design", "gate", "operation", "policy"])
def test_initial_context_refuses_before_materialization(document, monkeypatch, change):
    doc, source = document
    value = body(source)
    if change == "revision":
        value["expected_revision"] = state.revision() + 1
        value["batch"]["expected_revision"] = value["expected_revision"]
    elif change == "design":
        value["batch"]["expected_design_id"] = "other"
    elif change == "gate":
        monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", False)
    elif change == "operation":
        value = {"operation": "append", "kind": "duplex-relax", "params": {}}
    monkeypatch.setattr(immutable, "materialize_revision", lambda value: pytest.fail("Refused request decoded source"))
    with pytest.raises(HTTPException):
        jobs.start(value, **({"expected_policy_generation": policy.resolve(doc).generation + 1} if change == "policy" else {}))
    assert state._sessions[doc].design is source and not jobs._jobs
    slot_available()


@pytest.mark.parametrize("change", ["close", "reopen", "revision", "source", "policy"])
def test_change_during_decode_refuses_before_job_admission(document, monkeypatch, change):
    doc, source = document
    original = immutable.materialize_revision
    replacement = revisions.prepare_revision(revisions.materialize_revision(source))
    prior_admissions = len(permits._admissions)

    def decode(value):
        result = original(value)
        unlocked()
        if change in {"close", "reopen"}:
            state.drop_doc(doc)
            if change == "reopen":
                with state._lock:
                    state._session()
        elif change == "policy":
            host.configure(policy.current_configuration())
        else:
            with state._lock:
                if change == "revision":
                    state._sessions[doc].revision += 1
                else:
                    state._sessions[doc].design = replacement
        return result

    monkeypatch.setattr(immutable, "materialize_revision", decode)
    monkeypatch.setattr(jobs, "_submit", lambda *args: pytest.fail("Stale source reached supervisor"))
    with pytest.raises(HTTPException) as error:
        jobs.start(body(source))
    assert error.value.status_code == 409
    assert len(permits._admissions) == prior_admissions and not jobs._jobs
    assert (doc in state._sessions) is (change != "close")
    slot_available()


def test_batch_commit_keeps_one_immutable_authority_and_exact_handle_undo(immediate, monkeypatch):
    doc, source = immediate
    before, payload = state.revision(), source.payload
    identity = jobs.start(body(source))["job_id"]
    assert jobs.inspect(identity)["result"]["status"] == "ready"
    assert jobs._jobs[identity].source() is source
    assert state._sessions[doc].design is source and source.payload == payload
    jobs._jobs[identity].result["candidate"]["annotations_enabled"] = False
    original = immutable.prepare_revision

    def prepare(candidate):
        unlocked()
        assert candidate.annotations_enabled is True  # carried from published source
        return original(candidate)

    monkeypatch.setattr(immutable, "prepare_revision", prepare)
    result = jobs.commit(identity)
    published = state._sessions[doc].design
    assert revisions.is_prepared_revision(published) and published is not source
    assert result["design_id"] == revisions.revision_metadata(source).design_id
    assert result["revision"] == before + 1
    assert list(state._sessions[doc].history) == [source] and not state._sessions[doc].redo
    assert jobs.commit(identity) == {"job_id": identity, "status": "committed", "revision": before + 1}
    assert revisions.materialize_revision(published).nanoparticles[0].diameter_nm == 10
    assert source.payload == payload and "candidate" not in jobs._jobs[identity].result
    slot_available()


@pytest.mark.parametrize("change", ["cancel", "expiry", "policy", "close", "source", "failure"])
def test_candidate_preparation_failure_cannot_publish_or_consume_source(immediate, monkeypatch, change):
    doc, source = immediate
    identity = jobs.start(body(source))["job_id"]
    job, revision = jobs._jobs[identity], state.revision()
    original = immutable.prepare_revision

    def prepare(candidate):
        unlocked()
        if change == "failure":
            raise ValueError("injected private preparation failure")
        result = original(candidate)
        if change == "cancel":
            job.cancelled.set()
        elif change == "expiry":
            job.created = monotonic() - jobs.RESULT_TTL - 1
        elif change == "policy":
            host.configure(policy.current_configuration())
        elif change == "close":
            state.drop_doc(doc)
        else:
            replacement = revisions.prepare_revision(revisions.materialize_revision(source))
            with state._lock:
                state._sessions[doc].design = replacement
        return result

    monkeypatch.setattr(immutable, "prepare_revision", prepare)
    with pytest.raises((HTTPException, ValueError)):
        jobs.commit(identity)
    if change != "close":
        assert state._sessions[doc].revision == revision and not state._sessions[doc].history
    assert job.committed_revision is None
    slot_available()


def test_verify_on_immutable_source_remains_nonpublishing(immediate):
    doc, source = immediate
    identity = jobs.start({"operation": "verify", "expected_revision": state.revision()})["job_id"]
    result = jobs.inspect(identity)["result"]
    assert result["status"] == "verified" and "candidate" not in result
    with pytest.raises(HTTPException, match="nonpublishing"):
        jobs.commit(identity)
    assert state._sessions[doc].design is source and not state._sessions[doc].history


def test_real_spawned_batch_then_cold_verify_keeps_immutable_publication(document, monkeypatch):
    doc, source = document
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    identity = jobs.start(body(source))["job_id"]
    result = jobs.inspect(identity)["result"]
    assert result["status"] == "ready", result
    jobs.commit(identity)
    published = state._sessions[doc].design
    assert revisions.is_prepared_revision(published)
    identity = jobs.start({"operation": "verify", "expected_revision": state.revision()})["job_id"]
    result = jobs.inspect(identity)["result"]
    assert result["status"] == "verified", result
    assert state._sessions[doc].design is published


@pytest.mark.parametrize("failure,status", [
    (CaptureLimit("retained candidate exceeds budget"), 413),
    (CommandContractError("candidate outside storage scope", code="unsupported_batch_publication_scope"), 422),
])
def test_preparation_refusal_is_actionable_and_preserves_retryable_job(immediate, monkeypatch, failure, status):
    doc, source = immediate
    identity = jobs.start(body(source))["job_id"]

    def refuse(_candidate):
        raise failure

    monkeypatch.setattr(immutable, "prepare_revision", refuse)
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == status
    assert state._sessions[doc].design is source
    assert jobs._jobs[identity].committed_revision is None and jobs._jobs[identity].result["candidate"]
    slot_available()


def test_strict_http_reuses_jobs_and_never_returns_a_mutable_source(immediate):
    from fastapi.testclient import TestClient
    from backend.api.part_strict_http import StrictPartDispatch
    from tests.test_part_strict_http import forbidden_app, JOBS, REVISION

    doc, source = immediate
    with TestClient(StrictPartDispatch(forbidden_app), headers={"X-NADOC-Doc": doc}) as client:
        response = client.post(JOBS, json=body(source))
        assert response.status_code == 202, response.text
        identity = response.json()["job_id"]
        result = client.get(f"{JOBS}/{identity}").json()
        assert result["result"]["status"] == "ready" and "candidate" not in result["result"]
        published = client.post(f"{JOBS}/{identity}/commit")
        assert published.status_code == 200, published.text
        assert client.get(REVISION).json()["revision"] == published.json()["revision"]
        assert client.get("/api/design").status_code == 403
        assert "design" not in published.json()
    assert revisions.is_prepared_revision(state._sessions[doc].design)
