"""Conservative finite-duplex cylinder clearance for rigid network fitting.

Geometric endpoint clearance only: excludes ssDNA/overhangs and intra-body
contacts. Does not claim atomistic sterics or a collision-free motion path.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.constants import HELIX_RADIUS_NM, DSDNA_RISE_PER_BP_NM

def segment_distances(p, q, r, s):
    """Exact finite segment distance, including parallel/degenerate segments."""
    u, v, w = q-p, s-r, p-r
    dot = lambda a, b: np.einsum('ij,ij->i', a, b)
    a, c = dot(u, u), dot(v, v)
    # Avoid subtracting nearly equal O(length**4) terms for parallel duplexes.
    # Cross products also keep finite-difference derivatives stable as they turn.
    normal = np.cross(u, v)
    den = dot(normal, normal)
    t = np.divide(dot(np.cross(v, w), normal), den, out=np.zeros_like(a), where=den > 1e-12)
    z = np.divide(dot(np.cross(u, w), normal), den, out=np.zeros_like(a), where=den > 1e-12)
    interior = np.linalg.norm(w+t[:, None]*u-z[:, None]*v, axis=1)
    interior[(den <= 1e-12) | (t < 0) | (t > 1) | (z < 0) | (z > 1)] = np.inf

    def point_segment(x, y, direction, norm):
        t = np.clip(np.divide(dot(x-y, direction), norm,
                             out=np.zeros_like(norm), where=norm > 1e-12), 0, 1)
        return np.linalg.norm(x-y-t[:, None]*direction, axis=1)

    return np.minimum.reduce([interior, point_segment(p, r, v, c),
                              point_segment(q, r, v, c), point_segment(r, p, u, a),
                              point_segment(s, p, u, a)])


def capsule_gaps(p, q, r, s, diameter):
    """Exact gap near contact; conservative positive AABB bound elsewhere.

    This broad phase preserves the feasible set and every penetration value.
    Candidate pairs are recomputed on every evaluation, never frozen initially.
    """
    separation = np.maximum(np.maximum(np.minimum(p, q)-np.maximum(r, s),
                                       np.minimum(r, s)-np.maximum(p, q)), 0)
    gap = np.linalg.norm(separation, axis=1)-diameter
    near = gap <= 0
    gap[near] = segment_distances(p[near], q[near], r[near], s[near])-diameter
    return gap


def cylinder_gaps(p, q, r, s, diameter):
    """Conservative separation bounds for finite, flat-ended duplex cylinders.

    Capsules bound radial separation; axial support planes additionally certify
    clear ends. Each axis extends half a base-pair rise beyond its terminal sites.
    A positive bound guarantees separation; unrecognized separating directions
    can only cause conservative false contacts, never false clearance.
    """
    pad = DSDNA_RISE_PER_BP_NM / 2
    separation = np.maximum(np.maximum(np.minimum(p, q)-np.maximum(r, s),
                                       np.minimum(r, s)-np.maximum(p, q)), 0)
    gap = np.linalg.norm(separation, axis=1)-diameter-2*pad
    near = gap <= 0
    gap[near] = _cylinder_overlap_bounds(p[near], q[near], r[near], s[near], diameter, pad)
    return gap


def _cylinder_overlap_bounds(p, q, r, s, diameter, pad):
    u, v = q-p, s-r
    lu, lv = np.linalg.norm(u, axis=1), np.linalg.norm(v, axis=1)
    a = np.divide(u, lu[:, None], out=np.zeros_like(u), where=lu[:, None] > 1e-12)
    b = np.divide(v, lv[:, None], out=np.zeros_like(v), where=lv[:, None] > 1e-12)
    gap = capsule_gaps(p-pad*a, q+pad*a, r-pad*b, s+pad*b, diameter)
    cosine = np.clip(np.abs(np.einsum('ij,ij->i', a, b)), 0, 1)
    radial_support = diameter/2 * np.linalg.norm(np.cross(a, b), axis=1)
    delta = (r+s-p-q)/2
    along_a = np.abs(np.einsum('ij,ij->i', delta, a)) - (lu/2+pad) - (lv/2+pad)*cosine - radial_support
    along_b = np.abs(np.einsum('ij,ij->i', delta, b)) - (lv/2+pad) - (lu/2+pad)*cosine - radial_support
    valid = (lu > 1e-12) & (lv > 1e-12)
    return np.where(valid, np.maximum.reduce([gap, along_a, along_b]), gap)



def design_capsules(design, cluster_ids):
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.flexible_segments import _build_bead_graph, _owning_cluster_id
    from backend.core.models import Direction
    _, domains = _build_bead_graph(design)
    sites = {}
    for g in _geometry_for_design(design):
        key = (g['helix_id'], g['bp_index'], Direction(g['direction']))
        sd = domains.get(key)
        owner = _owning_cluster_id(design, key, sd) if sd is not None else None
        if owner not in cluster_ids or g.get('is_flexible_segment') or g.get('is_unpaired') or g.get('copy_k'):
            continue
        site = g.get('helical_site')
        if not site:
            raise ValueError('Cannot resolve duplex collision geometry')
        sites.setdefault((owner, g['helix_id']), {})[g['bp_index']] = np.array(site['axis_point'])
    capsules = []
    for (owner, helix), points in sorted(sites.items()):
        run = []
        def flush():
            if run:
                capsules.append(dict(owner=owner, id=f'{owner}:{helix}:{run[0]}:{run[-1]}',
                                     p=points[run[0]], q=points[run[-1]]))
        for bp in sorted(points):
            if run and (bp != run[-1]+1 or np.linalg.norm(np.cross(
                    points[bp]-points[run[0]], points[run[-1]]-points[run[0]])) > 1e-6):
                previous = run[-1]
                flush()
                run = [previous] if bp == previous+1 else []
            run.append(bp)
        flush()
    return capsules


class Contacts:
    def __init__(self, capsules, moving, centers):
        self.capsules = capsules
        self.p = np.array([c['p'] for c in capsules], dtype=float).reshape(-1, 3)
        self.q = np.array([c['q'] for c in capsules], dtype=float).reshape(-1, 3)
        if not np.isfinite(self.p).all() or not np.isfinite(self.q).all():
            raise ValueError('Collision geometry must be finite')
        self.moving, self.centers = moving, centers
        self.masks = {k: np.array([c['owner'] == k for c in capsules], dtype=bool) for k in moving}
        pairs = [(a, b) for a in range(len(capsules)) for b in range(a)
                 if capsules[a]['owner'] != capsules[b]['owner']]
        self.ia = np.array([a for a, _ in pairs], dtype=int)
        self.ib = np.array([b for _, b in pairs], dtype=int)

    def gaps(self, x):
        p, q = self.p.copy(), self.q.copy()
        for i, k in enumerate(self.moving):
            shift, rv = x[6*i:6*i+3], x[6*i+3:6*i+6]
            mask = self.masks[k]
            for points in (p, q):
                points[mask] = Rotation.from_rotvec(rv).apply(points[mask]-self.centers[k])+self.centers[k]+shift
        return cylinder_gaps(p[self.ia], q[self.ia], p[self.ib], q[self.ib], 2*HELIX_RADIUS_NM)

    def report(self, x):
        gap = self.gaps(x)
        return dict(model='duplex-flat-cylinder-bounds-v1', radius_nm=HELIX_RADIUS_NM,
                    axial_padding_nm=DSDNA_RISE_PER_BP_NM/2,
                    capsule_count=len(self.capsules), pair_count=len(gap),
                    max_penetration_nm=float(max(0., -gap.min())) if len(gap) else 0.,
                    overlap_count=int(np.count_nonzero(gap < -.001)), tolerance_nm=.001,
                    scope='participating rigid clusters; paired duplex axes only',
                    limitations='Excludes ssDNA, overhangs and intra-body contacts; endpoint clearance, not atomistic or trajectory validation')
