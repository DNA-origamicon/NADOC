"""All saved frames, read-only, all TT pairs; no molecular authoring or simulation."""
import sys,json,hashlib,itertools,warnings
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.formats.libdcd import DCDFile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.core.md_job import MdJob
from backend.core.models import Design
from backend.core.cpd_metrics import designed_weld_pairs
from experiments.cpd_isomer_formation.geometry import NAMES,catalog,features,eligible,planar_reactant_audit,local_image
O=Path(__file__).resolve().parent
warnings.filterwarnings('ignore',category=DeprecationWarning)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def config(p):
 lines=[l.split() for l in p.read_text().splitlines()];d={t[0].lower():t[1] for t in lines if len(t)>1 and not t[0].startswith('#')};d['parameters']=[t[1] for t in lines if len(t)>1 and t[0].lower()=='parameters'];return d

def main():
 products=catalog();audit=planar_reactant_audit(products);assert audit['passed'];grid=list(itertools.product([3.6,4.,4.5],[30.,45.,60.],[.1,.25,.5]));jobs=[j for j in MdJob.list_jobs(Path('workspace')) if j.design_name=='2hb_1xT'];inventory=[]
 for j in jobs:
  jd=j.job_dir(Path('workspace'));d=json.loads((jd/'job.json').read_text());pkg=jd/d['package_subdir'];files=sorted((pkg/'output').glob('*.dcd'));inventory.append(dict(job_id=j.job_id,created=datetime.fromtimestamp(d['created_at'],ZoneInfo('America/Denver')).isoformat(),parent=d.get('parent_job_id'),status=d['status'],job_dir=str(jd.resolve()),package=str(pkg.resolve()),production=any('production' in s['name'] for s in d['segments']),files=[str(f.resolve()) for f in files],design_sha256=sha(jd/'design.json')))
 inventory.sort(key=lambda v:v['created']);(O/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n');(O/'classifier_audit.json').write_text(json.dumps(dict(audit=audit,products=products,grid=grid,source_sha256=sha(Path('experiments/cpd_isomer_formation/geometry.py'))),indent=2)+'\n')
 for rec in inventory:
  jid=rec['job_id'];out=O/jid;out.mkdir(exist_ok=True)
  if (out/'summary.json').exists():print('cached',jid,flush=True);continue
  jd=Path(rec['job_dir']);pkg=Path(rec['package']);design=Design.model_validate_json((jd/'design.json').read_text());welds=designed_weld_pairs(design);assert len(welds)==1;w=welds[0];ends=[(w['segid_a'],w['resid_a']),(w['segid_b'],w['resid_b'])]
  first=Path(rec['files'][0]);stem=first.stem.split('.cont')[0];cfg=config(pkg/(stem+'.conf'));u=mda.Universe(str(pkg/cfg['structure']));dna=u.select_atoms('segid D*');identity=[(a.segid,int(a.resid),a.name) for a in dna]
  tsites=[res for res in dna.residues if res.resname in ['THY','DT','T']];sites=[(r.segid,int(r.resid)) for r in tsites];assert all(e in sites for e in ends)
  atoms=[]
  for res in tsites:
   for name in NAMES:
    a=res.atoms.select_atoms('name C7 C5M' if name=='C7' else 'name '+name);assert len(a)==1;atoms.append(a[0].index)
  pairs=list(itertools.combinations(range(len(sites)),2));wi=next(i for i,p in enumerate(pairs) if {sites[p[0]],sites[p[1]]}==set(ends));pairs[wi]=(sites.index(ends[0]),sites.index(ends[1]));pairidx=np.array([[*range(a*6,a*6+6),*range(b*6,b*6+6)] for a,b in pairs]);bondset={tuple(sorted(map(int,b))) for b in dna.bonds.indices}
  assert all(tuple(sorted((atoms[a*6+ia],atoms[b*6+ib]))) not in bondset for a,b in pairs for ia in [1,2] for ib in [1,2])
  # Reuse existing reference-relative pairing plan only with exact DNA identity ordering.
  plans=[pkg/'nadoc_wc_plan.json']+[Path(v['package'])/'nadoc_wc_plan.json' for v in inventory];wpfile=next(p for p in plans if p.exists());puf=mda.Universe(str(next(wpfile.parent.glob('*.psf'))));assert identity==[(a.segid,int(a.resid),a.name) for a in puf.select_atoms('segid D*')];del puf
  wp=json.loads(wpfile.read_text());flat=np.array([b for p in wp['pairs'] for b in p['atom_pairs']]);cuts=np.cumsum([0]+[len(p['atom_pairs']) for p in wp['pairs']]);limits=np.array([x+.75 for p in wp['pairs'] for x in p['ref_distances']]);local_res={ (s,r+v) for s,r in ends for v in [-1,0,1]};localpairs=np.array([any((u.atoms[int(a)].segid,int(u.atoms[int(a)].resid)) in local_res for b in p['atom_pairs'] for a in b) for p in wp['pairs']])
  selected=np.unique(np.r_[atoms,flat.ravel()]).astype(np.int64);lookup={int(a):i for i,a in enumerate(selected)};ti=np.array([lookup[int(a)] for a in atoms]);fi=np.vectorize(lookup.get)(flat)
  meta={**rec,'sites':sites,'pairs':[dict(a=sites[a],b=sites[b],intended=i==wi,category='intended' if i==wi else ('extra_native' if sites[a] in ends or sites[b] in ends else 'native_native'),same_strand=sites[a][0]==sites[b][0]) for i,(a,b) in enumerate(pairs)],'intended_pair_index':wi,'ordered_endpoints':ends,'wc_plan':str(wpfile),'wc_plan_sha256':sha(wpfile),'topology_sha256':sha(pkg/cfg['structure']),'topology_atoms':len(u.atoms),'dna_atoms':len(dna),'ion_residue_counts':{str(n):int(sum(u.residues.resnames==n)) for n in np.unique(u.residues.resnames) if n not in ['THY','ADE','GUA','CYT']},'files':[]};frames=[];time=[];fileids=[];batches={k:[] for k in ['signs_match','face_margin','max_forming_distance_ang','min_forming_distance_ang','mapped_twist_deg']};raw=[];wcs=[];lwcs=[];pairmasks=[];counts=np.zeros((27,len(pairs),len(products)),np.int64);filecounts=[]
  for fileid,pathstr in enumerate(rec['files']):
   path=Path(pathstr);before=path.stat();stem=path.stem.split('.cont')[0];cp=pkg/(stem+'.conf');c=config(cp);cont=path.stem.split('.cont');actualcp=pkg/(stem+'.resume'+cont[1]+'.conf') if len(cont)>1 else cp
   if actualcp.exists():c=config(actualcp)
   u.load_new(str(path));n=len(u.trajectory);dt=u.trajectory.dt/1000;start=u.trajectory[0].time/1000;header=u.trajectory._file.header;assert np.isclose(dt,float(c['timestep'])*header['nsavc']/1e6,rtol=1e-5);reference=u.atoms.positions[selected].copy();boxref=u.trajectory.ts.dimensions.copy();rawfile=DCDFile(str(path));fc=np.zeros_like(counts)
   fmeta=dict(path=str(path),bytes=before.st_size,mtime_ns=before.st_mtime_ns,frames=n,dt_ns=dt,first_ns=start,last_ns=start+(n-1)*dt,config=c,config_path=str(actualcp if actualcp.exists() else cp),config_sha256=sha(actualcp if actualcp.exists() else cp),parameter_hashes={s:sha(pkg/s) for s in c['parameters'] if (pkg/s).exists()},production='production' in stem)
   meta['files'].append(fmeta)
   for lo in range(0,n,256):
    hi=min(n,lo+256);chunk=rawfile.readframes(start=lo,stop=hi,indices=selected);x=chunk.xyz.astype(float);cell=chunk.unitcell;length=cell[:,[0,2,5]];angles=cell[:,[1,3,4]];assert ((np.isclose(angles,0)|np.isclose(angles,90))).all();assert (length>0).all() and np.isfinite(x).all()
    if lo==0:np.testing.assert_allclose(x[0],reference,atol=1e-5);np.testing.assert_allclose(length[0],boxref[:3],atol=1e-4)
    z=x[:,ti].reshape(len(x),len(sites)*6,3);p=z[:,pairidx].copy();a=p[:,:,1:2,:];b=a+(p[:,:,7:8,:]-a)-length[:,None,None,:]*np.round((p[:,:,7:8,:]-a)/length[:,None,None,:]);p[:,:,:6,:]=a+(p[:,:,:6,:]-a)-length[:,None,None,:]*np.round((p[:,:,:6,:]-a)/length[:,None,None,:]);v=p[:,:,6:,:]-p[:,:,7:8,:];p[:,:,6:,:]=b+v-length[:,None,None,:]*np.round(v/length[:,None,None,:])
    if lo==0:np.testing.assert_allclose(p[0],local_image(z[0,pairidx],boxref),atol=2e-5)
    f=features(p,products);primary=eligible(f);bits=np.sum(primary.astype(np.uint8)*(1<<np.arange(8,dtype=np.uint8)),axis=-1,dtype=np.uint16).astype(np.uint8);pairmasks.append(bits)
    for gi,(d,t,m) in enumerate(grid):fc[gi]+=eligible(f,d,t,m).sum(0)
    for k in batches:batches[k].append(f[k][:,wi])
    raw.append(p[:,wi].astype(np.float32));diff=x[:,fi[:,0]]-x[:,fi[:,1]];diff-=length[:,None,:]*np.round(diff/length[:,None,:]);dist=np.linalg.norm(diff,axis=-1);flags=np.stack([np.all(dist[:,cuts[i]:cuts[i+1]]<=limits[cuts[i]:cuts[i+1]],axis=1) for i in range(len(cuts)-1)],axis=1);wcs.extend(flags.mean(1));lwcs.extend(flags[:,localpairs].mean(1));frames.extend(range(lo,hi));time.extend(start+np.arange(lo,hi)*dt);fileids.extend([fileid]*(hi-lo))
   rawfile.close();after=path.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns);counts+=fc;filecounts.append(fc.tolist());print(rec['created'],path.name,n,'frames intended primary',fc[13,wi].tolist(),flush=True)
  np.savez_compressed(out/'series.npz',time_ns=np.array(time),file_id=np.array(fileids),frame=np.array(frames),wc_fraction=np.array(wcs),local_wc_fraction=np.array(lwcs),coordinates_ang=np.concatenate(raw),pair_primary_bits=np.concatenate(pairmasks),**{k:np.concatenate(v) for k,v in batches.items()})
  meta.update(frames=len(time),grid_counts=counts.tolist(),file_grid_counts=filecounts,source_unchanged=True);(out/'summary.json').write_text(json.dumps(meta,indent=2)+'\n')
if __name__=='__main__':main()
