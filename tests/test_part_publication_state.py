"""Strict embedding policy refuses generic writes before callbacks or copies."""

from contextlib import ExitStack
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import doc_context, feature_recording, state
from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def document():
    doc = f"__strict_publication__{uuid4()}"
    previous = policy.current_configuration()
    source = create_empty_part("Strict source", "HONEYCOMB")
    with ExitStack() as cleanup:
        token = doc_context.set_current_doc(doc)
        cleanup.callback(doc_context.reset_current_doc, token)
        cleanup.callback(state.drop_doc, doc)
        cleanup.callback(state.configure_part_publication_policy, previous)
        state.load_design(source)
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(
            default_mode=previous.default_mode, document_modes={**previous.document_modes, doc: "registered_only"}))
        session = state._sessions[doc]
        yield doc, session, source


def denied(call):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == 403 and error.value.detail["code"] == "construction_policy"


@pytest.mark.parametrize("operation", [
    "load", "clear-load", "restore", "replace", "branch", "callback", "display", "reconcile",
    "replace-reconcile", "feature", "minor", "undo", "redo", "snapshot", "clear-history",
    "close", "pdb", "add-asset", "remove-asset", "silent", "save-copy",
    "save-ack", "heads",
])
def test_generic_mutations_refuse_before_any_callback_snapshot_or_assignment(document, monkeypatch, operation):
    doc, session, source = document
    before = source.model_dump_json()
    revision = session.revision
    candidate = source.model_copy(deep=True)

    def forbidden(*_a, **_k):
        pytest.fail("Rejected operation performed work or invoked a callback")

    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    monkeypatch.setattr(state, "reconcile_cluster_membership", forbidden)
    operations = {
        "load": lambda: state.load_design(candidate),
        "clear-load": lambda: state.load_design(None),
        "restore": lambda: state.restore_doc_design(doc, candidate),
        "replace": lambda: state.set_design(candidate),
        "branch": lambda: state.set_design_branch(candidate),
        "callback": lambda: state.mutate_and_validate(forbidden),
        "display": lambda: state.mutate_display_metadata(forbidden),
        "reconcile": lambda: state.mutate_with_reconcile(forbidden),
        "replace-reconcile": lambda: state.replace_with_reconcile(candidate),
        "feature": lambda: state.mutate_with_feature_log("nanoparticle-create", "Untrusted callback", {}, forbidden),
        "minor": lambda: state.mutate_with_minor_log("helix-add", "Untrusted callback", {}, forbidden),
        "undo": state.undo,
        "redo": state.redo,
        "snapshot": state.snapshot,
        "clear-history": state.clear_history,
        "close": state.close_session,
        "pdb": lambda: state.set_pdb_atomistic(object()),
        "add-asset": lambda: state.add_protein_asset(object()),
        "remove-asset": lambda: state.remove_protein_asset("missing"),
        "silent": lambda: state.set_design_silent(candidate),
        "save-copy": state.copy_for_workspace_save,
        "save-ack": lambda: state.acknowledge_workspace_save(source, candidate, revision),
        "heads": lambda: state.restore_workspace_heads(doc, {"part": {"branch": ["revision"]}}),
    }
    denied(operations[operation])
    assert session.design is source and source.model_dump_json() == before
    assert session.revision == revision and not session.history and not session.redo
    assert session.workspace_heads == {} and session.pdb_atomistic is None


@pytest.mark.parametrize("helper", ["record", "minor", "run", "publish", "replacement"])
def test_direct_recording_and_replacement_helpers_cannot_bypass_state_policy(document, monkeypatch, helper):
    _doc, session, source = document
    revision = session.revision

    def forbidden(*_a, **_k):
        pytest.fail("Direct publication bypass executed work")

    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    from backend.api.part_replacement_transaction import publish_replacement

    operations = {
        "record": lambda: feature_recording.record_feature(session, "nanoparticle-create", "Callback", {}, forbidden),
        "minor": lambda: feature_recording.record_minor(session, "helix-add", "Callback", {}, forbidden),
        "run": lambda: feature_recording._run(session, source, forbidden, state),
        "publish": lambda: feature_recording._publish(session, source, "row", state),
        "replacement": lambda: publish_replacement(session, source.model_copy(deep=True)),
    }
    with state._lock:
        denied(operations[helper])
    assert session.design is source and session.revision == revision
    assert not session.history and not session.redo


def test_strict_binding_survives_drop_and_lazy_recreation_without_saved_authority(document):
    doc, session, source = document
    original_identity = session.identity
    state.drop_doc(doc)
    assert state.get_design() is None
    assert state._sessions[doc].identity != original_identity
    assert state.part_publication_policy().strict
    denied(lambda: state.load_design(source))
    assert state.get_design() is None


def test_restore_checks_the_target_doc_policy_not_the_callers_compatibility_context(document):
    doc, session, source = document
    token = doc_context.set_current_doc(f"__compat_caller__{uuid4()}")
    try:
        denied(lambda: state.restore_doc_design(doc, source.model_copy(deep=True)))
        assert state._sessions[doc] is session and session.design is source
    finally:
        doc_context.reset_current_doc(token)


def test_explicit_empty_creation_builds_root_without_supplied_geometry_or_undo(document):
    doc, _session, _source = document
    state.drop_doc(doc)
    candidate = state.create_empty_part("Native empty", "SQUARE")
    assert state.get_design() is candidate
    assert candidate.recipe_root.kind == "empty" and candidate.recipe_root.initial_name == "Native empty"
    assert candidate.lattice_type == "SQUARE" and candidate.feature_log == []
    assert state.revision() == 1 and state.undo_depth() == state.redo_depth() == 0
    with pytest.raises(TypeError):
        state.create_empty_part(candidate=candidate)
    with pytest.raises(HTTPException) as error:
        state.create_empty_part("Replacement", "HONEYCOMB")
    assert error.value.detail["code"] == "part_already_open"
    assert state.get_design() is candidate and state.revision() == 1


def batch_permit(document, candidate):
    doc, session, _source = document
    with state._lock:
        admission = permits.admit_evaluation(doc, session, operation="batch", request_sha256="a" * 64)
    cancelled = Event()
    permit = permits.issue_batch_permit(admission, candidate, request_sha256="a" * 64,
        authoring_sha256="b" * 64, recipe_sha256="c" * 64, source_status="verified",
        cancelled=cancelled, expires=monotonic() + 60)
    return permit, cancelled


@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_failed_publication_restores_everything_and_leaves_permit_retryable(document, monkeypatch, exception):
    _doc, session, source = document
    candidate = source.model_copy(deep=True)
    permit, _cancelled = batch_permit(document, candidate)
    revision = session.revision
    bump = state._bump_revision

    def interrupted(current):
        bump(current)
        raise exception("Interrupted after assignment")

    monkeypatch.setattr(state, "_bump_revision", interrupted)
    with pytest.raises(exception):
        state.set_design(candidate, publication_permit=permit)
    assert session.design is source and session.revision == revision
    assert not session.history and not session.redo
    monkeypatch.setattr(state, "_bump_revision", bump)
    assert state.set_design(candidate, publication_permit=permit) == revision + 1
    assert session.design is candidate and len(session.history) == 1
    with pytest.raises(HTTPException):
        state.set_design(candidate, publication_permit=permit)
    assert session.revision == revision + 1 and len(session.history) == 1


@pytest.mark.parametrize("stop", ["cancel", "expire"])
def test_liveness_is_checked_after_snapshot_before_assignment(document, monkeypatch, stop):
    _doc, session, source = document
    candidate = source.model_copy(deep=True)
    permit, cancelled = batch_permit(document, candidate)
    revision = session.revision
    snapshot = state._snapshot_copy

    def stop_after_copy(value):
        result = snapshot(value)
        if stop == "cancel":
            cancelled.set()
        else:
            monkeypatch.setattr(permits, "monotonic", lambda: monotonic() + 100)
        return result

    monkeypatch.setattr(state, "_snapshot_copy", stop_after_copy)
    with pytest.raises(HTTPException) as error:
        state.set_design(candidate, publication_permit=permit)
    assert error.value.detail["code"] == ("cancelled" if stop == "cancel" else "publication_expired")
    assert session.design is source and session.revision == revision
    assert not session.history and not session.redo


def test_compatibility_callbacks_and_replacements_keep_existing_behavior(document):
    _doc, _session, source = document
    state.configure_part_publication_policy(policy.HostPolicyConfiguration())
    calls = []
    state.mutate_display_metadata(lambda design: calls.append(design.id))
    state.set_design(source.model_copy(deep=True))
    state.undo()
    state.redo()
    assert calls == [source.id] and state.undo_depth() == 1


def test_guarded_save_snapshot_refuses_before_the_existing_route_can_write(document, monkeypatch):
    monkeypatch.setattr(state, "_snapshot_copy", lambda *_a: pytest.fail("Save copied before policy check"))
    denied(state.copy_for_workspace_save)


def test_permit_bearing_direct_setter_does_not_recreate_a_closed_session(document):
    doc, _session, source = document
    candidate = source.model_copy(deep=True)
    permit, _cancelled = batch_permit(document, candidate)
    state.drop_doc(doc)
    with pytest.raises(HTTPException) as error:
        state.set_design(candidate, publication_permit=permit)
    assert error.value.status_code == 409 and error.value.detail["code"] == "source_changed"
    assert doc not in state.revision_map()
