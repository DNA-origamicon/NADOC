import json
from pathlib import Path
import numpy as np
O=Path(__file__).resolve().parent
R=json.loads((O/'production_results.json').read_text());out={}
for cohort,jobs in [('October_2fs',['be74a1436d66','be5dc708adb2','a9261569b8c7']),('August_4fs_500ns',['bd13e4dfa6c5','07d7cd2766e3'])]:
 metrics={}
 for metric in ['midpoint_A','wc_fraction','local_wc_fraction']:
  chains=[];means=[]
  for jid in jobs:
   z=np.load(O/jid/'series.npz');x=z[metric] if metric!='midpoint_A' else np.linalg.norm(z['coordinates_ang'][:,1:3].mean(1)-z['coordinates_ang'][:,7:9].mean(1),axis=1);x=x[len(x)//4:];means.append(float(x.mean()));n=len(x)//2;chains.extend([x[:n],x[-n:]])
  n=min(map(len,chains));a=np.array([x[:n] for x in chains]);W=np.var(a,axis=1,ddof=1).mean();B=n*np.var(a.mean(1),ddof=1);rh=np.sqrt(((n-1)/n*W+B/n)/W);metrics[metric]=dict(replica_means=means,split_Rhat=float(rh))
 out[cohort]=dict(jobs=jobs,metrics=metrics,qualification='Classical split Rhat on final75%, not rank normalized. Shared preparation, no independent conformational initialization. Unequal 800 ns run deliberately excluded from equal-length pair comparison.')
(O/'convergence.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
