"""Private editor leases own inputs and never use seek/temporary mutations."""

from copy import deepcopy
from threading import Event, Thread
from uuid import uuid4
from weakref import ref

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history
from tests.test_part_deformation_preview import native_source, patch


def service():
    from backend.api import part_deformation_preview_sessions
    return part_deformation_preview_sessions


class Timer:
    def __init__(self, interval, callback):
        self.interval, self.callback = interval, callback
        self.cancelled = False
        self.daemon = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def document(monkeypatch):
    host = service()
    monkeypatch.setattr(host, "Timer", Timer)
    source = native_source()
    identity = f"private-deformation-preview-{uuid4()}"
    prior_revision = doc_context.current_request_revision()
    prior_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(identity)
    try:
        state.load_design(source)
        del source
        yield host, identity
    finally:
        try:
            host.clear_for_testing()
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(prior_revision)
            doc_context.set_request_feature_log_entry_id(prior_entry)


def opening(**changes):
    source, revision = state.get_design_with_revision()
    return {"preview_id": str(uuid4()), "expected_design_id": source.id,
            "expected_revision": revision, "feature_id": "edited-feature", **changes}


def update(opened, *, sequence=1, params=None):
    return {key: opened[key] for key in (
        "preview_id", "lease_id", "expected_design_id", "expected_revision", "feature_id",
    )} | {"request_sequence": sequence, "params": patch("bend") if params is None else params}


def cancellation(value):
    return {key: value[key] for key in (
        "preview_id", "expected_design_id", "expected_revision", "feature_id", "lease_id",
    ) if key in value}


def checkpoint():
    source, revision = state.get_design_with_revision()
    with state._lock:
        current = state._session()
        return {"source": source, "json": source.model_dump(mode="json"), "revision": revision,
                "history": tuple(current.history), "redo": tuple(current.redo),
                "request_revision": doc_context.current_request_revision(),
                "request_entry": doc_context.current_request_feature_log_entry_id()}


def unchanged(before):
    after = checkpoint()
    assert after["source"] is before["source"]
    assert after["json"] == before["json"]
    for name in ("revision", "history", "redo", "request_revision", "request_entry"):
        assert after[name] == before[name]


def test_prepare_repeated_evaluate_and_cancel_preserve_exact_document_and_stacks(document):
    host, _ = document
    state.set_design(state.get_or_404().copy_with())
    state.undo()
    before = checkpoint()
    assert before["redo"]
    opened = host.prepare(opening())
    assert opened["source_equivalence_checked"] is False
    assert opened["downstream_evaluated"] is False
    for sequence in (1, 2, 3):
        result = host.evaluate(update(opened, sequence=sequence))
        assert result["request_sequence"] == sequence
        assert result["candidate"]["display_topology"]["deformations"][-1]["id"] == "preview-operation"
    host.cancel(cancellation(opened))
    unchanged(before)
    with pytest.raises(HTTPException) as caught:
        host.evaluate(update(opened, sequence=4))
    assert caught.value.status_code == 409


def test_apply_uses_fresh_input_proof_one_undo_and_stable_feature_identity(document):
    host, _ = document
    before = checkpoint()
    opened = host.prepare(opening())
    receipt = host.apply(update(opened))
    assert receipt["status"] == "applied"
    assert receipt["revision"] == before["revision"] + 1
    current = state.get_or_404()
    assert current.feature_log[-1].id == "edited-feature"
    assert current.feature_log[-1].deformation_id == "preview-operation"
    assert current.deformations[-1].params.curvature_deg_per_bp == .5
    assert state.undo_depth() == len(before["history"]) + 1
    assert assess_part_history(current, execute=execute, dependencies=dependencies)["status"] == "verified"
    assert before["source"].model_dump(mode="json") == before["json"]
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
    state.redo()
    assert state.get_or_404().deformations[-1].params.curvature_deg_per_bp == .5
    with pytest.raises(HTTPException):
        host.apply(update(opened, sequence=2))


@pytest.mark.parametrize("operation", ["evaluate", "apply"])
@pytest.mark.parametrize("change", ["revision", "same_revision_source", "session_aba"])
def test_original_source_and_session_binding_refuse_stale_work(document, operation, change):
    host, identity = document
    opened = host.prepare(opening())
    source, revision = state.get_design_with_revision()
    if change == "revision":
        state.set_design(source.copy_with())
    elif change == "same_revision_source":
        with state._lock:
            state._session().design = source.copy_with()
    else:
        state.drop_doc(identity)
        with state._lock:
            session = state._session()
            session.design, session.revision = source, revision
    before = checkpoint()
    with pytest.raises(HTTPException) as caught:
        getattr(host, operation)(update(opened))
    assert caught.value.status_code == 409
    unchanged(before)


def test_doc_switch_never_uses_another_documents_token(document):
    host, _ = document
    opened = host.prepare(opening())
    token = doc_context.set_current_doc(f"other-preview-{uuid4()}")
    try:
        with pytest.raises(HTTPException) as caught:
            host.evaluate(update(opened))
        assert caught.value.status_code == 409
    finally:
        doc_context.reset_current_doc(token)
    assert host.evaluate(update(opened))["request_sequence"] == 1


def test_cancel_before_prepare_has_bounded_tombstone_and_never_captures(document, monkeypatch):
    host, _ = document
    request = opening()
    host.cancel(cancellation(request))
    monkeypatch.setattr(host, "capture", lambda *_a, **_k: pytest.fail("Captured a cancelled opening"))
    with pytest.raises(HTTPException) as caught:
        host.prepare(request)
    assert caught.value.status_code == 409
    for _ in range(40):
        host.cancel(cancellation(opening()))
    assert len(host._tombstones) <= host.MAX_TOMBSTONES


def test_expiry_releases_prefix_without_a_followup_request(document, monkeypatch):
    host, identity = document
    clock = [10.0]
    monkeypatch.setattr(host, "monotonic", lambda: clock[0])
    opened = host.prepare(opening())
    entry = host._entries[identity]
    prepared = ref(entry.prepared._prefix)
    timer = entry.timer
    clock[0] += host.TTL_SECONDS + 1
    timer.callback()
    assert identity not in host._entries
    assert prepared() is None
    assert timer.cancelled
    with pytest.raises(HTTPException):
        host.evaluate(update(opened))


def test_catalog_does_not_retain_live_design_and_cancel_releases_owned_prefix(document):
    host, identity = document
    opened = host.prepare(opening())
    source = state.get_or_404()
    original = ref(source)
    retained = ref(host._entries[identity].prepared._prefix)
    state.drop_doc(identity)
    del source
    assert original() is None
    host.cancel(cancellation(opened))
    assert retained() is None


def test_failed_apply_keeps_unchanged_preview_usable(document, monkeypatch):
    host, _ = document
    opened = host.prepare(opening())
    before = checkpoint()
    with monkeypatch.context() as fault:
        fault.setattr(host, "prepare_change", lambda *_a, **_k: (_ for _ in ()).throw(
            HTTPException(409, detail="Downstream failure")))
        with pytest.raises(HTTPException, match="Downstream failure"):
            host.apply(update(opened))
    unchanged(before)
    assert host.evaluate(update(opened, sequence=2))["candidate"]["display_topology"]["strands"]


def test_publication_failure_restores_exact_state_and_keeps_preview(document, monkeypatch):
    host, _ = document
    opened = host.prepare(opening())
    before = checkpoint()
    original = state._bump_revision

    def fault(session):
        original(session)
        raise RuntimeError("Publication fault")

    with monkeypatch.context() as scoped:
        scoped.setattr(state, "_bump_revision", fault)
        with pytest.raises(RuntimeError, match="Publication fault"):
            host.apply(update(opened))
    unchanged(before)
    assert host.evaluate(update(opened, sequence=2))["candidate"]["display_topology"]["strands"]


def test_late_evaluation_after_cancel_never_returns_a_preview(document, monkeypatch):
    host, identity = document
    opened = host.prepare(opening())
    started, release = Event(), Event()
    original = host.local_evaluate
    result = []

    def held(*args, **kwargs):
        assert not host._lock.locked(), "Catalog lock held during native evaluation"
        assert not state._lock.locked(), "State lock held during native evaluation"
        started.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    def run():
        token = doc_context.set_current_doc(identity)
        try:
            result.append(host.evaluate(update(opened)))
        except BaseException as error:
            result.append(error)
        finally:
            doc_context.reset_current_doc(token)

    before = checkpoint()
    monkeypatch.setattr(host, "local_evaluate", held)
    thread = Thread(target=run)
    thread.start()
    try:
        assert started.wait(2)
        host.cancel(cancellation(opened))
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert len(result) == 1 and isinstance(result[0], HTTPException)
    assert result[0].status_code == 409
    unchanged(before)


def test_request_and_response_objects_cannot_mutate_retained_inputs(document):
    host, _ = document
    request = opening()
    opened = host.prepare(request)
    request["feature_id"] = "replacement"
    result = host.evaluate(update(opened))
    result["candidate"]["nucleotides"][0][4][0] += 100
    result["candidate"]["display_topology"]["strands"][0]["domains"].clear()
    opened["control_context"]["strands"].clear()
    again = host.evaluate(update(opened, sequence=2))
    assert again["candidate"]["nucleotides"][0][4][0] != result["candidate"]["nucleotides"][0][4][0]
    assert again["candidate"]["display_topology"]["strands"][0]["domains"]


def test_old_server_lease_cannot_attach_to_reused_nonce(document, monkeypatch):
    host, identity = document
    clock = [10.0]
    monkeypatch.setattr(host, "monotonic", lambda: clock[0])
    request = opening()
    first = host.prepare(request)
    host.cancel(cancellation(first))
    clock[0] += host.TTL_SECONDS + 1
    second = host.prepare(deepcopy(request))
    assert second["lease_id"] != first["lease_id"]
    with pytest.raises(HTTPException):
        host.evaluate(update(first))
    assert host._entries[identity].lease_id == second["lease_id"]
    assert host.evaluate(update(second))["request_sequence"] == 1


@pytest.mark.parametrize("fail", [False, True])
def test_commit_reservation_reports_cancel_honestly_and_survives_expiry(document, monkeypatch, fail):
    host, identity = document
    opened = host.prepare(opening())
    entry = host._entries[identity]
    before = checkpoint()
    started, release = Event(), Event()
    original = host.publish_replacement
    result = []

    def held(*args, **kwargs):
        assert state._lock.locked()
        assert not host._lock.locked(), "Catalog lock held during full-source undo copy"
        started.set()
        assert release.wait(2)
        if fail:
            raise RuntimeError("Reserved publication failed")
        return original(*args, **kwargs)

    def run():
        token = doc_context.set_current_doc(identity)
        try:
            result.append(host.apply(update(opened)))
        except BaseException as error:
            result.append(error)
        finally:
            doc_context.reset_current_doc(token)

    monkeypatch.setattr(host, "publish_replacement", held)
    thread = Thread(target=run)
    thread.start()
    try:
        assert started.wait(2)
        assert host.cancel(cancellation(opened))["status"] == "commit_in_progress"
        entry.timer.callback()
        assert host._entries[identity] is entry
        assert entry.phase == "committing"
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert identity not in host._entries
    if fail:
        assert isinstance(result[0], RuntimeError)
        unchanged(before)
    else:
        assert result[0]["status"] == "applied"
        assert state.revision() == before["revision"] + 1
        assert state.undo_depth() == len(before["history"]) + 1


def test_newer_busy_request_supersedes_inflight_result_without_queueing(document, monkeypatch):
    host, identity = document
    opened = host.prepare(opening())
    started, release = Event(), Event()
    original = host.local_evaluate
    results = []

    def held(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    def run():
        token = doc_context.set_current_doc(identity)
        try:
            results.append(host.evaluate(update(opened)))
        except BaseException as error:
            results.append(error)
        finally:
            doc_context.reset_current_doc(token)

    with monkeypatch.context() as scoped:
        scoped.setattr(host, "local_evaluate", held)
        thread = Thread(target=run)
        thread.start()
        try:
            assert started.wait(2)
            with pytest.raises(HTTPException) as caught:
                host.evaluate(update(opened, sequence=2))
            assert caught.value.status_code == 429
            assert host._entries[identity].sequence == 2
        finally:
            release.set()
            thread.join(2)
    assert not thread.is_alive()
    assert isinstance(results[0], HTTPException) and results[0].status_code == 409
    assert host.evaluate(update(opened, sequence=3))["request_sequence"] == 3


def test_two_document_capacity_and_one_prepared_prefix_per_document(document):
    host, first_doc = document
    first = host.prepare(opening())
    replacement = host.prepare(opening())
    assert first["lease_id"] != replacement["lease_id"]
    assert len(host._entries) == 1
    others = [f"private-preview-capacity-{uuid4()}" for _ in range(2)]
    try:
        token = doc_context.set_current_doc(others[0])
        try:
            state.load_design(native_source())
            second = host.prepare(opening())
        finally:
            doc_context.reset_current_doc(token)
        token = doc_context.set_current_doc(others[1])
        try:
            state.load_design(native_source())
            with pytest.raises(HTTPException) as caught:
                host.prepare(opening())
            assert caught.value.status_code == 429
            assert len(host._entries) == host.MAX_SESSIONS == 2
        finally:
            doc_context.reset_current_doc(token)
        token = doc_context.set_current_doc(others[0])
        try:
            host.cancel(cancellation(second))
        finally:
            doc_context.reset_current_doc(token)
        assert list(host._entries) == [first_doc]
    finally:
        for identity in others:
            state.drop_doc(identity)


def test_no_full_history_edit_is_called_on_prepare_or_sliders(document, monkeypatch):
    host, _ = document
    monkeypatch.setattr(host, "prepare_change", lambda *_a, **_k: pytest.fail("Full edit on slider"))
    opened = host.prepare(opening())
    assert host.evaluate(update(opened))["candidate"]["display_topology"]["strands"]


def test_cancel_during_prepare_rejects_late_result(document, monkeypatch):
    host, identity = document
    request = opening()
    started, release = Event(), Event()
    original = host.prepare_from_capture
    results = []

    def held(*args, **kwargs):
        assert not host._lock.locked() and not state._lock.locked()
        started.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    def run():
        token = doc_context.set_current_doc(identity)
        try:
            results.append(host.prepare(request))
        except BaseException as error:
            results.append(error)
        finally:
            doc_context.reset_current_doc(token)

    before = checkpoint()
    monkeypatch.setattr(host, "prepare_from_capture", held)
    thread = Thread(target=run)
    thread.start()
    try:
        assert started.wait(2)
        assert host.cancel(cancellation(request))["status"] == "cancelled"
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert isinstance(results[0], HTTPException) and results[0].status_code == 409
    assert identity not in host._entries
    unchanged(before)


def test_controls_only_uses_strict_boolean_and_never_allocates_geometry(document, monkeypatch):
    from backend.core import design_geometry

    host, _ = document
    opened = host.prepare(opening())
    monkeypatch.setattr(design_geometry, "_geometry_for_design",
                        lambda *_a, **_k: pytest.fail("Controls-only request allocated geometry"))
    result = host.evaluate({**update(opened), "include_geometry": False})
    assert result["candidate"] is None
    assert result["feasibility"]
    with pytest.raises(HTTPException) as caught:
        host.evaluate({**update(opened, sequence=2), "include_geometry": 0})
    assert caught.value.status_code == 422


def test_complete_envelope_budget_and_projection_are_outside_locks(document, monkeypatch):
    from backend.api import part_deformation_preview_dto as dto

    host, _ = document
    original = host.bound_display
    bounded = []

    def observe(value):
        assert not state._lock.locked() and not host._lock.locked()
        assert {"preview_id", "lease_id", "feature_id", "expected_revision"} <= value.keys()
        bounded.append(True)
        return original(value)

    monkeypatch.setattr(host, "bound_display", observe)
    opened = host.prepare(opening())
    before = checkpoint()
    with monkeypatch.context() as small:
        small.setattr(host, "evaluate_display", lambda *_a, **_k: {"candidate": None})
        small.setattr(dto, "MAX_OUTPUT_BYTES", 50)
        with pytest.raises(HTTPException) as caught:
            host.evaluate(update(opened))
    assert caught.value.status_code == 413
    assert len(bounded) == 2
    unchanged(before)
    assert host.evaluate(update(opened, sequence=2))["candidate"]


def test_policy_generation_cannot_revive_old_lease_after_compatibility_roundtrip(document):
    from backend.api import part_publication_policy as policy

    host, identity = document
    opened = host.prepare(opening())
    original = policy.current_configuration()
    try:
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(
            default_mode=original.default_mode,
            document_modes={**original.document_modes, identity: "registered_only"},
        ))
        state.configure_part_publication_policy(original)
        with pytest.raises(HTTPException) as caught:
            host.evaluate(update(opened))
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "policy_changed"
    finally:
        state.configure_part_publication_policy(original)


def test_apply_deadline_rechecked_at_final_publication_lock(document, monkeypatch):
    host, _ = document
    clock = [0.0]
    monkeypatch.setattr(host, "monotonic", lambda: clock[0])
    opened = host.prepare(opening())
    before = checkpoint()
    original_prepare, original_current = host.prepare_change, host._current
    ready = [False]

    def completed(*args, **kwargs):
        value = original_prepare(*args, **kwargs)
        ready[0] = True
        return value

    def waited(*args, **kwargs):
        value = original_current(*args, **kwargs)
        if ready[0]:
            # Simulate scheduling/lock wait after the last external checkpoint,
            # without sleeps or a timing-dependent performance assertion.
            clock[0] = host.APPLY_SECONDS + 1
        return value

    monkeypatch.setattr(host, "prepare_change", completed)
    monkeypatch.setattr(host, "_current", waited)
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened))
    assert caught.value.status_code == 408
    unchanged(before)
    assert host.evaluate(update(opened, sequence=2))["candidate"]
