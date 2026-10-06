"""Pattern copies retain canonical lattice cells; rigid placement uses new frames."""

import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.cluster_copy import extract_cluster_subdesign
from backend.core.lattice_frame_model import LatticeFrame
from backend.core.models import ClusterRigidTransform
from backend.core.primitive_placement import detect_plane


def _pose(cluster):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_quat(cluster.rotation).as_matrix()
    pivot = np.array(cluster.pivot)
    matrix[:3, 3] = pivot + np.array(cluster.translation) - matrix[:3, :3] @ pivot
    return matrix


def copy_pattern_instances(design, cluster_id, placements, *, id_seed=None):
    """Pure additive copy; source topology and placements remain unchanged.

    Existing cluster extraction owns strand-boundary truncation and copy eligibility.
    A new frame per distinct source placement preserves cell parity and prevents
    unrelated instances sharing lattice addresses. Poses compose after deformation.
    """
    cluster_ids = [cluster_id] if isinstance(cluster_id, str) else list(cluster_id)
    by_id = {c.id: c for c in design.cluster_transforms}
    if not cluster_ids or any(cid not in by_id for cid in cluster_ids):
        raise ValueError("Source cluster no longer exists")
    sources = [by_id[cid] for cid in cluster_ids]
    if any(c.domain_ids for c in sources):
        raise ValueError(
            "Pattern confirmation currently requires a whole-helix cluster"
        )
    cluster_id = "/".join(cluster_ids)
    source = (
        sources[0]
        if len(sources) == 1
        else ClusterRigidTransform(
            id=cluster_id,
            name=f"{len(sources)} clusters",
            helix_ids=list(dict.fromkeys(hid for c in sources for hid in c.helix_ids)),
        )
    )
    copied = set(source.helix_ids) - design.reference_helix_ids()
    poses = [c for c in design.cluster_transforms if copied & set(c.helix_ids)]
    if any(c.domain_ids for c in poses):
        raise ValueError("Pattern cannot yet copy domain-specific cluster poses")
    source_crossovers = {
        x.id
        for x in design.crossovers
        if x.half_a.helix_id in copied or x.half_b.helix_id in copied
    }
    if any(
        t.helix_id in copied or t.crossover_id in source_crossovers
        for t in design.nucleotide_transforms
    ):
        raise ValueError("Pattern cannot yet copy individual nucleotide transforms")
    # Extraction needs a self-contained frame-free view; cells and axes themselves
    # are unchanged. Placement is reconstructed below, including overlapping poses.
    extraction = design.model_copy(
        update={
            "lattice_frames": [],
            "helices": [
                h.model_copy(update={"lattice_frame_id": None}) for h in design.helices
            ],
            "cluster_transforms": [
                c.model_copy(update={"parent_cluster_id": None}) for c in sources
            ],
        }
    )
    # Extract the selected union once: strands/crossovers between selected
    # clusters belong to the same copied pattern, not to a cut boundary.
    sub, report = extract_cluster_subdesign(extraction, cluster_ids)
    if any(h.grid_pos is None for h in sub.helices):
        raise ValueError("Pattern requires lattice-addressed helices")
    if not placements:
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
        owner = next(c.id for c in sources if h.id in c.helix_ids)
        key = (frame_id, plane, tuple(pose.flatten()), owner)
        groups.setdefault(key, []).append(h.id)
    result = design.model_copy(deep=True)
    new_ids = []
    seed = id_seed or str(uuid.uuid4())
    for index, (instance_key, turn) in enumerate(placements, 2):

        def new_id(kind, source_id):
            return str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{seed}/{cluster_id}/{instance_key}/{kind}/{source_id}",
                )
            )

        hmap = {h.id: new_id("helix", h.id) for h in sub.helices}
        # Extraction gives truncated strand fragments fresh IDs. Their traversal
        # order is stable, so key copies by fragment index for repeatable edits.
        smap = {s.id: new_id("strand", i) for i, s in enumerate(sub.strands)}
        root_id = new_id("cluster", "root")
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
        for (_, plane, values, owner), ids in groups.items():
            placed = turn @ np.array(values).reshape(4, 4)
            cid = root_id if len(groups) == 1 else new_id("cluster", ids[0])
            frame = LatticeFrame(
                id=new_id("frame", ids[0]), plane=plane, placement_cluster_id=cid
            )
            result.lattice_frames.append(frame)
            result.cluster_transforms.append(
                ClusterRigidTransform(
                    id=cid,
                    name=root_name
                    if len(groups) == 1
                    else f"{by_id[owner].name or 'Cluster'} · Pattern {index} · Placement",
                    helix_ids=[hmap[hid] for hid in ids],
                    translation=placed[:3, 3].tolist(),
                    rotation=Rotation.from_matrix(placed[:3, :3]).as_quat().tolist(),
                    color=by_id[owner].color,
                    opacity=by_id[owner].opacity,
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
                    "id": new_id("crossover", x.id),
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
                    "id": new_id("ligation", x.id),
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
                            "id": new_id("deformation", op.id),
                            "affected_helix_ids": [
                                hmap[hid] for hid in sorted(affected)
                            ],
                            "cluster_ids": [root_id],
                        }
                    )
                )
        new_ids.extend(hmap.values())
    return result, new_ids, report
