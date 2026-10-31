"""Explicit root-length exemptions; never infer strain intent or invent joints.

Ownership is resolved at the host nucleotide, not the relocated duplex. Two
independently owned arms remain independent even under a common parent. In the
current model a joint moves its whole cluster, and flexible connections join
existing clusters; neither cuts a rigid cluster into new arms automatically.
"""

from collections import defaultdict

from backend.core.flexible_segments import _owning_cluster_id


def host_root_owner(design, overhang_id):
    """Return the rigid owner of a unique terminal overhang's host anchor."""
    matches = [(s, i) for s in design.strands for i, d in enumerate(s.domains)
               if d.overhang_id == overhang_id]
    if len(matches) != 1:
        return None
    strand, index = matches[0]
    if len(strand.domains) < 2 or index not in (0, len(strand.domains) - 1):
        return None
    parent_index = 1 if index == 0 else index - 1
    parent = strand.domains[parent_index]
    bp = parent.start_bp if index == 0 else parent.end_bp
    # A marked anchor is not a fixed point of the rigid body.
    if any(m.strand_id == strand.id and m.domain_index == parent_index
           and m.bp_index == bp for m in design.flexible_segment_marks):
        return None
    return _owning_cluster_id(design, (parent.helix_id, bp, parent.direction),
                              (strand.id, parent_index))


def root_length_exemptions(design, overhang_ids):
    """Groups with ≥2 host roots fixed to the same existing rigid body.

Joint motion of that common body moves both roots together. Relative joint or
flexible-connection motion requires distinct arm owners, which are never merged
here. Unowned, rootless and ambiguous domains never receive an exemption.
"""
    groups = defaultdict(list)
    for oid in dict.fromkeys(overhang_ids):
        owner = host_root_owner(design, oid)
        if owner is not None:
            groups[owner].append(oid)
    clusters = {c.id: c for c in design.cluster_transforms}
    specs = {o.id: o for o in design.overhangs}
    result = []
    for cid, ids in groups.items():
        if len(ids) < 2:
            continue
        labels = ", ".join((specs[oid].label or oid) if oid in specs else oid for oid in ids)
        name = clusters[cid].name or cid
        result.append({"code": "same_rigid_cluster", "cluster_id": cid, "overhang_ids": ids,
            "message": f"Root-length preservation exemption ({labels}): both host roots are fixed "
            f"to cluster {name}, with no relative joint or flexible connection between them. "
            "Existing strain is retained. NADOC does not infer whether it is intentional."})
    return result


def direct_connection_exemptions(design):
    """Nonblocking notices for applied Direct connections; derived, never saved."""
    pairs = [([b.overhang_a_id, b.overhang_b_id], b.id)
             for b in design.overhang_bindings if b.bound]
    pairs += [([d.left.overhang_id, d.right.overhang_id], d.id)
              for d in design.duplexes if d.bound]
    seen, result = set(), []
    for ids, connection_id in pairs:
        key = frozenset(ids)
        if key in seen:
            continue
        seen.add(key)
        result.extend({**notice, "connection_id": connection_id}
                      for notice in root_length_exemptions(design, ids))
    return result
