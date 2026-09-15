from pathlib import Path
import numpy as np,json
from scipy.spatial import cKDTree
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';g=json.loads((p/'graphene_nanopore.json').read_text());box=np.array(g['periodic_box_nm']);c=np.array(g['pore_center_nm']);n=1679987
water=148711+np.arange(508219)*3;heavy=[]
with (p/'cube_pore.psf').open() as f:
 for l in f:
  if '!NATOM' in l:
   for i in range(123167):
    a=next(f).split()
    if float(a[7])>5:heavy.append(i)
   break
records=[]
for stage in ['00_min_enm_k0p5','01_300K_NPT_ENM_k0p5_p10','02_300K_NPT_ENM_k0p1_p10','03_300K_NPT_ENM_k0p01_p10','04_300K_NPT_MGHH_only_p10']:
 xyz=np.memmap(p/'output'/f'cube_pore_{stage}.coor',dtype='<f8',offset=4,shape=(n,3))/10
 dist=cKDTree(xyz[heavy]%box,boxsize=box).query(xyz[water]%box,workers=2)[0]
 rel=xyz[water]-c;rel-=box*np.round(rel/box);rad=np.linalg.norm(rel[:,:2],axis=1)
 # Fixed cylinder encompassing the observed pore cavity.
 cavity_count=int(np.sum((rad<5)&(rel[:,2]>-6)&(rel[:,2]<1)))
 item={'stage':stage,'water_within_nm_of_DNA_heavy':{str(d):int(np.sum(dist<d)) for d in [.35,.4,.5,.6,1]},'water_in_pore_cavity_cylinder':cavity_count}
 records.append(item);print(item,flush=True)
(root/'hydration_transfer.json').write_text(json.dumps(records,indent=2)+'\n')
