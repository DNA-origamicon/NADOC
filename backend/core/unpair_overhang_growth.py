"""Keep an exposed staple run's identity when a later Move/Rotate extends it."""
from backend.core.models import DomainRef


def merge_adjacent(design, original_ids):
    from backend.core.deformation import _cluster_moving_segment_keys
    import numpy as np
    from scipy.spatial.transform import Rotation
    owners = [(c, _cluster_moving_segment_keys(c, design)) for c in design.cluster_transforms
              if not (np.allclose(Rotation.from_quat(c.rotation).as_matrix(), np.eye(3), rtol=0, atol=1e-10)
                      and np.allclose(c.translation, 0, rtol=0, atol=1e-10))]
    specs = {o.id: o for o in design.overhangs}
    remap, domain_map, removed, strands = {}, {}, set(), []
    for strand in design.strands:
        domains = []
        for index, domain in enumerate(strand.domains):
            spec = specs.get(domain.overhang_id)
            previous = domains[-1] if domains else None
            prior = specs.get(previous.overhang_id) if previous else None
            contiguous = (previous is not None and previous.direction == domain.direction
                          and domain.start_bp - previous.end_bp == (1 if domain.direction.value == 'FORWARD' else -1))
            same_source = (spec and prior and spec.unpaired_source_helix_id
                           and spec.unpaired_source_helix_id == prior.unpaired_source_helix_id)
            if not contiguous or not same_source:
                domain_map[strand.id, index] = len(domains)
                domains.append(domain)
                continue
            if any(((strand.id, index - 1) in keys) != ((strand.id, index) in keys) for _, keys in owners):
                raise ValueError('Cannot merge independently moved overhang segments')
            # Only untouched, automatically classified runs can be combined.
            for item in (prior, spec):
                if (item.rotation != [0, 0, 0, 1] or item.translation != [0, 0, 0]
                        or item.sequence is not None or len(item.sub_domains) != 1
                        or item.sub_domains[0].rotation_theta_deg or item.sub_domains[0].rotation_phi_deg
                        or item.sub_domains[0].sequence_override or item.strand_anim_setup):
                    raise ValueError('Cannot extend an overhang with independently authored controls')
            keep, drop = (prior, spec) if prior.id in original_ids or spec.id not in original_ids else (spec, prior)
            remap[drop.helix_id] = keep.helix_id
            removed.add(drop.id)
            length = abs(domain.end_bp - previous.start_bp) + 1
            specs[keep.id] = keep.model_copy(update={'sub_domains': [keep.sub_domains[0].model_copy(update={'length_bp': length})]})
            domains[-1] = previous.model_copy(update={'end_bp': domain.end_bp,
                'helix_id': keep.helix_id, 'overhang_id': keep.id})
            domain_map[strand.id, index] = len(domains) - 1
        strands.append(strand.model_copy(update={'domains': domains}))
    if not removed:
        return design
    def mapped(hid):
        while hid in remap:
            hid = remap[hid]
        return hid
    clusters = []
    for cluster in design.cluster_transforms:
        refs = list(dict.fromkeys((r.strand_id, domain_map[r.strand_id, r.domain_index]) for r in cluster.domain_ids))
        clusters.append(cluster.model_copy(update={
            'helix_ids': list(dict.fromkeys(mapped(h) for h in cluster.helix_ids)),
            'domain_ids': [DomainRef(strand_id=s, domain_index=i) for s, i in refs]}))
    return design.copy_with(strands=strands,
        helices=[h for h in design.helices if h.id not in remap],
        overhangs=[specs[o.id] for o in design.overhangs if o.id not in removed],
        cluster_transforms=clusters,
        nucleotide_transforms=[p.model_copy(update={'helix_id': mapped(p.helix_id)})
                              if p.kind == 'base' else p for p in design.nucleotide_transforms])
