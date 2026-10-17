"""Source publication is metadata-only and uses existing document ownership."""

from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, part_repair_source_host as host, state
from backend.core.models import DesignLoadout
from backend.core.part_input_sources import EmbeddedInput
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from tests.test_part_repair_sources import NEW, OLD, descriptor, selection, source


@pytest.fixture
def document():
    identity = f"__repair_source__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    prior_revision = doc_context.current_request_revision()
    prior_entry = doc_context.current_request_feature_log_entry_id()
    state.load_design(source())
    try:
        yield identity
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(prior_revision)
        doc_context.set_request_feature_log_entry_id(prior_entry)


def request(*, operation="stage_proposed", **changes):
    design, revision = state.get_design_with_revision()
    return selection(design, operation=operation, expected_revision=revision, **changes)


def upload_ready(body=None, raw=NEW):
    receipt = host.inspect_source(request() if body is None else body)
    captured = host.capture_source_request(receipt, mutation=True)
    prepared, response = host.prepare_upload(captured, raw)
    return captured, prepared, response


def test_source_staging_preserves_exact_proposal_geometry_and_history(document, monkeypatch):
    before, revision = state.get_design_with_revision()
    draft, geometry, log = before.repair_draft, before.helices, before.feature_log
    snapshot = state.undo_depth()
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Source took geometry snapshot"))
    monkeypatch.setattr(state, "validate_design", lambda *_: pytest.fail("Source validated geometry"))
    ready = upload_ready()
    result = host.publish_upload(*ready)
    after = state.get_or_404()
    assert after is not before and before.input_sources == {}
    assert after.repair_draft is draft and after.helices is geometry and after.feature_log is log
    assert after.input_sources[descriptor(NEW).sha256].data_b64
    assert state.undo_depth() == snapshot and state.revision() == revision + 1
    assert result["repair_draft"]["status"] == "pending"
    assert result["repair_draft"]["base_status"] == "unchecked"
    assert result["published_source_changed"] is False
    assert repair_base_fingerprint(after) == draft.base


def test_restore_does_not_silently_rebase_or_repair_proposed_definition(document):
    current = state.get_or_404()
    current.input_sources[descriptor(OLD).sha256] = EmbeddedInput(data_b64="corrupt")
    current.repair_draft.actions[0].expected_old["format"] = "obsolete input expectation"
    draft = current.repair_draft
    result = host.publish_upload(*upload_ready(request(operation="restore_published"), OLD))
    assert result["published_source_changed"]
    assert result["repair_draft"]["base_status"] == "rebase_required"
    assert state.get_or_404().repair_draft is draft
    assert draft.actions[0].expected_old["format"] == "obsolete input expectation"
    assert repair_base_fingerprint(state.get_or_404()) != draft.base


@pytest.mark.parametrize("change", ["revision", "design", "draft_generation", "discard", "reopen", "doc"])
def test_final_compare_and_swap_refuses_concurrent_changes(document, change):
    ready = upload_ready()
    captured = ready[0]
    token = None
    with state._lock:
        session = state._session()
        if change == "revision":
            session.revision += 1
        elif change == "design":
            session.design = session.design.model_copy()
        elif change == "draft_generation":
            session.design.repair_draft = session.design.repair_draft.model_copy(update={"generation": 5})
        elif change == "discard":
            session.design.repair_draft = None
        elif change == "reopen":
            state._sessions[document] = type(session)(design=session.design, revision=session.revision)
        else:
            token = doc_context.set_current_doc("another-source-tab")
    try:
        with pytest.raises(HTTPException) as error:
            host.publish_upload(*ready)
        assert error.value.status_code == 409
        assert descriptor(NEW).sha256 not in captured.source.input_sources
        assert descriptor(NEW).sha256 not in state._sessions[document].design.input_sources
    finally:
        if token is not None:
            doc_context.reset_current_doc(token)


def test_source_changed_after_receipt_refuses_before_body_work(document):
    body = host.inspect_source(request(operation="restore_published"))
    state.get_or_404().input_sources[descriptor(OLD).sha256] = EmbeddedInput(data_b64="new corruption")
    with pytest.raises(HTTPException) as error:
        host.capture_source_request(body, mutation=True)
    assert error.value.detail["code"] == "source_blob_conflict"


def test_hashing_and_schema_admission_happen_outside_lock(document, monkeypatch):
    def outside(original):
        def check(*args, **kwargs):
            assert not state._lock.locked()
            return original(*args, **kwargs)
        return check
    monkeypatch.setattr(host, "select_source", outside(host.select_source))
    monkeypatch.setattr(host, "blob_expectation", outside(host.blob_expectation))
    monkeypatch.setattr(host, "check_blob_expectation", outside(host.check_blob_expectation))
    monkeypatch.setattr(host, "_prepare_checked_source", outside(host._prepare_checked_source))
    host.publish_upload(*upload_ready())


def test_protected_loadout_allows_inspection_but_refuses_source_mutation(document):
    design = state.get_or_404()
    loadout = DesignLoadout(id="protected", name="Protected", protected=True)
    design.loadouts = [loadout]
    design.active_loadout_id = loadout.id
    body = host.inspect_source(request())
    before = state.revision()
    with pytest.raises(HTTPException) as error:
        host.capture_source_request(body, mutation=True)
    assert error.value.status_code == 409
    assert state.get_or_404() is design and state.revision() == before


class Cancelled(BaseException):
    pass


@pytest.mark.parametrize("fault", [RuntimeError, Cancelled])
@pytest.mark.parametrize("phase", ["copy", "bump"])
def test_publication_failure_rolls_back_exact_state_and_request_markers(document, monkeypatch, phase, fault):
    ready = upload_ready()
    before, revision = state.get_design_with_revision()
    doc_context.set_request_revision(42)
    doc_context.set_request_feature_log_entry_id("prior-entry")

    def fail(*_args, **_kwargs):
        state._session().revision = 900
        doc_context.set_request_revision(900)
        doc_context.set_request_feature_log_entry_id("partial")
        raise fault("source publication failed")

    if phase == "copy":
        monkeypatch.setattr(type(before), "model_copy", fail)
    else:
        monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(fault):
        host.publish_upload(*ready)
    assert state.get_or_404() is before and state.revision() == revision and before.input_sources == {}
    assert doc_context.current_request_revision() == 42
    assert doc_context.current_request_feature_log_entry_id() == "prior-entry"
    assert state.undo_depth() == 0


def test_cancel_after_lock_wait_prevents_publication(document):
    ready = upload_ready()
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        host.publish_upload(*ready, cancelled=lambda: True)
    assert error.value.status_code == 499
    assert state.get_or_404() is before and state.revision() == revision


def test_response_preparation_failure_has_no_hidden_mutation(document, monkeypatch):
    body = host.inspect_source(request())
    captured = host.capture_source_request(body, mutation=True)
    before, revision = state.get_design_with_revision()
    monkeypatch.setattr(host, "draft_summary", lambda *_: (_ for _ in ()).throw(RuntimeError("serialize")))
    with pytest.raises(RuntimeError, match="serialize"):
        host.prepare_upload(captured, NEW)
    assert state.get_or_404() is before and state.revision() == revision


def test_upload_hashes_old_immutable_bytes_only_once(document, monkeypatch):
    from backend.core import part_repair_sources as repair
    body = host.inspect_source(request())
    calls = []
    original = repair.blob_expectation
    def count(blob):
        calls.append(blob)
        return original(blob)
    monkeypatch.setattr(repair, "blob_expectation", count)
    upload = host.capture_source_request(body, mutation=True)
    prepared, response = host.prepare_upload(upload, NEW)
    host.publish_upload(upload, prepared, response)
    assert len(calls) == 1
