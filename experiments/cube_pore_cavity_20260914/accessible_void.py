"""Accessible cavity diagnostic: exclude grid sites near DNA and graphene.
Grid 0.4 nm; void requires no oxygen within 0.4 nm and no solute heavy atom
within 0.35 nm. A geometric diagnostic, not a thermodynamic vapor volume.
"""
from pathlib import Path
import numpy as np,json,mmap
from scipy.spatial import cKDTree
from scipy.ndimage import label
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';g=json.loads((p/'graphene_nanopore.json').read_text());c=np.array(g['pore_center_nm']);box0=np.array(g['periodic_box_nm']);n=1679987
masses=np.load(root/'openmm_full/masses.npy');heavy=np.flatnonzero(masses[:148711]>5);water=148711+np.arange(508219)*3
axes=[np.arange(-5.8,6,.4),np.arange(-5.8,6,.4),np.arange(-6.8,2,.4)];shape=tuple(len(a) for a in axes);grid=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
def measure(pos,box):
 q=grid%box;dw=cKDTree(pos[water]%box,boxsize=box).query(q,workers=2)[0];ds=cKDTree(pos[heavy]%box,boxsize=box).query(q,workers=2)[0];mask=(dw>.4)&(ds>.35);labels,num=label(mask.reshape(shape));sizes=np.bincount(labels.ravel())[1:]
 return {'accessible_water_void_nm3':float(mask.sum()*.4**3),'largest_accessible_void_component_nm3':float(sizes.max()*.4**3) if len(sizes) else 0.,'unexcluded_water_void_nm3':float((dw>.4).sum()*.4**3)}
result={}
for stage,t in [('00_min_enm_k0p5',0),('01_300K_NPT_ENM_k0p5_p10',240),('02_300K_NPT_ENM_k0p1_p10',720),('03_300K_NPT_ENM_k0p01_p10',1200),('04_300K_NPT_MGHH_only_p10',1680)]:
 pos=np.memmap(p/'output'/f'cube_pore_{stage}.coor',dtype='<f8',offset=4,shape=(n,3))/10-c
 result['original_'+stage]={'time_ps':t,**measure(pos,box0)}
pos=np.memmap(root/'full_wet_static/wet_8ps.coor',dtype='<f8',offset=4,shape=(n,3))/10-c;result['original_8ps']={'time_ps':8,**measure(pos,box0)}
box=np.array((root/'full_npzat/run.xsc').read_text().splitlines()[-1].split()[1:10],float).reshape(3,3).diagonal()/10
pos=np.memmap(root/'full_npzat/run.coor',dtype='<f8',offset=4,shape=(n,3))/10-c;result['NAMD_npzat_10ps']={'time_ps':10,**measure(pos,box)}
r=_DcdPrefixFile(root/'full_npzat/run.dcd',0);trace=[]
with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
 for frame in range(r.n_frames):
  base=r.frame_start+frame*r.frame_bytes;box=np.frombuffer(m,'<f8',6,base+4)[[0,2,5]]/10
  pos=np.stack([np.frombuffer(m,'<f4',n,base+r.cell_record_bytes+a*r.coord_record_bytes+4).copy()/10 for a in range(3)],axis=1)-c
  trace.append({'time_ps':(frame+1)*.4,**measure(pos,box)})
r.close();result['NAMD_npzat_trace']=trace
for mode in ['npzat','nvt']:
 d=root/'openmm_full'/mode
 if not (d/'metrics.jsonl').exists():continue
 metrics={int(round(json.loads(l)['time_ps']/.002)):json.loads(l) for l in (d/'metrics.jsonl').read_text().splitlines() if l.strip()}
 rows=[]
 for f in sorted(d.glob('positions_*.npy')):
  step=int(f.stem.split('_')[1]);r=metrics.get(step)
  if r is None:continue
  pos=np.load(f);rows.append({'time_ps':r['time_ps'],**measure(pos,np.array(r['box_nm']))})
 result['OpenMM_'+mode]=rows
(root/'accessible_void.json').write_text(json.dumps(result,indent=2)+'\n')
for k,v in result.items():print(k,v[-1] if isinstance(v,list) and v else v,flush=True)
