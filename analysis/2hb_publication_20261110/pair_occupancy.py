"""Sparse localization of pairing loss in long trajectories (up to 120 frames/file)."""
import json,re
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from backend.core.cpd_metrics import make_whole_dna
O=Path(__file__).resolve().parent;out=[]
for r in json.loads((O/'results.json').read_text()):
 if r['created'].startswith('2026-10') or r['sampled_frames']<100:continue
 pkg=Path(r['files'][0]['path']).parents[1];wp=json.loads(Path(r['wc_plan']).read_text());pairs=wp['pairs'];flat=np.array([p for w in pairs for p in w['atom_pairs']]);cuts=np.cumsum([0]+[len(w['atom_pairs']) for w in pairs]);limits=np.array([v+.75 for w in pairs for v in w['ref_distances']]);u=mda.Universe(str(pkg/r['config']['structure']));dna=u.select_atoms('segid D*');flags=[];times=[]
 for f in r['files']:
  u.load_new(f['path']);frags=dna.fragments if r['config']['wrapall']=='on' else None
  for i in np.unique(np.linspace(0,len(u.trajectory)-1,min(120,len(u.trajectory))).astype(int)):
   ts=u.trajectory[i];t=ts.time/1000
   if t<r['late_window_start_ns']:continue
   if frags:make_whole_dna(dna,frags,ts.dimensions[:3])
   x=ts.positions;wd=np.linalg.norm(x[flat[:,0]]-x[flat[:,1]],axis=1);flags.append([np.all(wd[cuts[k]:cuts[k+1]]<=limits[cuts[k]:cuts[k+1]]) for k in range(len(pairs))]);times.append(t)
 flags=np.array(flags);out.append(dict(job_id=r['job_id'],design=r['design'],created=r['created'],frames=len(flags),time_ns=times,pairs=[dict(res_a=p['res_a'],res_b=p['res_b'],occupancy=float(flags[:,i].mean())) for i,p in enumerate(pairs)]))
 print(r['design'],r['created'][5:16],'low occupancy',[(p['res_a'],p['res_b'],round(p['occupancy'],2)) for p in out[-1]['pairs'] if p['occupancy']<.7],flush=True)
(O/'long_run_pair_occupancy.json').write_text(json.dumps(out,indent=2)+'\n')
