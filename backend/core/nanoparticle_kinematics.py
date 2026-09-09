"""Closed-loop kinematics for multiply anchored nanoparticles.

Each applied handle/overhang duplex is a rigid link with a ball joint at its
fixed crossover root and another at a nanoparticle-local attachment site.  The
nanoparticle pose is solved against *all* links at once; the links are then
swung about their roots to the solved sites.  This is deliberately a closed-
loop constraint solve rather than forward kinematics through a cluster tree.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from backend.core.design_geometry import fitting_geometry
from backend.core.duplex_cluster import (
    dematerialize_duplex_cluster,
    duplex_cluster_for,
    materialize_duplex_cluster,
)
from backend.core.models import Design
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.protein import _rotation_between, resolve_overhang_anchor


@dataclass(frozen=True)
class _Anchor:
    version_id: str
    strand_id: str
    overhang_id: str
    local_joint: np.ndarray
    root: np.ndarray
    link_radius: float


def _owner(design: Design, nanoparticle_id: str, strand_id: str):
    for conjugation in design.nanoparticle_conjugations:
        if conjugation.nanoparticle_id != nanoparticle_id:
            continue
        for record in conjugation.surface_strands:
            if record.strand_id == strand_id:
                return conjugation, record
    return None, None


def _terminal(geometry: list[dict], strand_id: str, attach_end: str):
    flag = "is_three_prime" if attach_end == "3p" else "is_five_prime"
    return next(
        (n for n in geometry if n.get("strand_id") == strand_id and n.get(flag)),
        None,
    )


def _collect_anchors(design: Design, nanoparticle_id: str) -> list[_Anchor]:
    particle = next(p for p in design.nanoparticles if p.id == nanoparticle_id)
    geometry = fitting_geometry(design)
    anchors: list[_Anchor] = []
    versions = sorted(
        (v for v in design.nanoparticle_connection_versions
         if v.nanoparticle_id == nanoparticle_id and v.applied),
        key=lambda v: v.id,
    )
    for version in versions:
        conjugation, record = _owner(design, nanoparticle_id, version.strand_id)
        if conjugation is None or record is None:
            continue
        root, _ = resolve_overhang_anchor(geometry, version.overhang_id, "root")
        handle = _terminal(geometry, version.strand_id, conjugation.attach_end)
        if root is None or handle is None:
            continue
        root = np.asarray(root, dtype=float)
        endpoint = np.asarray(handle["backbone_position"], dtype=float)
        local = (
            np.asarray(record.backbone_attachment_local_nm, dtype=float)
            if record.backbone_attachment_local_nm is not None
            else np.asarray(record.site_local, dtype=float)
            * (particle.diameter_nm / 2.0 + conjugation.spacer_nm)
        )
        radius = float(np.linalg.norm(endpoint - root))
        if radius > 1e-9:
            anchors.append(_Anchor(
                version.id, version.strand_id, version.overhang_id,
                local, root, radius,
            ))
    return anchors


def _pose_from_delta(initial: np.ndarray, params: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_rotvec(params[3:]).as_matrix() @ initial[:3, :3]
    matrix[:3, 3] = initial[:3, 3] + params[:3]
    return matrix


def _world_sites(matrix: np.ndarray, anchors: list[_Anchor]) -> np.ndarray:
    local = np.asarray([a.local_joint for a in anchors], dtype=float)
    return local @ matrix[:3, :3].T + matrix[:3, 3]


def solve_closed_loop_pose(
    initial: np.ndarray,
    local_joints: np.ndarray,
    roots: np.ndarray,
    link_radii: np.ndarray,
    obstacles: np.ndarray,
    clearance_nm: float,
    *,
    max_translation_nm: float = 50.0,
) -> tuple[np.ndarray, dict]:
    """Pure geometric kernel used by the API solver and deterministic tests."""
    initial = np.asarray(initial, dtype=float)
    local_joints = np.asarray(local_joints, dtype=float)
    roots = np.asarray(roots, dtype=float)
    link_radii = np.asarray(link_radii, dtype=float)
    obstacles = np.asarray(obstacles, dtype=float).reshape((-1, 3))

    def sites_for(pose: np.ndarray) -> np.ndarray:
        return local_joints @ pose[:3, :3].T + pose[:3, 3]

    def residual(params: np.ndarray) -> np.ndarray:
        pose = _pose_from_delta(initial, params)
        sites = sites_for(pose)
        link_errors = np.linalg.norm(sites - roots, axis=1) - link_radii
        center = pose[:3, 3]
        penetrations = (
            np.maximum(clearance_nm - np.linalg.norm(obstacles - center, axis=1), 0.0)
            if len(obstacles) else np.empty(0)
        )
        regularization = np.r_[params[:3] * 2e-3, params[3:] * 1e-2]
        return np.r_[link_errors, penetrations * 8.0, regularization]

    bounds = (
        np.r_[np.full(3, -max_translation_nm), np.full(3, -np.pi)],
        np.r_[np.full(3, max_translation_nm), np.full(3, np.pi)],
    )
    solved = least_squares(
        residual, np.zeros(6), bounds=bounds, method="trf",
        ftol=1e-11, xtol=1e-11, gtol=1e-11, max_nfev=1200,
    )
    pose = _pose_from_delta(initial, solved.x)
    joint_errors = np.abs(np.linalg.norm(sites_for(pose) - roots, axis=1) - link_radii)
    center_distances = (
        np.linalg.norm(obstacles - pose[:3, 3], axis=1)
        if len(obstacles) else np.empty(0)
    )
    penetrations = (
        np.maximum(clearance_nm - center_distances, 0.0)
        if len(center_distances) else np.empty(0)
    )
    max_joint = float(np.max(joint_errors))
    max_penetration = float(np.max(penetrations)) if len(penetrations) else 0.0
    tolerance = 0.10
    return pose, {
        "success": bool(solved.success),
        "iterations": int(solved.nfev),
        "message": str(solved.message),
        "joint_errors_nm": joint_errors,
        "rms_residual_nm": float(np.sqrt(np.mean(joint_errors ** 2))),
        "max_joint_error_nm": max_joint,
        "joint_tolerance_nm": tolerance,
        "nearest_dna_center_distance_after_nm": (
            float(np.min(center_distances)) if len(center_distances) else None
        ),
        "max_penetration_nm": max_penetration,
        "converged": bool(solved.success and max_joint <= tolerance and max_penetration <= 0.05),
        "translation_nm": solved.x[:3].tolist(),
        "rotation_delta_quat": Rotation.from_rotvec(solved.x[3:]).as_quat().tolist(),
    }


def _swing_duplexes(
    design: Design, nanoparticle_id: str, anchors: list[_Anchor], pose: np.ndarray,
) -> tuple[Design, list[str]]:
    """Swing every rigid link to its solved NP joint, preserving internal geometry."""
    out = design
    moved: list[str] = []
    sites = _world_sites(pose, anchors)
    for anchor, site in zip(anchors, sites):
        geometry = fitting_geometry(out)
        conjugation, _record = _owner(out, nanoparticle_id, anchor.strand_id)
        root, _ = resolve_overhang_anchor(geometry, anchor.overhang_id, "root")
        handle = _terminal(geometry, anchor.strand_id, conjugation.attach_end)
        if root is None or handle is None:
            continue
        root = np.asarray(root, dtype=float)
        old_ray = np.asarray(handle["backbone_position"], dtype=float) - root
        desired_ray = np.asarray(site, dtype=float) - root
        if np.linalg.norm(old_ray) < 1e-9 or np.linalg.norm(desired_ray) < 1e-9:
            continue
        swing = _rotation_between(old_ray, desired_ray)
        cluster = duplex_cluster_for(out, anchor.overhang_id)
        cluster_id = cluster.id if cluster is not None else None
        cluster_name = cluster.name if cluster is not None else None
        if cluster is not None:
            out = dematerialize_duplex_cluster(out, anchor.overhang_id)
        spec = next((o for o in out.overhangs if o.id == anchor.overhang_id), None)
        if spec is None:
            continue
        new_rotation = swing @ Rotation.from_quat(spec.rotation).as_matrix()
        out = out.model_copy(update={"overhangs": [
            item.model_copy(update={
                "rotation": Rotation.from_matrix(new_rotation).as_quat().tolist()
            }) if item.id == anchor.overhang_id else item
            for item in out.overhangs
        ]})
        out, _ = materialize_duplex_cluster(
            out, anchor.overhang_id, name=cluster_name, cluster_id=cluster_id,
        )
        moved.append(anchor.version_id)
    return out, moved


def solve_nanoparticle_anchors(
    design: Design,
    nanoparticle_id: str,
    *,
    clearance_margin_nm: float = 0.75,
    max_translation_nm: float = 50.0,
) -> tuple[Design, dict]:
    """Jointly solve every applied anchor and return an updated design + diagnostics.

    Link-length residuals and excluded-volume penetration are optimized together.
    A solution may retain residual when the closed loop is geometrically infeasible;
    diagnostics make that explicit instead of distorting a rigid duplex.
    """
    particle = next(p for p in design.nanoparticles if p.id == nanoparticle_id)
    anchors = _collect_anchors(design, nanoparticle_id)
    if not anchors:
        raise ValueError("Applied connections have no resolvable overhang geometry.")

    initial = particle.pose.to_array().copy()
    owned = {
        record.strand_id
        for conjugation in design.nanoparticle_conjugations
        if conjugation.nanoparticle_id == nanoparticle_id
        for record in conjugation.surface_strands
    }
    geometry = fitting_geometry(design)
    obstacles = np.asarray([
        n["backbone_position"] for n in geometry
        if n.get("strand_id") not in owned and n.get("backbone_position") is not None
    ], dtype=float)
    if not obstacles.size:
        obstacles = np.empty((0, 3), dtype=float)
    clearance = particle.diameter_nm / 2.0 + float(clearance_margin_nm)

    pose, kernel = solve_closed_loop_pose(
        initial,
        np.asarray([a.local_joint for a in anchors]),
        np.asarray([a.root for a in anchors]),
        np.asarray([a.link_radius for a in anchors]),
        obstacles,
        clearance,
        max_translation_nm=max_translation_nm,
    )
    joint_errors = kernel["joint_errors_nm"]

    moved = replace_gold_nanosphere(
        design, nanoparticle_id, pose=pose.reshape(-1).tolist(),
    )
    moved, oriented_ids = _swing_duplexes(moved, nanoparticle_id, anchors, pose)
    return moved, {
        "solver": "closed_loop_least_squares",
        "converged": kernel["converged"],
        "infeasible": not kernel["converged"],
        "iterations": kernel["iterations"],
        "message": kernel["message"],
        "anchor_count": len(anchors),
        "version_ids": [a.version_id for a in anchors],
        "duplex_reorientation_version_ids": oriented_ids,
        "per_anchor_residual_nm": {
            anchor.version_id: float(error)
            for anchor, error in zip(anchors, joint_errors)
        },
        "rms_residual_nm": kernel["rms_residual_nm"],
        "max_joint_error_nm": kernel["max_joint_error_nm"],
        "joint_tolerance_nm": kernel["joint_tolerance_nm"],
        "dna_clearance_target_nm": clearance,
        "nearest_dna_center_distance_after_nm": kernel["nearest_dna_center_distance_after_nm"],
        "max_penetration_nm": kernel["max_penetration_nm"],
        "translation_nm": kernel["translation_nm"],
        "rotation_delta_quat": kernel["rotation_delta_quat"],
    }
