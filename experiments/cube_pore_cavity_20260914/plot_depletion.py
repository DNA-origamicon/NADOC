from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent;data=json.loads((root/'control_analysis.json').read_text());child=root/'open_pore/fill_92_npzat';meta=json.loads((child/'meta.json').read_text());start=json.loads((child/'initial_hydration.json').read_text());offset=meta['parent_time_ps']
fig,axes=plt.subplots(1,3,figsize=(13,4),constrained_layout=True)
for name,label,color in [('fill_92','Resident NVT (failed segment)','0.55'),('fill_92_nvt_offload','NVT continuation (offload)','tab:orange'),('fill_92_npzat','Fixed area / normal pressure','tab:blue')]:
 rows=data.get(name,{}).get('frames',[])
 if not rows:continue
 if name!='fill_92':
  times=[offset]+[offset+r['time_ps'] for r in rows];rows=[start]+rows
 else:times=[r['time_ps'] for r in rows]
 for a,key in zip(axes,['pore_slice_water','total_water_void_nm3','box_nm']):
  values=[r[key][2] if key=='box_nm' else r[key] for r in rows];a.plot(times,values,label=label,color=color)
for a in axes:
 a.axvline(offset,color='.6',ls=':',lw=1);a.set_xlabel('Time since parent minimization (ps)');a.spines[['top','right']].set_visible(False)
axes[0].set_ylabel('Aperture-plane water oxygens');axes[0].set_title('Hydration');axes[0].legend(fontsize=8)
axes[1].set_ylabel('Water-free grid volume (nm³)');axes[1].set_title('Sum across all void regions');axes[1].set_ylim(bottom=0)
axes[2].set_ylabel('Box height (nm)');axes[2].set_title('Lateral cell vectors unchanged')
fig.suptitle('Same depleted-pore checkpoint; pressure intervention at '+str(int(offset))+' ps')
fig.savefig(root/'depletion.png',dpi=170);fig.savefig(root/'depletion.pdf')
