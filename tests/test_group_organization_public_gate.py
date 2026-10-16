"""Organization remains private while ordinary editing consumers are staged.

All fixtures are tiny in-memory models. A private-session injection exercises
defence in depth without making an ordinary load path authorize the new state.
"""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, feature_recording, state
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import Design, DesignLoadout, Helix, Vec3
from backend.core.part_group_model import GroupOrganization, PartGroup


def legacy():
    return Design(helices=[Helix(id="helix", length_bp=4,
        axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=1))])


def active(source, populated=False):
    return source.model_copy(update={"group_organization": GroupOrganization(groups=[
        PartGroup(id="organization", helix_ids=["helix"])] if populated else [])})


@pytest.fixture
def document():
    source = legacy()
    doc = f"__organization_gate__{uuid4()}"
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(doc)
    try:
        state.load_design(source)
        session = state._sessions[doc]
        session.history.append(legacy())
        session.redo.append(legacy())
        session.workspace_heads[(source.id, "branch")] = {"saved-head"}
        session.pdb_atomistic = object()
        doc_context.set_request_revision(97)
        doc_context.set_request_feature_log_entry_id("existing-request-row")
        yield doc, session, source
    finally:
        try:
            state.drop_doc(doc)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)


def stored(session):
    return (session.design, session.design.model_dump_json(), session.revision,
        tuple(session.history), tuple(session.redo), deepcopy(session.workspace_heads),
        session.pdb_atomistic, session.identity, doc_context.current_request_revision(),
        doc_context.current_request_feature_log_entry_id())


def unchanged(session, before):
    after = stored(session)
    assert after[0] is before[0] and after[1:3] == before[1:3]
    for old, new in zip(before[3:5], after[3:5]):
        assert len(old) == len(new) and all(a is b for a, b in zip(old, new))
    assert after[5] == before[5] and after[6] is before[6]
    assert after[7:] == before[7:]


def denied(call):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "group_organization_not_enabled"


def unexpected(*_args, **_kwargs):
    pytest.fail("Staged organization performed publication or callback work")


def incoming_operation(operation, doc, session, source, candidate):
    if operation == "publish":
        with state._lock:
            return publish_replacement(session, candidate)
    return {
        "load": lambda: state.load_design(candidate),
        "restore": lambda: state.restore_doc_design(doc, candidate),
        "set": lambda: state.set_design(candidate),
        "branch": lambda: state.set_design_branch(candidate),
        "silent": lambda: state.set_design_silent(candidate),
        "save-ack": lambda: state.acknowledge_workspace_save(source, candidate, session.revision),
        "undo": state.undo,
        "redo": state.redo,
    }[operation]()


@pytest.mark.parametrize("populated", [False, True], ids=["empty", "populated"])
@pytest.mark.parametrize("operation", ["load", "restore", "set", "branch", "silent", "save-ack",
                                       "publish", "undo", "redo"])
def test_active_incoming_content_refuses_before_side_effects(document, monkeypatch, operation, populated):
    doc, session, source = document
    candidate = active(source, populated).model_copy(update={"loadouts": [
        DesignLoadout(id="incoming", head_revision_id="new-head")]})
    if operation == "undo":
        session.history.append(candidate)
    elif operation == "redo":
        session.redo.append(candidate)
    before = stored(session)
    candidate_before = candidate.model_dump_json()
    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    monkeypatch.setattr(state, "_restore_edit_snapshot", unexpected)
    monkeypatch.setattr(state, "_assert_photoproduct_dependencies", unexpected)
    denied(lambda: incoming_operation(operation, doc, session, source, candidate))
    unchanged(session, before)
    assert candidate.model_dump_json() == candidate_before


@pytest.mark.parametrize("operation", ["load", "restore", "set", "branch", "silent", "save-ack"])
def test_refused_startup_does_not_allocate_a_document_session(monkeypatch, operation):
    source, candidate = legacy(), active(legacy())
    doc = f"__organization_startup__{uuid4()}"
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(doc)
    try:
        assert doc not in state._sessions
        monkeypatch.setattr(state, "_DesignSession", unexpected)
        operations = {
            "load": lambda: state.load_design(candidate),
            "restore": lambda: state.restore_doc_design(doc, candidate),
            "set": lambda: state.set_design(candidate),
            "branch": lambda: state.set_design_branch(candidate),
            "silent": lambda: state.set_design_silent(candidate),
            "save-ack": lambda: state.acknowledge_workspace_save(source, candidate, 0),
        }
        denied(operations[operation])
        assert doc not in state._sessions
        assert doc_context.current_request_revision() == previous_revision
        assert doc_context.current_request_feature_log_entry_id() == previous_entry
    finally:
        try:
            state.drop_doc(doc)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)


@pytest.mark.parametrize("operation", ["callback", "display", "reconcile", "feature", "minor",
                                       "direct-record", "ordinary-helix", "early-guard"])
def test_active_source_never_reaches_ordinary_callbacks(document, monkeypatch, operation):
    _doc, session, source = document
    session.design = active(source, populated=True)
    before = stored(session)
    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    monkeypatch.setattr(state, "reconcile_cluster_membership", unexpected)

    def direct_record():
        with state._lock:
            return feature_recording.record_feature(session, "bundle-create", "blocked", {}, unexpected)

    operations = {
        "callback": lambda: state.mutate_and_validate(unexpected),
        "display": lambda: state.mutate_display_metadata(unexpected),
        "reconcile": lambda: state.mutate_with_reconcile(unexpected),
        "feature": lambda: state.mutate_with_feature_log("bundle-create", "blocked", {}, unexpected),
        "minor": lambda: state.mutate_with_minor_log("helix-update", "blocked", {}, unexpected),
        "direct-record": direct_record,
        "ordinary-helix": lambda: crud.update_helix("helix", crud.HelixRequest(
            axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=2), length_bp=5)),
        "early-guard": lambda: state.require_compatibility_write("test_preparation"),
    }
    denied(operations[operation])
    unchanged(session, before)


def test_restore_source_guard_uses_target_document_without_allocating_callers_session(document):
    doc, session, source = document
    session.design = active(source)
    before = stored(session)
    other = f"__organization_caller__{uuid4()}"
    token = doc_context.set_current_doc(other)
    try:
        denied(lambda: state.restore_doc_design(doc, source))
        unchanged(session, before)
        assert other not in state._sessions
    finally:
        doc_context.reset_current_doc(token)


@pytest.mark.parametrize("operation", ["load", "restore", "set", "branch", "silent", "save-ack",
                                       "publish", "undo", "redo"])
def test_legacy_incoming_models_keep_existing_publication_behavior(document, operation):
    doc, session, source = document
    before = session.revision
    candidate = source.model_copy(deep=True)
    candidate.metadata.name = "Legacy replacement"
    expected = (session.history[-1] if operation == "undo" else
                session.redo[-1] if operation == "redo" else candidate)
    incoming_operation(operation, doc, session, source, candidate)
    assert session.design.id == expected.id
    assert session.design.group_organization is None
    assert session.revision == before + 1
    assert doc_context.current_request_revision() == session.revision


def test_absent_organization_check_never_materializes_an_immutable_handle(monkeypatch):
    from backend.api.part_group_organization_gate import require_live_design
    from backend.api.part_immutable_revision import StrictPartRevision

    # A typed handle with no installed payload proves the scalar staging check
    # cannot inspect or materialize immutable content through a fallback.
    handle = object.__new__(StrictPartRevision)
    monkeypatch.setattr(state, "_mutable_design", unexpected)
    require_live_design(handle)


@pytest.mark.parametrize("reserved", [False, True], ids=["absent-session", "empty-session"])
def test_active_first_feature_refuses_before_reservation_or_callback(monkeypatch, reserved):
    candidate = active(legacy())
    doc = f"__organization_initial__{uuid4()}"
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(doc)
    try:
        if reserved:
            state.load_design(None)
        session = state._sessions.get(doc)
        revision = None if session is None else session.revision
        request_revision = doc_context.current_request_revision()
        monkeypatch.setattr(state, "_DesignSession", unexpected)
        monkeypatch.setattr(feature_recording, "record_feature", unexpected)
        denied(lambda: state.mutate_with_feature_log(
            "bundle-create", "blocked first feature", {}, unexpected, initial_design=candidate))
        assert state._sessions.get(doc) is session
        if session is not None:
            assert session.design is None and session.revision == revision
            assert not session.history and not session.redo
        assert doc_context.current_request_revision() == request_revision
        assert doc_context.current_request_feature_log_entry_id() == previous_entry
    finally:
        try:
            state.drop_doc(doc)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)


def test_unused_initial_model_does_not_reject_an_active_legacy_document(document, monkeypatch):
    _doc, session, source = document
    seen = []

    def record(actual, _kind, _label, _params, callback):
        assert actual is session and actual.design is source
        callback(actual.design)
        return "existing recording result"

    monkeypatch.setattr(feature_recording, "record_feature", record)
    result = state.mutate_with_feature_log("bundle-create", "existing source", {},
        lambda design: seen.append(design), initial_design=active(legacy()))
    assert result == "existing recording result" and seen == [source]


@pytest.mark.parametrize("permit", [False, True], ids=["compatibility", "permit-bearing"])
def test_direct_publisher_checks_its_supplied_session_source(document, monkeypatch, permit):
    from backend.api import part_publication_permit as permits

    _doc, current, source = document
    other = state._DesignSession(design=active(source))
    before, current_before = stored(other), stored(current)
    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    monkeypatch.setattr(permits, "check_publication", unexpected)
    with state._lock:
        with pytest.raises(HTTPException) as error:
            publish_replacement(other, source, publication_permit=object() if permit else None)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == ("source_changed" if permit
            else "group_organization_not_enabled")
    unchanged(other, before)
    unchanged(current, current_before)
