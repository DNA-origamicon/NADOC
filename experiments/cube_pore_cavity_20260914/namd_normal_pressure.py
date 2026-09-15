from pathlib import Path
import json,numpy as np
root=Path(__file__).resolve().parent;result={}
for name,skip in [('full_npzat',4),('open_pore/fill_92_npzat',50),('open_pore/fill_92_nvt_offload',50)]:
 d=root/name
 if not (d/'run.log').exists():continue
 cfg=[l.split() for l in (d/'run.conf').read_text().splitlines() if l.split()];dt=float(next(a[1] for a in cfg if a[0]=='timestep'))/1000;rows=[]
 for l in (d/'run.log').read_text().splitlines():
  if l.startswith('GPRESSAVG:'):
   a=l.split();t=int(a[1])*dt
   if t>skip and (name=='full_npzat' or t<=200):rows.append([t]+list(map(float,a[2:])))
 if not rows:continue
 a=np.array(rows);result[name]={'window_after_ps':skip,'last_time_ps':float(a[-1,0]),'samples':len(a),'mean_averaged_pressure_tensor_bar':np.mean(a[:,1:],axis=0).reshape(3,3).tolist(),'std_interval_normal_pressure_bar':float(np.std(a[:,-1],ddof=1)) if len(a)>1 else None,'interpretation':'GPRESSAVG interval-averaged tensor, not aliased instantaneous GPRESSURE samples.'}
(root/'namd_normal_pressure.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
