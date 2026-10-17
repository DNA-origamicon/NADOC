"""Host authority is private, bounded and invalidated independently of Design."""

from dataclasses import FrozenInstanceError
from threading import Event
from types import SimpleNamespace
from weakref import WeakKeyDictionary

import pytest
from fastapi import HTTPException

from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(
        document_modes={"part": "registered_only"}), 7))
    monkeypatch.setattr(permits, "_admissions", WeakKeyDictionary())
    monkeypatch.setattr(permits, "_permits", WeakKeyDictionary())
    monkeypatch.setattr(permits, "monotonic", lambda: 100.)
    source = create_empty_part("Native part", "HONEYCOMB")
    return SimpleNamespace(design=source, revision=3, identity="host-session")


def admission(session, operation="batch"):
    return permits.admit_evaluation("part", session, operation=operation, request_sha256="a" * 64)


def issue(session, candidate, *, handle=None, cancelled=None, **changes):
    fields = dict(request_sha256="a" * 64, authoring_sha256="b" * 64, recipe_sha256="c" * 64,
        expires=150., cancelled=cancelled or Event(), source_status="verified")
    fields.update(changes)
    return permits.issue_batch_permit(handle or admission(session), candidate, **fields)


def test_configuration_owns_bindings_and_unknown_modes_are_refused():
    bindings = {"part": "registered_only"}
    config = policy.HostPolicyConfiguration(document_modes=bindings)
    bindings["part"] = "compatibility"
    assert config.document_modes["part"] == "registered_only"
    with pytest.raises(TypeError):
        config.document_modes["part"] = "compatibility"
    with pytest.raises(FrozenInstanceError):
        config.default_mode = "registered_only"
    with pytest.raises(ValueError):
        policy.HostPolicyConfiguration(default_mode="trusted-agent")
    with pytest.raises(ValueError):
        policy.HostPolicyConfiguration(document_modes={"": "compatibility"})


def test_generation_changes_even_when_same_host_configuration_is_installed(context):
    before = policy.resolve("part")
    policy._install_configuration(policy.current_configuration())
    assert policy.resolve("part").generation == before.generation + 1
    assert policy.resolve("part").strict
    assert not policy.resolve("another-part").strict
    with pytest.raises(TypeError):
        policy._install_configuration({"default_mode": "compatibility"})


@pytest.mark.parametrize("operation", ["edit", "delete", "append", "repair", "selection", "unknown"])
def test_first_strict_profile_refuses_other_evaluation_families(context, operation):
    with pytest.raises(HTTPException) as error:
        admission(context, operation)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "construction_policy"
    assert not permits._admissions


def test_admission_binds_identity_without_retaining_source_or_accepting_forged_shape(context):
    handle = admission(context)
    bound = permits.admission_context(handle)
    assert bound.source() is context.design
    assert (bound.doc_id, bound.session_identity, bound.source_revision, bound.policy_generation,
        bound.operation, bound.scope_tag) == ("part", "host-session", 3, 7, "batch", "registered_batch_v1")
    assert permits.admission_context(permits.EvaluationAdmission()) is None
    assert permits.admission_context(vars(context)) is None
    assert not permits.context_matches(bound, "other", context)
    assert permits.context_matches(bound, "part", context)


@pytest.mark.parametrize("field,value", [("identity", "new-session"), ("revision", 4)])
def test_admission_context_rejects_session_and_revision_changes(context, field, value):
    handle = admission(context)
    bound = permits.admission_context(handle)
    setattr(context, field, value)
    assert not permits.context_matches(bound, "part", context)


def test_admission_context_rejects_source_replacement_and_policy_generation(context):
    handle = admission(context)
    bound = permits.admission_context(handle)
    context.design = context.design.model_copy(deep=True)
    assert not permits.context_matches(bound, "part", context)
    assert permits.context_matches(bound, "part", context, include_source=False)
    policy._install_configuration(policy.current_configuration())
    assert not permits.context_matches(bound, "part", context, include_source=False)


@pytest.mark.parametrize("forged", [None, {}, {"status": "ready", "operation": "batch"}])
def test_worker_or_saved_labels_cannot_supply_admission(context, forged):
    with pytest.raises(HTTPException) as error:
        permits.issue_batch_permit(forged, context.design, request_sha256="a" * 64, authoring_sha256="b" * 64,
            recipe_sha256="c" * 64, expires=150., cancelled=Event(), source_status="verified")
    assert error.value.detail["code"] == "invalid_publication_permit"


def test_verify_admission_cannot_publish_even_with_claimed_verified_result(context):
    with pytest.raises(HTTPException):
        issue(context, context.design, handle=admission(context, "verify"))


def test_batch_cannot_reuse_live_source_as_private_candidate(context):
    with pytest.raises(HTTPException) as error:
        issue(context, context.design)
    assert error.value.detail["code"] == "invalid_publication_permit"


def test_batch_issuer_must_match_the_canonical_admitted_request(context):
    with pytest.raises(HTTPException) as error:
        issue(context, context.design.model_copy(deep=True), request_sha256="d" * 64)
    assert error.value.detail["code"] == "invalid_publication_permit"


@pytest.mark.parametrize("status", ["reproduced_import", "unverified", "failed", "ready"])
def test_batch_requires_native_source_composition_not_import_or_ready_label(context, status):
    with pytest.raises(HTTPException):
        issue(context, context.design, source_status=status)


@pytest.mark.parametrize("expires", [99., 100., 1001., float("inf"), float("nan"), True])
def test_permits_have_a_fixed_bounded_lifetime(context, expires):
    with pytest.raises(HTTPException):
        issue(context, context.design, expires=expires)


def test_policy_change_invalidates_prior_admission_before_permit_issue(context):
    handle = admission(context)
    policy._install_configuration(policy.current_configuration())
    with pytest.raises(HTTPException) as error:
        issue(context, context.design, handle=handle)
    assert error.value.detail["code"] == "policy_changed"


def test_candidate_identity_and_cancelled_or_expired_permit_fail_before_scope(context, monkeypatch):
    candidate = context.design.model_copy(deep=True)
    cancelled = Event()
    permit = issue(context, candidate, cancelled=cancelled)
    with pytest.raises(HTTPException):
        permits.check_publication(permit, doc_id="part", session=context, candidate=candidate.model_copy(deep=True))
    cancelled.set()
    with pytest.raises(HTTPException) as error:
        permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)
    assert error.value.detail["code"] == "cancelled"
    cancelled.clear()
    monkeypatch.setattr(permits, "monotonic", lambda: 200.)
    with pytest.raises(HTTPException) as error:
        permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)
    assert error.value.detail["code"] == "publication_expired"


def test_creation_builds_its_own_root_and_permit_is_one_use(context):
    context.design = None
    candidate, permit = permits.prepare_empty_creation("part", context, name="Empty", lattice_type="SQUARE")
    assert candidate.recipe_root.kind == "empty" and candidate.recipe_root.initial_name == "Empty"
    assert candidate.lattice_type == "SQUARE" and candidate.feature_log == []
    checked = permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)
    assert checked.evidence_class == "explicit_empty_root"
    # Checking twice is permitted while the failure-atomic publisher retries.
    assert permits.check_publication(permit, doc_id="part", session=context, candidate=candidate) is checked
    permits.consume_publication(permit, checked)
    with pytest.raises(HTTPException):
        permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)


def test_creation_cannot_replace_a_live_part_or_accept_arbitrary_design(context):
    with pytest.raises(HTTPException) as error:
        permits.prepare_empty_creation("part", context, name="Empty", lattice_type="SQUARE")
    assert error.value.detail["code"] == "part_already_open"
    context.design = None
    with pytest.raises(TypeError):
        permits.prepare_empty_creation("part", context, candidate=create_empty_part("Hidden model", "SQUARE"))


def test_live_capability_counts_are_bounded_and_forged_objects_remain_unregistered(context, monkeypatch):
    monkeypatch.setattr(permits, "MAX_CAPABILITIES", 1)
    handle = admission(context)
    with pytest.raises(HTTPException) as error:
        admission(context)
    assert error.value.status_code == 429
    assert permits.admission_context(handle) is not None
    assert permits.admission_context(permits.EvaluationAdmission()) is None
    del handle
    assert permits.admission_context(admission(context)) is not None


def test_compatibility_admission_still_binds_generation_and_batch_scope(context):
    policy._install_configuration(policy.HostPolicyConfiguration())
    handle = admission(context)
    bound = permits.admission_context(handle)
    assert bound.scope_tag == "registered_batch_v1"
    assert not policy.resolve("part").strict
    policy._install_configuration(policy.HostPolicyConfiguration())
    assert not permits.context_matches(bound, "part", context)
