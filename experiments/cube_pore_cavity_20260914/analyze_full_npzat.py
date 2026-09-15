from pathlib import Path
import numpy as np,json,mmap
from scipy.spatial import cKDTree
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;p=root/'full_npzat';n=1679987;water=148711+np.arange(508219)*3
# PSF atom order verified: 123167 DNA + 25544 graphene, then waters and ions.
c=np.array(json.loads((p/'meta.json').read_text())['pore_center_nm']);r=_DcdPrefixFile(p/'run.dcd',0);records=[]
with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
 for f in range(r.n_frames):
  base=r.frame_start+f*r.frame_bytes;box=np.frombuffer(m,'<f8',6,base+4)[[0,2,5]]/10
  xyz=np.stack([np.frombuffer(m,'<f4',n,base+r.cell_record_bytes+a*r.coord_record_bytes+4).copy()/10 for a in range(3)],axis=1)
  rel=xyz-c;rel-=box*np.round(rel/box);rad=np.linalg.norm(rel[water,:2],axis=1)
  grid=np.stack(np.meshgrid(np.arange(-5.8,6,.4),np.arange(-5.8,6,.4),np.arange(-6.8,2,.4),indexing='ij'),axis=-1).reshape(-1,3)+c
  d=cKDTree(xyz[water]%box,boxsize=box).query(grid%box,workers=2)[0]
  records.append({'time_ps':(f+1)*.4,'box_z_nm':float(box[2]),'slice_counts':{str(z):int(np.sum((rad<4)&(abs(rel[water,2]-z)<.25))) for z in [-3,-2,-1,0,1]},'pore_region_water_void_nm3':float(np.sum(d>.4)*.4**3),'graphene_z_range_nm':np.quantile(rel[123167:148711,2],[0,.5,1]).tolist(),'dna_atoms_in_aperture_plane':int(np.sum((np.linalg.norm(rel[:123167,:2],axis=1)<4)&(abs(rel[:123167,2])<.5)))})
r.close();(root/'full_npzat_analysis.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(records[-3:],indent=2))
