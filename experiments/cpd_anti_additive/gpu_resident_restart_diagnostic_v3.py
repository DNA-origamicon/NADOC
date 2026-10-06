"""Two registered resident update/restart diagnostics; no parameter or cutoff changes."""
import os,sys,time,subprocess,json,traceback,re
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive import context_startup_v3 as s
from experiments.cpd_anti_additive.solvated_engine_v3 import geometry_passed
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from backend.core.dcd_fast import read_layout,read_frame
ROOT=REPO/'.development-artifacts/cpd-anti-gpu-restart-diagnostic-v3'

def solvent(x):
 oxygen=x[3043:30712:3]%s.BOX
 d,_=cKDTree(oxygen,boxsize=s.BOX).query(oxygen,k=2)
 w=x[3043:30712].reshape(-1,3,3);oh=w[:,1:]-w[:,:1];oh-=np.rint(oh/s.BOX)*s.BOX
 lengths=np.linalg.norm(oh,axis=2)
 return dict(minimum_periodic_OO_A=float(d[:,1].min()),max_rigid_OH_error_A=float(abs(lengths-.9572).max()))

def run():
 plan=read(ROOT/'plan.json')
 for p in plan['inputs']:checked(p)
 with (ROOT/'started.json').open('x') as f:json.dump(dict(at=now(),plan=source(ROOT/'plan.json')),f)
 deadline=plan['deadline_epoch'];results=[]
 def native(out,cfg):
  assert time.time()<deadline
  out.mkdir(parents=True,exist_ok=False);(out/'run.conf').write_text(cfg)
  with (out/'run.log').open('w') as log:
   p=subprocess.run([str(s.NAMD),'+p2','+devices','0','run.conf'],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=deadline-time.time())
  save(out/'native_exit.json',dict(at=now(),returncode=p.returncode))
  assert p.returncode==0
  return parse_log(out/'run.log')
 def cfg(previous,first,cycle,resident=True):
  c=s.config('anti',previous/'result.restart.coor',44017,first,previous/'result.restart')
  c=c.replace('stepspercycle 1\n',f'stepspercycle {cycle}\n')
  return c.replace('bondedGPU 0\n','GPUresident on\n') if resident else c
 def review(out,first,count):
  layout=read_layout(out/'result.dcd');assert layout.n_frames==count and layout.nsavc==500 and layout.istart==first+500
  records=[]
  for i in range(count+1):
   x=read_frame(out/'result.dcd',layout,i)[0] if i<count else read_binary(out/'result.coor',s.N)
   assert np.isfinite(x).all()
   g=geometry(s.ROOT/'anti',x);v=solvent(x);gap=s.clearance(x)
   records.append(dict(frame=i,final=i==count,geometry=g,solvent=v,image_clearance_A=gap,passed=bool(geometry_passed(g) and gap>12 and v['minimum_periodic_OO_A']>2 and v['max_rigid_OH_error_A']<1e-5)))
  save(out/'frames_review.json',records);s.check_checkpoint(out,first+count*500)
  return all(r['passed'] for r in records)
 try:
  for cycle in plan['cycles']:
   folder=ROOT/f'cycle-{cycle}';out=folder/'dynamics';error=None
   try:
    previous=s.ROOT/'anti/replica-1/startup'
    rows=native(out,cfg(previous,50000,cycle)+'run 25000\noutput result.restart\noutput result\n')
    passed=review(out,50000,50)
    r=dict(cycle=cycle,no_preceding_run_zero=True,trajectory_passed=passed,log=source(out/'run.log'),frames=source(out/'frames_review.json'))
    if passed:
     # Diagnostic static reference only, never a slower dynamics fallback.
     ref=folder/'endpoint_reference';rr=native(ref,cfg(out,75000,cycle,False)+'run 0\n')
     delta=abs(rr[-1]['POTENTIAL']-rows[-1]['POTENTIAL']);limit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
     r.update(endpoint_energy_error_kcal=delta,endpoint_energy_limit_kcal=limit)
     assert delta<=limit,'Saved endpoint differs from live GPU potential'
     restart=folder/'restart';rr=native(restart,cfg(out,75000,cycle)+'run 5000\noutput result.restart\noutput result\n')
     r['restart_passed']=review(restart,75000,10)
     r['restart_energy_error_kcal']=abs(rr[0]['POTENTIAL']-rows[-1]['POTENTIAL'])
     assert r['restart_passed'] and r['restart_energy_error_kcal']<=limit
     r['passed']=True
    else:r['passed']=False
   except BaseException as exc:
    folder.mkdir(exist_ok=True,parents=True);(folder/'failure_traceback.txt').write_text(traceback.format_exc());r=dict(cycle=cycle,passed=False,error=repr(exc))
   results.append(r);save(folder/'assessment.json',r)
  save(ROOT/'assessment.json',dict(at=now(),results=results,any_diagnostic_passed=any(r['passed'] for r in results),qualification_complete=False,simulation_ready=False,minimum_certified=False))
  assert any(r['passed'] for r in results),'Neither registered resident restart diagnostic passed'
 except BaseException:
  (ROOT/'failure_traceback.txt').write_text(traceback.format_exc());raise

if __name__=='__main__':run()
