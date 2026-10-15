"""Strict publication uses host admission, never worker/saved authority labels."""

from threading import Event, Thread
from time import monotonic
from uuid import uuid4
from weakref import ref

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import part_batch_evaluation, part_evaluation_jobs as jobs, state
from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_history_verification import _slot
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Annotation, Design
from backend.core.part_history_contract import assess_part_history


@pytest.fixture
def document(monkeypatch):
    doc = f"__strict_jobs__{uuid4()}"
    token = set_current_doc(doc)
    previous = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(
        default_mode=previous.default_mode, document_modes={**previous.document_modes, doc: "registered_only"}))
    source = state.create_empty_part("Registered only", "HONEYCOMB")
    before = set(jobs._jobs)
    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", True)
    try:
        yield doc, source, state.revision()
    finally:
        with jobs._lock:
            for identity in set(jobs._jobs) - before:
                jobs._jobs.pop(identity)
        state.configure_part_publication_policy(previous)
        state.drop_doc(doc)
        reset_current_doc(token)


def body(source, revision, *, identity=None, diameter=10.):
    return {"operation": "batch", "batch": {"batch_version": 1,
        "expected_design_id": source.id, "expected_revision": revision,
        "commands": [{"kind": "nanoparticle-create", "version": 1,
            "params": {"nanoparticle_id": identity or str(uuid4()), "diameter_nm": diameter}}]}}


def install_worker(monkeypatch, *, on_start=None):
    calls, received = [], []

    class Worker:
        def __init__(self, source, operation):
            calls.append("construct")
            self.source, self.operation = source, operation
            received.append(operation)

        def start(self):
            calls.append("start")
            if on_start:
                on_start()

        def wait(self, _timeout):
            return True

        def result(self):
            calls.append("evaluate")
            return evaluate(self.source, self.operation)

        def is_alive(self):
            return False

        def close(self):
            calls.append("close")

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    return calls, received


def test_fifth_capture_value_is_private_and_old_three_four_shapes_remain(document):
    doc, source, revision = document
    ordinary = state.capture_design_for_evaluation({"operation": "verify"})
    fourth = state.capture_design_for_evaluation({"operation": "verify"}, include_session_identity=True)
    fifth = state.capture_design_for_evaluation({"operation": "verify"}, include_admission=True)
    assert len(ordinary) == 3 and len(fourth) == 4 and len(fifth) == 5
    context = permits.admission_context(fifth[4])
    assert (context.doc_id, context.source(), context.source_revision) == (doc, source, revision)
    assert context.session_identity == fourth[3] == fifth[3]
    assert context.operation == "verify" and context.policy_generation == state.part_publication_policy().generation
    assert "policy_generation" not in source.model_dump_json()


@pytest.mark.parametrize("operation", ["edit", "delete", "append", "repair", "selection"])
def test_unsupported_strict_evaluation_refuses_before_capture(document, monkeypatch, operation):
    from backend.api import part_evaluation_capture
    from tests.test_part_evaluation_admission import request

    _doc, source, revision = document
    monkeypatch.setattr(part_evaluation_capture, "capture_for_evaluation",
        lambda *_a, **_k: pytest.fail("Unsupported operation captured a source"))
    with pytest.raises(HTTPException) as error:
        jobs.start(request(operation, source, revision))
    assert error.value.status_code == 403 and error.value.detail["code"] == "construction_policy"
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_host_policy_does_not_override_disabled_public_batch_gate(document, monkeypatch):
    _doc, source, revision = document
    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", False)
    with pytest.raises(HTTPException) as error:
        jobs.start(body(source, revision))
    assert error.value.status_code == 422 and error.value.detail["code"] == "registered_batch_unavailable"
    assert state.get_design_with_revision() == (source, revision) and state.undo_depth() == 0


def test_strict_batch_is_editable_native_composition_and_one_commit_without_repeat(document, monkeypatch):
    _doc, source, revision = document
    calls, received = install_worker(monkeypatch)
    identity = jobs.start(body(source, revision))["job_id"]
    result = jobs.inspect(identity)["result"]
    assert result["status"] == "ready" and "candidate" not in result
    assert result["source_assessment"]["status"] == "verified"
    assert result["batch"]["candidate_replay_verified"] is False
    assert "admission" not in received[0] and "policy_generation" not in received[0]["header"]
    assert state.get_design_with_revision() == (source, revision)
    committed = jobs.commit(identity)
    assert committed["revision"] == revision + 1 and state.undo_depth() == 1
    assert jobs.commit(identity)["revision"] == committed["revision"]
    assert calls == ["construct", "start", "evaluate", "close"]
    published = state.get_or_404()
    assert len(published.feature_log) == 1 and published.feature_log[0].op_kind == "nanoparticle-create"
    cold = assess_part_history(Design.from_json(published.to_json()), execute=execute, dependencies=dependencies)
    assert cold["status"] == "verified"
    # Recovery undo remains explicitly unsupported in this first strict profile.
    with pytest.raises(HTTPException) as error:
        state.undo()
    assert error.value.status_code == 403 and state.get_or_404() is published


def test_verify_is_allowed_but_remains_nonpublishing(document, monkeypatch):
    _doc, source, revision = document
    install_worker(monkeypatch)
    identity = jobs.start({"operation": "verify"})["job_id"]
    assert jobs.inspect(identity)["result"]["status"] == "verified"
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state.get_design_with_revision() == (source, revision) and state.undo_depth() == 0


def test_policy_generation_revokes_ready_and_committed_handles(document, monkeypatch):
    _doc, source, revision = document
    install_worker(monkeypatch)
    identity = jobs.start(body(source, revision))["job_id"]
    state.configure_part_publication_policy(policy.current_configuration())
    assert jobs.inspect(identity)["stale"]
    assert jobs.inspect(identity)["result"]["issues"][-1]["code"] == "policy_changed"
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.detail["code"] == "policy_changed"
    assert state.get_design_with_revision() == (source, revision)
    second = jobs.start(body(source, revision))["job_id"]
    committed = jobs.commit(second)
    state.configure_part_publication_policy(policy.current_configuration())
    assert jobs.inspect(second)["stale"]
    with pytest.raises(HTTPException) as error:
        jobs.commit(second)
    assert error.value.detail["code"] == "policy_changed"
    assert state.revision() == committed["revision"] and state.undo_depth() == 1


def test_policy_change_stops_running_worker_and_releases_admission(document, monkeypatch):
    _doc, source, revision = document
    calls, _received = install_worker(monkeypatch,
        on_start=lambda: state.configure_part_publication_policy(policy.current_configuration()))
    identity = jobs.start(body(source, revision))["job_id"]
    assert calls == ["construct", "start", "close"]
    assert jobs.inspect(identity)["result"]["issues"][0]["code"] == "policy_changed"
    assert state.get_design_with_revision() == (source, revision) and state.undo_depth() == 0
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_policy_change_during_decode_blocks_before_final_publication(document, monkeypatch):
    _doc, source, revision = document
    install_worker(monkeypatch)
    identity = jobs.start(body(source, revision))["job_id"]
    decode = Design.model_validate

    def changed(*args, **kwargs):
        candidate = decode(*args, **kwargs)
        state.configure_part_publication_policy(policy.current_configuration())
        return candidate

    monkeypatch.setattr(Design, "model_validate", changed)
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.detail["code"] == "policy_changed"
    assert state.get_design_with_revision() == (source, revision) and state.undo_depth() == 0


@pytest.mark.parametrize("forged", [None, {}, "worker-claim"])
def test_ready_worker_json_cannot_supply_missing_private_admission(document, monkeypatch, forged):
    doc, source, revision = document
    identity = str(uuid4())
    job = jobs.EvaluationJob(doc, ref(source), revision, created=monotonic(), status="complete",
        admitted_operation="batch", session_identity=state._sessions[doc].identity,
        admission=forged, request_sha256="a" * 64,
        result={"status": "ready", "candidate": source.model_dump(mode="json"), "issues": [],
            "source_assessment": {"status": "verified"}, "admission": "worker-claim"})
    jobs._jobs[identity] = job
    monkeypatch.setattr(Design, "model_validate", lambda *_a, **_k: pytest.fail("Unadmitted candidate decoded"))
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.detail["code"] == "invalid_evaluation_admission"


def test_admission_for_another_request_cannot_authorize_a_retained_candidate(document, monkeypatch):
    _doc, source, revision = document
    install_worker(monkeypatch)
    first = jobs.start(body(source, revision, diameter=10.))["job_id"]
    second = jobs.start(body(source, revision, diameter=12.))["job_id"]
    jobs._jobs[first].admission = jobs._jobs[second].admission
    with pytest.raises(HTTPException) as error:
        jobs.commit(first)
    assert error.value.detail["code"] == "invalid_evaluation_admission"
    assert state.get_design_with_revision() == (source, revision)


def test_request_ownership_rejects_dispatch_mutation_but_detaches_callers_alias(document, monkeypatch):
    _doc, source, revision = document
    calls, _received = install_worker(monkeypatch)
    held = []
    monkeypatch.setattr(jobs, "_submit", lambda *args: held.append(args))
    original = body(source, revision)
    identity = jobs.start(original)["job_id"]
    original["batch"]["commands"][0]["params"]["diameter_nm"] = 99.
    jobs._run(*held.pop())
    assert jobs._jobs[identity].result["candidate"]["nanoparticles"][0]["diameter_nm"] == 10.
    assert calls.count("evaluate") == 1

    second = jobs.start(body(source, revision))["job_id"]
    args = held.pop()
    args[2]["request"]["batch"]["commands"][0]["params"]["diameter_nm"] = 99.
    jobs._run(*args)
    assert jobs.inspect(second)["result"]["issues"][0]["code"] == "invalid_evaluation_admission"
    assert calls.count("evaluate") == 1 and state.get_design_with_revision() == (source, revision)


def test_compatibility_batch_rechecks_complete_source_scope_at_publication(document, monkeypatch):
    _doc, source, revision = document
    state.configure_part_publication_policy(policy.HostPolicyConfiguration())
    install_worker(monkeypatch)
    identity = jobs.start(body(source, revision))["job_id"]
    source.annotations.append(Annotation(text="Retained source changed through a legacy alias"))
    before = source.model_dump_json()
    monkeypatch.setattr(state, "_snapshot_copy", lambda *_a: pytest.fail("Unsupported source was copied"))
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 422 and error.value.detail["code"] == "unsupported_batch_publication_scope"
    assert state.get_design_with_revision() == (source, revision)
    assert source.model_dump_json() == before and state.undo_depth() == 0


@pytest.mark.parametrize("field", ["policy", "policy_generation", "admission", "request_sha256", "publication_permit"])
def test_public_job_schema_cannot_supply_host_authority(field):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "verify", field: "trusted"})


def test_cancel_and_commit_serialize_at_the_existing_job_lock(document, monkeypatch):
    doc, source, revision = document
    install_worker(monkeypatch)
    identity = jobs.start(body(source, revision))["job_id"]
    entered, attempted, done = Event(), Event(), Event()
    outputs, errors = [], []
    snapshot = state._snapshot_copy

    def during_snapshot(value):
        entered.set()
        assert attempted.wait(5)
        assert not jobs._jobs[identity].cancelled.is_set()
        return snapshot(value)

    def cancel():
        token = set_current_doc(doc)
        try:
            assert entered.wait(5)
            attempted.set()
            outputs.append(jobs.inspect(identity, cancel=True))
        except BaseException as error:
            errors.append(error)
        finally:
            reset_current_doc(token)
            done.set()

    monkeypatch.setattr(state, "_snapshot_copy", during_snapshot)
    thread = Thread(target=cancel)
    thread.start()
    try:
        committed = jobs.commit(identity)
    finally:
        assert done.wait(5)
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert outputs[0]["status"] == "committed" and not jobs._jobs[identity].cancelled.is_set()
    assert committed["revision"] == revision + 1 and state.undo_depth() == 1
