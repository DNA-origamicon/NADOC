"""Historical group edits author native membership without rewriting old rows."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import part_deformation_preview as preview, part_proof_commands
from backend.api.part_recipe_edit import prepare_change
from backend.core.deformation import helices_crossing_planes, resolve_cluster_scope
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, ClusterRigidTransform, Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_overlay_commands import command_input
from tests.test_part_deformation_preview import _append, authoring, native_source, owned_capture


def grouped_source(kind="bend"):
    source = native_source(kind, grouped=True)
    entry = source.feature_log[-1]
    prefix = source.copy_with(feature_log=source.feature_log[:-1], deformations=[])
    # Keep the real frame placement owner: exhausting the default group is a
    # separate existing source-construction bug, characterized under ISSUE-106.
    second = next(group for group in prefix.cluster_transforms if group.is_default)
    assert second.helix_ids == [prefix.helices[1].id]
    prefix = _append(prefix, ClusterOpLogEntry(cluster_id=second.id,
        translation=[-3, 2, 0], rotation=[0, 0, 0, 1], pivot=[0, 0, 0], proof_version=1))
    source = _append(prefix, entry)
    assert Design.model_validate_json(source.model_dump_json()) == source
    return source, prefix, entry.op_snapshot.cluster_ids[0], second.id


def _proof(source):
    report = assess_part_history(source, execute=part_proof_commands.execute,
                                 dependencies=part_proof_commands.dependencies)
    assert report["status"] == "verified", report


def _apply(source, change):
    candidate, _ = prepare_change(source, owned_capture(source), len(source.feature_log) - 1,
                                  lambda: None, params=change)
    return candidate


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("selection", ["second", "both", "unscoped"])
def test_group_edit_preview_apply_and_cold_replay_share_native_membership(kind, selection):
    source, prefix, first, second = grouped_source(kind)
    _proof(source)
    before = source.model_dump(mode="json")
    ids = {"second": [second], "both": [first, second], "unscoped": []}[selection]
    original = source.feature_log[-1]
    op = original.op_snapshot
    expected_scope = resolve_cluster_scope(prefix, ids,
        helices_crossing_planes(prefix, op.plane_a_bp, op.plane_b_bp))
    expected_op = op.model_copy(update={"cluster_ids": expected_scope["cluster_ids"],
                                       "affected_helix_ids": expected_scope["helix_ids"]})
    expected = part_proof_commands.execute("deformation", prefix,
        {**expected_op.model_dump(mode="json"), "_proof_version": 1})
    prepared = preview.prepare_from_capture(owned_capture(source), original.id)
    evaluated = preview.evaluate(prepared, {"cluster_ids": ids})
    assert evaluated.entry.op_snapshot.affected_helix_ids == expected_scope["helix_ids"]
    assert authoring(evaluated.design) == authoring(expected)
    applied = _apply(source, {"cluster_ids": ids})
    assert authoring(applied) == authoring(expected)
    assert applied.feature_log[-1].op_snapshot == evaluated.entry.op_snapshot
    assert applied.feature_log[-1].id == original.id
    assert applied.feature_log[-1].deformation_id == original.deformation_id
    assert command_input(applied.feature_log[-1])[1]["_proof_version"] == 1
    # Poisoned prefix recovery never supplies geometry. Ordinary persisted
    # native inputs must reproduce the explicitly authored target selection.
    restored = Design.model_validate_json(applied.model_dump_json())
    _proof(restored)
    assert authoring(restored) == authoring(applied)
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_unchanged_group_parameter_edit_keeps_historical_explicit_membership(kind):
    source, prefix, first, _ = grouped_source(kind)
    old = source.feature_log[-1]
    # v1 stored the explicit member list separately from the group label.
    # Editing a scalar must not silently reinterpret those historical inputs.
    old = old.model_copy(update={"op_snapshot": old.op_snapshot.model_copy(
        update={"affected_helix_ids": [h.id for h in prefix.helices]})})
    source = _append(prefix, old)
    _proof(source)
    values = old.op_snapshot.params.model_dump(mode="json")
    values["curvature_deg_per_bp" if kind == "bend" else "total_degrees"] = .5 if kind == "bend" else 16
    change = {"cluster_ids": [first], "params": values}
    prepared = preview.prepare_from_capture(owned_capture(source), old.id)
    evaluated = preview.evaluate(prepared, change)
    applied = _apply(source, change)
    assert evaluated.entry.op_snapshot.affected_helix_ids == old.op_snapshot.affected_helix_ids
    assert applied.feature_log[-1].op_snapshot == evaluated.entry.op_snapshot
    _proof(applied)


@pytest.mark.parametrize("mode", ["preview", "apply"])
@pytest.mark.parametrize("invalid", ["missing", "duplicate", "empty_group"])
def test_invalid_group_selection_refuses_without_changing_source(mode, invalid):
    source, prefix, _, second = grouped_source()
    if invalid == "empty_group":
        entry = source.feature_log[-1]
        empty = ClusterRigidTransform(id=str(uuid4()), name="Empty selection", helix_ids=[])
        prefix = _append(prefix, ClusterCreateLogEntry(cluster_id=empty.id, name=empty.name,
            helix_ids=[], cluster_snapshot=empty, proof_version=1))
        source = _append(prefix, entry)
        ids = [empty.id]
    else:
        ids = ["missing"] if invalid == "missing" else [second, second]
    before = source.model_dump(mode="json")
    prepared = preview.prepare_from_capture(owned_capture(source), source.feature_log[-1].id)
    with pytest.raises((CommandContractError, HTTPException)) as caught:
        if mode == "preview":
            preview.evaluate(prepared, {"cluster_ids": ids})
        else:
            _apply(source, {"cluster_ids": ids})
    issue = caught.value.as_issue() if isinstance(caught.value, CommandContractError) else caught.value.detail
    assert isinstance(issue, dict) and issue.get("code")
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("mode", ["preview", "apply"])
def test_explicit_domain_selection_cannot_be_retargeted_by_group_metadata(mode):
    source = native_source(scoped=True)
    before = source.model_dump(mode="json")
    change = {"cluster_ids": [source.cluster_transforms[0].id]}
    prepared = preview.prepare_from_capture(owned_capture(source), source.feature_log[-1].id)
    with pytest.raises((CommandContractError, HTTPException)) as caught:
        if mode == "preview":
            preview.evaluate(prepared, change)
        else:
            _apply(source, change)
    issue = caught.value.as_issue() if isinstance(caught.value, CommandContractError) else caught.value.detail
    assert isinstance(issue, dict) and issue.get("code")
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("scoped", [False, True])
def test_display_exposes_group_editing_only_for_unscoped_native_selection(scoped):
    from backend.api.part_deformation_preview_dto import prepare_display

    source = native_source(scoped=scoped)
    prepared = preview.prepare_from_capture(owned_capture(source), source.feature_log[-1].id)
    evaluated = preview.evaluate(prepared, {})
    controls = prepare_display(prepared.copy_prefix(), evaluated)["control_context"]
    assert controls["capabilities"]["change_targets"] is False
    assert controls["capabilities"]["change_clusters"] is (not scoped)
