"""Owned named-preview lifecycle under the explicit organization rollout gate."""

from uuid import uuid4

import pytest

from backend.api import part_deformation_preview as native_preview
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from tests.test_named_deformation_preview import named_source
from tests.test_part_deformation_preview_sessions import (
    Timer, cancellation, checkpoint, opening, unchanged, update,
)


@pytest.fixture
def document(monkeypatch):
    # All fallible native construction precedes document-context mutation.
    source = named_source()
    identity = f"__named_preview__{uuid4()}"
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(host, "Timer", Timer)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 19))
    token = doc_context.set_current_doc(identity)
    try:
        state.load_design(source)
        yield identity
    finally:
        try:
            host.clear_for_testing()
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)


def change(opened, sequence=1):
    return update(opened, sequence=sequence,
                  params={"targets": [{"kind": "part_group", "id": "other"}]})


def test_named_prepare_evaluate_apply_publishes_exact_guarded_recipe_once(document):
    before = checkpoint()
    opened = host.prepare(opening())
    assert opened["control_context"]["capabilities"]["change_targets"] is True
    assert host.evaluate({**change(opened), "include_geometry": False})["candidate"] is None
    unchanged(before)
    receipt = host.apply(change(opened, 2))
    after = checkpoint()
    assert after["source"] is not before["source"]
    assert before["source"].model_dump(mode="json") == before["json"]
    assert after["revision"] == before["revision"] + 1 == receipt["revision"]
    assert len(after["history"]) == len(before["history"]) + 1
    assert after["redo"] == ()
    result = after["source"]
    assert result.cluster_transforms == before["source"].cluster_transforms
    assert result.group_organization == before["source"].group_organization
    assert [row.id for row in result.feature_log] == [row.id for row in before["source"].feature_log]
    assert result.deformations[-1].targets == change(opened)["params"]["targets"]
    assert result.deformations[-1].cluster_ids == before["source"].deformations[-1].cluster_ids
    loaded = Design.model_validate_json(result.model_dump_json())
    proof = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    assert host.status(cancellation(opened))["status"] == "applied"
    assert host.cancel(cancellation(opened))["status"] == "applied"
    with pytest.raises(HTTPException):
        host.apply(change(opened, 3))
    assert checkpoint()["source"] is result
    assert checkpoint()["revision"] == receipt["revision"]


def test_named_cancel_releases_preview_without_mutating_source_or_stacks(document):
    before = checkpoint()
    opened = host.prepare(opening())
    host.evaluate({**change(opened), "include_geometry": False})
    assert host.cancel(cancellation(opened))["status"] == "cancelled"
    unchanged(before)
    assert document not in host._entries
    with pytest.raises(HTTPException):
        host.apply(change(opened, 2))
    unchanged(before)


def test_disabled_organization_refuses_prepare_before_capture(document, monkeypatch):
    before = checkpoint()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    monkeypatch.setattr(host, "capture", lambda *_a, **_k: pytest.fail("Disabled source was captured"))
    with pytest.raises(HTTPException) as error:
        host.prepare(opening())
    assert error.value.detail["code"] == "group_organization_not_enabled"
    unchanged(before)


@pytest.mark.parametrize("operation", ["evaluate", "apply"])
@pytest.mark.parametrize("change_kind", ["source", "session_aba", "gate", "policy"])
def test_named_lease_guards_remain_live_before_native_work(document, monkeypatch, operation, change_kind):
    opened = host.prepare(opening())
    source, revision = state.get_design_with_revision()
    if change_kind == "source":
        with state._lock:
            state._sessions[document].design = source.copy_with()
    elif change_kind == "session_aba":
        state.drop_doc(document)
        state.load_design(source)
        with state._lock:
            state._sessions[document].revision = revision
    elif change_kind == "gate":
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    else:
        monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 20))
    before = checkpoint()
    monkeypatch.setattr(native_preview, "evaluate", lambda *_a, **_k: pytest.fail("Stale source reached native work"))
    with pytest.raises(HTTPException) as error:
        getattr(host, operation)(change(opened))
    assert error.value.status_code == 409
    unchanged(before)


def test_named_apply_refuses_gate_change_after_undo_copy_without_partial_publication(document, monkeypatch):
    opened = host.prepare(opening())
    before = checkpoint()
    original = state._snapshot_copy

    def changed_policy(design):
        snapshot = original(design)
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
        return snapshot

    monkeypatch.setattr(state, "_snapshot_copy", changed_policy)
    with pytest.raises(HTTPException) as error:
        host.apply(change(opened))
    assert error.value.detail["code"] == "group_organization_not_enabled"
    unchanged(before)


def test_named_publication_failure_restores_exact_source_and_can_retry(document, monkeypatch):
    opened = host.prepare(opening())
    before = checkpoint()
    original = state._bump_revision

    def fail_after_bump(session):
        original(session)
        raise RuntimeError("Publication failed after replacement")

    with monkeypatch.context() as fault:
        fault.setattr(state, "_bump_revision", fail_after_bump)
        with pytest.raises(RuntimeError, match="after replacement"):
            host.apply(change(opened))
    unchanged(before)
    assert host.status(cancellation(opened))["status"] == "ready"
    assert host.apply(change(opened, 2))["revision"] == before["revision"] + 1


def test_named_full_recipe_failure_preserves_editor_and_original_document(document, monkeypatch):
    opened = host.prepare(opening())
    before = checkpoint()
    with monkeypatch.context() as fault:
        fault.setattr(host, "prepare_change", lambda *_a, **_k: (_ for _ in ()).throw(
            HTTPException(409, detail="Downstream definition failed")))
        with pytest.raises(HTTPException, match="Downstream definition failed"):
            host.apply(change(opened))
    unchanged(before)
    assert host.evaluate({**change(opened, 2), "include_geometry": False})["candidate"] is None


@pytest.mark.parametrize("permit_kind", ["absent", "saved_label", "unknown_handle", "other_candidate"])
def test_set_design_facade_never_accepts_forged_or_nonmatching_recipe_permit(document, monkeypatch, permit_kind):
    from time import monotonic
    from backend.api import part_publication_permit as permits

    before = checkpoint()
    candidate = before["source"].model_copy(deep=True)
    permit = None
    if permit_kind == "saved_label":
        permit = {"scope_tag": "organized_recipe_v1", "evidence_class": "owned_recipe_rebuild"}
    elif permit_kind == "unknown_handle":
        permit = permits.PublicationPermit()
    elif permit_kind == "other_candidate":
        with state._lock:
            admission = permits.admit_organized_recipe(document, state._sessions[document],
                operation="deformation_preview", request_sha256="a" * 64)
        permit = permits.issue_organized_recipe_permit(admission, candidate,
            request_sha256="a" * 64, expires=monotonic() + 5)
        candidate = candidate.model_copy(deep=True)

    monkeypatch.setattr(state, "_snapshot_copy", lambda *_a, **_k: pytest.fail(
        "Rejected organized publication prepared undo"))
    with pytest.raises(HTTPException) as error:
        state.set_design(candidate, expected_revision=before["revision"],
            expected_source=before["source"], expected_session_identity=state._sessions[document].identity,
            publication_permit=permit)
    assert error.value.status_code == 409
    unchanged(before)
