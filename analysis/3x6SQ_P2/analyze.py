from pathlib import Path
import numpy as np,json,itertools,csv
from scipy.spatial import cKDTree
from MDAnalysis.coordinates.DCD import DCDReader
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
out=Path(__file__).resolve().parent
p=Path('workspace/md_jobs/9b1151dfca21/package/3x6SQ_norm_skips_namd_solvated')
coords=[];heavy=[];sugar=[];labels=[]
for line in open(p/'3x6SQ_norm_skips.pdb'):
 if line.startswith(('ATOM  ','HETATM')):
  i=len(coords);coords.append([float(line[30:38]),float(line[38:46]),float(line[46:54])]);name=line[12:16].strip();res=line[17:20].strip()
  if res in ('ADE','THY','GUA','CYT'):
   if not name.startswith('H'):heavy.append(i);labels.append(line[72:76].strip()+':'+res+line[22:26].strip()+':'+name)
   if name=="C1'":sugar.append(i)
ref=np.array(coords);heavy=np.array(heavy);sugar=np.array(sugar)
zref=ref[sugar,2];edges=np.linspace(zref.min()+25,zref.max()-25,33);groups=[np.where((zref>=a)&(zref<b))[0] for a,b in zip(edges[:-1],edges[1:])];centers=(edges[:-1]+edges[1:])/2
r=DCDReader(str(next((p/'output').glob('*.dcd'))));print('frames',len(r),'dt ps',r.dt,'DNA heavy',len(heavy),'sugars',len(sugar),flush=True)
plan=json.load(open(p/'nadoc_wc_plan.json'));ap=np.array([a for pair in plan['pairs'] for a in pair['atom_pairs']]);rd=np.array([v for pair in plan['pairs'] for v in pair['ref_distances']]);counts=[len(pair['atom_pairs']) for pair in plan['pairs']];starts=np.r_[0,np.cumsum(counts)]
shifts=np.array([v for v in itertools.product([-1,0,1],repeat=3) if v!=(0,0,0) and next(x for x in v if x)!=-1])
def metric(x,box,t):
 h=x[heavy].astype(float);lo=h.min(0);hi=h.max(0);tree=cKDTree(h);best=1e9;bestinfo=None;contacts=0
 for shift in sorted(shifts,key=lambda v:np.linalg.norm(np.maximum(abs(v*box)-(hi-lo),0))):
  v=shift*box;lower=np.linalg.norm(np.maximum(abs(v)-(hi-lo),0))
  if lower>max(best,10):continue
  query=h+v; bound=max(best if best<1e8 else 100,10)
  keep=np.all((query>=lo-bound)&(query<=hi+bound),axis=1)
  if not keep.any():continue
  ds,ix=tree.query(query[keep],workers=2);contacts+=int((ds<10).sum())
  k=ds.argmin()
  if ds[k]<best:best=float(ds[k]);ai=np.flatnonzero(keep)[k];bestinfo=[shift.tolist(),labels[ai],labels[ix[k]]]
 s=x[sugar];c=np.array([s[g].mean(0) for g in groups]);v=np.diff(c,axis=0);arc=np.linalg.norm(v,axis=1).sum();chord=np.linalg.norm(c[-1]-c[0]);direction=(c[-1]-c[0])/chord;perp=c-c[0]-np.outer((c-c[0])@direction,direction);bend=np.linalg.norm(perp,axis=1).max();vn=v/np.linalg.norm(v,axis=1)[:,None];angles=np.degrees(np.arccos(np.clip((vn[:-1]*vn[1:]).sum(1),-1,1)))
 distances=np.linalg.norm(x[ap[:,0]]-x[ap[:,1]],axis=1);ok=distances<=rd+.75;wc=np.mean([ok[a:b].all() for a,b in zip(starts[:-1],starts[1:])])
 row=dict(time_ns=t,box_x=box[0],box_y=box[1],box_z=box[2],span_x=hi[0]-lo[0],span_y=hi[1]-lo[1],span_z=hi[2]-lo[2],image_min_A=best,image_contact_atoms_10A=contacts,chord_nm=chord/10,contour_nm=arc/10,max_deflection_nm=bend/10,max_turn_deg=angles.max(),max_turn_ref_z_nm=centers[angles.argmax()+1]/10,wc_fraction=wc,image_pair=bestinfo)
 return row,c,angles
rows=[];profiles=[]
for fi in sorted(set(range(0,len(r),10))|{len(r)-1}):
 ts=r[fi];row,c,a=metric(ts.positions,ts.dimensions[:3],ts.time/1000);rows.append(row);profiles.append(c);print(fi,round(row['time_ns'],2),'image',round(row['image_min_A'],2),'chord',round(row['chord_nm'],2),'bend',round(row['max_deflection_nm'],2),flush=True)
json.dump(rows,open(out/'metrics.json','w'),indent=2,default=lambda x: x.item());np.savez(out/'profiles.npz',profiles=profiles,reference_z=centers)
fig,ax=plt.subplots(2,2,figsize=(12,8));t=[v['time_ns'] for v in rows]
for key in ['chord_nm','contour_nm']:ax[0,0].plot(t,[v[key] for v in rows],label=key)
ax[0,0].set_ylabel('Length (nm)');ax[0,0].legend()
ax[0,1].plot(t,[v['image_min_A']/10 for v in rows]);ax[0,1].axhline(1,color='r',ls='--',label='1 nm nonbonded cutoff');ax[0,1].set_ylabel('Closest DNA periodic copy (nm)');ax[0,1].legend()
ax[1,0].plot(t,[v['max_deflection_nm'] for v in rows]);ax[1,0].set_ylabel('Centerline deflection from end chord (nm)')
for i in [0,len(rows)//2,len(rows)-1]:
 c=profiles[i];direction=c[-1]-c[0];direction/=np.linalg.norm(direction);perp=c-c[0]-np.outer((c-c[0])@direction,direction);ax[1,1].plot((centers-centers[0])/10,np.linalg.norm(perp,axis=1)/10,label=f'{t[i]:.1f} ns')
ax[1,1].set_ylabel('Centerline deflection (nm)');ax[1,1].set_xlabel('Reference axial position (nm)');ax[1,1].legend()
for a in [ax[0,0],ax[0,1],ax[1,0]]:a.set_xlabel('Production time (ns)')
fig.suptitle('3x6SQ_norm_skips production — sampled every 1 ns');fig.tight_layout();fig.savefig(out/'diagnostics.png',dpi=170)
print('DONE',flush=True)
