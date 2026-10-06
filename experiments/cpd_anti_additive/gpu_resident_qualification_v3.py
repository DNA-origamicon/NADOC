"""Bounded GPU-resident qualification. Historical inputs and tolerances stay frozen."""
import os,sys,time,subprocess,traceback,re,json
from pathlib import Path
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive import context_startup_v3 as startup
from experiments.cpd_anti_additive import solvated_engine_v3 as engine
ROOT=REPO/'.development-artifacts/cpd-anti-gpu-resident-qualification-v3'

def run():
 plan=read(ROOT/'plan.json')
 for pin in plan['inputs']:checked(pin)
 assert not read(startup.ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
 start=time.time();deadline=min(start+7200,plan['context_deadline_epoch'])
 with (ROOT/'started.json').open('x') as f:json.dump(dict(at=now(),plan=source(ROOT/'plan.json'),deadline_epoch=deadline),f)
 records=[]
 def native(folder,cfg,threads=2):
  folder.mkdir(parents=True,exist_ok=False);(folder/'run.conf').write_text(cfg)
  assert 'GPUresident on' in cfg and 'bondedGPU 0' not in cfg
  with (folder/'run.log').open('w') as f:
   p=subprocess.run([str(engine.NAMD),f'+p{threads}','+devices','0','run.conf'],cwd=folder,stdout=f,stderr=subprocess.STDOUT,timeout=max(1,deadline-time.time()))
  assert p.returncode==0,f'Native failure {folder}'
  log=(folder/'run.log').read_text();assert 'Running with GPU-resident mode' in log
  assert 'Falling back' not in log
  return parse_log(folder/'run.log')
 try:
  for case in ['anti','control']:
   for kind in ['solute_static','solvent_static']:
    old=engine.ROOT/case/kind;out=ROOT/case/kind
    cfg=[]
    for line in (old/'run.conf').read_text().splitlines():
     key=line.split()[0]
     if key=='bondedGPU':continue
     if key in ['structure','coordinates','binCoordinates','parameters']:
      key,value=line.split(maxsplit=1);line=key+' '+str((old/value).resolve())
     if key=='run':cfg.append('GPUresident on')
     cfg.append(line)
    rows=native(out,'\n'.join(cfg)+'\n')
    a=read(old/'assessment.json');ref=np.load(old/'reference.npz');forces=read_binary(out/'static.force',a['atoms'])
    de=abs(rows[-1]['POTENTIAL']-float(ref['energy_kcal']));df=float(abs(forces-ref['forces_kcal_A']).max())
    result=dict(case=case,fixture=kind,energy_error_kcal=de,force_error_kcal_A=df,energy_limit_kcal=a['energy_limit_kcal'],force_limit_kcal_A=a['force_limit_kcal_A'],passed=bool(de<=a['energy_limit_kcal'] and df<=a['force_limit_kcal_A']),reference=source(old/'reference.npz'),log=source(out/'run.log'),force=source(out/'static.force'))
    save(out/'assessment.json',result);records.append(result)
    # Complete all four inexpensive static diagnostics, but never advance if any fails.
  save(ROOT/'static_assessment.json',dict(at=now(),records=records,passed=all(r['passed'] for r in records)))
  assert all(r['passed'] for r in records),'GPU-resident static equivalence failed; no dynamics'
  def dynamic_config(case,previous,first,seed,steps):
   cfg=startup.config(case,previous/'result.restart.coor',seed,first,previous/'result.restart')
   cfg=cfg.replace('bondedGPU 0\n','GPUresident on\n')
   return cfg+f'run 0\nrun {steps}\noutput result.restart\noutput result\n'
  # Completed native parser is explicitly used during replay; old source is unchanged.
  startup.parse_log=parse_log
  for case in ['anti','control']:
   previous=startup.ROOT/case/'replica-1/startup';out=ROOT/case/'dynamics'
   rows=native(out,dynamic_config(case,previous,50000,41017,25000))
   report,_=startup.review(case,out,50000,75000,50)
   oldrows=parse_log(previous/'run.log');delta=abs(rows[0]['POTENTIAL']-oldrows[-1]['POTENTIAL']);limit=max(.01,1e-6*abs(oldrows[-1]['POTENTIAL']))
   assert delta<=limit
   restart=ROOT/case/'restart-test';rr=native(restart,dynamic_config(case,out,75000,42017,5000))
   rreport,_=startup.review(case,restart,75000,80000,10)
   delta2=abs(rr[0]['POTENTIAL']-rows[-1]['POTENTIAL']);assert delta2<=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
   records.append(dict(case=case,dynamics=report,restart=rreport,initial_energy_error_kcal=delta,restart_energy_error_kcal=delta2))
  benchmark=[]
  for threads in [2,4]:
   out=ROOT/f'benchmark-p{threads}';previous=startup.ROOT/'anti/replica-1/startup'
   native(out,dynamic_config('anti',previous,50000,43017,5000),threads)
   report,_=startup.review('anti',out,50000,55000,10)
   sec=float(re.findall(r'WallClock:\s*([\d.]+)',(out/'run.log').read_text())[-1])
   benchmark.append(dict(threads=threads,duration_ns=.01,wall_seconds=sec,ns_per_day=.01*86400/sec,review=report))
  save(ROOT/'assessment.json',dict(at=now(),passed=True,records=records,benchmark=benchmark,elapsed_seconds=time.time()-start,large_box_qualification_pending=True,simulation_ready=False,minimum_certified=False))
 except BaseException:
  (ROOT/'failure_traceback.txt').write_text(traceback.format_exc())
  save(ROOT/'assessment.json',dict(at=now(),passed=False,records=records,elapsed_seconds=time.time()-start,simulation_ready=False,minimum_certified=False))
  raise

if __name__=='__main__':run()
