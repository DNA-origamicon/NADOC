"""Audit all fixed-contact native data and close sufficient water acquisition."""
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
    service=root.parent/(root.name+'-service');status=read(service/'status.json');ack=read(service/'completion_wake_ack.json')
    assert ack['token']==read(service/'completion_wake.json')['token'] and ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('water_completion',root/'executed_source.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    review=m.review(root);plan,base=m.context(root);assessment=read(root/'assessment.json')
    assert assessment['error'] is None and (assessment['completed'],assessment['reused_count'],assessment['new_completed'])==(44,5,39)
    assert review['all_curves_bracketed'] and review['all_sampled_minima_attractive'] and not review['curves_needing_shape_review']
    rows=[]
    for t in plan['tasks']:
        r=read(root/t['label']/'result.json');i=read(checked(t['input']));text=checked(r['native']).read_text()
        assert 'Threads set to 4' in text and 'Memory set to   4.000 GiB' in text
        basis=re.search(r'Basis Set: 6-31G\(D\)\n\s*Blend:\s*6-31G\(D\)\n\s*Number of shells:\s*\d+\n\s*Number of basis functions:\s*(\d+)\n\s*Number of Cartesian functions:\s*(\d+)\n\s*Spherical Harmonics\?:\s*(true|false)',text)
        count={'core':332,'water':19,'complex':351}[i['kind']];assert basis and basis.groups()==(str(count),str(count),'false')
        iterations=re.findall(r'@DF-RHF iter\s+(\d+):\s*('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')',text);assert iterations
        it,e,de,d=iterations[-1];assert abs(float(de))<=1.001e-12 and float(d)<=1.001e-12
        rows.append(dict(label=t['label'],result=pin(root/t['label']/'result.json'),last_iteration=int(it),last_energy_change_hartree=float(de),last_density_residual=float(d),cartesian_basis_functions=count))
    pairs=[]
    for atom in ['O2','O4','H3']:
        a,b=[next(c for c in review['curves'] if c['site']==f'{r}-{atom}') for r in [1,2]]
        differences=np.array([x['raw_interaction_kcal_mol']-y['raw_interaction_kcal_mol'] for x,y in zip(a['points'],b['points'])])
        pairs.append(dict(atom=atom,maximum_raw_difference_kcal_mol=float(np.max(abs(differences))),rms_raw_difference_kcal_mol=float(np.sqrt(np.mean(differences**2)))))
    save(out,dict(at=now(),source=pin(Path(__file__)),passed=True,status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),plan=pin(root/'plan.json'),independent_review=pin(root/'independent_review.json'),
        records=rows,curves=[dict(site=v['site'],diagnostic=v['diagnostic']) for v in review['curves']],ordered_base_comparison=pairs,
        service_seconds=status['finished_at']-status['started_at'],new_records=39,reused_records=5,all_curves_bracketed=True,all_sampled_minima_attractive=True,
        decision='Stop this sufficient QM acquisition. No grid extension, repeated points or additional DIRECT curves justified. Prepare MM charge-fit dataset with explicit fixed baseline/cap charges, source-pinned LJ, exact geometries, frozen objective and identifiability diagnostics before fitting.',
        caution='These are radial fixed-orientation interaction wells, not full water-complex minimum certifications. Near agreement of base-paired curves supports symmetry assessment but does not itself prove a graph automorphism. Interpolated minima remain approximations. No independent validation exposure.',
        charge_dataset_preparation_admitted=True,charge_fitting_admitted=False,minimum_certified=False,simulation_ready=False,cloud_spending_usd=0))
    print(pairs)


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
