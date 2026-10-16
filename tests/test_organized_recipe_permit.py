"""Only owned recipe hosts may publish organized parts, with live guards."""

from threading import Event
from types import SimpleNamespace
from weakref import WeakKeyDictionary

import pytest
from fastapi import HTTPException

from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.core.part_group_model import GroupOrganization
from backend.core.part_history_contract import create_empty_part


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(permits, "_admissions", WeakKeyDictionary())
    monkeypatch.setattr(permits, "_permits", WeakKeyDictionary())
    monkeypatch.setattr(permits, "monotonic", lambda: 100.)
    source = create_empty_part("Native part", "HONEYCOMB")
    source.group_organization = GroupOrganization()
    return SimpleNamespace(design=source, revision=3, identity="recipe-session")


def admit(context, operation="repair"):
    return permits.admit_organized_recipe("part", context, operation=operation, request_sha256="a" * 64)


def issue(context, candidate, handle=None, **changes):
    fields = dict(request_sha256="a" * 64, expires=150.)
    fields.update(changes)
    return permits.issue_organized_recipe_permit(handle or admit(context), candidate, **fields)


@pytest.mark.parametrize("operation", ["repair", "deformation_preview"])
def test_owned_recipe_evidence_is_distinct_and_exact_one_use(context, operation):
    candidate = context.design.model_copy(deep=True)
    permit = issue(context, candidate, admit(context, operation))
    checked = permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)
    assert checked.admission.scope_tag == "organized_recipe_v1"
    assert checked.evidence_class == "owned_recipe_rebuild"
    gate.require_group_publication(context.design, candidate, checked)
    with pytest.raises(HTTPException):
        permits.check_publication(permit, doc_id="part", session=context,
                                  candidate=candidate.model_copy(deep=True))
    permits.consume_publication(permit, checked)
    with pytest.raises(HTTPException):
        permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)


@pytest.mark.parametrize("operation", ["batch", "group-patch", "edit", "verify", "selection"])
def test_arbitrary_host_labels_cannot_acquire_recipe_authority(context, operation):
    with pytest.raises(HTTPException):
        admit(context, operation)
    assert not permits._admissions


def test_repair_evaluation_admission_uses_recipe_scope_but_verification_does_not(context):
    handle = permits.admit_evaluation("part", context, operation="repair", request_sha256="a" * 64)
    assert permits.admission_context(handle).scope_tag == "organized_recipe_v1"
    read = permits.admit_evaluation("part", context, operation="verify", request_sha256="a" * 64)
    assert permits.admission_context(read).scope_tag is None
    with pytest.raises(HTTPException):
        issue(context, context.design.model_copy(deep=True), read)


@pytest.mark.parametrize("change", ["gate", "policy", "cancel", "expiry", "revision", "session", "source"])
def test_live_guards_reject_before_publication(context, monkeypatch, change):
    candidate = context.design.model_copy(deep=True)
    cancelled = Event()
    permit = issue(context, candidate, cancelled=cancelled)
    if change == "gate":
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    elif change == "policy":
        policy._install_configuration(policy.current_configuration())
    elif change == "cancel":
        cancelled.set()
    elif change == "expiry":
        monkeypatch.setattr(permits, "monotonic", lambda: 200.)
    elif change == "revision":
        context.revision += 1
    elif change == "session":
        context.identity = "reopened"
    else:
        context.design = context.design.model_copy(deep=True)
    with pytest.raises(HTTPException):
        permits.check_publication(permit, doc_id="part", session=context, candidate=candidate)


@pytest.mark.parametrize("change", ["digest", "cancel_type", "expired", "same_source", "no_organization", "different_part"])
def test_issuer_requires_its_exact_owned_candidate_and_request(context, change):
    candidate = context.design.model_copy(deep=True)
    fields = {}
    if change == "digest":
        fields["request_sha256"] = "b" * 64
    elif change == "cancel_type":
        fields["cancelled"] = {"cancelled": False}
    elif change == "expired":
        fields["expires"] = 100.
    elif change == "same_source":
        candidate = context.design
    elif change == "no_organization":
        candidate.group_organization = None
    else:
        candidate.id = "another-part"
    with pytest.raises(HTTPException):
        issue(context, candidate, **fields)


def test_registered_only_policy_and_disabled_gate_do_not_gain_a_bypass(context, monkeypatch):
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    with pytest.raises(HTTPException) as error:
        admit(context)
    assert error.value.detail["code"] == "group_organization_not_enabled"
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    policy._install_configuration(policy.HostPolicyConfiguration(default_mode="registered_only"))
    with pytest.raises(HTTPException) as error:
        admit(context)
    assert error.value.detail["code"] == "construction_policy"
