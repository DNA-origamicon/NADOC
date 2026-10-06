"""Replay completed pressure-diagnostic files before a new method is admitted."""
import sys,time,itertools
import numpy as np
from scipy.spatial import cKDTree
from experiments.cpd_anti_additive.ensemble_diagnostic_v3_r1 import *

def audit(output,deadline):
 plan=read(OUT/'plan.json')
 for p in plan['inputs']:checked(p)
 records=[];static_records=[];count=0
 for case in ['anti','control']:
  static=[]
  for switch in ['off','on']:
   a=OUT/case/f'static-{switch}-reference';b=OUT/case/f'static-{switch}-resident'
   ar=parse_log(a/'run.log');br=parse_log(b/'run.log');af=read_binary(a/'result.force',N);bf=read_binary(b/'result.force',N)
   de=abs(ar[-1]['POTENTIAL']-br[-1]['POTENTIAL']);df=float(abs(af-bf).max())
   assert de<=max(.001,1e-4*abs(ar[-1]['POTENTIAL'])) and df<=max(.001,1e-4*float(abs(af).max()))
   static.append(dict(switch=switch,energy_error_kcal=de,force_error_kcal_A=df))
  static_records.append(dict(case=case,comparisons=static))
  for stage in ['npt','npt-restart','nvt-probe']:
   p=OUT/case/stage;r=read(p/'assessment.json');rows=parse_log(p/'run.log');first=r['first_step'];last=r['last_step'];layout=read_layout(p/'result.dcd');frames=(last-first)//1000
   assert [v['TS'] for v in rows]==list(range(first,last+1,1000))
   assert read(p/'native_exit.json')['returncode']==0
   native=(p/'run.log').read_text();assert 'Running with GPU-resident mode' in native
   assert ('LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in native)==(stage!='nvt-probe')
   previous=SOURCE/case/'replica-1/restart' if stage=='npt' else OUT/case/('npt' if stage=='npt-restart' else 'npt-restart')
   previous_energy=parse_log(previous/'run.log')[-1]['POTENTIAL']
   restart_error=abs(rows[0]['POTENTIAL']-previous_energy);assert restart_error<=max(.01,1e-6*abs(previous_energy))
   assert (layout.n_atoms,layout.n_frames,layout.nsavc,layout.istart)==(N,frames,1000,first+1000)
   saved=read(p/'frames_review.json');assert len(saved)==frames+1
   finalbox,pins=verify_checkpoint(p,last)
   minima=1e9
   for i in range(frames+1):
    assert time.time()<deadline
    if i<frames:x,cell=read_frame(p/'result.dcd',layout,i);box=cell_to_dimensions(cell)[:3]
    else:x=read_binary(p/'result.coor',N);box=finalbox
    v=physical(case,x,box,i<frames);assert v['passed'];count+=1;minima=min(minima,v['image_clearance_A'])
    for key in ['image_clearance_A','min_water_OO_A','max_OH_error_beyond_storage_A']:assert abs(v[key]-saved[i][key])<1e-9
   ref=parse_log(p/'endpoint-reference/run.log');de=abs(ref[-1]['POTENTIAL']-rows[-1]['POTENTIAL']);assert de<=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
   x=read_binary(p/'result.coor',N);axes=[np.arange(0,b,1.5) for b in finalbox];grid=np.array(np.meshgrid(*axes,indexing='ij')).reshape(3,-1).T
   radii=cKDTree(x%finalbox,boxsize=finalbox).query(grid)[0];j=int(radii.argmax())
   blocks=summarize(rows[1:],250 if stage=='npt' else frames,25 if stage!='npt-restart' else 5,plan['mass_Da'])
   records.append(dict(case=case,stage=stage,geometries=frames+1,native_exit_zero=True,resident_and_piston_modes_verified=True,restart_error_kcal=restart_error,minimum_image_A=minima,endpoint_error_kcal=de,void_witness_A=float(radii[j]),void_radius_continuum_upper_bound_A=float(radii[j])+np.sqrt(3)*1.5/2,raw_statistics=blocks,checkpoints=pins,trajectory=source(p/'result.dcd'),native_log=source(p/'run.log')))
 assert count==1116
 save(Path(output),dict(at=now(),native_and_geometry_replay_passed=True,geometries=count,results=records,static_comparisons=static_records,source=source(Path(__file__)),pressure_interpretation='NPT improves tension/no sampled large cavities; NVT probes and force-switch decision remain separate. No equilibrium or minimum certificate.',simulation_ready=False,minimum_certified=False))
if __name__=='__main__':audit(sys.argv[1],float(sys.argv[2]))
