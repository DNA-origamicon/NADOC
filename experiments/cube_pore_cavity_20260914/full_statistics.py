from pathlib import Path
import numpy as np,json
root=Path(__file__).resolve().parent;result={}
for mode in ['npzat','nvt']:
 d=root/'openmm_full'/mode;r=[json.loads(l) for l in (d/'metrics.jsonl').read_text().splitlines()];late=[x for x in r if x['time_ps']>=10];tail=[x for x in r if x['time_ps']>=r[-1]['time_ps']-20];pr=[x for x in late if 'instantaneous_molecular_pressure_bar' in x]
 rec={'last_time_ps':r[-1]['time_ps'],'initial_box_z_nm':r[0]['box_nm'][2],'final_box_z_nm':r[-1]['box_nm'][2],'volume_change_percent':100*(r[-1]['box_nm'][2]/r[0]['box_nm'][2]-1),'initial_unexcluded_void_nm3':r[0]['pore_region_water_void_nm3'],'final_unexcluded_void_nm3':r[-1]['pore_region_water_void_nm3'],'pore_plane_water_count_range':[min(x['slice_counts']['0'] for x in r),max(x['slice_counts']['0'] for x in r)],'mean_temperature_after_10ps_K':float(np.mean([x['temperature_K'] for x in late])),'sampled_mean_normal_pressure_after_10ps_bar':float(np.mean([x['instantaneous_molecular_pressure_bar'][2] for x in pr])),'normal_pressure_sample_count':len(pr),'box_z_slope_last_20ps_nm_per_ps':float(np.polyfit([x['time_ps'] for x in tail],[x['box_nm'][2] for x in tail],1)[0]),'completed':'\ncompleted\n' in (root/'openmm_validation'/f'{mode}.log').read_text()}
 result[mode]=rec
(root/'full_statistics.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
