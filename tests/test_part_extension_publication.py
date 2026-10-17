"""Extension permits confer only one exact, source-bound field replacement.

The owned host validates command content and budgets before issuing authority;
these boundary tests do not pretend that a permit independently proves history.
"""

from copy import copy
from threading import Event
from weakref import WeakKeyDictionary

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_extension_owned_recording as owned
from backend.api import part_extension_publication as authority
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as policy
from backend.api.part_extension_commands import build
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import SnapshotLogEntry
from tests import test_group_organization_recording as groups
from tests.test_part_extension_commands import inputs
from tests.test_part_extension_owned_recording import values


document = groups.document


@pytest.fixture
def organized(document, monkeypatch):
    groups.apply(document)
    monkeypatch.setattr(permits, "_admissions", WeakKeyDictionary())
    monkeypatch.setattr(permits, "_permits", WeakKeyDictionary())
    for module in (authority, permits, owned):
        monkeypatch.setattr(module, "monotonic", lambda: 100.)
    return document


def admission(session, **options):
    return authority.admit(doc_context.get_current_doc(), session,
        operation=options.pop("operation", "extension-upsert"),
        request_sha256=options.pop("request_sha256", "a" * 64), **options)


def candidate(session):
    source = session.design
    params = inputs(source, version=2)
    prepared = build("extension-upsert", source, params)
    row = SnapshotLogEntry(op_kind="extension-upsert", label="Terminal", params=params)
    return source.copy_with(extensions=prepared.extensions,
        feature_log=[*source.feature_log, row])


def issue(session, value, *, admitted=None, **options):
    return authority.issue(admitted if admitted is not None else admission(session), value,
        request_sha256=options.pop("request_sha256", "a" * 64),
        expires=options.pop("expires", 160.), **options)


def publish(session, value, permit):
    with state._lock:
        return publish_replacement(session, value, publication_permit=permit)


def forbidden(*_args, **_kwargs):
    pytest.fail("Refused extension publication reached undo preparation")


@pytest.mark.parametrize("operation", ["repair", "group-create", "cluster_op", {}, []])
def test_only_closed_extension_operations_can_be_admitted(organized, operation):
    saved = groups.before(organized)
    with pytest.raises(HTTPException) as error:
        admission(organized, operation=operation)
    assert error.value.detail["code"] == "invalid_operation_admission"
    assert not permits._admissions
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("forgery", ["unregistered", "copied", "json-label", "other-scope", "request"])
def test_admission_identity_and_request_cannot_be_forged(organized, forgery):
    handle = admission(organized)
    options = {}
    if forgery == "unregistered": handle = permits.EvaluationAdmission()
    if forgery == "copied": handle = copy(handle)
    if forgery == "json-label": handle = {"scope_tag": authority.SCOPE}
    if forgery == "other-scope":
        handle = permits.admit_group_edit(doc_context.get_current_doc(), organized,
            operation="group-create", request_sha256="a" * 64)
    if forgery == "request": options["request_sha256"] = "b" * 64
    saved = groups.before(organized)
    with pytest.raises(HTTPException):
        issue(organized, candidate(organized), admitted=handle, **options)
    assert not permits._permits
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("version", [1, True, 2.0, "2", 3])
def test_extension_scope_cannot_authorize_v1_or_coerced_upsert_version(organized, version):
    value = candidate(organized)
    value.feature_log[-1].params["_proof_version"] = version
    with pytest.raises(HTTPException):
        issue(organized, value)
    assert not permits._permits


@pytest.mark.parametrize("change", ["helices", "strands", "cluster_transforms", "group_organization",
                                    "physical_layer", "prior-row", "row-kind", "row-version", "extensions-type"])
def test_scope_is_rechecked_on_exact_candidate_after_permit_issue(organized, monkeypatch, change):
    value = candidate(organized)
    permit = issue(organized, value)
    saved = groups.before(organized)
    if change in {"helices", "strands", "cluster_transforms"}:
        setattr(value, change, list(getattr(value, change)))
    elif change == "group_organization":
        value.group_organization = value.group_organization.model_copy(deep=True)
    elif change == "physical_layer": value.atomistic_reference = object()
    elif change == "prior-row": value.feature_log[0] = value.feature_log[0].model_copy(deep=True)
    elif change == "row-kind": value.feature_log[-1].op_kind = "extension-delete"
    elif change == "row-version": value.feature_log[-1].params["_proof_version"] = 1
    elif change == "extensions-type": value.extensions = tuple(value.extensions)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    with pytest.raises(HTTPException):
        publish(organized, value, permit)
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("replacement", ["different-object", "copied-permit", "unregistered-permit", "json-permit"])
def test_publication_requires_registered_exact_candidate_and_permit(organized, monkeypatch, replacement):
    value = candidate(organized)
    permit = issue(organized, value)
    if replacement == "different-object": value = value.model_copy()
    elif replacement == "copied-permit": permit = copy(permit)
    elif replacement == "unregistered-permit": permit = permits.PublicationPermit()
    elif replacement == "json-permit": permit = {"scope_tag": authority.SCOPE, "evidence_class": authority.EVIDENCE}
    saved = groups.before(organized)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    with pytest.raises(HTTPException):
        publish(organized, value, permit)
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("race", ["source", "revision", "incarnation", "policy-aba", "disabled", "expired"])
def test_admitted_candidate_cannot_publish_after_origin_or_policy_changes(organized, monkeypatch, race):
    value = candidate(organized)
    permit = issue(organized, value)
    if race == "source": organized.design = organized.design.model_copy(deep=True)
    elif race == "revision": organized.revision += 1
    elif race == "incarnation": organized.identity = "replacement-incarnation"
    elif race == "policy-aba":
        policy._install_configuration(policy.HostPolicyConfiguration(default_mode="registered_only"))
        policy._install_configuration(policy.HostPolicyConfiguration())
    elif race == "disabled": monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    elif race == "expired": monkeypatch.setattr(permits, "monotonic", lambda: 161.)
    saved = groups.before(organized)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    with pytest.raises(HTTPException):
        publish(organized, value, permit)
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("late", ["cancel", "expire", "policy", "disable"])
def test_liveness_after_undo_copy_prevents_assignment_and_preserves_stacks(organized, monkeypatch, late):
    cancelled = Event()
    value = candidate(organized)
    permit = issue(organized, value, cancelled=cancelled)
    saved = groups.before(organized)
    original = state._snapshot_copy
    calls = []

    def during_snapshot(source):
        result = original(source)
        calls.append(source)
        if late == "cancel": cancelled.set()
        elif late == "expire": monkeypatch.setattr(permits, "monotonic", lambda: 161.)
        elif late == "policy": policy._install_configuration(policy.HostPolicyConfiguration())
        else: monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
        return result

    monkeypatch.setattr(state, "_snapshot_copy", during_snapshot)
    with pytest.raises(HTTPException):
        publish(organized, value, permit)
    assert calls == [saved[0]]
    groups.unchanged(organized, saved)


def test_success_consumes_permit_once_even_if_source_revision_is_restored(organized, monkeypatch):
    value = candidate(organized)
    permit = issue(organized, value)
    saved = groups.before(organized)
    assert publish(organized, value, permit) == saved[2] + 1
    assert organized.design is value and len(organized.history) == len(saved[3]) + 1
    assert not permits._permits
    # Simulate exact source/revision ABA: registry consumption still forbids replay.
    organized.design, organized.revision = saved[0], saved[2]
    after_aba = groups.before(organized)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    with pytest.raises(HTTPException):
        publish(organized, value, permit)
    groups.unchanged(organized, after_aba)


@pytest.mark.parametrize("empty", [False, True])
def test_noop_upsert_admits_response_geometry_before_return(organized, monkeypatch, empty):
    from backend.api import part_group_geometry_budget as geometry_budget

    made, _, _ = owned.apply("create", values(organized), expected_revision=organized.revision)
    assert made is organized.design
    saved = groups.before(organized)
    monkeypatch.setattr(geometry_budget, "MAX_NATIVE_WORK", 1)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
    with pytest.raises(HTTPException) as error:
        owned.apply("batch", [] if empty else values(organized), expected_revision=organized.revision)
    assert error.value.detail["code"] == "group_geometry_limit"
    groups.unchanged(organized, saved)


def test_history_budget_refuses_before_recovery_or_publication(organized, monkeypatch):
    monkeypatch.setattr(authority, "MAX_HISTORY_ROWS", len(organized.design.feature_log))
    saved = groups.before(organized)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
    with pytest.raises(HTTPException) as error:
        owned.apply("create", values(organized), expected_revision=organized.revision)
    assert error.value.detail["code"] == "extension_capture_limit"
    groups.unchanged(organized, saved)
