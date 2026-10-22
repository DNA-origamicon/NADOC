"""Carry saved residue poses through a later authored cluster movement.

Rendering evaluates a residue delta after its owning cluster frame. Changing
that frame from A to B must carry the already-posed residue by D = B A^-1.
Conjugating its saved delta Q to D Q D^-1 gives Q' B = D Q A. This uses only
authored rigid inputs, never displayed/physical coordinates.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from types import SimpleNamespace


def affine(pose):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_quat(pose.rotation).as_matrix()
    pivot = np.asarray(pose.pivot)
    matrix[:3, 3] = pivot - matrix[:3, :3] @ pivot + np.asarray(pose.translation)
    return matrix


def frame(design, pose):
    """Mirror native child, whole-helix, then domain-cluster application order."""
    clusters = [c for c in design.cluster_transforms if pose.helix_id in c.helix_ids]
    clusters.sort(key=lambda c: 0 if c.parent_cluster_id else 2 if c.domain_ids else 1)
    strands = {s.id: s for s in design.strands}
    result = np.eye(4)
    for cluster in clusters:
        if cluster.domain_ids:
            domains = [strands[r.strand_id].domains[r.domain_index] for r in cluster.domain_ids
                       if r.strand_id in strands and r.domain_index < len(strands[r.strand_id].domains)]
            domains = [d for d in domains if d.helix_id == pose.helix_id]
            selected = any(d.direction == pose.direction and
                min(d.start_bp, d.end_bp) <= pose.bp_index <= max(d.start_bp, d.end_bp) for d in domains)
            if not selected and (domains or cluster.parent_cluster_id):
                continue
        result = affine(cluster) @ result
    return result


def anchors(design, pose):
    if pose.kind == 'extra_base':
        crossover = next((c for c in design.crossovers if c.id == pose.crossover_id), None)
        return [] if crossover is None else [SimpleNamespace(helix_id=h.helix_id,
            bp_index=h.index, direction=h.strand) for h in (crossover.half_a, crossover.half_b)]
    if pose.helix_id.startswith('__ext_'):
        extension = next((e for e in design.extensions if f'__ext_{e.id}' == pose.helix_id), None)
        strand = next((s for s in design.strands if extension and s.id == extension.strand_id), None)
        if strand is None or not strand.domains:
            return []
        first = extension.end == 'five_prime'
        domain = strand.domains[0 if first else -1]
        return [SimpleNamespace(helix_id=domain.helix_id, direction=domain.direction,
            bp_index=domain.start_bp if first else domain.end_bp)]
    return [pose]


def carry_member_poses(before, after):
    if not before.nucleotide_transforms:
        return after
    poses = []
    for pose in before.nucleotide_transforms:
        targets = anchors(before, pose)
        if not targets:
            poses.append(pose)
            continue
        frames = [(frame(before, target), frame(after, target)) for target in targets]
        if all(np.array_equal(old, new) for old, new in frames):
            poses.append(pose)
            continue
        old, new = frames[0]
        delta = new @ np.linalg.inv(old)
        if any(not np.allclose(new @ np.linalg.inv(old), delta, atol=1e-10, rtol=0)
               for old, new in frames[1:]):
            raise ValueError('Move both ends of an individually posed crossover insert together before moving its cluster')
        rotation = delta[:3, :3]
        # Moving the pivot and rotating the translation is the same conjugation,
        # while preserving the authored pivot rather than forcing it to zero.
        poses.append(pose.model_copy(update={
            'pivot': (rotation @ np.asarray(pose.pivot) + delta[:3, 3]).tolist(),
            'translation': (rotation @ np.asarray(pose.translation)).tolist(),
            'rotation': Rotation.from_matrix(rotation @ Rotation.from_quat(pose.rotation).as_matrix()
                @ rotation.T).as_quat().tolist(),
        }))
    return after.copy_with(nucleotide_transforms=poses)
