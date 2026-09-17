"""Retained local CUDA campaign; run as a module from repository root.
Uses original campaign paths; choose fresh output paths before repeating.
"""
from pathlib import Path
import json,subprocess
import numpy as np
from backend.core.models import Design
from backend.core.nanoparticle import create_gold_nanosphere,build_thiol_conjugation
from backend.api.crud import _geometry_for_design
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_protocol import OxdnaStageSpec,render_stage_input
from backend.core.oxdna_runner import prepare_oxdna_job
from backend.physics.oxdna_mobile_gold import find_mobile_gold_oxdna
root=Path('experiments/mobile_gold/ws/mobile_gold_generated_handles_v1');root.mkdir(exist_ok=False)
records=[]
for end in ['5p','3p']:
 p=create_gold_nanosphere(10);c,h,s=build_thiol_conjugation(p,scheme='direct_thiol',sequence='ACGTACGTACGTACGT',count=3,attach_end=end)
 d=Design(nanoparticles=[p],nanoparticle_conjugations=[c],helices=h,strands=s)
 stage=OxdnaStageSpec('test','production','MD',30000,'CUDA',max_backbone_force=5,max_backbone_force_far=10,seed=171,print_conf_interval_override=1000)
 job=new_oxdna_job(end,[stage.to_status()]);info=prepare_oxdna_job(d,_geometry_for_design(d),job,root,[stage]);jd=job.job_dir(root)
 (jd/'input').write_text(render_stage_input(stage,'topology.top','conf.dat'))
 with (jd/'run.log').open('w') as log:r=subprocess.run([find_mobile_gold_oxdna(),'input'],cwd=jd,stdout=log,stderr=subprocess.STDOUT,timeout=90)
 if r.returncode:raise RuntimeError((jd/'run.log').read_text()[-2000:])
 rows=np.loadtxt(jd/'last_conf.dat',skiprows=3);cp=rows[-1];rot=np.column_stack((cp[3:6],np.cross(cp[6:9],cp[3:6]),cp[6:9]));lengths=[]
 for g in info['mobile_gold']['grafts']:
  x=rows[g['dna']];bb=x[:3]-.34*x[3:6]+.3408*np.cross(x[6:9],x[3:6]);a=cp[:3]+rot@np.array(g['site']);lengths.append(float(np.linalg.norm(bb-a)*.8518))
 records.append(dict(end=end,steps=30000,graft_lengths_nm=lengths,core_translation_nm=float(np.linalg.norm(cp[:3])*.8518)))
(root/'results.json').write_text(json.dumps(records,indent=2));print(records)
