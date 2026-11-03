"""Freeze figure-only direction predictions; never opens native references."""
import hashlib
import json
from pathlib import Path
from backend.core.image_direction_inference import track_hypotheses, crossover_corroboration


def run(source, output):
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for path in sorted(source.glob('*/evidence.json')):
        raw=path.read_bytes(); evidence=json.loads(raw)
        result={'id':int(path.parent.name),'evidence_sha256':hashlib.sha256(raw).hexdigest(),
                'hypotheses':[track_hypotheses(evidence,axis) for axis in (0,1)]}
        for h in result['hypotheses']:
            h['crossover_check']=crossover_corroboration(evidence,h)
        (output/(path.parent.name+'.json')).write_text(json.dumps(result,indent=2))
        results.append({'id':result['id'],'tracks_by_axis':[len(h['tracks']) for h in result['hypotheses']],
                        'conflicts_by_axis':[sum(t['signed_track_offset'] is None for t in h['tracks']) for h in result['hypotheses']]})
    (output/'summary.json').write_text(json.dumps(results,indent=2))
    (output/'frozen-manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.json') if p.name!='frozen-manifest.json'},indent=2))
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    import sys
    run(Path(sys.argv[1]),Path(sys.argv[2]))
