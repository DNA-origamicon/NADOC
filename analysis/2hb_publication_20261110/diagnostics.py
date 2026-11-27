"""Replica/window diagnostics. Never converts these descriptors into production parameters."""
import json
from pathlib import Path
import numpy as np
from collect import summary
O=Path(__file__).resolve().parent
R=json.loads((O/'results.json').read_text());out={};sensitivity=[]
keys=['Rg_A','helix_centroid_sep_A','helix_tilt_deg','wc_fraction','d_mid_A']
for name in sorted({r['design'] for r in R}):
 runs=[r for r in R if r['design']==name and r['created'].startswith('2026-10')]
 entry={'replicas':len(runs),'metrics':{}}
 if len(runs)<2:continue
 for k in keys:
  chains=[];means=[];stds=[]
  for r in runs:
   a=np.genfromtxt(O/(r['job_id']+'_trace.csv'),delimiter=',',names=True);x=a[k][a['time_ns']>=r['late_window_start_ns']];n=len(x)//2;chains.extend([x[:n],x[-n:]]);means.append(float(x.mean()));stds.append(float(x.std(ddof=1)))
  n=min(map(len,chains));chains=np.array([x[:n] for x in chains]);W=np.mean(np.var(chains,axis=1,ddof=1));B=n*np.var(chains.mean(1),ddof=1);rhat=np.sqrt(((n-1)/n*W+B/n)/W)
  entry['metrics'][k]={'replica_means':means,'replica_sds':stds,'mean_of_replica_means':float(np.mean(means)),'between_replica_sd':float(np.std(means,ddof=1)),'split_Rhat':float(rhat),'qualification':'Classical split Rhat on final 75%; three replicas share initial geometry. Not rank normalized.'}
 out[name]=entry
for r in R:
 a=np.genfromtxt(O/(r['job_id']+'_trace.csv'),delimiter=',',names=True)
 sensitivity.append({'job_id':r['job_id'],'windows':{str(cut):{k:summary(a[k][a['time_ns']>=a['time_ns'][0]+cut*(a['time_ns'][-1]-a['time_ns'][0])],r['sample_dt_ns']) for k in keys} for cut in [0,.25,.5]}})
(O/'replica_diagnostics.json').write_text(json.dumps(out,indent=2)+'\n');(O/'window_sensitivity.json').write_text(json.dumps(sensitivity,indent=2)+'\n')
for name,e in out.items():
 print(name)
 for k,v in e['metrics'].items():print(k,'means',np.round(v['replica_means'],3),'Rhat',round(v['split_Rhat'],3))
