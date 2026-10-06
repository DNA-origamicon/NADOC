"""Read-only native energy, gradient, chemistry and correspondence audit."""
import argparse
from pathlib import Path
import re
import sys
import numpy as np
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.sella_pilot import BOHR,save,now,projected_metrics,force_pass,geometry_audit
from experiments.cpd_anti_additive.validation_gate import read,checked,source

def audit(root,output,recovery=None):
    if output.exists():raise FileExistsError(output)
    master=read(root/'plan.json')
    for pin in read(root/'inputs_lock.json')['files']+master['sources']+master['runtime_sources']:
        checked(pin)
    recovered={}
    if recovery is not None:
        recovery_plan=read(recovery/'plan.json')
        for pin in read(recovery/'inputs_lock.json')['files']+recovery_plan['sources']+recovery_plan['runtime_sources']:
            checked(pin)
        recovered={t['case_id']:t for t in recovery_plan['tasks']}
    records=[]
    for task in master['tasks']:
        original_folder=Path(task['folder'])
        actual=recovered.get(task['case_id'],task)
        folder=Path(actual['folder']);plan=read(checked(actual['plan']))
        graph=read(checked(plan['record']['model_graph']))
        rows=read(folder/'progress.json')['evaluations'];verified=[]
        for row in rows:
            result=read(checked(row['result']));x=np.load(checked(result['geometry']))
            inputs=read(checked(result['input']));native=checked(result['native']).read_text()
            assert np.array_equal(x,inputs['geometry_bohr'])
            assert inputs['method']==plan['method'] and inputs['options']==plan['options']
            assert inputs['elements']==plan['elements']
            energies=[float(v) for v in re.findall(r'^\s*Total Energy\s*=\s*([-+\d.Ee]+)\s*\[Eh\]',native,re.M)]
            assert energies and abs(energies[-1]-result['energy'])<1e-10
            table=native.rsplit('-Total Gradient:',1)[1].split('*** tstop()',1)[0]
            parsed=re.findall(r'^\s*(\d+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*$',table,re.M)
            assert [int(p[0]) for p in parsed]==list(range(1,len(x)+1))
            gradient=np.array([[float(v) for v in p[1:]] for p in parsed])
            error=float(np.max(abs(gradient-np.array(result['gradient']))));assert error<6e-13
            response=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)]
            assert response and max(response)<=plan['options']['solver_convergence']
            chemistry=geometry_audit(x,dict(plan,geometry_bohr=plan['reference_geometry_bohr']),graph)
            assert chemistry['chemistry_passed']
            verified.append(dict(result=row['result'],native_energy=energies[-1],gradient_rounding_error=error))
        projections=[projected_metrics(x,gradient,plan['record']['torsion_indices'],h) for h in [1e-4,1e-5,1e-6]]
        assessment=read(folder/'assessment.json') if (folder/'assessment.json').exists() else {}
        passed=bool(assessment.get('joint_optimizer_converged') and all(force_pass(p,plan['limits']) for p in projections) and chemistry['constraint_passed'])
        records.append(dict(case=task['case_id'],evaluations=verified,completed_gradients=len(rows),
            attempted_gradient_directories=sum(len(list(p.glob('evaluation-*'))) for p in {folder,original_folder}),
            native_stationarity_verified=passed,last_energy_hartree=result['energy'],
            last_result=rows[-1]['result'],projection_checks=projections,chemistry=chemistry))
    delta=(records[1]['last_energy_hartree']-records[0]['last_energy_hartree'])*627.509474
    report=dict(at=now(),records=records,native_gradients_verified=sum(r['completed_gradients'] for r in records),
        completed_stationary_cases=sum(r['native_stationarity_verified'] for r in records),
        trial1_minus_old_reference_kcal=delta,minimum_certified=False,simulation_ready=False,new_qm_evaluations=0)
    save(output,report)
    print({k:v for k,v in report.items() if k!='records'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);p.add_argument('--recovery',type=Path);a=p.parse_args();audit(a.root.resolve(),a.output.resolve(),a.recovery.resolve() if a.recovery else None)
