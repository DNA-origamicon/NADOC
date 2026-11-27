import json,hashlib,csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
O=Path(__file__).resolve().parent;old=O.parent/'2hb_publication_20261110';new=json.loads((O/'additional_shape_results.json').read_text());prior=[r for r in json.loads((old/'results.json').read_text()) if r['design']=='2hb_1xT'];rows=[];R=[];fig,axs=plt.subplots(3,2,figsize=(14,10));keys=['heavy_rmsd_A','local_fit_rmsd_A','Rg_A','helix_centroid_sep_A','helix_tilt_deg','wc_fraction']
for r in sorted(new+prior,key=lambda r:r['created']):
 base=O if r in new else old;trace=base/(r['job_id']+'_trace.csv');a=np.genfromtxt(trace,delimiter=',',names=True)
 for f in r['files']:
  st=Path(f['path']).stat();assert (st.st_size,st.st_mtime_ns)==(f['bytes'],f['mtime_ns'])
 r['analysis_source']=str(base/'additional_shape_results.json' if r in new else old/'results.json');r['trace_source']=str(trace);r['trace_sha256']=hashlib.sha256(trace.read_bytes()).hexdigest();R.append(r)
 for k in keys:
  s=r['statistics'][k];rows.append(dict(job_id=r['job_id'],created=r['created'],metric=k,mean=s['mean'],sd=s['sd'],ess=s['ess'],half_shift=s['half_shift']))
 for ax,k in zip(axs.ravel(),keys):ax.plot(a['time_ns'],a[k],lw=.6,alpha=.8,label=r['created'][:16]+' '+r['job_id'][:4]);ax.set_ylabel(k);ax.set_xlabel('Time (ns)')
axs[0,0].legend(fontsize=6);fig.tight_layout();fig.savefig(O/'shape_timeseries.png',dpi=150);plt.close(fig)
(O/'shape_results.json').write_text(json.dumps(R,indent=2)+'\n')
with (O/'shape_summary.csv').open('w') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
