"""Audit the first HF allocation, preserving timeout evidence and reusable data."""
from pathlib import Path
import importlib.util
import re
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked,pin,read,save,now,geometry_audit
from experiments.cpd_anti_additive.endpoint_native import NUMBER


def audit(root):
    out=root/'failure_review.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json')
    ack=read(service/'completion_wake_ack.json');wake=read(service/'completion_wake.json')
    assert status['state']==ack['event']=='failed' and status['returncode']==1 and ack['token']==wake['token']
    spec=importlib.util.spec_from_file_location('frozen_hf_partial',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);p,base=m.context(root)
    records=[];values={};pending=[]
    for t in p['tasks']:
        path=root/t['label']/'result.json';inp=read(checked(t['input']));x=np.array(inp['geometry_angstrom'])
        if not path.exists():pending.append(t['label']);continue
        r=read(path);assert r['input']==t['input']
        native=checked(r['native']).read_text()
        na=m.audit_hf_native(native,inp['elements'],x,inp['options']['scf_type'],r['energy_hartree'],r['dipole_au'])
        assert np.max(abs(np.load(checked(r['returned_geometry']))-x))<1e-12
        assert 'Threads set to 4' in native and 'Memory set to   4.000 GiB' in native
        if inp['kind']!='water':assert geometry_audit(x[:36]/m.HF_BOHR_ANGSTROM,base)['passed']
        if inp['grid']:
            assert r['grid']==inp['grid'];g=np.loadtxt(checked(r['grid']));esp=np.loadtxt(checked(r['potentials']))
            assert esp.shape==(len(g),) and np.isfinite(esp).all()
        records.append(dict(label=t['label'],result=pin(path),wall_seconds=r['wall_seconds'],native_audit=na));values[t['label']]=r
    assert len(records)==read(root/'assessment.json')['completed']==7
    assert pending==['1-O2-direct','2-O4-direct','1-H3-direct']
    failed=root/'1-O2-direct/output.dat';text=failed.read_text()
    assert 'Final Energy:' not in text and 'Energy and wave function converged.' not in text
    iterations=re.findall(r'@RHF iter\s+(\d+):\s*('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')',text)
    assert iterations and 'TimeoutExpired' in read(root/'assessment.json')['error']
    rows=[dict(iteration=int(i),energy_hartree=float(e),delta_energy_hartree=float(de),density_residual=float(d)) for i,e,de,d in iterations]
    d=np.array(values['core-df']['dipole_au']);direct=np.array(values['core-direct']['dipole_au'])
    dipole=float(np.linalg.norm(direct)*2.541746473)
    save(out,dict(at=now(),source=pin(Path(__file__)),status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),
        plan=pin(root/'plan.json'),service_seconds=status['finished_at']-status['started_at'],native_completed_records_passed=True,
        reusable_records=records,pending_labels=pending,failed_output=pin(failed),failed_runner=pin(root/'1-O2-direct/runner.log'),traceback=pin(root/'failure_traceback.txt'),
        failed_direct_iterations=rows,failed_task_timeout_seconds=150,failed_density_reduction=rows[0]['density_residual']/rows[-1]['density_residual'],
        failed_task_finished=False,failed_energy_usable=False,raw_last_iterate_not_a_target=True,
        core_direct_dipole_debye=dipole,core_df_direct_dipole_difference_debye=float(np.linalg.norm(d-direct)*2.541746473),
        core_esp_df_direct_rms_difference_au=float(np.sqrt(np.mean((np.loadtxt(checked(values['core-df']['potentials']))-np.loadtxt(checked(values['core-direct']['potentials'])))**2))),
        diagnosis='Per-task wall timeout while DIRECT SCF residual was decreasing; no native convergence record. 150-second limit was undersized relative to the successful 138-second DIRECT core. Seven results pass reopened native audit.',
        recovery='Retain seven completed results and all failed native/scratch files. Re-execute only three missing DIRECT complexes with identical input/options, fresh scratch and 600-second per-task limit in one 2100-second allocation. No valid wavefunction restart was saved; do not infer one from integral scratch.',
        alternatives_review='DF is much faster and remains the candidate for full curves, but three DIRECT comparisons are still required. Relaxing numerical thresholds or changing the algorithm is unnecessary while SCF is progressing; only local scheduling limits change. No core or DF reruns.',
        minimum_certified=False,fit_target_accepted=False,full_curves_admitted=False,simulation_ready=False))
    print(read(out))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
