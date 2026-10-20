"""Failure injection at the standard-part history transaction boundaries."""
from collections import deque

import pytest

from backend.api import state
from backend.api.doc_context import (
    current_request_feature_log_entry_id,
    current_request_revision,
    reset_current_doc,
    set_current_doc,
    set_request_feature_log_entry_id,
    set_request_revision,
)
from backend.core.models import Design


@pytest.fixture
def session(monkeypatch):
    token = set_current_doc("feature-recording-transaction-test")
    request_revision = current_request_revision()
    request_entry = current_request_feature_log_entry_id()
    state.load_design(Design())
    s = state._session()
    # A full bounded stack catches loss of the oldest entry on a failed append.
    s.history = deque([Design(), Design()], maxlen=2)
    s.redo = deque([Design()], maxlen=2)
    set_request_revision(123)
    set_request_feature_log_entry_id("previous-request-entry")
    yield s
    monkeypatch.undo()
    state.close_session()
    reset_current_doc(token)
    set_request_revision(request_revision)
    set_request_feature_log_entry_id(request_entry)


def record(kind, fn):
    if kind == "snapshot":
        return state.mutate_with_feature_log("nick", "Test edit", {}, fn)
    return state.mutate_with_minor_log("nick", "Test edit", {}, fn)


def signature(s):
    return (
        s.design.model_dump() if s.design is not None else None, [d.model_dump() for d in s.history],
        [d.model_dump() for d in s.redo], s.revision,
        current_request_revision(), current_request_feature_log_entry_id(),
    )


@pytest.mark.parametrize("kind", ["bundle-create", "extrude-segment", "extrude-continuation",
    "extrude-deformed-continuation", "extrude-frame", "circle-segment", "overhang-extrude"])
@pytest.mark.parametrize("cursor,sub_cursor", [(-2, None), (0, None), (-1, 0)])
def test_extrusion_creation_refuses_rollback_before_building(session, kind, cursor, sub_cursor):
    from fastapi import HTTPException

    session.design.feature_log_cursor = cursor
    session.design.feature_log_sub_cursor = sub_cursor
    before = signature(session)

    def forbidden(_design):
        pytest.fail("Historical extrusion must refuse before running its builder")

    with pytest.raises(HTTPException) as caught:
        state.mutate_with_feature_log(kind, "Extrude", {}, forbidden)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "historical_cursor"
    assert signature(session) == before


@pytest.mark.parametrize("kind", ["snapshot", "minor", "minor-append"])
@pytest.mark.parametrize("stage", ["pre-encode", "callback", "reconcile", "retry",
                                   "post-encode", "validate", "revision", "entry-marker"])
def test_failure_restores_design_full_undo_redo_and_request_state(session, monkeypatch, kind, stage):
    if kind == "minor-append":
        record("minor", lambda d: None)
        session.redo.append(Design())
    before = signature(session)

    def fail(*args, **kwargs):
        raise RuntimeError("injected transaction failure")

    def mutation(design):
        design.metadata.name = "changed before failure"
        if stage == "callback":
            fail()

    if stage in {"pre-encode", "post-encode"}:
        original = state.encode_design_snapshot
        calls = 0
        # An appended routing child reuses the cluster's pre-state.
        fail_at = 1 if stage == "pre-encode" or kind == "minor-append" else 2

        def encode(design):
            nonlocal calls
            calls += 1
            if calls == fail_at:
                fail()
            return original(design)

        monkeypatch.setattr(state, "encode_design_snapshot", encode)
    elif stage in {"reconcile", "retry", "validate"}:
        name = {"reconcile": "reconcile_cluster_membership", "retry": "_retry_pending_ligations",
                "validate": "validate_design"}[stage]
        monkeypatch.setattr(state, name, fail)
    elif stage in {"revision", "entry-marker"}:
        name = "_bump_revision" if stage == "revision" else "set_request_feature_log_entry_id"
        original = getattr(state, name)

        def publish(value):
            original(value)
            fail()

        monkeypatch.setattr(state, name, publish)
    with pytest.raises(RuntimeError, match="injected transaction failure"):
        record(kind, mutation)
    assert signature(session) == before


def test_minor_diff_failure_preserves_existing_cluster(session, monkeypatch):
    from backend.core import design_diff
    record("minor", lambda d: None)
    session.redo.append(Design())
    before = signature(session)

    def fail(*args):
        raise RuntimeError("diff failure")

    monkeypatch.setattr(design_diff, "encode_child_diff", fail)
    with pytest.raises(RuntimeError, match="diff failure"):
        record("minor", lambda d: setattr(d.metadata, "name", "lost edit"))
    assert signature(session) == before


@pytest.mark.parametrize("kind", ["snapshot", "minor"])
def test_success_keeps_one_undo_and_publishes_history(session, kind):
    before = session.design.model_dump()
    revision = session.revision
    design, _, entry = record(kind, lambda d: setattr(d.metadata, "name", "accepted"))
    assert design.metadata.name == "accepted"
    assert session.history[-1].model_dump() == before
    assert len(session.history) == 2
    assert not session.redo
    assert session.revision == revision + 1
    assert current_request_revision() == session.revision
    assert current_request_feature_log_entry_id() == design.feature_log[-1].id
    assert entry.id == (design.feature_log[-1].id if kind == "snapshot"
                        else design.feature_log[-1].children[-1].id)


@pytest.mark.parametrize("kind", ["snapshot", "minor"])
def test_cancellation_restores_transaction(session, kind):
    before = signature(session)

    def cancel(design):
        design.metadata.name = "cancelled"
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        record(kind, cancel)
    assert signature(session) == before


@pytest.mark.parametrize("kind", ["snapshot", "minor"])
def test_invalid_record_schema_rolls_back_mutation(session, kind):
    from pydantic import ValidationError
    before = signature(session)
    fn = state.mutate_with_feature_log if kind == "snapshot" else state.mutate_with_minor_log
    with pytest.raises(ValidationError):
        fn("unknown-operation", "Invalid", {}, lambda d: setattr(d.metadata, "name", "changed"))
    assert signature(session) == before


def test_validation_findings_do_not_prevent_saving_an_editable_draft(session, monkeypatch):
    from backend.core.validator import ValidationReport, ValidationResult
    report = ValidationReport([ValidationResult(False, "Unresolved design input")])
    monkeypatch.setattr(state, "validate_design", lambda d: report)
    design, result, _ = record("minor", lambda d: setattr(d.metadata, "name", "Draft"))
    assert design.metadata.name == "Draft"
    assert result is report
    assert not result.passed


@pytest.mark.parametrize("stage", ["pre-encode", "callback", "reconcile", "validate", "revision", "cancel"])
def test_first_feature_failure_restores_no_document_and_all_transaction_state(session, monkeypatch, stage):
    from backend.core.part_history_contract import create_empty_part

    session.design = None
    before = signature(session)

    def fail(*_args, **_kwargs):
        raise RuntimeError("first feature failure")

    def mutation(design):
        design.metadata.name = "changed"
        if stage == "cancel":
            raise KeyboardInterrupt()
        if stage == "callback":
            fail()

    if stage in {"pre-encode", "reconcile", "validate"}:
        name = {"pre-encode": "encode_design_snapshot", "reconcile": "reconcile_cluster_membership",
                "validate": "validate_design"}[stage]
        monkeypatch.setattr(state, name, fail)
    elif stage == "revision":
        bump = state._bump_revision

        def publish(value):
            bump(value)
            fail()

        monkeypatch.setattr(state, "_bump_revision", publish)
    with pytest.raises(KeyboardInterrupt if stage == "cancel" else RuntimeError):
        state.mutate_with_feature_log("aptamer-import", "First feature", {}, mutation,
            initial_design=create_empty_part("Initial", "HONEYCOMB"), expected_revision=session.revision)
    assert signature(session) == before


def test_first_feature_creates_one_revision_and_undoable_empty_root(session):
    from backend.core.part_history_contract import create_empty_part

    state.load_design(None)
    initial = create_empty_part("Initial", "HONEYCOMB")
    revision = session.revision
    result, _, entry = state.mutate_with_feature_log("aptamer-import", "First feature", {},
        lambda design: design.copy_with(metadata=design.metadata.model_copy(update={"name": "Imported"})),
        initial_design=initial, expected_revision=revision)
    assert session.revision == revision + 1
    assert len(session.history) == 1 and not session.redo
    assert result.recipe_root == initial.recipe_root
    assert result.feature_log == [entry]
    state.undo()
    assert session.design.metadata.name == "Initial"
    assert session.design.feature_log == []
    state.redo()
    assert session.design.metadata.name == "Imported"


def test_initial_document_never_overwrites_existing_session(session):
    from backend.core.part_history_contract import create_empty_part

    original = session.design
    initial = create_empty_part("Unused", "HONEYCOMB")
    result, _, _ = state.mutate_with_feature_log("aptamer-import", "Existing", {}, lambda design: design,
                                                initial_design=initial)
    assert result.id == original.id != initial.id
    assert result.recipe_root is None


def test_stale_first_feature_never_initializes_document(session):
    from fastapi import HTTPException
    from backend.core.part_history_contract import create_empty_part

    session.design = None
    before = signature(session)
    with pytest.raises(HTTPException) as error:
        state.mutate_with_feature_log("aptamer-import", "First feature", {},
            lambda _: pytest.fail("Stale callback ran"), expected_revision=session.revision - 1,
            initial_design=create_empty_part("Unused", "HONEYCOMB"))
    assert error.value.status_code == 409
    assert signature(session) == before
