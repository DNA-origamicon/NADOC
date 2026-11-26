"""Isolated radial-outward/clearance/rotation A/B; no production imports this."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model
from backend.core.constants import BASE_DISPLACEMENT, SSDNA_CONTOUR_PER_NT_NM
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.strand_loop_geometry import ellipse_points
from experiments.loop_bond_rotation_comparison import ANGLES, ZERO, contact_guard, piercing_keys
from experiments.loop_offset_comparison import atom_context, atoms_for_pose, atomic_metrics
from experiments.loop_orientation_comparison import context, digest, measure, pack, LABEL
from scripts.agent_structure_guard import audit

OFFSETS = (.50, .75, 1., 1.5, 2., 3., 4.)
TARGET = .1600


def radial_pose(records, ctx, offset):
    """Nominal ellipse-body center defines the requested outward radial field."""
    anchor=records[ctx['anchor']];end=records[ctx['following']]
    start=np.array(anchor['backbone_position']);finish=np.array(end['backbone_position'])
    axis=np.array(anchor['axis_tangent']);axis/=np.linalg.norm(axis)
    outward=-np.array(anchor['base_normal']);outward-=axis*np.dot(axis,outward);outward/=np.linalg.norm(outward)
    count=len(ctx['loops']);ratio=3.
    points=ellipse_points(start,finish,axis,outward,count,ratio,0.,outward_offset_nm=offset)
    # Reproduce the curve's scale to identify its nominal translated body center.
    theta=np.linspace(0,2*np.pi,max(2049,32*count));t=theta/(2*np.pi)
    shoulder=1-np.exp(-(np.sin(np.pi*t)/.18)**2);shoulder[[0,-1]]=0
    line=start+t[:,None]*(finish-start)+offset*shoulder[:,None]*outward
    shape=ratio*np.sin(theta)[:,None]*axis+(1-np.cos(theta))[:,None]*outward
    target=(count+1)*SSDNA_CONTOUR_PER_NT_NM;lo,hi=0.,target
    for _ in range(48):
        scale=(lo+hi)/2;length=np.linalg.norm(np.diff(line+scale*shape,axis=0),axis=1).sum()
        if length<target:lo=scale
        else:hi=scale
    center=(start+finish)/2+(offset+(lo+hi)/2)*outward
    posed=deepcopy(records)
    for ordinal,index in enumerate(ctx['loops'],1):
        radial=points[ordinal]-center;radial/=np.linalg.norm(radial)
        tangent=points[ordinal+1]-points[ordinal-1];tangent/=np.linalg.norm(tangent)
        normal=tangent-radial*np.dot(tangent,radial);normal/=np.linalg.norm(normal)
        matrix=np.column_stack((np.cross(normal,radial),normal,radial))
        base=points[ordinal]+BASE_DISPLACEMENT*radial
        posed[index].update(backbone_position=points[ordinal].tolist(),base_position=base.tolist(),
            slab_position=base.tolist(),slab_quaternion=Rotation.from_matrix(matrix).as_quat().tolist(),
            base_normal=radial.tolist(),axis_tangent=tangent.tolist())
    return posed,center


def optimize_rotations(model,ac,xyz,records,ctx):
    """Ring-first local search, without increasing overlap counts/depth or linkers.

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
            keep=(dl<=dl[old]+1e-10)&(dr<=dr[old]+1e-10)
            keep&=(dl>=min(dl[old],TARGET)-1e-10)&(dr>=min(dr[old],TARGET)-1e-10)
            keep&=contact_guard(ac,model,positions,states[k],serials[k],host,old)
            cost=(dl-TARGET)**2+(dr-TARGET)**2+1e-12*np.deg2rad(ANGLES)**2
            keep&=cost<=cost[old]+1e-12
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
        # Radial axis is exactly preserved by the rotation, so outward facing
        # cannot be sacrificed to obtain a better linker objective.
        np.testing.assert_allclose(matrix[:,2],ctx['mats'][index][:,2],atol=1e-12)
    np.testing.assert_array_equal(positions[~ac['movable']],xyz[~ac['movable']])
    return posed,positions,dict(angles_deg=[float(ANGLES[i]) for i in chosen],accepted_moves=accepted,
        sweeps=sweep+1,ring_checks=checks,ring_rejections=rejected,ordered_moves=history)


def evaluate(model, ac, records, xyz, original_ctx):
    ctx=context(records);metrics=measure(records,ctx,ctx['centers'],ctx['mats'])
    atoms=atomic_metrics(model,ac,xyz,records,ctx)
    atoms['mean_linker_nm']=float(np.mean([b['length_nm'] for b in atoms['linker_bonds']]))
    metrics.update(backbone_displacement_nm=float(np.linalg.norm(ctx['beads']-original_ctx['beads'],axis=1).max()),
       max_slab_displacement_nm=float(np.linalg.norm(ctx['centers']-original_ctx['centers'],axis=1).max()),
       attachment_displacement_nm=0.,max_atom_displacement_nm=float(np.linalg.norm(xyz-ac['xyz'],axis=1).max()))
    return dict(metrics=metrics,atomic=atoms,slab_centers=ctx['centers'].tolist(),
        slab_quaternions=[r['slab_quaternion'] for r in records],backbone_positions=ctx['beads'].tolist(),
        loop_atom_positions=xyz[ac['movable']].tolist())


def run(out,verify=False,pilot=False):
    recipe=json.loads((out/'process.json').read_text())
    assert recipe['user_grant']=='A/B testing authorized — outward from the ellipse center'
    paths=sorted((out/'inputs').glob('*.nadoc'))
    if pilot:paths=[p for p in paths if p.stem in ('loop-6-forward-bp40','loop-6-reverse-bp40','loop-30-forward-bp40','loop-30-forward-bp43','loop-80-forward-bp40','loop-80-reverse-bp30')]
    summaries=[]
    for path in paths:
        original=path.read_bytes();design=Design.model_validate_json(original);proof=audit(design)
        records=_geometry_for_design(design);ctx=context(records)
        assert all(loop.aspect_ratio==3 and loop.rotation_deg==0 for s in design.strands for loop in s.loops)
        model=build_atomistic_model(design,strand_loop_display=True);ac=atom_context(model,records)
        result={'current':evaluate(model,ac,records,ac['xyz'],ctx)};eligible=[];trials=[]
        for offset in OFFSETS:
            try:posed,center=radial_pose(records,ctx,offset)
            except ValueError as e:
                trials.append(dict(offset_nm=offset,status='infeasible',reason=str(e)));continue
            new=context(posed);xyz=atoms_for_pose(ac,ctx,new)
            # Both attachment residues and the surrounding design are immutable.
            for i in range(len(records)):
                if i not in ctx['loops']:assert records[i]==posed[i]
            name=f'radial_{offset:.2f}';v=evaluate(model,ac,posed,xyz,ctx)
            v['offset_nm']=offset;v['ellipse_center']=center.tolist();result[name]=v
            c=v['atomic']['by_group'];score=(c['loop'],c['parent_helix']+c['other_helix'],len(v['atomic']['ring_piercings']),offset)
            trials.append(dict(offset_nm=offset,status='evaluated',score=score))
            if offset>.5:eligible.append((score,name,posed,xyz))
        _,selected,posed,xyz=min(eligible,key=lambda item:item[0])
        fitted,newxyz,search=optimize_rotations(model,ac,xyz,posed,context(posed))
        result['optimized']=evaluate(model,ac,fitted,newxyz,ctx);result['optimized']['search']=search
        result['optimized']['selected_offset']=selected
        before=result[selected]['atomic'];after=result['optimized']['atomic']
        for group in ('parent_helix','other_helix','loop'):
            assert after['by_group'][group]<=before['by_group'][group]
            depth=lambda a:sum(-c['gap_nm']-.04 for c in a['contacts'] if c['group']==group)
            assert depth(after)<=depth(before)+1e-8
        for a,b in zip(before['linker_bonds'],after['linker_bonds']):assert b['length_nm']<=a['length_nm']+1e-10
        hit=lambda h:(tuple(h['bond_serials']),tuple(h['ring_serials']))
        assert {hit(h) for h in after['ring_piercings']}<={hit(h) for h in before['ring_piercings']}
        for v in result.values():
            for metric in ('metrics','atomic'):
                key=lambda c:(c.get('kind'),c['a'],c['b'])
                first={key(c) for c in result['current'][metric]['contacts']};last={key(c) for c in v[metric]['contacts']}
                v[metric].update(removed_contacts=len(first-last),introduced_contacts=len(last-first))
            first={hit(h) for h in result['current']['atomic']['ring_piercings']};last={hit(h) for h in v['atomic']['ring_piercings']}
            v['atomic'].update(introduced_piercings=len(last-first),removed_piercings=len(first-last))
        first=records[ctx['loops'][0]]
        value=dict(label=LABEL,case=path.stem,input_sha256=digest(path),proof=proof,records=records,length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],loop_indices=ctx['loops'],near_indices=ctx['loops'],anchor_index=ctx['anchor'],following_index=ctx['following'],variants=result,offset_trials=trials,
          atoms=[dict(name=a.name,record=int(ac['ri'][i]),element=a.element) for i,a in enumerate(model.atoms)],atom_positions=ac['xyz'].tolist(),atom_bonds=model.bonds,loop_atom_indices=np.flatnonzero(ac['movable']).tolist())
        encoded=pack(value);target=out/'cases'/f'{path.stem}.json.gz'
        if verify:assert gzip.decompress(target.read_bytes())==encoded,path.stem
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f:f.write(encoded)
        assert path.read_bytes()==original
        summaries.append(dict(case=path.stem,length=len(ctx['loops']),selected_offset=selected,variants={k:dict(display=v['metrics']['by_group'],atomic=v['atomic']['by_group'],piercings=len(v['atomic']['ring_piercings']),introduced_piercings=v['atomic']['introduced_piercings'],mean_linker_nm=v['atomic']['mean_linker_nm'],max_linker_nm=v['atomic']['max_linker_nm']) for k,v in result.items()}))
        if len(summaries)%7==0 or pilot:print(f'{len(summaries)}/{len(paths)} {path.stem} -> {selected}',flush=True)
    name=('pilot-' if pilot else '')+('replay.json' if verify else 'summary.json')
    (out/name).write_text(json.dumps(dict(status='verified',cases=len(summaries),tolerance=0) if verify else summaries,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--verify',action='store_true');p.add_argument('--pilot',action='store_true');a=p.parse_args();run(a.output.resolve(),a.verify,a.pilot)
