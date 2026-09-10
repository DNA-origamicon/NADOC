"""Compare direct and minimum-image chain reconstruction in saved trajectories."""
import hashlib
import json
from pathlib import Path

import numpy as np


def audit(directory):
    meta=json.loads((directory/'run.json').read_text())
    if meta['status']!='completed':raise ValueError('Only audit immutable completed trajectories')
    n=meta['n'];count=meta.get('chains',1);frames=0;difference=0.;raw_bond=0.;image_bond=0.
    trajectory=directory/'trajectory.dat'
    with trajectory.open() as stream:
        while line:=stream.readline():
            int(line.split('=')[1])
            box=np.array([float(v) for v in stream.readline().split('=')[1].split()])*.8518
            stream.readline()
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(n*count)])*.8518
            if xyz.shape!=(n*count,3) or not np.isfinite(xyz).all():raise ValueError('Invalid frame')
            chains=xyz.reshape(count,n,3);bonds=np.diff(chains,axis=1)
            images=bonds-box*np.rint(bonds/box)
            reconstructed=np.concatenate([np.zeros((count,1,3)),np.cumsum(images,axis=1)],axis=1)
            def rg(x):return np.sqrt(np.mean(np.sum((x-x.mean(axis=1,keepdims=True))**2,axis=2),axis=1))
            difference=max(difference,float(np.max(np.abs(rg(chains)-rg(reconstructed)))))
            raw_bond=max(raw_bond,float(np.linalg.norm(bonds,axis=2).max()))
            image_bond=max(image_bond,float(np.linalg.norm(images,axis=2).max()))
            frames+=1
    if not frames:raise ValueError('Empty trajectory')
    return dict(directory=str(directory),trajectory_sha256=hashlib.sha256(trajectory.read_bytes()).hexdigest(),
        frames=frames,chains=count,n=n,maximum_rg_difference_nm=difference,
        maximum_direct_bond_nm=raw_bond,maximum_minimum_image_bond_nm=image_bond,
        agreement_within_1e_9_nm=difference<1e-9)


def main():
    root=Path(__file__).parent
    selections=['equilibrium_zero_tail_294/n455_t294_s201',
        'equilibrium_zero_tail_381_396/n135_t396_s201',
        'zero_tail_gpu_n36_t381/s701',
        'eos_zero_tail_n135_t294/n135_t294_p10_s401']
    rows=[audit(root/'runs'/s) for s in selections]
    report=dict(status='Selected trajectory representation audit, not a convergence assessment',
        method='Read box in every frame; independently reconstruct each chain by sequential minimum-image bonds; compare each molecular Rg with direct-coordinate analysis.',
        limitations='These selected CPU pivot, GPU MD and CPU NPT trajectories do not prove every future trajectory is unwrapped. No simulation or stored analysis was modified.',results=rows)
    (root/'periodic_analysis_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in rows:print(json.dumps(row))


if __name__=='__main__':main()
