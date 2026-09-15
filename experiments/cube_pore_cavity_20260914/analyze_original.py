"""Read-only parent trajectory diagnostics: actual molecular geometry and void history."""
from pathlib import Path
import numpy as np,json,mmap
from scipy.spatial import cKDTree
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated'
g=json.loads((p/'graphene_nanopore.json').read_text());c=np.array(g['pore_center_nm']);box=np.array(g['periodic_box_nm'])
res=[];names=[];mass=[]
with (p/'cube_pore_hmr.psf').open() as f:
 for l in f:
  if '!NATOM' in l:
   n=int(l.split()[0])
   for _ in range(n):
    a=next(f).split();res.append(a[3]);names.append(a[4]);mass.append(float(a[7]))
   break
res=np.array(res);names=np.array(names);mass=np.array(mass);water=np.flatnonzero((res=='TIP3')&(names=='OH2'));dna=np.flatnonzero(np.isin(res,['ADE','THY','GUA','CYT'])&(mass>5))
# Fixed independent uniform grid estimates volume empty of water O within 0.4 nm.
axes=[np.arange(.2,b,.4) for b in box];grid=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
records=[]
for path in sorted((p/'output').glob('*p10.dcd')):
 r=_DcdPrefixFile(path,0)
 with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
  for frame in [0,4,14,r.n_frames-1]:
   if frame>=r.n_frames:continue
   base=r.frame_start+frame*r.frame_bytes
   xyz=np.stack([np.frombuffer(m,'<f4',n,base+r.cell_record_bytes+a*r.coord_record_bytes+4).copy()/10 for a in range(3)],axis=1)
   rel=xyz-c;rel-=box*np.round(rel/box);rad=np.linalg.norm(rel[water,:2],axis=1)
   counts=[int(np.sum((rad<4)&(abs(rel[water,2]-z)<.25))) for z in [-3,-2,-1,0,1]]
   tree=cKDTree(xyz[water]%box,boxsize=box);d,_=tree.query(grid,workers=2)
   # Water-void voxel estimate includes solute; report separately and retain raw counts.
   deep=(np.linalg.norm((grid-c+box/2)%box-box/2,axis=1)<6)
   coords=xyz[dna];extent=coords.max(axis=0)-coords.min(axis=0)
   item={'stage':path.stem,'frame':frame,'time_in_stage_ps':(frame+1)*4000*float(next(l.split()[1] for l in (p/(path.stem+'.conf')).read_text().splitlines() if l.startswith('timestep')))/1000,'slice_counts_z_minus3_minus2_minus1_0_1':counts,'water_void_grid_nm3':float(np.mean(d>.4)*np.prod(box)),'dna_extent_nm':extent.tolist(),'water_OH_median_nm':float(np.median(np.linalg.norm(xyz[water+1]-xyz[water],axis=1)))}
   records.append(item);print(item,flush=True)
 r.close()
(root/'original_trajectory_analysis.json').write_text(json.dumps(records,indent=2)+'\n')
