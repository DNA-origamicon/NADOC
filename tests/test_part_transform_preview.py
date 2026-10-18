"""Owned native transform histories, including earlier and reset operations."""

from copy import deepcopy
from uuid import uuid4

import numpy as np
import pytest

from backend.api import crud, part_proof_commands as commands
from backend.core import models as m
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_overlay_commands import command_input
from tests.test_part_deformation_preview import _append, authoring, owned_capture
from tests.test_part_transform_inputs import SEED, pose

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

# Bounding-mechanism tests use tiny fixtures at the original test-scale allowances.
pytestmark = pytest.mark.usefixtures("preview_test_scale_limits")



FEATURE = "selected-transform"


def service():
    from backend.api import part_transform_preview
    return part_transform_preview


def snapshot(source, kind, params, identity):
    if kind in commands.PROOF_MINOR_KINDS:
        params = {**params, "_proof_version": 1}
        child = m.MinorMutationLogEntry(id=f"{identity}-child", op_subtype=kind, label=kind,
            params=params, diff_added_b64="poisoned-diff")
        row = m.RoutingClusterLogEntry(id=identity, children=[child],
            pre_state_gz_b64="poisoned-pre", post_state_gz_b64="poisoned-post")
        updated = commands.execute(kind, source, params)
        return updated.copy_with(id=source.id, recipe_root=source.recipe_root,
                                 feature_log=[*source.feature_log, row])
    return _append(source, m.SnapshotLogEntry(id=identity, op_kind=kind, label=kind,
        params={**params, "_proof_version": 1}, evicted=True,
        design_snapshot_gz_b64="poisoned-pre", post_state_gz_b64="poisoned-post"))


def source_recipe(kind="cluster_op", *, extra=False, organized=False, suffix=True):
    source = create_empty_part("Transform preview", "HONEYCOMB")
    source = snapshot(source, "bundle-create", crud.BundleRequest(cells=[[0, 0], [0, 1]],
        length_bp=12, ligate_adjacent=False, history_seed=uuid4()).model_dump(mode="json"), "bundle")
    if extra:
        first, second = source.helices
        request = crud.PlaceCrossoverRequest(
            half_a=dict(helix_id=first.id, index=7, strand="REVERSE"),
            half_b=dict(helix_id=second.id, index=7, strand="FORWARD"), nick_bp_a=7, nick_bp_b=6,
        ).model_dump(mode="json")
        source = snapshot(source, "crossover-place", request, "junction")
        source = snapshot(source, "crossover-extra-bases", {"crossover_id": request["crossover_id"],
            "sequence": "AT"}, "inserted")
        body = pose(kind="extra_base", helix_id=None, bp_index=None, direction=None,
            crossover_id=request["crossover_id"], extra_base_k=1)
    else:
        domain = source.strands[0].domains[0]
        body = pose(helix_id=domain.helix_id, direction=domain.direction.value)
    if organized:
        source = snapshot(source, "group-organize", {"expected_placement_ids": [
            owner.id for owner in source.cluster_transforms]}, "organize")
    if kind == "cluster_op":
        owner = source.cluster_transforms[0]
        authored = {} if organized else {"name": "Arm", "helix_ids": list(owner.helix_ids),
            "domain_ids": [], "color": "#123456", "opacity": .7}
        source = _append(source, m.ClusterOpLogEntry(id=FEATURE, cluster_id=owner.id,
            translation=[1, 2, 3], rotation=[0, 0, 0, 1], pivot=[0, 0, 0],
            authored_fields=authored, proof_version=1, source="manual-test"))
    else:
        if kind == "nucleotide-transform-delete":
            source = snapshot(source, "nucleotide-transform", {**body, "history_seed": SEED}, "earlier-pose")
            target = source.nucleotide_transforms[0]
            params = {"transform_id": target.id, "target": list(target.target_key())}
        else:
            params = {"history_seed": SEED, **({"transforms": [body]} if kind.endswith("-batch") else body)}
        source = snapshot(source, kind, params, FEATURE)
    if suffix:
        source = snapshot(source, "extrude-segment", {"cells": [[8, 8]], "length_bp": 3,
            "plane": "XY", "history_seed": str(uuid4())}, "later-extrusion")
    return source


@pytest.mark.parametrize("kind,extra,organized", [
    ("cluster_op", False, False), ("cluster_op", False, True),
    ("nucleotide-transform", False, False), ("nucleotide-transform-batch", False, False),
    ("nucleotide-transform-delete", False, False),
    ("nucleotide-transform", True, False), ("nucleotide-transform-batch", True, False),
    ("nucleotide-transform-delete", True, False),
])
def test_actual_native_feature_stage_matches_and_never_mutates_retained_inputs(kind, extra, organized):
    source = source_recipe(kind, extra=extra, organized=organized)
    original = source.model_dump(mode="json")
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    prefix = prepared.copy_prefix()
    result = service().evaluate(prepared, {})
    expected = commands.execute(kind, prefix.model_copy(deep=True), result.params)
    assert authoring(result.design) == authoring(expected)
    assert result.entry.id == FEATURE and command_input(result.entry) == (kind, result.params)
    assert result.stage == "feature" and not result.source_equivalence_checked and not result.downstream_evaluated
    if kind == "cluster_op":
        for helix in expected.helices:
            actual_arrays = deformed_nucleotide_arrays(helix, result.design)
            expected_arrays = deformed_nucleotide_arrays(helix, expected)
            for field in ("positions", "base_normals", "axis_tangents"):
                np.testing.assert_array_equal(actual_arrays[field], expected_arrays[field])
        assert result.entry.source == "manual-test"
    expected_authoring = deepcopy(authoring(expected))
    result.design.strands.clear()
    result.params.clear()
    prefix.helices.clear()
    assert authoring(service().evaluate(prepared, {}).design) == expected_authoring
    assert source.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", ["cluster_op", "nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete"])
def test_native_fixture_independently_replays_without_recovery(kind):
    source = source_recipe(kind)
    proof = assess_part_history(source, execute=commands.execute, dependencies=commands.dependencies)
    assert proof["status"] == "verified", proof


def test_evaluation_replays_only_selected_command_and_prepare_never_uses_suffix_or_recovery(monkeypatch):
    from backend.api import part_deformation_preview as shared, part_recipe_edit, state
    source = source_recipe()
    actual = shared.execute
    calls = []
    def execute(kind, design, params):
        calls.append(kind)
        assert kind != "extrude-segment", "executed downstream suffix"
        return actual(kind, design, params)
    monkeypatch.setattr(shared, "execute", execute)
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_: pytest.fail("decoded recovery"))
    monkeypatch.setattr(part_recipe_edit, "assess_part_history", lambda *_a, **_k: pytest.fail("full proof during slider"))
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    assert calls == ["bundle-create"]
    calls.clear()
    service().evaluate(prepared, {"translation": [3, 2, 1]})
    service().evaluate(prepared, {"translation": [1, 2, 3]})
    assert calls == ["cluster_op", "cluster_op"]


def test_complete_cluster_retarget_entry_agrees_with_native_params():
    source = source_recipe(suffix=False)
    # A second native placement exists before the selected row.
    bundle = source.feature_log[0]
    prefix = _append(create_empty_part("retarget", "HONEYCOMB"), bundle)
    other = m.ClusterRigidTransform(id=str(uuid4()), name="Other", helix_ids=[prefix.helices[0].id])
    prefix = _append(prefix, m.ClusterCreateLogEntry(cluster_id=other.id, name=other.name,
        helix_ids=other.helix_ids, cluster_snapshot=other, proof_version=2))
    row = source.feature_log[-1].model_copy(update={"cluster_id": prefix.cluster_transforms[0].id})
    source = _append(prefix, row)
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    result = service().evaluate(prepared, {"cluster_id": other.id, "helix_ids": list(other.helix_ids)})
    assert result.entry.cluster_id == other.id == result.params["cluster_id"]
    assert command_input(result.entry) == ("cluster_op", result.params)


@pytest.mark.parametrize("kind,patch,path", [
    ("cluster_op", {"cluster_id": "missing"}, ["cluster_id"]),
    ("cluster_op", {"helix_ids": ["missing"]}, ["helix_ids", 0]),
    ("nucleotide-transform", {"helix_id": "missing"}, ["helix_id"]),
    ("nucleotide-transform-delete", {"transform_id": "missing"}, ["transform_id"]),
])
def test_missing_reference_has_exact_authored_path_and_keeps_prefix(kind, patch, path):
    source = source_recipe(kind)
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    before = prepared.copy_prefix().model_dump(mode="json")
    with pytest.raises(CommandContractError) as caught:
        service().evaluate(prepared, patch)
    assert caught.value.code == "missing_reference"
    assert any(ref["parameter_path"] == path for ref in caught.value.as_issue()["references"])
    assert prepared.copy_prefix().model_dump(mode="json") == before
    assert service().evaluate(prepared, {}).entry.id == FEATURE


def test_delete_binds_derived_target_receipt_to_exact_owned_prefix():
    from backend.api import part_transform_inputs
    source = source_recipe("nucleotide-transform-delete", suffix=False)
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    prefix = prepared.copy_prefix()
    original = prefix.nucleotide_transforms[0]
    domain = next(domain for strand in prefix.strands for domain in strand.domains
                  if domain.helix_id == prefix.helices[1].id)
    body = pose(helix_id=domain.helix_id, direction=domain.direction.value)
    prefix = commands.execute("nucleotide-transform", prefix,
        {**body, "history_seed": str(uuid4()), "_proof_version": 1})
    other = next(item for item in prefix.nucleotide_transforms if item.id != original.id)
    params = {"_proof_version": 1, "transform_id": other.id, "target": list(original.target_key())}
    result = part_transform_inputs.bind_prefix("nucleotide-transform-delete", params, prefix)
    assert result["target"] == list(other.target_key()) and params["target"] == list(original.target_key())


def test_unknown_suffix_contract_is_not_an_unconditional_local_preview_claim():
    source = source_recipe()
    source.feature_log[-1].params["_proof_version"] = 99
    with pytest.raises(CommandContractError):
        service().prepare_from_capture(owned_capture(source), FEATURE)


def test_inserted_residue_expansion_is_refused_before_native_metadata_builder(monkeypatch):
    from backend.api import part_deformation_preview as shared
    source = source_recipe("nucleotide-transform", extra=True)
    row = next(row.children[0] for row in source.feature_log if row.id == "inserted")
    row.params["sequence"] = "A" * 1025
    actual = shared.execute
    def forbidden_insert(kind, design, params):
        assert kind != "crossover-extra-bases", "executed excessive inserted material"
        return actual(kind, design, params)
    monkeypatch.setattr(shared, "execute", forbidden_insert)
    with pytest.raises(CommandContractError) as caught:
        service().prepare_from_capture(owned_capture(source), FEATURE)
    assert caught.value.code == "preview_limit"
