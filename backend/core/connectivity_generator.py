"""Compile a reviewed bundle tree to shared-lattice scaffolded origami.

Geometry is quantized at base-pair stations. Daughter sections copy their
parent's frames in the shared interval so crossovers remain real lattice links.
"""

import math
import numpy as np
from scipy.spatial.transform import Rotation, Slerp
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

from backend.core.models import LatticeType, DeformationOp, CrossoverConstraint
from backend.core.sweep_model import SweepParams
from backend.core.lattice import honeycomb_position
from backend.core.sweep_path import rotation_between

RISE = 0.34


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(max_length=120)
    kind: Literal["particle", "split"]
    position: tuple[float, float, float]
    particleId: str | None = None


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(max_length=120)
    source: str
    target: str
    controlPoints: list[tuple[float, float, float]] = Field(min_length=4, max_length=4)


class ConnectivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    nodes: list[Node] = Field(min_length=2, max_length=14)
    edges: list[Edge] = Field(min_length=1, max_length=13)
    uniform_hb: Literal[6, 12, 18, 24] = 6


def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n < 1e-8:
        raise ValueError("The connectivity path has a zero-length direction.")
    return v / n


def frame(z, x):
    z = unit(z)
    x = np.asarray(x) - z * np.dot(x, z)
    if np.linalg.norm(x) < 1e-8:
        x = np.eye(3)[np.argmin(abs(z))]
        x = x - z * np.dot(x, z)
    x = unit(x)
    return np.column_stack([x, np.cross(z, x), z])


def segment(a, b, ra, rb, straight_bp=0):
    """A curved approach followed by an exactly straight crossover interval."""
    end = np.asarray(b)
    pre = end - rb[:, 2] * straight_bp * RISE
    chord = np.linalg.norm(pre - a)
    if chord < 1:
        raise ValueError("Not enough room for a shared junction and curved approach.")
    handle = min(chord / 3, 12.0)
    cps = np.array([a, a + ra[:, 2] * handle, pre - rb[:, 2] * handle, pre])
    t = np.linspace(0, 1, 257)
    s = 1 - t
    points = (
        s[:, None] ** 3 * cps[0]
        + 3 * s[:, None] ** 2 * t[:, None] * cps[1]
        + 3 * s[:, None] * t[:, None] ** 2 * cps[2]
        + t[:, None] ** 3 * cps[3]
    )
    tangent = (
        3 * s[:, None] ** 2 * (cps[1] - cps[0])
        + 6 * s[:, None] * t[:, None] * (cps[2] - cps[1])
        + 3 * t[:, None] ** 2 * (cps[3] - cps[2])
    )
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    steps = max(7, math.ceil(arc[-1] / RISE / 7) * 7)
    matrices = [ra]
    for i in range(1, len(points)):
        matrices.append(rotation_between(tangent[i - 1], tangent[i]) @ matrices[-1])
    matrices = np.array(matrices)
    goal = rb[:, 0]
    last = matrices[-1, :, 0]
    twist = np.arctan2(rb[:, 2] @ np.cross(last, goal), last @ goal)
    matrices = (
        Rotation.from_rotvec(tangent * (twist * arc / arc[-1])[:, None]).as_matrix()
        @ matrices
    )
    samples = np.linspace(0, arc[-1], steps + 1)
    p = np.column_stack([np.interp(samples, arc, points[:, k]) for k in range(3)])
    r = Slerp(arc, Rotation.from_matrix(matrices))(samples).as_matrix()
    p[0] = a
    p[-1] = pre
    r[0] = ra
    r[-1] = rb
    for i in range(1, straight_bp + 1):
        p = np.vstack([p, pre + rb[:, 2] * i * RISE])
        r = np.concatenate([r, rb[None]])
    return p, r


def compile_connectivity(
    source, request, duplex_bp=18, junction_retreat_nm=0, junction_bp=42
):
    if source.lattice_type != LatticeType.HONEYCOMB:
        raise ValueError(
            "Connectivity generation currently requires a honeycomb lattice."
        )
    nodes = {n.id: n for n in request.nodes}
    edges = {e.id: e for e in request.edges}
    if (
        len(nodes) != len(request.nodes)
        or len(edges) != len(request.edges)
        or len(edges) != len(nodes) - 1
    ):
        raise ValueError("Connectivity must be one tree with unique node and edge IDs.")
    particles = {p.id: p for p in source.nanoparticles if p.kind == "gold_nanosphere"}
    leaves = [n for n in nodes.values() if n.kind == "particle"]
    if len(leaves) != len(particles) or {n.particleId for n in leaves} != set(
        particles
    ):
        raise ValueError(
            "Connectivity must include every gold nanoparticle exactly once."
        )
    for n in leaves:
        if not np.allclose(
            n.position,
            particles[n.particleId].pose.to_array()[:3, 3],
            atol=1e-6,
            rtol=0,
        ):
            raise ValueError("Particle positions changed. Recalculate Connectivity.")
    adjacency = {i: [] for i in nodes}
    for e in edges.values():
        if e.source not in nodes or e.target not in nodes or e.source == e.target:
            raise ValueError("Connectivity contains an invalid edge.")
        adjacency[e.source].append(e)
        adjacency[e.target].append(e)
    if any(
        len(adjacency[n.id]) != (1 if n.kind == "particle" else 3)
        for n in nodes.values()
    ):
        raise ValueError(
            "Only binary shared-section splits and terminal nanoparticles are supported."
        )
    root = leaves[0].id
    # Preserve the preview's rooted stem when its first node is a particle.
    if request.nodes[0].kind == "particle":
        root = request.nodes[0].id
    parent = {root: None}
    children = {}
    cps = {}
    order = [root]
    for nid in order:
        children[nid] = []
        for e in adjacency[nid]:
            other = e.target if e.source == nid else e.source
            if other == parent[nid]:
                continue
            if other in parent:
                raise ValueError("Connectivity has a cycle.")
            parent[other] = nid
            order.append(other)
            children[nid].append(other)
            cps[other] = np.array(
                e.controlPoints if e.source == nid else e.controlPoints[::-1]
            )
    if len(order) != len(nodes):
        raise ValueError("Connectivity is disconnected.")
    # Give terminal duplexes room: retreat split stations toward the root while
    # retaining the reviewed topology. End tangents then point at their particles.
    if junction_retreat_nm:
        direction = unit(
            np.asarray(nodes[root].position)
            - np.mean([n.position for n in leaves if n.id != root], axis=0)
        )
        nodes = {
            i: n.model_copy(
                update={
                    "position": tuple(
                        np.asarray(n.position) + direction * junction_retreat_nm
                    )
                }
            )
            if n.kind == "split"
            else n
            for i, n in nodes.items()
        }
    shapes = {6: (2, 3), 12: (4, 3), 18: (6, 3), 24: (6, 4)}
    rows, cols = shapes[request.uniform_hb]
    faces = [[(r, c + 1) for r in range(rows) for c in range(cols)]]
    owners = {root: 0}
    branch_parent = {}
    node_newgroup = {}
    used = set(faces[0])
    for nid in order:
        cs = children[nid]
        if len(cs) == 2:
            # Continue through the straighter arm, rather than turn the entire stem.
            incoming = unit(cps[nid][3] - cps[nid][2])
            cs.sort(
                key=lambda c: (
                    -float(
                        incoming
                        @ unit(np.asarray(nodes[c].position) - nodes[nid].position)
                    )
                )
            )
            g = owners[nid]
            new = None
            for dc, dr in [
                (cols, cols % 2),
                (-cols, -cols % 2),
                (cols, -(cols % 2)),
                (-cols, cols % 2),
            ]:
                trial = [(r + dr, c + dc) for r, c in faces[g]]
                if not used.intersection(trial):
                    new = trial
                    break
            if new is None:
                raise ValueError(
                    "No adjacent unoccupied lattice face is available for this branch."
                )
            gid = len(faces)
            faces.append(new)
            used.update(new)
            node_newgroup[nid] = gid
            branch_parent[gid] = g
            owners[cs[0]] = g
            owners[cs[1]] = gid
        elif cs:
            owners[cs[0]] = owners[nid]
    centroids = [np.mean([honeycomb_position(*c) for c in f], axis=0) for f in faces]
    frames = {}
    positions = {}
    diffs = {}
    for nid in order:
        n = nodes[nid]
        if nid == root:
            z = unit(cps[children[nid][0]][1] - cps[children[nid][0]][0])
            frames[nid] = frame(z, [0, 1, 0])
            positions[nid] = np.array(n.position) + z * (
                particles[n.particleId].diameter_nm / 2 + duplex_bp * RISE + 2
            )
        elif children[nid]:
            z = unit(np.asarray(n.position) - nodes[parent[nid]].position)
            delta = centroids[node_newgroup[nid]] - centroids[owners[nid]]
            lateral = (
                np.asarray(nodes[children[nid][1]].position)
                - nodes[children[nid][0]].position
            )
            frames[nid] = frame(z, lateral * np.sign(delta[0]))
            diffs[nid] = frames[nid] @ np.r_[delta, 0]
            positions[nid] = np.array(n.position) - diffs[nid] / 2
        else:
            z = unit(np.asarray(n.position) - nodes[parent[nid]].position)
            frames[nid] = frame(z, frames[parent[nid]][:, 0])
            positions[nid] = np.array(n.position) - z * (
                particles[n.particleId].diameter_nm / 2 + duplex_bp * RISE + 2
            )
    # Grow groups in root-to-leaf order. The new daughter copies the parent's
    # complete shared interval before departing, including the exact frames.
    groups = {0: dict(start=0, p=[positions[root]], r=[frames[root]])}
    stations = {root: 0}
    junctions = []
    terminal = []
    terminal.append(dict(particle_id=nodes[root].particleId, group=0, end="low"))
    for nid in order[1:]:
        prev = parent[nid]
        gid = owners[nid]
        if gid not in groups:
            pg = groups[owners[prev]]
            count = junction_bp
            delta = np.r_[centroids[gid] - centroids[owners[prev]], 0]
            groups[gid] = dict(
                start=stations[prev] - count,
                p=[
                    p + r @ delta
                    for p, r in zip(pg["p"][-count - 1 :], pg["r"][-count - 1 :])
                ],
                r=list(pg["r"][-count - 1 :]),
            )
            junctions.append(
                dict(
                    parent=owners[prev],
                    child=gid,
                    interval=[stations[prev] - count, stations[prev] - 1],
                )
            )
        group = groups[gid]
        a = (
            positions[prev] + (diffs[prev] if gid != owners[prev] else 0)
            if prev in diffs
            else positions[prev]
        )
        p, r = segment(
            a,
            positions[nid],
            frames[prev],
            frames[nid],
            junction_bp if children[nid] else 0,
        )
        group["p"].extend(p[1:])
        group["r"].extend(r[1:])
        stations[nid] = group["start"] + len(group["p"]) - 1
        if not children[nid]:
            terminal.append(
                dict(particle_id=nodes[nid].particleId, group=gid, end="high")
            )
    # A parent's path may already have continued when its child is visited.
    # Re-copy by station rather than relying on traversal order's final tail.
    for j in junctions:
        child = groups[j["child"]]
        pg = groups[j["parent"]]
        lo, hi = j["interval"]
        delta = np.r_[centroids[j["child"]] - centroids[j["parent"]], 0]
        for bp in range(lo, hi + 2):
            at = bp - pg["start"]
            ci = bp - child["start"]
            child["p"][ci] = pg["p"][at] + pg["r"][at] @ delta
            child["r"][ci] = pg["r"][at]
    tracks = []
    sections = []
    paths = []
    for gid, f in enumerate(faces):
        g = groups[gid]
        lo = g["start"]
        hi = lo + len(g["p"]) - 1
        if lo < 0 or hi > 2015:
            raise ValueError(
                "The connectivity layout exceeds the supported base-pair span."
            )
        section = [dict(cell=list(c), interval=[lo, hi]) for c in f]
        sections.append(section)
        tracks.extend(dict(cell=list(c), intervals=[[lo, hi]]) for c in f)
        paths.append(
            dict(
                start=lo,
                positions=np.asarray(g["p"]).tolist(),
                frames=np.asarray(g["r"]).reshape(-1, 9).tolist(),
            )
        )
    return dict(
        shape="branched",
        branch_geometry="connectivity",
        cells=[list(c) for f in faces for c in f],
        nominal_length_bp=max(p["start"] + len(p["positions"]) for p in paths),
        branch_tracks=tracks,
        branch_trunk=sections[0],
        branch_windows=sections[1:],
        branch_junction_intervals=[
            j["interval"] for j in sorted(junctions, key=lambda j: j["child"])
        ],
        connectivity_faces=faces,
        connectivity_paths=paths,
        connectivity_junctions=junctions,
        connectivity_terminals=terminal,
        uniform_hb=request.uniform_hb,
        junction_retreat_nm=junction_retreat_nm,
        section=f"{request.uniform_hb}HB arms/stems · {2 * request.uniform_hb}HB shared junctions",
        length_nm=sum(
            np.linalg.norm(np.diff(p["positions"], axis=0), axis=1).sum() for p in paths
        ),
        center_local=[0, 0, 0],
        base_frame=np.eye(3).tolist(),
    )


def apply_connectivity_geometry(seed, summary):
    ids = {h.grid_pos: h.id for h in seed.helices}
    groups = [[ids[tuple(c)] for c in f] for f in summary["connectivity_faces"]]
    ops = []
    for gid, path in enumerate(summary["connectivity_paths"]):
        points = path["positions"]
        frames = path["frames"]
        lo = path["start"]
        hi = lo + len(points) - 1
        ops.append(
            DeformationOp(
                id=f"connectivity_sweep_{gid}",
                type="sweep",
                plane_a_bp=lo,
                plane_b_bp=hi,
                affected_helix_ids=groups[gid],
                params=SweepParams(
                    points_nm=[points[0], points[-1]],
                    origin_nm=[0, 0, 0],
                    initial_rotation=frames[0],
                    steps=hi - lo,
                    path_length_nm=(hi - lo) * RISE,
                    auto_loop_skips=True,
                    bp_positions_nm=points,
                    bp_frames=frames,
                ),
            )
        )
    constraints = [
        CrossoverConstraint(
            helix_ids_a=groups[a],
            helix_ids_b=groups[b],
            allowed_bp_intervals=[
                j["interval"]
                for j in summary["connectivity_junctions"]
                if j["parent"] == a and j["child"] == b
            ],
        )
        for a in range(len(groups))
        for b in range(a + 1, len(groups))
    ]
    return seed.copy_with(deformations=ops, crossover_constraints=constraints)
