"""Finite ordinary Apply must reproduce native topology from declared inputs.

Tests-first integration: the pure materializer has its independent legacy
oracle. These checks exercise the actual registry, repair graph and cold worker,
without admitting a live route or changing a numerical manifest.
"""

from copy import deepcopy

import pytest

from backend.api.part_proof_commands import PART_TOPOLOGY, dependencies, execute
from backend.api.part_recipe_edit import prepare_change, regenerate
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_edit_identity import preserve_proof_identity
from backend.core.part_verification_capture import capture
from tests.test_part_connection_application_commands import (
    ACTION, _params, _pending, application_prefix as application_prefix,
)
from tests.test_part_pending_connection_versions import (
    append, authored, native_prefix as native_prefix, proof,
)


@pytest.fixture
def pending(application_prefix):
    return _pending(application_prefix.model_copy(deep=True))


def applied(design, *, identity="applied-linker", feature_id="apply"):
    return append(design, "overhang-bulk", _params(design, connection_id=identity), feature_id)


@pytest.mark.parametrize("material", ["ss", "ds"])
def test_registered_contract_exposes_typed_inputs_conflicts_and_output_ownership(pending, material):
    params = {**_params(pending), "connection_type": f"root-to-root-{material}dna-linker",
              "conflict_connection_ids": ["old-connection"],
              "conflict_version_ids": ["candidate", "alternative"]}
    contract = dependencies("overhang-bulk", params)
    assert contract.known and contract.barrier and not contract.imported_sources
    assert {PART_TOPOLOGY, Resource("connection_version", "candidate"),
            Resource("connection_version", "alternative"),
            Resource("overhang", params["overhang_a_id"]),
            Resource("overhang", params["overhang_b_id"]),
            Resource("overhang_connection", "old-connection")} <= contract.reads
    assert {PART_TOPOLOGY, Resource("connection_version", "candidate"),
            Resource("connection_version", "alternative"),
            Resource("overhang_connection", "applied-linker"),
            Resource("helix", "__lnk__applied-linker")} <= contract.writes
    suffixes = ("s",) if material == "ss" else ("a", "b")
    assert {Resource("strand", f"__lnk__applied-linker__{suffix}")
            for suffix in suffixes} <= contract.writes


@pytest.mark.parametrize("change", [
    {"connection_application_version": None}, {"connection_application_version": True},
    {"connection_application_version": 2}, {"action": []},
    {"action": "connection-version-apply"}, {"_generated_scope": {}},
])
def test_registration_does_not_promote_legacy_malformed_or_scoped_receipts(pending, change):
    assert not dependencies("overhang-bulk", {**_params(pending), **change}).known


def test_edit_policy_protects_only_existing_contract_and_output_identity(pending):
    previous = _params(pending)
    updated = {**previous, "action": "another-action", "connection_application_version": 2,
        "connection_id": "new-output", "version_id": "another-version",
        "overhang_a_id": "another-endpoint", "conflict_version_ids": ["another-version"],
        "conflict_connection_ids": ["another-conflict"]}
    result = preserve_proof_identity(previous, updated, kind="overhang-bulk")
    for key in ("action", "connection_application_version", "connection_id"):
        assert result[key] == previous[key]
    for key in ("version_id", "overhang_a_id", "conflict_version_ids", "conflict_connection_ids"):
        assert result[key] == updated[key]
    assert preserve_proof_identity({}, {"name": "Legacy"}, kind="overhang-bulk") == {"name": "Legacy"}


@pytest.mark.parametrize("material", ["ss", "ds"])
def test_native_prefix_pending_apply_and_reapply_survive_cold_input_replay(application_prefix, material):
    source = _pending(application_prefix.model_copy(deep=True), f"root-to-root-{material}dna-linker")
    source = applied(source)
    source = applied(source, identity="replacement-linker", feature_id="reapply")
    assert [row.id for row in source.overhang_connections] == ["replacement-linker"]
    assert not any(row.id.startswith("__lnk__applied-linker") for row in [*source.helices, *source.strands])
    transported = Design.model_validate_json(source.model_dump_json())
    assert all(row.design_snapshot_gz_b64 == "poisoned recovery" for row in transported.feature_log)
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5), "Small finite linker recipe exceeded ordinary worker allowance"
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == 6 and result["native_editable"]
    finally:
        worker.close()


def test_apply_runs_normal_topology_reconciliation_and_ligation_postprocessing(pending, monkeypatch):
    from backend.core import cluster_reconcile, lattice
    from backend.api.part_connection_version_commands import is_metadata_command
    assert not is_metadata_command("overhang-bulk", _params(pending))
    reconciler, retry = cluster_reconcile.reconcile_cluster_membership, lattice.retry_pending_ligations
    calls = []

    def reconcile(*args, **kwargs):
        calls.append("reconcile")
        return reconciler(*args, **kwargs)

    def ligations(*args, **kwargs):
        calls.append("ligations")
        return retry(*args, **kwargs)

    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", reconcile)
    monkeypatch.setattr(lattice, "retry_pending_ligations", ligations)
    result = execute("overhang-bulk", pending, _params(pending))
    assert result.overhang_connections and calls == ["reconcile", "ligations"]


@pytest.mark.parametrize("producer,changes", [
    ("pending-candidate", {"bridge_length": 11}), ("endpoint-1", {"length_bp": 14}),
])
def test_upstream_inputs_regenerate_linker_with_stable_output_identity(pending, producer, changes):
    source = applied(pending)
    before = source.model_dump_json()
    index = next(i for i, row in enumerate(source.feature_log) if row.id == producer)
    candidate, _ = prepare_change(source, capture(source, preserve_entry_types=True), index,
                                  lambda: None, params=changes)
    assert candidate.overhang_connections[0].id == "applied-linker"
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    if producer == "pending-candidate":
        assert candidate.find_helix("__lnk__applied-linker").length_bp == 11
    else:
        endpoint = next(row for row in candidate.overhangs if row.id == _params(pending)["overhang_a_id"])
        assert candidate.find_helix(endpoint.helix_id).length_bp == 14
        assert len(candidate.connection_versions[0].overhang_a_seq) == 14
    assert proof(candidate)["status"] == "verified"
    poisoned = source.model_copy(deep=True)
    poisoned.find_helix("__lnk__applied-linker").axis_start.x += 1000.0
    assert authored(regenerate(poisoned, candidate.feature_log, lambda: None)) == authored(candidate)
    assert source.model_dump_json() == before


def test_missing_version_producer_reports_exact_input_instead_of_using_linker_output(pending):
    source = applied(pending)
    log = [row for row in source.feature_log if row.id != "pending-candidate"]
    with pytest.raises(ReferenceResolutionError) as caught:
        regenerate(source, log, lambda: None)
    assert caught.value.code == "missing_reference"
    assert caught.value.references == ({"kind": "connection_version", "identity": "candidate",
                                        "parameter_path": ["version_id"]},)


def test_endpoint_producer_delete_reports_dependents_and_requires_explicit_cascade(pending):
    source = applied(pending)
    before = source.model_dump_json()
    index = next(i for i, row in enumerate(source.feature_log) if row.id == "endpoint-2")
    captured = capture(source, preserve_entry_types=True)
    preview = prepare_change(source, captured, index, lambda: None)
    assert preview["needs_cascade_decision"]
    issues = {identity: issue for item in preview["dependents"]
              for identity, issue in item["issues"].items()}
    assert set(issues) == {"pending-candidate", "apply"}
    assert issues["pending-candidate"]["code"] == "missing_reference"
    assert issues["apply"]["references"][0]["parameter_path"] == ["version_id"]
    candidate, _ = prepare_change(source, captured, index, lambda: None, cascade=True)
    assert len(candidate.overhangs) == 1
    assert not candidate.connection_versions and not candidate.overhang_connections
    assert proof(candidate)["status"] == "verified"
    assert source.model_dump_json() == before


def test_broken_apply_endpoint_has_feature_and_parameter_diagnostic(pending):
    source = applied(pending)
    params = deepcopy(source.feature_log[-1].params)
    params["overhang_a_id"] = "missing-endpoint"
    source.feature_log[-1].params = params
    result = proof(source)
    assert result["status"] == "failed"
    assert result["issues"][0]["feature_id"] == "apply"
    assert result["issues"][0]["references"] == [{"kind": "overhang", "identity": "missing-endpoint",
                                                "parameter_path": ["overhang_a_id"]}]
    assert source.feature_log[-1].params["action"] == ACTION
