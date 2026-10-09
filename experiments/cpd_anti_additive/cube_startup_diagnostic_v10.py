"""One bounded native restart diagnostic after startup-only Charm++ failure."""
import os,sys
from pathlib import Path
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.gpu_cube_preparation_v6 import admission,load_engine
from experiments.cpd_anti_additive.validation_gate import read,checked,source
from experiments.cpd_anti_additive.sella_pilot import save,now


def run(path):
 p=admission(read(path));a=read(checked(p['failure_audit']));assert a['checkpoint_verified']
 m=load_engine(p);cp=Path(a['checkpoint_prefix']);box,row=m.box_from_xsc(Path(str(cp)+'.xsc'));assert row[0]==1030000
 assert m.physical('anti',m.read_binary(Path(str(cp)+'.coor'),m.N),box)['passed']
 assert p['seed']==55227 and p['hard_seconds']==900
 out=Path(p['output'])
 result=m.run_stage('anti',out,cp,1030000,50000,p['seed'],5000,p['deadline_epoch'],4,True)
 save(out/'diagnostic_assessment.json',dict(at=now(),native_restart_diagnostic_passed=True,result=source(out/'assessment.json'),endpoint_step=1080000,diagnostic_ns=.1,full_validation_credit_pending_review=True,next_job_requires_model_review=True,simulation_ready=False,minimum_certified=False))

if __name__=='__main__':run(Path(sys.argv[1]))
