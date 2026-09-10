"""Run a frozen plan of independent EOS continuations from completed endpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from experiments.peg_chudoba.analyze_npt import analyze


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cutoff',choices=['raw','shifted','zero_tail'],default='zero_tail')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--steps',type=int,default=20000)
    ap.add_argument('--n',type=int,default=135)
    ap.add_argument('--temperature',type=float,default=294)
    ap.add_argument('--pressure-kpa',type=float,default=1)
    ap.add_argument('--plan-only',action='store_true')
    args=ap.parse_args()
    if args.steps<1:ap.error('Positive continuation allocation required')
    root=Path(__file__).parent;args.output.mkdir(parents=True,exist_ok=True)
    settings=dict(cutoff=args.cutoff,n=args.n,temperature=args.temperature,pressure_kpa=args.pressure_kpa,steps=args.steps)
    plan_path=args.output/'plan.json'
    if plan_path.exists():
        saved=json.loads(plan_path.read_text())
        saved['settings'].setdefault('cutoff','raw')
        if saved['settings']!=settings:raise ValueError('Existing plan differs')
        plan=saved['allocations']
    else:
        report=json.loads((root/'eos_comparison.json').read_text())
        matches=[r for r in report['estimates'] if r['n']==args.n and r['temperature_K']==args.temperature
                 and r['pressure_kpa']==args.pressure_kpa and r['sampling']=='npt' and r['cutoff']==args.cutoff]
        if len(matches)!=1 or len(matches[0]['replica_ids'])<3:raise ValueError('Require a complete independent pilot cohort')
        row=matches[0]
        if not row['extension_recommended']:raise ValueError('No extension recommended by current diagnostics')
        plan=[]
        for source_name in row['directories']:
            source=Path(source_name).resolve();meta=json.loads((source/'run.json').read_text())
            if meta['status']!='completed':raise ValueError('Source not completed')
            replica=meta.get('replica_id',meta['seed']);generation=meta.get('sampling_generation',0)+1
            plan.append(dict(source=str(source),source_sha256=hashlib.sha256((source/'last_conf.dat').read_bytes()).hexdigest(),
                replica_id=replica,sampling_generation=generation,seed=replica+1000*generation,
                name=f'n{args.n}_t{args.temperature:g}_p{args.pressure_kpa:g}_r{replica}_g{generation}',
                volume_delta=meta.get('volume_delta',.04),pivot_prob=meta.get('pivot_prob',min(.01,1.5/args.n))))
        if len({p['replica_id'] for p in plan})!=len(plan):raise ValueError('Duplicate replica ancestry')
        plan_path.write_text(json.dumps(dict(created_unix=time.time(),settings=settings,allocations=plan,
            status='Bounded continuation allocations; fresh convergence analysis required',
            triggering_diagnostics={k:v for k,v in row.items() if 'rhat' in k or 'effective' in k}),indent=2)+'\n')
    if args.plan_only:return
    results=[]
    for entry in plan:
        source=Path(entry['source'])
        if hashlib.sha256((source/'last_conf.dat').read_bytes()).hexdigest()!=entry['source_sha256']:
            raise ValueError('Saved source endpoint changed')
        directory=args.output/entry['name']
        if directory.exists():
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed':raise ValueError(f'Inspect unfinished run {directory}')
            expected=dict(settings,seed=entry['seed'],replica_id=entry['replica_id'],sampling_generation=entry['sampling_generation'],sampling='npt')
            if any(meta.get(k)!=v for k,v in expected.items()):raise ValueError('Existing continuation settings differ')
        else:
            command=[sys.executable,'-m','experiments.peg_chudoba.run_solution','--sampling','npt',
                     '--initial-run',str(source),'--output',str(directory)]
            for k,v in dict(settings,seed=entry['seed'],volume_delta=entry['volume_delta'],pivot_prob=entry['pivot_prob']).items():
                command+=['--'+k.replace('_','-'),str(v)]
            subprocess.run(command,check=True)
        result=analyze(directory);result['directory']=str(directory);results.append(result)
        (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
