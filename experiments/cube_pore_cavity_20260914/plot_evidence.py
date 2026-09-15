from pathlib import Path
import json,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
transfer=json.loads((root/'hydration_transfer.json').read_text());t=np.array([0,.24,.72,1.2,1.68]);near=np.array([v['water_within_nm_of_DNA_heavy']['0.4'] for v in transfer]);pore=np.array([v['water_in_pore_cavity_cylinder'] for v in transfer])
a=axs[0,0];a.plot(t,(near-near[0])/1000,'o-',label='Within 0.4 nm of DNA');a.plot(t,(pore-pore[0])/1000,'s-',label='Pore-region cylinder');a.axhline(0,color='.7',lw=.7);a.set(xlabel='Parent relaxation time (ns)',ylabel='Change in water count (thousands)',title='Original run: hydration grows as the cavity empties');a.legend()
for name,color in [('nvt','tab:orange'),('npt','tab:blue')]:
 p=root/'bulk'/name/'run.log'
 if not p.exists():continue
 v=[]
 for l in p.read_text(errors='replace').splitlines():
  if l.startswith('ENERGY:'):
   a=l.split()
   if float(a[12])>250:v.append([max(0,(int(a[1])-500)*.002),float(a[18])/1000,float(a[20])])
 if not v:continue
 v=np.array(v);axs[0,1].plot(v[:,0],v[:,1],label=name.upper(),color=color);axs[1,0].plot(v[:,0],v[:,2],alpha=.7,label=name.upper(),color=color)
axs[0,1].set(xlabel='Bulk control time (ps)',ylabel='Cell volume (nm³)',title='Same electrolyte: pressure equilibration changes density');axs[0,1].legend()
axs[1,0].axhline(1.01325,color='k',ls='--',lw=.8,label='1 atm target');axs[1,0].set(xlabel='Bulk control time (ps)',ylabel='Average group pressure (bar)',title='Fixed initial volume retains tensile stress');axs[1,0].legend()
data=json.loads((root/'control_analysis.json').read_text())
for name,val in data.items():
 if not name.startswith('fill_'):continue
 v=val.get('frames',[])
 if v:
  meta=json.loads((root/'open_pore'/name/'meta.json').read_text());offset=meta.get('parent_time_ps',(meta['parent_restart_step']-2000)*.002) if 'parent_restart_step' in meta else 0
  axs[1,1].plot([x['time_ps']+offset for x in v],[x['pore_slice_water'] for x in v],label=name.replace('fill_','water ').replace('_npzat',' + NPzAT').replace('_nvt_offload',' NVT offload'))
axs[1,1].set(xlabel='Time since parent minimization (ps)',ylabel='Water oxygens in pore-plane slice',title='8 nm open pore: hydration controls');axs[1,1].legend()
fig.savefig(root/'evidence.png',dpi=170);fig.savefig(root/'evidence.pdf')
