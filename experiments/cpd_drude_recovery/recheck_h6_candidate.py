"""Retrospective H6 stress check of the equilibrium-both-blocks candidate."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,checked,write
from experiments.cpd_drude_recovery.predict_h6_scan import main as predict

root=Path('.development-artifacts/cpd-equilibrium-both-h6-recheck-v1').resolve()
root.mkdir(exist_ok=False)
old=Path('.development-artifacts/cpd-independent-h6-scan-v1').resolve()
original_plan=old/'plan.json'
plan=json.loads(original_plan.read_text())
fit=Path('.development-artifacts/cpd-drude-equilibrium-both-blocks-v1/selected_response_fit.json').resolve()
plan['frozen_models']=[source(fit)]
plan['role']='Retrospective development stress test on previously examined targets; not a fresh holdout and no refit in this script.'
plan['original_qm_plan']=source(original_plan)
write(root/'plan.json',plan)
predict(root,Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve())
previous_path=old/'scan_assessment.json'
previous=json.loads(previous_path.read_text())
for record in previous['sources']:checked(record)
assert previous['complete_qm_coverage']
qm={r['case_id']:r for r in previous['models'][0]['rows']}
predictions=json.loads((root/'frozen_mm_predictions.json').read_text())['models'][0]
mm={r['case_id']:r for r in predictions['rows']}
reference=mm['reference']['energy_kcal_mol']
rows=[]
for case in plan['cases']:
    key=case['id']
    if key=='reference':continue
    assert mm[key]['status']=='evaluated'
    energy=mm[key]['energy_kcal_mol']-reference
    gradient=float(np.sum(np.array(mm[key]['gradient_kcal_mol_angstrom'])*np.array(case['direction'])))
    rows.append({'case_id':key,'endpoint':case['endpoint'],'regime':case['regime'],'displacement_angstrom':case['displacement_angstrom'],'qm_relative_energy_kcal_mol':qm[key]['qm_relative_energy_kcal_mol'],'mm_relative_energy_kcal_mol':energy,'energy_error_kcal_mol':energy-qm[key]['qm_relative_energy_kcal_mol'],'projected_gradient_error_kcal_mol_angstrom':gradient-qm[key]['qm_projected_gradient_kcal_mol_angstrom']})
groups=[]
for endpoint in (1,2):
    for regime in ('near_equilibrium','extended_challenge'):
        selected=[r for r in rows if r['endpoint']==endpoint and r['regime']==regime]
        assert len(selected)==(6 if regime=='near_equilibrium' else 2)
        groups.append({'endpoint':endpoint,'regime':regime,'points':len(selected),'energy_rmse_kcal_mol':float(np.sqrt(np.mean([r['energy_error_kcal_mol']**2 for r in selected]))),'gradient_rmse_kcal_mol_angstrom':float(np.sqrt(np.mean([r['projected_gradient_error_kcal_mol_angstrom']**2 for r in selected])))})
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','scope':'Previously exposed H6 scan recheck, not new independent validation. All near and extended targets retained; no parameter changes.','records':rows,'groups':groups,'sources':[source(p) for p in (fit,previous_path,root/'frozen_mm_predictions.json',Path(__file__))]})
print(json.dumps(groups,indent=2))
