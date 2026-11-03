"""Attribute CUPTI runtime-allocation events to NAMD call stacks (offline)."""
import argparse
import hashlib
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.core.namd_measurements import receipt_qualification
from backend.core.namd_allocation_model import QUALIFIED_ENGINE


def summarize(path,binary):
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    if rows[0].get('subscribe')!=0 or rows[0].get('enable')!=0:
        raise ValueError('CUPTI did not initialize successfully')
    events=[x for x in rows if 'sequence' in x]
    offsets=sorted({a for x in events for a in x.get('namd_offsets',[])})
    output=subprocess.check_output(['addr2line','-C','-f','-e',str(binary),*offsets],text=True).splitlines()
    names={address:output[2*i] for i,address in enumerate(offsets)}
    live={};category_live=defaultdict(int);category_peak=defaultdict(int)
    peak=0;at_peak={};callsite_sizes=defaultdict(set)
    for event in events:
        pointer=event['pointer'];size=event['bytes']
        if event['api'].startswith('cudaMalloc'):
            stack=[names[a] for a in event.get('namd_offsets',[])]
            joined=' '.join(stack)
            if 'CudaTileListKernel' in joined:category='neighbor_tile_lists'
            elif any(n in joined.lower() for n in ('pme','cufft','fft')):category='pme_and_fft'
            elif 'Bonded' in joined:category='bonded'
            elif any(n in joined for n in ('integrate_CUDA','Integrator')):category='integration'
            else:category='other_engine'
            live[pointer]=(category,size);category_live[category]+=size
            relevant=next((a for a in event.get('namd_offsets',[]) if any(n in names[a] for n in ('CudaTileListKernel','CudaPme','CudaCompute'))),None)
            if relevant:callsite_sizes[(relevant,names[relevant])].add(size)
        elif pointer in live:
            category,known=live.pop(pointer);category_live[category]-=known
        for key,value in category_live.items():category_peak[key]=max(category_peak[key],value)
        total=sum(category_live.values())
        if total>peak:peak=total;at_peak=dict(category_live)
        if total!=event['live_bytes']:raise ValueError('Allocation replay disagrees with collector')
    return dict(case=path.parent.name,events=len(events),runtime_allocation_peak_mib=peak/1024**2,
        components_at_total_peak_mib={k:v/1024**2 for k,v in at_peak.items()},
        independent_component_peaks_mib={k:v/1024**2 for k,v in category_peak.items()},
        allocation_sizes_by_callsite=[dict(offset=k[0],function=k[1],bytes=sorted(v)) for k,v in callsite_sizes.items()],
        limitations='Tracks selected CUDA runtime allocations, not driver/context internals or physical residency. Async frees reflect API return. Instrumentation overhead must be measured against uninstrumented runs.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--engine-sha256',default=QUALIFIED_ENGINE,help='Explicit identity for a separate experimental-engine report')
    args=parser.parse_args()
    if hashlib.sha256(args.binary.read_bytes()).hexdigest()!=args.engine_sha256:
        raise ValueError('Symbol binary does not match the qualified report engine')
    reports=[];excluded=[]
    for path in sorted((args.root/'traces').glob('*/allocations.jsonl')):
        result=path.parent/'engine/result.json'
        raw=json.loads(result.read_text()) if result.exists() else {}
        reasons=receipt_qualification(raw,path.parent,engine_sha256=args.engine_sha256)
        if reasons:excluded.append(dict(source=str(path),reasons=reasons));continue
        reports.append(summarize(path,args.binary))
    (args.root/'allocation_report.json').write_text(json.dumps(reports,indent=2)+'\n')
    (args.root/'allocation_exclusions.json').write_text(json.dumps(excluded,indent=2)+'\n')
    for report in reports:
        print(report['case'],round(report['runtime_allocation_peak_mib'],2),report['components_at_total_peak_mib'])
