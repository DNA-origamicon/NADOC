"""Session-approved terminal-T/TT-crossover conformers for native atomistic builds.

Match topology and a proper two-helix frame, never design/strand identifiers.
The library is finite: rebuilding performs template transfer, not minimization.
Residual bond strain is recorded in the data's provenance; this is not a seed gate.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

VERSION = "tt-terminal-t-v1"


@lru_cache(maxsize=1)
def templates():
    data = json.loads((Path(__file__).parent / "data" / "terminal_t_motif_templates.json").read_text())
    if data["version"] != VERSION:
        raise ValueError("Unsupported terminal-T template library")
    return data["templates"]


def two_helix_frame(source_axis, target_axis, source_tangent, source_direction):
    """Columns x=toward partner, y=z×x, z=source strand's 5′→3′ direction."""
    z = np.asarray(source_tangent, dtype=float).copy()
    z /= np.linalg.norm(z)
    if source_direction == "REVERSE":
        z *= -1
    x = np.asarray(target_axis) - source_axis
    x = x - z * np.dot(x, z)
    if np.linalg.norm(x) < 1e-8:
        return None
    x /= np.linalg.norm(x)
    return np.column_stack((x, np.cross(z, x), z))


def _matches(design, atoms, bonds):
    from backend.core.deformation import deformed_nucleotide_arrays
    from backend.core.junction_topology import crossover_connectors

    strands = {s.id: s for s in design.strands}
    ends = {}
    by_helix = defaultdict(list)
    for e in design.extensions:
        strand = strands.get(e.strand_id)
        if strand is None or not strand.domains:
            continue
        dom = strand.domains[0 if e.end == "five_prime" else -1]
        bp = dom.start_bp if e.end == "five_prime" else dom.end_bp
        key = (dom.helix_id, bp, dom.direction.value, e.end)
        ends.setdefault(key, []).append(e)
        by_helix[dom.helix_id].append((bp, e.id))
    ext, insert, adj = defaultdict(dict), defaultdict(dict), defaultdict(set)
    for i, a in enumerate(atoms):
        if a.extension_id is not None and a.ext_k == 0:
            ext[a.extension_id][a.name] = i
        elif a.crossover_id is not None and a.extra_base_k == 1:
            insert[a.crossover_id][a.name] = i
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
                (int(b), "REVERSE" if rev else "FORWARD"): (a["axis_points"][k], a["axis_tangents"][k], a["radial_hats"][k])
                for k, (b, rev) in enumerate(zip(a["bp_indices"], a["directions"]))
                if int(copies[k]) == 0
            }
        return arrays[hid].get((bp, direction))

    sequences = {x.id: x.extra_bases for x in (*design.crossovers, *design.forced_ligations)}
    matches = []
    for c in crossover_connectors(design):
        if c.n_inserts != 2 or sequences.get(c.crossover_id) != "TT" or c.from_dir == c.to_dir:
            continue
        if any(abs(ls.bp_index - bp) <= 2 for hid, bp in [(c.from_helix, c.from_bp), (c.to_helix, c.to_bp)]
               for ls in helices[hid].loop_skips):
            continue
        sign = 1 if c.from_dir == "FORWARD" else -1
        five = ends.get((c.from_helix, c.from_bp + sign, c.from_dir, "five_prime"), [])
        three = ends.get((c.to_helix, c.to_bp + sign, c.to_dir, "three_prime"), [])
        if len(five) != 1 or len(three) != 1 or five[0].sequence != "T" or three[0].sequence != "T":
            continue
        near = {e for h, bp in [(c.from_helix, c.from_bp), (c.to_helix, c.to_bp)] for b, e in by_helix[h] if abs(b - bp) <= 2}
        if near != {five[0].id, three[0].id}:
            continue
        a, b = site(c.from_helix, c.from_bp, c.from_dir), site(c.to_helix, c.to_bp, c.to_dir)
        if a is None or b is None or np.dot(a[1], b[1]) < .999:
            continue
        frame = two_helix_frame(a[0], b[0], a[1], c.from_dir)
        if frame is None:
            continue
        phase = np.r_[a[2] @ frame, b[2] @ frame]
        delta = (b[0] - a[0]) @ frame
        eligible = [t for t in sorted(templates(), key=lambda t: t["id"]) if t["source_direction"] == c.from_dir
                    and np.max(np.abs(phase - t["phase"])) < .02
                    and np.linalg.norm(delta - t["axis_delta_nm"]) < .05]
        if not eligible:
            continue
        try:
            ex3, ex5, tt = ext[three[0].id], ext[five[0].id], insert[c.crossover_id]
            root3 = next(j for j in adj[ex3["P"]] if atoms[j].extension_id != three[0].id and atoms[j].name == "O3'")
            root5 = next(j for j in adj[ex5["O3'"]] if atoms[j].extension_id != five[0].id and atoms[j].name == "P")
            rt = next(j for j in adj[tt["P"]] if atoms[j].crossover_id != c.crossover_id or atoms[j].extra_base_k != 1)
            pi = next(j for j in adj[tt["O3'"]] if atoms[j].name == "P")
            ph = {atoms[j].name: j for j in {pi, *adj[pi]} if j != tt["O3'"]}
            c5 = next(j for j in adj[ph["O5'"]] if atoms[j].name == "C5'")
            if set(ph) != {"P", "OP1", "OP2", "O5'"}:
                continue
            roles = {"three_prime": ex3, "five_prime": ex5, "last_T": tt, "phosphate": ph}
            if any(not set(part) <= set(roles[role]) for t in eligible for role, part in t["parts"].items()):
                continue
        except (KeyError, StopIteration):
            continue
        matches.append(dict(junction=c.crossover_id, extensions=[five[0].id, three[0].id], frame=frame, roles=roles,
                            roots={"three_prime": root3, "five_prime": root5, "last_T": rt, "phosphate": c5}, templates=eligible))
    return matches, adj


def _candidate(match, template, positions):
    roles, roots, frame = match["roles"], match["roots"], match["frame"]
    q = {}
    for role, part in template["parts"].items():
        for name, local in part.items():
            q[roles[role][name]] = positions[roots[role]] + np.asarray(local) @ frame.T

    def connect(parent, child, length):
        origin = q.get(parent, positions[parent])
        delta = q[child] - origin
        norm = np.linalg.norm(delta)
        if norm < 1e-10:
            raise ValueError("Degenerate terminal-T root direction")
        q[child] = origin + delta * (length / norm)

    ex3, ex5, tt, ph = (roles[k] for k in ["three_prime", "five_prime", "last_T", "phosphate"])
    connect(roots["three_prime"], ex3["P"], .16)
    connect(ex3["P"], ex3["O5'"], .16)
    connect(roots["five_prime"], ex5["O3'"], template["five_prime_root_nm"])
    if template["family"] != 1:
        connect(ex5["O3'"], ex5["C3'"], .1433)
    connect(roots["last_T"], tt["P"], .16)
    connect(tt["P"], tt["O5'"], .16)
    connect(roots["phosphate"], ph["O5'"], np.linalg.norm(positions[roots["phosphate"]] - positions[ph["O5'"]]))
    connect(ph["O5'"], ph["P"], .16)
    for name in ["OP1", "OP2"]:
        connect(ph["P"], ph[name], .148)
    connect(ph["P"], tt["O3'"], .16)
    connect(tt["O3'"], tt["C3'"], .1433)
    return q


def apply_terminal_t_motifs(design, atoms, bonds):
    """Apply approved matches in-place before manual nucleotide poses; report selections."""
    if not design.extensions:
        return []
    matches, adj = _matches(design, atoms, bonds)
    if not matches:
        return []
    positions = np.array([[a.x, a.y, a.z] for a in atoms], dtype=float)
    moving = {i for m in matches for t in m["templates"] for role, part in t["parts"].items() for name in part for i in [m["roles"][role][name]]}
    # P/OP ghosts at 5′ termini are removed by CHARMM 5TER; do not score them as physical obstacles.
    ghosts = {i for i, a in enumerate(atoms) if a.name == "P" and not any(atoms[j].name == "O3'" for j in adj[i])}
    ghosts |= {j for i in tuple(ghosts) for j in adj[i] if atoms[j].name in {"OP1", "OP2"}}
    fixed = np.array(sorted(set(range(len(atoms))) - moving - ghosts), dtype=int)
    tree = cKDTree(positions[fixed])
    exclusion = {i: {i} | adj[i] | {k for j in adj[i] for k in adj[j]} for i in moving}
    reports = []
    for m in matches:
        own = {i for t in m["templates"] for role, part in t["parts"].items() for name in part for i in [m["roles"][role][name]]}
        others = np.array(sorted(moving - own), dtype=int)
        other_tree = cKDTree(positions[others]) if len(others) else None
        best = None
        for template in m["templates"]:
            q = _candidate(m, template, positions)
            ids = sorted(q)
            xyz = np.array([q[i] for i in ids])
            distances = []
            for index, neighbors in zip(ids, tree.query_ball_point(xyz, .2)):
                distances.extend(np.linalg.norm(q[index] - positions[j]) for j in fixed[neighbors] if j not in exclusion[index])
            if other_tree is not None:
                for index, neighbors in zip(ids, other_tree.query_ball_point(xyz, .2)):
                    distances.extend(np.linalg.norm(q[index] - positions[j]) for j in others[neighbors] if j not in exclusion[index])
            for a, b in cKDTree(xyz).query_pairs(.2):
                if ids[b] not in exclusion[ids[a]]:
                    distances.append(np.linalg.norm(xyz[a] - xyz[b]))
            score = (int(sum(x < .08 for x in distances)), int(sum(x < .2 for x in distances)), template["id"])
            if best is None or score < best[0]:
                best = score, q, template
            if score[:2] == (0, 0):
                break
        score, q, template = best
        # Keep nonphysical display-only 5′ phosphate ghosts attached to the transported sugar.
        ex5 = m["roles"]["five_prime"]
        names = ["O5'", "C5'", "C4'"]
        old = positions[[ex5[n] for n in names]]
        new = np.array([q[ex5[n]] for n in names])
        u, _, vt = np.linalg.svd((old - old.mean(0)).T @ (new - new.mean(0)))
        correction = np.diag([1., 1., np.linalg.det(u @ vt)])
        rotation = u @ correction @ vt
        for name in ["P", "OP1", "OP2"]:
            if name in ex5 and ex5[name] in ghosts:
                q[ex5[name]] = (positions[ex5[name]] - old.mean(0)) @ rotation + new.mean(0)
        for i, p in q.items():
            atoms[i].x, atoms[i].y, atoms[i].z = map(float, p)
            positions[i] = p
        reports.append(dict(junction=m["junction"], extensions=m["extensions"], template=template["id"],
                            family=template["family"], moved_atom_serials=sorted(q), contacts_under_2A=score[1], severe_overlaps=score[0]))
    return reports
