from pathlib import Path
import numpy as np,json,mmap,struct,sys
from scipy.spatial import cKDTree
from scipy.ndimage import label
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;selected=set(sys.argv[1:]);result=json.loads((root/'control_analysis.json').read_text()) if selected and (root/'control_analysis.json').exists() else {}
for p in sorted((root/'open_pore').iterdir()):
 if selected and p.name not in selected:continue
 if not p.is_dir() or not (p/'run.dcd').exists():continue
 meta=json.loads((p/'meta.json').read_text());ng=meta['graphene_atoms'];nw=meta['water_count'];c=np.array(meta['pore_center_nm']);rows=ng+np.arange(nw)*3
 r=_DcdPrefixFile(p/'run.dcd',0)
 # Header only counts flushed complete frames; sufficient for monitoring.
 if not r.n_frames:r.close();continue
 frames=[]
 conf=[line.split() for line in (p/'run.conf').read_text().splitlines() if line.split()]
 dt=float(next(a[1] for a in conf if a[0]=='timestep'))
 minsteps=sum(int(a[1]) for a in conf if a[0]=='minimize')
 with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
  ints=struct.unpack('<20i',m[8:88]);first,interval=ints[1],ints[2]
  for f in range(r.n_frames):
   base=r.frame_start+f*r.frame_bytes;box=np.frombuffer(m,'<f8',6,base+4)[[0,2,5]]/10
   xyz=np.stack([np.frombuffer(m,'<f4',r.n_atoms,base+r.cell_record_bytes+a*r.coord_record_bytes+4).copy()/10 for a in range(3)],axis=1)
   rel=xyz[rows]-c;rel-=box*np.round(rel/box);rad=np.linalg.norm(rel[:,:2],axis=1)
   axes=[np.arange(.2,b,.4) for b in box];grid=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
   dw=cKDTree(xyz[rows]%box,boxsize=box).query(grid,workers=2)[0];dg=cKDTree(xyz[:ng]%box,boxsize=box).query(grid,workers=2)[0]
   mask=((dw>.4)&(dg>.35)).reshape([len(a) for a in axes]);labels,num=label(mask);sizes=np.bincount(labels.ravel())[1:]
   rec={'frame':f,'step':first+f*interval,'time_ps':(first+f*interval-minsteps)*dt/1000,'box_nm':box.tolist(),'pore_slice_water':int(np.sum((rad<4)&(abs(rel[:,2])<.25))),'pore_core_density_nm3':float(np.sum((rad<3.5)&(abs(rel[:,2])<.25))/(np.pi*3.5**2*.5)),'total_water_void_nm3':float(mask.sum()*.4**3),'largest_water_void_nm3':float(sizes.max()*.4**3) if len(sizes) else 0}
   frames.append(rec)
 r.close()
 energies=[]
 for line in (p/'run.log').read_text(errors='replace').splitlines():
  if line.startswith('ENERGY:'):
   a=line.split();step=int(a[1]);temp=float(a[12]);
   if temp>250:energies.append({'step':step,'temperature':temp,'pressure':float(a[16]),'group_pressure':float(a[17]),'group_pressure_avg':float(a[20]),'volume_nm3':float(a[18])/1000})
 result[p.name]={'n_frames_available':r.n_frames,'n_frames_sampled':len(frames),'frames':frames,'last_energy':energies[-1] if energies else None,'tail_pressure_bar':float(np.mean([v['group_pressure_avg'] for v in energies[-30:]])) if energies else None}
for p in sorted((root/'bulk').iterdir()):
 if selected and 'bulk_'+p.name not in selected:continue
 if not p.is_dir() or not (p/'run.log').exists():continue
 e=[]
 for l in (p/'run.log').read_text(errors='replace').splitlines():
  if l.startswith('ENERGY:'):
   a=l.split()
   if float(a[12])>250:e.append([int(a[1]),float(a[12]),float(a[20]),float(a[18])/1000])
 if e:result['bulk_'+p.name]={'last_step':e[-1][0],'tail_mean_temp_groupPressure_volume':np.mean(np.array(e[-30:])[:,1:],axis=0).tolist(),'samples':len(e)}
(root/'control_analysis.json').write_text(json.dumps(result,indent=2)+'\n')
for name,val in result.items():
 if selected and name not in selected:continue
 summary=dict(val)
 if 'frames' in summary: summary['frames']=summary['frames'][-1:]
 print(name,json.dumps(summary),flush=True)
