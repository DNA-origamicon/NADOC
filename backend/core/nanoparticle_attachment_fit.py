"""Rigid attachment fitting shared by manual authoring and design generation."""

import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.protein import _rotation_between


def _surface_owner(design, nanoparticle_id, strand_id):
    for owner in design.nanoparticle_conjugations:
        if owner.nanoparticle_id == nanoparticle_id:
            for record in owner.surface_strands:
                if record.strand_id == strand_id:
                    return owner, record
    raise ValueError("Nanoparticle handle was not found.")


def attachment_joint(design, version, geometry):
    owner, record = _surface_owner(design, version.nanoparticle_id, version.strand_id)
    flag = "is_five_prime" if owner.attach_end == "5p" else "is_three_prime"
    point = next(
        n["backbone_position"]
        for n in geometry
        if n.get("strand_id") == version.strand_id and n.get(flag)
    )
    return np.asarray(point), np.asarray(record.backbone_attachment_local_nm)


def fit_swing(
    root,
    joint,
    center,
    radius,
    frame,
    geometry,
    version,
    particles,
    centers,
    angles=None,
    obstacle_tree=None,
    phase_samples=16,
    roll_samples=24,
):
    """Search the sphere-intersection circle and duplex axial roll for clearance.

    Both rigid rotations preserve the exact graft joint and crossover bead.
    Evaluate emitted native DNA landmarks, including bases, before committing
    a pose; the shortest swing alone can put the opposite strand inside gold.
    """
    length = np.linalg.norm(joint - root)
    delta = center - root
    distance = np.linalg.norm(delta)
    if distance > length + radius + 1e-7 or distance < abs(length - radius) - 1e-7:
        raise ValueError(
            "The fixed-center attachment spheres do not intersect. Try a longer duplex."
        )
    unit = delta / distance
    a = (length**2 - radius**2 + distance**2) / (2 * distance)
    perpendicular = frame[:, 2] - unit * np.dot(frame[:, 2], unit)
    if np.linalg.norm(perpendicular) < 1e-8:
        reference = np.eye(3)[int(np.argmin(np.abs(unit)))]
        perpendicular = reference - unit * np.dot(reference, unit)
    perpendicular /= np.linalg.norm(perpendicular)
    other = np.cross(unit, perpendicular)
    circle_radius = np.sqrt(max(0, length**2 - a**2))
    points = np.array(
        [
            n[key]
            for n in geometry
            if n.get("strand_id") == version.strand_id
            or n.get("overhang_id") == version.overhang_id
            for key in ("backbone_position", "base_position")
        ]
    )
    best = None
    best_clearance = -float("inf")
    phases = (
        [np.radians(angles["phase_deg"])]
        if angles and "phase_deg" in angles
        else np.linspace(0, 2 * np.pi, phase_samples, endpoint=False)
    )
    rolls = (
        np.array([np.radians(angles["duplex_roll_deg"])])
        if angles and "duplex_roll_deg" in angles
        else np.linspace(0, 2 * np.pi, roll_samples, endpoint=False)
    )
    if not np.isfinite(phases).all() or not np.isfinite(rolls).all():
        raise ValueError("Attachment angles must be finite.")
    for phase in phases:
        target = (
            root
            + a * unit
            + circle_radius * (np.cos(phase) * perpendicular + np.sin(phase) * other)
        )
        swing = _rotation_between(joint - root, target - root)
        axis = (target - root) / length
        rotations = Rotation.from_rotvec(rolls[:, None] * axis).as_matrix() @ swing
        transformed = np.einsum("kij,nj->kni", rotations, points - root) + root
        clearance = np.min(
            np.stack(
                [
                    np.linalg.norm(transformed - c, axis=2) - p.diameter_nm / 2
                    for p, c in zip(particles, centers)
                ]
            ),
            axis=(0, 2),
        )
        if obstacle_tree is not None and obstacle_tree.n:
            distances, _ = obstacle_tree.query(transformed.reshape((-1, 3)))
            clearance = np.minimum(
                clearance, distances.reshape(transformed.shape[:2]).min(axis=1) - 0.5
            )
        index = int(np.argmax(clearance))
        if clearance[index] > best_clearance:
            best_clearance = clearance[index]
            best = (
                target,
                rotations[index],
                {
                    "phase_deg": float(np.degrees(phase)),
                    "duplex_roll_deg": float(np.degrees(rolls[index])),
                },
            )
    if best_clearance < 0:
        raise ValueError(
            "No sampled fixed-center duplex orientation clears all gold cores. Try a longer duplex or a different particle arrangement."
        )
    return best
