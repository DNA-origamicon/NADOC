"""Direct input→output unit tests for backend.core.feature_log_edit.

Pins the pure model-transform core extracted from crud.py's ``edit_feature``
endpoint (Refactor #35, service push): the cluster_op pose-rewrite and the
deformation op-rewrite + deformation-set rebuild. No TestClient — these assert
the pure Design→Design behavior the api shim now delegates to.
"""

import pytest

from backend.core.feature_log_edit import (
    FeatureEditError,
    edit_cluster_op_entry,
    edit_deformation_entry,
)
from backend.core.models import (
    BendParams,
    ClusterOpLogEntry,
    ClusterRigidTransform,
    DeformationLogEntry,
    DeformationOp,
    Design,
)


# ── cluster_op edit branch ──────────────────────────────────────────────────


def _design_with_two_cluster_ops():
    """Design where cluster 'A' has two cluster_ops in the log (op0 then op1)
    and a live transform reflecting op1's pose."""
    ct = ClusterRigidTransform(
        id="A",
        helix_ids=["h0"],
        translation=[2.0, 0.0, 0.0],
        rotation=[0, 0, 0, 1],
        pivot=[0, 0, 0],
    )
    op0 = ClusterOpLogEntry(
        cluster_id="A",
        translation=[1.0, 0.0, 0.0],
        rotation=[0, 0, 0, 1],
        pivot=[0, 0, 0],
    )
    op1 = ClusterOpLogEntry(
        cluster_id="A",
        translation=[2.0, 0.0, 0.0],
        rotation=[0, 0, 0, 1],
        pivot=[0, 0, 0],
    )
    return Design(cluster_transforms=[ct], feature_log=[op0, op1])


def test_edit_latest_cluster_op_updates_live_pose():
    d = _design_with_two_cluster_ops()
    entry = d.feature_log[1]
    out = edit_cluster_op_entry(
        d,
        1,
        entry,
        {
            "translation": [9.0, 0.0, 0.0],
            "rotation": [0, 0, 0, 1],
            "pivot": [0, 0, 0],
        },
    )
    # Log entry rewritten...
    assert out.feature_log[1].translation == [9.0, 0.0, 0.0]
    # ...and because op1 is the LAST cluster_op for A, the live transform follows.
    assert out.cluster_transforms[0].translation == [9.0, 0.0, 0.0]


def test_edit_earlier_cluster_op_preserves_latest_pose():
    d = _design_with_two_cluster_ops()
    entry = d.feature_log[0]
    out = edit_cluster_op_entry(
        d,
        0,
        entry,
        {
            "translation": [5.0, 0.0, 0.0],
            "rotation": [0, 0, 0, 1],
            "pivot": [0, 0, 0],
        },
    )
    # The earlier op's seek/scrub frame is rewritten...
    assert out.feature_log[0].translation == [5.0, 0.0, 0.0]
    # ...but op1 still wins for the live pose (last cluster_op for A).
    assert out.cluster_transforms[0].translation == [2.0, 0.0, 0.0]


def test_edit_cluster_op_does_not_mutate_input_design():
    d = _design_with_two_cluster_ops()
    edit_cluster_op_entry(
        d,
        1,
        d.feature_log[1],
        {
            "translation": [9.0, 0.0, 0.0],
            "rotation": [0, 0, 0, 1],
            "pivot": [0, 0, 0],
        },
    )
    assert d.cluster_transforms[0].translation == [2.0, 0.0, 0.0]
    assert d.feature_log[1].translation == [2.0, 0.0, 0.0]


@pytest.mark.parametrize("missing", ["translation", "rotation", "pivot"])
def test_edit_cluster_op_missing_field_is_400(missing):
    d = _design_with_two_cluster_ops()
    params = {"translation": [1, 0, 0], "rotation": [0, 0, 0, 1], "pivot": [0, 0, 0]}
    del params[missing]
    with pytest.raises(FeatureEditError) as ei:
        edit_cluster_op_entry(d, 1, d.feature_log[1], params)
    assert ei.value.status == 400


def test_edit_cluster_op_missing_cluster_is_404():
    d = _design_with_two_cluster_ops()
    ghost = ClusterOpLogEntry(
        cluster_id="GONE",
        translation=[1, 0, 0],
        rotation=[0, 0, 0, 1],
        pivot=[0, 0, 0],
    )
    with pytest.raises(FeatureEditError) as ei:
        edit_cluster_op_entry(
            d,
            1,
            ghost,
            {
                "translation": [1, 0, 0],
                "rotation": [0, 0, 0, 1],
                "pivot": [0, 0, 0],
            },
        )
    assert ei.value.status == 404


# ── deformation edit branch ─────────────────────────────────────────────────


def _design_with_one_bend():
    op = DeformationOp(
        id="d1",
        type="bend",
        plane_a_bp=0,
        plane_b_bp=10,
        affected_helix_ids=["h0"],
        cluster_ids=[],
        params=BendParams(curvature_deg_per_bp=1.0),
    )
    entry = DeformationLogEntry(deformation_id="d1", op_snapshot=op)
    return Design(feature_log=[entry])


def test_edit_deformation_rewrites_op_and_rebuilds_set():
    d = _design_with_one_bend()
    entry = d.feature_log[0]
    out = edit_deformation_entry(
        d,
        0,
        entry,
        {
            "type": "bend",
            "plane_a_bp": 0,
            "plane_b_bp": 20,
            "affected_helix_ids": ["h0"],
            "params": {"curvature_deg_per_bp": 2.0},
        },
    )
    # op_snapshot refreshed in the log...
    assert out.feature_log[0].op_snapshot.plane_b_bp == 20
    assert out.feature_log[0].op_snapshot.params.curvature_deg_per_bp == 2.0
    # ...and design.deformations rebuilt from the log (source of truth).
    assert len(out.deformations) == 1
    assert out.deformations[0].plane_b_bp == 20
    # cursor reset to -1 (live end) so the edit's effect is shown.
    assert out.feature_log_cursor == -1


def test_edit_deformation_preserves_op_id():
    d = _design_with_one_bend()
    out = edit_deformation_entry(
        d,
        0,
        d.feature_log[0],
        {
            "type": "bend",
            "plane_a_bp": 0,
            "plane_b_bp": 15,
            "affected_helix_ids": ["h0"],
            "params": {"curvature_deg_per_bp": 0.5},
        },
    )
    assert out.deformations[0].id == "d1"


def test_edit_deformation_bad_type_is_400():
    d = _design_with_one_bend()
    with pytest.raises(FeatureEditError) as ei:
        edit_deformation_entry(
            d,
            0,
            d.feature_log[0],
            {
                "type": "wobble",
                "plane_a_bp": 0,
                "plane_b_bp": 10,
                "params": {},
            },
        )
    assert ei.value.status == 400


def test_edit_deformation_missing_planes_is_400():
    d = _design_with_one_bend()
    with pytest.raises(FeatureEditError) as ei:
        edit_deformation_entry(
            d,
            0,
            d.feature_log[0],
            {
                "type": "bend",
                "params": {"curvature_deg_per_bp": 1.0},
            },
        )
    assert ei.value.status == 400


def test_edit_deformation_no_snapshot_is_409():
    entry = DeformationLogEntry(deformation_id="d1", op_snapshot=None)
    d = Design(feature_log=[entry])
    with pytest.raises(FeatureEditError) as ei:
        edit_deformation_entry(
            d,
            0,
            entry,
            {
                "type": "bend",
                "plane_a_bp": 0,
                "plane_b_bp": 10,
                "affected_helix_ids": ["h0"],
                "params": {"curvature_deg_per_bp": 1.0},
            },
        )
    assert ei.value.status == 409


def test_edit_deformation_does_not_mutate_input():
    d = _design_with_one_bend()
    edit_deformation_entry(
        d,
        0,
        d.feature_log[0],
        {
            "type": "bend",
            "plane_a_bp": 0,
            "plane_b_bp": 99,
            "affected_helix_ids": ["h0"],
            "params": {"curvature_deg_per_bp": 3.0},
        },
    )
    assert d.feature_log[0].op_snapshot.plane_b_bp == 10
