"""Saved repair proposals change metadata without executing or copying geometry."""

from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, part_repair_drafts as drafts, state
from backend.api.routes_feature_log import router
from backend.core.models import DesignLoadout, SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_verification_capture import CaptureLimit


PATH = "/api/design/features/repair-draft"


@pytest.fixture
def document():
    identity = f"__draft_metadata__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    source = create_empty_part("Broken gold input", "HONEYCOMB")
    source.feature_log = [
        SnapshotLogEntry(id="create", op_kind="nanoparticle-create", label="Gold",
            params={"_proof_version": 1, "nanoparticle_version": 1,
                    "nanoparticle_id": "gold", "diameter_nm": 10.0}),
        SnapshotLogEntry(id="resize", op_kind="nanoparticle-patch", label="Resize",
            params={"_proof_version": 1, "nanoparticle_version": 1,
                    "nanoparticle_id": "missing", "diameter_nm": 12.0}),
    ]
    state.load_design(source)
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    try:
        with TestClient(app) as client:
            yield client, {"X-NADOC-Doc": identity}
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)


def request(operation="create", **extra):
    source, revision = state.get_design_with_revision()
    current = source.repair_draft
    body = {"draft_version": 1, "operation": operation,
            "expected_design_id": source.id, "expected_revision": revision,
            "expected_draft_id": None if current is None else current.draft_id,
            "expected_generation": None if current is None else current.generation}
    if operation in {"create", "update"}:
        body["actions"] = [{"action": "set_input", "feature_id": "resize",
            "parameter_path": ["nanoparticle_id"], "expected_old": "missing", "value": "gold"}]
    return {**body, **extra}


def post(document, body):
    client, headers = document
    return client.post(PATH, headers=headers, json=body)


def test_http_lifecycle_publishes_only_metadata_and_returns_independent_inputs(document, monkeypatch):
    source, revision = state.get_design_with_revision()
    monkeypatch.setattr(state, "_snapshot_copy", lambda *_a: pytest.fail("Metadata copied the whole part"))
    monkeypatch.setattr(state, "validate_design", lambda *_a: pytest.fail("Metadata validated geometry"))
    from backend.api import part_proof_commands
    monkeypatch.setattr(part_proof_commands, "execute", lambda *_a, **_k: pytest.fail("Metadata ran a builder"))
    result = post(document, request())
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["revision"] == revision + 1
    assert payload["repair_draft"] == {"version": 1, "draft_id": payload["draft"]["draft_id"],
        "generation": 0, "action_count": 1, "status": "pending", "base_status": "unchecked"}
    assert state.get_or_404().feature_log is source.feature_log
    assert state.get_or_404().helices is source.helices
    assert state.undo_depth() == 0
    payload["draft"]["actions"][0]["value"] = "client mutation"
    assert state.get_or_404().repair_draft.actions[0].value == "gold"
    updated = post(document, request("update"))
    assert updated.status_code == 200 and updated.json()["draft"]["generation"] == 1
    client, headers = document
    monkeypatch.setattr(drafts, "prepare_draft", lambda *_a, **_k: pytest.fail("Read prepared a proposal"))
    read = client.get(PATH, headers=headers)
    assert read.status_code == 200 and read.json() == updated.json()
    monkeypatch.undo()
    discarded = post(document, request("discard"))
    assert discarded.status_code == 200 and discarded.json()["draft"] is None
    assert state.revision() == revision + 3 and state.undo_depth() == 0
    assert state.get_or_404().feature_log is source.feature_log


@pytest.mark.parametrize("field,value", [
    ("expected_revision", 0), ("expected_design_id", "another-part"),
])
def test_stale_document_guard_precedes_capture(document, monkeypatch, field, value):
    source, revision = state.get_design_with_revision()
    monkeypatch.setattr(drafts, "capture_draft_inputs", lambda *_a, **_k: pytest.fail("Stale request captured inputs"))
    result = post(document, request(**{field: value}))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "draft_conflict"
    assert state.get_design_with_revision() == (source, revision)


def test_draft_identity_and_generation_prevent_overwrite(document):
    assert post(document, request()).status_code == 200
    source, revision = state.get_design_with_revision()
    for changes in ({"expected_generation": 99}, {"expected_draft_id": "replaced"}):
        result = post(document, request("update", **changes))
        assert result.status_code == 409
    assert state.get_design_with_revision() == (source, revision)


def test_definition_change_needs_explicit_rebase_with_original_expectations(document):
    assert post(document, request()).status_code == 200
    source = state.get_or_404()
    changed = source.model_copy(deep=True)
    changed.feature_log[0].params["diameter_nm"] = 11.0
    state.set_design(changed)
    result = post(document, request("update"))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "draft_rebase_required"
    result = post(document, request("rebase"))
    assert result.status_code == 200 and result.json()["draft"]["generation"] == 1
    assert state.get_or_404().repair_draft.actions[0].expected_old == "missing"


@pytest.mark.parametrize("race", ["source", "revision", "reopen"])
def test_compare_and_swap_rejects_changes_during_unlocked_preparation(document, monkeypatch, race):
    original = drafts.prepare_draft
    raced = []

    def prepare(*args, **kwargs):
        # A real lock probe proves expensive preparation is outside the lock.
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        prepared = original(*args, **kwargs)
        with state._lock:
            session = state._session()
            if race == "source":
                session.design = session.design.copy_with(name="Concurrent edit")
            elif race == "revision":
                state._bump_revision(session)
            else:
                state._sessions[doc_context.get_current_doc()] = replace(session)
            raced.append((state._session().design, state._session().revision))
        return prepared

    monkeypatch.setattr(drafts, "prepare_draft", prepare)
    result = post(document, request())
    assert result.status_code == 409 and result.json()["detail"]["code"] == "draft_conflict"
    assert state.get_design_with_revision() == raced[0]
    assert state.get_or_404().repair_draft is None


def test_capture_refusal_is_atomic_and_never_prepares(document, monkeypatch):
    source, revision = state.get_design_with_revision()
    def refuse(*_args, **_kwargs):
        raise CaptureLimit("Injected bounded capture refusal")
    monkeypatch.setattr(drafts, "capture_draft_inputs", refuse)
    monkeypatch.setattr(drafts, "prepare_draft", lambda *_a, **_k: pytest.fail("Refused capture prepared"))
    result = post(document, request())
    assert result.status_code == 413 and result.json()["detail"]["code"] == "draft_capture_limit"
    assert state.get_design_with_revision() == (source, revision)


def test_publication_failure_rolls_back_exact_source_revision_and_request_markers(document, monkeypatch):
    source, revision = state.get_design_with_revision()
    doc_context.set_request_revision(42)
    doc_context.set_request_feature_log_entry_id("prior-entry")
    original = state._bump_revision
    def fail(session):
        original(session)
        doc_context.set_request_feature_log_entry_id("wrong")
        raise RuntimeError("Injected publication failure")
    monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(RuntimeError, match="Injected publication"):
        state.mutate_repair_draft(request())
    assert state.get_design_with_revision() == (source, revision)
    assert state.get_or_404() is source and state.undo_depth() == 0
    assert doc_context.current_request_revision() == 42
    assert doc_context.current_request_feature_log_entry_id() == "prior-entry"


def test_discard_does_not_read_oversized_or_broken_recipe(document, monkeypatch):
    assert post(document, request()).status_code == 200
    class Poison:
        def __getattribute__(self, _name):
            pytest.fail("Discard inspected geometry/history")
        def __len__(self):
            pytest.fail("Discard sized geometry/history")
    source = state.get_or_404()
    source.feature_log = Poison()
    source.helices = Poison()
    monkeypatch.setattr("backend.core.part_repair_draft_host.repair_base_fingerprint",
                        lambda *_a, **_k: pytest.fail("Discard hashed definitions"))
    result = post(document, request("discard"))
    assert result.status_code == 200 and state.get_or_404().repair_draft is None
    assert state.get_or_404().feature_log is source.feature_log


@pytest.mark.parametrize("extra", [{"candidate": {}}, {"ready": True}, {"input_sources": {}}, {"draft_id": "client-id"}])
def test_public_request_rejects_outputs_and_client_identity(document, extra):
    source, revision = state.get_design_with_revision()
    result = post(document, request(**extra))
    assert result.status_code == 422
    assert state.get_design_with_revision() == (source, revision)


def test_invalid_action_returns_structured_target_without_publication(document):
    body = request()
    body["actions"][0].update(parameter_path=["_proof_version"], expected_old=1, value=2)
    source, revision = state.get_design_with_revision()
    result = post(document, body)
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "protected_recipe_identity"
    assert result.json()["detail"]["feature_id"] == "resize"
    assert state.get_design_with_revision() == (source, revision)


def test_missing_document_returns_404_without_creating_model(document):
    state.load_design(None)
    with pytest.raises(HTTPException) as error:
        state.get_repair_draft()
    assert error.value.status_code == 404 and state.get_design() is None


def test_protected_simulation_branch_allows_read_but_refuses_draft_changes_before_capture(document, monkeypatch):
    source = state.get_or_404()
    source.loadouts = [DesignLoadout(id="simulation", name="Simulation", protected=True)]
    source.active_loadout_id = "simulation"
    client, headers = document
    read = client.get(PATH, headers=headers)
    assert read.status_code == 200 and read.json()["draft"] is None
    revision = state.revision()
    monkeypatch.setattr(drafts, "capture_draft_inputs", lambda *_a, **_k: pytest.fail("Read-only branch captured mutation"))
    result = post(document, request())
    assert result.status_code == 409 and result.json()["detail"]["code"] == "protected_simulation_loadout"
    assert state.get_design_with_revision() == (source, revision)
