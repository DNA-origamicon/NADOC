"""Read-only rigid-flex solver comparison; outputs metrics, never a structure.

Run: python -m experiments.flexible_collision_benchmark INPUT.nadoc
Collision proxies are contiguous occupied duplex-axis capsules (radius 1 nm).
No atomistic claim, trajectory guarantee, geometry mutation or publication.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares, minimize
from scipy.spatial.transform import Rotation

from backend.core.constants import HELIX_RADIUS_NM
from backend.core.flexible_contacts import segment_distances, capsule_gaps
from backend.core.design_geometry import _geometry_for_design
from backend.core.flexible_relax import _geom_index, _anchor_world_pos
from backend.core.flexible_segments import _build_bead_graph, _owning_cluster_id
from backend.core.models import Design, Direction


class Problem:
    def __init__(self, design, *, broad_phase=False):
        self.broad_phase = broad_phase
        conns = sorted(design.flexible_connections, key=lambda c: c.id)
        ids = sorted({k for c in conns for k in (c.cluster_a_id, c.cluster_b_id)})
        _, domains = _build_bead_graph(design)
        ownership = {key: _owning_cluster_id(design, key, sd) for key, sd in domains.items()}
        sizes = {k: sum(v == k for v in ownership.values()) for k in ids}
        # This benchmark deliberately requires one connected network.
        reached = {ids[0]}
        for _ in ids:
            reached |= {k for c in conns if c.cluster_a_id in reached or c.cluster_b_id in reached
                        for k in (c.cluster_a_id, c.cluster_b_id)}
        if reached != set(ids):
            raise ValueError('Benchmark requires a single connected network')
        self.fixed = min(ids, key=lambda k: (-sizes[k], k))
        self.ids = [self.fixed] + [k for k in ids if k != self.fixed]
        ix = {k: i for i, k in enumerate(self.ids)}
        geom = _geom_index(design)
        self.pa = np.array([_anchor_world_pos(geom, design, c.anchor_a) for c in conns])
        self.pb = np.array([_anchor_world_pos(geom, design, c.anchor_b) for c in conns])
        self.ea = np.array([ix[c.cluster_a_id] for c in conns])
        self.eb = np.array([ix[c.cluster_b_id] for c in conns])
        self.contour = np.array([c.contour_length_nm for c in conns])
        self.centers = np.array([np.concatenate([self.pa[self.ea == i], self.pb[self.eb == i]]).mean(0)
                                 for i in range(len(ids))])
        # Use paired, non-flexible sites only. Never bridge missing slots or bends.
        sites = {}
        for g in _geometry_for_design(design):
            key = (g['helix_id'], g['bp_index'], Direction(g['direction']))
            owner = ownership.get(key)
            if owner not in ix or g.get('is_flexible_segment') or g.get('is_unpaired') or g.get('copy_k'):
                continue
            sites.setdefault((ix[owner], g['helix_id']), {})[g['bp_index']] = np.array(g['helical_site']['axis_point'])
        starts, ends, owners = [], [], []
        for (owner, _), points in sorted(sites.items()):
            run = []
            def flush():
                if run:
                    starts.append(points[run[0]])
                    ends.append(points[run[-1]])
                    owners.append(owner)
            for bp in sorted(points):
                if run and (bp != run[-1]+1 or
                            np.linalg.norm(np.cross(points[bp]-points[run[0]],
                                                    points[run[-1]]-points[run[0]])) > 1e-6):
                    previous = run[-1]
                    flush()
                    # At a bend, share the corner so the next segment covers
                    # the connecting axis edge. Missing slots stay disconnected.
                    run = [previous] if bp == previous+1 else []
                run.append(bp)
            flush()
        self.p, self.q, self.owners = np.array(starts), np.array(ends), np.array(owners)
        self.ia, self.ib = np.array([(a, b) for a in range(len(owners)) for b in range(a)
                                    if owners[a] != owners[b]]).T
        self.dimension = 6*(len(ids)-1)
        self.names = {c.id: c.name for c in design.cluster_transforms}

    def move(self, points, owners, x):
        v = np.vstack([np.zeros(6), x.reshape(-1, 6)])
        rotations = Rotation.from_rotvec(v[:, 3:]).as_matrix()
        return np.einsum('nij,nj->ni', rotations[owners], points-self.centers[owners]) + self.centers[owners] + v[owners, :3]

    def constraints(self, x):
        lengths = np.linalg.norm(self.move(self.pa, self.ea, x)-self.move(self.pb, self.eb, x), axis=1)
        p, q = self.move(self.p, self.owners, x), self.move(self.q, self.owners, x)
        args = (p[self.ia], q[self.ia], p[self.ib], q[self.ib])
        gap = (capsule_gaps(*args, 2*HELIX_RADIUS_NM) if self.broad_phase
               else segment_distances(*args)-2*HELIX_RADIUS_NM)
        return self.contour-lengths, gap

    def metrics(self, x):
        tether, gap = self.constraints(x)
        p = self.move(self.p, self.owners, x)
        return dict(max_tether_excess_nm=float(max(0, -tether.min())),
                    accepted=bool(tether.min() >= -.001 and gap.min() >= -.001),
                    capsule_overlaps=int(sum(gap < -.001)),
                    max_penetration_nm=float(max(0, -gap.min())),
                    rms_capsule_endpoint_motion_nm=float(np.sqrt(np.mean(np.sum((p-self.p)**2, axis=1)))))


def expanded_seed(problem):
    """Translate whole bodies radially; never scale their internal geometry.

    Return the first clear sampled expansion, or the least-penetrating seed.
    Tether extension is allowed only in these uncommitted numeric iterates.
    """
    centers = np.array([np.concatenate([problem.p[problem.owners == i],
                                        problem.q[problem.owners == i]]).mean(0)
                        for i in range(len(problem.ids))])
    best = None
    for factor in (1.25, 1.5, 2., 3., 4., 6., 8.):
        x = np.zeros((len(problem.ids)-1, 6))
        x[:, :3] = (factor-1)*(centers[1:]-centers[0])
        metrics = problem.metrics(x.ravel())
        score = (metrics['capsule_overlaps'], metrics['max_penetration_nm'])
        if best is None or score < best[0]:
            best = (score, x.ravel(), factor)
        if metrics['capsule_overlaps'] == 0:
            break
    return best[1], best[2]


def compare(problem, methods=('joint_penalty', 'contact_continuation', 'constrained_sqp')):
    zero = np.zeros(problem.dimension)
    results = {'saved': problem.metrics(zero)}
    print(json.dumps({'saved': results['saved'], 'capsules': len(problem.p),
                      'pairs': len(problem.ia), 'fixed': problem.names[problem.fixed]}), flush=True)
    def penalty(x, contact_weight=1., motion=1e-5, allowance=0.):
        tether, gap = problem.constraints(x)
        return np.r_[np.minimum(tether+allowance, 0), contact_weight*np.minimum(gap, 0), motion*x]

    feasible_seed = None
    for method in methods:
        start = time.monotonic()
        x = zero.copy()
        if method == 'warm_start_sqp':
            if feasible_seed is None:
                results[method] = {'skipped': 'No feasible preceding trial to refine'}
                print(json.dumps({method: results[method]}), flush=True)
                continue
            x = feasible_seed.copy()
        if method == 'joint_penalty':
            fit = least_squares(penalty, x, max_nfev=300, ftol=1e-9, gtol=1e-9, xtol=1e-9)
            x = fit.x
        elif method in ('contact_continuation', 'radial_expand_relax'):
            if method == 'radial_expand_relax':
                x, factor = expanded_seed(problem)
                print(json.dumps({'expansion_seed': dict(factor=factor, **problem.metrics(x))}), flush=True)
            for weight in (.1, .3, 1., 3., 10.):
                fit = least_squares(lambda v: penalty(v, weight), x, max_nfev=150,
                                    ftol=1e-9, gtol=1e-9, xtol=1e-9)
                x = fit.x
        elif method in ('separate_reclose', 'radial_expand_reclose'):
            # First repair only contacts, then tighten temporary tether bounds.
            # True contours and native body dimensions are never edited.
            if method == 'radial_expand_reclose':
                x, factor = expanded_seed(problem)
                print(json.dumps({'expansion_factor': factor}), flush=True)
            else:
                fit = least_squares(lambda v: np.r_[np.minimum(problem.constraints(v)[1], 0), 1e-3*v],
                                    x, max_nfev=150, ftol=1e-9, gtol=1e-9, xtol=1e-9)
                x = fit.x
            allowance = np.maximum(-problem.constraints(x)[0], 0)
            print(json.dumps({'separation_seed': problem.metrics(x)}), flush=True)
            for fraction in (1., .5, .25, .1, 0.):
                fit = least_squares(lambda v: penalty(v, 10., allowance=fraction*allowance),
                                    x, max_nfev=150, ftol=1e-9, gtol=1e-9, xtol=1e-9)
                x = fit.x
        else:
            def objective(v):
                if method in ('minimum_motion_sqp', 'warm_start_sqp'):
                    p = problem.move(problem.p, problem.owners, v)
                    q = problem.move(problem.q, problem.owners, v)
                    return .5*np.mean(np.sum((p-problem.p)**2+(q-problem.q)**2, axis=1))
                return .5*np.dot(v, v)
            fit = minimize(objective, x, method='SLSQP',
                           constraints={'type': 'ineq', 'fun': lambda v: np.concatenate(problem.constraints(v))},
                           options={'maxiter': 400, 'ftol': 1e-9})
            x = fit.x
        results[method] = dict(**problem.metrics(x), seconds=time.monotonic()-start,
                               optimizer_success=bool(fit.success))
        if results[method]['accepted']:
            feasible_seed = x.copy()
        print(json.dumps({method: results[method]}), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--broad-phase', action='store_true')
    parser.add_argument('--before-last-relax', action='store_true',
                        help='Read the existing last Relax pre-state, without undoing or writing the design')
    parser.add_argument('--methods', nargs='+', default=['joint_penalty', 'contact_continuation', 'constrained_sqp'],
                        choices=['joint_penalty', 'contact_continuation', 'constrained_sqp', 'minimum_motion_sqp', 'warm_start_sqp',
                                 'radial_expand_relax', 'separate_reclose', 'radial_expand_reclose'])
    args = parser.parse_args()
    raw = args.source.read_bytes()
    print(json.dumps({'source': str(args.source), 'sha256': hashlib.sha256(raw).hexdigest(),
                      'broad_phase': args.broad_phase, 'methods': args.methods}), flush=True)
    design = Design.model_validate_json(raw)
    if args.before_last_relax:
        feature = design.feature_log[-1]
        if feature.op_kind != 'flexible-relax' or not feature.design_snapshot_gz_b64:
            raise ValueError('Last feature must have an existing Relax pre-state snapshot')
        design = Design.model_validate_json(gzip.decompress(base64.b64decode(feature.design_snapshot_gz_b64)))
        print(json.dumps({'input_state': 'existing pre-Relax snapshot', 'feature_id': feature.id}), flush=True)
    problem = Problem(design, broad_phase=args.broad_phase)
    compare(problem, args.methods)
    if args.source.read_bytes() != raw:
        raise RuntimeError('Source changed during read-only benchmark')


if __name__ == '__main__':
    main()
