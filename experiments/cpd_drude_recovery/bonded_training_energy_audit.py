"""Audit training-conformer strain and near-minimum identifiability without refitting."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked,source,write
from backend.parameterization.photoproduct_qm import parse_xyz

root=Path('.development-artifacts/cpd-bonded-training-energy-v1').resolve()
root.mkdir(exist_ok=False)
stage=Path('.development-artifacts/cpd-drude-bonded-h6-endpoints-v1').resolve()
campaign_path=stage/'response_campaign/response_campaign_manifest.json'
campaign=json.loads(campaign_path.read_text())
reference_path=Path('.development-artifacts/cpd-independent-h6-scan-v1/reference/result.json').resolve()
reference=json.loads(reference_path.read_text())
portability_path=reference_path.parent.parent/'portability.json'
assert json.loads(portability_path.read_text())['passed']
records=[]
minimum=None
for dataset in campaign['training_datasets']:
    manifest_path=checked(dataset['response_manifest'])
    m=json.loads(manifest_path.read_text())
    t=json.loads(checked(m['sources']['hessian_targets']).read_text())
    if t.get('electronic_energy'):
        assert t['partition']=='training'
        energy=t['electronic_energy']['value']
        geometry=checked(m['sources']['target_geometry'])
        xyz=np.array([a[1:] for a in parse_xyz(geometry.read_text())[0]])
        records.append({'case':manifest_path.parent.name,'energy_hartree':energy,'relative_energy_kcal_mol':(energy-reference['energy_hartree'])*627.5094740631,'sources':[source(manifest_path),source(checked(m['sources']['hessian_targets'])),source(geometry)]})
    else:
        with np.load(checked(m['outputs']['linear_response_arrays'])) as z:minimum=dict(z)
        minimum_manifest=manifest_path
assert minimum is not None
spec_path=stage/'quantitative_fit_specification.json'
spec=json.loads(spec_path.read_text())
scales=np.array([p['scale'] for p in spec['parameters']])
blocks=[]
for kind in ('gradient','hessian_upper'):
    a=minimum['projected_design_'+kind]*scales
    norm=np.linalg.norm(a,axis=0)
    blocks.append(a/np.where(norm>0,norm,1))
a=np.vstack(blocks)
s=np.linalg.svd(a,compute_uv=False)
rank=int(np.sum(s>s[0]*1e-8))
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','scope':'Training-only strain-energy and minimum-only derivative-rank diagnostic. Pointwise Boltzmann factors are not conformer populations; this audit does not change dataset weights, partitions, acceptance gates, or discard any target.','training_conformers':records,'reference_energy_hartree':reference['energy_hartree'],'minimum_only_parameter_count':len(scales),'minimum_only_normalized_joint_rank':rank,'minimum_only_nullity':len(scales)-rank,'rank_cutoff_relative':1e-8,'sources':[source(p) for p in (campaign_path,reference_path,portability_path,minimum_manifest,spec_path,Path(__file__))]})
print(json.dumps({'conformer_energies_kcal_mol':[(r['case'],r['relative_energy_kcal_mol']) for r in records],'minimum_only_rank':rank,'parameter_count':len(scales)},indent=2))
