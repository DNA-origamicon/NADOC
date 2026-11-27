"""Compact comparison and static figures from completed research campaigns."""
import argparse
import json
from pathlib import Path
import numpy as np
from tools.oxdna_tm_research.analyze import passages


def report(root,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    campaigns=[p for p in root.iterdir() if p.is_dir() and (p/'result.json').exists() and 'smoke' not in p.name]
    campaigns.sort(key=lambda p:json.loads((p/'manifest.json').read_text())['seed'])
    rows=[]
    fig,axes=plt.subplots(len(campaigns),1,figsize=(10,2.5*len(campaigns)),squeeze=False)
    for ax,p in zip(axes[:,0],campaigns):
        m=json.loads((p/'manifest.json').read_text());r=json.loads((p/'result.json').read_text())
        f=json.loads((p/'full_analysis.json').read_text()) if (p/'full_analysis.json').exists() else None
        events=[json.loads(x) for x in (p/'events.jsonl').read_text().splitlines()]
        tuning=next(e['elapsed_seconds'] for e in events if e['event']=='tuning_complete')
        equil=next(e['elapsed_seconds'] for e in events if e['event']=='equilibration_complete')
        reps=[];traces={}
        checkpoints=[e["elapsed_seconds"] for e in events if e["event"]=="precision_checkpoint"]
        for i,paths in enumerate(r['production_directories']):
            states=[];matched=[];xs=[];elapsed=equil;acceptance=[]
            for block,d in enumerate(map(Path,paths)):
                elapsed=equil if block==0 else checkpoints[block-1]
                e=np.loadtxt(d/'energy.dat',ndmin=2);e=e[e[:,0]>0]
                execution=json.loads((d/'execution.json').read_text())
                xs.extend((elapsed+e[:,0]/execution['requested_steps']*execution['elapsed_seconds'])/60)
                acceptance.append(e[-1,2:4].tolist())
                states.extend(e[:,5].astype(int));matched.extend(e[e[:,0]%10000==0,5].astype(int))
                elapsed+=execution['elapsed_seconds']
            q=np.array(states);qmatched=np.array(matched)
            reps.append(dict(replica=i,translation_rotation_acceptance_by_block=acceptance,occupancy=np.bincount(q,minlength=9).tolist(),full=passages(q,8),six=passages(q,6),matched_10k_full=passages(qmatched,8)))
            traces[f'replica_{i}']=np.column_stack((xs,q))
            ax.plot(xs,q,lw=.65,alpha=.75,label=f'{i+1}: {m["starts"][i]}')
        (output/'traces').mkdir(exist_ok=True)
        np.savez_compressed(output/'traces'/f'{p.name}.npz',**traces)
        if p.name=='distance_confirmation':
            detail,daxes=plt.subplots(4,1,figsize=(10,7),sharex=True,sharey=True)
            for i,dax in enumerate(daxes):
                trace=traces[f'replica_{i}']
                dax.plot(trace[:,0],trace[:,1],lw=.7,color=f'C{i}')
                dax.axvspan(0,tuning/60,color='gray',alpha=.15)
                dax.axvspan(tuning/60,equil/60,color='gold',alpha=.15)
                dax.set(ylabel=f'Replica {i+1}\n{m["starts"][i]}',yticks=[0,4,8],ylim=(-.3,8.3))
            dax.set_xlabel('Elapsed minutes; native pair count on each vertical axis')
            detail.tight_layout();detail.savefig(output/'confirmation_traces.png',dpi=160);detail.savefig(output/'confirmation_traces.pdf');plt.close(detail)
        ax.axvspan(0,tuning/60,color='gray',alpha=.15,label='training')
        ax.axvspan(tuning/60,equil/60,color='gold',alpha=.15,label='equilibration')
        ax.set(ylim=(-.3,8.3),yticks=[0,2,4,6,8],ylabel='Native pairs',title=p.name,xlabel='Elapsed minutes (trace times interpolated within native stages)')
        ax.legend(ncol=3,fontsize=7,loc='upper right')
        full=None if f is None else f['precision']
        post_seconds=f['analysis_seconds'] if f else 0
        if p.name=='distance_confirmation' and (root/'confirmation_analysis_timing.json').exists():
            post_seconds=json.loads((root/'confirmation_analysis_timing.json').read_text())['total_analysis_and_audits_seconds']
            if (p/'binding_definition.json').exists():
                post_seconds+=json.loads((p/'binding_definition.json').read_text())['analysis_seconds']
        rows.append(dict(name=p.name,proposals=m['proposals'],training_walkers=m.get('training_walkers',1),distance_split=m.get('distance_split',0),seed=m['seed'],tuning_seconds=tuning,equilibration_seconds=equil-tuning,sampling_and_native_analysis_seconds=r['elapsed_seconds']-equil,driver_seconds=r['elapsed_seconds'],full_analysis_seconds=None if f is None else f['analysis_seconds'],
            total_timed_seconds=r['elapsed_seconds']+post_seconds,
            full_hamiltonian_tm_c=None if full is None else full['tm_c'],ci95_c=None if full is None else full['ci95_c'],
            replica_tm_c=None if full is None else full['replica_tm_c'],
            start_probabilities_70=None if f is None else [a['p_bound_70'] for a in f['replicas']],
            same_frame_stacking_only_tm_c=None if f is None else f['same_frame_stacking_only_tm_c'],
            all_interstrand_tm_c=None if f is None else f.get('all_interstrand_bond_tm_c'),
            reasons=None if full is None else full['reasons'],replicas=reps,certified=False))
    fig.tight_layout();fig.savefig(output/'pairing_traces.png',dpi=160);fig.savefig(output/'pairing_traces.pdf');plt.close(fig)
    (output/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    import csv
    with (output/'comparison.csv').open('w') as stream:
        fields=['name','total_timed_seconds','full_hamiltonian_tm_c','ci95_c','replica_tm_c','start_probabilities_70','certified']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        writer.writerows({k:r[k] for k in fields} for r in rows)
    return rows

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');p.add_argument('output');a=p.parse_args();report(a.root,a.output)
