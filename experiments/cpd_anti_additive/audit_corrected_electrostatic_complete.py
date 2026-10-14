"""Completion audit and measured admission basis for the six frozen water curves."""
from pathlib import Path
import importlib.util
import re
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now
from experiments.cpd_anti_additive.endpoint_native import NUMBER


def audit(root):
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json')
    ack=read(service/'completion_wake_ack.json');wake=read(service/'completion_wake.json')
    assert ack['token']==wake['token'] and ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('hf_completion',root/'executed_source.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    review=m.review(root);plan,base=m.context(root);assessment=read(root/'assessment.json')
    assert assessment['error'] is None and (assessment['completed'],assessment['reused_count'],assessment['new_completed'])==(10,7,3)
    assert review['df_direct_calibration_passed'] and status['finished_at']-status['started_at']<plan['hard_seconds']
    rows=[];records={};inputs={}
    for t in plan['tasks']:
        r=read(root/t['label']/'result.json');i=read(checked(t['input']));text=checked(r['native']).read_text()
        for phrase in ['Threads set to 4','Memory set to   4.000 GiB']:
            assert phrase in text
        basis=re.search(r'Basis Set: 6-31G\(D\)\n\s*Blend:\s*6-31G\(D\)\n\s*Number of shells:\s*\d+\n\s*Number of basis functions:\s*(\d+)\n\s*Number of Cartesian functions:\s*(\d+)\n\s*Spherical Harmonics\?:\s*(true|false)',text)
        count={'core':332,'water':19,'complex':351}[i['kind']]
        assert basis and basis.groups()==(str(count),str(count),'false')
        algo='DF-RHF' if i['options']['scf_type']=='df' else 'RHF'
        iterations=re.findall('@'+algo+r' iter\s+(\d+):\s*('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')',text)
        assert iterations
        it,e,de,d=iterations[-1];assert abs(float(de))<=1.001e-12 and float(d)<=1.001e-12
        if t['label'] in plan['reused_results']:assert m.reused_result(root,t,plan) is not None
        rows.append(dict(label=t['label'],result=pin(root/t['label']/'result.json'),last_iteration=int(it),last_energy_change_hartree=float(de),last_density_residual=float(d),cartesian_basis_functions=count))
        records[t['label']]=r;inputs[t['label']]=i
    calibration=[]
    for site in plan['calibration_sites']:
        assert inputs[site+'-df']['geometry_angstrom']==inputs[site+'-direct']['geometry_angstrom']
        energies={a:627.509474*(records[site+'-'+a]['energy_hartree']-records['core-'+a]['energy_hartree']-records['water-'+a]['energy_hartree']) for a in ('df','direct')}
        error=abs(energies['df']-energies['direct']);assert error<=.02
        calibration.append(dict(site=site,raw_interaction_kcal_mol=energies,raw_absolute_error_kcal_mol=error,scaled_absolute_error_kcal_mol=1.16*error,df_seconds=records[site+'-df']['wall_seconds'],direct_seconds=records[site+'-direct']['wall_seconds'],direct_over_df_time_ratio=records[site+'-direct']['wall_seconds']/records[site+'-df']['wall_seconds']))
    save(out,dict(at=now(),source=pin(Path(__file__)),passed=True,status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),plan=pin(root/'plan.json'),independent_review=pin(root/'independent_review.json'),
        records=rows,calibration=calibration,df_direct_calibration_passed=True,service_seconds=status['finished_at']-status['started_at'],reused_records=7,new_records=3,
        maximum_raw_error_kcal_mol=max(v['raw_absolute_error_kcal_mol'] for v in calibration),
        decision='The three contact calibrations pass unchanged 0.02 kcal/mol raw criterion. Admit preparation of one bounded DF curve allocation with at most39 new points, reusing three exact pilot contacts and isolated references. No further DIRECT pilot or core rerun justified.',
        limits='Calibration sampled one fixed distance at three contact types; it is not a bound on DF error over every distance/orientation. Review curve shape and mixed contacts before fitting; if anomalies occur use selective diagnostics rather than a full DIRECT sweep.',
        full_curve_preparation_admitted=True,minimum_certified=False,fit_target_accepted=False,simulation_ready=False,cloud_spending_usd=0))
    print(calibration)


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
