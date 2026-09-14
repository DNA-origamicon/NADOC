"""Bounded sequential EOS allocations; never overwrite or infer convergence.

Each invocation owns one output directory and runs one simulation at a time.
It records the complete requested plan before launching, and refuses unfinished
or mismatched existing runs. Further allocation requires convergence analysis.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from experiments.peg_chudoba.analyze_npt import analyze


def make_plan(args):
    targets=json.loads((Path(__file__).parent/'reference/published_targets.json').read_text())['osmotic_pressure']
    plan=[]
    for target in sorted(targets,key=lambda r:(r['n'],r['temperature_K'],r['pressure_kpa'])):
        n,t=target['n'],target['temperature_K']
        pressure=min([1,10,20,50,100,200,1000],key=lambda p:abs(p/target['pressure_kpa']-1))
        if abs(pressure/target['pressure_kpa']-1)>.02:raise ValueError(target)
        if n not in args.lengths or t not in args.temperatures or pressure not in args.pressures:continue
        c=target['concentration_g_per_l']
        delta=.04 if c<30 else (.015 if c<150 else (.003 if t==294 else .001))
        for seed in args.seeds:
            factor={0:.85,1:1.,2:1.15}[seed%3]
            plan.append(dict(n=n,chains=108,temperature=t,pressure_kpa=pressure,seed=seed,
                concentration=c*factor,initial_concentration_factor=factor,
                published_concentration_g_per_l=c,volume_delta=delta,pivot_prob=min(.01,1.5/n),
                steps=args.sweeps,sampling='npt',cutoff=args.cutoff,list_type='cells',
                name=f'n{n}_t{t:g}_p{pressure:g}_s{seed}'))
    if not plan:raise ValueError('No published states match the requested filters')
    return plan


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cutoff',choices=['raw','shifted','zero_tail'],default='zero_tail')
    ap.add_argument('--lengths',type=int,nargs='+',default=[135,455])
    ap.add_argument('--temperatures',type=float,nargs='+',default=[294,371])
    ap.add_argument('--pressures',type=float,nargs='+',default=[1,10,20,50,100,200,1000])
    ap.add_argument('--seeds',type=int,nargs='+',default=[401,402,403])
    ap.add_argument('--sweeps',type=int,default=2000)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--plan-only',action='store_true')
    args=ap.parse_args()
    if args.sweeps<1:ap.error('Sweep allocation must be positive')
    plan=make_plan(args);args.output.mkdir(parents=True,exist_ok=True)
    plan_path=args.output/'plan.json'
    if plan_path.exists():
        if json.loads(plan_path.read_text())['allocations']!=plan:raise RuntimeError('Existing plan differs; use a new output directory')
    else:
        plan_path.write_text(json.dumps(dict(created_unix=time.time(),status='Initial allocations, not convergence targets',
            initialization='Published concentrations only set deliberately offset initial states; they do not alter the Hamiltonian or measured result',
            allocations=plan),indent=2)+'\n')
    if args.plan_only:
        print(f'Wrote {len(plan)} allocations to {plan_path}');return
    results=[]
    for entry in plan:
        directory=args.output/entry['name']
        if directory.exists():
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed':raise RuntimeError(f'Inspect unfinished run: {directory}')
            for key in ('n','chains','temperature','pressure_kpa','seed','concentration','volume_delta','pivot_prob','steps','sampling','cutoff','list_type'):
                if meta.get(key)!=entry[key]:raise RuntimeError(f'Existing settings mismatch: {directory}, {key}')
        else:
            command=[sys.executable,'-m','experiments.peg_chudoba.run_solution','--output',str(directory)]
            for key in ('n','chains','temperature','pressure_kpa','seed','concentration','volume_delta','pivot_prob','steps','sampling','cutoff','list_type'):
                command+=['--'+key.replace('_','-'),str(entry[key])]
            subprocess.run(command,check=True)
        result=analyze(directory);result['directory']=str(directory);results.append(result)
        (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
