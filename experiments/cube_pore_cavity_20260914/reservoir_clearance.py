from pathlib import Path
import numpy as np,json
from scipy.spatial import cKDTree
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated'
g=json.loads((p/'graphene_nanopore.json').read_text());box=np.array(g['periodic_box_nm']);c=np.array(g['pore_center_nm']);n=1679987
heavy=[]
with (p/'cube_pore.psf').open() as f:
 for l in f:
  if '!NATOM' in l:
   for i in range(123167):
    a=next(f).split()
    if float(a[7])>5:heavy.append(i)
   break
out=[]
for stage in ['00_min_enm_k0p5','01_300K_NPT_ENM_k0p5_p10','04_300K_NPT_MGHH_only_p10']:
 xyz=np.memmap(p/'output'/f'cube_pore_{stage}.coor',dtype='<f8',offset=4,shape=(n,3))/10
 dna=xyz[heavy];tree=cKDTree(dna);gaps={}
 for axis in range(3):
  shift=np.eye(3)[axis]*box
  gaps['xyz'[axis]]=float(tree.query(dna+shift,workers=2)[0].min())
 # Raw coordinates preserve the compact origami; do not independently wrap its atoms.
 z=dna[:,2]-c[2]
 rec={'stage':stage,'dna_heavy_min_nm':dna.min(axis=0).tolist(),'dna_heavy_max_nm':dna.max(axis=0).tolist(),'dna_heavy_z_relative_to_membrane_quantiles_nm':np.quantile(z,[0,.01,.5,.99,1]).tolist(),'nearest_axial_periodic_DNA_image_atom_distance_nm':gaps,'normal_gap_between_DNA_extents_nm':float(box[2]-np.ptp(z)),'normal_DNA_to_next_membrane_plane_nm':float(box[2]-z.max())}
 out.append(rec);print(rec,flush=True)
(root/'reservoir_clearance.json').write_text(json.dumps(out,indent=2)+'\n')
