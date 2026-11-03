"""Post-inference native checks. Does not alter frozen figure predictions."""
import hashlib
import json
from pathlib import Path


def run(predictions, native, output):
    manifest=json.loads((predictions/'frozen-manifest.json').read_text())
    for name,digest in manifest.items():
        if hashlib.sha256((predictions/name).read_bytes()).hexdigest()!=digest:raise ValueError('Prediction manifest mismatch')
    results=[]
    for path in sorted(predictions.glob('*.json')):
        if not path.stem.isdigit():continue
        predicted=json.loads(path.read_text());rid=predicted['id']
        h=max(predicted['hypotheses'],key=lambda h:len(h['tracks']))
        result={'id':rid,'predicted_tracks':len(h['tracks']),'axis':h['axis'],'crossover_check':{k:v for k,v in h.get('crossover_check',{}).items() if k!='junctions'},'checks':[]}
        for ref in sorted((native/str(rid)).glob('*.json')):
            d=json.loads(ref.read_text());helices=[v for v in d['vstrands'] if any(q!=[-1]*4 for q in v['scaf'])]
            check={'reference':ref.name,'scaffold_helices':len(helices),'status':'not registered'}
            if h['axis']==0 and len(h['tracks'])==len(helices) and helices:
                expected=[]
                for helix in helices:
                    signs={q[3]-i for i,q in enumerate(helix['scaf']) if q[2]==helix['num'] and abs(q[3]-i)==1}
                    expected.append(next(iter(signs)) if len(signs)==1 else None)
                check.update(status='conditional comparison: figure order equals stored vstrand order; identity not independently established',
                    matches=sum(t['signed_track_offset']==d for t,d in zip(h['tracks'],expected) if d is not None),
                    mismatches=[i for i,(t,d) in enumerate(zip(h['tracks'],expected)) if d is not None and t['signed_track_offset']!=d],
                    untestable_reference_tracks=sum(d is None for d in expected))
            result['checks'].append(check)
        results.append(result)
    output.write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))


if __name__=='__main__':
    import sys
    run(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
