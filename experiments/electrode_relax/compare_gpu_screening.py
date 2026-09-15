"""Compare saved screening series without confusing pooled precision with convergence."""
import argparse
import json
from pathlib import Path

import numpy as np
from experiments.electrode_relax.debye_analysis import analyze


def main():
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path);a=p.parse_args();out=a.campaign
    rows=json.loads((out/'jobs.json').read_text());results={}
    for series in ('replica_a','replica_b','control_2fs'):
        selected=[r for r in rows if r.get('health',{}).get('confined') and (r['series']==series or (series=='replica_a' and r['series']=='pilot'))]
        if not selected or (len(selected)==1 and selected[0]['series']=='pilot'):continue
        folder=out/series/'final';folder.mkdir(parents=True,exist_ok=True);(folder/'jobs.json').write_text(json.dumps(selected,indent=2)+'\n')
        analyze(folder,folder,.24)
        result=json.loads((folder/'debye_analysis.json').read_text())
        matched=folder/'matched_0.24_to_1.20ns';analyze(folder,matched,.24,1.2)
        result['matched_first_window']=json.loads((matched/'debye_analysis.json').read_text())
        results[series]=result
    (out/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(1,3,figsize=(15,4.5),layout='constrained')
    for j,(name,r) in enumerate(results.items()):
        fits=r['ratio_fits'];center=next(f['lambda_nm'] for f in fits if f['exclude_nm']==.6)
        lo,hi=min(f['lambda_nm'] for f in fits),max(f['lambda_nm'] for f in fits)
        axs[0].errorbar(j,center,yerr=[[center-lo],[hi-center]],fmt='o',capsize=4,color=f'C{j}')
        classical=list(r['classical_lambda_from_center_nm'].values());axs[0].plot([j,j],classical,linewidth=6,alpha=.3,color=f'C{j}')
        blocks=next(x['blocks'] for x in r['sampling_diagnostics']['physical_blocks'] if x['duration_ns']==.6)
        axs[1].plot([x['end_ns'] for x in blocks],[x['center_mM'] for x in blocks],'o-',label=name)
        axs[2].plot([x['end_ns'] for x in blocks],[x['fit'].get('lambda_nm',np.nan) for x in blocks],'o-',label=name)
    axs[0].set(xticks=range(len(results)),xticklabels=list(results),ylabel='Length (nm)',title='Pooled fit: exclusion sensitivity\nThick interval: classical εr 78.3–100')
    axs[1].set(xlabel='Additional time (ns)',ylabel='Central salt (mM)',title='Separate 600 ps windows')
    axs[2].set(xlabel='Additional time (ns)',ylabel='Fitted length (nm)',title='Separate 600 ps fits; bounds retained')
    for ax in axs:ax.grid(alpha=.25)
    axs[1].legend();axs[2].legend();fig.savefig(out/'comparison.png',dpi=160);fig.savefig(out/'comparison.pdf')
    print({name:dict(frames=r['frames'],lambda_nm=r['ratio_fits'][1]['lambda_nm'],center_mM=r['center_ionic_strength_mM']) for name,r in results.items()})


if __name__=='__main__':main()
