"""Complete resident qualification at cycle10, reusing the passed 50ps diagnostic."""
import os,sys,time,subprocess,json,re,traceback
from pathlib import Path
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive import context_startup_v3 as s
from experiments.cpd_anti_additive.solvated_engine_v3 import geometry_passed
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.gpu_water_precision_v3 import water_checks
from backend.core.dcd_fast import read_layout,read_frame
ROOT=REPO/'.development-artifacts/cpd-anti-gpu-resident-cycle10-v3'

def config(case,previous,first,seed,resident=True):
 text=s.config(case,previous/'result.restart.coor',seed,first,previous/'result.restart')
 text=text.replace('stepspercycle 1\n','stepspercycle 10\n')
 return text.replace('bondedGPU 0\n','GPUresident on\n') if resident else text

def run():
 plan=read(ROOT/'plan.json');deadline=plan['deadline_epoch']
 for p in plan['inputs']:checked(p)
 assert read(checked(plan['reused_anti_review']))['passed']
 with (ROOT/'started.json').open('x') as f:json.dump(dict(at=now(),plan=source(ROOT/'plan.json')),f)
 def native(out,text,resident=True,threads=2):
  assert time.time()<deadline;out.mkdir(parents=True,exist_ok=False);(out/'run.conf').write_text(text)
  with (out/'run.log').open('w') as log:
   proc=subprocess.run([str(s.NAMD),f'+p{threads}','+devices','0','run.conf'],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=deadline-time.time())
  save(out/'native_exit.json',dict(at=now(),returncode=proc.returncode));assert proc.returncode==0
  log=(out/'run.log').read_text();assert ('Running with GPU-resident mode' in log)==resident
  return parse_log(out/'run.log')
 def review(case,out,first,frames):
  layout=read_layout(out/'result.dcd');assert layout.n_frames==frames and layout.istart==first+500 and layout.nsavc==500
  result=[]
  for i in range(frames+1):
   x=read_frame(out/'result.dcd',layout,i)[0] if i<frames else read_binary(out/'result.coor',s.N)
   assert np.isfinite(x).all();g=geometry(s.ROOT/case,x);w=water_checks(x,i<frames);gap=s.clearance(x)
   result.append(dict(frame=i,geometry=g,water=w,image_clearance_A=gap,passed=bool(geometry_passed(g) and w['passed'] and gap>12)))
  save(out/'frames_review.json',result);assert all(r['passed'] for r in result)
  s.check_checkpoint(out,first+500*frames)
  return dict(log=source(out/'run.log'),frames=source(out/'frames_review.json'),final=source(out/'result.coor'),checkpoint_velocity=source(out/'result.restart.vel'),passed=True)
 results=[]
 try:
  for case in ['anti','control']:
   if case=='anti':
    out=Path(plan['reused_anti_folder']);rows=parse_log(out/'run.log');report=dict(reused_review=plan['reused_anti_review'],passed=True)
    s.check_checkpoint(out,75000)
   else:
    out=ROOT/case/'dynamics';prev=s.ROOT/case/'replica-1/startup'
    rows=native(out,config(case,prev,50000,44017)+'run 25000\noutput result.restart\noutput result\n')
    report=review(case,out,50000,50)
   ref=ROOT/case/'endpoint_reference';rr=native(ref,config(case,out,75000,45017,False)+'run 0\n',False)
   de=abs(rr[-1]['POTENTIAL']-rows[-1]['POTENTIAL']);limit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']));assert de<=limit
   restart=ROOT/case/'restart';rr=native(restart,config(case,out,75000,45017)+'run 5000\noutput result.restart\noutput result\n')
   rreview=review(case,restart,75000,10);delta=abs(rr[0]['POTENTIAL']-rows[-1]['POTENTIAL']);assert delta<=limit
   seconds=float(re.findall(r'WallClock:\s*([\d.]+)',(out/'run.log').read_text())[-1])
   results.append(dict(case=case,threads=2,native_50ps_seconds=seconds,trajectory=report,restart=rreview,endpoint_reference_energy_error_kcal=de,restart_energy_error_kcal=delta,continuity_limit_kcal=limit))
  out=ROOT/'benchmark-p4';prev=s.ROOT/'anti/replica-1/startup'
  native(out,config('anti',prev,50000,44017)+'run 25000\noutput result.restart\noutput result\n',threads=4)
  report=review('anti',out,50000,50);seconds=float(re.findall(r'WallClock:\s*([\d.]+)',(out/'run.log').read_text())[-1])
  bench=dict(threads=4,duration_ns=.05,wall_seconds=seconds,ns_per_day=.05*86400/seconds,review=report)
  save(ROOT/'assessment.json',dict(at=now(),passed=True,results=results,benchmark_p4=bench,qualification='cycle10,no precedingrun0,resident dynamics; representation-aware force checks inherited and pinned. Original cycle1 and double-coordinate solvent failures retained.',large_box_qualification_pending=True,simulation_ready=False,minimum_certified=False))
 except BaseException:
  (ROOT/'failure_traceback.txt').write_text(traceback.format_exc());save(ROOT/'assessment.json',dict(at=now(),passed=False,results=results,simulation_ready=False));raise

if __name__=='__main__':run()
