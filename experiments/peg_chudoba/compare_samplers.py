"""Compare completed GPU replica cohorts with the matching CPU pivot cohort."""
import json
from pathlib import Path
import numpy as np
from experiments.peg_chudoba.analyze_chain import analyze
from experiments.peg_chudoba.rg_statistics import summarize_rms


def main():
    root=Path(__file__).parent;runs=root/'runs'
    cpu=json.loads((root/'campaign_comparison.json').read_text())['comparisons']
    cases=[(36,381,'raw','hmc',[runs/f'hmc_n36_t381_raw_warm_s{s}' for s in (903,904)]+[runs/'hmc_n36_t381_raw_warm_s905_retry1']),
           (36,381,'zero_tail','md',[runs/'zero_tail_gpu_n36_t381'/f's{s}' for s in (701,702,703)]),
           (135,396,'zero_tail','md',[runs/'zero_tail_gpu_n135_t396'/f's{s}' for s in (721,722,723)]),
           (135,396,'zero_tail','md',[runs/'zero_tail_gpu_n135_t396_extension1'/f's{s}' for s in (1721,1722,1723)])]
    comparisons=[]
    for n,temperature,cutoff,sampling,dirs in cases:
        completed=[];pending=[];traces=[];origins=[]
        for directory in dirs:
            manifest=directory/'run.json'
            if not manifest.exists():pending.append(str(directory));continue
            meta=json.loads(manifest.read_text())
            if meta['status']!='completed':pending.append(str(directory));continue
            if any(meta.get(k)!=v for k,v in dict(n=n,temperature=temperature,sampling=sampling,cutoff=cutoff).items()):
                raise ValueError('Sampler comparison settings mismatch')
            origin=meta.get('replica_id')
            if origin is None and meta.get('initial_source'):
                parent=json.loads((Path(meta['initial_source']['directory'])/'run.json').read_text())
                origin=parent.get('replica_id',parent['seed'])
            origins.append(origin if origin is not None else meta['seed'])
            if not (directory/'analysis.json').exists():analyze(directory)
            x=np.loadtxt(directory/'rg.csv',delimiter=',',skiprows=1,usecols=1)
            traces.append(x[len(x)//10:]);completed.append(str(directory))
        entry=dict(cutoff=cutoff,sampling=sampling,n=n,temperature_K=temperature,completed=completed,pending=pending)
        if len(traces)==3:
            if len(set(origins))!=3:raise ValueError('Duplicate GPU replica origin')
            stats=summarize_rms(traces);entry.update(gpu=stats,replica_ids=origins)
            match=[r for r in cpu if r['cutoff']==cutoff and r['n']==n and r['temperature_K']==temperature]
            if len(match)==1:
                reference=match[0];difference=stats['rms_rg_nm']-reference['rms_rg_nm']
                combined=np.hypot(stats['conservative_sem_nm'],reference['conservative_sem_nm'])
                entry.update(cpu_rms_rg_nm=reference['rms_rg_nm'],cpu_sem_nm=reference['conservative_sem_nm'],
                    difference_nm=float(difference),combined_sem_nm=float(combined),
                    within_two_combined_sem=bool(abs(difference)<=2*combined),
                    cpu_extension_recommended=reference['extension_recommended'])
        comparisons.append(entry)
    result=dict(status='Sampler checks, not a published benchmark reproduction claim',
        interpretation='GPU trajectories start from independent CPU origins. Quadrature SEM comparison assumes post-discard sampling has lost initial-state dependence; inspect both cohorts for convergence.',comparisons=comparisons)
    (root/'sampler_comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    for row in comparisons:print({k:v for k,v in row.items() if k not in ('completed','pending')})


if __name__=='__main__':main()
