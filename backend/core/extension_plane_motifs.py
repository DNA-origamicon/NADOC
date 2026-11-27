"""Approved terminal-T placements bounded by the plane across the nick.

Use a finite, reviewed local-geometry dictionary, never an online optimizer.
Matching is deliberately conservative: changed neighborhoods keep their native
placement rather than extrapolating an unreviewed molecular geometry. Contexts
contain geometry/connectivity, not document, strand, helix or extension IDs.
The reviewed bank covers shared native display/export/NAMD seed (interpolated-bridge) geometry;
unmatched alternative bridge geometries are deliberately not extrapolated.
"""
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

VERSION = "terminal-plane-v1"
RADIUS_NM = 1.6


@lru_cache(maxsize=1)
def library():
    data = json.loads((Path(__file__).parent / 'data/extension_plane_templates.json').read_text())
    if data['version'] != VERSION:
        raise ValueError('Unsupported terminal-plane template library')
    return data


def context_key(atoms, positions, indices, adjacency, origin, frame, end, own):
    """Rigid-motion/identifier invariant identity for a reviewed local environment."""
    records = []
    for i in indices:
        a = atoms[i]
        role = 'self' if a.extension_id == own else 'extension' if a.extension_id else 'insert' if a.crossover_id else 'ordinary'
        xyz = np.round((positions[i] - origin) @ frame, 5)
        xyz[xyz == 0] = 0.  # Canonicalize negative zero before hashing.
        records.append(([role, a.name, *xyz.tolist()], int(i)))
    records.sort(key=lambda item: item[0])
    mapping = {i: k for k, (_, i) in enumerate(records)}
    edges = sorted([mapping[i], mapping[j]] for i in mapping for j in adjacency[i] if j in mapping and mapping[i] < mapping[j])
    payload = [end, [row for row, _ in records], edges]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


def contexts(design, atoms, bonds):
    """Describe single-T termini in the unchanged pre-placement geometry."""
    from backend.core.deformation import deformed_nucleotide_arrays

    if not any(e.sequence == 'T' for e in design.extensions):
        return [], None, set()
    adj, ext = defaultdict(set), defaultdict(dict)
    for i, j in bonds:
        adj[i].add(j)
        adj[j].add(i)
    for i, a in enumerate(atoms):
        if a.extension_id and a.ext_k == 0:
            ext[a.extension_id][a.name] = i
    ghosts = {i for i, a in enumerate(atoms) if a.name == 'P' and not any(atoms[j].name == "O3'" for j in adj[i])}
    ghosts |= {j for i in tuple(ghosts) for j in adj[i] if atoms[j].name in ('OP1', 'OP2')}
    positions = np.array([[a.x, a.y, a.z] for a in atoms])
    physical = np.array(sorted(set(range(len(atoms))) - ghosts), dtype=int)
    tree = cKDTree(positions[physical])
    strands = {s.id: s for s in design.strands}
    helices = {h.id: h for h in design.helices}
    arrays = {}

    def site(hid, bp, direction):
        if hid not in arrays:
            a = deformed_nucleotide_arrays(helices[hid], design)
            copies = a.get('copy_ks', np.zeros(len(a['bp_indices']), dtype=int))
            arrays[hid] = {(int(b), 'REVERSE' if rev else 'FORWARD'):
                           (a['axis_points'][k], a['axis_tangents'][k], a['radial_hats'][k])
                           for k, (b, rev) in enumerate(zip(a['bp_indices'], a['directions'])) if copies[k] == 0}
        return arrays[hid].get((bp, direction))

    out = []
    for e in design.extensions:
        if e.sequence != 'T' or e.strand_id not in strands:
            continue
        strand = strands[e.strand_id]
        if not strand.domains or e.id not in ext:
            continue
        dom = strand.domains[0 if e.end == 'five_prime' else -1]
        bp = dom.start_bp if e.end == 'five_prime' else dom.end_bp
        direction = dom.direction.value
        step = (1 if direction == 'FORWARD' else -1) * (1 if e.end == 'three_prime' else -1)
        if any(abs(ls.bp_index - bp) <= 2 for ls in helices[dom.helix_id].loop_skips):
            continue
        a, b = site(dom.helix_id, bp, direction), site(dom.helix_id, bp + step, direction)
        if a is None or b is None:
            continue
        normal = b[0] - a[0]
        if np.linalg.norm(normal) < 1e-8:
            continue
        normal = normal / np.linalg.norm(normal)
        x = a[2] - normal * np.dot(a[2], normal)
        x /= np.linalg.norm(x)
        frame = np.column_stack([x, np.cross(normal, x), normal])
        roles = {name: i for name, i in ext[e.id].items() if i not in ghosts}
        own = set(roles.values())
        boundary = [(i, j) for i in own for j in adj[i] if j not in own and j not in ghosts]
        if len(boundary) != 1:
            continue
        child, anchor = boundary[0]
        origin = positions[anchor]
        near = physical[tree.query_ball_point(origin, RADIUS_NM)]
        key = context_key(atoms, positions, near, adj, origin, frame, e.end, e.id)
        out.append(dict(extension=e.id, key=key, roles=roles, all_roles=ext[e.id],
                        anchor=anchor, child=child, origin=origin, frame=frame,
                        plane=(a[0] + b[0]) / 2, normal=normal))
    return out, positions, ghosts


def apply_extension_plane_motifs(design, atoms, bonds):
    """Apply only demonstrated neighborhoods, simultaneously, before manual poses."""
    if not any(e.sequence == 'T' for e in design.extensions):
        return []
    data = library()
    matches, positions, ghosts = contexts(design, atoms, bonds)
    reports = []
    for m in matches:
        t = data['contexts'].get(m['key'])
        if t is None or set(t['parts']) != set(m['roles']):
            continue
        all_points = m['origin'] + np.asarray(t['all_atom_points']) @ m['frame'].T
        if np.max((all_points - m['plane']) @ m['normal']) > 1e-8:
            continue
        q = {m['roles'][name]: m['origin'] + np.asarray(local) @ m['frame'].T for name, local in t['parts'].items()}
        if abs(np.linalg.norm(q[m['child']] - m['origin']) - .16) > 1e-8:
            continue
        # Nonphysical 5TER phosphate display ghosts follow the transported sugar,
        # matching the existing terminal-T placement convention.
        rr = m['all_roles']
        if any(i in ghosts for i in rr.values()):
            names = ["O5'", "C5'", "C4'"]
            old = positions[[rr[n] for n in names]]
            new = np.array([q[rr[n]] for n in names])
            u, _, vt = np.linalg.svd((old - old.mean(0)).T @ (new - new.mean(0)))
            rotation = u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt
            for i in rr.values():
                if i in ghosts:
                    q[i] = (positions[i] - old.mean(0)) @ rotation + new.mean(0)
        for i, p in q.items():
            atoms[i].x, atoms[i].y, atoms[i].z = map(float, p)
        reports.append(dict(extension=m['extension'], context=m['key'], moved_atom_serials=sorted(q)))
    return reports
