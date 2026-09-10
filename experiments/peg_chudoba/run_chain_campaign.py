"""Sequential, restartable equilibrium benchmark campaign in the oxDNA engine.

Existing completed runs are analyzed, never overwritten. An unfinished run
requires process inspection; this launcher refuses to guess whether to restart.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from experiments.peg_chudoba.analyze_chain import analyze


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cutoff',choices=['raw','shifted','zero_tail'],default='zero_tail')
    ap.add_argument('--lengths',type=int,nargs='+',default=[9,18,27,36,76,135,275,455,795])
    ap.add_argument('--temperatures',type=float,nargs='+',default=[294])
    ap.add_argument('--seeds',type=int,nargs='+',default=[201,202,203])
    ap.add_argument('--sweeps',type=int,default=100000)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    # Cover short chains at every temperature before expensive long chains.
    for n in args.lengths:
        for t in args.temperatures:
            for seed in args.seeds:
                directory=args.output/f'n{n}_t{t:g}_s{seed}'
                if directory.exists():
                    metadata=json.loads((directory/'run.json').read_text())
                    if metadata['status']!='completed':
                        raise RuntimeError(f'Inspect unfinished run before continuing: {directory}')
                    expected=dict(n=n,temperature=t,seed=seed,steps=args.sweeps,sampling='pivot')
                    if any(metadata.get(k)!=v for k,v in expected.items()):
                        raise RuntimeError(f'Existing run settings do not match requested campaign: {directory}')
                    if metadata.get('cutoff','raw')!=args.cutoff:
                        raise RuntimeError(f'Existing cutoff differs: {directory}')
                else:
                    subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
                        '--sampling','pivot','--cutoff',args.cutoff,'--n',str(n),'--temperature',str(t),
                        '--steps',str(args.sweeps),'--seed',str(seed),'--output',str(directory)],check=True)
                result=analyze(directory);result['directory']=str(directory)
                results.append(result)
                (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
                print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
