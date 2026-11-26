"""Rebuild the authorized production loop policy and independently audit contacts."""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from experiments.loop_offset_comparison import atom_context, atomic_metrics
from experiments.loop_orientation_comparison import context, measure, pack, digest
from scripts.agent_structure_guard import audit


def run(out, verify=False):
    process=json.loads((out/'process.json').read_text())
    assert process['user_instruction']=='Ok, we want to implement the bond optimum and then re-evaluate for clash or pierces.'
    summary=[]
    for path in sorted((out/'inputs').glob('*.nadoc')):
        old=json.loads(gzip.decompress((out/'approved'/f'{path.stem}.json.gz').read_bytes()))
        design=Design.model_validate_json(path.read_text());proof=audit(design)
        assert digest(path)==old['input_sha256']
        records=_geometry_for_design(design);ctx=context(records)
        model=build_atomistic_model(design,strand_loop_display=True);ac=atom_context(model,records);xyz=ac['xyz']
        expected=np.array(old['atom_positions']);expected[old['loop_atom_indices']]=old['variants']['bond_only']['loop_atom_positions']
        np.testing.assert_allclose(xyz,expected,atol=1e-10,rtol=0)
        np.testing.assert_allclose(ctx['beads'],old['variants']['current']['backbone_positions'],atol=1e-12,rtol=0)
        np.testing.assert_allclose(ctx['centers'],old['variants']['current']['slab_centers'],atol=1e-12,rtol=0)
        metrics=measure(records,ctx,ctx['centers'],ctx['mats']);atomic=atomic_metrics(model,ac,xyz,records,ctx)
        lengths=[b['length_nm'] for b in atomic['linker_bonds']]
        atomic['mean_linker_nm']=float(np.mean(lengths))
        before=old['variants']['current']['atomic']
        def piercing(h):return tuple(h['bond_serials']),tuple(h['ring_serials'])
        first={piercing(h) for h in before['ring_piercings']};last={piercing(h) for h in atomic['ring_piercings']}
        atomic['introduced_piercings']=len(last-first);atomic['removed_piercings']=len(first-last)
        for a,b in zip(before['linker_bonds'],atomic['linker_bonds']):
            assert b['length_nm']<=a['length_nm']+1e-10
            b['delta_nm']=b['length_nm']-a['length_nm']
        value=dict(case=path.stem,proof=proof,input_sha256=digest(path),records=records,metrics=metrics,atomic=atomic,
                   approved_atom_max_delta_nm=float(np.max(abs(xyz-expected))))
        target=out/'cases'/f'{path.stem}.json.gz';encoded=pack(value)
        if verify:assert gzip.decompress(target.read_bytes())==encoded
        else:
            with gzip.GzipFile(filename=str(target),mode='wb',mtime=0) as f:f.write(encoded)
        summary.append(dict(case=path.stem,length=old['length'],display=metrics['by_group'],atomic=atomic['by_group'],
            piercings=len(atomic['ring_piercings']),introduced_piercings=atomic['introduced_piercings'],
            mean_linker_nm=atomic['mean_linker_nm'],max_linker_nm=atomic['max_linker_nm'],approved_atom_max_delta_nm=value['approved_atom_max_delta_nm']))
        if len(summary)%21==0:print(f'{len(summary)}/126',flush=True)
    (out/('replay.json' if verify else 'summary.json')).write_text(json.dumps(dict(status='verified',cases=len(summary),tolerance=0) if verify else summary,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--verify',action='store_true');a=p.parse_args();run(a.output.resolve(),a.verify)
