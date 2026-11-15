"""Precise lattice-nucleotide membership, independent of strand/domain renumbering."""
from collections import Counter


def base_key(ref):
    return ref.helix_id, ref.bp_index, ref.direction, ref.copy_k


def occupied_keys(design):
    helices = {h.id: h for h in design.helices}
    loops = {h.id: Counter() for h in design.helices}
    for h in design.helices:
        for ls in h.loop_skips:
            loops[h.id][ls.bp_index] += ls.delta
    for strand in design.strands:
        if strand.is_reference:
            continue
        for domain in strand.domains:
            h = helices.get(domain.helix_id)
            if h is None:
                continue
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            for bp in range(max(lo, h.bp_start), min(hi, h.bp_start + h.length_bp - 1) + 1):
                for copy in range(max(0, 1 + loops[h.id][bp])):
                    yield h.id, bp, domain.direction, copy


def validate_base_members(design, cluster):
    if not cluster.base_ids:
        return
    if cluster.domain_ids:
        raise ValueError('Choose either exact bases or whole domains for a cluster.')
    keys = [base_key(ref) for ref in cluster.base_ids]
    if len(keys) > 30000 or len(keys) != len(set(keys)):
        raise ValueError('Base cluster selection is too large or contains duplicate bases.')
    if set(cluster.helix_ids) != {key[0] for key in keys}:
        raise ValueError('Base cluster helices must match its selected bases.')
    missing = set(keys) - set(occupied_keys(design))
    if missing:
        raise ValueError('A selected cluster base no longer exists. Refresh the selection.')


def array_mask(cluster, helix_id, arrs):
    """Match insertion copies in native array order without changing geometry."""
    import numpy as np
    keys = {base_key(ref) for ref in cluster.base_ids if ref.helix_id == helix_id}
    seen = Counter()
    mask = np.zeros(len(arrs['bp_indices']), dtype=bool)
    from backend.core.models import Direction
    for i, (bp, direction) in enumerate(zip(arrs['bp_indices'], arrs['directions'])):
        direction = Direction.FORWARD if direction == 0 else Direction.REVERSE
        slot = (helix_id, int(bp), direction)
        copy = seen[slot]
        seen[slot] += 1
        mask[i] = (*slot, copy) in keys
    return mask


def claimed_elsewhere(design, cluster):
    """Exact clusters partition ordinary owners; later exact assignments win."""
    exact = [c for c in design.cluster_transforms if c.base_ids]
    if cluster.base_ids:
        index = next((i for i, c in enumerate(exact) if c.id == cluster.id), -1)
        exact = exact[index + 1:]
    return {base_key(r) for c in exact if c.id != cluster.id for r in c.base_ids}


def exclusion_mask(design, cluster, helix_id, arrs):
    from types import SimpleNamespace
    from backend.core.models import ClusterBaseRef
    excluded = claimed_elsewhere(design, cluster)
    return array_mask(SimpleNamespace(base_ids=[ClusterBaseRef(helix_id=h, bp_index=bp,
        direction=d, copy_k=k) for h, bp, d, k in excluded if h == helix_id]), helix_id, arrs)


def inherit_base_placement(design, cluster):
    """Transfer a uniform authored frame without changing any molecular coordinates."""
    import numpy as np
    from scipy.spatial.transform import Rotation
    from backend.core.cluster_member_poses import frame
    frames = [frame(design, ref) for ref in cluster.base_ids]
    first = frames[0]
    if not all(np.allclose(first, value, atol=1e-10, rtol=0) for value in frames[1:]):
        raise ValueError('Selected bases have different existing cluster placements. Group bases in the same placement first.')
    return cluster.model_copy(update={'translation': first[:3, 3].tolist(),
        'rotation': Rotation.from_matrix(first[:3, :3]).as_quat().tolist(), 'pivot': [0., 0., 0.]})
