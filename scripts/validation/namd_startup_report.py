"""Separate startup overshoot from retained RAM/VRAM using engine time markers."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.core.resource_spikes import summarize_startup
from backend.core.namd_measurements import receipt_qualification
from backend.core.namd_allocation_model import QUALIFIED_ENGINE

MIB=1024**2
ALLOCATIONS={'cudaMalloc','cudaMallocManaged','cudaMallocAsync','cudaMallocAsync_ptsz',
             'cudaMallocHost','cudaHostAlloc'}


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def allocation_series(path,start,cutoff,end,binary):
    rows=records(path)
    if any('trace_error' in x for x in rows):
        raise ValueError('Allocation trace contains an accounting error')
    if rows[0].get('subscribe')!=0 or rows[0].get('enable')!=0:
        raise ValueError('CUPTI initialization failed')
    finish=next((x['finished_monotonic_s'] for x in rows if 'finished_monotonic_s' in x),None)
    if finish is None or finish<start+end:
        raise ValueError('Trace does not cover the running window')
    live={};at_startup={};at_peak={};peak=0;points=[(0.,0.)]
    events=[x for x in rows if 'sequence' in x]
    for event in events:
        t=event['monotonic_s']-start
        if t>end:break
        pointer=event['pointer']
        if event['api'] in ALLOCATIONS:
            if pointer in live:raise ValueError('Duplicate live allocation')
            live[pointer]=event
        else:
            live.pop(pointer,None)
        total=sum(x['bytes'] for x in live.values())
        if total!=event['live_bytes']:raise ValueError('Allocation replay disagrees with trace')
        points.append((t,total/MIB))
        if t<=cutoff:at_startup=dict(live)
        if total>peak:peak=total;at_peak=dict(live)
    points.append((end,points[-1][1]))
    startup_bytes=sum(x['bytes'] for x in at_startup.values())
    retained=sum(x['bytes'] for p,x in at_startup.items()
                 if p in live and live[p]['sequence']==x['sequence'])
    # Attribute the simultaneous peak, not a sum of unrelated component peaks.
    offsets=sorted({a for x in at_peak.values() for a in x.get('namd_offsets',[])})
    names={}
    if offsets:
        lines=subprocess.check_output(['addr2line','-C','-f','-e',str(binary),*offsets],text=True).splitlines()
        names={a:lines[2*i] for i,a in enumerate(offsets)}
    components=defaultdict(int)
    for x in at_peak.values():
        stack=' '.join(names[a] for a in x.get('namd_offsets',[]))
        if 'CudaTileListKernel' in stack:category='neighbor_tiles'
        elif any(n in stack.lower() for n in ['pme','cufft','fft']):category='pme_fft'
        elif 'Bonded' in stack:category='bonded'
        elif any(n in stack for n in ['integrate_CUDA','Integrator']):category='integration'
        else:category='other'
        components[category]+=x['bytes']
    return points,dict(events=len(events),startup_live_mib=startup_bytes/MIB,
        startup_still_live_at_running_end_mib=retained/MIB,
        startup_retained_fraction=retained/startup_bytes if startup_bytes else None,
        components_at_peak_mib={k:v/MIB for k,v in components.items()},
        limitation='Selected successful runtime APIs only; no driver/context memory. Pinned host bytes overlap process RSS.')


def report(root,results_file='plan_results.json',engine_sha256=QUALIFIED_ENGINE):
    rows=[];excluded=[]
    for item in json.loads((root/results_file).read_text()):
        directory=root/'tests'/item['id'];engine=directory/'engine'
        result=json.loads((engine/'result.json').read_text())
        reasons=receipt_qualification({**result,'output_validation':item.get('output_validation')},
            directory,engine_sha256=engine_sha256)
        if reasons:
            excluded.append(dict(id=item['id'],reasons=reasons))
            continue
        invocation=json.loads((engine/'invocation.json').read_text())
        start=invocation['start_monotonic_s'];markers=result['markers']
        cutoff=markers['first_timing_s'];end=markers['last_energy_s']
        if end-cutoff<4:raise ValueError('At least four seconds of running observation required')
        samples=records(engine/'samples.jsonl')
        gpu=json.loads((engine/'gpu_samples.json').read_text())
        series={'process_ram':[(x['s'],x['rss_mib']) for x in samples],
                'process_vram':[(x['monotonic_s']-start,x['gpu_mib']) for x in gpu]}
        binary=next(Path(x) for x in invocation['command'] if Path(x).name=='namd3')
        details={}
        for name,file in [('requested_device','allocations.jsonl'),('requested_host_pinned','host_allocations.jsonl')]:
            series[name],details[name]=allocation_series(directory/file,start,cutoff,end,binary)
        resources={key:summarize_startup(points,startup_end_s=cutoff,
            running_start_s=cutoff+1,running_end_s=end) for key,points in series.items()}
        rows.append(dict(id=item['id'],completed=True,elapsed_s=result['elapsed_s'],
            startup_marker='first TIMING log line observed',resources=resources,
            allocation_details=details,output_validation=item.get('output_validation'),
            full_run_peak_ram_mib=result['peak_rss_mib'],full_run_peak_vram_mib=result['gpu_peak_mib']))
    return dict(schema='namd-startup-v2',rows=rows,excluded=excluded,engine_sha256=engine_sha256,
        definition='Startup ends at first TIMING; running begins one second later and ends at last ENERGY, before exit. Raw excess and threshold classification are both reported.',
        limitations=['Polling timestamps approximate engine events.','Physical RAM/VRAM samples cannot exclude peaks shorter than their measured gaps.','Pinned host allocation totals are part of RSS, not extra RAM.','No universal completion guarantee or reduction of production admission limits.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--results',default='plan_results.json')
    parser.add_argument('--engine-sha256',default=QUALIFIED_ENGINE,help='Explicit matching engine identity for a separate experimental report')
    args=parser.parse_args()
    result=report(args.root,args.results,args.engine_sha256)
    (args.root/'startup_report.json').write_text(json.dumps(result,indent=2)+'\n')
    for row in result['rows']:
        print(row['id'],[(k,round(v['startup_peak_mib'],3),round(v['running_peak_mib'],3),
            v['classification']) for k,v in row.get('resources',{}).items()])
