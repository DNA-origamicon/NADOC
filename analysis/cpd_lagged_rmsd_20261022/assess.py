"""Read-only trajectory assessment; all outputs stay alongside this script."""
import json, csv, sys, hashlib
from pathlib import Path
import numpy as np
import MDAnalysis as mda
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.core.cpd_metrics import make_whole_dna
OUT=Path(__file__).resolve().parent
JOBS=['d6bcdef3d59f','972af34aa9c5','37d39cc6b88f','9b08bed08561','29c5b267380f','bd13e4dfa6c5']

def stats(v):
 return dict(zip(['median','p95','max','mean'],map(float,[np.median(v),np.percentile(v,95),np.max(v),np.mean(v)])))

def aligned(a,b,local):
 ac=a.mean(0);bc=b.mean(0);x=a-ac;y=b-bc
 u,s,v=np.linalg.svd(x.T@y);r=u@np.diag([1,1,np.linalg.det(u@v)])@v
 diff=x@r-y
 whole=np.sqrt(np.mean(np.sum(diff**2,axis=1)))
 local_global=np.sqrt(np.mean(np.sum(diff[local]**2,axis=1)))
 x=a[local]-a[local].mean(0);y=b[local]-b[local].mean(0)
 u,s,v=np.linalg.svd(x.T@y);r=u@np.diag([1,1,np.linalg.det(u@v)])@v
 loc=np.sqrt(np.mean(np.sum((x@r-y)**2,axis=1)))
 return whole,local_global,loc

def main():
 results=[];rows=[]
 for jid in JOBS:
  jd=next(r/jid for r in [Path('workspace/md_jobs'),Path('/media/jojo/Archive/NADOC_archive')] if (r/jid/'job.json').exists())
  job=json.loads((jd/'job.json').read_text());assert job['status']=='completed'
  pkg=jd/job['package_subdir'];seg=job['segments'][0]['name'];conf=pkg/(seg+'.conf')
  d={t[0].lower():t[1] for l in conf.read_text().splitlines() if (t:=l.split()) and len(t)>1 and not t[0].startswith('#')}
  dcd=pkg/'output'/(seg+'.dcd');before=dcd.stat();psf=pkg/d['structure']
  u=mda.Universe(str(psf),str(dcd));dt=float(d['timestep'])*int(d['dcdfreq'])/1000
  assert np.isclose(dt,u.trajectory.dt);assert int(d['dcdfreq'])==u.trajectory._file.header['nsavc']
  dna=u.select_atoms('segid D*');heavy=dna.select_atoms('not name H*');ends=[('D001',15),('D000',8)]
  if 'CPD' in job['design_name']:
   prod=json.loads((pkg/'photoproduct_forcefield_manifest.json').read_text());ep=prod['topology_and_placement_audits']['photoproduct_patch_audit']['patches'][0]['endpoints'];ends=[(e['segid'],int(e['resid'])) for e in ep]
  local=np.array([i for i,a in enumerate(heavy) if any(a.segid==s and abs(int(a.resid)-n)<=1 for s,n in ends)])
  assert len(local)>0
  wrapped=d.get('wrapall','off').lower()=='on';frags=dna.fragments if wrapped else None
  # Inspect actual covalent bond lengths after periodic reconstruction.
  bonds=dna.bonds.indices;bondmax=0.;coords=[]
  n=min(len(u.trajectory),round(20000/dt))
  for ts in u.trajectory[:n]:
   if wrapped:
    assert np.allclose(ts.dimensions[3:],90)
    make_whole_dna(dna,frags,ts.dimensions[:3])
   x=ts.positions;bondmax=max(bondmax,float(np.linalg.norm(x[bonds[:,0]]-x[bonds[:,1]],axis=1).max()))
   coords.append(heavy.positions.copy())
  coords=np.asarray(coords,dtype=np.float64);assert np.isfinite(coords).all();assert bondmax<3.,bondmax
  entry={'job_id':jid,'design':job['design_name'],'source_dcd':str(dcd.resolve()),'source_psf':str(psf.resolve()),'config':{k:d.get(k) for k in ['dcdfreq','timestep','wrapall','langevindamping','rigidbonds']},'source_frames':len(u.trajectory),'analyzed_frames':n,'frame_interval_ps':dt,'duration_ns':n*dt/1000,'heavy_atoms':len(heavy),'local_atoms':len(local),'local_endpoints':ends,'pbc_reconstructed':wrapped,'maximum_DNA_bond_A':bondmax,'source_bytes':before.st_size,'psf_sha256':hashlib.sha256(psf.read_bytes()).hexdigest(),'lags':[]}
  for ps in [10,20,40,80,100,200,400,1000]:
   if ps<dt or not np.isclose(ps/dt,round(ps/dt)):continue
   k=round(ps/dt);vals=np.array([aligned(coords[i],coords[i+k],local) for i in range(n-k)])
   # All time origins, not just one thinning phase; assess late window separately.
   lag={'lag_ps':ps,'stride':k,'pairs':len(vals),'nominal_storage_reduction_pct':100*(1-1/k)}
   for col,name in enumerate(['whole_DNA','local_after_whole_fit','local_after_local_fit']):
    lag[name]=stats(vals[:,col]);lag[name]['last10ns']=stats(vals[np.arange(n-k)*dt>=10000,col])
    rows.append({'job_id':jid,'design':job['design_name'],'lag_ps':ps,'stride':k,'metric':name,'pairs':len(vals),**stats(vals[:,col])})
   entry['lags'].append(lag)
  after=dcd.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
  entry['source_size_mtime_unchanged']=True;results.append(entry)
  (OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n')
  print(jid,job['design_name'],'frames',n,'dt',dt,'max bond',bondmax,flush=True)
 with (OUT/'summary.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 fig,axes=plt.subplots(1,3,figsize=(15,4.5),sharex=True)
 for entry in results:
  label=entry['design'].replace('2hb_1xT_CPD_','') if 'CPD' in entry['design'] else 'Unwelded '+str(int(entry['frame_interval_ps']))+' ps'
  for ax,key,title in zip(axes,['whole_DNA','local_after_whole_fit','local_after_local_fit'],['Whole DNA, pairwise fitted','CPD neighborhood, whole-DNA fit','CPD neighborhood, local fit']):
   l=entry['lags'];line=ax.plot([v['lag_ps'] for v in l],[v[key]['median'] for v in l],label=label)[0];ax.plot([v['lag_ps'] for v in l],[v[key]['p95'] for v in l],ls='--',color=line.get_color(),alpha=.65)
   ax.set(xscale='log',xlabel='Lag (ps)',ylabel='RMSD (Å)',title=title);ax.grid(alpha=.2)
 axes[0].legend(fontsize=7);fig.suptitle('First 20 ns: median (solid), 95th percentile (dashed); all time origins')
 fig.tight_layout();fig.savefig(OUT/'lagged_rmsd.png',dpi=170)
if __name__=='__main__':main()
