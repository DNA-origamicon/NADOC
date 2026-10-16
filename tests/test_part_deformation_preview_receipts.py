"""Scalar publication receipts share the bounded preview lease and its origin."""

from copy import deepcopy
from threading import Event, Thread
from weakref import ref

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state
from tests.test_part_deformation_preview_sessions import (
    cancellation, checkpoint, document as document, opening, unchanged, update,
)


def receipt_keys(value):
    return {key: value[key] for key in (
        "preview_id", "expected_design_id", "expected_revision", "lease_id", "feature_id",
        "deformation_id", "doc_id", "request_sequence", "design_id", "revision",
    )}


def test_status_tracks_ready_then_applied_without_republishing_or_retaining_prefix(document):
    host, identity = document
    before = checkpoint()
    opened = host.prepare(opening())
    request = cancellation(opened)
    ready = host.status(request)
    assert ready["status"] == "ready"
    assert ready["request_sequence"] == 0
    assert ready["feature_id"] == opened["feature_id"]
    entry = host._entries[identity]
    retained = ref(entry.prepared._prefix)
    deadline = entry.expires
    timer = entry.timer
    applied = host.apply(update(opened))
    assert set(applied) == {"status", *receipt_keys(applied)}
    assert all(type(value) in {str, int} for value in applied.values())
    assert applied["doc_id"] == identity and applied["request_sequence"] == 1
    assert applied["revision"] == before["revision"] + 1
    assert host._entries[identity] is entry
    assert entry.prepared is None and retained() is None
    assert entry.expires == deadline and entry.timer is timer
    assert not timer.cancelled
    status = host.status(request)
    assert status["status"] == "applied"
    assert set(status) == {*applied, "remaining_seconds"}
    assert receipt_keys(status) == receipt_keys(applied)
    assert "validation" not in status and "candidate" not in status and "design" not in status
    assert status["deformation_id"] == opened["deformation_id"]
    published = checkpoint()
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened, sequence=2))
    assert caught.value.status_code == 409
    unchanged(published)
    assert host.status(request)["request_sequence"] == 1


def test_applied_cancel_reports_publication_instead_of_claiming_undo(document):
    host, _ = document
    opened = host.prepare(opening())
    applied = host.apply(update(opened))
    before = checkpoint()
    cancelled = host.cancel(cancellation(opened))
    assert cancelled["status"] == "applied"
    assert set(cancelled) == {"status", *receipt_keys(cancelled)}
    assert receipt_keys(cancelled) == receipt_keys(applied)
    assert host.status(cancellation(opened))["status"] == "applied"
    unchanged(before)


def test_apply_receipt_does_not_traverse_an_already_computed_validation_report(document, monkeypatch):
    host, _ = document
    opened = host.prepare(opening())
    original = host.prepare_change

    class ReportNotForTransport:
        @property
        def passed(self):
            pytest.fail("Apply read a validation report already supplied by canonical refresh")

        @property
        def results(self):
            pytest.fail("Apply walked validation results outside its scalar receipt contract")

    def prepared(*args, **kwargs):
        candidate, _report = original(*args, **kwargs)
        return candidate, ReportNotForTransport()

    monkeypatch.setattr(host, "prepare_change", prepared)
    applied = host.apply(update(opened))
    assert set(applied) == {"status", *receipt_keys(applied)}
    assert host.status(cancellation(opened))["revision"] == applied["revision"]


@pytest.mark.parametrize("change", ["revision", "source", "session_aba", "policy"])
def test_applied_status_rechecks_published_source_and_session_before_any_refresh(document, change):
    from backend.api import part_publication_policy as policy

    host, identity = document
    opened = host.prepare(opening())
    host.apply(update(opened))
    configuration = policy.current_configuration()
    try:
        with state._lock:
            session = state._sessions[identity]
            if change == "revision":
                session.revision += 1
            elif change == "source":
                session.design = session.design.model_copy()
            elif change == "session_aba":
                state._sessions[identity] = state._DesignSession(
                    design=session.design, revision=session.revision)
        if change == "policy":
            state.configure_part_publication_policy(policy.HostPolicyConfiguration(
                default_mode=configuration.default_mode, document_modes={identity: "registered_only"}))
            state.configure_part_publication_policy(configuration)
        before = checkpoint()
        with pytest.raises(HTTPException) as caught:
            host.status(cancellation(opened))
        assert caught.value.status_code == 409
        unchanged(before)
    finally:
        state.configure_part_publication_policy(configuration)


def test_applied_receipt_does_not_retain_the_live_published_design(document):
    host, identity = document
    opened = host.prepare(opening())
    host.apply(update(opened))
    current = ref(state.get_or_404())
    state.drop_doc(identity)
    assert current() is None
    with pytest.raises(HTTPException) as caught:
        host.status(cancellation(opened))
    assert caught.value.status_code == 409


def test_applied_expiry_releases_receipt_without_extending_original_lease(document, monkeypatch):
    host, identity = document
    now = [10.0]
    monkeypatch.setattr(host, "monotonic", lambda: now[0])
    opened = host.prepare(opening())
    entry = host._entries[identity]
    expires = entry.expires
    now[0] += 3
    host.apply(update(opened))
    assert entry.expires == expires
    now[0] = expires + 1
    entry.timer.callback()
    assert identity not in host._entries
    with pytest.raises(HTTPException):
        host.status(cancellation(opened))


def test_status_is_an_owned_receipt_and_requires_exact_lease(document):
    host, _ = document
    opened = host.prepare(opening())
    applied = host.apply(update(opened))
    value = host.status(cancellation(opened))
    value["revision"] += 1
    assert host.status(cancellation(opened))["revision"] == applied["revision"]
    missing = deepcopy(cancellation(opened))
    missing.pop("lease_id")
    with pytest.raises(HTTPException) as caught:
        host.status(missing)
    assert caught.value.status_code == 422


def test_failed_apply_keeps_status_ready_and_original_bound_revision(document, monkeypatch):
    host, _ = document
    opened = host.prepare(opening())
    with monkeypatch.context() as fault:
        def refuse(*_a, **_k):
            raise HTTPException(409, detail="Downstream definition cannot regenerate")
        fault.setattr(host, "prepare_change", refuse)
        with pytest.raises(HTTPException):
            host.apply(update(opened))
    status = host.status(cancellation(opened))
    assert status["status"] == "ready"
    assert status["expected_revision"] == opened["expected_revision"]
    assert status["request_sequence"] == 1
    assert "revision" not in status and "design_id" not in status


def test_status_cannot_report_ready_while_original_apply_can_still_publish(document, monkeypatch):
    host, identity = document
    opened = host.prepare(opening())
    started, release = Event(), Event()
    original = host.prepare_change
    result = []

    def held(*args, **kwargs):
        assert not state._lock.locked() and not host._lock.locked()
        started.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    def run():
        token = doc_context.set_current_doc(identity)
        try:
            result.append(host.apply(update(opened)))
        except BaseException as error:
            result.append(error)
        finally:
            doc_context.reset_current_doc(token)

    monkeypatch.setattr(host, "prepare_change", held)
    thread = Thread(target=run)
    thread.start()
    try:
        assert started.wait(2)
        pending = host.status(cancellation(opened))
        assert pending["status"] == "applying" and pending["request_sequence"] == 1
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert result[0]["status"] == "applied"
    assert host.status(cancellation(opened))["status"] == "applied"
