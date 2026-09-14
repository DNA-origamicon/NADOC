"""Bounded GPU dynamics cohort after a specified predecessor finishes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from experiments.peg_chudoba.analyze_chain import analyze


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--wait-for-run',type=Path,required=True)
    ap.add_argument('--n',type=int,default=36)
    ap.add_argument('--temperature',type=int,choices=[381,396],default=381)
    ap.add_argument('--seed-base',type=int,default=701)
    args=ap.parse_args()
    if args.n<4 or args.seed_base<1:ap.error('Require at least four repeats and positive seeds')
    root=Path(__file__).parent/'runs';out=root/f'zero_tail_gpu_n{args.n}_t{args.temperature}'
    out.mkdir(parents=True,exist_ok=True)
    plan=[dict(seed=seed,source=str(root/f'equilibrium_zero_tail_381_396/n{args.n}_t{args.temperature}_s{source}'),
               directory=str(out/f's{seed}'),n=args.n,temperature=args.temperature,cutoff='zero_tail',sampling='md',
               dt_fs=2,steps=10000000) for seed,source in zip(range(args.seed_base,args.seed_base+3),(201,202,203))]
    planfile=out/'plan.json'
    if planfile.exists():
        if json.loads(planfile.read_text())['allocations']!=plan:raise ValueError('Existing GPU plan differs')
    else:planfile.write_text(json.dumps(dict(allocations=plan,wait_for_run=str(args.wait_for_run),
                    interpretation='20 ns per independent origin; convergence and CPU agreement remain to be assessed'),indent=2)+'\n')
    waiting=args.wait_for_run.resolve()
    while True:
        live=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():continue
            try:
                if (proc/'comm').read_text().strip()=='oxDNA' and (proc/'cwd').resolve()==waiting:live.append(int(proc.name))
            except OSError:pass
        if not live:break
        print(f'Waiting for existing control engine PID {live}',flush=True);time.sleep(30)
    if json.loads((waiting/'run.json').read_text())['status']!='completed':
        raise ValueError('Control engine is no longer live but is not completed; inspect before continuing')
    results=[]
    for entry in plan:
        source=Path(entry['source']);directory=Path(entry['directory'])
        prior=json.loads((source/'run.json').read_text())
        if prior['status']!='completed' or prior['cutoff']!='zero_tail':raise ValueError('CPU source not ready')
        if directory.exists():
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed' or any(meta.get(k)!=entry[k] for k in ('seed','n','temperature','cutoff','sampling','dt_fs','steps')):
                raise ValueError('Inspect existing incomplete or mismatched GPU allocation')
        else:
            command=[sys.executable,'-m','experiments.peg_chudoba.run_chain','--initial-run',str(source),'--output',str(directory)]
            for key in ('seed','n','temperature','cutoff','sampling','dt_fs','steps'):
                command+=['--'+key.replace('_','-'),str(entry[key])]
            subprocess.run(command,check=True)
        row=analyze(directory);row['directory']=str(directory);results.append(row)
        (out/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(row),flush=True)


if __name__=='__main__':main()
