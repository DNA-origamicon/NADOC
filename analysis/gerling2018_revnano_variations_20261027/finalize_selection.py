"""Merge independent capacity-constrained experiments and select feasible inputs."""
from pathlib import Path
import json
O=Path(__file__).resolve().parent
rows=json.loads((O/'search_results.json').read_text());paths={r['path'] for r in rows}
for branch_name in ['capacity_branch_corrected','capacity_repair']:
 branch=O/branch_name/'search_results.json'
 if branch.exists():
  for r in json.loads(branch.read_text()):
   if r['path'] not in paths:rows.append({**r,'label':branch_name+'/'+r['label'],'search_branch':branch_name});paths.add(r['path'])
(O/'search_results.json').write_text(json.dumps(rows,indent=2)+'\n')
most={key:max((r for r in rows if r['key']==key),key=lambda r:(r['placed'],r['covered'],-max(0,r['candidate_paired_nt']-7560))) for key in ['42hb13','42hb14']}
selected={key:max((r for r in rows if r['key']==key and r['candidate_paired_nt']<=7560 and not r.get('solver_error') and not r.get('execution_error')),key=lambda r:(r['placed'],r['covered'])) for key in most}
(O/'best.json').write_text(json.dumps(most,indent=2)+'\n');(O/'selected_best.json').write_text(json.dumps(selected,indent=2)+'\n')
print('Selected capacity-consistent inputs:')
for key,r in selected.items():print(key,r['placed'],r['covered'],r['candidate_paired_nt'],r['label'])
