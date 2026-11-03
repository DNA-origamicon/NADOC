"""Check execution provenance and deterministic repeats for completed trials."""
from pathlib import Path
import json
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
rows=json.loads((O/'search_results.json').read_text());seen={};duplicates=0
for r in rows:
 s=json.loads((R/r['path']/'solver/summary.json').read_text());p=r['parameters'];actual=s['scientific_parameters']
 for field,name,default in [('MU_MIN','mu_min',6),('SIGMA','sigma',4),('BETA','beta',.3),('seven_route_bonus','seven_route_bonus',0)]:assert actual.get(field,default)==p.get(name,default),(r['path'],field)
 assert s.get('ordered_pruning',{}).get('enabled',False)==bool(p.get('ordered_pruning',False)),r['path']
 key=(r['key'],r['annotation_sha256'],actual['MU_MIN'],actual['SIGMA'],actual['BETA'],actual.get('seven_route_bonus',0),s.get('ordered_pruning',{}).get('enabled',False))
 outcome=(s.get('contactmap_sha256'),s.get('solver_error'),s.get('execution_error'))
 if key in seen:
  assert seen[key]==outcome,(r['path'],'duplicate differs');duplicates+=1
 else:seen[key]=outcome
(O/'execution_audit.json').write_text(json.dumps({'completed_runs_checked':len(rows),'requested_vs_executed_parameters_match':True,'duplicate_contexts_checked':duplicates,'duplicate_contexts_identical':True,'excluded_branch':'capacity_branch/EXCLUDED.txt','interrupted_run':'42hb14/options_mu5_sigma4_beta0.3/INTERRUPTED.json'},indent=2)+'\n')
print('PASS',len(rows),'runs;',duplicates,'deterministic repeats')
