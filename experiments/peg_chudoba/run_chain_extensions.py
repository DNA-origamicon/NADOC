"""Extend flagged chain states from saved endpoints without duplicating replicas."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from experiments.peg_chudoba.analyze_chain import analyze


def reserved_chain_generations(runs):
    """Existing frozen plans reserve generations, even if their driver stopped.

    A stopped plan needs explicit recovery rather than duplicate allocation.
    This is not a claim that the plan's processes are live.
    """
    reserved={}
    for path in runs.glob('*/plan.json'):
        saved=json.loads(path.read_text())
        for entry in saved.get('allocations',[]):
            if not all(k in entry for k in ('n','temperature','generation','replica_id')):continue
            key=(saved.get('cutoff','raw'),entry['n'],entry['temperature'],entry['generation'])
            reserved.setdefault(key,set()).add(str(path))
    return reserved


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cutoff',choices=['raw','shifted','zero_tail'],default='zero_tail')
    ap.add_argument('--plan-only',action='store_true')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--report',type=Path,default=Path(__file__).parent/'campaign_comparison.json')
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    plan_file=args.output/'plan.json'
    if plan_file.exists():
        saved=json.loads(plan_file.read_text())
        if saved.get('cutoff','raw')!=args.cutoff:raise ValueError('Existing plan uses a different cutoff convention')
        plan=saved['allocations']
    else:
        plan=[];skipped=[]
        reserved=reserved_chain_generations(Path(__file__).parent/'runs')
        for row in json.loads(args.report.read_text())['comparisons']:
            if row['cutoff']!=args.cutoff or not row['extension_recommended']:continue
            key=(args.cutoff,row['n'],row['temperature_K'],row.get('sampling_generation',0)+1)
            if key in reserved:
                skipped.append(dict(n=key[1],temperature_K=key[2],generation=key[3],plans=sorted(reserved[key])))
                continue
            for source_name in row['directories']:
                source=Path(source_name);prior=json.loads((source/'run.json').read_text())
                replica=prior.get('replica_id',prior['seed']);generation=prior.get('sampling_generation',0)+1
                factor=max(2,math.ceil(200/max(1,row['minimum_seed_effective_samples'])))
                steps=min(2000000,prior['steps']*factor)
                plan.append(dict(n=row['n'],temperature=row['temperature_K'],replica_id=replica,generation=generation,
                    seed=replica+1000*generation,steps=steps,source=str(source),
                    name=f"n{row['n']}_t{row['temperature_K']:g}_r{replica}_g{generation}",
                    reason=dict(rhat=row['rank_folded_split_rhat'],minimum_effective_samples=row['minimum_seed_effective_samples'])))
        plan_file.write_text(json.dumps(dict(created_unix=time.time(),cutoff=args.cutoff,status='Extensions require fresh convergence assessment',skipped_existing_plan_states=skipped,allocations=plan),indent=2)+'\n')
    if args.plan_only:return
    rows=[]
    for entry in plan:
        directory=args.output/entry['name']
        if directory.exists():
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed':raise RuntimeError(f'Inspect unfinished run: {directory}')
            if meta.get('cutoff','raw')!=args.cutoff:raise ValueError('Existing continuation cutoff differs')
            for k in ('n','temperature','seed','steps','replica_id'):
                if meta.get(k)!=entry[k]:raise RuntimeError(f'Existing extension mismatch: {directory}')
        else:
            subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
                '--sampling','pivot','--cutoff',args.cutoff,'--n',str(entry['n']),'--temperature',str(entry['temperature']),
                '--seed',str(entry['seed']),'--steps',str(entry['steps']),'--initial-run',entry['source'],
                '--output',str(directory)],check=True)
        row=analyze(directory);row['directory']=str(directory);rows.append(row)
        (args.output/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(json.dumps(row),flush=True)


if __name__=='__main__':main()
