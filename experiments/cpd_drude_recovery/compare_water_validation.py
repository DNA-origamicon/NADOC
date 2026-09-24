"""Audit completed independent water targets against prospectively frozen models."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.audit_water_results import audit_output, digest
from experiments.cpd_drude_recovery.campaign import checked, source, write

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--additional-cloud',type=Path)
args = parser.parse_args()
root = args.root.resolve()
root.mkdir(exist_ok=False)
cloud = Path('.development-artifacts/cpd-drude-cloud-budget5-v1').resolve()
predpath = Path('.development-artifacts/cpd-water-depth-predictions-v1/frozen_predictions.json').resolve()
pred = json.loads(predpath.read_text())
assert pred['validation_qm_values_read'] is False
for record in pred['sources']:
    checked(record)
batchpath = cloud/'batch.json'
batch = json.loads(batchpath.read_text())
assert batch['energy_scale'] == 1 and batch['distance_offset'] == 0
checked(batch['worker'])
assert digest(cloud/'worker.py') == batch['worker']['sha256']
basepath = Path('.development-artifacts/cpd-water-force-refinement-v1/assessment.json').resolve()
base = json.loads(basepath.read_text())
models = {'native': {r['case_id']: r['total_interaction_kcal_mol'] for r in base['records']}}
for m in pred['models']:
    models[m['scheme']] = {r['case_id']: r['prediction_kcal_mol'] for r in m['records']}
batches = [(cloud,batchpath,batch)]
if args.additional_cloud:
    extra=args.additional_cloud.resolve()
    extra_path=extra/'batch.json'
    extra_batch=json.loads(extra_path.read_text())
    assert extra_batch['method']==batch['method']
    assert extra_batch['energy_scale']==1 and extra_batch['distance_offset']==0
    checked(extra_batch['worker'])
    assert digest(extra/'worker.py')==extra_batch['worker']['sha256']
    original_cases={c['id']:c for c in batch['cases']}
    assert len({c['id'] for c in extra_batch['cases']})==len(extra_batch['cases'])
    for c in extra_batch['cases']:
        assert c == original_cases[c['id']], 'Resumed case definition changed'
    batches.append((extra,extra_path,extra_batch))
records = []
planned = [c for c in batch['cases'] if c['partition'] == 'validation']
write(root/'plan.json', {'simulation_ready': False, 'gate_effect': 'none',
    'scope': 'Read every completed validation target, report every frozen model, no model selection or refitting. Partial results cannot establish validation of the batch.',
    'sources': [source(p) for p in (predpath, basepath, Path(__file__))]+[source(p) for _,p,_ in batches]})
for case in planned:
    available=[(r,p,b) for r,p,b in batches if (r/'results'/case['id']/'result.json').exists()]
    assert len(available)<=1, 'Duplicate case results require explicit reconciliation'
    if not available:
        continue
    case_root,case_batch_path,case_batch=available[0]
    assert case['id'] in {c['id'] for c in case_batch['cases']}
    folder=case_root/'results'/case['id']
    for s in [case['source_manifest'], *case['geometry_sources'].values()]:
        checked(s)
    result = json.loads((folder/'result.json').read_text())
    assert result['case_id'] == case['id']
    assert result['psi4_version'] == '1.11'
    assert result['batch_sha256'] == digest(case_batch_path)
    assert result['worker_sha256'] == digest(case_root/'worker.py')
    evidence = audit_output((folder/'output.dat').read_text(), result)
    qm = evidence['reconstructed_cp_hartree'] * 627.5094740631
    records.append({'case_id': case['id'], 'qm_cp_kcal_mol': qm,
        'predictions': {name: {'mm_kcal_mol': m[case['id']], 'error_kcal_mol': m[case['id']]-qm} for name, m in models.items()},
        'execution_audit': evidence, 'execution_batch':source(case_batch_path), 'sources': [source(folder/f) for f in ('result.json', 'output.dat')]})
assert records, 'No completed validation results'
summary = {name: float(np.sqrt(np.mean([r['predictions'][name]['error_kcal_mol']**2 for r in records]))) for name in models}
write(root/'assessment.json', {'simulation_ready': False, 'gate_effect': 'none',
    'validation_values_read': True, 'completed': len(records), 'planned': len(planned),
    'complete_batch': len(records) == len(planned), 'partial_rmse_kcal_mol': summary,
    'records': records, 'policy': source(root/'plan.json')})
print(json.dumps({'completed':len(records), 'planned':len(planned), 'partial_rmse_kcal_mol': summary}, indent=2))
