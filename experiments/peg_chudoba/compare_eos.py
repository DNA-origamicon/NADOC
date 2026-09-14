"""EOS coverage and preliminary estimates, with missing states made explicit."""
from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiments.peg_chudoba.analyze_chain import correlation_time
from experiments.peg_chudoba.sampling_diagnostics import split_rhat


def main():
    root=Path(__file__).parent
    targets=json.loads((root/'reference/published_targets.json').read_text())['osmotic_pressure']
    latest={};excluded=[]
    for path in list((root/'runs').glob('*/analysis.json'))+list((root/'runs').glob('*/*/analysis.json')):
        row=json.loads(path.read_text())
        if 'concentration_g_per_l' not in row or row.get('chains')!=108:continue
        meta=json.loads((path.parent/'run.json').read_text())
        if meta.get('status')!='completed' or meta.get('sampling') not in ('npt','hmc') or meta['steps']<1000:continue
        density=np.atleast_2d(np.loadtxt(path.parent/'thermo.dat'))[:,1]
        volume=meta['particles']/density*.8518**3;volume=volume[len(volume)//2:]
        if np.var(volume)==0:
            excluded.append(dict(directory=str(path.parent),reason='Frozen volume trace; uncertainty cannot be inferred'))
            continue
        ineff=correlation_time(volume)
        row=dict(row,_volume_trace=volume,effective_volume_samples=len(volume)/ineff,
            concentration_sem_g_per_l=float(row['concentration_g_per_l']*volume.std(ddof=1)*np.sqrt(ineff/len(volume))/volume.mean()))
        key=(meta['n'],meta['temperature'],meta['pressure_kpa'],meta['sampling'],meta['cutoff'],meta.get('replica_id',meta['seed']))
        # A short pilot and its longer same-seed repeat are not independent.
        score=(meta.get('sampling_generation',0),meta['steps'])
        if key not in latest or score>(latest[key][0].get('sampling_generation',0),latest[key][0]['steps']):
            latest[key]=(meta,row,str(path.parent))
    grouped=defaultdict(list)
    for key,item in latest.items():grouped[key[:-1]].append(item)
    estimates=[]
    for (n,t,p,sampling,cutoff),items in sorted(grouped.items()):
        matches=[r for r in targets if r['n']==n and r['temperature_K']==t and abs(r['pressure_kpa']/p-1)<.02]
        if not matches:continue
        target=matches[0];c=np.array([row['concentration_g_per_l'] for _,row,_ in items])
        within=np.sqrt(sum(row['concentration_sem_g_per_l']**2 for _,row,_ in items))/len(items)
        between=c.std(ddof=1)/np.sqrt(len(c)) if len(c)>1 else 0.
        traces=[r['_volume_trace'] for _,r,_ in items]
        rh=split_rhat(traces)['maximum'] if len(items)>1 and len({len(x) for x in traces})==1 else float('inf')
        shape_traces=[np.asarray(row.get('saved_rg_trace_nm',[]),dtype=float) for _,row,_ in items]
        shape_traces=[x[len(x)//2:] for x in shape_traces]
        shape_available=all(len(x)>=8 and np.isfinite(x).all() for x in shape_traces)
        shape_rhat=(split_rhat(shape_traces)['maximum'] if shape_available and len(items)>1
                    and len({len(x) for x in shape_traces})==1 else float('inf'))
        shape_ess=[len(x)/correlation_time(x) if len(x)>=8 and np.var(x)>0 else 0. for x in shape_traces]
        estimates.append(dict(n=n,temperature_K=t,pressure_kpa=p,sampling=sampling,cutoff=cutoff,
            seeds=[m['seed'] for m,_,_ in items],directories=[d for _,_,d in items],
            replica_ids=[m.get('replica_id',m['seed']) for m,_,_ in items],
            mean_concentration_g_per_l=float(c.mean()),conservative_sem_g_per_l=float(max(within,between)),
            minimum_effective_volume_samples=min(row['effective_volume_samples'] for _,row,_ in items),
            rank_folded_split_rhat=float(rh) if np.isfinite(rh) else None,
            structure_observable='Mean instantaneous chain Rg over all molecules; used only for mixing diagnostics',
            structure_rank_folded_split_rhat=float(shape_rhat) if np.isfinite(shape_rhat) else None,
            minimum_effective_structure_samples=float(min(shape_ess)),
            retained_structure_frames=[len(x) for x in shape_traces],
            extension_recommended=bool(len(items)<3 or rh>=1.01 or min(row['effective_volume_samples'] for _,row,_ in items)<100
                                       or shape_rhat>=1.01 or min(shape_ess)<100),
            published_concentration_g_per_l=target['concentration_g_per_l'],
            digitization_relative_bound=target['digitization_relative_bound'],
            relative_difference=float(c.mean()/target['concentration_g_per_l']-1),
            status='Allocation estimates only; initialization, structural mixing and independent-seed convergence must be assessed'))
    missing=[target for target in targets if not any(r['n']==target['n'] and r['temperature_K']==target['temperature_K']
        and r['cutoff']=='zero_tail' and abs(r['pressure_kpa']/target['pressure_kpa']-1)<.02 and len(r['seeds'])>=3 for r in estimates)]
    (root/'eos_comparison.json').write_text(json.dumps(dict(status='Incomplete and unvalidated',primary_cutoff='zero_tail',
        published_states=len(targets),estimates=estimates,missing_three_seed_states=missing,excluded=excluded),indent=2)+'\n')
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for ax,(n,t) in zip(axes,[(135,294),(455,294),(455,371)]):
        rows=[r for r in targets if r['n']==n and r['temperature_K']==t]
        ax.errorbar([r['pressure_kpa'] for r in rows],[r['concentration_g_per_l'] for r in rows],
            yerr=[r['concentration_g_per_l']*r['digitization_relative_bound'] for r in rows],fmt='k.',label='Published markers')
        for sampling in ('npt','hmc'):
            rows=[r for r in estimates if r['n']==n and r['temperature_K']==t and r['sampling']==sampling and r['cutoff']=='zero_tail']
            if rows:ax.errorbar([r['pressure_kpa'] for r in rows],[r['mean_concentration_g_per_l'] for r in rows],
                yerr=[2*r['conservative_sem_g_per_l'] for r in rows],fmt='o',label=f'{sampling}, zero tail: ±2 SEM')
        ax.set(xscale='log',yscale='log',xlabel='Pressure (kPa)',ylabel='Concentration (g/L)',title=f'N={n}, {t} K')
        ax.legend(fontsize=7)
    fig.suptitle('PEG osmotic EOS — incomplete coverage; no reproduction claim')
    fig.tight_layout();fig.savefig(root/'eos_comparison.png',dpi=170)
    print(json.dumps(dict(estimates=len(estimates),missing_three_seed_states=len(missing))))


if __name__=='__main__':main()
