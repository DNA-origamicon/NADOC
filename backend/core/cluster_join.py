"""Directed scaffold splicing between explicitly selected rigid clusters.

The selected host edge and donor edge are replaced by two real ssDNA runs.
A donor's existing adjacent nick is closed while the host nick is retained.
Rigid placement is an authored pose, not a claim of mechanical rigidity.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

import numpy as np
from pydantic import BaseModel, Field, ConfigDict
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.constants import SSDNA_RISE_PER_BASE_NM, BDNA_RISE_PER_BP
from backend.core.design_geometry import (
    native_full_arrays_for_helix,
    _geometry_for_design,
)
from backend.core.flexible_segments import derive_flexible_connections
from backend.core.models import (
    Design,
    Direction,
    Domain,
    FlexibleSegmentMark,
    ForcedLigation,
    Helix,
    Vec3,
)
from backend.core.sequences import domain_bp_range, strand_nucleotide_count
from backend.core.topology_integrity import (
    domain_order_errors,
    occupancy_errors,
    junction_errors,
    half_slot,
    forced_edge,
)


class JoinSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cluster_id: str
    port_id: str


class ClusterJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    first: JoinSelection
    second: JoinSelection
    gap_nm: float = Field(default=0.8, ge=0.3, le=10)
    roll_deg: float = Field(default=0, ge=-180, le=180)
    tilt_deg: float = Field(default=0, ge=-60, le=60)
    expected_design_id: str
    expected_revision: int = Field(ge=0)
    preview_token: str | None = None


def _key(d, bp):
    return (d.helix_id, int(bp), d.direction.value)


def _site(k):
    return dict(helix_id=k[0], bp_index=int(k[1]), direction=k[2])


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n < 1e-9:
        raise ValueError("Attachment frame is degenerate; choose another site.")
    return v / n


def _geometry(design, ids=None):
    out = {}
    for h in design.helices:
        if ids is not None and h.id not in ids:
            continue
        a = native_full_arrays_for_helix(h, design)
        for i, bp in enumerate(a["bp_indices"]):
            k = (h.id, int(bp), "REVERSE" if a["directions"][i] else "FORWARD")
            if k in out:
                continue
            out[k] = (
                np.asarray(a["positions"][i]),
                np.asarray(a["axis_points"][i]),
                np.asarray(a["axis_tangents"][i]),
            )
    return out


def _collision_beads(design):
    """Occupied posed bases, including loop copies and per-residue overrides.

    Flexible domains use their native fixed-contour display arc rather than the
    placeholder construction helix, which would be a false collision obstacle.
    """
    from backend.physics.oxdna_interface import (
        flexible_segment_geo_keys,
        _flexible_arc_points,
        _perp_bow,
    )

    records = [
        n for n in _geometry_for_design(design) if not n.get("is_reference", False)
    ]
    positions = {
        (n["helix_id"], n["bp_index"], n["direction"]): np.asarray(
            n["backbone_position"]
        )
        for n in records
    }
    replacements = {}
    for a, b, beads, contour in flexible_segment_geo_keys(design):
        if a in positions and b in positions:
            pa, pb = positions[a], positions[b]
            replacements.update(
                zip(
                    beads,
                    _flexible_arc_points(
                        pa, pb, contour, len(beads), _perp_bow(pb - pa)
                    ),
                )
            )
    return [
        (
            (n["helix_id"], n["bp_index"], n["direction"], int(n.get("copy_k", 0))),
            replacements.get(
                (n["helix_id"], n["bp_index"], n["direction"]),
                np.asarray(n["backbone_position"]),
            ),
        )
        for n in records
    ]


def _connector_clearance(bridges, occupied_beads):
    """Reject hard overlaps of the proposed native ssDNA arc particles.

    The 0.30 nm cutoff is a coarse backbone seed guard, not an all-atom steric
    calculation. Direct covalent neighbors are excluded; other existing bases,
    both connector legs and nonadjacent beads on one leg are compared.
    """
    tree = cKDTree([position for _, position in occupied_beads])
    minimum = float("inf")
    particles = []
    for leg, bridge in enumerate(bridges):
        interior = np.asarray(bridge["points"][1:-1])
        start = tuple(
            bridge["from"][key] for key in ("helix_id", "bp_index", "direction")
        ) + (0,)
        end = tuple(
            bridge["to"][key] for key in ("helix_id", "bp_index", "direction")
        ) + (0,)
        for i, point in enumerate(interior):
            bonded = start if i == 0 else end if i == len(interior) - 1 else None
            distances, indices = tree.query(point, k=min(2, len(occupied_beads)))
            for distance, index in zip(
                np.atleast_1d(distances), np.atleast_1d(indices)
            ):
                if occupied_beads[int(index)][0] != bonded:
                    minimum = min(minimum, float(distance))
            particles.append((leg, i, point))
    for j, (leg, index, point) in enumerate(particles):
        for other_leg, other_index, other_point in particles[j + 1 :]:
            if leg == other_leg and abs(index - other_index) == 1:
                continue
            minimum = min(minimum, float(np.linalg.norm(point - other_point)))
    if minimum < 0.30:
        raise ValueError(
            f"Connector placement clashes with DNA ({minimum:.2f} nm); increase the gap, change roll or choose another site."
        )
    return minimum


def _scope_reason(design, cluster):
    ids = set(cluster.helix_ids)
    if cluster.id in design.visibility_state.hidden_cluster_ids:
        return "Show the cluster before selecting a Join attachment."
    if cluster.domain_ids or not ids:
        return "Join needs a whole-helix cluster; domain-only or empty clusters are unsupported."
    if cluster.parent_cluster_id or any(
        c.parent_cluster_id == cluster.id for c in design.cluster_transforms
    ):
        return "Flatten the cluster hierarchy before joining this cluster."
    if cluster.overhang_duplex_driver_id:
        return "Overhang-driven clusters cannot be joined directly."
    strands_by_id = {s.id: s for s in design.strands}
    for other in design.cluster_transforms:
        if other.id == cluster.id:
            continue
        for ref in other.domain_ids:
            strand = strands_by_id.get(ref.strand_id)
            if (
                strand
                and ref.domain_index < len(strand.domains)
                and strand.domains[ref.domain_index].helix_id in ids
            ):
                return "Resolve overlapping domain-cluster membership before joining."
    if any(
        ids & set(c.helix_ids) for c in design.cluster_transforms if c.id != cluster.id
    ):
        return "Resolve overlapping cluster membership before joining."
    helices = {h.id: h for h in design.helices}
    if not ids <= helices.keys():
        return "Cluster contains a deleted helix."
    if any(helices[h].native_residues for h in ids):
        return "Imported residue geometry is not supported by Join."
    xo_ids = {
        x.id
        for x in design.crossovers
        if x.half_a.helix_id in ids or x.half_b.helix_id in ids
    }
    if any(
        t.helix_id in ids or t.crossover_id in xo_ids
        for t in design.nucleotide_transforms
    ):
        return "Remove individual nucleotide poses before joining this cluster."
    if any(
        s.is_reference and any(d.helix_id in ids for d in s.domains)
        for s in design.strands
    ):
        return "Reference geometry cannot be moved or routed by Join."
    return None


def _ports(design, cluster, geo, *, dense=False):
    ids = set(cluster.helix_ids)
    helices = {h.id: h for h in design.helices}
    records = {
        frozenset((half_slot(x.half_a), half_slot(x.half_b))): x
        for x in design.crossovers
    }
    records.update({frozenset(forced_edge(x)): x for x in design.forced_ligations})
    axis_traces = {
        hid: np.asarray(
            [v[1] for k, v in geo.items() if k[0] == hid and k[2] == "FORWARD"]
        )
        for hid in ids
    }
    hidden = set(design.visibility_state.hidden_base_keys)
    ports = []
    for strand in design.scaffolds():
        if strand.is_reference or not strand.domains:
            continue

        def add(a, b, kind, di, bp):
            record = records.get(frozenset((a, b)))
            if record is not None and record.extra_bases:
                return
            if a not in geo or b not in geo or a[0] not in ids or b[0] not in ids:
                return
            if any(f"{k[0]}:{k[1]}:{k[2]}" in hidden for k in (a, b)):
                return
            if any(
                abs(ls.bp_index - k[1]) <= 2
                for k in (a, b)
                for ls in helices[k[0]].loop_skips
            ):
                return
            pa, axa, ta = geo[a]
            pb, axb, tb = geo[b]
            axis = _unit(ta)
            if kind == "side":
                radial = (pa + pb) / 2 - (axa + axb) / 2
                radial -= np.dot(radial, axis) * axis
                if np.linalg.norm(radial) < 0.1:
                    return
                normal = _unit(radial)
                # A supporting half-plane excludes inward-facing and buried sides.
                for hid, trace in axis_traces.items():
                    if hid == a[0] or not len(trace):
                        continue
                    # A local cross-section is essential on bent/swept bundles;
                    # a whole-helix centroid can classify their outer face inward.
                    other = trace[np.argmin(np.sum((trace - axa) ** 2, axis=1))]
                    v = other - axa
                    v -= np.dot(v, axis) * axis
                    if np.dot(v, normal) > 0.25:
                        return
            else:
                sign = (
                    1
                    if a[1]
                    >= (helices[a[0]].bp_start + (helices[a[0]].length_bp - 1) / 2)
                    else -1
                )
                normal = axis * sign
            digest = hashlib.sha256(
                json.dumps([cluster.id, strand.id, a, b]).encode()
            ).hexdigest()[:20]
            ports.append(
                dict(
                    id="join-port-" + digest,
                    cluster_id=cluster.id,
                    strand_id=strand.id,
                    kind=kind,
                    position=((pa + pb) / 2).tolist(),
                    normal=normal.tolist(),
                    axis=axis.tolist(),
                    **{"from": _site(a), "to": _site(b)},
                    _domain_index=di,
                    _bp=bp,
                )
            )

        for di, dm in enumerate(strand.domains):
            if dm.helix_id not in ids or dm.overhang_id or dm.binds_overhang_id:
                continue
            bps = list(domain_bp_range(dm))
            # Every helical phase may contain an outward-facing candidate. Keep
            # one per roughly one DNA turn for a readable native picker.
            last = -100
            for j in range(3, len(bps) - 4):
                if not dense and j - last < 7:
                    continue
                count = len(ports)
                add(_key(dm, bps[j]), _key(dm, bps[j + 1]), "side", di, bps[j])
                if len(ports) > count:
                    last = j
            if di + 1 < len(strand.domains):
                nxt = strand.domains[di + 1]
                a, b = _key(dm, dm.end_bp), _key(nxt, nxt.start_bp)
                rec = records.get(frozenset((a, b)))
                if (
                    dm.helix_id != nxt.helix_id
                    and dm.direction != nxt.direction
                    and rec is not None
                    and not rec.extra_bases
                ):
                    # End ports are actual blunt turns, not internal crossovers.
                    if all(
                        min(
                            abs(k[1] - helices[k[0]].bp_start),
                            abs(
                                k[1]
                                - (helices[k[0]].bp_start + helices[k[0]].length_bp - 1)
                            ),
                        )
                        <= 3
                        for k in (a, b)
                        if k[0] in helices
                    ):
                        add(a, b, "end", di, dm.end_bp)
        if strand.routing_seed:
            dm = strand.domains[-1]
            a = _key(dm, dm.end_bp)
            for other in design.scaffolds():
                if not other.routing_seed or other.id == strand.id:
                    continue
                nxt = other.domains[0]
                b = _key(nxt, nxt.start_bp)
                if a in geo and b in geo and b[0] in ids and dm.direction != nxt.direction:
                    # Potential blunt turns between adjacent precursor helices.
                    if abs(a[1] - b[1]) <= 3 and np.linalg.norm(geo[a][1] - geo[b][1]) <= 3.5:
                        add(a, b, "end", len(strand.domains)-1, dm.end_bp)
    reserved = set()
    for constraint in design.cluster_join_constraints:
        for port in (constraint.first, constraint.second):
            reserved.add((port.source.helix_id, port.source.bp_index, port.source.direction.value, "out"))
            reserved.add((port.target.helix_id, port.target.bp_index, port.target.direction.value, "in"))
    return [p for p in ports if not any(tuple(p[side][k] for k in ("helix_id", "bp_index", "direction")) + (role,) in reserved
            for side, role in (("from", "out"), ("to", "in")))]


def cluster_join_candidates(design: Design, cluster_id: str | None = None):
    clusters = []
    sites = []
    for c in design.cluster_transforms:
        if cluster_id is not None and c.id != cluster_id:
            continue
        reason = _scope_reason(design, c)
        ports = [] if reason else _ports(design, c, _geometry(design, set(c.helix_ids)))
        if not reason and not ports:
            reason = (
                "No available exposed scaffold attachment sites."
            )
        public = [{k: v for k, v in p.items() if not k.startswith("_")} for p in ports]
        clusters.append(
            dict(
                cluster_id=c.id,
                name=c.name,
                eligible=not bool(reason),
                reason=reason,
                helix_ids=list(c.helix_ids),
                ports=public,
            )
        )
        sites.extend(public)
    return dict(design_id=design.id, clusters=clusters, sites=sites)


def _split(strand, port):
    di, bp = port["_domain_index"], port["_bp"]
    dm = strand.domains[di]
    left = [d.model_copy(deep=True) for d in strand.domains[:di]]
    right = [d.model_copy(deep=True) for d in strand.domains[di + 1 :]]
    left.append(dm.model_copy(update={"end_bp": bp}))
    if bp != dm.end_bp:
        step = 1 if dm.direction == Direction.FORWARD else -1
        right.insert(0, dm.model_copy(update={"start_bp": bp + step}))
    return left, right


def _frame(normal, tangent):
    n = _unit(normal)
    t = np.asarray(tangent) - np.dot(tangent, n) * n
    if np.linalg.norm(t) < 1e-8:
        t = np.cross(n, [0, 0, 1] if abs(n[2]) < 0.9 else [0, 1, 0])
    t = _unit(t)
    return np.column_stack((t, np.cross(n, t), n))


def _slot_counter(design):
    result = Counter()
    for s in design.strands:
        if s.is_reference:
            continue
        for d in s.domains:
            for bp in domain_bp_range(d):
                result[_key(d, bp)] += 1
    return result


def join_preview_token(design, body):
    payload = body.model_dump(mode="json", exclude={"preview_token"})
    # Hash all authored content: revision alone is insufficient across documents.
    return hashlib.sha256(
        (design.model_dump_json() + json.dumps(payload, sort_keys=True)).encode()
    ).hexdigest()


def _validate_moving_cluster(design, host, donor, second):
    donor_ids = set(second.helix_ids)
    for x in [
        *(forced_edge(f) for f in design.forced_ligations),
        *((half_slot(x.half_a), half_slot(x.half_b)) for x in design.crossovers),
    ]:
        if (x[0][0] in donor_ids) != (x[1][0] in donor_ids):
            raise ValueError(
                "The moving cluster has an external routing connection; keep that assembly fixed."
            )
    if any(j.cluster_id == second.id for j in design.cluster_joints):
        raise ValueError(
            "The moving cluster has an existing joint; keep that assembly fixed."
        )
    local = [
        s
        for s in design.strands
        if not s.is_reference and any(d.helix_id in donor_ids for d in s.domains)
    ]
    if any(any(d.helix_id not in donor_ids for d in s.domains) for s in local):
        raise ValueError(
            "The moving cluster is already connected outside its scope; select that assembly as the fixed cluster."
        )
    local_ids = {s.id for s in local}
    moving_overhangs = {
        o.id
        for o in design.overhangs
        if o.helix_id in donor_ids or o.strand_id in local_ids
    }
    if any(o.helix_id in donor_ids for o in design.overhangs):
        raise ValueError(
            "Overhang-bearing moving clusters are not supported; join their rigid core before adding overhangs."
        )
    if any(
        getattr(p.target, "overhang_id", None) in moving_overhangs
        for p in design.protein_attachments
    ):
        raise ValueError(
            "The moving cluster has a protein attachment; keep that assembly fixed."
        )
    if len([s for s in local if s.is_scaffold]) != 1:
        raise ValueError("The moving cluster needs exactly one routed scaffold.")
    if any(e.strand_id in (host.id, donor.id) for e in design.extensions):
        raise ValueError(
            "Scaffold terminal extensions must be removed before this join."
        )
    dfirst, dlast = donor.domains[0], donor.domains[-1]
    step = 1 if dlast.direction == Direction.FORWARD else -1
    if not (
        dfirst.helix_id == dlast.helix_id
        and dfirst.direction == dlast.direction
        and dfirst.start_bp == dlast.end_bp + step
    ):
        raise ValueError(
            "The moving scaffold nick is not adjacent; route a closable scaffold before joining."
        )
    nick = frozenset((_key(dlast, dlast.end_bp), _key(dfirst, dfirst.start_bp)))
    if any(
        frozenset(forced_edge(link)) == nick and link.extra_bases
        for link in design.forced_ligations
    ):
        raise ValueError(
            "The moving scaffold nick carries extra bases; resolve that annotation before joining."
        )
    for k in (_key(dfirst, dfirst.start_bp), _key(dlast, dlast.end_bp)):
        h = next(h for h in design.helices if h.id == k[0])
        if any(ls.bp_index == k[1] for ls in h.loop_skips):
            raise ValueError("The donor nick includes a loop or deleted base.")
    return dfirst, dlast


def propose_cluster_join(design: Design, body: ClusterJoinRequest | dict, *, identity_seed=None):
    if isinstance(body, dict):
        body = ClusterJoinRequest.model_validate(body)
    if body.expected_design_id != design.id:
        raise ValueError("Active design changed.")
    if body.first.cluster_id == body.second.cluster_id:
        raise ValueError("Choose two different clusters.")
    clusters = {c.id: c for c in design.cluster_transforms}
    try:
        first, second = (
            clusters[body.first.cluster_id],
            clusters[body.second.cluster_id],
        )
    except KeyError as exc:
        raise ValueError("Selected cluster no longer exists.") from exc
    for c in (first, second):
        reason = _scope_reason(design, c)
        if reason:
            raise ValueError(reason)
    donor_ids = set(second.helix_ids)
    if donor_ids & set(first.helix_ids):
        raise ValueError("Selected clusters overlap.")
    geo = _geometry(design)
    chosen = []
    for c, selection in ((first, body.first), (second, body.second)):
        port = next(
            (p for p in _ports(design, c, geo) if p["id"] == selection.port_id), None
        )
        if port is None:
            raise ValueError(
                "Attachment site is stale or unavailable; select a new exposed site."
            )
        chosen.append(port)
    p, q = chosen
    strands = {s.id: s for s in design.strands}
    host, donor = strands[p["strand_id"]], strands[q["strand_id"]]
    if host.id == donor.id:
        raise ValueError(
            "These clusters already share a scaffold; this join would split its route."
        )
    deferred = any(s.routing_seed for s in design.scaffolds() if any(d.helix_id in set(first.helix_ids + second.helix_ids) for d in s.domains))
    if not deferred:
        dfirst, dlast = _validate_moving_cluster(design, host, donor, second)
    a = tuple(p["from"][k] for k in ("helix_id", "bp_index", "direction"))
    b = tuple(p["to"][k] for k in ("helix_id", "bp_index", "direction"))
    c = tuple(q["from"][k] for k in ("helix_id", "bp_index", "direction"))
    d = tuple(q["to"][k] for k in ("helix_id", "bp_index", "direction"))
    # Match the donor normal to the host outward normal's opposite. The in-plane
    # endpoint vector establishes an unambiguous roll, without reversing DNA.
    fa = _frame(p["normal"], geo[b][0] - geo[a][0])
    fb = _frame(q["normal"], geo[c][0] - geo[d][0])
    target = (
        fa
        @ Rotation.from_euler(
            "xz", [body.tilt_deg, body.roll_deg], degrees=True
        ).as_matrix()
        @ np.diag([1, -1, -1])
    )
    rot = target @ fb.T
    fixed_center = np.asarray(p["position"])
    moving_center = np.asarray(q["position"])
    translation = (
        fixed_center + np.asarray(p["normal"]) * body.gap_nm - rot @ moving_center
    )
    if deferred:
        from backend.core.cluster_join_free import FreeClusterJoinRequest, propose_free_cluster_join
        free_body = FreeClusterJoinRequest(moving_cluster_id=second.id, fixed_cluster_id=first.id,
            world_translation=translation.tolist(), world_rotation=Rotation.from_matrix(rot).as_quat().tolist(),
            reach_nm=10, expected_design_id=body.expected_design_id, expected_revision=body.expected_revision)
        result, report = propose_free_cluster_join(design, free_body, selected_ports=(p, q), identity_seed=identity_seed)
        report.update(token=join_preview_token(design, body), preview_token=join_preview_token(design, body), mode="manual")
        return result, report
    result = design.model_copy(deep=True)
    moved = next(x for x in result.cluster_transforms if x.id == second.id)
    oldrot = Rotation.from_quat(second.rotation).as_matrix()
    pivot = np.asarray(second.pivot)
    moved.rotation = Rotation.from_matrix(rot @ oldrot).as_quat().tolist()
    moved.translation = (
        rot @ (pivot + np.asarray(second.translation)) + translation - pivot
    ).tolist()
    posed = _geometry(result, donor_ids)
    # Native occupied backbone coordinates, never lattice-space assumptions.
    collision_beads = _collision_beads(result)
    fixed_pts = np.asarray([v for key, v in collision_beads if key[0] not in donor_ids])
    moving_pts = np.asarray([v for key, v in collision_beads if key[0] in donor_ids])
    if len(fixed_pts) and len(moving_pts):
        distance = float(cKDTree(fixed_pts).query(moving_pts, k=1)[0].min())
        if distance < 0.65:
            raise ValueError(
                f"Placement clashes with existing DNA ({distance:.2f} nm); increase the gap or choose another site."
            )
    else:
        distance = None
    geo.update(posed)
    left, right = _split(host, p)
    pre, post = _split(donor, q)
    rotated = post + pre
    # Rejoin the native buried nick without creating a spurious junction record.
    for i in range(len(rotated) - 1, 0, -1):
        x, y = rotated[i - 1 : i + 1]
        st = 1 if x.direction == Direction.FORWARD else -1
        if (
            x.helix_id == y.helix_id
            and x.direction == y.direction
            and y.start_bp == x.end_bp + st
            and x.overhang_id == y.overhang_id
            and x.binds_overhang_id == y.binds_overhang_id
        ):
            rotated[i - 1 : i + 1] = [x.model_copy(update={"end_bp": y.end_bp})]
    token = join_preview_token(design, body)
    bridge_identity = identity_seed or token[:14]
    bridges = []
    linkdomains = []
    addedids = []
    from backend.physics.oxdna_interface import _flexible_arc_points, _perp_bow

    for j, (start, end) in enumerate(((a, d), (c, b))):
        pa, pb = geo[start][0], geo[end][0]
        span = float(np.linalg.norm(pb - pa))
        n = max(3, math.ceil(span * 1.15 / SSDNA_RISE_PER_BASE_NM))
        if n > 64:
            raise ValueError(
                "Connector exceeds 64 nucleotides; choose a closer attachment."
            )
        hid = f"join_ss_{bridge_identity}_{j}"
        addedids.append(hid)
        # The native flexible resolver uses these real particles and seats them
        # on its contour-length arc between the already posed attachment bases.
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
        dm = Domain(helix_id=hid, start_bp=0, end_bp=n - 1, direction=Direction.FORWARD)
        linkdomains.append(dm)
        for k, (u, v) in enumerate(((start, _key(dm, 0)), (_key(dm, n - 1), end))):
            result.forced_ligations.append(
                ForcedLigation(
                    id=f"join_bond_{bridge_identity}_{j}_{k}",
                    three_prime_helix_id=u[0],
                    three_prime_bp=u[1],
                    three_prime_direction=u[2],
                    five_prime_helix_id=v[0],
                    five_prime_bp=v[1],
                    five_prime_direction=v[2],
                )
            )
        points = [
            pa,
            *_flexible_arc_points(
                pa, pb, n * SSDNA_RISE_PER_BASE_NM, n, _perp_bow(pb - pa)
            ),
            pb,
        ]
        bridges.append(
            {
                "from": _site(start),
                "to": _site(end),
                "points": [x.tolist() for x in points],
                "span_nm": span,
                "extra_bases": n,
                "helix_id": hid,
            }
        )
    connector_clearance = _connector_clearance(bridges, collision_beads)
    removed = {frozenset((a, b)), frozenset((c, d))}
    result.crossovers = [
        x
        for x in result.crossovers
        if frozenset((half_slot(x.half_a), half_slot(x.half_b))) not in removed
    ]
    result.forced_ligations = [
        x for x in result.forced_ligations if frozenset(forced_edge(x)) not in removed
    ]
    merged = next(s for s in result.strands if s.id == host.id)
    merged.domains = left + [linkdomains[0]] + rotated + [linkdomains[1]] + right
    merged.sequence = None
    merged.custom_scaffold_length = None
    merged.routing_seed = []
    result.strands = [s for s in result.strands if s.id != donor.id]
    # Existing flexible segments are anchored by their original physical sites;
    # remap their strand/domain references after both splits and donor rerooting.
    locations = {
        _key(dm, bp): (merged.id, di)
        for di, dm in enumerate(merged.domains)
        for bp in domain_bp_range(dm)
    }
    for mark in result.flexible_segment_marks:
        if mark.strand_id in (host.id, donor.id):
            dm = strands[mark.strand_id].domains[mark.domain_index]
            sid, di = locations[_key(dm, mark.bp_index)]
            mark.strand_id = sid
            mark.domain_index = di
    for di, dm in enumerate(merged.domains):
        if dm.helix_id in addedids:
            for bp in domain_bp_range(dm):
                result.flexible_segment_marks.append(
                    FlexibleSegmentMark(
                        id=f"{dm.helix_id}_{bp}",
                        strand_id=merged.id,
                        domain_index=di,
                        bp_index=bp,
                        direction=dm.direction,
                    )
                )
    result.flexible_connections = derive_flexible_connections(result)
    errors = (
        domain_order_errors(result) + occupancy_errors(result) + junction_errors(result)
    )
    if errors:
        raise ValueError("Join topology validation failed: " + "; ".join(errors[:3]))
    before_slots = _slot_counter(design)
    after_slots = _slot_counter(result)
    if any(after_slots[k] != v for k, v in before_slots.items()):
        raise ValueError("Join did not preserve original nucleotide occupancy.")
    before_nt = sum(
        strand_nucleotide_count(s, design) for s in design.strands if not s.is_reference
    )
    after_nt = sum(
        strand_nucleotide_count(s, result) for s in result.strands if not s.is_reference
    )
    added = sum(x["extra_bases"] for x in bridges)
    if after_nt - before_nt != added:
        raise ValueError("Connector nucleotide accounting failed.")
    if len(result.scaffolds()) != len(design.scaffolds()) - 1:
        raise ValueError("Join must merge exactly two scaffold routes.")
    delta = np.eye(4)
    delta[:3, :3] = rot
    delta[:3, 3] = translation
    report = dict(
        valid=True,
        errors=[],
        warnings=[
            "One flexible connection pair does not impose a mechanically rigid angle.",
            "Join clears the merged scaffold sequence/source; assign a matching scaffold and verify staple complementarity before folding.",
        ],
        token=token,
        preview_token=token,
        design_id=design.id,
        revision=body.expected_revision,
        donor_world_delta=delta.flatten(order="F").tolist(),
        donor_transform={"cluster_id": moved.id, **moved.model_dump(mode="json")},
        donor_helix_ids=sorted(donor_ids),
        bridges=bridges,
        removed_edges=[
            {"from": _site(a), "to": _site(b)},
            {"from": _site(c), "to": _site(d)},
        ],
        scaffold_count_before=len(design.scaffolds()),
        scaffold_count_after=len(result.scaffolds()),
        site_count_before=before_nt,
        site_count_after=after_nt,
        added_connector_nt=added,
        preserved_original_nt=before_nt,
        minimum_backbone_clearance_nm=distance,
        minimum_connector_clearance_nm=connector_clearance,
        clearance_scope="Native backbone beads: 0.65 nm rigid placement and 0.30 nm nonbonded connector hard-overlap cutoffs; not all-atom steric validation.",
        closed_donor_nick={
            "from": _site(_key(dlast, dlast.end_bp)),
            "to": _site(_key(dfirst, dfirst.start_bp)),
        },
    )
    return result, report
