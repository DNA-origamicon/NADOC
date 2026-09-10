"""Bounded continuation of the poorly mixed N135/396 K GPU replica cohort."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from experiments.peg_chudoba.analyze_chain import analyze


def main():
    root=Path(__file__).parent
    out=root/'runs/zero_tail_gpu_n135_t396_extension1'
    out.mkdir(parents=True,exist_ok=True)
    plan=[]
    for seed,source_seed in zip((1721,1722,1723),(721,722,723)):
        source=root/f'runs/zero_tail_gpu_n135_t396/s{source_seed}'
        prior=json.loads((source/'run.json').read_text())
        if any(prior.get(k)!=v for k,v in dict(status='completed',n=135,temperature=396,
                cutoff='zero_tail',sampling='md',dt_fs=2).items()):raise ValueError('Invalid predecessor')
        plan.append(dict(seed=seed,source=str(source),
            source_sha256=hashlib.sha256((source/'last_conf.dat').read_bytes()).hexdigest(),
            replica_id=prior['replica_id'],name=f's{seed}',n=135,temperature=396,
            cutoff='zero_tail',sampling='md',dt_fs=2,steps=200000000))
    planfile=out/'plan.json'
    if planfile.exists():
        if json.loads(planfile.read_text())['allocations']!=plan:raise ValueError('Frozen plan mismatch')
    else:
        report=json.loads((root/'sampler_comparison.json').read_text())
        matches=[r for r in report['comparisons'] if r['n']==135 and r['temperature_K']==396 and
                 r['cutoff']=='zero_tail' and len(r['completed'])==3 and r.get('gpu',{}).get('extension_recommended')]
        if len(matches)!=1:raise ValueError('Require the completed, flagged predecessor cohort')
        planfile.write_text(json.dumps(dict(allocations=plan,triggering_diagnostics=matches[0]['gpu'],
            interpretation='400 ns per independent origin at 2 fs. Twentyfold allocation versus the 20 ns pilot; new convergence assessment required. Roughly 12 GPU-hours for three sequential replicas at the measured pilot rate, not a completion-time guarantee.'),indent=2)+'\n')
    rows=[]
    for entry in plan:
        directory=out/entry['name']
        if directory.exists():
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed' or any(meta.get(k)!=entry[k] for k in
                    ('seed','n','temperature','cutoff','sampling','dt_fs','steps','replica_id')):
                raise ValueError('Inspect incomplete or mismatched existing continuation')
        else:
            command=[sys.executable,'-m','experiments.peg_chudoba.run_chain',
                     '--initial-run',entry['source'],'--output',str(directory)]
            for key in ('seed','n','temperature','cutoff','sampling','dt_fs','steps'):
                command+=['--'+key.replace('_','-'),str(entry[key])]
            subprocess.run(command,check=True)
        result=analyze(directory);result['directory']=str(directory);rows.append(result)
        (out/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
