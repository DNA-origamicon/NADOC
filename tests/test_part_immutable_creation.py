"""Durable first creation is separate from ephemeral internal storage tests."""

from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, session_cache, state
from backend.api import part_immutable_creation as creation
from backend.api import part_immutable_revision as revisions
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api import part_publication_permit as permits
from backend.api.part_immutable_persistence import StrictPersistence
from backend.core.part_command_errors import CommandContractError


@pytest.fixture
def document(tmp_path, monkeypatch):
    doc = "__durable_create__" + uuid4().hex
    token = doc_context.set_current_doc(doc)
    previous = policy.current_configuration()
    host.configure(policy.HostPolicyConfiguration(default_mode=previous.default_mode,
        document_modes={**previous.document_modes, doc: "registered_only"}))
    owner = StrictPersistence(tmp_path)
    monkeypatch.setattr(session_cache, "_strict_persistence", owner)
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path / ".session")
    try:
        yield doc, owner
    finally:
        state.drop_doc(doc)
        host.configure(previous)
        doc_context.reset_current_doc(token)


def test_first_create_is_durable_before_one_sealed_publication(document, monkeypatch):
    doc, owner = document
    original = owner.cache.write
    observed = []

    def write(*args):
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        assert state._sessions[doc].design is None
        observed.append(True)
        return original(*args)

    monkeypatch.setattr(owner.cache, "write", write)
    candidate, revision = creation.create_durable_empty("Durable empty", "HONEYCOMB")
    assert observed == [True] and revision == 1
    assert state._sessions[doc].design is candidate and revisions.is_prepared_revision(candidate)
    assert owner.read_pending(doc).payload == candidate.payload
    assert owner.write_if_immutable(doc) == 1 and not state._sessions[doc].history


def test_pending_record_refuses_fresh_creation_without_preparation_or_overwrite(document, monkeypatch):
    doc, owner = document
    candidate, _revision = creation.create_durable_empty()
    state.drop_doc(doc)
    monkeypatch.setattr(permits, "prepare_admitted_empty", lambda *_a, **_k: pytest.fail("Pending record rebuilt an empty part"))
    with pytest.raises(HTTPException) as error:
        creation.create_durable_empty()
    assert error.value.detail["code"] == "strict_cache_pending"
    assert state._sessions[doc].design is None and owner.read_pending(doc).payload == candidate.payload


@pytest.mark.parametrize("change", ["close", "reopen", "policy", "populate"])
def test_change_after_durable_write_preserves_record_without_replacing_new_work(document, monkeypatch, change):
    doc, owner = document
    original = owner.cache.write
    replacement = []

    def race(*args):
        lease = original(*args)
        if change in {"close", "reopen"}:
            state.drop_doc(doc)
            if change == "reopen":
                with state._lock:
                    state._session()
        elif change == "policy":
            host.configure(policy.current_configuration())
        else:
            replacement.append(host.create_immutable_empty("Different host work")[0])
        return lease

    monkeypatch.setattr(owner.cache, "write", race)
    with pytest.raises(HTTPException):
        creation.create_durable_empty("Preserved pending part")
    assert owner.read_pending(doc).payload
    if change == "close":
        assert doc not in state._sessions
    elif change == "populate":
        assert state._sessions[doc].design is replacement[0]
    else:
        assert state._sessions[doc].design is None


def test_failed_publication_keeps_pending_record_and_never_fakes_a_saved_live_revision(document, monkeypatch):
    doc, owner = document
    original = state._bump_revision

    def broken(session):
        original(session)
        raise RuntimeError("Injected durable publication failure")

    monkeypatch.setattr(state, "_bump_revision", broken)
    with pytest.raises(RuntimeError, match="durable publication"):
        creation.create_durable_empty()
    assert state._sessions[doc].design is None and state._sessions[doc].revision == 0
    assert owner.read_pending(doc).payload and owner.write_if_immutable(doc) is None


def test_failure_after_first_file_write_preserves_pending_bytes_without_binding(document, monkeypatch):
    doc, owner = document
    original = owner.cache.write

    def fail_after_write(*args):
        original(*args)
        raise RuntimeError("Injected failure after first durable write")

    monkeypatch.setattr(owner.cache, "write", fail_after_write)
    with pytest.raises(RuntimeError, match="after first durable write"):
        creation.create_durable_empty()
    assert state._sessions[doc].design is None and state._sessions[doc].revision == 0
    assert owner.read_pending(doc).payload and doc not in owner._bindings


def test_storage_or_policy_refusal_happens_before_session_or_file_creation(document, monkeypatch):
    doc, owner = document
    generation = policy.resolve(doc).generation
    host.configure(policy.current_configuration())
    with pytest.raises(HTTPException) as error:
        creation.create_durable_empty(expected_policy_generation=generation)
    assert error.value.detail["code"] == "policy_changed"
    assert doc not in state._sessions and not owner.cache.directory.exists()
    monkeypatch.setattr(session_cache, "_strict_persistence", None)
    with pytest.raises(HTTPException) as error:
        creation.create_durable_empty()
    assert error.value.status_code == 503 and doc not in state._sessions


@pytest.mark.parametrize("when", ["prepare", "write"])
def test_storage_owner_change_refuses_publication_and_preserves_written_bytes(document, monkeypatch, tmp_path, when):
    doc, owner = document
    replacement_workspace = tmp_path / "replacement"
    replacement_workspace.mkdir()
    replacement = StrictPersistence(replacement_workspace)
    original = permits.prepare_admitted_empty if when == "prepare" else owner.cache.write

    def replace(*args, **kwargs):
        value = original(*args, **kwargs)
        monkeypatch.setattr(session_cache, "_strict_persistence", replacement)
        return value

    monkeypatch.setattr(permits if when == "prepare" else owner.cache,
        "prepare_admitted_empty" if when == "prepare" else "write", replace)
    with pytest.raises(HTTPException) as error:
        creation.create_durable_empty()
    assert error.value.detail["code"] == "strict_cache_changed"
    assert state._sessions[doc].design is None and not replacement.cache.directory.exists()
    if when == "write":
        assert owner.read_pending(doc).payload
    else:
        assert owner.cache.inspect(doc) is None


def test_close_during_preparation_never_writes_or_recreates_session(document, monkeypatch):
    doc, owner = document
    original = permits.prepare_admitted_empty

    def close(*args, **kwargs):
        value = original(*args, **kwargs)
        state.drop_doc(doc)
        return value

    monkeypatch.setattr(permits, "prepare_admitted_empty", close)
    monkeypatch.setattr(owner.cache, "write", lambda *_a: pytest.fail("Closed reservation wrote bytes"))
    with pytest.raises(HTTPException) as error:
        creation.create_durable_empty()
    assert error.value.detail["code"] == "source_changed"
    assert doc not in state._sessions and owner.cache.inspect(doc) is None


def test_legacy_write_lease_prevents_initial_record_before_old_writer_finishes(document):
    doc, owner = document
    with owner.legacy_write(doc):
        with pytest.raises(HTTPException) as error:
            creation.create_durable_empty()
        assert error.value.detail["code"] == "strict_cache_busy"
        assert not owner.cache.directory.exists()
    candidate, revision = creation.create_durable_empty()
    assert revision == 1 and owner.read_pending(doc).payload == candidate.payload


def test_existing_namespace_legacy_lease_also_excludes_cooperating_typed_writer(document):
    doc, owner = document
    owner.reserve_empty(doc)  # Establish the typed namespace without writing a record.
    peer = StrictPersistence(owner.cache.directory.parent)
    with owner.legacy_write(doc):
        with pytest.raises(CommandContractError) as error:
            peer.reserve_empty("other-doc")
        assert error.value.code == "strict_cache_busy"


def test_autosave_admitted_before_policy_transition_finishes_before_first_durable_write(document, monkeypatch):
    doc, owner = document
    configuration = policy.current_configuration()
    host.configure(policy.HostPolicyConfiguration(default_mode=configuration.default_mode,
        document_modes={**configuration.document_modes, doc: "compatibility"}))
    state.create_empty_part("Earlier compatibility part", "HONEYCOMB")
    original = state.copy_doc_for_persist
    observed = []

    def captured_before_transition(identity):
        snapshot = original(identity)
        state.drop_doc(doc)
        host.configure(configuration)
        with pytest.raises(HTTPException) as error:
            creation.create_durable_empty()
        assert error.value.detail["code"] == "strict_cache_busy"
        observed.append(True)
        return snapshot

    monkeypatch.setattr(state, "copy_doc_for_persist", captured_before_transition)
    assert session_cache._write_doc(doc) is not False
    prior = session_cache._doc_dir(doc) / session_cache._DESIGN_FILE
    old_bytes = prior.read_bytes()
    assert observed == [True] and b"Earlier compatibility part" in old_bytes
    candidate, _revision = creation.create_durable_empty()
    assert prior.read_bytes() == old_bytes and owner.read_pending(doc).payload == candidate.payload


def test_legacy_close_serializes_before_first_durable_write(document, monkeypatch):
    doc, owner = document
    directory = session_cache._doc_dir(doc)
    directory.mkdir(parents=True)
    prior = directory / session_cache._DESIGN_FILE
    prior.write_bytes(b"pytest-owned earlier legacy part")
    original = session_cache._remove_known_files
    observed = []

    def unlink(*args):
        with pytest.raises(HTTPException) as error:
            creation.create_durable_empty()
        assert error.value.detail["code"] == "strict_cache_busy"
        assert not owner.cache.directory.exists()
        observed.append(True)
        original(*args)

    monkeypatch.setattr(session_cache, "_remove_known_files", unlink)
    session_cache._remove_doc_dir(doc)
    assert observed == [True] and not prior.exists()
    candidate, revision = creation.create_durable_empty()
    assert revision == 1 and owner.read_pending(doc).payload == candidate.payload


def test_ordinary_compatibility_autosave_does_not_create_typed_namespace(document):
    doc, owner = document
    configuration = policy.current_configuration()
    host.configure(policy.HostPolicyConfiguration(default_mode=configuration.default_mode,
        document_modes={**configuration.document_modes, doc: "compatibility"}))
    state.create_empty_part("Ordinary compatibility part", "HONEYCOMB")
    assert session_cache._write_doc(doc) is not False
    assert not owner.cache.directory.exists()
    assert (session_cache._doc_dir(doc) / session_cache._DESIGN_FILE).is_file()


def test_strict_http_switch_uses_durable_creation_without_mutable_response_alias(document, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.part_strict_http import StrictPartDispatch
    from tests.test_part_strict_http import forbidden_app

    doc, owner = document
    monkeypatch.setattr(host, "IMMUTABLE_STRICT_STORAGE_ENABLED", True)
    client = TestClient(StrictPartDispatch(forbidden_app))
    response = client.post("/api/design/registered-empty", headers={"X-NADOC-Doc": doc}, json={"name": "Durable HTTP"})
    assert response.status_code == 201, response.text
    assert response.json()["revision"] == 1 and "helices" not in response.json()
    current = state._sessions[doc].design
    assert revisions.is_prepared_revision(current) and owner.read_pending(doc).payload == current.payload
    with pytest.raises(HTTPException):
        state.get_design()


def test_real_durable_create_batch_flush_restart_restore_and_edit(document, monkeypatch):
    from collections import OrderedDict
    from backend.api import part_batch_evaluation, part_evaluation_jobs as jobs
    from backend.api import part_immutable_recovery as recovery
    from backend.core.part_verification_capture import capture
    from backend.api.part_verification_worker import VerificationWorker
    from tests.test_part_registered_batch import GOLD, command, gold, request

    doc, owner = document
    monkeypatch.setattr(jobs, "_jobs", OrderedDict())
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    monkeypatch.setattr(recovery, "_submit", recovery._run)
    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", True)
    initial, revision = creation.create_durable_empty("Durable editable recipe")
    design_id = revisions.revision_metadata(initial).design_id

    def batch(operation, current_revision):
        response = jobs.start({"operation": "batch", "expected_revision": current_revision,
            "batch": request(operation, expected_design_id=design_id, expected_revision=current_revision)})
        report = jobs.inspect(response["job_id"])
        assert report["result"]["status"] == "ready", report
        return jobs.commit(response["job_id"])["revision"]

    revision = batch(gold(), revision)
    active = state._sessions[doc].design
    first_feature = revisions.materialize_revision(active).feature_log[0].id
    assert session_cache._write_doc(doc)[0] == revision
    assert owner.read_pending(doc).payload == active.payload
    state.drop_doc(doc)
    restarted = StrictPersistence(owner.cache.directory.parent)
    monkeypatch.setattr(session_cache, "_strict_persistence", restarted)
    assert recovery.status()["record"]["state"] == "pending"
    response = recovery.start({"expected_revision": 0})
    report = jobs.inspect(response["job_id"])
    assert report["result"]["restoration_assessment"]["status"] == "verified", report
    revision = jobs.commit(response["job_id"])["revision"]
    assert state._sessions[doc].design.payload == active.payload
    revision = batch(command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 14.0}), revision)
    current = revisions.materialize_revision(state._sessions[doc].design)
    assert current.feature_log[0].id == first_feature and current.nanoparticles[0].id == GOLD
    assert current.nanoparticles[0].diameter_nm == 14.0 and len(current.feature_log) == 2
    assert session_cache._write_doc(doc)[0] == revision
    # Independent classic capture/proof remains an oracle for byte-transport jobs.
    captured = capture(revisions.materialize_revision(state._sessions[doc].design), preserve_entry_types=True)
    worker = VerificationWorker(captured)
    try:
        worker.start()
        assert worker.wait(10)
        assert worker.result()["status"] == "verified"
    finally:
        worker.close()
