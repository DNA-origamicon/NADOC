"""Training-only exact LJ depth-scaling diagnostic at frozen native radii."""
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import nnls

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked,source,write

root=Path('.development-artifacts/cpd-water-depth-feasibility-v1').resolve()
root.mkdir(exist_ok=False)
comparison_path=Path('.development-artifacts/cpd-native-water-training-comparison-v3/assessment.json').resolve()
comparison=json.loads(comparison_path.read_text())
for record in comparison['sources']:
    checked(record)
assert comparison['completed_training_cases']==6 and not comparison['validation_values_read']
sensitivity_path=Path('.development-artifacts/cpd-water-lj-identifiability-v1/assessment.json').resolve()
sensitivity=json.loads(sensitivity_path.read_text())
for record in sensitivity['sources']:
    checked(record)
write(root/'policy.json',{'simulation_ready':False,'gate_effect':'none','scope':'Two declared exact linear depth-only feasibility problems with fixed radii and frozen electrostatics. Pair epsilon scales constrained nonnegative but no physical upper bounds; solutions are diagnostic lower bounds, never release parameters. No validation values read.','schemes':['shared_carbonyl_and_H3','separate_O2_O4_and_H3'],'objective':'Unweighted training interaction-energy squared error; no ridge or target rescaling.','sources':[source(p) for p in (comparison_path,sensitivity_path,Path(__file__))]})
lookup={r['case_id']:r for r in comparison['records']}
results=[]
for scheme in sensitivity['records']:
    case_ids=scheme['case_ids']
    design=np.array(scheme['sensitivity_kcal_mol_per_log_parameter'])[:,::2]
    # At fixed nuclear positions, LJ acts on nuclei only and cannot change
    # minimized Drude coordinates. Thus log-epsilon derivative at the native
    # point equals that group's exact energy coefficient for linear scaling.
    mm=np.array([lookup[k]['mm_kcal_mol'] for k in case_ids])
    qm=np.array([lookup[k]['qm_cp_kcal_mol'] for k in case_ids])
    fixed=mm-design@np.ones(design.shape[1])
    scales,_=nnls(design,qm-fixed)
    unconstrained=np.linalg.lstsq(design,qm-fixed,rcond=None)[0]
    predicted=fixed+design@scales
    singular=np.linalg.svd(design/np.linalg.norm(design,axis=0),compute_uv=False)
    gradient=design.T@(predicted-qm)
    assert np.all(gradient[scales<1e-10]>=-1e-8)
    assert np.max(abs(gradient[scales>=1e-10]),initial=0)<1e-8
    results.append({'scheme':scheme['scheme'],'pair_epsilon_scale_factors':dict(zip([c.split(':')[0] for c in scheme['columns'][::2]],map(float,scales))),'unconstrained_scale_factors':unconstrained.tolist(),'nnls_rmse_kcal_mol':float(np.sqrt(np.mean((predicted-qm)**2))),'unconstrained_lower_bound_rmse_kcal_mol':float(np.sqrt(np.mean((fixed+design@unconstrained-qm)**2))),'normalized_condition':float(singular[0]/singular[-1]),'boundary_zero_depth':bool(np.any(scales<1e-10)),'kkt_gradient':gradient.tolist(),'training_records':[{'case_id':k,'qm_kcal_mol':float(q),'depth_only_prediction_kcal_mol':float(p),'error_kcal_mol':float(p-q)} for k,q,p in zip(case_ids,qm,predicted)]})
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','validation_values_read':False,'policy':source(root/'policy.json'),'records':results})
for r in results:
    print(r['scheme'],r['pair_epsilon_scale_factors'],'RMSE',r['nnls_rmse_kcal_mol'],'boundary',r['boundary_zero_depth'])
