"""Approved fixed-center ring-priority loop display fitting.

Display-only rigid templates; topology and surrounding atoms never change.
"""
from contextvars import ContextVar
from copy import deepcopy
from collections import OrderedDict
from threading import Lock
import hashlib
import json

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.strand_loop_bond_fit import ANGLES, ZERO
from backend.core.ring_piercing import model_piercings

TARGET = .1600
_BUILDING_CONTEXT = ContextVar('loop_ring_fit_context', default=False)
_POSE_CACHE = OrderedDict()
_CACHE_LOCK = Lock()


def refine_loop_geometry(design, records):
    """One authority for Full and atomistic poses; cache by complete inputs."""
    if _BUILDING_CONTEXT.get() or not any(r.get('placement_source') == 'strand-loop-ellipse-v4-ring-priority' for r in records):
        return
    # Atomistic construction uses temporary model_copy views with transforms
    # already applied. Preserve those objects; revalidating their JSON would
    # incorrectly require removed placement clusters to still exist.
    key = hashlib.sha256((design.model_dump_json() + json.dumps(records, sort_keys=True)).encode()).digest()
    with _CACHE_LOCK:
        poses = _POSE_CACHE.get(key)
    if poses is None:
        poses = _fit_poses(design, records)
        with _CACHE_LOCK:
            _POSE_CACHE[key] = poses
            _POSE_CACHE.move_to_end(key)
            while len(_POSE_CACHE) > 8:
                _POSE_CACHE.popitem(last=False)
    for i, quaternion in poses:
        records[i]['slab_quaternion'] = list(quaternion)


def _fit_poses(design, records):
    from backend.core.atomistic import build_atomistic_model, VDW_RADIUS
    from backend.core.strand_loops import strand_entries
    records = deepcopy(records)
    token = _BUILDING_CONTEXT.set(True)
    try:
        model = build_atomistic_model(design, strand_loop_display=True, fast_bridges=True)
    finally:
        _BUILDING_CONTEXT.reset(token)
    key = lambda r: (r['strand_id'], r['helix_id'], r['bp_index'], r['direction'], r.get('copy_k', 0))
    lookup = {key(r): i for i, r in enumerate(records)}
    ri = np.array([lookup.get((a.strand_id, a.helix_id, a.bp_index, a.direction, a.copy_k or 0), -1) for a in model.atoms])
    movable = np.array([i >= 0 and records[i].get('loop_order', 0) > 0 for i in ri])
    bonded = [set() for _ in model.atoms]
    for a, b in model.bonds:
        bonded[a].add(b); bonded[b].add(a)
    ac = dict(ri=ri, movable=movable, radii=np.array([VDW_RADIUS[a.element] for a in model.atoms]),
              excluded=[neighbors | {k for j in neighbors for k in bonded[j]} for neighbors in bonded])
    xyz = np.array([[a.x, a.y, a.z] for a in model.atoms])
    poses = []
    for strand in design.strands:
        entries = list(strand_entries(design, strand))
        for loop in strand.loops:
            if not 6 <= loop.length < 40:
                continue
            identity = (loop.helix_id, loop.bp_index, loop.direction)
            indices = [lookup.get((strand.id, *identity, k)) for k in range(loop.length + 1)]
            if any(i is None for i in indices):
                continue  # A partial geometry request may omit this helix.
            start = entries.index((*identity, 0))
            following = lookup.get((strand.id, *entries[start + loop.length + 1]))
            if following is None:
                continue
            ctx = dict(anchor=indices[0], following=following, loops=indices[1:],
                       beads=np.array([r['backbone_position'] for r in records]),
                       centers=np.array([r['slab_position'] for r in records]),
                       mats=Rotation.from_quat([r['slab_quaternion'] for r in records]).as_matrix())
            records, xyz, _ = optimize_rotations(model, ac, xyz, records, ctx, .10)
            poses.extend((i, tuple(records[i]['slab_quaternion'])) for i in indices[1:])
    return tuple(poses)


def contact_guard(ac, model, xyz, states, serials, host, current_state):
    """Check a local rotation against every other residue, including this loop."""
    own=set(serials);fixed=np.array([i for i in range(len(xyz)) if i not in own])
    tree=cKDTree(xyz[fixed]);flat=states.reshape(-1,3);m=len(serials)
    neighbors=tree.query_ball_point(flat,float(2*ac['radii'].max()-.04))
    counts=np.zeros((len(ANGLES),3),int);depth=np.zeros((len(ANGLES),3))
    for row,near in enumerate(neighbors):
        i=int(serials[row%m]);k=row//m
        for local in near:
            j=int(fixed[local])
            if j in ac['excluded'][i]:continue
            gap=np.linalg.norm(flat[row]-xyz[j])-ac['radii'][i]-ac['radii'][j]
            if gap < -.04:
                group=2 if ac['movable'][j] else int(model.atoms[j].helix_id!=host)
                counts[k,group]+=1;depth[k,group]+=-gap-.04
    return np.all(counts<=counts[current_state],axis=1)&np.all(depth<=depth[current_state]+1e-10,axis=1)


def piercing_keys(model,xyz):
    return {(tuple(h['bond_serials']),tuple(h['ring_serials'])) for h in model_piercings(model,positions=xyz,max_report=100000)}


def optimize_rotations(model,ac,xyz,records,ctx,max_growth=0.):
    """Ring-first local search with a baseline-relative linker growth budget.

    Every loop residue visits the complete 5-degree rotor grid on alternating
    sweeps. For residues implicated in existing piercings, prefer removal before
    bond error. New piercing identities are forbidden at every accepted step.
    """
    serials=[];states=[];matrices=[];p=[];o3=[]
    host=records[ctx['anchor']]['helix_id']
    for index in [ctx['anchor'],*ctx['loops'],ctx['following']]:
        ids=np.flatnonzero(ac['ri']==index);names={model.atoms[i].name:k for k,i in enumerate(ids)}
        if index in ctx['loops']:
            bead=ctx['beads'][index];axis=ctx['centers'][index]-bead;axis/=np.linalg.norm(axis)
            rot=Rotation.from_rotvec(np.deg2rad(ANGLES)[:,None]*axis).as_matrix()
            coords=np.einsum('kij,nj->kni',rot,xyz[ids]-bead)+bead;coords[ZERO]=xyz[ids]
            serials.append(ids);states.append(coords);matrices.append(rot)
        else:coords=xyz[ids][None]
        p.append(coords[:,names['P']]);o3.append(coords[:,names["O3'"]])
    chosen=[ZERO]*len(states);positions=xyz.copy();hits=piercing_keys(model,positions)
    accepted=0;checks=0;rejected=0;history=[]
    for sweep in range(4):
        changed=False
        order=range(len(states)) if sweep%2==0 else reversed(range(len(states)))
        for k in order:
            left=o3[k][0 if k==0 else chosen[k-1]];right=p[k+2][0 if k==len(states)-1 else chosen[k+1]]
            dl=np.linalg.norm(p[k+1]-left,axis=1);dr=np.linalg.norm(o3[k+1]-right,axis=1);old=chosen[k]
            initial_left=np.linalg.norm(o3[k][0 if k==0 else ZERO]-p[k+1][ZERO])
            initial_right=np.linalg.norm(o3[k+1][ZERO]-p[k+2][0 if k==len(states)-1 else ZERO])
            keep=(dl<=initial_left+max_growth+1e-10)&(dr<=initial_right+max_growth+1e-10)
            keep&=(dl>=min(initial_left,TARGET)-1e-10)&(dr>=min(initial_right,TARGET)-1e-10)
            keep&=contact_guard(ac,model,positions,states[k],serials[k],host,old)
            cost=(dl-TARGET)**2+(dr-TARGET)**2+1e-12*np.deg2rad(ANGLES)**2
            if max_growth==0:keep&=(dl<=dl[old]+1e-10)&(dr<=dr[old]+1e-10)
            own=set(serials[k]);unchanged={h for h in hits if not own.intersection((*h[0],*h[1]))}
            best=(len(hits),float(cost[old]),old);best_hits=hits
            for trial_index in sorted(np.flatnonzero(keep),key=lambda i:(cost[i],abs(ANGLES[i]),ANGLES[i])):
                if trial_index==old:continue
                trial=positions.copy();trial[serials[k]]=states[k][trial_index]
                trial_hits=piercing_keys(model,trial);checks+=1
                if trial_hits-hits:rejected+=1;continue
                candidate=(len(trial_hits),float(cost[trial_index]),int(trial_index))
                if candidate[:2]<best[:2]:best=candidate;best_hits=trial_hits
                # Sorted bond error: the first state that removes every mutable
                # piercing is the optimum among this residue's feasible states.
                if len(trial_hits)==len(unchanged):break
            if best[:2]<(len(hits),float(cost[old])):
                chosen[k]=best[2];positions[serials[k]]=states[k][best[2]]
                history.append(dict(sweep=sweep+1,ordinal=k+1,from_deg=float(ANGLES[old]),to_deg=float(ANGLES[best[2]]),piercings_before=len(hits),piercings_after=len(best_hits)))
                hits=best_hits;accepted+=1;changed=True
        if not changed:break
    posed=deepcopy(records)
    for k,index in enumerate(ctx['loops']):
        matrix=matrices[k][chosen[k]]@ctx['mats'][index]
        posed[index]['slab_quaternion']=Rotation.from_matrix(matrix).as_quat().tolist()
        assert posed[index]['slab_position']==records[index]['slab_position']
        assert posed[index]['backbone_position']==records[index]['backbone_position']
    np.testing.assert_array_equal(positions[~ac['movable']],xyz[~ac['movable']])
    return posed,positions,dict(angles_deg=[float(ANGLES[i]) for i in chosen],accepted_moves=accepted,
        sweeps=sweep+1,ring_checks=checks,ring_rejections=rejected,ordered_moves=history)
