"""Exclusive immutable session content without copying or an alternate truth."""

from collections import deque
from threading import Event
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state
from backend.api import part_immutable_revision as revisions, part_immutable_storage as storage
from backend.api import part_publication_host as host, part_publication_permit as permits
from backend.api import part_publication_policy as policy
from backend.core.part_verification_capture import CaptureLimit


@pytest.fixture
def document():
    doc = f"__immutable__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    previous = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(
        document_modes={**previous.document_modes, doc: "registered_only"}, default_mode=previous.default_mode))
    try:
        yield doc
    finally:
        state.drop_doc(doc)
        state.configure_part_publication_policy(previous)
        doc_context.reset_current_doc(token)


def create():
    return host.create_immutable_empty("Private strict", "HONEYCOMB")


def candidate(source, visible=False):
    model = revisions.materialize_revision(source)
    model.annotations_enabled = visible
    return revisions.prepare_revision(model)


def permit(doc, prepared, *, cancelled=None):
    with state._lock:
        admission = permits.admit_evaluation(doc, state._sessions[doc], operation="batch", request_sha256="a" * 64)
    meta = revisions.revision_metadata(prepared)
    return permits.issue_batch_permit(admission, prepared, request_sha256="a" * 64,
        authoring_sha256=meta.authoring_sha256, recipe_sha256=meta.recipe_sha256,
        source_status="verified", expires=monotonic() + 60, cancelled=cancelled or Event())


def test_reserved_empty_is_prepared_outside_lock_and_published_once(document, monkeypatch):
    original = revisions.prepare_revision
    reservations = []

    def inspect(candidate, **kwargs):
        assert state._lock.acquire(blocking=False)
        try:
            reserved = state._sessions[document]
            assert reserved.design is None and not reserved.history and not reserved.redo
            reservations.append(reserved)
        finally:
            state._lock.release()
        return original(candidate, **kwargs)

    monkeypatch.setattr(revisions, "prepare_revision", inspect)
    prepared, revision = create()
    session = state._sessions[document]
    assert session is reservations[0] and session.design is prepared
    assert revisions.is_prepared_revision(prepared) and revision == session.revision == 1
    assert not session.history and not session.redo
    assert set(session.__dict__).isdisjoint({"mutable_mirror", "strict_revision", "decoded_design"})


@pytest.mark.parametrize("reopen", [False, True])
def test_close_during_preparation_cannot_recreate_even_after_empty_session_aba(document, monkeypatch, reopen):
    original = revisions.prepare_revision

    def close(candidate, **kwargs):
        result = original(candidate, **kwargs)
        state.drop_doc(document)
        if reopen:
            with state._lock:
                state._session()
        return result

    monkeypatch.setattr(revisions, "prepare_revision", close)
    with pytest.raises(HTTPException) as error:
        create()
    assert error.value.detail["code"] == "source_changed"
    assert (document in state._sessions) is reopen
    if reopen:
        assert state._sessions[document].design is None and state._sessions[document].revision == 0


def test_policy_change_during_preparation_refuses_and_keeps_empty_reservation(document, monkeypatch):
    original = revisions.prepare_revision

    def change(candidate, **kwargs):
        result = original(candidate, **kwargs)
        state.configure_part_publication_policy(policy.current_configuration())
        return result

    monkeypatch.setattr(revisions, "prepare_revision", change)
    with pytest.raises(HTTPException) as error:
        create()
    assert error.value.detail["code"] == "policy_changed"
    assert state._sessions[document].design is None and state._sessions[document].revision == 0


@pytest.mark.parametrize("field,value", [("history", deque([object()])), ("redo", deque([object()])),
    ("pdb_atomistic", object()), ("workspace_heads", {("part", "loadout"): {"revision"}})])
def test_empty_creation_refuses_legacy_session_extras_before_preparation(document, monkeypatch, field, value):
    with state._lock:
        setattr(state._session(), field, value)
    monkeypatch.setattr(revisions, "prepare_revision", lambda *a, **k: pytest.fail("Unadmitted preparation"))
    with pytest.raises(HTTPException) as error:
        create()
    assert error.value.detail["code"] == "immutable_empty_session_required"
    assert state._sessions[document].design is None


@pytest.mark.parametrize("getter", ["get_design", "get_design_with_revision", "get_or_404",
    "peek_design", "copy_for_persist", "copy_doc_for_persist"])
def test_mutable_getters_refuse_without_decoding_or_copying(document, monkeypatch, getter):
    prepared, _revision = create()
    monkeypatch.setattr(revisions, "materialize_revision", lambda *a, **k: pytest.fail("Hidden decode"))
    monkeypatch.setattr(state, "_snapshot_copy", lambda *a, **k: pytest.fail("Hidden copy"))
    with pytest.raises(HTTPException) as error:
        getattr(state, getter)(document) if getter in {"peek_design", "copy_doc_for_persist"} else getattr(state, getter)()
    assert error.value.detail["code"] == "immutable_design_access"
    assert state._sessions[document].design is prepared


def test_scalar_reads_use_metadata_without_materialization(document, monkeypatch):
    from backend.api.part_revision_status import revision_status

    prepared, revision = create()
    monkeypatch.setattr(revisions, "materialize_revision", lambda *a, **k: pytest.fail("Hidden decode"))
    assert state.design_metadata_for_doc(document) == {
        "id": revisions.revision_metadata(prepared).design_id, "name": "Private strict"}
    assert revision_status() == {"doc_id": document, "design_id": revisions.revision_metadata(prepared).design_id,
        "revision": revision, "has_design": True}
    assert document in state.list_doc_ids() and state.has_design_unlocked()


def test_strict_to_compatibility_transition_refuses_before_generation_changes(document):
    prepared, revision = create()
    before = policy.resolve(document)
    with pytest.raises(HTTPException) as error:
        state.configure_part_publication_policy(policy.HostPolicyConfiguration())
    assert error.value.detail["code"] == "immutable_policy_transition"
    assert policy.resolve(document) == before
    assert state._sessions[document].design is prepared and state.revision() == revision
    state.configure_part_publication_policy(policy.current_configuration())
    assert policy.resolve(document).generation == before.generation + 1


def test_exact_immutable_publication_retains_source_handle_without_snapshot(document, monkeypatch):
    source, revision = create()
    prepared = candidate(source)
    authority = permit(document, prepared)
    monkeypatch.setattr(state, "_snapshot_copy", lambda *a, **k: pytest.fail("Immutable undo copied a model"))
    assert state.set_design(prepared, publication_permit=authority) == revision + 1
    session = state._sessions[document]
    assert session.design is prepared and list(session.history) == [source] and not session.redo
    with pytest.raises(HTTPException):
        state.set_design(prepared, publication_permit=authority)
    assert session.revision == revision + 1 and list(session.history) == [source]


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_failed_revision_bump_restores_exact_handles_stacks_and_retryable_permit(document, monkeypatch, error_type):
    source, revision = create()
    prepared = candidate(source)
    authority = permit(document, prepared)
    session = state._sessions[document]
    older, redo = candidate(source), candidate(source)
    session.history.append(older)
    session.redo.append(redo)
    bump = state._bump_revision

    def fail(current):
        bump(current)
        raise error_type("after revision")

    monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(error_type):
        state.set_design(prepared, publication_permit=authority)
    assert session.design is source and session.revision == revision
    assert list(session.history) == [older] and list(session.redo) == [redo]
    monkeypatch.setattr(state, "_bump_revision", bump)
    state.set_design(prepared, publication_permit=authority)
    assert session.design is prepared and list(session.history) == [older, source] and not session.redo


def test_retention_refusal_is_atomic_and_permit_is_retryable(document, monkeypatch):
    source, revision = create()
    prepared = candidate(source)
    authority = permit(document, prepared)
    session = state._sessions[document]
    session.history.append(candidate(source))
    old = list(session.history)
    monkeypatch.setattr(storage, "MAX_RETAINED_REVISION_BYTES", len(source.payload) + len(prepared.payload) - 1)
    with pytest.raises(CaptureLimit):
        state.set_design(prepared, publication_permit=authority)
    assert session.design is source and session.revision == revision and list(session.history) == old
    monkeypatch.setattr(storage, "MAX_RETAINED_REVISION_BYTES", 32_000_000)
    state.set_design(prepared, publication_permit=authority)


def test_retention_evicts_only_oldest_and_preserves_immediate_source(document, monkeypatch):
    source, _revision = create()
    prepared = candidate(source)
    session = state._sessions[document]
    session.history.extend([candidate(source), candidate(source)])
    authority = permit(document, prepared)
    monkeypatch.setattr(storage, "MAX_RETAINED_REVISION_BYTES", len(source.payload) + len(prepared.payload))
    state.set_design(prepared, publication_permit=authority)
    assert list(session.history) == [source] and session.design is prepared


def test_unsealed_or_mixed_candidates_cannot_enter_immutable_session(document):
    source, revision = create()
    mutable = revisions.materialize_revision(source)
    with state._lock:
        admission = permits.admit_evaluation(document, state._sessions[document], operation="batch", request_sha256="a" * 64)
    with pytest.raises(HTTPException) as error:
        permits.issue_batch_permit(admission, mutable, request_sha256="a" * 64,
            authoring_sha256="b" * 64, recipe_sha256="c" * 64, source_status="verified",
            expires=monotonic() + 60, cancelled=Event())
    assert error.value.detail["code"] == "immutable_publication_scope"
    assert state._sessions[document].design is source and state.revision() == revision


def test_public_immutable_creation_gate_remains_closed(document):
    assert host.IMMUTABLE_STRICT_STORAGE_ENABLED is False
    existing = state.create_empty_part("Existing creation", "HONEYCOMB")
    assert state.get_design() is existing


@pytest.mark.parametrize("metadata", [None, {}, object()])
def test_scalar_compatibility_reads_do_not_depend_on_metadata_shape(document, metadata):
    from backend.api.part_revision_status import revision_status

    existing = state.create_empty_part("Compatibility representation", "HONEYCOMB")
    existing.metadata = metadata
    assert revision_status()["design_id"] == existing.id
    assert state.design_metadata_for_doc(document) == {"id": existing.id, "name": None}


@pytest.mark.parametrize("generation", [True, -1])
def test_stale_or_invalid_trusted_generation_refuses_before_reserving_session(document, generation):
    with pytest.raises(HTTPException) as error:
        host.create_immutable_empty(expected_policy_generation=generation)
    assert error.value.detail["code"] == "policy_changed" and document not in state._sessions


def test_different_projection_digest_cannot_authorize_the_sealed_candidate(document):
    source, _revision = create()
    prepared = candidate(source)
    with state._lock:
        admission = permits.admit_evaluation(document, state._sessions[document], operation="batch", request_sha256="a" * 64)
    with pytest.raises(HTTPException) as error:
        permits.issue_batch_permit(admission, prepared, request_sha256="a" * 64,
            authoring_sha256="b" * 64, recipe_sha256="c" * 64, source_status="verified",
            expires=monotonic() + 60, cancelled=Event())
    assert error.value.detail["code"] == "immutable_publication_scope"
    assert state._sessions[document].design is source


def test_cancelled_handle_publication_leaves_content_and_retention_unchanged(document):
    source, revision = create()
    prepared = candidate(source)
    cancelled = Event()
    authority = permit(document, prepared, cancelled=cancelled)
    cancelled.set()
    with pytest.raises(HTTPException) as error:
        state.set_design(prepared, publication_permit=authority)
    assert error.value.detail["code"] == "cancelled"
    session = state._sessions[document]
    assert session.design is source and session.revision == revision and not session.history


def test_old_mutable_verification_capture_refuses_immutable_content(document, monkeypatch):
    create()
    monkeypatch.setattr(revisions, "materialize_revision", lambda *a, **k: pytest.fail("Hidden decode"))
    with pytest.raises(HTTPException) as error:
        state.capture_design_for_verification()
    assert error.value.detail["code"] == "immutable_design_access"
