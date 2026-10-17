"""Historical movement reads recorded joint/flexible context, never live state."""

import pytest

from backend.api import crud, part_deformation_preview as shared
from backend.api import part_transform_preview as preview
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from tests.test_part_deformation_preview import _append, owned_capture
from tests.test_part_transform_inputs import SEED
from tests.test_part_transform_preview import FEATURE, snapshot


def constrained_source(*, remove=False):
    source = snapshot(create_empty_part("Constraint prefix", "HONEYCOMB"),
        "bundle-create", crud.BundleRequest(cells=[[0, 0]], length_bp=12,
            strand_filter="scaffold", history_seed=SEED).model_dump(mode="json"), "bundle")
    owner = source.cluster_transforms[0]
    source = snapshot(source, "joint-place", {
        "cluster_id": owner.id, "joint_id": "hinge", "name": "Original",
        "local_axis_origin": [1, 2, 3], "local_axis_direction": [0, 1, 0],
        "min_angle_deg": -20, "max_angle_deg": 40,
    }, "joint-create")
    source = snapshot(source, "joint-update", {
        "joint_id": "hinge", "name": "Historical hinge", "max_angle_deg": 25,
    }, "joint-edit")
    strand = source.strands[0]
    domain = strand.domains[0]
    source = snapshot(source, "flexible-segment-mark", {
        "marks": [{"id": "flex", "strand_id": strand.id, "domain_index": 0,
                   "bp_index": 3, "direction": domain.direction.value}],
        "batch": True, "replace": False,
    }, "mark")
    if remove:
        source = snapshot(source, "joint-delete", {"joint_id": "hinge"}, "joint-remove")
        source = snapshot(source, "flexible-segment-unmark", {"mark_ids": ["flex"]}, "unmark")
    source = _append(source, m.ClusterOpLogEntry(id=FEATURE, cluster_id=owner.id,
        translation=[1, 0, 0], rotation=[0, 0, 0, 1], pivot=[0, 0, 0], proof_version=1))
    # A later change must not leak into the selected feature's controls.
    if not remove:
        source = snapshot(source, "joint-update", {"joint_id": "hinge", "max_angle_deg": 90}, "later")
    return source


@pytest.mark.parametrize("remove", [False, True])
def test_native_prefix_rebuild_preserves_exact_historical_constraint_context(remove):
    source = constrained_source(remove=remove)
    before = source.model_dump(mode="json")
    prepared = preview.prepare_from_capture(owned_capture(source), FEATURE)
    prefix = prepared.copy_prefix()
    if remove:
        assert prefix.cluster_joints == prefix.flexible_segment_marks == []
    else:
        assert prefix.cluster_joints[0].name == "Historical hinge"
        assert prefix.cluster_joints[0].max_angle_deg == 25
        assert prefix.cluster_joints[0].local_axis_origin == [1, 2, 3]
        assert prefix.flexible_segment_marks[0].id == "flex"
    candidate = preview.evaluate(prepared, {"translation": [2, 0, 0]}).design
    assert candidate.cluster_joints == prefix.cluster_joints
    assert candidate.flexible_segment_marks == prefix.flexible_segment_marks
    assert source.model_dump(mode="json") == before


def test_flexible_prefix_rejects_oversized_mark_batch_before_native_derivation(monkeypatch):
    source = constrained_source()
    entry = next(row for row in source.feature_log if row.id == "mark")
    entry.params["marks"] *= 3
    monkeypatch.setattr(shared, "MAX_SLOTS", 2)
    # Direct admission separates the new work guard from the bundle site guard.
    with pytest.raises(CommandContractError) as caught:
        shared._before_command("flexible-segment-mark", entry.params, create_empty_part("", "HONEYCOMB"))
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("field", ["cluster_joints", "flexible_segment_marks", "flexible_connections"])
def test_retained_constraint_count_is_bounded_before_native_projection(field):
    source = constrained_source()
    if field == "cluster_joints":
        value = source.cluster_joints[0]
    elif field == "flexible_segment_marks":
        value = source.flexible_segment_marks[0]
    else:
        # Count admission does not need to inspect or allocate connection geometry.
        value = object()
    setattr(source, field, [value] * (shared.MAX_SLOTS + 1))
    with pytest.raises(CommandContractError) as caught:
        shared._work(source, lambda: None)
    assert caught.value.code == "preview_limit"
