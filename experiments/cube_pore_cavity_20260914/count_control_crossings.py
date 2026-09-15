from pathlib import Path
import json,numpy as np,mmap
from backend.core.md_trajectory import _DcdPrefixFile
from backend.core.md_ion_paths import crossing_events
root=Path(__file__).resolve().parent;out={}
for p in sorted((root/'open_pore').iterdir()):
 if not p.is_dir() or not (p/'run.dcd').exists():continue
 meta=json.loads((p/'meta.json').read_text());ng=meta['graphene_atoms'];nw=meta['water_count'];count=meta['salt_pairs']*2
 r=_DcdPrefixFile(p/'run.dcd',0)
 if not r.n_frames:r.close();continue
 xyz=np.empty((r.n_frames,count,3));cells=np.empty((r.n_frames,3));rows=ng+nw*3+np.arange(count)
 with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
  for f in range(r.n_frames):
   base=r.frame_start+f*r.frame_bytes;cells[f]=np.frombuffer(m,'<f8',6,base+4)[[0,2,5]]/10
   for a in range(3):xyz[f,:,a]=np.frombuffer(m,'<f4',r.n_atoms,base+r.cell_record_bytes+a*r.coord_record_bytes+4)[rows]/10
 e=crossing_events(xyz,cells,np.array(meta['pore_center_nm']),np.array([0,0,1]),4)
 out[p.name]={'frames':r.n_frames,'saved_plane_crossings':len(e),'positive_z':sum(v[2]>0 for v in e),'negative_z':sum(v[2]<0 for v in e),'distinct_crossing_ions':len(set(v[1] for v in e))};r.close()
(root/'control_crossings.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
