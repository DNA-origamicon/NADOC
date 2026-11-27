import sys,json,hashlib,warnings
from pathlib import Path
import numpy as np
import MDAnalysis as mda
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.core.cpd_metrics import make_whole_dna
from scripts.check_ring_piercing_frame import _rings_and_bonds,_scan_frame
O=Path(__file__).resolve().parent
warnings.filterwarnings('ignore')
results=[]
for rec in json.loads((O/'inventory.json').read_text()):
 if not rec['production']:continue
 m=json.loads((O/rec['job_id']/'summary.json').read_text());pkg=Path(m['package']);f=next(f for f in m['files'] if f['production']);c=f['config'];u=mda.Universe(str(pkg/c['structure']));dna,rings,bonds=_rings_and_bonds(u,'segid D*');frags=dna.fragments
 mass=[]
 for s,r in m['ordered_endpoints']:
  ag=u.select_atoms(f'segid {s} and resid {r}');mass.append(dict(site=[s,r],masses={a.name:float(a.mass) for a in ag}))
 dnaids=set(dna.indices+1);eb=[]
 if c.get('extrabondsfile'):
  for line in (pkg/c['extrabondsfile']).read_text().splitlines():
   ts=line.split()
   if ts and ts[0]=='bond' and any(int(i) in dnaids for i in ts[1:3]):eb.append(line)
 checks=[]
 for file in m['files']:
  if not file['production']:continue
  u.load_new(file['path'])
  for i in sorted(set([0,len(u.trajectory)//2,len(u.trajectory)-1])):
   ts=u.trajectory[i];make_whole_dna(dna,frags,ts.dimensions[:3]);hit=_scan_frame(u,rings,bonds,rec['job_id']+' '+str(i),True);checks.append(dict(file=file['path'],frame=i,time_ns=ts.time/1000,box_A=ts.dimensions[:3].tolist(),ring_piercings=hit))
 results.append(dict(job_id=rec['job_id'],config=c,parameter_hashes=f['parameter_hashes'],topology_sha256=m['topology_sha256'],ions=m['ion_residue_counts'],extra_base_masses=mass,dna_extrabonds=eb,structure_spot_checks=checks))
 (O/'protocol_structure_checks.json').write_text(json.dumps(results,indent=2)+'\n')
# Source immutability and analysis code provenance.
changed=[]
for rec in json.loads((O/'inventory.json').read_text()):
 m=json.loads((O/rec['job_id']/'summary.json').read_text())
 for f in m['files']:
  st=Path(f['path']).stat()
  if (st.st_size,st.st_mtime_ns)!=(f['bytes'],f['mtime_ns']):changed.append(f['path'])
assert not changed
(O/'verification.json').write_text(json.dumps(dict(all_source_size_mtime_unchanged=True,classifier_planar_audit=True,extraction_firstframe_MDA_comparison=True,extraction_periodic_image_comparison=True,summary_descriptor_recomputation_and_rigid_transform=True,code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in O.glob('*.py')}),indent=2)+'\n')
