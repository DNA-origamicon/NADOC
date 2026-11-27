import json,csv
from pathlib import Path
import numpy as np
O=Path(__file__).resolve().parent;results=[]
for r in json.loads((O/'inventory.json').read_text()):
 if not r['production']:continue
 logs=[]
 for p in sorted(Path(r['package']).glob('*production*.log')):
  head=[];rows=[];normal=False;warnings=[]
  for line in p.open(errors='replace'):
   if line.startswith('ETITLE:'):head=line.split()[1:]
   elif line.startswith('ENERGY:') and head:
    try:rows.append(dict(zip(head,map(float,line.split()[1:]))))
    except ValueError:pass
   if 'End of program' in line:normal=True
   if any(s in line.lower() for s in ['fatal error','rattle failure','constraint failure']):warnings.append(line.strip())
  if rows:
   name=r['job_id']+'_'+p.stem+'_energy.csv'
   with (O/name).open('w') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
   stats={}
   for k in ['TEMP','VOLUME','POTENTIAL','TOTAL','TOTAL3']:
    if k not in rows[0]:continue
    x=np.array([v[k] for v in rows]);stats[k]=dict(mean=float(x.mean()),min=float(x.min()),max=float(x.max()),quarter_means=[float(a.mean()) for a in np.array_split(x,4)])
   logs.append(dict(source=str(p),trace=name,records=len(rows),first_step=rows[0]['TS'],last_step=rows[-1]['TS'],statistics=stats,normal_exit=normal,errors=warnings))
 results.append(dict(job_id=r['job_id'],logs=logs))
(O/'thermal_results.json').write_text(json.dumps(results,indent=2)+'\n')
