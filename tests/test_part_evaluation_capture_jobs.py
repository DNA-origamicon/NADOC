"""Explicit evaluation captures use fixed policy inside the host state lock."""

from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import part_evaluation_capture as policy, part_evaluation_jobs as jobs, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_history_verification import _slot
from backend.core.models import Design
from backend.core.part_verification_capture import CaptureLimit
from tests.test_part_evaluation_capture import source


@pytest.fixture
def document():
    identity = f"__evaluation_capture_test__{uuid4()}"
    token = set_current_doc(identity)
    state.load_design(source())
    try:
        yield identity
    finally:
        with state._lock:
            state._sessions.pop(identity, None)
        reset_current_doc(token)


def body(operation="verify"):
    revision = state.revision()
    if operation == "repair":
        return {"operation": operation, "repair": {"repair_version": 1,
            "expected_design_id": state.get_or_404().id, "expected_revision": revision,
            "actions": [{"action": "set_input", "feature_id": "coating-row", "parameter_path": ["seed"],
                         "expected_old": 1, "value": 2}]}}
    if operation == "selection":
        return {"operation": operation, "selection": {"selection_version": 1,
            "expected_design_id": state.get_or_404().id, "expected_revision": revision,
            "feature_id": "coating-row", "parameter_path": ["nanoparticle_id"], "expected_old": "gold"}}
    return {"operation": operation, "expected_revision": revision,
            **({"index": 1, "params": {"seed": 2}} if operation == "edit" else {})}


@pytest.fixture
def submitted(monkeypatch):
    received = []

    class Worker:
        def __init__(self, captured, operation):
            self.captured = captured
            received.append((captured, operation))

        def start(self):
            pass

        def wait(self, _timeout):
            return True

        def result(self):
            # This fixture exercises transport/publication, not numerical proof.
            return {"status": "ready", "issues": [], "candidate": self.captured.model_dump(mode="json")}

        def is_alive(self):
            return False

        def close(self):
            pass

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    before = set(jobs._jobs)
    yield received
    with jobs._lock:
        for identity in set(jobs._jobs) - before:
            jobs._jobs.pop(identity)


def test_state_seam_captures_source_revision_and_fixed_profile_under_same_lock(document, monkeypatch):
    live, revision = state.get_design_with_revision()
    observed = []

    def capture(design, **options):
        assert state._lock.locked()
        observed.append((design, options))
        return design.model_copy(deep=True)

    monkeypatch.setattr(policy, "capture", capture)
    original, isolated, captured_revision = state.capture_design_for_evaluation(body())
    assert original is live and isolated is not live and captured_revision == revision
    assert observed == [(live, {"preserve_entry_types": True, **policy.COATING_PROFILE})]
    isolated.nanoparticles[0].diameter_nm = 77
    assert live.nanoparticles[0].diameter_nm == 20


def test_busy_admission_precedes_any_evaluation_capture(document, monkeypatch):
    request = body()
    monkeypatch.setattr(state, "capture_design_for_evaluation", lambda *_a: pytest.fail("Busy job captured"))
    assert _slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as error:
            jobs.start(request)
        assert error.value.status_code == 429
    finally:
        _slot.release()


@pytest.mark.parametrize("operation,guard,code", [("verify", "revision", "source_changed"),
    ("repair", "revision", "repair_conflict"), ("repair", "design", "repair_conflict"),
    ("selection", "revision", "selection_conflict"), ("selection", "design", "selection_conflict")])
def test_stale_guards_fail_before_scope_or_copy_and_are_actionable_409(document, monkeypatch, operation, guard, code):
    request = body(operation)
    target = request if operation == "verify" else request[operation]
    key = "expected_revision" if guard == "revision" else "expected_design_id"
    target[key] = target[key] - 1 if guard == "revision" else "other-part"
    monkeypatch.setattr(policy, "_scope", lambda *_a: pytest.fail("Stale scope inspected"))
    monkeypatch.setattr(policy, "capture", lambda *_a, **_k: pytest.fail("Stale source copied"))
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Stale worker submitted"))
    original, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 409 and error.value.detail["code"] == code
    assert state.get_design_with_revision() == (original, revision)
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.mark.parametrize("fault,code", [("missing_revision", "invalid_capture_context"),
    ("additional_geometry", "unsupported_coating_scope"), ("selection", "unsupported_reference_slot")])
def test_unsupported_coating_capture_is_422_without_copy_or_worker(document, monkeypatch, fault, code):
    request = body("selection" if fault == "selection" else "verify")
    if fault == "missing_revision":
        request.pop("expected_revision")
    elif fault == "additional_geometry":
        state.get_or_404().protein_assets = [object()]
    monkeypatch.setattr(policy, "capture", lambda *_a, **_k: pytest.fail("Unsupported source copied"))
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Unsupported worker submitted"))
    with pytest.raises(HTTPException) as error:
        jobs.start(request)
    assert error.value.status_code == 422 and error.value.detail["code"] == code
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_capture_limit_is_413_without_retry_and_no_job_is_retained(document, monkeypatch):
    calls = []

    def refusal(*_a, **kwargs):
        calls.append(kwargs)
        raise CaptureLimit("Coating capture exceeded fixed work allowance")

    monkeypatch.setattr(policy, "capture", refusal)
    monkeypatch.setattr(jobs, "_submit", lambda *_a: pytest.fail("Refused capture submitted"))
    before = set(jobs._jobs)
    with pytest.raises(HTTPException) as error:
        jobs.start(body())
    assert error.value.status_code == 413
    assert calls == [{"preserve_entry_types": True, **policy.COATING_PROFILE}]
    assert set(jobs._jobs) == before
    assert _slot.acquire(blocking=False)
    _slot.release()


def test_poll_does_not_recapture_and_captured_source_guards_survive_profile_selection(document, submitted, monkeypatch):
    original, revision = state.get_design_with_revision()
    identity = jobs.start(body("edit"))["job_id"]
    assert submitted[0][0] is not original
    assert submitted[0][1]["header"]["source_revision"] == revision
    monkeypatch.setattr(state, "capture_design_for_evaluation", lambda *_a: pytest.fail("Polling copied source"))
    for _ in range(3):
        assert jobs.inspect(identity)["result"]["status"] == "ready"
    state.load_design(original.model_copy(deep=True))
    assert jobs.inspect(identity)["stale"]
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409


def test_ordinary_capture_keeps_defaults_and_verifier_never_uses_coating_profile(document, monkeypatch):
    from backend.core import part_verification_capture
    state.load_design(Design())
    calls = []

    def capture(design, **options):
        calls.append(options)
        return design

    monkeypatch.setattr(policy, "capture", capture)
    state.capture_design_for_evaluation({"operation": "verify"})
    assert calls == [{"preserve_entry_types": True}]
    calls.clear()
    monkeypatch.setattr(part_verification_capture, "capture", capture)
    state.load_design(source())
    state.capture_design_for_verification()
    assert calls == [{"preserve_entry_types": False}]


def test_capture_holds_revision_pair_until_copy_finishes_without_worker_under_lock(document, monkeypatch):
    entered, release, reader_done = Event(), Event(), Event()
    original, revision = state.get_design_with_revision()
    results, errors = [], []
    request = body()

    def capture(design, **_options):
        entered.set()
        assert release.wait(5)
        return design.model_copy(deep=True)

    monkeypatch.setattr(policy, "capture", capture)

    def run_capture():
        token = set_current_doc(document)
        try:
            results.append(state.capture_design_for_evaluation(request))
        except BaseException as error:
            errors.append(error)
        finally:
            reset_current_doc(token)

    def read_revision():
        token = set_current_doc(document)
        try:
            results.append(state.revision())
            reader_done.set()
        finally:
            reset_current_doc(token)

    thread = Thread(target=run_capture)
    reader = Thread(target=read_revision)
    thread.start()
    try:
        assert entered.wait(5)
        assert state.verification_source_matches(document, original, revision, blocking=False) is None
        reader.start()
        assert not reader_done.is_set()
    finally:
        release.set()
        thread.join(5)
        if reader.ident is not None:
            reader.join(5)
    assert not errors and not thread.is_alive() and not reader.is_alive()
    assert any(type(value) is int and value == revision for value in results)
    pair = next(value for value in results if isinstance(value, tuple))
    assert pair[0] is original and pair[1] is not original and pair[2] == revision


@pytest.mark.parametrize("operation", ["append", "edit"])
@pytest.mark.parametrize("field", ["feature_identity", "source_descriptor", "source_table", "root"])
def test_all_publishable_operations_preserve_exact_recipe_transport(document, submitted, monkeypatch, operation, field):
    # Append is a deliberately ordinary source here: no public coating append
    # has been admitted. The test double isolates the parent transport guard.
    if operation == "append":
        state.load_design(source(coated=False).copy_with(feature_log=[]))
        request = {"operation": "append", "kind": "duplex-relax", "params": {}}
    else:
        request = body("edit")
    identity = jobs.start(request)["job_id"]
    if operation == "append":
        with jobs._lock:
            jobs._jobs[identity].result["candidate"]["feature_log"] = [source().feature_log[1].model_dump(mode="json")]
    original, revision = state.get_design_with_revision()
    depth, redo = state.undo_depth(), state.redo_depth()
    validate = Design.model_validate

    def changed(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        if field == "feature_identity":
            candidate.feature_log[0].id = "rewritten"
        elif field == "source_descriptor":
            row = next(row for row in candidate.feature_log if "pdb_source" in row.params)
            row.params["pdb_source"]["sha256"] = "f" * 64
        elif field == "source_table":
            from backend.core.part_input_sources import EmbeddedInput
            candidate.input_sources["f" * 64] = EmbeddedInput(data_b64="AAAA")
        else:
            candidate.recipe_root = candidate.recipe_root.model_copy(update={"initial_name": "Other root"})
        return candidate

    monkeypatch.setattr(Design, "model_validate", changed)
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409
    assert jobs.inspect(identity)["result"]["issues"] == [{"code": "candidate_decode_changed_recipe"}]
    assert state.get_design_with_revision() == (original, revision)
    assert (state.undo_depth(), state.redo_depth()) == (depth, redo)


def test_decoder_cannot_hide_authoring_mutation_through_nested_any_alias(document, submitted, monkeypatch):
    state.get_or_404().nanoparticles[0].coating.protein.metadata["nested"] = {"values": [1]}
    identity = jobs.start(body("edit"))["job_id"]
    original, revision = state.get_design_with_revision()
    validate = Design.model_validate

    def changed(*args, **kwargs):
        candidate = validate(*args, **kwargs)
        candidate.nanoparticles[0].coating.protein.metadata["nested"]["values"].append(2)
        return candidate

    monkeypatch.setattr(Design, "model_validate", changed)
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409
    assert jobs.inspect(identity)["result"]["issues"] == [{"code": "candidate_decode_changed_authoring"}]
    assert state.get_design_with_revision() == (original, revision)
    assert original.nanoparticles[0].coating.protein.metadata["nested"] == {"values": [1]}
