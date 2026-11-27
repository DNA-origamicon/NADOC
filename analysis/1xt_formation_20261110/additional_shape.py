"""Read-only saved-frame analysis. No molecular structures are authored or exported."""
import sys,json,re,hashlib,csv,warnings
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import MDAnalysis as mda
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.core.md_job import MdJob
from backend.core.cpd_metrics import make_whole_dna,dihedral_deg
from backend.core.photoproduct_chemistry import load_chemical_definition,audit_product_chirality
from backend.core.namd_topology import charmm_atom_name
warnings.filterwarnings('ignore',category=DeprecationWarning)
OUT=Path(__file__).resolve().parent

def confread(p):
 return {t[0].lower():t[1] for l in p.read_text().splitlines() if len(t:=l.split())>1 and not t[0].startswith('#')}
def rms(x,y):
 x=x-x.mean(0);y=y-y.mean(0);u,s,v=np.linalg.svd(x.T@y);r=u@np.diag([1,1,np.linalg.det(u@v)])@v
 return np.sqrt(np.mean(np.sum((x@r-y)**2,axis=1)))
def summary(x,dt):
 x=np.asarray(x);n=len(x);v=x-x.mean();f=np.fft.rfft(v,n=2*n);a=np.fft.irfft(f*f.conj())[:n]/np.arange(n,0,-1)
 if a[0]>1e-15:
  a/=a[0];pairs=a[1:2*(n//2)-1].reshape(-1,2).sum(1);stop=next((i for i,p in enumerate(pairs) if p<=0),len(pairs));g=max(1.,1+2*pairs[:stop].sum())
 else:g=1.
 blocks=[float(z.mean()) for z in np.array_split(x,4)]
 return dict(mean=float(x.mean()),sd=float(x.std(ddof=1)),p05=float(np.percentile(x,5)),p95=float(np.percentile(x,95)),quarter_means=blocks,half_shift=float(x[n//2:].mean()-x[:n//2].mean()),ess=float(n/g),tau_int_ns=float(.5*g*dt),acf_caution='Stationarity assumed; single-run estimate, not a convergence certificate')

def main():
 jobs={j.job_id:j for j in MdJob.list_jobs(Path('workspace'))}
 selected=[]
 for j in jobs.values():
  if j.job_id not in ['e4a49b2057a5','29c5b267380f']:continue
  d=json.loads((j.job_dir(Path('workspace'))/'job.json').read_text())
  if len(d['segments'])!=1 or 'production' not in d['segments'][0]['name']:continue
  selected.append((j,d))
 results=[]
 for j,d in sorted(selected,key=lambda x:x[1]['created_at']):
  jd=j.job_dir(Path('workspace'));pkg=jd/d['package_subdir'];seg=d['segments'][0]['name'];cp=pkg/(seg+'.conf');cfg=confread(cp);psf=pkg/cfg['structure']
  files=sorted((pkg/'output').glob(seg+'*.dcd'),key=lambda p:(('.cont' in p.name),p.name));records=[];rows=[];ref=None;last=-1;maxbond=0;chiral_bad=0
  u=mda.Universe(str(psf),str(pkg/cfg['coordinates']));dna=u.select_atoms('segid D*');heavy=dna.select_atoms('not name H*');idx={(a.segid,int(a.resid),a.name):a.index for a in dna};identity=[(a.segid,int(a.resid),a.name) for a in dna]
  # WC plan may live in a sibling replica, only accepted after DNA identity match.
  plans=[pkg/'nadoc_wc_plan.json']
  plans += [q.job_dir(Path('workspace'))/json.loads((q.job_dir(Path('workspace'))/'job.json').read_text())['package_subdir']/'nadoc_wc_plan.json' for q in jobs.values() if q.design_name==j.design_name]
  plan=next((p for p in plans if p.exists()),None)
  assert plan is not None,j.job_id
  wp=json.loads(plan.read_text());srcpsf=next(plan.parent.glob('*.psf'));pu=mda.Universe(str(srcpsf));assert identity==[(a.segid,int(a.resid),a.name) for a in pu.select_atoms('segid D*')]
  pairs=wp['pairs'];flat=np.array([p for w in pairs for p in w['atom_pairs']]);cuts=np.cumsum([0]+[len(w['atom_pairs']) for w in pairs]);limits=np.array([v+.75 for w in pairs for v in w['ref_distances']])
  ends=[('D001',15),('D000',8)];definition=None;cross=[];core=[]
  pm=pkg/'photoproduct_forcefield_manifest.json'
  if pm.exists():
   prod=json.loads(pm.read_text());le=prod['lesions'][0];definition=load_chemical_definition(le['product'],le['stereochemistry']);ep=prod['topology_and_placement_audits']['photoproduct_patch_audit']['patches'][0]['endpoints'];ends=[(e['segid'],int(e['resid'])) for e in sorted(ep,key=lambda e:e['endpoint'])]
   def atom(r):
    n,name=r.split(':');return idx[(*ends[int(n)-1],charmm_atom_name(name))]
   cross=np.array([[atom(b['atom_1']),atom(b['atom_2'])] for b in definition['graph_delta']['bonds_added']]);core=sorted({r for c in definition['product_stereocenters'] for r in [c['atom'],*c['signed_volume_reference_atoms']]});ci=[atom(r) for r in core]
  li=np.array([a.index for a in heavy if any(a.segid==s and abs(int(a.resid)-r)<=1 for s,r in ends)])
  carbon=[idx[(*e,n)] for e in ends for n in ['C5','C6']]
  # Topology-defined helix assignment from saved scaffold domains, no geometry inference.
  design=json.loads((jd/'design.json').read_text());sc=[s for s in design['strands'] if s['strand_type']=='scaffold'];assert len(sc)==1
  mapping={};nr=0
  for dom in sc[0]['domains']:
   step=1 if dom['end_bp']>=dom['start_bp'] else -1
   for bp in range(dom['start_bp'],dom['end_bp']+step,step):nr+=1;mapping[nr]=(dom['helix_id'],bp)
  assert nr==len(u.select_atoms('segid D002').residues)==52
  groups={}
  for p in pairs:
   a,b=[u.atoms[i] for i in p['atom_pairs'][0]]
   if b.segid=='D002':a,b=b,a
   assert a.segid=='D002'
   h,bp=mapping[int(a.resid)]
   if 8<=bp<=27 and bp not in [13,14]:groups.setdefault(h,[]).append((bp,idx[(a.segid,int(a.resid),"C1'")],idx[(b.segid,int(b.resid),"C1'")]))
  groups=[np.array(sorted(v)) for h,v in sorted(groups.items())];assert len(groups)==2
  bonds=dna.bonds.indices;frags=dna.fragments if cfg.get('wrapall')=='on' else None
  for path in files:
   st=path.stat();u.load_new(str(path));head=u.trajectory._file.header;dt=u.trajectory.dt/1000;expected=float(cfg['timestep'])*head['nsavc']/1e6;assert np.isclose(dt,expected,rtol=1e-5)
   stride=max(1,round((.2 if d['created_at']<1790000000 else .1)/dt));n=len(u.trajectory)
   records.append(dict(path=str(path.resolve()),bytes=st.st_size,mtime_ns=st.st_mtime_ns,frames=n,dt_ns=dt,istart=head['istart'],stride=stride,first_ns=float(u.trajectory[0].time/1000),last_ns=float(u.trajectory[-1].time/1000)))
   for ts in u.trajectory[::stride]:
    t=ts.time/1000
    if t<=last+1e-6:continue
    last=t
    if frags:make_whole_dna(dna,frags,ts.dimensions[:3])
    x=ts.positions.astype(float);assert np.isfinite(x[heavy.indices]).all()
    if ref is None:ref=x.copy()
    maxbond=max(maxbond,float(np.linalg.norm(x[bonds[:,0]]-x[bonds[:,1]],axis=1).max()))
    wd=np.linalg.norm(x[flat[:,0]]-x[flat[:,1]],axis=1);wc=np.array([np.all(wd[cuts[i]:cuts[i+1]]<=limits[cuts[i]:cuts[i+1]]) for i in range(len(pairs))])
    centers=[];axes=[]
    for g in groups:
     z=(x[g[:,1]]+x[g[:,2]])/2;centers.append(z.mean(0));_,_,v=np.linalg.svd(z-z.mean(0));axis=v[0];axis*=np.sign(axis@(z[-1]-z[0]));axes.append(axis)
    c5a,c6a,c5b,c6b=x[carbon];dmid=np.linalg.norm((c5a+c6a-c5b-c6b)/2);eta=dihedral_deg(c5a,c6a,c6b,c5b)
    row=[t,rms(x[heavy.indices],ref[heavy.indices]),rms(x[li],ref[li]),np.sqrt(np.mean(np.sum((x[heavy.indices]-x[heavy.indices].mean(0))**2,axis=1))),wc.mean(),np.linalg.norm(centers[1]-centers[0]),np.degrees(np.arccos(np.clip(axes[0]@axes[1],-1,1))),dmid,eta]
    if definition:
     ch=audit_product_chirality(definition,dict(zip(core,x[ci])));chiral_bad+=not ch['passed'];row+=list(np.linalg.norm(x[cross[:,0]]-x[cross[:,1]],axis=1))
    rows.append(row)
   assert (st.st_size,st.st_mtime_ns)==(path.stat().st_size,path.stat().st_mtime_ns)
  arr=np.array(rows);assert maxbond<3.,maxbond
  names=['time_ns','heavy_rmsd_A','local_fit_rmsd_A','Rg_A','wc_fraction','helix_centroid_sep_A','helix_tilt_deg','d_mid_A','eta_deg']+(['crosslink1_A','crosslink2_A'] if definition else [])
  np.savetxt(OUT/(j.job_id+'_trace.csv'),arr,delimiter=',',header=','.join(names),comments='')
  intervals=np.diff(arr[:,0]);typ=float(np.median(intervals));late=arr[arr[:,0]>=arr[0,0]+.25*(arr[-1,0]-arr[0,0])]
  result=dict(job_id=j.job_id,design=j.design_name,created=datetime.fromtimestamp(d['created_at'],ZoneInfo('America/Denver')).isoformat(),status=d['status'],parent=d.get('parent_job_id'),files=records,config={k:cfg.get(k) for k in ['timestep','structure','langevintemp','langevindamping','rigidbonds','wrapall','constraints','extrabondsfile','colvars']},manifest_timestep_fs=prod.get('timestep_fs') if definition else None,psf_sha256=hashlib.sha256(psf.read_bytes()).hexdigest(),wc_plan=str(plan.resolve()),heavy_atoms=len(heavy),wc_pairs=len(pairs),sampled_frames=len(arr),sample_dt_ns=typ,max_sample_gap_ns=float(intervals.max()),max_dna_bond_A=maxbond,chirality_failures=chiral_bad if definition else None,first_last_ns=[float(arr[0,0]),float(arr[-1,0])],late_window_start_ns=float(late[0,0]),statistics={k:summary(late[:,i],typ) for i,k in enumerate(names) if i and k!='eta_deg'})
  results.append(result);(OUT/'additional_shape_results.json').write_text(json.dumps(results,indent=2)+'\n');print(j.design_name,result['created'],result['first_last_ns'],'n',len(arr),'maxbond',round(maxbond,3),flush=True)
if __name__=='__main__':main()
