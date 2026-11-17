"""Compare native CPU/CUDA CPD throughput from the same immutable checkpoint."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from scripts.check_oxdna_cpd_cuda import settings


def benchmark(job, plugin, binary, steps):
    results=[]
    for backend in ['CPU','CUDA']:
        with tempfile.TemporaryDirectory(prefix='nadoc-cpd-bench-') as td:
            directory=Path(td)
            inp=settings(job,plugin,directory,backend=backend,steps=steps,edge=backend=='CUDA',sort_every=0)
            path=directory/'input';path.write_text('\n'.join(f'{k} = {v}' for k,v in inp.items()))
            started=time.monotonic()
            run=subprocess.run([str(binary),str(path)],cwd=directory,capture_output=True,text=True)
            log=run.stdout+run.stderr+(directory/'native.log').read_text()
            if run.returncode: raise RuntimeError(log[-4000:])
            seconds=time.monotonic()-started
            native_seconds=float(re.search(r'Total Running Time: ([\d.]+)',log)[1])
            row=dict(backend=backend,edge=backend=='CUDA',steps=steps,seconds=seconds,native_cpu_clock_seconds=native_seconds,steps_per_second=steps/seconds)
            results.append(row);print(row,flush=True)
    return dict(source=str(job),results=results,speedup=results[0]['seconds']/results[1]['seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job',type=Path);parser.add_argument('--receipt',required=True,type=Path)
    parser.add_argument('--steps',type=int,default=100000)
    root=Path.home()/'.local/share/nadoc/engines/oxdna'
    args=parser.parse_args()
    result=benchmark(args.job.resolve(),root/'cpd-v1',root/'current/bin/oxDNA',args.steps)
    args.receipt.write_text(json.dumps(result,indent=2)+'\n')
