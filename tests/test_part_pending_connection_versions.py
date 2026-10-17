"""Pending ordinary OH candidates need input-only, independently replayable rows.

Tests-first contract: this deliberately does not admit connection Apply, bound
topology, relocation, numerical relaxation, or assembly versions.
"""

from copy import deepcopy
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, routes_connection_versions as routes, state
from backend.api.part_proof_commands import (
    PART_TOPOLOGY, dependencies as registered_dependencies, execute as registered_execute,
)
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import ConnectionVersion, Design, DomainRef, ForcedLigation, SnapshotLogEntry
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture
from tests.conftest import valid_overhang_sites


CREATE = "connection-version-create"
PATCH = "connection-version-patch"
DELETE = "connection-version-delete"
PENDING_ACTIONS = {CREATE, PATCH, DELETE}


def command(action, params):
    # Reuse the existing snapshot literal; adding a metadata lifecycle must not
    # invalidate unrelated numerical engine pins by editing core/models.py.
    return ("overhang-bulk", {**params, "action": action}) if action in PENDING_ACTIONS else (action, params)


def dependencies(action, params):
    return registered_dependencies(*command(action, params))


def execute(action, design, params):
    kind, values = command(action, params)
    return registered_execute(kind, design, values)


def append(design, kind, params, identity):
    result = execute(kind, design, params)
    kind, params = command(kind, params)
    row = SnapshotLogEntry(
        id=identity, op_kind=kind, label=identity, timestamp="2026-10-15T00:00:00Z",
        params=deepcopy(params), design_snapshot_gz_b64="poisoned recovery",
        post_state_gz_b64="poisoned output",
    )
    return result.copy_with(feature_log=[*design.feature_log, row])


@pytest.fixture(scope="module")
def native_prefix():
    design = create_empty_part("Pending ordinary connections", "HONEYCOMB")
    design = append(design, "bundle-create", {
        "_proof_version": 1, "history_seed": str(UUID(int=810)),
        "cells": [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]],
        "length_bp": 42, "name": "Pending ordinary connections", "lattice_type": "HONEYCOMB",
    }, "bundle")
    for i, five_prime in enumerate((False, True), start=1):
        site = next(item for item in valid_overhang_sites(design)
                    if item["is_five_prime"] == five_prime)
        design = append(design, "overhang-extrude", {
            "_proof_version": 1, "history_seed": str(UUID(int=810 + i)),
            **site, "direction": site["direction"].value, "length_bp": 12,
        }, f"endpoint-{i}")
    return design


@pytest.fixture
def source(native_prefix):
    return native_prefix.model_copy(deep=True)


def selection(design, *, version_id="candidate"):
    a, b = design.overhangs[:2]
    return {"_proof_version": 1, "connection_version_contract": 1,
            "version_id": version_id, "overhang_a_id": a.id, "overhang_b_id": b.id}


def creation(design, **changes):
    return {**selection(design), "name": "", "created_at": 12.0,
            "connection_type": "root-to-root-ssdna-linker",
            "overhang_a_seq": "ac gt?", "overhang_b_seq": None,
            "bridge_length": 7, "bridge_seq": "ggNN", "applied": False, **changes}


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def pending_model(design, **changes):
    values = creation(design, **changes)
    return ConnectionVersion(
        id=values["version_id"], name=values["name"] or "V1", created_at=values["created_at"],
        overhang_a_id=values["overhang_a_id"], overhang_b_id=values["overhang_b_id"],
        connection_type=values["connection_type"], overhang_a_seq="ACGT",
        overhang_b_seq=None, bridge_length=values["bridge_length"], bridge_seq="GGNN",
        applied=values["applied"],
    )


def test_fixture_reproduces_real_native_ordinary_overhangs(source):
    result = proof(source)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 3 and source.recipe_root.kind == "empty"
    assert len(source.overhangs) == 2
    assert all(not item.auxiliary_endpoint for item in source.overhangs)


def test_pending_create_preserves_normalization_and_all_unrelated_authoring(source, monkeypatch):
    from backend.core import duplex, lattice

    def unexpected(*_args, **_kwargs):
        pytest.fail("Pending metadata invoked materialization")

    monkeypatch.setattr(duplex, "relocate_duplex", unexpected)
    monkeypatch.setattr(lattice, "generate_linker_topology", unexpected)
    before = source.model_dump_json()
    result = execute(CREATE, source, creation(source))
    expected = pending_model(source)
    assert result.connection_versions == [expected]
    assert authored(result) == authored(source.copy_with(connection_versions=[expected]))
    assert source.model_dump_json() == before
    assert Design.model_validate_json(result.model_dump_json()) == result


def test_default_names_follow_ordered_creation_and_unordered_pair_without_geometry(source):
    first = execute(CREATE, source, creation(source))
    second = execute(CREATE, first, creation(first, version_id="second", created_at=13.0,
        overhang_a_id=source.overhangs[1].id, overhang_b_id=source.overhangs[0].id))
    assert [item.name for item in second.connection_versions] == ["V1", "V2"]
    assert [item.created_at for item in second.connection_versions] == [12.0, 13.0]
    assert authored(second.copy_with(connection_versions=[])) == authored(source)


def test_sparse_patch_preserves_absent_fields_and_existing_null_blank_semantics(source):
    created = execute(CREATE, source, creation(source, name="Chosen"))
    result = execute(PATCH, created, {**selection(created), "patch": {
        "name": "  ", "connection_type": None, "overhang_a_seq": None,
        "bridge_length": None, "bridge_seq": "tt tt",
    }})
    expected = created.connection_versions[0].model_copy(update={"overhang_a_seq": None, "bridge_seq": "TTTT"})
    assert result.connection_versions == [expected]
    assert authored(result) == authored(created.copy_with(connection_versions=[expected]))


@pytest.mark.parametrize("kind", [CREATE, PATCH, DELETE])
def test_dependencies_expose_exact_endpoints_and_selected_version(source, kind):
    params = creation(source) if kind == CREATE else selection(source)
    if kind == PATCH:
        params["patch"] = {"name": "Renamed"}
    contract = dependencies(kind, params)
    assert contract.known and contract.barrier and not contract.imported_sources
    assert {PART_TOPOLOGY, Resource("overhang", params["overhang_a_id"]),
            Resource("overhang", params["overhang_b_id"])} <= contract.reads
    version = Resource("connection_version", params["version_id"])
    assert {PART_TOPOLOGY, version} <= contract.writes
    if kind != CREATE:
        assert version in contract.reads


@pytest.mark.parametrize("parameter", ["overhang_a_id", "overhang_b_id"])
def test_missing_endpoint_is_structured_and_nonmutating(source, parameter):
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        execute(CREATE, source, creation(source, **{parameter: "missing"}))
    assert caught.value.code == "missing_reference"
    assert caught.value.as_issue()["references"] == [
        {"kind": "overhang", "identity": "missing", "parameter_path": [parameter]}]
    assert source.model_dump_json() == before


@pytest.mark.parametrize("kind", [PATCH, DELETE])
def test_pending_contract_rejects_applied_rows_without_touching_topology(source, kind):
    source.connection_versions = [pending_model(source, applied=True)]
    before = source.model_dump_json()
    params = selection(source)
    if kind == PATCH:
        params["patch"] = {"name": "Renamed"}
    with pytest.raises(ReferenceResolutionError) as caught:
        execute(kind, source, params)
    assert caught.value.code == "invalid_selection"
    assert source.model_dump_json() == before


@pytest.mark.parametrize("kind", [PATCH, DELETE])
def test_selected_version_missing_or_pair_changed_is_not_silently_retargeted(source, kind):
    params = selection(source)
    if kind == PATCH:
        params["patch"] = {"name": "Renamed"}
    with pytest.raises(ReferenceResolutionError) as caught:
        execute(kind, source, params)
    assert caught.value.as_issue()["references"] == [{"kind": "connection_version",
        "identity": "candidate", "parameter_path": ["version_id"]}]
    source.connection_versions = [pending_model(source)]
    before = source.model_dump_json()
    # Ordered authored endpoints remain distinct even though V1/V2 naming groups
    # an unordered pair. Do not reinterpret a user's A/B sequence orientation.
    params.update(overhang_a_id=source.overhangs[1].id, overhang_b_id=source.overhangs[0].id)
    with pytest.raises(ReferenceResolutionError) as caught:
        execute(kind, source, params)
    assert caught.value.code == "invalid_selection"
    assert source.model_dump_json() == before


def test_closed_action_does_not_promote_unversioned_or_scoped_legacy_receipts(source):
    values = creation(source)
    values.pop("connection_version_contract")
    assert not dependencies(CREATE, values).known
    assert not dependencies(CREATE, creation(source, _generated_scope={"version": 1, "input_ids": []})).known
    assert not registered_dependencies("overhang-bulk", {
        **creation(source), "action": "connection-version-apply",
    }).known


@pytest.mark.parametrize("change", [
    {"_proof_version": True}, {"connection_version_contract": 2},
    {"applied": True}, {"applied": 0}, {"created_at": float("inf")},
    {"created_at": -1.0}, {"version_id": ""}, {"name": "x" * 257},
    {"connection_type": "invented-topology"}, {"bridge_length": -1},
    {"bridge_length": True}, {"prior_driven_topology": {}}, {"saved_design": {}},
])
def test_pending_schema_refuses_application_and_unbounded_or_opaque_inputs(source, change):
    assert not dependencies(CREATE, creation(source, **change)).known


def test_poisoned_recovery_cold_proof_and_complete_lifecycle(source):
    created = append(source, CREATE, creation(source), "candidate-create")
    renamed = append(created, PATCH, {**selection(created), "patch": {
        "name": "Chosen", "bridge_length": 9,
    }}, "candidate-patch")
    transported = Design.model_validate_json(renamed.model_dump_json())
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == 5 and result["native_editable"]
    finally:
        worker.close()
    deleted = append(renamed, DELETE, selection(renamed), "candidate-delete")
    assert authored(deleted) == authored(source)
    assert proof(deleted)["status"] == "verified"


def test_recipe_edit_preserves_output_identity_time_and_contract(source):
    created = append(source, CREATE, creation(source), "candidate-create")
    candidate, _ = prepare_change(created, capture(created, preserve_entry_types=True), 3, lambda: None,
        params={"name": "Edited", "bridge_length": 11, "version_id": "forged",
                "created_at": 99.0, "connection_version_contract": 99})
    selected = candidate.connection_versions[0]
    assert (selected.id, selected.created_at, selected.name, selected.bridge_length) == (
        "candidate", 12.0, "Edited", 11)
    assert candidate.feature_log[-1].params["connection_version_contract"] == 1
    assert proof(candidate)["status"] == "verified"
    assert authored(candidate.copy_with(connection_versions=[])) == authored(source)


def test_removed_endpoint_requires_actual_consumer_cascade_and_remains_replayable(source):
    created = append(source, CREATE, creation(source), "candidate-create")
    preview = prepare_change(created, capture(created, preserve_entry_types=True), 2, lambda: None)
    assert preview["needs_cascade_decision"]
    issue = next(item["issues"]["candidate-create"] for item in preview["dependents"]
                 if "candidate-create" in item["issues"])
    assert issue["code"] == "missing_reference"
    assert issue["references"] == [{"kind": "overhang", "identity": source.overhangs[1].id,
                                     "parameter_path": ["overhang_b_id"]}]
    candidate, _ = prepare_change(created, capture(created, preserve_entry_types=True), 2,
                                  lambda: None, cascade=True)
    assert not candidate.connection_versions
    assert len(candidate.overhangs) == 1
    assert proof(candidate)["status"] == "verified"


@pytest.fixture
def document(source):
    identity = f"__pending_ordinary_connections_{uuid4()}"
    token = doc_context.set_current_doc(identity)
    revision = doc_context.current_request_revision()
    entry = doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(source)
        yield source
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def test_ordinary_pending_routes_record_create_patch_delete_once_with_undo(document):
    before = state.get_or_404()
    before_json = before.model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    a, b = before.overhangs[:2]
    routes.create_connection_version(routes.ConnectionVersionCreateRequest(
        overhang_a_id=a.id, overhang_b_id=b.id,
        connection_type="root-to-root-ssdna-linker", overhang_a_seq="ac gt", bridge_length=7,
    ))
    created = state.get_or_404()
    assert len(created.feature_log) == len(before.feature_log) + 1, "Pending CRUD bypassed the feature log"
    row, version = created.feature_log[-1], created.connection_versions[0]
    assert (row.op_kind, row.params["action"]) == ("overhang-bulk", CREATE)
    assert row.params["version_id"] == version.id
    assert row.params["created_at"] == version.created_at
    assert row.params["connection_version_contract"] == 1
    assert (version.name, version.overhang_a_seq, version.bridge_length) == ("V1", "ACGT", 7)
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    routes.patch_connection_version(version.id, routes.ConnectionVersionPatchRequest(name="Chosen", bridge_length=9))
    renamed = state.get_or_404()
    assert (renamed.feature_log[-1].op_kind, renamed.feature_log[-1].params["action"]) == ("overhang-bulk", PATCH)
    assert renamed.feature_log[-1].params["patch"] == {"name": "Chosen", "bridge_length": 9}
    routes.delete_connection_version(version.id)
    assert (state.get_or_404().feature_log[-1].op_kind,
            state.get_or_404().feature_log[-1].params["action"]) == ("overhang-bulk", DELETE)
    assert not state.get_or_404().connection_versions
    assert state.revision() == revision + 3 and state.undo_depth() == depth + 3
    assert proof(state.get_or_404())["status"] == "verified"
    state.undo()
    assert state.get_or_404().connection_versions[0].name == "Chosen"
    state.redo()
    assert not state.get_or_404().connection_versions
    assert before.model_dump_json() == before_json


def test_ordinary_route_missing_endpoint_is_atomic(document):
    before, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    with pytest.raises(HTTPException):
        routes.create_connection_version(routes.ConnectionVersionCreateRequest(
            overhang_a_id=before.overhangs[0].id, overhang_b_id="missing", connection_type="root-to-root"))
    assert state.get_design_with_revision() == (before, revision)
    assert state.undo_depth() == depth


def retained_metadata(design):
    from backend.core.part_repair_draft import RepairDraft

    first, second = design.strands[:2]
    a, b = first.domains[-1], second.domains[0]
    partial = design.cluster_transforms[0].model_copy(update={
        "id": "retained-partial", "name": "Retained domain selection", "is_default": False,
        "helix_ids": [], "domain_ids": [DomainRef(strand_id=first.id, domain_index=0)],
    })
    draft = RepairDraft.model_validate({"version": 1, "draft_id": "saved-proposal", "generation": 0,
        "base_design_id": design.id, "repair_version": 1,
        "base": {"version": 1, "root_sha256": "a" * 64, "commands_sha256": "b" * 64, "sources_sha256": "c" * 64},
        "actions": [{"action": "set_input", "feature_id": "bundle", "parameter_path": ["length_bp"],
                     "expected_old": 42, "value": 49}]})
    return design.copy_with(
        cluster_transforms=[*design.cluster_transforms, partial], repair_draft=draft,
        forced_ligations=[ForcedLigation(id="retained-pending", three_prime_helix_id=a.helix_id,
            three_prime_bp=a.end_bp, three_prime_direction=a.direction,
            five_prime_helix_id=b.helix_id, five_prime_bp=b.start_bp, five_prime_direction=b.direction)],
    )


def test_proof_pending_actions_skip_topology_postprocessors_but_keep_cpd_guard(source, monkeypatch):
    from backend.core import cluster_reconcile, lattice, photoproducts

    source = retained_metadata(source)
    before = authored(source)
    def unexpected(*_args, **_kwargs):
        pytest.fail("Pending metadata ran a topology postprocessor")
    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", unexpected)
    monkeypatch.setattr(lattice, "retry_pending_ligations", unexpected)
    current = execute(CREATE, source, creation(source))
    current = execute(PATCH, current, {**selection(current), "patch": {"name": "Chosen"}})
    current = execute(DELETE, current, selection(current))
    assert authored(current) == before
    assert current.repair_draft == source.repair_draft
    monkeypatch.setattr(photoproducts, "stale_photoproduct_ids", lambda *_: ["formed-junction"])
    with pytest.raises(ValueError, match="photoproduct_dependency"):
        execute(CREATE, source, creation(source))


def test_recorded_pending_actions_preserve_unrelated_state_and_validate(document, monkeypatch):
    source = retained_metadata(document)
    state.load_design(source)
    before, draft = authored(source), source.repair_draft
    def unexpected(*_args, **_kwargs):
        pytest.fail("Pending recorder ran a topology postprocessor")
    monkeypatch.setattr(state, "reconcile_cluster_membership", unexpected)
    monkeypatch.setattr(state, "_retry_pending_ligations", unexpected)
    validate, calls = state.validate_design, []
    def observed(design):
        calls.append(design)
        return validate(design)
    monkeypatch.setattr(state, "validate_design", observed)
    a, b = source.overhangs[:2]
    routes.create_connection_version(routes.ConnectionVersionCreateRequest(
        overhang_a_id=a.id, overhang_b_id=b.id, connection_type="root-to-root"))
    identity = state.get_or_404().connection_versions[0].id
    routes.patch_connection_version(identity, routes.ConnectionVersionPatchRequest(name="Chosen"))
    routes.delete_connection_version(identity)
    assert len(calls) == 3
    assert authored(state.get_or_404()) == before
    assert state.get_or_404().repair_draft == draft


@pytest.mark.parametrize("malformed", [None, [], {"action": []}, {"action": {}},
    {"action": CREATE}, {"action": CREATE, "connection_version_contract": 99},
    {"action": "connection-version-apply", "connection_version_contract": 1}])
def test_metadata_classification_is_closed_and_never_throws_for_malformed_discriminators(malformed):
    from backend.api.part_connection_version_commands import is_metadata_command
    assert is_metadata_command("overhang-bulk", malformed) is False


def test_malformed_claimed_pending_action_cannot_run_recording_callback(document):
    before, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    def unexpected(_design):
        pytest.fail("Malformed pending contract reached its mutation callback")
    with pytest.raises(ValueError):
        state.mutate_with_feature_log("overhang-bulk", "Invalid pending", {
            **creation(document), "action": CREATE, "applied": True,
        }, unexpected)
    assert state.get_design_with_revision() == (before, revision)
    assert state.undo_depth() == depth


@pytest.mark.parametrize("failure", ["encode", "validation", "publish", "cancel", "cpd"])
def test_pending_recording_failure_is_atomic_and_keeps_draft(document, monkeypatch, failure):
    from backend.core import photoproducts
    state.load_design(retained_metadata(document))
    session = state._session()
    def signature():
        return (session.design.model_dump_json(), session.revision,
            [item.model_dump_json() for item in session.history],
            [item.model_dump_json() for item in session.redo],
            doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())
    before = signature()
    def fail(*_args):
        raise RuntimeError("Injected pending recording failure")
    if failure in {"encode", "cancel"}:
        encode, calls = state.encode_design_snapshot, []
        def encode_or_fail(design):
            calls.append(design)
            if len(calls) == 2:
                if failure == "cancel":
                    raise KeyboardInterrupt()
                fail()
            return encode(design)
        monkeypatch.setattr(state, "encode_design_snapshot", encode_or_fail)
    elif failure == "validation":
        monkeypatch.setattr(state, "validate_design", fail)
    elif failure == "publish":
        bump = state._bump_revision
        def bump_or_fail(current):
            bump(current)
            fail()
        monkeypatch.setattr(state, "_bump_revision", bump_or_fail)
    else:
        monkeypatch.setattr(photoproducts, "stale_photoproduct_ids", lambda *_: ["formed-junction"])
    a, b = session.design.overhangs[:2]
    expected = KeyboardInterrupt if failure == "cancel" else HTTPException if failure == "cpd" else RuntimeError
    with pytest.raises(expected):
        routes.create_connection_version(routes.ConnectionVersionCreateRequest(
            overhang_a_id=a.id, overhang_b_id=b.id, connection_type="root-to-root"))
    assert signature() == before
