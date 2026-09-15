from pathlib import Path
import json,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
initial_void=363.264;initial_z=24.2394
accessible=json.loads((root/'accessible_void.json').read_text())
for mode,color in [('npzat','tab:blue'),('nvt','tab:orange')]:
 p=root/'openmm_full'/mode/'metrics.jsonl'
 if not p.exists():continue
 rows=[]
 for l in p.read_text().splitlines():
  try:rows.append(json.loads(l))
  except json.JSONDecodeError:pass
 if not rows:continue
 t=[r['time_ps'] for r in rows];lab='OpenMM '+('fixed area / normal pressure' if mode=='npzat' else 'fixed volume')
 axs[0,0].plot(t,[r['box_nm'][2] for r in rows],color=color,label=lab)
 ar=accessible.get('OpenMM_'+mode,[])
 if ar:axs[0,1].plot([r['time_ps'] for r in ar],[r['accessible_water_void_nm3'] for r in ar],color=color,label=lab)
 axs[1,0].plot(t,[r['slice_counts']['0'] for r in rows],color=color,label=lab)
 pr=[r for r in rows if 'instantaneous_molecular_pressure_bar' in r]
 axs[1,1].plot([r['time_ps'] for r in pr],[r['instantaneous_molecular_pressure_bar'][2] for r in pr],'o-',color=color,label=lab)
p=root/'full_npzat_analysis.json'
if p.exists():
 r=json.loads(p.read_text());t=[0]+[v['time_ps'] for v in r]
 axs[0,0].plot(t,[initial_z]+[v['box_z_nm'] for v in r],color='tab:green',ls='--',label='NAMD fixed area / normal pressure')
 ar=accessible.get('NAMD_npzat_trace',[])
 if ar:axs[0,1].plot([0]+[r['time_ps'] for r in ar],[initial_void]+[r['accessible_water_void_nm3'] for r in ar],color='tab:green',ls='--')
 axs[1,0].plot(t,[0]+[v['slice_counts']['0'] for v in r],color='tab:green',ls='--')
axs[0,0].set(ylabel='Box height (nm)',title='Lateral cell vectors fixed');axs[0,0].legend(fontsize=8)
axs[0,1].set(ylabel='Accessible local water-void estimate (nm³)',title='Original dry checkpoint: cavity response')
axs[1,0].set(ylabel='Water oxygens in aperture-plane slice',title='A wet aperture would contain ~800 oxygens')
axs[0,1].set_ylim(0,400)
axs[1,0].set_ylim(0,850)
axs[1,0].axhline(800,color='.5',ls=':',lw=.8)
axs[1,1].axhline(1.01325,color='.4',ls='--',lw=.8);axs[1,1].set(ylabel='Instantaneous normal pressure (bar)',title='Single samples; not equilibrium averages')
for a in axs.ravel():a.set_xlabel('Recovery test time (ps)')
fig.savefig(root/'recovery.png',dpi=170);fig.savefig(root/'recovery.pdf')
