"""Only owned group edits may publish the staged organization representation."""

from copy import copy
from types import SimpleNamespace
from uuid import uuid4
from weakref import WeakKeyDictionary

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as policy
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import ClusterRigidTransform
from backend.core.part_group_organization import build
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def document(monkeypatch):
    source = create_empty_part("Owned organization", "HONEYCOMB")
    source.cluster_transforms = [ClusterRigidTransform(id="placement", name="Placed")]
    doc = f"__organization_permit__{uuid4()}"
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    monkeypatch.setattr(permits, "_admissions", WeakKeyDictionary())
    monkeypatch.setattr(permits, "_permits", WeakKeyDictionary())
    monkeypatch.setattr(permits, "monotonic", lambda: 100.)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True, raising=False)
    token = doc_context.set_current_doc(doc)
    try:
        state.load_design(source)
        yield SimpleNamespace(doc=doc, session=state._sessions[doc], source=source)
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(previous_revision)
        doc_context.set_request_feature_log_entry_id(previous_entry)


def admit(document, operation="group-organize"):
    return permits.admit_group_edit(document.doc, document.session,
        operation=operation, request_sha256="a" * 64)


def candidate(document):
    return build("group-organize", document.source,
        {"_proof_version": 1, "expected_placement_ids": ["placement"]})


def issue(document, value, *, admission=None, **changes):
    options = {"request_sha256": "a" * 64, "expires": 160.}
    options.update(changes)
    return permits.issue_group_edit_permit(admission or admit(document), value, **options)


def publish(document, value, permit):
    with state._lock:
        return publish_replacement(document.session, value, publication_permit=permit)


def denied(call, code=None):
    with pytest.raises(HTTPException) as failure:
        call()
    if code is not None:
        assert failure.value.detail["code"] == code
    return failure.value


def unexpected(*_args, **_kwargs):
    pytest.fail("Rejected publication performed snapshot or mutation work")


def test_rollout_is_disabled_by_default():
    assert gate.GROUP_ORGANIZATION_ENABLED is False


def test_disabled_rollout_cannot_issue_an_admission(document, monkeypatch):
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    denied(lambda: admit(document), "group_organization_not_enabled")
    assert not permits._admissions


@pytest.mark.parametrize("lifecycle", ["load_design", "restore_doc_design", "set_design_branch",
    "copy_for_workspace_save", "acknowledge_workspace_save", "undo", "redo"])
def test_explicit_lifecycle_admission_requires_enabled_host_rollout(document, monkeypatch, lifecycle):
    value = candidate(document)
    gate.require_live_design(value, lifecycle=lifecycle)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    denied(lambda: gate.require_live_design(value, lifecycle=lifecycle), "group_organization_not_enabled")


@pytest.mark.parametrize("lifecycle", [None, "set_design", "publish_replacement", "mutate_and_validate", True])
def test_lifecycle_names_cannot_authorize_generic_authored_changes(document, lifecycle):
    denied(lambda: gate.require_live_design(candidate(document), lifecycle=lifecycle),
        "group_organization_not_enabled")


def test_enabled_rollout_does_not_downgrade_strict_construction_policy(document):
    policy._install_configuration(policy.HostPolicyConfiguration(default_mode="registered_only"))
    assert denied(lambda: admit(document), "construction_policy").status_code == 403
    assert not permits._admissions


@pytest.mark.parametrize("operation", ["cluster_create", "repair", "batch", {"kind": "group-create"}])
def test_admission_requires_a_closed_ordinary_group_operation(document, operation):
    denied(lambda: admit(document, operation), "invalid_operation_admission")
    assert not permits._admissions


def test_admission_binds_original_source_session_revision_policy_and_request(document):
    handle = admit(document)
    context = permits.admission_context(handle)
    assert context.source() is document.source
    assert (context.doc_id, context.session_identity, context.source_revision,
        context.policy_generation, context.operation, context.request_sha256, context.scope_tag) == (
        document.doc, document.session.identity, document.session.revision,
        7, "group-organize", "a" * 64, "group_organization_v1")


@pytest.mark.parametrize("forged", [None, {"scope_tag": "group_organization_v1"}])
def test_saved_or_request_labels_cannot_issue_a_group_permit(document, forged):
    denied(lambda: permits.issue_group_edit_permit(forged, candidate(document),
        request_sha256="a" * 64, expires=160.), "invalid_publication_permit")


def test_other_admission_and_changed_request_cannot_issue_group_permit(document):
    other = permits.admit_evaluation(document.doc, document.session,
        operation="verify", request_sha256="a" * 64)
    value = candidate(document)
    denied(lambda: issue(document, value, admission=other), "invalid_publication_permit")
    denied(lambda: issue(document, value, request_sha256="b" * 64), "invalid_publication_permit")


@pytest.mark.parametrize("invalid", ["source", "different-id", "legacy", "untyped"])
def test_permit_requires_a_distinct_owned_active_candidate_for_same_design(document, invalid):
    value = candidate(document)
    value = {"source": document.source,
        "different-id": value.model_copy(update={"id": "different"}),
        "legacy": document.source.model_copy(deep=True),
        "untyped": {"id": document.source.id, "group_organization": {"version": 1, "groups": []}},
    }[invalid]
    denied(lambda: issue(document, value), "invalid_publication_permit")


@pytest.mark.parametrize("expires", [100., 1001., float("inf"), float("nan"), True])
def test_group_permit_lifetime_uses_existing_finite_bound(document, expires):
    denied(lambda: issue(document, candidate(document), expires=expires), "publication_expired")


def test_generation_changes_refuse_before_permit_issuance(document):
    admission = admit(document)
    policy._install_configuration(policy.current_configuration())
    denied(lambda: issue(document, candidate(document), admission=admission), "policy_changed")


def test_exact_candidate_publication_is_one_undo_revision_and_one_use(document):
    value = candidate(document)
    before = document.source.model_dump_json()
    permit = issue(document, value)
    checked = permits.check_publication(permit, doc_id=document.doc,
        session=document.session, candidate=value)
    assert checked.evidence_class == "owned_group_edit"
    revision = document.session.revision
    assert publish(document, value, permit) == revision + 1
    assert document.session.design is value
    assert len(document.session.history) == 1 and not document.session.redo
    assert document.session.history[-1].model_dump_json() == before
    assert document.source.model_dump_json() == before
    denied(lambda: publish(document, value, permit), "invalid_publication_permit")
    assert document.session.revision == revision + 1 and len(document.session.history) == 1


@pytest.mark.parametrize("operation", ["group-create", "group-update", "group-dissolve", "cluster_op"])
def test_active_source_owned_edit_uses_same_transaction(document, operation):
    source = candidate(document)
    document.session.design = source
    value = source.model_copy(deep=True)
    permit = issue(document, value, admission=admit(document, operation))
    revision = document.session.revision
    assert publish(document, value, permit) == revision + 1
    assert document.session.design is value and len(document.session.history) == 1


@pytest.mark.parametrize("change", ["copy-permit", "copy-candidate", "source", "revision", "session", "policy"])
def test_changed_or_copied_publication_context_refuses_before_snapshot(document, monkeypatch, change):
    value = candidate(document)
    permit = issue(document, value)
    if change == "copy-permit":
        permit = copy(permit)
    elif change == "copy-candidate":
        value = value.model_copy(deep=True)
    elif change == "source":
        document.session.design = document.source.model_copy(deep=True)
    elif change == "revision":
        document.session.revision += 1
    elif change == "session":
        # Same Design object and revision after real drop/reopen must not revive authority.
        revision = document.session.revision
        state.drop_doc(document.doc)
        state.load_design(document.source)
        document.session = state._sessions[document.doc]
        document.session.revision = revision
    else:
        policy._install_configuration(policy.current_configuration())
    current, revision = document.session.design, document.session.revision
    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    denied(lambda: publish(document, value, permit))
    assert document.session.design is current and document.session.revision == revision
    assert not document.session.history and not document.session.redo


@pytest.mark.parametrize("change", ["rollout", "expiry", "policy"])
def test_final_admission_is_rechecked_after_undo_preparation(document, monkeypatch, change):
    value = candidate(document)
    permit = issue(document, value)
    revision = document.session.revision
    snapshot = state._snapshot_copy

    def change_after_copy(source):
        result = snapshot(source)
        if change == "rollout":
            monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
        elif change == "expiry":
            monkeypatch.setattr(permits, "monotonic", lambda: 200.)
        else:
            policy._install_configuration(policy.current_configuration())
        return result

    monkeypatch.setattr(state, "_snapshot_copy", change_after_copy)
    denied(lambda: publish(document, value, permit))
    assert document.session.design is document.source and document.session.revision == revision
    assert not document.session.history and not document.session.redo


def test_failed_publication_rolls_back_markers_and_leaves_exact_permit_retryable(document, monkeypatch):
    value = candidate(document)
    permit = issue(document, value)
    revision = document.session.revision
    request_revision = doc_context.current_request_revision()
    doc_context.set_request_feature_log_entry_id("before-row")
    bump = state._bump_revision

    def fail_after_assignment(session):
        bump(session)
        doc_context.set_request_feature_log_entry_id("failed-row")
        raise RuntimeError("after assignment")

    monkeypatch.setattr(state, "_bump_revision", fail_after_assignment)
    with pytest.raises(RuntimeError, match="after assignment"):
        publish(document, value, permit)
    assert document.session.design is document.source and document.session.revision == revision
    assert not document.session.history and not document.session.redo
    assert doc_context.current_request_revision() == request_revision
    assert doc_context.current_request_feature_log_entry_id() == "before-row"
    monkeypatch.setattr(state, "_bump_revision", bump)
    assert publish(document, value, permit) == revision + 1


@pytest.mark.parametrize("active_source", [False, True])
def test_enabled_rollout_does_not_allow_generic_replacement(document, monkeypatch, active_source):
    value = candidate(document)
    if active_source:
        document.session.design = value
        value = document.source
    before = document.session.design
    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    denied(lambda: publish(document, value, None), "group_organization_not_enabled")
    assert document.session.design is before and not document.session.history


def test_unrelated_valid_creation_permit_cannot_publish_active_organization(document, monkeypatch):
    document.session.design = None
    value, permit = permits.prepare_empty_creation(document.doc, document.session,
        name="Empty", lattice_type="HONEYCOMB")
    value.group_organization = candidate(document).group_organization
    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    denied(lambda: publish(document, value, permit), "group_organization_not_enabled")
    assert document.session.design is None and not document.session.history
