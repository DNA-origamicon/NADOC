"""Audit actual DNA-to-image clearance at every saved frame, including H atoms."""
import itertools
import json
from pathlib import Path
import warnings

import MDAnalysis as mda
from MDAnalysis.lib.formats.libdcd import DCDFile
import numpy as np
from scipy.spatial.distance import cdist
from additional_shape import image_clearance

warnings.filterwarnings('ignore', category=DeprecationWarning)
O=Path(__file__).resolve().parent

def main():
    m=json.loads((O/'2bc15e9e2531/summary.json').read_text())
    f=m['files'][0];path=Path(f['path']);before=path.stat()
    u=mda.Universe(str(Path(m['package'])/f['config']['structure']))
    dna=u.select_atoms('segid D*');reader=DCDFile(str(path));rows=[]
    best=float('inf');best_x=best_box=None;best_frame=None
    for start in range(0,f['frames'],128):
        stop=min(start+128,f['frames'])
        batch=reader.readframes(start=start,stop=stop,indices=dna.indices.astype(np.int64))
        lengths=batch.unitcell[:,[0,2,5]]
        angles=batch.unitcell[:,[1,3,4]]
        assert ((np.isclose(angles,0)|np.isclose(angles,90))).all()
        for i,(xyz,box) in enumerate(zip(batch.xyz,lengths)):
            x=xyz.astype(float);distance,bound=image_clearance(x,box)
            frame=start+i
            rows.append([frame,f['first_ns']+frame*f['dt_ns'],distance,bound,*box])
            if distance<best:
                best=distance;best_x=x.copy();best_box=box.copy();best_frame=frame
        if stop%1024==0 or stop==f['frames']:print(stop,'/',f['frames'],'minimum all-atom image gap',best,flush=True)
    reader.close();after=path.stat()
    assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    a=np.array(rows)
    np.savetxt(O/'all_frame_image_clearance.csv',a,delimiter=',',header='frame,time_ns,nearest_image_all_atoms_A,rotation_bound_A,box_x_A,box_y_A,box_z_A',comments='')
    # Brute-force all-atom audit at the worst frame, independently of the tree.
    brute=float('inf');closest=None
    reach=np.floor((np.ptp(best_x,axis=0)+min(best_box))/best_box).astype(int)
    for shift in itertools.product(*[range(-n,n+1) for n in reach]):
        if shift==(0,0,0):continue
        distances=cdist(best_x,best_x+np.array(shift)*best_box)
        flat=int(np.argmin(distances));v=float(distances.flat[flat])
        if v<brute:
            brute=v;i,j=np.unravel_index(flat,distances.shape)
            closest=dict(atom=[dna[i].segid,int(dna[i].resid),dna[i].name],
                         image_atom=[dna[j].segid,int(dna[j].resid),dna[j].name],image_translation=list(shift))
    np.testing.assert_allclose(brute,best,atol=1e-6)
    out=dict(frames=len(a),dna_atoms=len(dna),includes_hydrogens=True,
             time_step_ns=f['dt_ns'],minimum_A=best,minimum_frame=best_frame,
             minimum_time_ns=float(a[best_frame,1]),minimum_atom_pair=closest,
             brute_force_minimum_A=brute,frames_below_10A=int(sum(a[:,2]<10)),
             frames_below_12A=int(sum(a[:,2]<12)),
             quantiles_A=np.quantile(a[:,2],[0,.01,.05,.5,.95,1]).tolist(),
             min_gap_by_50ns_block_A=[float(x[:,2].min()) for x in np.array_split(a,4)],
             source_size_mtime_unchanged=True,
             scope='Actual all-atom DNA image clearance at every saved 20 ps frame, not every integration step; does not measure long-range finite-size bias or guarantee future conformations.')
    (O/'all_frame_image_clearance.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()
