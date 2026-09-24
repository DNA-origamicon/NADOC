"""Run frozen thermal response diagnostics sequentially on local resources."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked,source,write
from experiments.cpd_drude_recovery.run_fresh_esp import PSI4,read_result

parser=argparse.ArgumentParser()
parser.add_argument('--root',required=True,type=Path)
args=parser.parse_args()
root=args.root.resolve()
plan=json.loads((root/'plan.json').read_text())
for item in plan['sources']:checked(item)
for case in plan['cases']:
    for item in case['inputs']:checked(item)
write(root/'execution.json',{'simulation_ready':False,'plan':source(root/'plan.json'),'worker':source(Path(__file__)),'psi4':source(Path(PSI4))})
records=[]
for case in plan['cases']:
    folder=root/case['id']
    if (folder/'output.dat').exists():
        raise FileExistsError('Existing response output requires reconciliation, not overwrite')
    write(root/'progress.json',{'state':'running','case':case['id'],'completed':len(records),'started_epoch':time.time()})
    with (folder/'runner.log').open('w') as log:
        subprocess.run([PSI4,'-i','input.dat','-o','output.dat','-n','4','-s',str(folder/'scratch')],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=1200,check=True)
    esp,dip=read_result(folder)
    zero_esp,zero_dip=read_result(Path(case['baseline']))
    qe,qd=esp-zero_esp,dip-zero_dip
    pe=np.loadtxt(folder/'model_delta_esp_au.txt')
    pd=np.array(case['model_delta_dipole_au'])
    assert np.linalg.norm(qe)>0 and np.linalg.norm(qd)>0
    records.append({'case':case['id'],'esp_response_relative_error':float(np.linalg.norm(pe-qe)/np.linalg.norm(qe)),
        'dipole_change_relative_error':float(np.linalg.norm(pd-qd)/np.linalg.norm(qd)),
        'qm_dipole_change_au':qd.tolist(),'model_max_drude_angstrom':case['model_max_drude_angstrom'],
        'model_domain_error':case['model_domain_error'],'sources':[source(folder/f) for f in ('output.dat','grid_esp.dat')]})
    write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','completed':len(records),'planned':len(plan['cases']),
        'scope':'Prospective thermal response diagnostic for original model; future fitting data, not release validation.',
        'records':records,'execution':source(root/'execution.json')})
write(root/'progress.json',{'state':'completed','completed':len(records),'simulation_ready':False})
