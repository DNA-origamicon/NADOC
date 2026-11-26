"""Verify and visualize the user-selected all-base flip / quarter-turn tip layout."""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.strand_loop_geometry import loop_base_rotation_angles
from experiments.loop_orientation_comparison import context, digest, measure, pack
from scripts.agent_structure_guard import audit


def run(source, out, verify=False):
    assert '180' in json.loads((out/'process.json').read_text())['user_instruction']
    (out/'cases').mkdir(exist_ok=True)
    summaries=[]
    for path in sorted((source/'cases').glob('*.json.gz')):
        baseline=json.loads(gzip.decompress(path.read_bytes()))
        case=baseline['case']
        design_path=source/'inputs'/f'{case}.nadoc'
        source_hash=digest(design_path)
        assert source_hash==baseline['input_sha256']
        design=Design.model_validate_json(design_path.read_text())
        proof=audit(design)
        current=_geometry_for_design(design)
        old=baseline['records'];ctx=context(old);newctx=context(current)
        assert len(current)==len(old)
        loops=set(ctx['loops'])
        for i,(a,b) in enumerate(zip(old,current)):
            assert a['backbone_position']==b['backbone_position']
            if i not in loops: assert a==b
            else:
                for key in set(a)-{'base_position','slab_position','base_normal','slab_quaternion','placement_source'}:
                    assert a[key]==b[key]
        chain=[ctx['anchor'],*ctx['loops'],ctx['following']]
        angles=loop_base_rotation_angles(ctx['beads'][chain],old[ctx['anchor']]['axis_tangent'])
        metrics=measure(current,newctx,newctx['centers'],newctx['mats'])
        displacement=np.linalg.norm(newctx['centers']-ctx['centers'],axis=1)
        metrics['max_slab_displacement_nm']=float(displacement.max())
        metrics['backbone_displacement_nm']=0.
        metrics['attachment_displacement_nm']=0.
        metrics['per_base_displacement_nm']=[{'index':i,'loop_ordinal':old[i]['loop_order'],
            'angle_deg':float(angle),'displacement_nm':float(displacement[i])} for i,angle in zip(ctx['loops'],angles)]
        initial={(c['kind'],c['a'],c['b']) for c in baseline['variants']['current']['metrics']['contacts']}
        final={(c['kind'],c['a'],c['b']) for c in metrics['contacts']}
        metrics['removed_contacts']=len(initial-final);metrics['introduced_contacts']=len(final-initial)
        metrics['tip_ordinals']=[old[i]['loop_order'] for i,angle in zip(ctx['loops'],angles) if angle==90]
        variant={'metrics':metrics,'angles':{str(i):float(angle) for i,angle in zip(ctx['loops'],angles)},
                 'slab_centers':newctx['centers'].tolist(),'slab_quaternions':[n['slab_quaternion'] for n in current]}
        assert digest(design_path)==source_hash
        baseline['variants']['all_flip_tip90']=variant
        baseline['near_indices']=ctx['loops']  # Viewer overlay includes ALL modified bases.
        baseline['production_proof']=proof
        baseline['label']='User-selected v2 layout; CG-only, no atomistic clearance claim.'
        encoded=pack(baseline);target=out/'cases'/path.name
        if verify: assert gzip.decompress(target.read_bytes())==encoded,case
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as stream:stream.write(encoded)
        summaries.append({'case':case,'length':baseline['length'],'direction':baseline['direction'],'bp':baseline['bp'],
                         'before':baseline['variants']['current']['metrics'],'after':metrics})
    if verify:
        (out/'replay.json').write_text(json.dumps({'status':'verified','cases':len(summaries),
            'comparison':'Full evidence identical after independent recorded-input replay and production geometry rebuild',
            'backbone_and_attachment_max_displacement_nm':0,'nonloop_geometry':'exactly preserved'},indent=2)+'\n')
    else: (out/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    print(json.dumps({'cases':len(summaries),'loop_self_display_contacts':sum(c['after']['by_group']['loop'] for c in summaries),
        'base_contacts_before':sum(c['before']['total_display_contacts'] for c in summaries),
        'base_contacts_after':sum(c['after']['total_display_contacts'] for c in summaries),
        'verified':verify},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--verify',action='store_true')
    args=parser.parse_args();run(args.source.resolve(),args.output.resolve(),args.verify)
