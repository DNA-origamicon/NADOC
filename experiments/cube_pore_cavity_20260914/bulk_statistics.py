from pathlib import Path
import json,numpy as np
root=Path(__file__).resolve().parent;results={}
for d in sorted((root/'bulk').iterdir()):
 if not (d/'run.conf').exists():continue
 conf=[l.split() for l in (d/'run.conf').read_text().splitlines() if l.split()];dt=float(next(a[1] for a in conf if a[0]=='timestep'))/1000;mini=sum(int(a[1]) for a in conf if a[0]=='minimize');rows=[]
 for l in (d/'run.log').read_text(errors='replace').splitlines():
  if l.startswith('ENERGY:'):
   a=l.split();t=(int(a[1])-mini)*dt
   if t>=50:rows.append([t,float(a[12]),float(a[20]),float(a[18])/1000])
 if not rows:continue
 a=np.array(rows);blocks=[]
 for start in np.arange(50,a[-1,0]-19,20):
  sel=(a[:,0]>=start)&(a[:,0]<start+20)
  if sel.any():blocks.append(a[sel,1:].mean(axis=0))
 b=np.array(blocks);results[d.name]={'sample_interval_ps':float(a[1,0]-a[0,0]) if len(a)>1 else None,'window_ps':[float(a[0,0]),float(a[-1,0])],'columns':['temperature_K','GPRESSAVG_bar','volume_nm3'],'mean':a[:,1:].mean(axis=0).tolist(),'20ps_block_means':b.tolist(),'block_SEM':(b.std(axis=0,ddof=1)/np.sqrt(len(b))).tolist() if len(b)>1 else None,'completed':'End of program' in (d/'run.log').read_text() and 'FATAL ERROR' not in (d/'run.log').read_text()}
(root/'bulk_statistics.json').write_text(json.dumps(results,indent=2)+'\n')
for k,v in results.items():print(k,v['mean'],v['block_SEM'],v['completed'])
