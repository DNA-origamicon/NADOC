"""Compare completed independent seeds with digitized published marker data."""
import json
from pathlib import Path
import numpy as np
from experiments.peg_chudoba.rg_statistics import summarize_rms
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    root=Path(__file__).parent
    results=json.loads((root/'runs/equilibrium_294/summary.json').read_text())
    targets=json.loads((root/'reference/published_targets.json').read_text())['chain_dimensions']
    records=[]
    for n in sorted({r['n'] for r in results}):
        rows=[r for r in results if r['n']==n]
        if len(rows)<3:continue
        choices=[r for r in targets if r['n']==n and r['temperature_K']==294]
        if not choices:continue
        target=sorted(choices,key=lambda r:r['figure'])[0]
        traces=[]
        for row in rows:
            x=np.loadtxt(Path(row['directory'])/'rg.csv',delimiter=',',skiprows=1,usecols=1)
            traces.append(x[len(x)//10:])
        stats=summarize_rms(traces)
        records.append(dict(n=n,seeds=len(rows),**stats,observable='sqrt(mean(Rg^2))',
            published_rg_nm=target['rg_nm'],digitization_bound_nm=target['digitization_bound_nm'],
            relative_difference=float(stats['rms_rg_nm']/target['rg_nm']-1)))
    (root/'chain_comparison_294.json').write_text(json.dumps(dict(
        status='Historical raw-truncation control; primary published-model reconstruction uses zero_tail',cutoff='raw',
        comparisons=records),indent=2)+'\n')
    fig,ax=plt.subplots(figsize=(6,4))
    ax.errorbar([r['n'] for r in records],[r['rms_rg_nm'] for r in records],
        yerr=[2*r['conservative_sem_nm'] for r in records],fmt='o',label='Raw-truncation control (±2 SEM)')
    ax.errorbar([r['n'] for r in records],[r['published_rg_nm'] for r in records],
        yerr=[r['digitization_bound_nm'] for r in records],fmt='v',label='Chudoba 2017 (digitized)')
    ax.set(xlabel='EO beads per chain',ylabel='RMS radius of gyration (nm)',
        title='294 K raw-truncation control')
    ax.legend(fontsize=8);fig.tight_layout();fig.savefig(root/'chain_comparison_294.png',dpi=180)
    print(json.dumps(records,indent=2))


if __name__=='__main__':main()
