from pathlib import Path
import json,hashlib
O=Path(__file__).resolve().parent;out=[]
for p0 in O.glob('*/summary.json'):
 m=json.loads(p0.read_text())
 if not m['production']:continue
 f=next(f for f in m['files'] if f['production']);p=Path(m['package'])/f['config']['structure'];rows=[]
 with p.open() as h:
  for l in h:
   if '!NATOM' in l:break
  for l in h:
   ts=l.split()
   if not ts:continue
   if not ts[1].startswith('D'):break
   rows.append(ts)
 assert len(rows)==m['dna_atoms']
 signature=[r[1:6]+[float(r[6])] for r in rows];out.append(dict(job_id=m['job_id'],dna_atoms=len(rows),charge=sum(float(r[6]) for r in rows),identity_type_charge_sha256=hashlib.sha256(json.dumps(signature).encode()).hexdigest(),mass_total=sum(float(r[7]) for r in rows)))
(O/'dna_parameter_identity.json').write_text(json.dumps(out,indent=2)+'\n')
