"""Isolated outward-loop A/B; no production imports this module or its candidates."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model, VDW_RADIUS
from backend.core.constants import SSDNA_CONTOUR_PER_NT_NM
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.ring_piercing import model_piercings
from backend.core.strand_loop_geometry import ellipse_points
from experiments.loop_orientation_comparison import context, digest, measure, pack, LABEL
from scripts.agent_structure_guard import audit

OFFSETS = (.15, .30, .50, .75)


def shifted_ellipse(start, end, axis, outward, count, aspect_ratio=3., rotation_deg=0., *, offset):
    """Translate the ellipse body with smooth fixed-root shoulders, refit contour."""
    if not offset:
        return ellipse_points(start, end, axis, outward, count, aspect_ratio, rotation_deg)
    start, end, axis, outward = [np.array(x, dtype=float) for x in (start, end, axis, outward)]
    axis /= np.linalg.norm(axis)
    outward -= axis * np.dot(outward, axis)
    outward /= np.linalg.norm(outward)
    outward = Rotation.from_rotvec(axis*np.deg2rad(rotation_deg)).apply(outward)
    theta = np.linspace(0, 2*np.pi, max(2049, 32*count))
    t = theta/(2*np.pi)
    # Smooth shoulders approach a near-uniform body translation; zero at roots.
    shoulder = 1-np.exp(-(np.sin(np.pi*t)/.18)**2)
    shoulder[[0,-1]] = 0
    baseline = start + t[:,None]*(end-start) + offset*shoulder[:,None]*outward
    shape = aspect_ratio*np.sin(theta)[:,None]*axis + (1-np.cos(theta))[:,None]*outward
    target = (count+1)*SSDNA_CONTOUR_PER_NT_NM
    if np.linalg.norm(np.diff(baseline,axis=0),axis=1).sum() >= target:
        raise ValueError('Offset exceeds contour budget')
    lo, hi = 0., target
    for _ in range(48):
        scale = (lo+hi)/2
        length = np.linalg.norm(np.diff(baseline+scale*shape,axis=0),axis=1).sum()
        if length < target: lo = scale
        else: hi = scale
    curve = baseline+(lo+hi)/2*shape
    distance = np.r_[0,np.cumsum(np.linalg.norm(np.diff(curve,axis=0),axis=1))]
    assert abs(distance[-1]-target)<1e-10
    points = np.column_stack([np.interp(np.linspace(0,distance[-1],count+2),distance,curve[:,i]) for i in range(3)])
    points[0],points[-1] = start,end
    assert np.max(np.linalg.norm(np.diff(points,axis=0),axis=1)) <= SSDNA_CONTOUR_PER_NT_NM+1e-10
    return points


def atom_context(model, records):
    def key(a): return a.strand_id,a.helix_id,a.bp_index,a.direction,a.copy_k or 0
    lookup={(r['strand_id'],r['helix_id'],r['bp_index'],r['direction'],r.get('copy_k',0)):i for i,r in enumerate(records)}
    ri=np.array([lookup[key(a)] for a in model.atoms])
    movable=np.array([bool(a.copy_k) for a in model.atoms])
    bonded=[set() for _ in model.atoms]
    for a,b in model.bonds: bonded[a].add(b);bonded[b].add(a)
    excluded=[neighbors|{k for j in neighbors for k in bonded[j]} for neighbors in bonded]
    return dict(ri=ri,movable=movable,excluded=excluded,
        radii=np.array([VDW_RADIUS[a.element] for a in model.atoms]),
        xyz=np.array([[a.x,a.y,a.z] for a in model.atoms]))


def atoms_for_pose(ac, old, new):
    xyz=ac['xyz'].copy()
    for i in new['loops']:
        selection=ac['ri']==i
        rotation=new['mats'][i]@old['mats'][i].T
        xyz[selection]=(xyz[selection]-old['beads'][i])@rotation.T+new['beads'][i]
    np.testing.assert_array_equal(xyz[~ac['movable']],ac['xyz'][~ac['movable']])
    return xyz


def atomic_metrics(model,ac,xyz,records,ctx):
    tree=cKDTree(xyz);contacts=[];host=records[ctx['anchor']]['helix_id']
    for i in np.flatnonzero(ac['movable']):
        for j in tree.query_ball_point(xyz[i],float(ac['radii'][i]+ac['radii'].max()-.04)):
            if j==i or (ac['movable'][j] and j<i) or ac['ri'][i]==ac['ri'][j] or j in ac['excluded'][i]: continue
            gap=float(np.linalg.norm(xyz[i]-xyz[j])-ac['radii'][i]-ac['radii'][j])
            if gap < -.04:
                group='loop' if ac['movable'][j] else ('parent_helix' if model.atoms[j].helix_id==host else 'other_helix')
                contacts.append(dict(a=int(i),b=int(j),gap_nm=gap,group=group))
    contacts.sort(key=lambda x:(x['a'],x['b']))
    hits=model_piercings(model,positions=xyz,max_report=100000)
    hits=[h for h in hits if any(ac['movable'][i] for i in [*h['bond_serials'],*h['ring_serials']])]
    bonds=[dict(a=a,b=b,length_nm=float(np.linalg.norm(xyz[a]-xyz[b]))) for a,b in model.bonds
           if (ac['movable'][a] or ac['movable'][b]) and {model.atoms[a].name,model.atoms[b].name}=={"O3'",'P'}]
    return dict(contacts=contacts,by_group={g:sum(c['group']==g for c in contacts) for g in ('parent_helix','other_helix','loop')},
                ring_piercings=hits,linker_bonds=bonds,max_linker_nm=max(b['length_nm'] for b in bonds))


def run(out,verify=False,pilot=False):
    recipe=json.loads((out/'process.json').read_text())
    assert recipe['user_grant']=='A/B testing authorized for outward ellipse offsets'
    summaries=[]
    paths=sorted((out/'inputs').glob('*.nadoc'))
    if pilot: paths=[p for p in paths if p.stem=='loop-30-forward-bp40']
    for path in paths:
        original=path.read_bytes();design=Design.model_validate_json(original);proof=audit(design)
        records=_geometry_for_design(design);ctx=context(records)
        model=build_atomistic_model(design,strand_loop_display=True);ac=atom_context(model,records)
        result={}
        for offset in (0.,*OFFSETS):
            if offset:
                def candidate(*args,**kwargs): return shifted_ellipse(*args,**kwargs,offset=offset)
                with patch('backend.core.strand_loop_geometry.ellipse_points',candidate):
                    posed=_geometry_for_design(design)
            else: posed=deepcopy(records)
            new=context(posed)
            for i in range(len(records)):
                if i not in ctx['loops']: assert records[i]==posed[i]
                else:
                    mutable={'backbone_position','base_position','slab_position','slab_quaternion','base_normal','axis_tangent'}
                    assert {k:v for k,v in records[i].items() if k not in mutable}=={k:v for k,v in posed[i].items() if k not in mutable}
            metrics=measure(posed,new,new['centers'],new['mats'])
            displacement=np.linalg.norm(new['beads']-ctx['beads'],axis=1)
            metrics['max_slab_displacement_nm']=float(np.linalg.norm(new['centers']-ctx['centers'],axis=1).max())
            metrics['backbone_displacement_nm']=float(displacement.max())
            metrics['attachment_displacement_nm']=float(displacement[[ctx['anchor'],ctx['following']]].max())
            metrics['per_base_displacement_nm']=displacement[ctx['loops']].tolist()
            xyz=atoms_for_pose(ac,ctx,new)
            atoms=atomic_metrics(model,ac,xyz,posed,new)
            result['current' if not offset else f'offset_{offset:.2f}']=dict(metrics=metrics,atomic=atoms,
                slab_centers=new['centers'].tolist(),slab_quaternions=[r['slab_quaternion'] for r in posed],
                backbone_positions=new['beads'].tolist(),loop_atom_positions=xyz[ac['movable']].tolist())
        before={(c['kind'],c['a'],c['b']) for c in result['current']['metrics']['contacts']}
        oldatoms={(c['a'],c['b']) for c in result['current']['atomic']['contacts']}
        for v in result.values():
            after={(c['kind'],c['a'],c['b']) for c in v['metrics']['contacts']}
            newatoms={(c['a'],c['b']) for c in v['atomic']['contacts']}
            v['metrics'].update(removed_contacts=len(before-after),introduced_contacts=len(after-before))
            v['atomic'].update(removed_contacts=len(oldatoms-newatoms),introduced_contacts=len(newatoms-oldatoms))
        first=records[ctx['loops'][0]]
        value=dict(label=LABEL,case=path.stem,input_sha256=digest(path),proof=proof,records=records,
            length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],loop_indices=ctx['loops'],near_indices=ctx['loops'],
            anchor_index=ctx['anchor'],following_index=ctx['following'],variants=result,
            atoms=[dict(name=a.name,record=int(ac['ri'][i]),element=a.element) for i,a in enumerate(model.atoms)],
            atom_positions=ac['xyz'].tolist(),atom_bonds=model.bonds,loop_atom_indices=np.flatnonzero(ac['movable']).tolist())
        encoded=pack(value);target=out/'cases'/f'{path.stem}.json.gz'
        if verify: assert gzip.decompress(target.read_bytes())==encoded,path.stem
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f:f.write(encoded)
        assert path.read_bytes()==original
        summaries.append(dict(case=path.stem,length=value['length'],direction=value['direction'],bp=value['bp'],
            variants={k:dict(display=v['metrics']['by_group'],atomic=v['atomic']['by_group'],piercings=len(v['atomic']['ring_piercings']),
              max_linker_nm=v['atomic']['max_linker_nm'],roots=v['metrics']['root_bonds_nm'],
              max_step_nm=v['metrics']['max_backbone_step_nm'],max_displacement_nm=v['metrics']['backbone_displacement_nm']) for k,v in result.items()}))
        if len(summaries)%7==0 or pilot: print(f'{len(summaries)}/{len(paths)} {path.stem}',flush=True)
    name=('pilot-' if pilot else '')+('replay.json' if verify else 'summary.json')
    (out/name).write_text(json.dumps(dict(status='verified',cases=len(summaries),tolerance=0) if verify else summaries,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--verify',action='store_true');p.add_argument('--pilot',action='store_true')
    a=p.parse_args();run(a.output.resolve(),a.verify,a.pilot)
