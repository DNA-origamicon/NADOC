"""Freeze both training-derived depth-only hypotheses before reading validation QM."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked,source,write

root=Path('.development-artifacts/cpd-water-depth-predictions-v1').resolve()
root.mkdir(exist_ok=False)
fit_path=Path('.development-artifacts/cpd-water-depth-feasibility-v1/assessment.json').resolve()
fit=json.loads(fit_path.read_text())
checked(fit['policy'])
policy_path=Path('.development-artifacts/cpd-native-water-predictions-v1/policy.json').resolve()
policy=json.loads(policy_path.read_text())
batch_path=checked(policy['batch'])
batch=json.loads(batch_path.read_text())
refinement_path=Path('.development-artifacts/cpd-water-force-refinement-v1/assessment.json').resolve()
refinement=json.loads(refinement_path.read_text())
base={r['case_id']:r for r in refinement['records']}
models=[]
for model in fit['records']:
    factors=model['pair_epsilon_scale_factors']
    pairs=json.loads(json.dumps(policy['pairs']))
    for name,pair in pairs.items():
        local=name.split(':')[1]
        group='carbonyl' if 'carbonyl' in factors and local in ('O2','O4') else local
        pair['epsilon_kcal_mol']*=factors.get(group,1)
    records=[]
    for case in batch['cases']:
        assert base[case['id']]['numerical_domain_passed']
        xyz=np.array([[float(v) for v in line.split()[1:]] for line in case['molecule'].splitlines() if len(line.split())==4])
        shift=0.
        for i,(name,pair) in enumerate(pairs.items()):
            ratio=(pair['rmin_angstrom']/np.linalg.norm(xyz[i]-xyz[-3]))**6
            shift+=(pair['epsilon_kcal_mol']-policy['pairs'][name]['epsilon_kcal_mol'])*(ratio**2-2*ratio)
        records.append({'case_id':case['id'],'partition':case['partition'],'prediction_kcal_mol':float(base[case['id']]['total_interaction_kcal_mol']+shift),'change_from_native_kcal_mol':float(shift)})
    # Verify exact reconstruction of the training least-squares predictions.
    train={r['case_id']:r['prediction_kcal_mol'] for r in records if r['partition']=='training'}
    assert max(abs(train[r['case_id']]-r['depth_only_prediction_kcal_mol']) for r in model['training_records'])<1e-10
    models.append({'scheme':model['scheme'],'pair_parameters':pairs,'records':records})
write(root/'frozen_predictions.json',{'simulation_ready':False,'gate_effect':'none','validation_qm_values_read':False,'scope':'Both training-only hypotheses frozen prospectively. No selection or release follows from later validation ranking; radial data remain required. These are CPD-water pair-specific epsilon hypotheses, not changes to solute atomic epsilons or intramolecular LJ.','models':models,'sources':[source(p) for p in (fit_path,policy_path,batch_path,refinement_path,Path(__file__))]})
print('Frozen two hypotheses, each with six training and six validation predictions; no validation QM read.')
