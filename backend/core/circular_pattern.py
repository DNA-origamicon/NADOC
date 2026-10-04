"""Circular copies retain canonical lattice cells; rigid placement uses new frames."""

import math
import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.cluster_copy import extract_cluster_subdesign
from backend.core.lattice_frame_model import LatticeFrame
from backend.core.models import ClusterRigidTransform
from backend.core.primitive_placement import detect_plane


def pattern_angles(instances, total_angle):
    if type(instances) is not int or not 1 <= instances <= 128:
        raise ValueError("Instances must be an integer from 1 to 128")
    if not math.isfinite(total_angle) or not 0 < total_angle <= 360:
        raise ValueError("Total angle must be greater than 0 and at most 360 degrees")
    divisor = instances if total_angle == 360 else max(1, instances - 1)
    return [math.radians(total_angle) * i / divisor for i in range(instances)]


def _pose(cluster):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_quat(cluster.rotation).as_matrix()
    pivot = np.array(cluster.pivot)
    matrix[:3, 3] = pivot + np.array(cluster.translation) - matrix[:3, :3] @ pivot
    return matrix


def create_circular_pattern(
    design, cluster_id, instances, total_angle, axis_point, axis_direction
):
    """Pure additive copy; source topology and placements remain unchanged.

    Existing cluster extraction owns strand-boundary truncation and copy eligibility.
    A new frame per distinct source placement preserves cell parity and prevents
    unrelated instances sharing lattice addresses. Poses compose after deformation.
    """
    angles = pattern_angles(instances, total_angle)
    point, direction = (
        np.asarray(axis_point, dtype=float),
        np.asarray(axis_direction, dtype=float),
    )
    if (
        point.shape != (3,)
        or direction.shape != (3,)
        or not np.isfinite([point, direction]).all()
        or not math.isfinite(float(np.linalg.norm(direction)))
        or np.linalg.norm(direction) < 1e-8
    ):
        raise ValueError("A finite axis point and nonzero direction are required")
    direction = direction / np.linalg.norm(direction)
    source = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if source is None:
        raise ValueError("Source cluster no longer exists")
    if source.domain_ids:
        raise ValueError(
            "Circular pattern confirmation currently requires a whole-helix cluster"
        )
    copied = set(source.helix_ids) - design.reference_helix_ids()
    poses = [c for c in design.cluster_transforms if copied & set(c.helix_ids)]
    if any(c.domain_ids for c in poses):
        raise ValueError(
            "Circular pattern cannot yet copy domain-specific cluster poses"
        )
    source_crossovers = {
        x.id
        for x in design.crossovers
        if x.half_a.helix_id in copied or x.half_b.helix_id in copied
    }
    if any(
        t.helix_id in copied or t.crossover_id in source_crossovers
        for t in design.nucleotide_transforms
    ):
        raise ValueError(
            "Circular pattern cannot yet copy individual nucleotide transforms"
        )
    # Extraction needs a self-contained frame-free view; cells and axes themselves
    # are unchanged. Placement is reconstructed below, including overlapping poses.
    extraction = design.model_copy(
        update={
            "lattice_frames": [],
            "helices": [
                h.model_copy(update={"lattice_frame_id": None}) for h in design.helices
            ],
            "cluster_transforms": [
                source.model_copy(update={"parent_cluster_id": None})
            ],
        }
    )
    sub, report = extract_cluster_subdesign(extraction, [cluster_id])
    if any(h.grid_pos is None for h in sub.helices):
        raise ValueError("Circular pattern requires lattice-addressed helices")
    if len(angles) == 1:
        return design, [], report
    frames = {f.id: f for f in design.lattice_frames}
    original_helices = {h.id: h for h in design.helices}
    # Whole-helix child entries are not applied by the domain-aware renderer.
    ordered_poses = [c for c in poses if not c.parent_cluster_id]
    groups = {}
    for h in sub.helices:
        pose = np.eye(4)
        for c in ordered_poses:
            if h.id in c.helix_ids:
                pose = _pose(c) @ pose
        frame_id = original_helices[h.id].lattice_frame_id
        plane = (
            frames[frame_id].plane
            if frame_id
            else detect_plane(sub.model_copy(update={"helices": [h]}))
        )
        key = (frame_id, plane, tuple(pose.flatten()))
        groups.setdefault(key, []).append(h.id)
    result = design.model_copy(deep=True)
    new_ids = []
    for index, angle in enumerate(angles[1:], 2):
        rotation = Rotation.from_rotvec(direction * angle).as_matrix()
        turn = np.eye(4)
        turn[:3, :3] = rotation
        turn[:3, 3] = point - rotation @ point
        hmap = {h.id: str(uuid.uuid4()) for h in sub.helices}
        smap = {s.id: str(uuid.uuid4()) for s in sub.strands}
        root_id = str(uuid.uuid4())
        root_name = f"{source.name or 'Cluster'} · Pattern {index}"
        if len(groups) > 1:
            result.cluster_transforms.append(
                ClusterRigidTransform(
                    id=root_id,
                    name=root_name,
                    helix_ids=list(hmap.values()),
                    color=source.color,
                    opacity=source.opacity,
                )
            )
        frame_by_helix = {}
        for (_, plane, values), ids in groups.items():
            placed = turn @ np.array(values).reshape(4, 4)
            cid = root_id if len(groups) == 1 else str(uuid.uuid4())
            frame = LatticeFrame(
                id=str(uuid.uuid4()), plane=plane, placement_cluster_id=cid
            )
            result.lattice_frames.append(frame)
            result.cluster_transforms.append(
                ClusterRigidTransform(
                    id=cid,
                    name=root_name if len(groups) == 1 else f"{root_name} · Placement",
                    helix_ids=[hmap[hid] for hid in ids],
                    translation=placed[:3, 3].tolist(),
                    rotation=Rotation.from_matrix(placed[:3, :3]).as_quat().tolist(),
                    color=source.color,
                    opacity=source.opacity,
                )
            )
            frame_by_helix.update({hid: frame.id for hid in ids})
        result.helices.extend(
            h.model_copy(
                update={"id": hmap[h.id], "lattice_frame_id": frame_by_helix[h.id]}
            )
            for h in sub.helices
        )
        result.strands.extend(
            s.model_copy(
                update={
                    "id": smap[s.id],
                    "domains": [
                        d.model_copy(update={"helix_id": hmap[d.helix_id]})
                        for d in s.domains
                    ],
                }
            )
            for s in sub.strands
        )
        result.crossovers.extend(
            x.model_copy(
                update={
                    "id": str(uuid.uuid4()),
                    "half_a": x.half_a.model_copy(
                        update={"helix_id": hmap[x.half_a.helix_id]}
                    ),
                    "half_b": x.half_b.model_copy(
                        update={"helix_id": hmap[x.half_b.helix_id]}
                    ),
                }
            )
            for x in sub.crossovers
        )
        result.forced_ligations.extend(
            x.model_copy(
                update={
                    "id": str(uuid.uuid4()),
                    "three_prime_helix_id": hmap[x.three_prime_helix_id],
                    "five_prime_helix_id": hmap[x.five_prime_helix_id],
                }
            )
            for x in sub.forced_ligations
        )
        for op in design.deformations:
            affected = copied & set(op.affected_helix_ids)
            if affected:
                result.deformations.append(
                    op.model_copy(
                        update={
                            "id": str(uuid.uuid4()),
                            "affected_helix_ids": [
                                hmap[hid] for hid in sorted(affected)
                            ],
                            "cluster_ids": [root_id],
                        }
                    )
                )
        new_ids.extend(hmap.values())
    return result, new_ids, report


def pattern_history_overlays(design, decode_snapshot):
    """Restore copy-owned overlays after topology seek, preserving later pose edits."""
    clusters, deformations = {}, {}
    for entry in design.feature_log:
        if (
            getattr(entry, "op_kind", None) != "circular-pattern"
            or entry.evicted
            or not entry.post_state_gz_b64
            or not entry.design_snapshot_gz_b64
        ):
            continue
        before = decode_snapshot(entry.design_snapshot_gz_b64)
        after = decode_snapshot(entry.post_state_gz_b64)
        old_clusters = {c.id for c in before.cluster_transforms}
        old_ops = {op.id for op in before.deformations}
        clusters.update(
            {c.id: c for c in after.cluster_transforms if c.id not in old_clusters}
        )
        deformations.update(
            {op.id: op for op in after.deformations if op.id not in old_ops}
        )
    visible = {h.id for h in design.helices}
    current = {c.id: c for c in design.cluster_transforms}
    surviving = {
        cid: current.get(cid, c)
        for cid, c in clusters.items()
        if c.helix_ids and set(c.helix_ids) <= visible
    }
    result = [c for c in design.cluster_transforms if c.id not in clusters]
    result.extend(surviving.values())
    ops = [
        op
        for op in deformations.values()
        if op.affected_helix_ids and set(op.affected_helix_ids) <= visible
    ]
    return result, ops
