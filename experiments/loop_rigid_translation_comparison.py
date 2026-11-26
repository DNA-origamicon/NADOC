"""Isolated rigid loop translation, with explicitly stretched attachment bonds."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import numpy as np
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from experiments.loop_offset_comparison import atom_context
from experiments.loop_orientation_comparison import context, digest, pack, LABEL
from experiments.loop_radial_comparison import evaluate
from scripts.agent_structure_guard import audit

OFFSETS=(.25,.50,.75,1.,1.5,2.,3.)


def run(out,verify=False):
    recipe=json.loads((out/'process.json').read_text())
    assert recipe['user_grant']=='A/B testing authorized for rigid ellipse translation with stretched attachments'
    summaries=[]
    for path in sorted((out/'inputs').glob('*.nadoc')):
        original=path.read_bytes();design=Design.model_validate_json(original);proof=audit(design)
        records=_geometry_for_design(design);ctx=context(records)
        model=build_atomistic_model(design,strand_loop_display=True);ac=atom_context(model,records)
        anchor=records[ctx['anchor']];axis=np.array(anchor['axis_tangent']);axis/=np.linalg.norm(axis)
        outward=-np.array(anchor['base_normal']);outward-=axis*np.dot(axis,outward);outward/=np.linalg.norm(outward)
        result={'current':evaluate(model,ac,records,ac['xyz'],ctx)}
        for offset in OFFSETS:
            posed=deepcopy(records);delta=offset*outward;xyz=ac['xyz'].copy();xyz[ac['movable']]+=delta
            for i in ctx['loops']:
                for field in ('backbone_position','base_position','slab_position'):posed[i][field]=(np.array(records[i][field])+delta).tolist()
                assert posed[i]['slab_quaternion']==records[i]['slab_quaternion']
            for i in range(len(records)):
                if i not in ctx['loops']:assert posed[i]==records[i]
            np.testing.assert_array_equal(xyz[~ac['movable']],ac['xyz'][~ac['movable']])
            np.testing.assert_allclose(xyz[ac['movable']]-ac['xyz'][ac['movable']],np.broadcast_to(delta,xyz[ac['movable']].shape),atol=1e-12)
            v=evaluate(model,ac,posed,xyz,ctx);v.update(offset_nm=offset,translation_vector_nm=delta.tolist());result[f'shift_{offset:.2f}']=v
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
                if ac['movable'][b['a']] and ac['movable'][b['b']]:assert abs(a['length_nm']-b['length_nm'])<1e-12
                else:roots.append(b)
            assert len(roots)==2;v['atomic']['attachment_bonds']=roots
            assert v['atomic']['by_group']['loop']==result['current']['atomic']['by_group']['loop']
        first=records[ctx['loops'][0]]
        value=dict(label=LABEL,case=path.stem,input_sha256=digest(path),proof=proof,records=records,length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],loop_indices=ctx['loops'],near_indices=ctx['loops'],anchor_index=ctx['anchor'],following_index=ctx['following'],variants=result,
            atoms=[dict(name=a.name,record=int(ac['ri'][i]),element=a.element) for i,a in enumerate(model.atoms)],atom_positions=ac['xyz'].tolist(),atom_bonds=model.bonds,loop_atom_indices=np.flatnonzero(ac['movable']).tolist())
        encoded=pack(value);target=out/'cases'/f'{path.stem}.json.gz'
        if verify:assert gzip.decompress(target.read_bytes())==encoded,path.stem
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f:f.write(encoded)
        assert path.read_bytes()==original
        summaries.append(dict(case=path.stem,length=len(ctx['loops']),direction=first['direction'],bp=first['bp_index'],variants={k:dict(display=v['metrics']['by_group'],atomic=v['atomic']['by_group'],piercings=len(v['atomic']['ring_piercings']),introduced_piercings=v['atomic']['introduced_piercings'],mean_linker_nm=v['atomic']['mean_linker_nm'],max_linker_nm=v['atomic']['max_linker_nm'],attachment_lengths_nm=[b['length_nm'] for b in v['atomic']['attachment_bonds']]) for k,v in result.items()}))
        if len(summaries)%7==0:print(f'{len(summaries)}/126 {path.stem}',flush=True)
    (out/('replay.json' if verify else 'summary.json')).write_text(json.dumps(dict(status='verified',cases=len(summaries),tolerance=0) if verify else summaries,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--verify',action='store_true');a=p.parse_args();run(a.output.resolve(),a.verify)
