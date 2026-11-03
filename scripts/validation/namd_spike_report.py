"""Characterize retained process samples and timestamped CUDA allocation events."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from backend.core.resource_spikes import summarize_series
from backend.core.namd_measurements import receipt_qualification
from backend.core.namd_allocation_model import QUALIFIED_ENGINE


def report(root,archive):
    rows=[];excluded=[];eligible=set()
    paths=sorted(archive.glob('long_*/samples.jsonl'))+sorted((root/'probes').glob('*/engine/samples.jsonl'))
    paths+=sorted((root/'engine').glob('*/samples.jsonl'))
    for p in paths:
        if not (p.parent/'result.json').exists():continue
        result=json.loads((p.parent/'result.json').read_text())
        directory=p.parent.parent if p.parent.name=='engine' else p.parent
        reasons=receipt_qualification(result,directory,engine_sha256=QUALIFIED_ENGINE)
        if reasons:
            excluded.append(dict(source=str(p),reasons=reasons));continue
        samples=[json.loads(s) for s in p.read_text().splitlines()]
        values={key:[] for key in ('rss_mib','gpu_mib')}
        for sample in samples:
            for key in values:
                value=sample.get(key)
                if value is None and key=='rss_mib' and sample.get('rss') is not None:value=sample['rss']/1024**2
                if value is not None:values[key].append((sample['s'],value))
        # Trim shutdown; process RSS/VRAM dropping to zero is not steady state.
        times=[t for t,v in values['rss_mib'] if v>128]
        if not times:
            excluded.append(dict(source=str(p),reasons=['no valid live process samples']));continue
        end=max(times)-1
        values={key:[(t,v) for t,v in data if t<=end] for key,data in values.items()}
        eligible.add(directory)
        rows.append(dict(id=p.parent.parent.name if p.parent.name=='engine' else p.parent.name,
            scope='process samples',source=str(p),completed=result['completed'],
            termination_errors=result.get('errors'),elapsed_s=result['elapsed_s'],
            resources={key:summarize_series(data,warmup_s=30 if 'long_' in p.parent.name else 5)
                       for key,data in values.items() if len(data)>1 and data[-1][0]>data[0][0]}))
    for p in sorted((root/'probes').glob('*/allocations.jsonl')):
        if p.parent not in eligible:continue
        records=[json.loads(s) for s in p.read_text().splitlines()]
        events=[e for e in records if 'sequence' in e and 'monotonic_s' in e]
        if not events:continue
        first=events[0]['monotonic_s']
        # Never reconstruct a previous boot's clock relation from today's clock.
        finish=next((e['finished_monotonic_s'] for e in records if 'finished_monotonic_s' in e),None)
        endpoint='tracer termination'
        if finish is None:
            excluded.append(dict(source=str(p),reasons=['missing tracer termination timestamp']));continue
        end=finish-1
        points=[(e['monotonic_s']-first,e['live_bytes']/1024**2) for e in events if e['monotonic_s']<=end]
        if not points or end<=first:
            excluded.append(dict(source=str(p),reasons=['no usable allocation interval']));continue
        # Close the observation interval even if the allocation set is stable.
        points.append((end-first,points[-1][1]))
        result=summarize_series(points,warmup_s=5)
        result['endpoint_basis']=endpoint
        result['limitation']='Allocation events cover selected runtime APIs; not all device memory or physical residency. Async frees reflect API return.'
        rows.append(dict(id=p.parent.name,scope='CUDA runtime allocation events',source=str(p),resources={'cuda_requested_mib':result}))
    return dict(schema='namd-spikes-v2',definition='above time-weighted post-warmup median + max(64 MiB, 5%); shutdown excluded',rows=rows,excluded=excluded,
        interpretation='Only successful output-validated runs with matching launch-time engine identity enter summaries. Missing GPU samples remain missing. Event-rate estimates apply only to observed intervals.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--archive',type=Path,default=ROOT/'.development-artifacts/namd-qualification-20261101')
    args=parser.parse_args();result=report(args.root,args.archive)
    (args.root/'spike_report.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in result['rows']:
        print(r['id'],r['scope'],[(k,round(v['observed_s']),v['episode_count'],round(v['peak_mib']/v['median_mib'],3)) for k,v in r['resources'].items()])
