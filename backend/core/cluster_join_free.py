"""Pose-preserving discovery and atomic multi-port scaffold attachment.

Exact matching maximizes compatible connections across nearby fixed clusters.
Unrouted attachments splice precursor strands; routed joins retain linear paths.
"""

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.cluster_join import (
    _geometry,
    _collision_beads,
    _connector_clearance,
    _scope_reason,
    _ports,
    _key,
    _site,
    _unit,
    _slot_counter,
    _validate_moving_cluster,
    join_preview_token,
)
from backend.core.constants import SSDNA_RISE_PER_BASE_NM, BDNA_RISE_PER_BP
from backend.core.models import (
    Direction,
    Domain,
    Helix,
    Vec3,
    ForcedLigation,
    FlexibleSegmentMark,
)
from backend.core.flexible_segments import derive_flexible_connections
from backend.core.sequences import domain_bp_range, strand_nucleotide_count
from backend.core.topology_integrity import (
    domain_order_errors,
    occupancy_errors,
    junction_errors,
    half_slot,
    forced_edge,
)


class FreeClusterJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["free"] = "free"
    moving_cluster_id: str
    fixed_cluster_id: str | None = None
    world_translation: tuple[float, float, float] = (0, 0, 0)
    world_rotation: tuple[float, float, float, float] = (0, 0, 0, 1)
    reach_nm: float = Field(default=3, ge=0.3, le=10)
    expected_design_id: str
    expected_revision: int = Field(ge=0)
    preview_token: str | None = None

    @field_validator("world_rotation")
    @classmethod
    def unit_quaternion(cls, value):
        if abs(np.linalg.norm(value) - 1) > 1e-5:
            raise ValueError("Rotation must be a unit quaternion.")
        return value


def _endpoint(port, side):
    return tuple(port[side][k] for k in ("helix_id", "bp_index", "direction"))


def _bridge(start, end, geo, *, extra_bases=0):
    from backend.physics.oxdna_interface import _flexible_arc_points, _perp_bow

    pa, pb = geo[start][0], geo[end][0]
    span = float(np.linalg.norm(pb - pa))
    n = max(3, math.ceil(span * 1.15 / SSDNA_RISE_PER_BASE_NM)) + extra_bases
    if n > 64:
        raise ValueError("Connector exceeds 64 nucleotides.")
    points = [
        pa,
        *_flexible_arc_points(
            pa, pb, n * SSDNA_RISE_PER_BASE_NM, n, _perp_bow(pb - pa)
        ),
        pb,
    ]
    return {
        "from": _site(start),
        "to": _site(end),
        "points": [v.tolist() for v in points],
        "span_nm": span,
        "extra_bases": n,
    }


def propose_free_cluster_join(design, body, *, selected_ports=None):
    if isinstance(body, dict):
        body = FreeClusterJoinRequest.model_validate(body)
    if design.id != body.expected_design_id:
        raise ValueError("Active design changed.")
    clusters = {c.id: c for c in design.cluster_transforms}
    moving = clusters.get(body.moving_cluster_id)
    if moving is None:
        raise ValueError("Select a moving cluster.")
    reason = _scope_reason(design, moving)
    if reason:
        raise ValueError(reason)
    if body.fixed_cluster_id == moving.id:
        raise ValueError("Fixed and moving clusters must differ.")
    if body.fixed_cluster_id and body.fixed_cluster_id not in clusters:
        raise ValueError("Fixed cluster no longer exists.")
    ids = set(moving.helix_ids)
    donor = [s for s in design.scaffolds() if any(d.helix_id in ids for d in s.domains)]
    from backend.core.cluster_join_constraints import validate_moving, join_precursors
    from backend.core.cluster_join_matching import JoinRoutes, maximum_connections

    validate_moving(design, moving)
    moving_unrouted = any(s.routing_seed for s in donor)
    donor = donor[0] if len(donor) == 1 else None
    native_geo = _geometry(design)
    moving_ports = (
        [selected_ports[1]]
        if selected_ports
        else _ports(design, moving, native_geo, dense=True)
    )
    rot = Rotation.from_quat(body.world_rotation).as_matrix()
    translation = np.asarray(body.world_translation)
    result = design.model_copy(deep=True)
    moved = next(c for c in result.cluster_transforms if c.id == moving.id)
    pivot = np.asarray(moving.pivot)
    moved.rotation = (
        Rotation.from_matrix(rot @ Rotation.from_quat(moving.rotation).as_matrix())
        .as_quat()
        .tolist()
    )
    moved.translation = (
        rot @ (pivot + np.asarray(moving.translation)) + translation - pivot
    ).tolist()
    geo = {**native_geo, **_geometry(result, ids)}
    beads = _collision_beads(result)
    fixed_pts = [v for key, v in beads if key[0] not in ids]
    moved_pts = [v for key, v in beads if key[0] in ids]
    clearance = (
        float(cKDTree(fixed_pts).query(moved_pts)[0].min())
        if fixed_pts and moved_pts
        else None
    )
    if clearance is not None and clearance < 0.65:
        raise ValueError(
            f"Placement clashes with existing DNA ({clearance:.2f} nm). Move the cluster farther away."
        )
    existing_bridges = []
    from backend.core.cluster_join_constraints import endpoint_key

    for constraint in design.cluster_join_constraints:
        for p, q in (
            (constraint.first, constraint.second),
            (constraint.second, constraint.first),
        ):
            a, b = endpoint_key(p.source), endpoint_key(q.target)
            if a not in geo or b not in geo:
                raise ValueError(
                    "A saved Join attachment was deleted; undo that edit before adding joins."
                )
            existing_bridges.append(_bridge(a, b, geo))
    hosts = {}
    for c in design.cluster_transforms:
        if (
            c.id == moving.id
            or (body.fixed_cluster_id and c.id != body.fixed_cluster_id)
            or _scope_reason(design, c)
        ):
            continue
        for p in (
            [selected_ports[0]]
            if selected_ports
            else _ports(design, c, native_geo, dense=True)
        ):
            if donor is None or p["strand_id"] != donor.id:
                hosts.setdefault(p["strand_id"], []).append(p)
    candidates = []
    host_strands = []
    for sid, ports in sorted(hosts.items()):
        host = next(s for s in design.strands if s.id == sid)
        if any(e.strand_id == sid for e in design.extensions):
            continue
        tree = cKDTree([p["position"] for p in ports])
        host_strands.append(host)
        for q in moving_ports:
            center = rot @ q["position"] + translation
            normal = rot @ q["normal"]
            for index in sorted(tree.query_ball_point(center, body.reach_nm)):
                p = ports[index]
                separation = center - p["position"]
                distance = float(np.linalg.norm(separation))
                if distance < 0.3 or np.dot(p["normal"], normal) > -0.25:
                    continue
                direction = separation / distance
                if (
                    np.dot(direction, p["normal"]) < 0.15
                    or np.dot(direction, normal) > -0.15
                ):
                    continue
                bridges = [
                    _bridge(_endpoint(p, "from"), _endpoint(q, "to"), geo),
                    _bridge(_endpoint(q, "from"), _endpoint(p, "to"), geo),
                ]
                try:
                    _connector_clearance([*existing_bridges, *bridges], beads)
                except ValueError:
                    continue
                candidates.append((p, q, distance, bridges))
    candidates.sort(key=lambda pair: (pair[2], pair[0]["id"], pair[1]["id"]))
    involved = {pair[0]["cluster_id"] for pair in candidates}
    deferred = moving_unrouted or any(
        s.routing_seed
        for c in design.cluster_transforms
        if c.id in involved
        for s in design.scaffolds()
        if any(d.helix_id in set(c.helix_ids) for d in s.domains)
    )
    if not deferred:
        if donor is None:
            raise ValueError("The moving cluster needs exactly one routed scaffold.")
        _validate_moving_cluster(design, donor, donor, moving)
    routes = None if deferred else JoinRoutes(host_strands, donor, candidates)
    indices, paths = maximum_connections(candidates, routes)
    pairs = [candidates[i] for i in indices]
    candidate_count = len(candidates)
    if not pairs:
        raise ValueError(
            "No compatible connections within reach. Translate or rotate the cluster, or increase connection reach."
        )
    if deferred:
        return join_precursors(
            design, result, body, pairs, candidate_count, clearance, rot, translation
        )
    # Route placeholders refer to the complete candidate array.
    selected_index = {original: selected for selected, original in enumerate(indices)}
    paths = {
        sid: [(selected_index[x[0]], x[1]) if isinstance(x, tuple) else x for x in path]
        for sid, path in paths.items()
    }
    token = join_preview_token(design, body)
    bridges, connector_domains = [], {}
    for i, pair in enumerate(pairs):
        for j, bridge in enumerate(pair[3]):
            hid = f"join_ss_{token[:14]}_{2 * i + j}"
            bridge = {**bridge, "helix_id": hid}
            bridges.append(bridge)
            pa, pb = np.array(bridge["points"])[[0, -1]]
            axis, n = _unit(pb - pa), bridge["extra_bases"]
            result.helices.append(
                Helix(
                    id=hid,
                    axis_start=Vec3.from_array(pa + axis * BDNA_RISE_PER_BP),
                    axis_end=Vec3.from_array(pa + axis * BDNA_RISE_PER_BP * n),
                    length_bp=n,
                    label="Join ssDNA connector",
                )
            )
            dm = Domain(
                helix_id=hid, start_bp=0, end_bp=n - 1, direction=Direction.FORWARD
            )
            connector_domains[i, j] = dm
            for k, (a, b) in enumerate(
                (
                    (_endpoint(bridge, "from"), _key(dm, 0)),
                    (_key(dm, n - 1), _endpoint(bridge, "to")),
                )
            ):
                result.forced_ligations.append(
                    ForcedLigation(
                        id=f"join_bond_{token[:14]}_{2 * i + j}_{k}",
                        three_prime_helix_id=a[0],
                        three_prime_bp=a[1],
                        three_prime_direction=a[2],
                        five_prime_helix_id=b[0],
                        five_prime_bp=b[1],
                        five_prime_direction=b[2],
                    )
                )
    merged_strands = [s for s in result.strands if s.id in paths]
    for merged in merged_strands:
        merged.domains = [
            connector_domains[x] if isinstance(x, tuple) else x
            for x in paths[merged.id]
        ]
        merged.sequence = None
        merged.custom_scaffold_length = None
        merged.routing_seed = []
    result.strands = [s for s in result.strands if s.id != donor.id]
    removed = {
        frozenset((_endpoint(p, "from"), _endpoint(p, "to")))
        for pair in pairs
        for p in pair[:2]
    }
    result.crossovers = [
        x
        for x in result.crossovers
        if frozenset((half_slot(x.half_a), half_slot(x.half_b))) not in removed
    ]
    result.forced_ligations = [
        x for x in result.forced_ligations if frozenset(forced_edge(x)) not in removed
    ]
    locations = {
        _key(dm, bp): (s.id, di)
        for s in merged_strands
        for di, dm in enumerate(s.domains)
        for bp in domain_bp_range(dm)
    }
    originals = {s.id: s for s in [*host_strands, donor]}
    for mark in result.flexible_segment_marks:
        if mark.strand_id in originals:
            dm = originals[mark.strand_id].domains[mark.domain_index]
            mark.strand_id, mark.domain_index = locations[_key(dm, mark.bp_index)]
    connector_ids = {dm.helix_id for dm in connector_domains.values()}
    for merged in merged_strands:
        for di, dm in enumerate(merged.domains):
            if dm.helix_id in connector_ids:
                result.flexible_segment_marks.extend(
                    FlexibleSegmentMark(
                        id=f"{dm.helix_id}_{bp}",
                        strand_id=merged.id,
                        domain_index=di,
                        bp_index=bp,
                        direction=dm.direction,
                    )
                    for bp in domain_bp_range(dm)
                )
    result.flexible_connections = derive_flexible_connections(result)
    errors = (
        domain_order_errors(result) + occupancy_errors(result) + junction_errors(result)
    )
    if errors:
        raise ValueError("Join topology validation failed: " + "; ".join(errors[:3]))
    before_slots, after_slots = _slot_counter(design), _slot_counter(result)
    if any(after_slots[k] != n for k, n in before_slots.items()):
        raise ValueError("Join did not preserve original nucleotide occupancy.")
    before_nt = sum(
        strand_nucleotide_count(s, design) for s in design.strands if not s.is_reference
    )
    after_nt = sum(
        strand_nucleotide_count(s, result) for s in result.strands if not s.is_reference
    )
    added = sum(b["extra_bases"] for b in bridges)
    if (
        after_nt - before_nt != added
        or len(result.scaffolds()) != len(design.scaffolds()) - 1
    ):
        raise ValueError("Join scaffold or nucleotide accounting failed.")
    connector_clearance = _connector_clearance(bridges, beads)
    delta = np.eye(4)
    delta[:3, :3] = rot
    delta[:3, 3] = translation
    return result, dict(
        valid=True,
        errors=[],
        mode="free",
        token=token,
        preview_token=token,
        design_id=design.id,
        revision=body.expected_revision,
        donor_world_delta=delta.flatten(order="F").tolist(),
        donor_helix_ids=sorted(ids),
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
        site_count_before=before_nt,
        site_count_after=after_nt,
        added_connector_nt=added,
        minimum_backbone_clearance_nm=clearance,
        minimum_connector_clearance_nm=connector_clearance,
        warnings=[
            "Connections preserve one linear scaffold; conflicting ports and detached cycles are excluded.",
            "Assign a matching scaffold sequence and verify staple complementarity before folding.",
        ],
        matching_method="Maximum simultaneous connections with attachment, clearance and routing constraints.",
    )
