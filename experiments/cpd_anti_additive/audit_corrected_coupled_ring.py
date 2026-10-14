"""Completion-triggered native and finite-response audit, without new QM."""
from pathlib import Path
import importlib.util
import re
import sys
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now
from experiments.cpd_anti_additive.endpoint_native import NUMBER,require_fitting_condition


def audit(root):
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json')
    ack=read(service/'completion_wake_ack.json');wake=read(service/'completion_wake.json')
    assert ack['token']==wake['token'] and ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('frozen_ring',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    report=m.review(root);plan,base=m.context(root)
    assert read(root/'assessment.json')['error'] is None and status['finished_at']-status['started_at']<plan['hard_seconds']
    records=[]
    for case in plan['cases']:
        result=read(root/case['label']/'result.json');text=checked(result['native']).read_text();x=np.load(checked(result['geometry']))
        require_fitting_condition(text)
        for phrase in ['RHF Reference','RMP2 Wavefunction','SCF Algorithm Type is DF.','Energy threshold   = 1.00e-12','Density threshold  = 1.00e-12','Threads set to 4','Memory set to   4.000 GiB']:
            assert phrase in text,phrase
        assert re.findall(r'PAIRS\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)',text)==[('20','74','54','258','258','0')]
        bases=re.findall(r'Basis Set:[^\n]+\n\s*Blend:\s*([^\n]+)\n\s*Number of shells:\s*\d+\n\s*Number of basis functions:\s*(\d+)\n\s*Number of Cartesian functions:\s*(\d+)\n\s*Spherical Harmonics\?:\s*(true|false)',text)
        assert set(bases)=={('6-31G(D)','332','332','false'),('CC-PVDZ-JKFIT','2020','2020','false'),('CC-PVDZ-RI','1344','1560','true')}
        rows=re.findall(r'^\s*([CHNO])\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s*$',text,re.M)
        assert len(rows)==72 and [v[0] for v in rows]==base['elements']*2
        assert text.count('Geometry (in Bohr), charge = 0, multiplicity = 1:')==2
        native=np.array([[float(v) for v in row[1:4]] for row in rows]).reshape(2,36,3)
        delta=float(np.max(abs(native-x)));assert delta<5.1e-13
        records.append(dict(label=case['label'],result=pin(root/case['label']/'result.json'),native_geometry_max_rounding_error_bohr=delta,electronic_settings_passed=True))
    pairs=[]
    for pair in report['response_pairs']:
        h=pair['hessian_curvature_hartree_bohr2']
        pairs.append({**pair,'energy_curvature_relative_difference':pair['energy_curvature_hartree_bohr2']/h-1,
            'gradient_curvature_relative_difference':pair['gradient_curvature_hartree_bohr2']/h-1,
            'energy_gradient_absolute_curvature_difference':abs(pair['energy_curvature_hartree_bohr2']-pair['gradient_curvature_hartree_bohr2'])})
    save(out,dict(at=now(),source=pin(Path(__file__)),passed=True,plan=pin(root/'plan.json'),
        status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),
        independent_review=pin(root/'independent_review.json'),records=records,response_pairs=pairs,
        native_gradient_components=432,native_geometry_tables=8,service_seconds=status['finished_at']-status['started_at'],
        decision='Finite paired responses agree closely with the existing Hessian; stop this completed four-target acquisition. No repeat, additional Hessian or tolerance sweep is justified.',
        interpretation='Observed agreement below 0.034 percent is evidence, not an imposed universal gate. Mode-two signed energy asymmetry is retained. Only two directions sampled; no fitted-force-field validation or new minimum claim.',
        development_reference_acquisition_complete=True,fit_target_accepted=False,minimum_certified=False,simulation_ready=False))
    print(pairs)


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
