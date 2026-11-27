"""Approved source-O3/TT placements for reverse forced junctions.

Transfer the reviewed finite bank in a proper two-helix frame. Match topology
and phase, never design identifiers; no online minimization or conformer search.
Clearance is not a simulation-readiness certificate (see packaged provenance).
"""
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from backend.core.terminal_t_motifs import two_helix_frame

VERSION = "forced-tt-o3-v1"


@lru_cache(maxsize=1)
def library():
    data = json.loads((Path(__file__).parent / "data/forced_tt_motif_templates.json").read_text())
    if data["version"] != VERSION:
        raise ValueError("Unsupported forced-TT template library")
    return data


def _matches(design, atoms, bonds, data):
    from backend.core.deformation import deformed_nucleotide_arrays
    from backend.core.junction_topology import crossover_connectors

    forced = {x.id for x in design.forced_ligations if x.extra_bases == "TT"}
    if not forced:
        return [], {}
    strands = {s.id: s for s in design.strands}
    near = defaultdict(list)
    for e in design.extensions:
        if not e.sequence:
            continue
        strand = strands.get(e.strand_id)
        if strand is None or not strand.domains:
            continue
        dom = strand.domains[0 if e.end == "five_prime" else -1]
        near[dom.helix_id].append(dom.start_bp if e.end == "five_prime" else dom.end_bp)
    inserts, adj = defaultdict(dict), defaultdict(set)
    for i, a in enumerate(atoms):
        if a.crossover_id in forced and a.extra_base_k in (0, 1):
            inserts[a.crossover_id][f"{a.extra_base_k}:{a.name}"] = i
    for i, j in bonds:
        adj[i].add(j)
        adj[j].add(i)
    helices = {h.id: h for h in design.helices}
    arrays = {}

    def site(hid, bp, direction):
        if hid not in arrays:
            a = deformed_nucleotide_arrays(helices[hid], design)
            copies = a.get("copy_ks", np.zeros(len(a["bp_indices"]), dtype=int))
            arrays[hid] = {
                (int(b), "REVERSE" if rev else "FORWARD"):
                    (a["axis_points"][k], a["axis_tangents"][k], a["radial_hats"][k])
                for k, (b, rev) in enumerate(zip(a["bp_indices"], a["directions"])) if copies[k] == 0
            }
        return arrays[hid].get((bp, direction))

    expected = set(data["templates"][0]["parts"])
    matches = []
    for c in crossover_connectors(design):
        if c.crossover_id not in forced or c.n_inserts != 2 or c.from_dir != "REVERSE" or c.to_dir != "FORWARD":
            continue
        endpoints = [(c.from_helix, c.from_bp), (c.to_helix, c.to_bp)]
        if any(abs(b - bp) <= 2 for hid, bp in endpoints for b in near[hid]):
            continue
        if any(abs(ls.bp_index - bp) <= 2 for hid, bp in endpoints for ls in helices[hid].loop_skips):
            continue
        a, b = site(c.from_helix, c.from_bp, c.from_dir), site(c.to_helix, c.to_bp, c.to_dir)
        if a is None or b is None or np.dot(a[1], b[1]) < .999:
            continue
        frame = two_helix_frame(a[0], b[0], a[1], c.from_dir)
        if frame is None or np.max(np.abs(np.r_[a[2] @ frame, b[2] @ frame] - data["phase"])) >= .02:
            continue
        if np.linalg.norm((b[0] - a[0]) @ frame - data["axis_delta_nm"]) >= .05:
            continue
        roles = dict(inserts[c.crossover_id])
        try:
            source = next(j for j in adj[roles["0:P"]] if atoms[j].name == "O3'" and atoms[j].crossover_id != c.crossover_id)
            roles["source:O3'"] = source
            roles["anchor:C3'"] = next(j for j in adj[source] if atoms[j].name == "C3'")
            roles["anchor:P"] = next(j for j in adj[roles["1:O3'"]] if atoms[j].name == "P" and atoms[j].crossover_id != c.crossover_id)
        except (KeyError, StopIteration):
            continue
        if not expected <= roles.keys():
            continue
        matches.append(dict(junction=c.crossover_id, roles=roles, frame=frame))
    return matches, adj


def _weight(role):
    if role.startswith("source:"):
        return 0.
    k, name = role.split(":", 1)
    if k == "0":
        return 0. if name in ("P", "OP1", "OP2") else .125 if name in ("O5'", "C5'") else .45 if name == "O3'" else .25
    return 1. if name == "O3'" else .55 if name in ("P", "OP1", "OP2") else .625 if name in ("O5'", "C5'") else .75


def apply_forced_tt_motifs(design, atoms, bonds):
    """Apply the approved bank simultaneously, before manual residue transforms.

    Score each homogeneous template state against the actual fixed environment,
    as in the approved comparison. The normal piercing detector remains separate;
    runtime ranking uses contacts, penetration and bond strain, not a new solver.
    """
    if not any(x.extra_bases == "TT" for x in design.forced_ligations):
        return []
    data = library()
    matches, adj = _matches(design, atoms, bonds, data)
    if not matches:
        return []
    roles = list(data["templates"][0]["parts"])
    # Stable role order is shared by the coordinate matrix and its ownership map.
    ids = np.array([m["roles"][r] for m in matches for r in roles], dtype=int)
    if len(set(ids)) != len(ids):
        raise ValueError("Overlapping forced-TT movable selections")
    owner = np.repeat(np.arange(len(matches)), len(roles))
    moving = set(ids)
    positions = np.array([[a.x, a.y, a.z] for a in atoms])
    ghosts = {i for i, a in enumerate(atoms) if a.name == "P" and not any(atoms[j].name == "O3'" for j in adj[i])}
    ghosts |= {j for i in tuple(ghosts) for j in adj[i] if atoms[j].name in ("OP1", "OP2")}
    fixed = np.array(sorted(set(range(len(atoms))) - moving - ghosts), dtype=int)
    tree = cKDTree(positions[fixed])
    excluded = {i: {i} | adj[i] | {k for j in adj[i] for k in adj[j]} for i in moving}
    weights = np.array([_weight(r) for r in roles])[:, None]
    candidates = []
    for template in data["templates"]:
        local = np.array([template["parts"][r] for r in roles])
        blocks, strains = [], []
        for m in matches:
            rr, frame = m["roles"], m["frame"]
            left, right = positions[rr["anchor:C3'"]], positions[rr["anchor:P"]]
            delta = right - left - np.asarray(template["span_nm"]) @ frame.T
            q = left + local @ frame.T + weights * delta
            blocks.append(q)
            coords = dict(zip(roles, q)) | {"anchor:C3'": left, "anchor:P": right}
            strains.append(max(abs(np.linalg.norm(coords[a] - coords[b]) * 10 - length * 10) for a, b, length in data["bonds"]))
        xyz = np.vstack(blocks)
        distances = [[] for _ in matches]
        for n, neighbors in enumerate(tree.query_ball_point(xyz, .2)):
            distances[owner[n]].extend(float(np.linalg.norm(xyz[n] - positions[j]) * 10)
                                       for j in fixed[neighbors] if j not in excluded[ids[n]])
        for a, b in sorted(cKDTree(xyz).query_pairs(.2)):
            if ids[b] in excluded[ids[a]]:
                continue
            distance = float(np.linalg.norm(xyz[a] - xyz[b]) * 10)
            for k in {owner[a], owner[b]}:
                distances[k].append(distance)
        scores = [(len(ds), sum((2. - distance) ** 2 for distance in ds), strains[k], template["id"])
                  for k, ds in enumerate(distances)]
        candidates.append((template, blocks, scores))
    reports = []
    for k, m in enumerate(matches):
        template, blocks, scores = min(candidates, key=lambda item: item[2][k])
        selected = [m["roles"][r] for r in roles]
        for i, q in zip(selected, blocks[k]):
            atoms[i].x, atoms[i].y, atoms[i].z = map(float, q)
        reports.append(dict(junction=m["junction"], template=template["id"], moved_atom_serials=selected,
                            contacts_under_2A=scores[k][0], penetration_A2=scores[k][1], max_bond_error_A=scores[k][2]))
    return reports
