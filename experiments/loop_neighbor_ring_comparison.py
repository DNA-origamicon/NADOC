"""Isolated ring-focused rotations of the selected +1 nm loop candidate."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from experiments.loop_offset_comparison import atom_context
from experiments.loop_orientation_comparison import context, digest, pack, LABEL
from experiments.loop_radial_comparison import evaluate
from experiments.loop_bond_rotation_comparison import ANGLES, ZERO, contact_guard, piercing_keys
from scripts.agent_structure_guard import audit
TARGET=.1600

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


def run(out,verify=False):
    recipe=json.loads((out/'process.json').read_text())
    assert recipe['user_grant']=='A/B testing authorized'
    summaries=[]
    for path in sorted((out/'inputs').glob('*.nadoc')):
        original=path.read_bytes();design=Design.model_validate_json(original);proof=audit(design)
        records=_geometry_for_design(design);ctx=context(records)
        model=build_atomistic_model(design,strand_loop_display=True);ac=atom_context(model,records)
        anchor=records[ctx['anchor']];axis=np.array(anchor['axis_tangent']);axis/=np.linalg.norm(axis)
        outward=-np.array(anchor['base_normal']);outward-=axis*np.dot(axis,outward);outward/=np.linalg.norm(outward)
        # The working baseline is the previously reviewed additional +1 nm shift.
        for i in ctx['loops']:
            for field in ('backbone_position','base_position','slab_position'):records[i][field]=(np.array(records[i][field])+outward).tolist()
        ac['xyz'][ac['movable']]+=outward
        ctx=context(records)
        result={'current':evaluate(model,ac,records,ac['xyz'],ctx)}
        for name,growth in [('strict',0.),('ring_priority',.10)]:
            posed,xyz,search=optimize_rotations(model,ac,ac['xyz'],records,ctx,growth)
            v=evaluate(model,ac,posed,xyz,ctx);v.update(search=search,max_linker_growth_budget_nm=growth);result[name]=v
            assert v['backbone_positions']==result['current']['backbone_positions']
            assert v['slab_centers']==result['current']['slab_centers']
            for a,b in zip(result['current']['atomic']['linker_bonds'],v['atomic']['linker_bonds']):assert b['length_nm']<=a['length_nm']+growth+1e-10
            assert piercing_keys(model,xyz)<=piercing_keys(model,ac['xyz'])
            for group in ('parent_helix','other_helix','loop'):
                assert v['atomic']['by_group'][group]<=result['current']['atomic']['by_group'][group]
                depth=lambda v:sum(-c['gap_nm']-.04 for c in v['atomic']['contacts'] if c['group']==group)
                assert depth(v)<=depth(result['current'])+1e-8
        hit=lambda h:(tuple(h['bond_serials']),tuple(h['ring_serials']))
        for v in result.values():
            for metric in ('metrics','atomic'):
                key=lambda c:(c.get('kind'),c['a'],c['b'])
                before={key(c) for c in result['current'][metric]['contacts']};after={key(c) for c in v[metric]['contacts']}
                v[metric].update(removed_contacts=len(before-after),introduced_contacts=len(after-before))
            before={hit(h) for h in result['current']['atomic']['ring_piercings']};after={hit(h) for h in v['atomic']['ring_piercings']}
            v['atomic'].update(introduced_piercings=len(after-before),removed_piercings=len(before-after))
            roots=[]
            for a,b in zip(result['current']['atomic']['linker_bonds'],v['atomic']['linker_bonds']):
                if not (ac['movable'][b['a']] and ac['movable'][b['b']]):roots.append(b)
            assert len(roots)==2;v['atomic']['attachment_bonds']=roots

        first=records[ctx['loops'][0]]
        value=dict(label=LABEL,case=path.stem,input_sha256=digest(path),proof=proof,records=records,length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],loop_indices=ctx['loops'],near_indices=ctx['loops'],anchor_index=ctx['anchor'],following_index=ctx['following'],variants=result,
            atoms=[dict(name=a.name,record=int(ac['ri'][i]),element=a.element) for i,a in enumerate(model.atoms)],atom_positions=ac['xyz'].tolist(),atom_bonds=model.bonds,loop_atom_indices=np.flatnonzero(ac['movable']).tolist())
        encoded=pack(value);target=out/'cases'/f'{path.stem}.json.gz'
        if verify:assert gzip.decompress(target.read_bytes())==encoded,path.stem
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f:f.write(encoded)
        assert path.read_bytes()==original
        summaries.append(dict(case=path.stem,length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],variants={k:dict(display=v['metrics']['by_group'],atomic=v['atomic']['by_group'],piercings=len(v['atomic']['ring_piercings']),introduced_piercings=v['atomic']['introduced_piercings'],mean_linker_nm=v['atomic']['mean_linker_nm'],max_linker_nm=v['atomic']['max_linker_nm'],attachment_lengths_nm=[b['length_nm'] for b in v['atomic']['attachment_bonds']]) for k,v in result.items()}))
        if len(summaries)%7==0:print(f'{len(summaries)}/84 {path.stem}',flush=True)
    (out/('replay.json' if verify else 'summary.json')).write_text(json.dumps(dict(status='verified',cases=len(summaries),tolerance=0) if verify else summaries,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--verify',action='store_true');a=p.parse_args();run(a.output.resolve(),a.verify)
