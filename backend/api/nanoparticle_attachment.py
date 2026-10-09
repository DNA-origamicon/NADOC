"""Atomic attachment command shared by the viewport and generator.

Planning happens on a private design. Existing duplex builders remain the sole
topology/placement authority; only rigid poses are optimized here.
"""

import numpy as np
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.core.models import NanoparticleConnectionVersion
from backend.core.design_geometry import fitting_geometry
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.nanoparticle_attachment_fit import attachment_joint, fit_swing
from backend.core.nanoparticle_attachment_obstacles import (
    duplex_obstacles,
    particle_clearance,
    protein_points,
)
from backend.core.duplex_cluster import (
    duplex_cluster_for,
    dematerialize_duplex_cluster,
    materialize_duplex_cluster,
)
from backend.core.protein import resolve_overhang_anchor, _rotation_between
from backend.core.sequences import assign_staple_sequences


def attach_nanoparticle(
    design,
    nanoparticle_id,
    overhang_id,
    *,
    strand_id=None,
    fixed_center=False,
    frame=None,
    angles=None,
):
    from backend.api.routes_nanoparticles import (
        _set_np_version_applied,
        _validate_np_connection_polarity,
    )
    from backend.core.nanoparticle_kinematics import solve_nanoparticle_anchors

    particle = next((p for p in design.nanoparticles if p.id == nanoparticle_id), None)
    target = next((o for o in design.overhangs if o.id == overhang_id), None)
    if particle is None or target is None or target.auxiliary_endpoint:
        raise ValueError("Select a nanoparticle and an ordinary origami overhang.")
    if particle.kind != "gold_nanosphere" or particle.coating is not None:
        raise ValueError(
            "Attach to overhang currently requires thiol-DNA on an uncoated gold nanoparticle."
        )
    if (
        any(
            v.applied and v.overhang_id == overhang_id
            for v in design.nanoparticle_connection_versions
        )
        or any(
            d.binds_overhang_id == overhang_id
            for s in design.strands
            for d in s.domains
        )
        or any(
            dx.bound and overhang_id in (dx.left.overhang_id, dx.right.overhang_id)
            for dx in design.duplexes
        )
    ):
        raise ValueError("This overhang is already occupied.")
    if not target.sequence or any(b not in "ACGT" for b in target.sequence.upper()):
        raise ValueError("Assign a complete A/C/G/T sequence to the overhang first.")
    complement = target.sequence.upper().translate(str.maketrans("ACGT", "TGCA"))[::-1]
    candidates = []
    for owner in design.nanoparticle_conjugations:
        if (
            owner.nanoparticle_id != nanoparticle_id
            or owner.sequence.upper() != complement
        ):
            continue
        for record in owner.surface_strands:
            if record.bound_overhang_id is not None or (
                strand_id and record.strand_id != strand_id
            ):
                continue
            if any(
                v.applied and v.strand_id == record.strand_id
                for v in design.nanoparticle_connection_versions
            ):
                continue
            for variant in ("end-to-root", "root-to-root"):
                try:
                    _validate_np_connection_polarity(
                        design, owner, overhang_id, variant
                    )
                except HTTPException:
                    continue
                candidates.append((record.strand_id, variant))
    if not candidates:
        raise ValueError(
            "No free complementary handle with compatible polarity. Create one in Conjugate Manager first."
        )

    failures = []
    for selected, variant in candidates:
        try:
            version = NanoparticleConnectionVersion(
                name="Attach to overhang",
                nanoparticle_id=nanoparticle_id,
                strand_id=selected,
                overhang_id=overhang_id,
                direct_variant=variant,
            )
            # An unapplied version can restore an older free carrier. Refresh
            # particle-owned free handles at the current body pose before use.
            out = replace_gold_nanosphere(
                design, nanoparticle_id, pose=particle.pose.values
            )
            out = out.copy_with(
                nanoparticle_connection_versions=[
                    *design.nanoparticle_connection_versions,
                    version,
                ]
            )
            out = _set_np_version_applied(out, version.id, True)
            applied = [
                v
                for v in out.nanoparticle_connection_versions
                if v.applied and v.nanoparticle_id == nanoparticle_id
            ]
            if not fixed_center and len(applied) == 1:
                # Start near the reachable shell even if the user selected a
                # remote overhang. The local solver's 50 nm bound is a search
                # radius, not a limit on how far authoring can move a particle.
                seed_geometry = fitting_geometry(
                    out, strand_ids={selected}, overhang_ids={overhang_id}
                )
                root, _ = resolve_overhang_anchor(seed_geometry, overhang_id, "root")
                joint, local = attachment_joint(out, version, seed_geometry)
                pose = particle.pose.to_array().copy()
                ray = pose[:3, 3] - root
                distance = np.linalg.norm(ray)
                link, radius = np.linalg.norm(joint - root), np.linalg.norm(local)
                reachable = np.clip(
                    distance, abs(link - radius) + 0.03, link + radius - 0.03
                )
                if distance < 1e-9 or abs(reachable - distance) > 1e-9:
                    pose[:3, 3] = (
                        root
                        + (
                            ray / distance
                            if distance > 1e-9
                            else np.array([0.0, 1.0, 0.0])
                        )
                        * reachable
                    )
                    out = replace_gold_nanosphere(
                        out, nanoparticle_id, pose=pose.reshape(-1).tolist()
                    )
            if not fixed_center or len(applied) > 1:
                out, diagnostics = solve_nanoparticle_anchors(
                    out,
                    nanoparticle_id,
                    fixed_center=fixed_center,
                    include_structure=True,
                )
                if diagnostics["anchor_count"] != len(applied):
                    raise ValueError("An existing attachment has unresolved geometry.")
                # An optimizer iteration limit is not itself a geometry failure.
                # Accept only measured closure/clearance; emitted poses are checked
                # again below after the exact rigid swing.
                if (
                    diagnostics["max_joint_error_nm"] > 0.02
                    or diagnostics["max_penetration_nm"] > 0.05
                ):
                    raise ValueError(
                        "No feasible pose preserves every applied attachment."
                    )
            if len(applied) == 1:
                geometry = fitting_geometry(out)
                root, _ = resolve_overhang_anchor(geometry, overhang_id, "root")
                joint, local = attachment_joint(out, version, geometry)
                current = next(p for p in out.nanoparticles if p.id == nanoparticle_id)
                center = current.pose.to_array()[:3, 3]
                proteins = protein_points(out, geometry)
                tree = duplex_obstacles(geometry, version, root, proteins)
                target_joint, swing, _ = fit_swing(
                    root,
                    joint,
                    center,
                    np.linalg.norm(local),
                    np.eye(3) if frame is None else frame,
                    geometry,
                    version,
                    out.nanoparticles,
                    [p.pose.to_array()[:3, 3] for p in out.nanoparticles],
                    angles,
                    obstacle_tree=tree,
                )
                cluster = duplex_cluster_for(out, overhang_id)
                out = dematerialize_duplex_cluster(out, overhang_id)
                out = out.copy_with(
                    overhangs=[
                        o.model_copy(
                            update={
                                "rotation": Rotation.from_matrix(
                                    swing @ Rotation.from_quat(o.rotation).as_matrix()
                                )
                                .as_quat()
                                .tolist()
                            }
                        )
                        if o.id == overhang_id
                        else o
                        for o in out.overhangs
                    ]
                )
                pose = current.pose.to_array().copy()
                pose[:3, :3] = (
                    _rotation_between(pose[:3, :3] @ local, target_joint - center)
                    @ pose[:3, :3]
                )
                out = replace_gold_nanosphere(
                    out, nanoparticle_id, pose=pose.reshape(-1).tolist()
                )
                out, _ = materialize_duplex_cluster(
                    out,
                    overhang_id,
                    cluster_id=cluster.id if cluster else None,
                    name=cluster.name if cluster else None,
                )
            geometry = fitting_geometry(out)
            clearance = particle_clearance(out, geometry, nanoparticle_id)
            if clearance < -1e-6:
                raise ValueError(
                    "No collision-free attachment was found; particle intersects existing structure."
                )
            current = next(p for p in out.nanoparticles if p.id == nanoparticle_id)
            measurements = {}
            for v in applied:
                joint, local = attachment_joint(out, v, geometry)
                residual = float(
                    np.linalg.norm(
                        joint - (current.pose.to_array() @ np.r_[local, 1])[:3]
                    )
                )
                if residual > 0.02:
                    raise ValueError("Attachment does not close within 0.02 nm.")
                root, _ = resolve_overhang_anchor(geometry, v.overhang_id, "root")
                obstacles = duplex_obstacles(
                    geometry, v, root, protein_points(out, geometry)
                )
                points = np.asarray(
                    [
                        n[k]
                        for n in geometry
                        if n.get("strand_id") == v.strand_id
                        or n.get("overhang_id") == v.overhang_id
                        for k in ("backbone_position", "base_position")
                    ]
                )
                if obstacles.n and obstacles.query(points)[0].min() < 0.5 - 1e-6:
                    raise ValueError(
                        "Fitted duplex intersects existing DNA or protein structure."
                    )
                measurements[v.id] = dict(
                    relaxed=True, residual_nm=residual, constraint_root_nm=tuple(root)
                )
            if fixed_center and not np.array_equal(
                current.pose.to_array()[:3, 3], particle.pose.to_array()[:3, 3]
            ):
                raise ValueError("Attachment moved a locked particle center.")
            out = out.copy_with(
                nanoparticle_connection_versions=[
                    v.model_copy(update=measurements.get(v.id, {}))
                    for v in out.nanoparticle_connection_versions
                ]
            )
            # A rigid pose must not erase user-authored sequences elsewhere.
            # Restore the target's sequence after materialization when topology
            # is unchanged; derive only an invalidated target when necessary.
            original = design.find_strand(target.strand_id)
            target_strand = out.find_strand(target.strand_id)
            if target_strand.sequence is None:
                sequence = (
                    original.sequence
                    if original.domains == target_strand.domains
                    else None
                )
                if sequence is None:
                    sequence = (
                        assign_staple_sequences(out)
                        .find_strand(target.strand_id)
                        .sequence
                    )
                out = out.copy_with(
                    strands=[
                        s.model_copy(update={"sequence": sequence})
                        if s.id == target.strand_id
                        else s
                        for s in out.strands
                    ]
                )
            return out, {
                "version_id": version.id,
                "strand_id": selected,
                "fixed_center": fixed_center,
                "clearance_nm": clearance,
                "residual_nm": measurements[version.id]["residual_nm"],
            }
        except ValueError as exc:
            failures.append(str(exc))
    raise ValueError(failures[-1])
