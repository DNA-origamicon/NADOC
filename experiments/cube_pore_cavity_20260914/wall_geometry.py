from pathlib import Path
import json,numpy as np
root=Path(__file__).resolve().parent;result={}
for name in ['fill_100_npzat','hydrated_300mv','fill_92_npzat','fill_92_nvt_offload']:
 d=root/'open_pore'/name
 if not (d/'run.coor').exists():continue
 m=json.loads((d/'meta.json').read_text());ng=m['graphene_atoms'];n=ng+3*m['water_count']+2*m['salt_pairs'];c=np.array(m['pore_center_nm']);box=np.array((d/'run.xsc').read_text().splitlines()[-1].split()[1:10],float).reshape(3,3).diagonal()/10
 cfg=[l.split() for l in (d/'run.conf').read_text().splitlines() if l.split()];ref_path=Path(next(a[1] for a in cfg if a[0]=='consref'));ref=[]
 with ref_path.open() as f:
  for l in f:
   if not l.startswith(('ATOM  ','HETATM')):continue
   ref.append([float(l[a:a+8])/10 for a in [30,38,46]])
   if len(ref)==ng:break
 xyz=np.memmap(d/'run.coor',dtype='<f8',offset=4,shape=(n,3))[:ng]/10;dr=xyz-np.array(ref);dr-=box*np.round(dr/box);rel=xyz-c;rel-=box*np.round(rel/box)
 result[name]={'box_nm':box.tolist(),'lateral_box_matches_original':bool(np.max(abs(box[:2]-np.array(m['box_nm'])[:2]))<1e-7),'wall_reference_rms_displacement_nm':float(np.sqrt(np.mean(np.sum(dr*dr,axis=1)))),'wall_reference_max_displacement_nm':float(np.max(np.linalg.norm(dr,axis=1))),'wall_normal_min_max_nm':[float(rel[:,2].min()),float(rel[:,2].max())],'closest_graphene_site_to_pore_axis_nm':float(np.linalg.norm(rel[:,:2],axis=1).min())}
(root/'wall_geometry.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
