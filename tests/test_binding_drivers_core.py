"""Direct tests for overhang-binding joint-driver arbitration."""

from backend.core.binding_drivers import (
    apply_driver_to_joint,
    first_claimant_for_joint,
    select_driver_for_joint,
)
from backend.core.models import ClusterJoint, Design, OverhangBinding


def _binding(*, created: float, bound: bool, locked: float | None = None):
    return OverhangBinding(
        name=f"B{created:g}",
        sub_domain_a_id=f"a-{created}",
        sub_domain_b_id=f"b-{created}",
        overhang_a_id=f"oa-{created}",
        overhang_b_id=f"ob-{created}",
        target_joint_id="joint-1",
        created_at=created,
        bound=bound,
        locked_angle_deg=locked,
    )


def _design(bindings):
    joint = ClusterJoint(
        id="joint-1",
        cluster_id="cluster-1",
        local_axis_origin=[0.0, 0.0, 0.0],
        local_axis_direction=[0.0, 1.0, 0.0],
        min_angle_deg=-90.0,
        max_angle_deg=90.0,
    )
    # This unit isolates arbitration from Design's cross-reference validator;
    # route coverage supplies fully resolved overhang/sub-domain topology.
    return Design.model_construct(overhang_bindings=bindings, cluster_joints=[joint])


def test_latest_bound_claimant_is_the_driver():
    older = _binding(created=1.0, bound=True, locked=10.0)
    newer = _binding(created=2.0, bound=True, locked=20.0)
    design = _design([newer, older])
    assert select_driver_for_joint(design, "joint-1") is newer
    assert first_claimant_for_joint(design, "joint-1") is older


def test_driver_collapses_joint_window_to_locked_angle():
    design = _design([_binding(created=1.0, bound=True, locked=25.0)])
    updated = apply_driver_to_joint(design, "joint-1")
    joint = updated.cluster_joints[0]
    assert (joint.min_angle_deg, joint.max_angle_deg) == (25.0, 25.0)


def test_first_claimant_snapshot_restores_window_without_driver():
    claimant = _binding(created=1.0, bound=False)
    claimant.prior_min_angle_deg = -45.0
    claimant.prior_max_angle_deg = 60.0
    updated = apply_driver_to_joint(_design([claimant]), "joint-1")
    joint = updated.cluster_joints[0]
    assert (joint.min_angle_deg, joint.max_angle_deg) == (-45.0, 60.0)
