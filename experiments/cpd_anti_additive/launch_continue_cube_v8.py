"""Record the reviewed2ns boundary and launch only the remaining8ns of anti1."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
REPO=Path('/home/jojo/Work/NADOC');sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
art=REPO/'.development-artifacts';root=art/'cpd-anti-gpu-cube-context-v5';oldservice=art/'cpd-anti-cube-resume-anti-1-service-v7';prior=root/'anti/replica-1/validation-resume-v7'
a=read(Path('/tmp/cpd_remainder_audit_v7.json'));assert a['passed']
for pin in a['inputs']:checked(pin)
assert subprocess.run(['pgrep','-x','namd3'],capture_output=True).returncode==1
out=root/'anti/replica-1/validation-remaining-v8';assert not out.exists()
service=art/'cpd-anti-cube-remaining-anti-1-service-v8';service.mkdir(exist_ok=False)
shutil.copy2('/tmp/cpd_remainder_audit_v7.json',prior/'completion_native_audit.json')
shutil.copy2('/tmp/audit_cpd_remainder_v7.py',prior/'completion_auditor_source.py')
review=prior/'completion_review.json'
save(review,dict(at=now(),approved_for_next_run=True,next_job='Remaining8ns of anti1 only',audit=source(prior/'completion_native_audit.json'),assessment=source(prior/'assessment.json'),
 physical_interpretation='Remainder46 saved frames plus endpoint, four periodic restart sets and three native jobs verified using frozen geometry routines. Exact checkpoint CPU and resident energies agree with saved-step energy; endpoint energy agrees. Minimum image35.681A, maximum void witness3.413A; block means299.207K,-2.693bar,1.022825g/cm3,149.825mM addedNaCl. Earlier154frame audit retained, no duplicated tail. Supports continuation, not equilibrium.',
 structural_interpretation='Source-contact fraction0.343–0.686 during0–2ns, final0.486; descriptive variation without independent convergence or mechanics conclusion. Preserve all registered local/stack/contact observables for final matched comparison.',
 necessity='Only2of10ns anti1 validation acquired. Remaining8ns required under fixed six-replica plan; no reason to truncate or repeat completed data.',
 alternatives_and_speed='Remainder3247.045s/ns versus3590.166s/ns conservative reference; current method faster than original preparation. Retainp4 and unchanged timestep/cell; prior p8 advantage<1%, smaller cell failed isolation. No additional tuning or fitting justified.',simulation_ready=False,minimum_certified=False))
save(oldservice/'completion_delivery_verified.json',dict(at=now(),token='d97adfe9-34e3-4413-b96a-1c1f65e1296d',ack=source(oldservice/'completion_wake_ack.json'),review=source(review),audit=source(prior/'completion_native_audit.json')))
worker=service/'continuation_worker.py';shutil.copy2(REPO/'experiments/cpd_anti_additive/continue_cube_v8.py',worker);shutil.copy2(Path(__file__),service/'launch_source.py')
auth=service/'authorization.json';save(auth,dict(at=now(),authorized=True,user_instruction='resume',scope='Complete anti1 from2ns to10ns through eight1ns segments; no other replica admitted.',review=source(review),historical_resume=source(oldservice/'resume_authorization.json'),no_cloud=True,simulation_ready=False))
cp=prior/'segment-02-remainder/result.restart';inputs=a['inputs']+[source(prior/'completion_native_audit.json'),source(review),source(auth),source(worker),source(REPO/'experiments/cpd_anti_additive/gpu_cube_validation_v6.py')]+[source(Path(str(cp)+'.'+e)) for e in ['coor','vel','xsc']]
budget=read(root/'startup_admission_v6.json')['budget'];native=budget['worst_native_seconds_per_ns'];analysis=budget['worst_analysis_seconds_per_ns'];conservative=8*(native+analysis)*1.25+1800;assert conservative<43200
plan=service/'plan.json';start=time.time()
save(plan,dict(at=now(),authorized=True,case='anti',root=str(root.resolve()),engine=source(root/'preparation_engine_v6.py'),authorization=source(auth),prior_audit=source(prior/'completion_native_audit.json'),inputs=inputs,output=str(out.resolve()),checkpoint_prefix=str(cp.resolve()),seed=84017,seed_policy='Declared base84017 plus100*segment (3..10); saved velocities/fullXSC retained, no bitwise RNG continuity claim.',hard_seconds=43200,deadline_epoch=start+43200,reference_native_seconds_per_ns=native,reference_segment_seconds=native+analysis,conservative_budget_seconds=conservative,expected_seconds=30600,scope='8ns in1ns segments; checkpoints100ps,DCD10ps; exact registered observables and unchanged science gates. Stop on failure or>20%slowdown. No next replica before aggregate review.',simulation_ready=False))
unit='cpd-anti-cube-remaining-anti-1-v8';codex=shutil.which('codex');assert codex
for src,dst in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/src,service/dst)
save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),expected_seconds=30600,review_deadline_epoch=start+10*3600,review_deadline_id='remaining-eight-ns-10h-review',self_test=False))
save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(REPO/'.venv/bin/python'),str(worker.resolve()),'--plan',str(plan.resolve())],cwd=str(REPO),expected_seconds=30600,runtime_hours=12,plan=source(plan),completion_semantics='Remaining8ns anti1 only; aggregate10ns scientific/native/performance review before control1.'))
subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=16G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=12h',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','/usr/bin/python3',str((service/'supervisor.py').resolve()),'--supervise',str(service.resolve())],check=True)
print(service.resolve())
