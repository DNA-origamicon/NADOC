"""Report all completed chain cohorts without treating missing states as passes."""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiments.peg_chudoba.rg_statistics import summarize_rms


def main():
    root=Path(__file__).parent
    targets=json.loads((root/'reference/published_targets.json').read_text())['chain_dimensions']
    intervals=json.loads((root/'reference/published_chain_intervals.json').read_text())['intervals']
    intervals={(r['n'],r['temperature_K']):r for r in intervals}
    # Figure 6a and Figure 7b overlap at 294 K. Keep their provenance, use the
    # first figure's marker for each unique observable/state comparison.
    target_by_state={}
    for row in sorted(targets,key=lambda r:r['figure']):
        target_by_state.setdefault((row['n'],row['temperature_K']),row)
    grouped=defaultdict(list)
    for path in (root/'runs').glob('*/summary.json'):
        for row in json.loads(path.read_text()):
            directory=Path(row['directory'])
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed':continue
            if meta.get('sampling')!='pivot' or meta.get('chains',1)!=1:continue
            # Early raw cohorts predate the explicit manifest field. Verify
            # their saved input rather than infer convention from a folder name.
            settings=dict(line.split('=',1) for line in (directory/'input').read_text().splitlines() if '=' in line)
            settings={k.strip():v.strip() for k,v in settings.items()}
            cutoff=('zero_tail' if settings.get('peg_chudoba_zero_tail','false')=='true' else
                    ('shifted' if settings.get('peg_chudoba_shift','false')=='true' else 'raw'))
            if 'cutoff' in meta and meta['cutoff']!=cutoff:raise ValueError(directory)
            key=(cutoff,row['n'],row['temperature_K'],meta.get('sampling_generation',0))
            row=dict(row,replica_id=meta.get('replica_id',meta['seed']))
            grouped[key].append((meta['seed'],row))
    # Promote an extension only when a complete three-replica generation exists.
    # Original trajectories and their continuations are not independent seeds.
    selected={}
    for key,values in grouped.items():
        if len(values)<3:continue
        state=key[:3]
        if state not in selected or key[3]>selected[state][0]:selected[state]=(key[3],values)
    comparisons=[]
    for (cutoff,n,t),(generation,values) in sorted(selected.items()):
        if (n,t) not in target_by_state:continue
        if len(values)<3:continue
        seeds=[seed for seed,_ in values]
        if len(set(seeds))!=len(seeds):raise ValueError(f'Duplicate seeds for {cutoff,n,t}')
        replica_ids=[row['replica_id'] for _,row in values]
        if len(set(replica_ids))!=len(replica_ids):raise ValueError(f'Duplicate replica ancestry for {cutoff,n,t}')
        rows=[row for _,row in values];target=target_by_state[n,t]
        traces=[]
        for row in rows:
            trace=np.loadtxt(Path(row['directory'])/'rg.csv',delimiter=',',skiprows=1,usecols=1)
            traces.append(trace[len(trace)//10:])
        stats=summarize_rms(traces)
        estimate=stats['rms_rg_nm'];sem=stats['conservative_sem_nm']
        comparisons.append(dict(cutoff=cutoff,n=n,temperature_K=t,seeds=seeds,
            replica_ids=replica_ids,sampling_generation=generation,directories=[row['directory'] for row in rows],
            observable='sqrt(mean(Rg^2))',mean_rg_nm=float(np.mean([x.mean() for x in traces])),
            **stats,published_rg_nm=target['rg_nm'],
            digitization_bound_nm=target['digitization_bound_nm'],figure=target['figure'],
            relative_difference=float(estimate/target['rg_nm']-1),
            within_two_sem_plus_digitization=bool(abs(estimate-target['rg_nm'])<=2*sem+target['digitization_bound_nm'])))
    for row in comparisons:
        interval=intervals.get((row['n'],row['temperature_K']))
        row['published_plotted_interval']=interval
        if interval:
            lo=interval['lower_nm']-interval['digitization_bound_nm']
            hi=interval['upper_nm']+interval['digitization_bound_nm']
            estimate=row['rms_rg_nm'];sem=row['conservative_sem_nm']
            row['estimate_within_published_interval']=bool(lo<=estimate<=hi)
            row['two_sem_overlaps_published_interval']=bool(estimate+2*sem>=lo and estimate-2*sem<=hi)
        else:
            row['estimate_within_published_interval']=None
            row['two_sem_overlaps_published_interval']=None
    missing={cutoff:[dict(n=n,temperature_K=t) for n,t in sorted(target_by_state)
        if not any(r['cutoff']==cutoff and r['n']==n and r['temperature_K']==t for r in comparisons)]
        for cutoff in ('raw','shifted','zero_tail')}
    report=dict(status='Preliminary; full coverage, convergence and cutoff audit remain required',
        observable='sqrt(mean(Rg^2))',observable_evidence='reference/rg_definition_audit.json',
        published_interval_interpretation='Figure 7(b) plotted bars; error-bar type unspecified. Overlap is descriptive, not a calibrated confidence test.',
        unique_published_states=len(target_by_state),comparisons=comparisons,missing_three_seed_states=missing)
    (root/'campaign_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    temperatures=sorted({t for n,t in target_by_state})
    fig,axes=plt.subplots(3,3,figsize=(12,10))
    for ax,t in zip(axes.flat,temperatures):
        ts=sorted((n,r) for (n,temp),r in target_by_state.items() if temp==t)
        ax.errorbar([n for n,r in ts],[r['rg_nm'] for n,r in ts],
            yerr=[r['digitization_bound_nm'] for n,r in ts],fmt='k.',label='Published markers')
        bars=[(n,intervals[n,t]) for n,r in ts if (n,t) in intervals]
        if bars:ax.vlines([n for n,r in bars],[r['lower_nm'] for n,r in bars],
                         [r['upper_nm'] for n,r in bars],color='gray',linewidth=1.2,label='Published bars (type unspecified)')
        for cutoff in ('raw','shifted','zero_tail'):
            rows=[r for r in comparisons if r['cutoff']==cutoff and r['temperature_K']==t]
            ax.errorbar([r['n'] for r in rows],[r['rms_rg_nm'] for r in rows],
                yerr=[2*r['conservative_sem_nm'] for r in rows],fmt='o',markersize=3,label=f'{cutoff}, ±2 SEM')
        ax.set(title=f'{t:g} K',xlabel='EO repeats',ylabel='RMS Rg (nm)',xscale='log',yscale='log')
    for ax in list(axes.flat)[len(temperatures):]:ax.axis('off')
    axes.flat[0].legend(fontsize=7)
    fig.suptitle('PEG benchmark reproduction — incomplete coverage and validation')
    fig.tight_layout();fig.savefig(root/'campaign_comparison.png',dpi=170)
    print(json.dumps(dict(three_seed_comparisons=len(comparisons),unique_published_states=len(target_by_state))))


if __name__=='__main__':main()
