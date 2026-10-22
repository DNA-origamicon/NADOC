"""Topology-only overhang reclassification after an authored residue move.

Dedicated overhang helices carry independent cadnano cells and retain their
evaluated rest axes/phase. No displayed coordinates are baked into topology.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.deformation import effective_helix_for_geometry
from backend.core.feature_identity import identity_factory
from backend.core.lattice import _linker_grid_pos, _lattice_direction
from backend.core.models import OverhangSpec, SubDomain, DomainRef, StrandType
from backend.core.sequences import domain_bp_range


def separated_staple_keys(design, posed, targets):
    """Identify ordinary scaffold/staple pairs with different authored poses.

    Compare rigid affine maps, not physical distance or simulation coordinates.
    A common move of both partners keeps the duplex paired.
    """
    occupancy = {}
    independently_posed = set()
    for owner in design.cluster_transforms:
        if not owner.domain_ids:
            continue
        rotation = Rotation.from_quat(owner.rotation).as_matrix()
        pivot = np.asarray(owner.pivot)
        offset = pivot - rotation @ pivot + np.asarray(owner.translation)
        if not (np.allclose(rotation, np.eye(3), rtol=0, atol=1e-10)
                and np.allclose(offset, 0, rtol=0, atol=1e-10)):
            independently_posed.update(owner.helix_ids)
    loop_skips = {(h.id, ls.bp_index): ls.delta for h in design.helices for ls in h.loop_skips}
    for strand in design.strands:
        if strand.is_reference:
            continue
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                for copy in range(max(0, 1 + loop_skips.get((domain.helix_id, bp), 0))):
                    key = (domain.helix_id, bp, domain.direction.value, copy)
                    if key in occupancy:
                        raise ValueError("Ambiguous occupied nucleotide slot")
                    occupancy[key] = strand.strand_type
    poses = {}
    for pose in posed.nucleotide_transforms:
        if pose.kind != "base":
            continue
        rotation = Rotation.from_quat(pose.rotation).as_matrix()
        pivot = np.asarray(pose.pivot)
        matrix = np.eye(4)
        matrix[:3, :3] = rotation
        matrix[:3, 3] = pivot - rotation @ pivot + np.asarray(pose.translation)
        poses[pose.helix_id, pose.bp_index, pose.direction.value, pose.copy_k] = matrix
    separated = set()
    for key in map(tuple, targets):
        if key not in occupancy:
            continue
        hid, bp, direction, copy = key
        other = (hid, bp, "REVERSE" if direction == "FORWARD" else "FORWARD", copy)
        if other not in occupancy:
            continue
        if hid in independently_posed:
            raise ValueError("Unpairing independently posed domain owners is not yet supported")
        if np.allclose(poses.get(key, np.eye(4)), poses.get(other, np.eye(4)), rtol=0, atol=1e-10):
            continue
        if {occupancy[key], occupancy[other]} != {StrandType.SCAFFOLD, StrandType.STAPLE}:
            raise ValueError("Separating this pair requires a scaffold and a staple")
        separated.add(key if occupancy[key] == StrandType.STAPLE else other)
    return sorted(separated)


def relocate_segments(design, selected_keys, *, identity_seed):
    """Relocate explicitly nominated staple sites, preserving native rest pose.

    The caller supplies staple keys after resolving the scaffold/staple rule.
    Refuse consumers whose identity remapping is not yet supported.
    """
    selected = set(map(tuple, selected_keys))
    if not selected:
        return design
    if any((design.deformations, design.crossovers, design.forced_ligations,
            design.extensions, design.duplexes, design.overhang_bindings,
            design.overhang_connections, design.annotations, design.dimensions,
            design.flexible_segment_marks, design.photoproduct_junctions,
            design.protein_attachments, design.nanoparticle_conjugations,
            design.crossover_constraints, design.cluster_join_constraints,
            design.group_organization and design.group_organization.groups)):
        raise ValueError("Unpairing with deformations, crossovers, extensions or linked consumers is not yet supported")
    identifier = identity_factory(identity_seed)
    helices = list(design.helices)
    overhangs = list(design.overhangs)
    by_id = {h.id: h for h in helices}
    remap = {}
    domain_map = {}
    strands = []
    resolved = set()
    for strand in design.strands:
        domains = []
        for di, domain in enumerate(strand.domains):
            indices = list(domain_bp_range(domain))
            keys = [(domain.helix_id, bp, domain.direction.value, 0) for bp in indices]
            hit = [key in selected for key in keys]
            if not any(hit):
                domain_map[strand.id, di] = [len(domains)]
                domains.append(domain)
                continue
            if strand.strand_type != StrandType.STAPLE or strand.is_reference:
                raise ValueError("Only ordinary staple segments may relocate")
            if (domain.overhang_id or domain.binds_overhang_id or by_id[domain.helix_id].loop_skips
                    or by_id[domain.helix_id].native_residues):
                raise ValueError("Unpairing decorated or loop/skip domains is not yet supported")
            new_indices = []
            offset = 0
            while offset < len(indices):
                start = offset
                moving = hit[offset]
                while offset < len(indices) and hit[offset] == moving:
                    offset += 1
                updates = {"start_bp": indices[start], "end_bp": indices[offset - 1]}
                if moving:
                    members = [strand.id, str(di), str(indices[start]), str(indices[offset - 1])]
                    hid = identifier("unpair-helix", members)
                    oid = identifier("unpair-overhang", members)
                    if hid in by_id or any(o.id == oid for o in overhangs):
                        raise ValueError("Unpair output identity already exists")
                    # Same mechanism as linker rows: cadnano cell is independent
                    # of the stored axis and phase on a dedicated overhang helix.
                    source = effective_helix_for_geometry(by_id[domain.helix_id], design)
                    layout_design = design.model_copy(update={"helices": helices})
                    row, col = _linker_grid_pos(layout_design)
                    if source.direction and _lattice_direction(row, col, design.lattice_type) != source.direction:
                        row += 1
                    helix = source.model_copy(update={
                        "id": hid, "grid_pos": (row, col),
                        "lattice_frame_id": None,
                    })
                    helices.append(helix)
                    by_id[hid] = helix
                    overhangs.append(OverhangSpec(id=oid, helix_id=hid, strand_id=strand.id,
                        sub_domains=[SubDomain(id=identifier("unpair-subdomain", members),
                            name="a", start_bp_offset=0, length_bp=offset-start)]))
                    updates.update(helix_id=hid, overhang_id=oid)
                    for key in keys[start:offset]:
                        resolved.add(key)
                        remap[key] = (hid, *key[1:])
                new_indices.append(len(domains))
                domains.append(domain.model_copy(update=updates))
            domain_map[strand.id, di] = new_indices
        strands.append(strand.model_copy(update={"domains": domains}))
    if resolved != selected:
        raise ValueError("Unresolved staple nucleotide selection")

    # A completely detached staple is free ssDNA, not an anchored overhang.
    # Auxiliary endpoints already represent free ssDNA in the existing model;
    # they preserve the dedicated helix pose without advertising a free tip.
    existing_overhangs = {o.id for o in design.overhangs}
    changed_strands = {o.strand_id for o in overhangs if o.id not in existing_overhangs}
    skipped = {(h.id, ls.bp_index) for h in helices for ls in h.loop_skips if ls.delta == -1}
    occupied = {(d.helix_id, bp, d.direction.value) for s in strands for d in s.domains
                for bp in domain_bp_range(d) if (d.helix_id, bp) not in skipped}
    free_strands = {s.id for s in strands if s.id in changed_strands and not any(
        (d.helix_id, bp, "REVERSE" if d.direction.value == "FORWARD" else "FORWARD") in occupied
        for d in s.domains for bp in domain_bp_range(d)
        if (d.helix_id, bp) not in skipped)}
    overhangs = [o.model_copy(update={"auxiliary_endpoint": True, "label": o.label or "Free ssDNA"})
                if o.strand_id in free_strands else o
                for o in overhangs]

    clusters = []
    new_strands = {s.id: s for s in strands}
    for cluster in design.cluster_transforms:
        if cluster.domain_ids:
            refs = [DomainRef(strand_id=ref.strand_id, domain_index=i)
                    for ref in cluster.domain_ids for i in domain_map[ref.strand_id, ref.domain_index]]
            ids = {new_strands[ref.strand_id].domains[i].helix_id
                   for ref in cluster.domain_ids
                   if design.find_strand(ref.strand_id).domains[ref.domain_index].helix_id in cluster.helix_ids
                   for i in domain_map[ref.strand_id, ref.domain_index]}
            # Keep domain ownership exact; do not add opposite-strand membership.
            old_domain_helices = {design.find_strand(r.strand_id).domains[r.domain_index].helix_id
                                  for r in cluster.domain_ids}
            exclusive = [hid for hid in cluster.helix_ids if hid not in old_domain_helices]
            clusters.append(cluster.model_copy(update={"domain_ids": refs,
                "helix_ids": list(dict.fromkeys([*exclusive, *sorted(ids)]))}))
        else:
            born = sorted({new[0] for old, new in remap.items() if old[0] in cluster.helix_ids})
            clusters.append(cluster.model_copy(update={"helix_ids": [*cluster.helix_ids, *born]}))
    transforms = []
    for pose in design.nucleotide_transforms:
        key = (pose.helix_id, pose.bp_index, pose.direction.value if pose.direction else None, pose.copy_k)
        transforms.append(pose.model_copy(update={"helix_id": remap[key][0]})
                          if pose.kind == "base" and key in remap else pose)
    return design.copy_with(helices=helices, strands=strands, overhangs=overhangs,
                            cluster_transforms=clusters, nucleotide_transforms=transforms)
