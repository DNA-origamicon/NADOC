"""Joint rigid-body kinematics for flexible tethers (no topology or atom changes).

Minimise contour violations subject to duplex clearance over all bodies. Each connected
component fixes its largest participating rigid cluster; overlapping organizational
clusters that own no tether endpoint are not bodies in this problem. Slack is free.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from threadpoolctl import threadpool_limits
from backend.core.flexible_contacts import Contacts, design_capsules

TOLERANCE_NM = 0.001


@threadpool_limits.wrap(limits=1, user_api='blas')
def solve_network(bodies, connections, *, max_nfev=1000, capsules=None):
    """Pure numeric input/output; positions are current world-space anchors.

    bodies: {id: {size, pivot, translation, rotation}}.
    connections: [{id, a, b, pa, pb, contour}].
    Returns absolute poses plus final per-tether diagnostics. Deterministic ties
    use cluster id. Rotations are incremental about each body's anchor centroid,
    then composed into its existing pose, preserving its authored pivot.
    """
    edges = sorted(connections, key=lambda c: c['id'])
    ids = sorted({c[k] for c in edges for k in ('a', 'b')})
    if any(k not in bodies for k in ids):
        raise ValueError('Flexible connection references a missing cluster')
    neighbors = {k: set() for k in ids}
    for c in edges:
        if c['a'] == c['b']:
            raise ValueError('Flexible connection must join distinct clusters')
        if c['contour'] <= 0 or not np.isfinite(c['contour']):
            raise ValueError('Invalid flexible contour length')
        neighbors[c['a']].add(c['b'])
        neighbors[c['b']].add(c['a'])
    pinned, unseen = [], set(ids)
    while unseen:
        pending, component = [min(unseen)], set()
        while pending:
            k = pending.pop()
            if k in component:
                continue
            component.add(k)
            pending.extend(neighbors[k] - component)
        unseen -= component
        pinned.append(min(component, key=lambda k: (-bodies[k]['size'], k)))
    moving = [k for k in ids if k not in pinned]
    index = {k: i for i, k in enumerate(moving)}
    centers = {k: np.mean([c[p] for c in edges for side, p in (('a', 'pa'), ('b', 'pb'))
                           if c[side] == k], axis=0) for k in ids}
    pa = np.array([c['pa'] for c in edges], dtype=float).reshape(-1, 3)
    pb = np.array([c['pb'] for c in edges], dtype=float).reshape(-1, 3)
    contour = np.array([c['contour'] for c in edges])
    if not np.isfinite(pa).all() or not np.isfinite(pb).all():
        raise ValueError('Flexible anchors must have finite coordinates')
    masks = {(k, side): np.array([c[side] == k for c in edges])
             for k in moving for side in ('a', 'b')}

    def lengths(x):
        a, b = pa.copy(), pb.copy()
        for k, i in index.items():
            shift, rv = x[6*i:6*i+3], x[6*i+3:6*i+6]
            rot = Rotation.from_rotvec(rv)
            for side, points in (('a', a), ('b', b)):
                mask = masks[k, side]
                points[mask] = rot.apply(points[mask] - centers[k]) + centers[k] + shift
        return np.linalg.norm(a - b, axis=1)

    x = np.zeros(6 * len(moving))
    contacts = Contacts(capsules or [], moving, centers)
    initial_contacts = contacts.report(x)
    before = lengths(x)
    evaluations = 0
    settings = dict(method='trf', max_nfev=max_nfev, motion_penalty=1e-6,
                    ftol=1e-10, xtol=1e-10, gtol=1e-10)
    if capsules is not None:
        settings = dict(method='SLSQP', maxiter=min(max_nfev, 500), ftol=1e-12,
                        motion_penalty=1e-10, contact_constraint='gap >= 0')
    if len(edges) and (np.max(before - contour) > TOLERANCE_NM or initial_contacts['overlap_count']):
        # Repair intersecting starts, then impose contact inequalities while
        # closing tethers. Pure anchor callers retain their numerical contract.
        if capsules is not None:
            from backend.core.flexible_contact_solve import solve_contact_constrained
            x, evaluations, settings = solve_contact_constrained(lengths, contacts, contour, x, max_nfev)
        else:
            result = least_squares(lambda v: np.r_[np.maximum(lengths(v)-contour, 0), 1e-6*v],
                                   x, max_nfev=max_nfev, ftol=1e-10, xtol=1e-10, gtol=1e-10)
            x, evaluations = result.x, result.nfev
    final = lengths(x)
    transforms = []
    for k, i in index.items():
        shift, rv = x[6*i:6*i+3], x[6*i+3:6*i+6]
        if np.linalg.norm(shift) < 1e-10 and np.linalg.norm(rv) < 1e-10:
            continue
        body, center = bodies[k], centers[k]
        pivot, translation = np.asarray(body['pivot']), np.asarray(body['translation'])
        delta = Rotation.from_rotvec(rv)
        transforms.append(dict(cluster_id=k, pivot=list(body['pivot']),
            translation=(delta.apply(pivot + translation - center) + center + shift - pivot).tolist(),
            rotation=(delta * Rotation.from_quat(body['rotation'])).as_quat().tolist()))
    diagnostics = [dict(connection_id=c['id'], before_nm=float(old), length_nm=float(new),
                        contour_nm=float(c['contour']), excess_nm=float(max(0, new-c['contour'])))
                   for c, old, new in zip(edges, before, final)]
    maximum = max((c['excess_nm'] for c in diagnostics), default=0.)
    clearance = contacts.report(x)
    return dict(transforms=transforms, fixed_cluster_ids=sorted(pinned),
                connections=diagnostics, max_excess_nm=maximum,
                converged=maximum <= TOLERANCE_NM and clearance['max_penetration_nm'] <= TOLERANCE_NM, evaluations=evaluations,
                tolerance_nm=TOLERANCE_NM, solver='rigid-flex-staged-contact-v2' if capsules is not None else 'rigid-flex-network-v1',
                contacts=clearance, initial_contacts=initial_contacts,
                cluster_sizes={k: bodies[k]['size'] for k in ids},
                settings=settings)


def solve_design_network(design, *, scope='all', conn_id=None):
    """Read a design, resolve all endpoints, then solve only numeric arrays.

    Relax-one includes its connected network: isolating a pair would break its
    neighbors. Disconnected networks are untouched in that scope.
    """
    from backend.core.flexible_relax import _geom_index, _anchor_world_pos
    from backend.core.flexible_segments import _build_bead_graph, _owning_cluster_id

    if scope not in ('one', 'all'):
        raise ValueError('Unknown flexible relaxation scope')
    conns = list(design.flexible_connections)
    if scope == 'one':
        selected = next((c for c in conns if c.id == conn_id), None)
        if selected is None:
            raise ValueError('Flexible connection not found')
        reached = {selected.cluster_a_id, selected.cluster_b_id}
        while True:
            expanded = reached | {k for c in conns if c.cluster_a_id in reached or c.cluster_b_id in reached
                                  for k in (c.cluster_a_id, c.cluster_b_id)}
            if expanded == reached:
                break
            reached = expanded
        conns = [c for c in conns if c.cluster_a_id in reached]
    if not conns:
        return solve_network({}, [])
    geom = _geom_index(design)
    # Count owned backbone slots, including exact-base/domain selections. Counting
    # entire helices makes two disjoint subclusters on one helix falsely equal.
    _, domains = _build_bead_graph(design)
    sizes = {}
    for key, sd in domains.items():
        owner = _owning_cluster_id(design, key, sd)
        sizes[owner] = sizes.get(owner, 0) + 1
    bodies = {c.id: dict(size=sizes.get(c.id, 0), pivot=c.pivot,
                         translation=c.translation, rotation=c.rotation)
              for c in design.cluster_transforms}
    edges = []
    for c in conns:
        a, b = _anchor_world_pos(geom, design, c.anchor_a), _anchor_world_pos(geom, design, c.anchor_b)
        if a is None or b is None:
            raise ValueError(f'Cannot resolve anchors for flexible connection {c.id}')
        edges.append(dict(id=c.id, a=c.cluster_a_id, b=c.cluster_b_id,
                          pa=a, pb=b, contour=c.contour_length_nm))
    ids = {c[k] for c in edges for k in ('a', 'b')}
    return solve_network(bodies, edges, capsules=design_capsules(design, ids))
