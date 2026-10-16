"""Join precursor scaffolds by nicking and ligating the previewed attachments."""

import numpy as np

from backend.core.models import ClusterJoinConstraint, JoinAttachment, JoinEndpoint
from backend.core.cluster_join import (
    _connector_clearance,
    _collision_beads,
    _geometry,
    _key,
    join_preview_token,
)
from backend.core.sequences import strand_nucleotide_count, domain_bp_range


def validate_moving(design, moving):
    ids = set(moving.helix_ids)
    for strand in design.strands:
        members = {d.helix_id for d in strand.domains}
        if members & ids and members - ids:
            raise ValueError(
                "Moving cluster has a strand connected outside the cluster."
            )
    if any(
        moving.id in (c.first.cluster_id, c.second.cluster_id)
        for c in design.cluster_join_constraints
    ):
        raise ValueError(
            "This cluster already has saved joins. Undo those joins before moving it independently."
        )
    if any(o.helix_id in ids for o in design.overhangs):
        raise ValueError("Overhang-bearing moving clusters are not supported.")
    local = {
        s.id for s in design.scaffolds() if any(d.helix_id in ids for d in s.domains)
    }
    if any(e.strand_id in local for e in design.extensions):
        raise ValueError("Remove scaffold terminal extensions before joining.")
    if any(moving.id == j.cluster_id for j in design.cluster_joints):
        raise ValueError(
            "The moving cluster already participates in a kinematic joint."
        )


def join_precursors(
    design, result, body, pairs, candidate_count, clearance, rot, translation,
    *, identity_seed=None,
):
    token = join_preview_token(design, body)
    # The preview token still guards live publication. Replay supplies the
    # recorded identity independently of its private document/revision values.
    bridge_identity = identity_seed or token[:14]
    bridges = []
    new_constraints = set()
    for i, (p, q, *_) in enumerate(pairs):

        def attachment(port):
            return JoinAttachment(
                cluster_id=port["cluster_id"],
                source=JoinEndpoint(**port["from"]),
                target=JoinEndpoint(**port["to"]),
            )

        constraint_id = f"join_plan_{bridge_identity}_{i}"
        new_constraints.add(constraint_id)
        bridges.extend(
            {**bridge, "helix_id": f"{constraint_id}_ss_{leg}"}
            for leg, bridge in enumerate(pairs[i][3])
        )
        result.cluster_join_constraints.append(
            ClusterJoinConstraint(
                id=constraint_id,
                first=attachment(p),
                second=attachment(q),
                reach_nm=body.reach_nm,
            )
        )
    connector_clearance = _connector_clearance(bridges, _collision_beads(result))
    result = realize_join_constraints(
        result, constraint_ids=new_constraints, bridges=bridges
    )
    added = sum(b["extra_bases"] for b in bridges)
    from backend.core.cluster_join import _slot_counter

    before_slots, after_slots = _slot_counter(design), _slot_counter(result)
    if any(after_slots[k] != n for k, n in before_slots.items()):
        raise ValueError("Join did not preserve original nucleotide occupancy.")
    delta = np.eye(4)
    delta[:3, :3] = rot
    delta[:3, 3] = translation
    moved = next(c for c in result.cluster_transforms if c.id == body.moving_cluster_id)
    count = sum(
        strand_nucleotide_count(s, design) for s in design.strands if not s.is_reference
    )
    actual_count = sum(
        strand_nucleotide_count(s, result) for s in result.strands if not s.is_reference
    )
    if actual_count != count + added:
        raise ValueError("Join nucleotide accounting failed.")
    return result, dict(
        valid=True,
        errors=[],
        mode="free",
        deferred_routing=False,
        token=token,
        preview_token=token,
        design_id=design.id,
        revision=body.expected_revision,
        donor_world_delta=delta.flatten(order="F").tolist(),
        donor_helix_ids=moved.helix_ids,
        donor_transform=moved.model_dump(mode="json"),
        bridges=bridges,
        connection_count=len(pairs),
        candidate_count=candidate_count,
        connections=[
            dict(
                fixed=p[0]["id"],
                moving=p[1]["id"],
                fixed_cluster_id=p[0]["cluster_id"],
                distance_nm=p[2],
            )
            for p in pairs
        ],
        scaffold_count_before=len(design.scaffolds()),
        scaffold_count_after=len(result.scaffolds()),
        site_count_before=count,
        site_count_after=count + added,
        added_connector_nt=added,
        minimum_backbone_clearance_nm=clearance,
        minimum_connector_clearance_nm=connector_clearance,
        warnings=[
            "Apply creates all previewed scaffold nicks and ligations. Assign scaffold sequences after joining."
        ],
        matching_method="Maximum simultaneous connections with attachment and clearance constraints.",
    )


def endpoint_key(endpoint):
    return endpoint.helix_id, endpoint.bp_index, endpoint.direction.value


def realize_join_constraints(design, *, constraint_ids=None, bridges=None):
    """Splice requested bridges directly into existing scaffold strands.

    Preserve all occupied bases and all requested bonds. A residual cycle is
    nicked at an ordinary native backbone edge, never at a requested join.
    Multiple linear scaffolds may result; we never silently drop a constraint.
    """
    if not design.cluster_join_constraints:
        return design
    from backend.core.cluster_join_free import _bridge
    from backend.core.models import (
        Domain,
        Helix,
        Vec3,
        Direction,
        ForcedLigation,
        FlexibleSegmentMark,
    )
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.topology_integrity import (
        half_slot,
        forced_edge,
        domain_order_errors,
        occupancy_errors,
        junction_errors,
    )
    from backend.core.flexible_segments import derive_flexible_connections
    from backend.core.cluster_join import _unit

    result = design.model_copy(deep=True)
    geo = _geometry(result)
    constraints = [
        c
        for c in result.cluster_join_constraints
        if constraint_ids is None or c.id in constraint_ids
    ]
    realized_ids = {c.id for c in constraints}
    if bridges is None:
        bridges = []
        occupied = _collision_beads(result)
        for constraint in constraints:
            for leg, (p, q) in enumerate(
                (
                    (constraint.first, constraint.second),
                    (constraint.second, constraint.first),
                )
            ):
                a, b = endpoint_key(p.source), endpoint_key(q.target)
                if a not in geo or b not in geo:
                    raise ValueError(
                        "A saved Join attachment is missing after routing; undo the geometry change or the join."
                    )
                # Routing can extend local scaffold ends. Adjust connector contour
                # length, never cluster pose or the saved endpoint assignment.
                for extra in range(65):
                    try:
                        bridge = _bridge(a, b, geo, extra_bases=extra)
                        _connector_clearance([*bridges, bridge], occupied)
                    except ValueError:
                        continue
                    bridge["helix_id"] = f"{constraint.id}_ss_{leg}"
                    bridges.append(bridge)
                    break
                else:
                    raise ValueError(
                        "Routing cannot realize every saved Join with clear connectors; the design and constraints were retained."
                    )
    _connector_clearance(bridges, _collision_beads(result))
    # Per-base graph keeps arbitrary domain metadata and pre-existing nicks.
    nodes, successors, owners = {}, {}, {}
    attachment_keys = {
        tuple(b[side][k] for k in ("helix_id", "bp_index", "direction"))
        for b in bridges
        for side in ("from", "to")
    }
    originals = {
        s.id: s
        for s in result.scaffolds()
        if not s.is_reference
        and any(
            _key(dm, bp) in attachment_keys
            for dm in s.domains
            for bp in domain_bp_range(dm)
        )
    }
    for strand in originals.values():
        previous = None
        for di, dm in enumerate(strand.domains):
            for bp in domain_bp_range(dm):
                key = _key(dm, bp)
                if key in nodes:
                    raise ValueError("Scaffold occupancy is ambiguous at a saved Join.")
                nodes[key] = dm.model_copy(update={"start_bp": bp, "end_bp": bp})
                owners[key] = (strand.id, di)
                successors[key] = None
                if previous is not None:
                    successors[previous] = key
                previous = key
    native_edges = {(a, b) for a, b in successors.items() if b is not None}
    reserved_sources, reserved_targets = set(), set()
    connector_ids = set()
    for bridge in bridges:
        a = tuple(bridge["from"][k] for k in ("helix_id", "bp_index", "direction"))
        b = tuple(bridge["to"][k] for k in ("helix_id", "bp_index", "direction"))
        if (
            a not in nodes
            or b not in nodes
            or a in reserved_sources
            or b in reserved_targets
        ):
            raise ValueError(
                "Saved Join attachments cannot all be realized by this scaffold route."
            )
        reserved_sources.add(a)
        reserved_targets.add(b)
        for source in list(successors):
            if successors[source] == b:
                successors[source] = None
        n, hid = bridge["extra_bases"], bridge["helix_id"]
        connector_ids.add(hid)
        pa, pb = np.asarray(bridge["points"])[[0, -1]]
        axis = _unit(pb - pa)
        result.helices.append(
            Helix(
                id=hid,
                axis_start=Vec3.from_array(pa + axis * BDNA_RISE_PER_BP),
                axis_end=Vec3.from_array(pa + axis * BDNA_RISE_PER_BP * n),
                length_bp=n,
                label="Join ssDNA connector",
            )
        )
        previous = a
        for bp in range(n):
            key = (hid, bp, "FORWARD")
            nodes[key] = Domain(
                helix_id=hid, start_bp=bp, end_bp=bp, direction=Direction.FORWARD
            )
            owners[key] = (hid, 0)
            successors[previous] = key
            previous = key
        successors[previous] = b
        for i, (source, target) in enumerate(
            ((a, (hid, 0, "FORWARD")), ((hid, n - 1, "FORWARD"), b))
        ):
            result.forced_ligations.append(
                ForcedLigation(
                    id=f"{hid}_bond_{i}",
                    three_prime_helix_id=source[0],
                    three_prime_bp=source[1],
                    three_prime_direction=source[2],
                    five_prime_helix_id=target[0],
                    five_prime_bp=target[1],
                    five_prime_direction=target[2],
                )
            )
    visited, paths = set(), []

    def walk(root):
        path = []
        while root is not None and root not in visited:
            visited.add(root)
            path.append(root)
            root = successors[root]
        paths.append(path)

    targets = {b for b in successors.values() if b is not None}
    for root in sorted(nodes.keys() - targets):
        walk(root)
    while len(visited) < len(nodes):
        root = next(k for k in nodes if k not in visited)
        cycle, node = [], root
        while node not in cycle:
            cycle.append(node)
            node = successors[node]
        cut = next(
            (
                a
                for a in cycle
                if (a, successors[a]) in native_edges and a[0] == successors[a][0]
            ),
            None,
        )
        if cut is None:
            raise ValueError(
                "Saved joins form a cycle with no native backbone available for a scaffold nick."
            )
        root = successors[cut]
        successors[cut] = None
        walk(root)
    live_edges = {(a, b) for a, b in successors.items() if b is not None}
    removed = {frozenset(edge) for edge in native_edges - live_edges}
    result.crossovers = [
        x
        for x in result.crossovers
        if frozenset((half_slot(x.half_a), half_slot(x.half_b))) not in removed
    ]
    result.forced_ligations = [
        x for x in result.forced_ligations if frozenset(forced_edge(x)) not in removed
    ]
    routed, used_ids, locations = [], set(), {}
    reserved_ids = {s.id for s in result.strands}
    for index, path in enumerate(paths):
        original_id = next(owners[k][0] for k in path if owners[k][0] in originals)
        strand = originals[original_id].model_copy(deep=True)
        strand.id = (
            original_id
            if original_id not in used_ids
            else f"{original_id}_joined_{index}"
        )
        if original_id in used_ids:
            while strand.id in reserved_ids:
                strand.id += "_next"
        used_ids.add(strand.id)
        reserved_ids.add(strand.id)
        strand.sequence = None
        strand.custom_scaffold_length = None
        strand.routing_seed = []
        domains, last_owner = [], None
        for key in path:
            dm = nodes[key]
            if (
                domains
                and owners[key] == last_owner
                and domains[-1].helix_id == dm.helix_id
                and abs(domains[-1].end_bp - dm.start_bp) == 1
            ):
                domains[-1].end_bp = dm.end_bp
            else:
                domains.append(dm.model_copy(deep=True))
            last_owner = owners[key]
            locations[key] = (strand.id, len(domains) - 1)
        strand.domains = domains
        routed.append(strand)
    for mark in result.flexible_segment_marks:
        if mark.strand_id in originals:
            dm = originals[mark.strand_id].domains[mark.domain_index]
            mark.strand_id, mark.domain_index = locations[_key(dm, mark.bp_index)]
    for key, (sid, di) in locations.items():
        if key[0] in connector_ids:
            result.flexible_segment_marks.append(
                FlexibleSegmentMark(
                    id=f"{key[0]}_{key[1]}",
                    strand_id=sid,
                    domain_index=di,
                    bp_index=key[1],
                    direction=key[2],
                )
            )
    result.strands = [s for s in result.strands if s.id not in originals] + routed
    result.cluster_join_constraints = [
        c for c in result.cluster_join_constraints if c.id not in realized_ids
    ]
    result.flexible_connections = derive_flexible_connections(result)
    errors = (
        domain_order_errors(result) + occupancy_errors(result) + junction_errors(result)
    )
    if errors:
        raise ValueError("Saved Join routing failed: " + "; ".join(errors[:3]))
    return result
