"""Prepared-model publication preserves source identity on all failed commits."""

from collections import deque
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.core.models import Design


class Cancelled(BaseException):
    pass


@pytest.fixture
def session():
    identity = f"__replacement_transaction_test__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    prior_revision = doc_context.current_request_revision()
    prior_entry = doc_context.current_request_feature_log_entry_id()
    state.load_design(Design(id="source"))
    with state._lock:
        current = state._session()
        current.history = deque((Design(id=f"before-{i}") for i in range(3)), maxlen=3)
        current.redo = deque((Design(id=f"redo-{i}") for i in range(2)), maxlen=3)
    doc_context.set_request_revision(123)
    doc_context.set_request_feature_log_entry_id("earlier-entry")
    try:
        yield current
    finally:
        with state._lock:
            state._sessions.pop(identity, None)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(prior_revision)
        doc_context.set_request_feature_log_entry_id(prior_entry)


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, Cancelled])
def test_post_publication_failure_restores_source_stacks_revision_and_request_context(session, monkeypatch, empty, error_type):
    if empty:
        session.design = None
    original = session.design
    history, redo, revision = list(session.history), list(session.redo), session.revision
    calls = []
    snapshot = state._snapshot_copy

    def copied(source):
        calls.append(source)
        return snapshot(source)

    def fail(current):
        assert current.design.id == "candidate"
        assert not current.redo
        current.revision += 1
        doc_context.set_request_revision(current.revision)
        doc_context.set_request_feature_log_entry_id("partially-published")
        raise error_type("publication interrupted")

    monkeypatch.setattr(state, "_snapshot_copy", copied)
    monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(error_type, match="publication interrupted"):
        state.set_design(Design(id="candidate"), expected_revision=revision, expected_source=original)
    assert session.design is original
    assert list(session.history) == history and list(session.redo) == redo
    assert all(a is b for a, b in zip(session.history, history))
    assert all(a is b for a, b in zip(session.redo, redo))
    assert session.revision == revision
    assert doc_context.current_request_revision() == 123
    assert doc_context.current_request_feature_log_entry_id() == "earlier-entry"
    assert len(calls) == (0 if empty else 1)


def test_snapshot_failure_does_not_publish(session, monkeypatch):
    original = session.design
    history, redo, revision = list(session.history), list(session.redo), session.revision
    monkeypatch.setattr(state, "_snapshot_copy", lambda _: (_ for _ in ()).throw(RuntimeError("snapshot failed")))
    with pytest.raises(RuntimeError, match="snapshot failed"):
        state.set_design(Design(id="candidate"))
    assert session.design is original
    assert (list(session.history), list(session.redo), session.revision) == (history, redo, revision)
    assert doc_context.current_request_revision() == 123


@pytest.mark.parametrize("guard", ["revision", "source"])
def test_stale_replacement_rejects_before_snapshot(session, monkeypatch, guard):
    monkeypatch.setattr(state, "_snapshot_copy", lambda _: pytest.fail("Stale source was copied"))
    kwargs = {"expected_revision": session.revision, "expected_source": session.design}
    kwargs["expected_revision" if guard == "revision" else "expected_source"] = (
        session.revision - 1 if guard == "revision" else Design(id=session.design.id))
    with pytest.raises(HTTPException) as error:
        state.set_design(Design(id="candidate"), **kwargs)
    assert error.value.status_code == 409
    assert session.design.id == "source"


def test_success_publishes_once_and_undo_snapshot_is_independent(session, monkeypatch):
    original = session.design
    revision = session.revision
    candidate = Design(id="candidate")
    snapshots = []
    snapshot = state._snapshot_copy

    def copied(source):
        snapshots.append(source)
        return snapshot(source)

    monkeypatch.setattr(state, "_snapshot_copy", copied)
    assert state.set_design(candidate, expected_source=original, expected_revision=revision) == revision + 1
    assert session.design is candidate
    assert [item.id for item in session.history] == ["before-1", "before-2", "source"]
    assert not session.redo and snapshots == [original]
    assert session.history[-1] is not original
    original.metadata.name = "modified old reference"
    assert session.history[-1].metadata.name != original.metadata.name
    assert doc_context.current_request_revision() == revision + 1
    assert doc_context.current_request_feature_log_entry_id() == "earlier-entry"
