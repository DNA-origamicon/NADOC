"""Explicit strict recovery uses owned temporary bytes and the existing job slot."""

from collections import OrderedDict
from contextlib import ExitStack
from dataclasses import replace
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, part_evaluation_jobs as jobs, session_cache, state
from backend.api import part_immutable_recovery as recovery
from backend.api import part_immutable_recovery_inputs as inputs
from backend.api import part_immutable_recovery_worker as transport
from backend.api import part_immutable_revision as revisions
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_persistence import StrictPersistence
from backend.core.part_history_contract import create_empty_part
from backend.core.models import Design
from tests.test_immutable_recovery_worker_lifecycle import _controlled_output


@pytest.fixture
def document(tmp_path, monkeypatch):
    doc = "__recovery__" + uuid4().hex
    previous = policy.current_configuration()
    owner = StrictPersistence(tmp_path)
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
        yield doc, owner
    assert _slot.acquire(blocking=False), "Recovery leaked the shared native worker slot"
    _slot.release()


@pytest.fixture
def immediate(document, monkeypatch):
    with ExitStack() as cleanup:
        def construct(ticket):
            worker = transport.RecoveryWorker(ticket)
            cleanup.callback(worker.close)
            parts, _binding = transport.encode_input(ticket)
            report = transport.evaluate_payload(b"".join(parts))
            # Control only process timing/output. Preparation and proof use the
            # actual child implementation; result, close and take_revision stay
            # real, including binding validation and private seal ownership.
            _controlled_output(worker, report)

            def start():
                assert state._lock.acquire(blocking=False)
                state._lock.release()

            worker.start = start
            worker.wait = lambda _timeout: True
            return worker

        monkeypatch.setattr(recovery, "RecoveryWorker", construct, raising=False)
        yield document


def stored(document):
    doc, owner = document
    source = revisions.prepare_revision(create_empty_part("Pending native part", "HONEYCOMB"))
    owner.cache.write(owner.reserve_empty(doc), source)
    return source


def start():
    response = recovery.start({"expected_revision": 0})
    return response["job_id"], jobs._jobs[response["job_id"]]


def test_status_is_pending_not_proof_and_never_creates_session(document, monkeypatch):
    doc, owner = document
    assert recovery.status()["record"]["state"] == "absent"
    source = stored(document)
    monkeypatch.setattr(inputs, "prepare_stored", lambda *_a, **_k: pytest.fail("Status decoded a Design"))
    report = recovery.status()
    assert report["doc_id"] == doc and report["revision"] == 0
    assert report["record"] == {"state": "pending", "storage_version": 1, "payload_bytes": len(source.payload)}
    assert report["assessment"] == "unverified" and doc not in state._sessions
    assert owner.read_pending(doc).payload == source.payload


@pytest.mark.parametrize("body", [{}, {"expected_revision": True}, {"expected_revision": -1},
    {"expected_revision": "0"}, {"expected_revision": 0, "candidate": {}},
    {"expected_revision": 0, "verified": True}, {"expected_revision": 0, "doc_id": "other"}])
def test_restore_dto_refuses_authority_payload_and_bad_revision_before_session(document, body):
    doc, _owner = document
    with pytest.raises((ValueError, HTTPException)):
        recovery.start(body)
    assert doc not in state._sessions


def test_restore_requires_host_storage_and_busy_admission_precedes_record_read(document, monkeypatch):
    doc, owner = document
    monkeypatch.setattr(owner, "read_pending", lambda *_a: pytest.fail("Busy restore read a record"))
    assert _slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as error:
            recovery.start({"expected_revision": 0})
        assert error.value.status_code == 429 and doc not in state._sessions
    finally:
        _slot.release()
    monkeypatch.setattr(session_cache, "_strict_persistence", None)
    with pytest.raises(HTTPException) as error:
        recovery.start({"expected_revision": 0})
    assert error.value.status_code == 503 and doc not in state._sessions


def test_qualified_restore_uses_same_job_owner_and_publishes_once_without_old_undo(immediate):
    doc, owner = immediate
    source = stored(immediate)
    identity, job = start()
    report = jobs.inspect(identity)
    assert report["result"]["status"] == "ready"
    assert report["result"]["restoration_assessment"]["status"] == "verified"
    assert "candidate" not in report["result"] and state._sessions[doc].design is None
    assert type(job.candidate) is revisions.StrictPartRevision and job.candidate.payload == source.payload
    first = jobs.commit(identity)
    assert jobs.commit(identity)["revision"] == first["revision"] == 1
    assert state._sessions[doc].design.payload == source.payload
    assert not state._sessions[doc].history and not state._sessions[doc].redo
    assert job.candidate is None and owner.write_if_immutable(doc) == 1


def test_saved_geometry_without_feature_inputs_cannot_forge_a_restore_receipt(immediate):
    from backend.api.part_nanoparticle_commands import build

    doc, owner = immediate
    raw = create_empty_part("Unsupported saved claim", "HONEYCOMB")
    raw = build("nanoparticle-create", raw, {"_proof_version": 1, "nanoparticle_version": 1,
        "nanoparticle_id": "unlogged", "diameter_nm": 5.0})
    candidate = revisions.prepare_revision(Design.model_validate_json(raw.model_dump_json()))
    owner.cache.write(owner.reserve_empty(doc), candidate)
    identity, job = start()
    assert jobs.inspect(identity)["result"]["status"] != "ready" and job.candidate is None
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None and owner.read_pending(doc).payload == candidate.payload


@pytest.mark.parametrize("change", ["close", "reopen", "policy", "cancel", "expire", "file"])
def test_restore_final_guards_preserve_pending_bytes(immediate, change):
    doc, owner = immediate
    source = stored(immediate)
    identity, job = start()
    if change in {"close", "reopen"}:
        state.drop_doc(doc)
        if change == "reopen":
            with state._lock:
                state._session()
    elif change == "policy":
        host.configure(policy.current_configuration())
    elif change == "cancel":
        jobs.inspect(identity, cancel=True)
    elif change == "expire":
        job.created = monotonic() - jobs.RESULT_TTL - 1
    else:
        record = owner.read_pending(doc)
        owner.cache.write(record.lease, source)  # Equal bytes still have a new file identity.
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert doc not in state._sessions or state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == source.payload


def test_forged_ready_result_has_no_host_observed_qualification(immediate):
    doc, _owner = immediate
    stored(immediate)
    identity, job = start()
    job.qualification = None
    job.result = {"status": "ready", "restoration_assessment": {"status": "verified"}, "issues": []}
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None


def test_publication_rollback_keeps_file_and_retryable_exact_candidate(immediate, monkeypatch):
    doc, owner = immediate
    source = stored(immediate)
    identity, job = start()
    candidate = job.candidate
    original = state._bump_revision

    def broken(session):
        original(session)
        raise RuntimeError("Injected post-bump failure")

    monkeypatch.setattr(state, "_bump_revision", broken)
    with pytest.raises(RuntimeError, match="post-bump"):
        jobs.commit(identity)
    assert state._sessions[doc].design is None and state._sessions[doc].revision == 0
    assert job.candidate is candidate and job.committed_revision is None
    assert doc not in owner._bindings and owner.read_pending(doc).payload == source.payload
    monkeypatch.setattr(state, "_bump_revision", original)
    assert jobs.commit(identity)["revision"] == 1


def test_policy_change_before_admission_does_not_reserve_session(document):
    doc, _owner = document
    generation = policy.resolve(doc).generation
    host.configure(policy.current_configuration())
    with pytest.raises(HTTPException) as error:
        recovery.start({"expected_revision": 0}, expected_policy_generation=generation)
    assert error.value.detail["code"] == "policy_changed" and doc not in state._sessions


def test_wrong_revision_and_nonempty_session_refuse_before_read(document, monkeypatch):
    doc, owner = document
    source, revision = host.create_immutable_empty()
    monkeypatch.setattr(owner, "read_pending", lambda *_a: pytest.fail("Invalid reservation read bytes"))
    with pytest.raises(HTTPException):
        recovery.start({"expected_revision": revision})
    assert state._sessions[doc].design is source


def test_preparation_refuses_mutated_manifest_and_keeps_exact_full_payload(document):
    from backend.core.part_command_errors import CommandContractError

    doc, owner = document
    stored(document)
    record = owner.read_pending(doc)
    with pytest.raises(CommandContractError):
        inputs.prepare_stored(replace(record, payload=record.payload + b" "))


@pytest.mark.parametrize("alter", ["duplicate", "nonfinite", "normalize", "saved_seal", "depth"])
def test_untrusted_payload_has_no_decode_or_saved_receipt_shortcut(document, alter):
    from hashlib import sha256
    import json
    from backend.core.part_command_errors import CommandContractError

    doc, owner = document
    stored(document)
    record = owner.read_pending(doc)
    if alter == "duplicate":
        payload = b'{"id":"duplicate",' + record.payload[1:]
    elif alter == "nonfinite":
        payload = b'{"id":NaN,' + record.payload[1:]
    elif alter == "saved_seal":
        payload = b'{"_seal":"verified","payload":"cached"}'
    elif alter == "depth":
        payload = b'{"value":' + b'[' * 70 + b'0' + b']' * 70 + b'}'
    else:
        data = json.loads(record.payload)
        data.pop("annotations_enabled")
        payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    manifest = replace(record.manifest, payload_bytes=len(payload), payload_sha256=sha256(payload).hexdigest())
    with pytest.raises(CommandContractError):
        inputs.prepare_stored(replace(record, payload=payload, manifest=manifest))


def test_poisoned_recovery_is_ignored_by_cold_proof_and_restored_recipe_stays_editable(immediate):
    from backend.api.part_recipe_edit import prepare_change
    from backend.api.part_proof_commands import dependencies, execute
    from tests.test_part_registered_batch import gold, prepare, request

    doc, owner = immediate
    design = prepare(body=request(gold()))["candidate"]
    entry = design.feature_log[0]
    entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    source = revisions.prepare_revision(Design.model_validate_json(design.model_dump_json()))
    owner.cache.write(owner.reserve_empty(doc), source)
    identity, _job = start()
    assert jobs.inspect(identity)["result"]["restoration_assessment"]["status"] == "verified"
    jobs.commit(identity)
    restored = revisions.materialize_revision(state._sessions[doc].design)
    from backend.core.part_verification_capture import capture
    result, _validation = prepare_change(restored, capture(restored), 0, lambda: None,
        params={**entry.params, "diameter_nm": 14.0}, executor=execute, dependency_resolver=dependencies)
    assert result.nanoparticles[0].diameter_nm == 14.0
    assert result.feature_log[0].id == entry.id
    assert owner.read_pending(doc).payload == source.payload


def test_close_during_read_never_recreates_reserved_session(immediate, monkeypatch):
    doc, owner = immediate
    stored(immediate)
    original = owner.read_pending

    def close(identity):
        value = original(identity)
        state.drop_doc(doc)
        return value

    monkeypatch.setattr(owner, "read_pending", close)
    identity, job = start()
    assert jobs.inspect(identity)["stale"] and job.candidate is None
    assert doc not in state._sessions


def test_cancel_before_preparation_reads_no_bytes(immediate, monkeypatch):
    _doc, owner = immediate
    stored(immediate)
    monkeypatch.setattr(owner, "read_pending", lambda *_a: pytest.fail("Cancelled recovery read bytes"))

    def cancel(job):
        job.cancelled.set()
        recovery._run(job)

    monkeypatch.setattr(recovery, "_submit", cancel)
    identity, job = start()
    assert job.candidate is None and jobs.inspect(identity)["result"]["issues"][0]["code"] == "cancelled"


def test_storage_owner_change_before_preparation_reads_no_bytes(immediate, monkeypatch, tmp_path):
    doc, owner = immediate
    source = stored(immediate)
    replacement_workspace = tmp_path / "replacement"
    replacement_workspace.mkdir()
    original_read = owner.read_pending
    monkeypatch.setattr(owner, "read_pending", lambda *_a: pytest.fail("Superseded storage owner read bytes"))

    def replace_owner(job):
        monkeypatch.setattr(session_cache, "_strict_persistence", StrictPersistence(replacement_workspace))
        recovery._run(job)

    monkeypatch.setattr(recovery, "_submit", replace_owner)
    identity, job = start()
    assert jobs.inspect(identity)["result"]["issues"][0]["code"] == "strict_cache_changed"
    assert job.candidate is None and state._sessions[doc].design is None
    assert original_read(doc).payload == source.payload


@pytest.mark.parametrize("when", ["qualified", "committed"])
def test_storage_owner_change_invalidates_ready_and_committed_restore(immediate, monkeypatch, tmp_path, when):
    doc, owner = immediate
    source = stored(immediate)
    identity, job = start()
    if when == "committed":
        jobs.commit(identity)
    current = state._sessions[doc].design
    revision = state._sessions[doc].revision
    replacement_workspace = tmp_path / "replacement"
    replacement_workspace.mkdir()
    monkeypatch.setattr(session_cache, "_strict_persistence", StrictPersistence(replacement_workspace))
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409 and error.value.detail["code"] == "strict_cache_changed"
    assert state._sessions[doc].design is current and state._sessions[doc].revision == revision
    assert owner.read_pending(doc).payload == source.payload
    assert job.candidate is None if when == "committed" else job.candidate is not None


def test_recovery_candidates_share_existing_catalog_retention(immediate, monkeypatch):
    stored(immediate)
    monkeypatch.setattr(jobs, "MAX_RESULTS", 2)
    first_id, first_job = start()
    start()
    start()
    assert len(jobs._jobs) == 2 and first_job.candidate is None
    with pytest.raises(HTTPException) as error:
        jobs.inspect(first_id)
    assert error.value.status_code == 404


def test_strict_http_recovery_uses_same_poll_commit_and_no_json_restore_selector(immediate):
    from fastapi.testclient import TestClient
    from backend.api.part_strict_http import StrictPartDispatch
    from tests.test_part_strict_http import forbidden_app

    doc, _owner = immediate
    stored(immediate)
    client = TestClient(StrictPartDispatch(forbidden_app))
    headers = {"X-NADOC-Doc": doc}
    response = client.get("/api/design/recovery", headers=headers)
    assert response.status_code == 200 and response.json()["assessment"] == "unverified"
    assert client.post("/api/design/features/evaluation/jobs", headers=headers,
        json={"operation": "restore", "expected_revision": 0}).status_code == 403
    assert client.post("/api/design/recovery/jobs", headers=headers,
        json={"expected_revision": 0, "verified": True}).status_code == 422
    response = client.post("/api/design/recovery/jobs", headers=headers, json={"expected_revision": 0})
    assert response.status_code == 202, response.text
    path = "/api/design/features/evaluation/jobs/" + response.json()["job_id"]
    assert client.get(path, headers=headers).json()["result"]["status"] == "ready"
    assert client.post(path + "/commit", headers=headers).status_code == 200
    assert client.get("/api/design/revision", headers=headers).json()["revision"] == 1


def test_real_spawned_native_empty_restore_is_cold_qualified_and_reverified(document):
    from backend.core.part_verification_capture import capture

    doc, _owner = document
    source = stored(document)
    identity, _job = start()
    report = jobs.inspect(identity)
    assert report["result"]["restoration_assessment"]["status"] == "verified", report
    assert jobs.commit(identity)["revision"] == 1
    assert state._sessions[doc].design.payload == source.payload
    captured = capture(revisions.materialize_revision(state._sessions[doc].design), preserve_entry_types=True)
    from backend.api.part_verification_worker import VerificationWorker
    worker = VerificationWorker(captured)
    try:
        worker.start()
        assert worker.wait(10)
        assert worker.result()["status"] == "verified"
    finally:
        worker.close()
