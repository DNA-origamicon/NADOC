"""Inspect KIMMDY close/aligned hits with the independent isomer classifier."""
import sys,json
from pathlib import Path
import numpy as np
import MDAnalysis as mda
O=Path(__file__).resolve().parent
sys.path.insert(0,str(O.parents[2]))
from experiments.cpd_isomer_formation.geometry import NAMES,features,local_image,catalog,eligible
r=json.loads((O/'summary.json').read_text());z=np.load(O/'timeseries.npz');u=mda.Universe(r['topology'],r['trajectories'][0]);out=[]
for i,p in enumerate(r['pairs']):
 if not p['reactive_frames']:continue
 offset=abs((z['eta_deg'][i]-r['parameters']['eta0_deg']+180)%360-180);hit=np.flatnonzero((z['d_mid_nm'][i]<.45)&(offset<45))
 for frame in hit:
  u.trajectory[int(frame)];x=[]
  for site in [p['site_a'],p['site_b']]:
   res=u.select_atoms(f"segid {site['segid']} and resid {site['resid']}")
   for name in NAMES:x.append(res.select_atoms('name C7 C5M' if name=='C7' else 'name '+name).positions[0])
  f=features(local_image(np.array(x),u.trajectory.ts.dimensions));out.append(dict(pair=p['id'],frame=int(frame),time_ns=float(z['times_ps'][frame]/1000),midpoint_A=float(z['d_mid_nm'][i,frame]*10),eta_deg=float(z['eta_deg'][i,frame]),upstream_score=float(z['upstream_propensity'][i,frame]),isomers=[dict(id=prod['id'],eligible=bool(eligible(f)[j]),**{k:bool(v[j]) if k=='signs_match' else float(v[j]) for k,v in f.items()}) for j,prod in enumerate(catalog())]))
(O/'close_pair_stereochemistry.json').write_text(json.dumps(out,indent=2)+'\n')
assert len(out)==1 and out[0]['pair']=='D001:28~D002:30'
h=out[0];assert not any(p['eligible'] for p in h['isomers'])
text=f'''\n<!-- close-pair follow-up -->
## The one close/aligned frame

**{h['pair']} at {h['time_ns']:.2f} ns** (frame {h['frame']}, zero-based) has midpoint separation {h['midpoint_A']:.3f} Å and dihedral {h['eta_deg']:.2f}°. It is a native/native staple–scaffold pair on the same helix at bp indices 26 and 27, not the intended crossover-insert pair. Its upstream score is {h['upstream_score']:.4f}. The closest midpoint observed for this pair at any time is 3.985 Å, but that minimum-distance frame is not the same as this jointly close/aligned frame.

In the jointly qualifying frame, the two proposed syn C–C distances are **{h['isomers'][0]['min_forming_distance_ang']:.2f} and {h['isomers'][0]['max_forming_distance_ang']:.2f} Å**. It fails the earlier 4 Å two-bond requirement; no channel passes the full eight-isomer screen. This single saved-frame hit is a possible pair to monitor, not a demonstrated formation event or robust product prediction. [Detailed descriptors](close_pair_stereochemistry.json)

The strongest extra/native competitor by mean upstream score is D000:9–D001:15 (rank 4, mean 0.07983, minimum midpoint 4.675 Å); it has no close/aligned frames. The two highest-scoring pairs are native/native staggered staple–scaffold pairs at neighboring bp indices within their respective helices. Their ranks should not be interpreted as eight-isomer yield rankings.

Run `check_close_pair.py` after `assess.py` to reproduce this additional comparison.
'''
p=O/'review.md';base=p.read_text().split('\n<!-- close-pair follow-up -->')[0];p.write_text(base+text)
print('Verified the sole close/aligned observation against the eight-isomer classifier.')
