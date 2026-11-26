"""Authorized isolated rotation-only loop diagnostic; never used in production."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_helpers import _CANON_O3P
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.ring_piercing import model_piercings
from experiments.loop_offset_comparison import shifted_ellipse, atom_context, atoms_for_pose, atomic_metrics
from experiments.loop_orientation_comparison import context, digest, measure, pack, LABEL
from scripts.agent_structure_guard import audit

ANGLES = np.arange(-180.,180.,5.)
ZERO = int(np.flatnonzero(ANGLES==0)[0])


def host_guard(ac, model, xyz, states, serials, host):
    """Per-residue parent/neighbor count and overlap-depth nonincrease."""
    fixed=np.flatnonzero(~ac['movable']);tree=cKDTree(xyz[fixed])
    flat=states.reshape(-1,3);m=len(serials)
    neighbors=tree.query_ball_point(flat,float(2*ac['radii'].max()-.04))
    counts=np.zeros((len(ANGLES),2),int);depth=np.zeros((len(ANGLES),2))
    for row,near in enumerate(neighbors):
        i=int(serials[row%m]);k=row//m
        for local in near:
            j=int(fixed[local])
            if j in ac['excluded'][i]:continue
            gap=np.linalg.norm(flat[row]-xyz[j])-ac['radii'][i]-ac['radii'][j]
            if gap < -.04:
                group=int(model.atoms[j].helix_id!=host)
                counts[k,group]+=1;depth[k,group]+=-gap-.04
    keep=np.all(counts<=counts[ZERO],axis=1)&np.all(depth<=depth[ZERO]+1e-10,axis=1)
    assert keep[ZERO]
    return keep


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


def conservative_search(model, ac, xyz, states, selections, p, o3, host, ring_keys=None):
    indices=[ZERO]*len(states);newxyz=xyz.copy();accepted=0;ring_rejections=0
    for sweep in range(4):
        changed=False
        order=range(len(states)) if sweep%2==0 else reversed(range(len(states)))
        for k in order:
            left=o3[k][0 if k==0 else indices[k-1]]
            right=p[k+2][0 if k==len(states)-1 else indices[k+1]]
            dleft=np.linalg.norm(p[k+1]-left,axis=1)
            dright=np.linalg.norm(o3[k+1]-right,axis=1)
            old=indices[k]
            keep=(dleft<=dleft[old]+1e-10)&(dright<=dright[old]+1e-10)
            keep&=(dleft>=min(dleft[old],_CANON_O3P)-1e-10)&(dright>=min(dright[old],_CANON_O3P)-1e-10)
            keep&=contact_guard(ac,model,newxyz,states[k],selections[k],host,old)
            cost=(dleft-_CANON_O3P)**2+(dright-_CANON_O3P)**2
            best=int(np.argmin(np.where(keep,cost+1e-12*np.deg2rad(ANGLES)**2,np.inf)))
            if cost[best]<cost[old]-1e-12:
                if ring_keys is not None:
                    trial=newxyz.copy();trial[selections[k]]=states[k][best]
                    if piercing_keys(model,trial)-ring_keys:
                        ring_rejections+=1;continue
                indices[k]=best;newxyz[selections[k]]=states[k][best];accepted+=1;changed=True
        if not changed:break
    return indices,dict(grid_deg=5.,target_nm=_CANON_O3P,individual_linker_nonincrease=True,
                        sweeps=sweep+1,accepted_local_moves=accepted,contact_count_and_depth_nonincrease=True,ring_rejections=ring_rejections)


def solve_chain(p, o3, guard):
    """Global discrete rotor optimum, never lengthening any individual linker."""
    # Fixed attachments have a single state, loop residues have 72 states.
    starts=[0]+[ZERO]*(len(p)-2)+[0]
    distance=[np.linalg.norm(a[:,None,:]-b[None,:,:],axis=2) for a,b in zip(o3[:-1],p[1:])]
    limits=[d[starts[k],starts[k+1]] for k,d in enumerate(distance)]
    score=np.zeros(1);back=[]
    for k,(d,limit) in enumerate(zip(distance,limits)):
        cost=(d-_CANON_O3P)**2
        allowed=(d<=limit+1e-10)&(d>=min(limit,_CANON_O3P)-1e-10)
        cost=np.where(allowed,cost,np.inf)
        total=score[:,None]+cost
        best=np.argmin(total,axis=0)
        score=total[best,np.arange(len(best))]
        if k<len(distance)-1:
            score+=1e-12*np.deg2rad(ANGLES)**2
            score=np.where(guard[k],score,np.inf)
        back.append(best)
    assert np.isfinite(score[0]),'Baseline must always remain feasible'
    indices=[0]
    for prev in reversed(back):indices.append(int(prev[indices[-1]]))
    indices=list(reversed(indices))[1:-1]
    return indices,dict(objective=float(score[0]),grid_deg=5.,target_nm=_CANON_O3P,
                       individual_linker_nonincrease=True)


def variants(model,ac,xyz,records,ctx):
    states=[];matrices=[];selections=[];guards=[];p=[];o3=[]
    host=records[ctx['anchor']]['helix_id']
    for index in [ctx['anchor'],*ctx['loops'],ctx['following']]:
        serials=np.flatnonzero(ac['ri']==index);names={model.atoms[i].name:k for k,i in enumerate(serials)}
        if index not in ctx['loops']:
            coords=xyz[serials][None]
        else:
            axis=ctx['centers'][index]-ctx['beads'][index];axis/=np.linalg.norm(axis)
            rot=Rotation.from_rotvec(np.deg2rad(ANGLES)[:,None]*axis).as_matrix()
            coords=np.einsum('kij,nj->kni',rot,xyz[serials]-ctx['beads'][index])+ctx['beads'][index]
            coords[ZERO]=xyz[serials]  # exact unchanged state
            np.testing.assert_allclose(coords[:,names["O5'"]],np.broadcast_to(ctx['beads'][index],(len(ANGLES),3)),atol=1e-12)
            # Both displayed centroids lie on the rotation axis and stay fixed.
            np.testing.assert_allclose(np.einsum('kij,j->ki',rot,ctx['centers'][index]-ctx['beads'][index])+ctx['beads'][index],np.broadcast_to(ctx['centers'][index],(len(ANGLES),3)),atol=1e-12)
            states.append(coords);matrices.append(rot);selections.append(serials)
            guards.append(host_guard(ac,model,xyz,coords,serials,host))
        p.append(coords[:,names['P']]);o3.append(coords[:,names["O3'"]])
    yield 'current',records,xyz,dict(angles_deg=[0.]*len(ctx['loops']))
    newxyz=xyz.copy()
    for name,guard in [('bond_only',[np.ones(len(ANGLES),bool) for _ in guards]),('host_guarded',guards),('contact_guarded',None),('ring_guarded',None)]:
        if name=='ring_guarded':
            baseline_hits=piercing_keys(model,xyz)
            if piercing_keys(model,newxyz)-baseline_hits:
                indices,info=conservative_search(model,ac,xyz,states,selections,p,o3,host,ring_keys=baseline_hits)
                info['ring_guard_rerun']=True
            else:info={**info,'ring_guard_rerun':False}
        elif guard is None:indices,info=conservative_search(model,ac,xyz,states,selections,p,o3,host)
        else:indices,info=solve_chain(p,o3,guard)
        posed=deepcopy(records);newxyz=xyz.copy()
        for k,(index,state,selection) in enumerate(zip(ctx['loops'],indices,selections)):
            newxyz[selection]=states[k][state]
            matrix=matrices[k][state]@ctx['mats'][index]
            posed[index]['slab_quaternion']=Rotation.from_matrix(matrix).as_quat().tolist()
            posed[index]['axis_tangent']=matrix[:,1].tolist()
            posed[index]['base_normal']=matrix[:,2].tolist()
        np.testing.assert_array_equal(newxyz[~ac['movable']],xyz[~ac['movable']])
        for old,new in zip(records,posed):
            for key in ('backbone_position','base_position','slab_position'):assert old[key]==new[key]
        if name=='ring_guarded':assert not piercing_keys(model,newxyz)-baseline_hits
        info['angles_deg']=[float(ANGLES[i]) for i in indices]
        info['host_guard_allowed_states']=[int(g.sum()) for g in guards]
        yield name,posed,newxyz,info


def run(out,verify=False,pilot=False):
    recipe=json.loads((out/'process.json').read_text());assert 'A/B testing authorized' in recipe['user_grant']
    paths=sorted((out/'inputs').glob('*.nadoc'))
    if pilot:paths=[p for p in paths if p.stem in ('loop-6-forward-bp40','loop-30-forward-bp40','loop-80-forward-bp40')]
    summaries=[]
    for path in paths:
        original=path.read_bytes();design=Design.model_validate_json(original);proof=audit(design)
        original_records=_geometry_for_design(design);original_ctx=context(original_records)
        model=build_atomistic_model(design,strand_loop_display=True);ac=atom_context(model,original_records)
        def offset(*args,**kwargs):return shifted_ellipse(*args,**kwargs,offset=.50)
        with patch('backend.core.strand_loop_geometry.ellipse_points',offset):records=_geometry_for_design(design)
        ctx=context(records);xyz=atoms_for_pose(ac,original_ctx,ctx);result={}
        for name,posed,positions,search in variants(model,ac,xyz,records,ctx):
            new=context(posed);metrics=measure(posed,new,new['centers'],new['mats']);atoms=atomic_metrics(model,ac,positions,posed,new)
            lengths=np.array([b['length_nm'] for b in atoms['linker_bonds']])
            atoms['mean_linker_nm']=float(lengths.mean());atoms['rms_target_error_nm']=float(np.sqrt(np.mean((lengths-_CANON_O3P)**2)))
            atoms['linkers_over_020nm']=int(np.sum(lengths>.20))
            metrics.update(max_slab_displacement_nm=0.,backbone_displacement_nm=0.,attachment_displacement_nm=0.,
                           max_atom_displacement_nm=float(np.linalg.norm(positions-xyz,axis=1).max()))
            result[name]=dict(metrics=metrics,atomic=atoms,search=search,slab_centers=new['centers'].tolist(),
              slab_quaternions=[r['slab_quaternion'] for r in posed],backbone_positions=new['beads'].tolist(),
              loop_atom_positions=positions[ac['movable']].tolist())
        old=result['current']
        for v in result.values():
            for group in ('metrics','atomic'):
                def key(c):return (c.get('kind'),c['a'],c['b'])
                before={key(c) for c in old[group]['contacts']};after={key(c) for c in v[group]['contacts']}
                v[group].update(removed_contacts=len(before-after),introduced_contacts=len(after-before))
            for a,b in zip(old['atomic']['linker_bonds'],v['atomic']['linker_bonds']):
                assert (a['a'],a['b'])==(b['a'],b['b'])
                assert b['length_nm']<=a['length_nm']+1e-10
                b['delta_nm']=b['length_nm']-a['length_nm']
            def hitkey(h):return tuple(h['bond_serials']),tuple(h['ring_serials'])
            before={hitkey(h) for h in old['atomic']['ring_piercings']};after={hitkey(h) for h in v['atomic']['ring_piercings']}
            v['atomic'].update(introduced_piercings=len(after-before),removed_piercings=len(before-after))
        first=records[ctx['loops'][0]]
        value=dict(label=LABEL,case=path.stem,input_sha256=digest(path),proof=proof,records=records,length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],loop_indices=ctx['loops'],near_indices=ctx['loops'],anchor_index=ctx['anchor'],following_index=ctx['following'],variants=result,
          atoms=[dict(name=a.name,record=int(ac['ri'][i]),element=a.element) for i,a in enumerate(model.atoms)],atom_positions=xyz.tolist(),atom_bonds=model.bonds,loop_atom_indices=np.flatnonzero(ac['movable']).tolist())
        encoded=pack(value);target=out/'cases'/f'{path.stem}.json.gz'
        if verify:assert gzip.decompress(target.read_bytes())==encoded,path.stem
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f:f.write(encoded)
        assert original==path.read_bytes()
        summaries.append(dict(case=path.stem,length=len(ctx['loops']),variants={k:dict(display=v['metrics']['by_group'],atomic=v['atomic']['by_group'],piercings=len(v['atomic']['ring_piercings']),introduced_piercings=v['atomic']['introduced_piercings'],max_linker_nm=v['atomic']['max_linker_nm'],mean_linker_nm=v['atomic']['mean_linker_nm'],rms_target_error_nm=v['atomic']['rms_target_error_nm'],linkers_over_020nm=v['atomic']['linkers_over_020nm']) for k,v in result.items()}))
        if len(summaries)%7==0 or pilot:print(f'{len(summaries)}/{len(paths)} {path.stem}',flush=True)
    name=('pilot-' if pilot else '')+('replay.json' if verify else 'summary.json')
    (out/name).write_text(json.dumps(dict(status='verified',cases=len(summaries),tolerance=0) if verify else summaries,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--verify',action='store_true');p.add_argument('--pilot',action='store_true')
    a=p.parse_args();run(a.output.resolve(),a.verify,a.pilot)
