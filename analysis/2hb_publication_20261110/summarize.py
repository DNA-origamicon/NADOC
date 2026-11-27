"""Summaries, protocol inventory, and figures from collected scalar traces."""
import json,csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collect import summary,confread
O=Path(__file__).resolve().parent
R=json.loads((O/'results.json').read_text());rows=[];logs=[]
for r in R:
 a=np.genfromtxt(O/(r['job_id']+'_trace.csv'),delimiter=',',names=True);pkg=Path(r['files'][0]['path']).parents[1];logrows=[]
 for p in sorted(pkg.glob('*production*.log')):
  head=[];en=[]
  for line in p.read_text(errors='replace').splitlines():
   if line.startswith('ETITLE:'):head=line.split()[1:]
   elif line.startswith('ENERGY:') and head:
    try:en.append(dict(zip(head,map(float,line.split()[1:]))))
    except ValueError:pass
  if en:
   with (O/(r['job_id']+'_'+p.stem.split('_k0')[-1]+'_energy.csv')).open('w') as f:
    w=csv.DictWriter(f,fieldnames=list(en[0]));w.writeheader();w.writerows(en)
   logrows.append(dict(path=str(p),records=len(en),first_step=en[0]['TS'],last_step=en[-1]['TS'],statistics={k:dict(mean=float(np.mean([v[k] for v in en])),min=min(v[k] for v in en),max=max(v[k] for v in en)) for k in ['TEMP','VOLUME','POTENTIAL'] if k in en[0]},normal_exit='End of program' in p.read_text(errors='replace')))
 dna_extras=[]
 ep=pkg/r['config']['extrabondsfile']
 if ep.exists():
  for l in ep.read_text().splitlines():
   t=l.split()
   if t and t[0]=='bond' and any(int(i)<3043 for i in t[1:3]):dna_extras.append(l)
 logs.append(dict(job_id=r['job_id'],logs=logrows,dna_extrabonds=dna_extras))
 for k,s in r['statistics'].items():
  rows.append(dict(design=r['design'],created=r['created'],job_id=r['job_id'],metric=k,first_ns=r['first_last_ns'][0],last_ns=r['first_last_ns'][1],**{n:s[n] for n in ['mean','sd','p05','p95','ess','tau_int_ns','half_shift']}))
with (O/'summary.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(O/'protocol_audit.json').write_text(json.dumps(logs,indent=2)+'\n')
# One panel per metric and cohort; raw traces and cumulative means retained.
for group,sel in [('short_replicas',[r for r in R if r['created'].startswith('2026-10')]),('long_runs',[r for r in R if not r['created'].startswith('2026-10') and r['sampled_frames']>100]),('long_cpd',[r for r in R if r['created'].startswith('2026-11')])]:
 fig,ax=plt.subplots(3,2,figsize=(14,10),sharex=True)
 keys=['heavy_rmsd_A','Rg_A','helix_centroid_sep_A','helix_tilt_deg','wc_fraction','d_mid_A']
 colors={'2hb_1xT':'#555555','2hb_1xT_CPD_cis-syn-I':'#0072B2','2hb_1xT_CPD_cis-anti-I':'#D55E00','2hb_1xT_CPD_trans-syn-I':'#009E73','2hb_1xT_CPD_trans-syn-II':'#CC79A7'}
 seen={}
 labels=['Heavy-atom RMSD (Å)','Heavy-atom Rg (Å)','Helix centroid distance (Å)','Helix tilt (degrees)','WC distance fraction','Reactive-bond midpoint distance (Å)']
 for r in sel:
  occurrence=seen.get(r['design'],0);seen[r['design']]=occurrence+1;style=['-','--',':'][occurrence%3]
  a=np.genfromtxt(O/(r['job_id']+'_trace.csv'),delimiter=',',names=True);t=a['time_ns'];t=t-t[0];label=r['design'].replace('2hb_1xT','unwelded' if r['design']=='2hb_1xT' else '').strip('_')+' '+r['created'][5:16].replace('T',' ')
  for axis,k,ylabel in zip(ax.flat,keys,labels):
   axis.plot(t,a[k],lw=.4,alpha=.25,color=colors[r['design']]);axis.plot(t,np.cumsum(a[k])/np.arange(1,len(a)+1),lw=1.2,ls=style,label=label,color=colors[r['design']]);axis.set_ylabel(ylabel);axis.grid(alpha=.2)
 for axis in ax[-1]:axis.set_xlabel('Time since first available frame (ns)')
 ax[0,0].legend(fontsize=6,ncol=2);fig.suptitle('Saved-frame traces (faint) and cumulative means; '+group.replace('_',' '));fig.tight_layout();fig.savefig(O/(group+'.png'),dpi=170);plt.close(fig)
# Print replica late-window means and long-run summaries.
for r in R:
 print(r['design'],r['created'][5:16],*[f'{k}={r["statistics"][k]["mean"]:.2f} (ESS {r["statistics"][k]["ess"]:.0f}, shift {r["statistics"][k]["half_shift"]:.2f})' for k in ['helix_centroid_sep_A','helix_tilt_deg','wc_fraction','d_mid_A']])
