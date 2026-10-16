"""Owned immutable projection preserves ordinary accounting without another graph clone."""

import pytest
from fastapi import HTTPException

from backend.api import part_batch_evaluation as batch
from backend.api import part_immutable_evaluation as immutable
from backend.api import part_immutable_revision as revisions
from backend.api.part_evaluation import EvaluationRequest
from backend.core import part_capture_inputs as inputs
from backend.core.models import ClusterCreateLogEntry, Design, RoutingClusterLogEntry, MinorMutationLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import CaptureLimit, capture
from tests.test_part_immutable_revision import retained_source
from tests.test_part_registered_batch import gold, request as batch_request


def source():
    design = retained_source()
    design.feature_log.extend([
        ClusterCreateLogEntry(id="group-feature", proof_version=1, cluster_id="group", name="Group", helix_ids=[]),
        RoutingClusterLogEntry(id="routing", label="Routing", children=[MinorMutationLogEntry(
            id="child", label="Strand", op_subtype="strand-add", params={"_proof_version": 1, "nested": {"values": [1, 2]}})]),
    ])
    return Design.model_validate_json(design.model_dump_json())


def projected(design, **kwargs):
    return inputs.visit_inputs(design, max_nodes=kwargs.get("max_nodes", 30_000),
        max_bytes=kwargs.get("max_bytes", 2_000_000), seconds=kwargs.get("seconds", 0.025),
        preserve_entry_types=kwargs.get("preserve_entry_types", True), copy_inputs=False, retain_owned=True)


@pytest.mark.parametrize("preserve", [False, True])
def test_owned_projection_has_exact_capture_shape_and_exclusions(preserve):
    design = source()
    before = design.model_dump_json()
    expected = capture(design, preserve_entry_types=preserve)
    actual = projected(design, preserve_entry_types=preserve)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert design.model_dump_json() == before
    assert "poisoned recovery" not in actual.model_dump_json()
    assert actual is not design and actual.feature_log is not design.feature_log


def test_owned_projection_mutations_cannot_change_seal_or_future_materialization():
    handle = revisions.prepare_revision(source())
    original = handle.payload
    actual = immutable._capture_owned_revision(handle,
        request=EvaluationRequest(operation="verify", expected_revision=1), revision=1)
    actual.nanoparticles[0].diameter_nm = 22.
    actual.feature_log[0].params["nested"]["values"].clear()
    actual.feature_log[1].helix_ids.append("changed")
    actual.feature_log[2].children[0].params["nested"]["values"].append("changed")
    after = revisions.materialize_revision(handle)
    assert handle.payload is original
    assert after.nanoparticles[0].diameter_nm == 10.
    assert after.feature_log[0].params["nested"]["values"] == [1, 2., True]
    assert after.feature_log[1].helix_ids == []
    assert after.feature_log[2].children[0].params["nested"]["values"] == [1, 2]


def test_owned_path_does_not_deepcopy_an_already_isolated_graph(monkeypatch):
    handle = revisions.prepare_revision(source())
    monkeypatch.setattr(inputs, "deepcopy", lambda *a, **k: pytest.fail("Redundant graph copy"))
    value = immutable._capture_owned_revision(handle,
        request=EvaluationRequest(operation="verify", expected_revision=1), revision=1)
    assert value.nanoparticles[0].id == "gold"
    assert value.feature_log[2].children[0].id == "child"


@pytest.mark.parametrize("budget", [{"max_nodes": 1}, {"max_nodes": 100}, {"max_bytes": 1},
                                     {"max_bytes": 100}, {"seconds": -1}])
def test_owned_projection_retains_ordinary_node_byte_and_time_refusals(budget):
    design = source()
    for call in (projected, capture):
        with pytest.raises(CaptureLimit):
            call(design, **budget)


def test_capture_retains_mutable_source_isolation_after_owned_support():
    design = source()
    value = capture(design, preserve_entry_types=True)
    value.feature_log[0].params["nested"]["values"].clear()
    value.feature_log[1].helix_ids.append("changed")
    value.nanoparticles[0].pose.values[3] = 7.
    assert design.feature_log[0].params["nested"]["values"] == [1, 2., True]
    assert design.feature_log[1].helix_ids == []
    assert design.nanoparticles[0].pose.values[3] == 0.


@pytest.mark.parametrize("changes", [{"seconds": None}, {"copy_inputs": True}])
def test_owned_transfer_cannot_disable_deadline_or_mix_copy_modes(changes):
    kwargs = dict(max_nodes=30_000, max_bytes=2_000_000, seconds=.025,
                  preserve_entry_types=True, copy_inputs=False, retain_owned=True)
    kwargs.update(changes)
    with pytest.raises(TypeError):
        inputs.visit_inputs(source(), **kwargs)


@pytest.mark.parametrize("fake", [None, {}, b"{}"])
def test_owned_host_requires_sealed_bytes_before_materialization(fake):
    with pytest.raises(HTTPException) as error:
        immutable._capture_owned_revision(fake, request=EvaluationRequest(operation="verify"), revision=1)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "immutable_publication_scope"


def test_owned_capture_reuses_batch_scope_and_command_row_admission(monkeypatch):
    handle = revisions.prepare_revision(retained_source())
    monkeypatch.setattr(batch, "REGISTERED_BATCH_ENABLED", True)
    request = EvaluationRequest.model_validate({"operation": "batch", "batch": batch_request(
        gold(), expected_revision=1, expected_design_id="stable-part")})
    value = immutable._capture_owned_revision(handle, request=request, revision=1)
    assert value.feature_log[0].post_state_gz_b64 == ""
    monkeypatch.setattr(batch, "REGISTERED_BATCH_ENABLED", False)
    with pytest.raises(CommandContractError, match="not enabled"):
        immutable._capture_owned_revision(handle, request=request, revision=1)
    monkeypatch.setattr(batch, "REGISTERED_BATCH_ENABLED", True)
    with pytest.raises(CommandContractError, match="different part"):
        immutable._capture_owned_revision(handle, request=request, revision=2)
