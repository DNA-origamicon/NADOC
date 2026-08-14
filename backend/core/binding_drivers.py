"""Joint-driver arbitration for competing overhang bindings."""

from typing import Optional

from backend.core.models import Design, OverhangBinding


def select_driver_for_joint(
    design: Design, joint_id: str
) -> Optional[OverhangBinding]:
    """Return the latest-created bound binding driving a joint."""
    candidates = [
        binding
        for binding in design.overhang_bindings
        if binding.bound and binding.target_joint_id == joint_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda binding: (binding.created_at, binding.id))
    return candidates[-1]


def first_claimant_for_joint(
    design: Design, joint_id: str
) -> Optional[OverhangBinding]:
    """Return the earliest-created binding, bound or unbound, claiming a joint."""
    candidates = [
        binding
        for binding in design.overhang_bindings
        if binding.target_joint_id == joint_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda binding: (binding.created_at, binding.id))
    return candidates[0]


def apply_driver_to_joint(design: Design, joint_id: str) -> Design:
    """Freeze a joint to its active driver or restore its claimant snapshot."""
    driver = select_driver_for_joint(design, joint_id)
    joints = []
    for joint in design.cluster_joints:
        if joint.id != joint_id:
            joints.append(joint)
            continue
        if driver is not None and driver.locked_angle_deg is not None:
            joints.append(
                joint.model_copy(
                    update={
                        "min_angle_deg": driver.locked_angle_deg,
                        "max_angle_deg": driver.locked_angle_deg,
                    }
                )
            )
            continue
        first = first_claimant_for_joint(design, joint_id)
        if (
            first is not None
            and first.prior_min_angle_deg is not None
            and first.prior_max_angle_deg is not None
        ):
            joints.append(
                joint.model_copy(
                    update={
                        "min_angle_deg": first.prior_min_angle_deg,
                        "max_angle_deg": first.prior_max_angle_deg,
                    }
                )
            )
        else:
            joints.append(joint)
    return design.model_copy(update={"cluster_joints": joints})
