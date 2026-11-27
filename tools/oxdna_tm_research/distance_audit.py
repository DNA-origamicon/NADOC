"""Independent geometric audit of native DNA2 minimum-base-distance bins.

Read-only molecular coordinates; no construction, rewriting or relaxation.
POS_BASE=0.4 is verified against the pinned DNA2 native particle implementation.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from backend.core.oxdna_vmmc import duplex_pairs
from tools.oxdna_umbrella.native import digest


def audit(root):
    root=Path(root);m=json.loads((root/'manifest.json').read_text());r=json.loads((root/'result.json').read_text())
    split=m['distance_split']
    if not split: raise ValueError('Requires a two-coordinate campaign')
    pairs=np.array(duplex_pairs(root/'topology.top'));n=int((root/'topology.top').read_text().split()[0])
    result=[];saved={}
    for replica,paths in enumerate(r['production_directories']):
        samples=[];ambiguous=0;hashes={}
        for path in map(Path,paths):
            lines=(path/'trajectory.dat').read_text().splitlines();assert len(lines)%(n+3)==0
            energies={int(row[0]):row for row in np.loadtxt(path/'energy.dat',ndmin=2)}
            for i in range(0,len(lines),n+3):
                step=int(lines[i].split('=')[1]);box=np.fromstring(lines[i+1].split('=')[1],sep=' ')
                a=np.array([list(map(float,x.split())) for x in lines[i+3:i+3+n]])
                delta=a[pairs[:,1],:3]-a[pairs[:,0],:3]
                delta-=box*np.floor(delta/box+.5)
                delta+=.4*(a[pairs[:,1],3:6]-a[pairs[:,0],3:6])
                distance=float(np.linalg.norm(delta,axis=1).min())
                expected=int(distance>split);recorded=int(energies[step][6])
                near=abs(distance-split)<2e-5;ambiguous+=int(near)
                assert near or expected==recorded,(path,step,distance,recorded)
                samples.append([step,distance,recorded,int(energies[step][5])])
            hashes[str(path/'trajectory.dat')]=digest(path/'trajectory.dat')
        a=np.array(samples);saved[f'replica_{replica}']=a
        result.append(dict(replica=replica,frames=len(a),near_boundary_frames=ambiguous,distance_bin_mismatches_away_from_roundoff=0,minimum=float(a[:,1].min()),maximum=float(a[:,1].max()),trajectory_sha256=hashes))
    (root/'distance_audit.json').write_text(json.dumps(dict(replicas=result,split=split,base_offset=.4,qualification='Independent recorded-bin check, not an equilibrium test.'),indent=2)+'\n')
    np.savez_compressed(root/'distance_samples.npz',**saved)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('campaign');a=p.parse_args();print(json.dumps(audit(a.campaign),indent=2))
