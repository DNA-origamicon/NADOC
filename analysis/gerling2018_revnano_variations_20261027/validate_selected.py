"""Independently check disk/parallel results using cached sequential REVNANO."""
from pathlib import Path
import json,subprocess
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
rows=json.loads((O/'search_results.json').read_text())+json.loads((O/'capacity_branch_corrected/search_results.json').read_text())
selected={key:max((r for r in rows if r['key']==key and r['candidate_paired_nt']<=7560),key=lambda r:(r['placed'],r['covered'])) for key in ['42hb13','42hb14']}
checks=[]
for key,r in selected.items():
 src=R/r['path'];p=r['parameters'];dest=O/f"validation_cached_{key}_{r['annotation_sha256'][:10]}"
 args=[str(R/'.venv/bin/python'),str(R/'tools/revnano_accel/run.py'),str(src/'input.rev'),'--output',str(dest),'--mode','cached','--budget-mib','1024','--mu-min',str(p.get('mu_min',6)),'--sigma',str(p.get('sigma',4)),'--beta',str(p.get('beta',.3)),'--seven-route-bonus',str(p.get('seven_route_bonus',0))]
 if p.get('ordered_pruning'):args.append('--ordered-pruning')
 if not (dest/'summary.json').exists():
  with (O/f'{dest.name}.log').open('w') as f:proc=subprocess.run(args,cwd=R,stdout=f,stderr=subprocess.STDOUT)
  assert proc.returncode==0,(key,proc.returncode)
 a=json.loads((src/'solver/summary.json').read_text());b=json.loads((dest/'summary.json').read_text())
 for field in ['contactmap_sha256','stage_results','no_tree_ids','tree_digests']:assert a[field]==b[field],(key,field)
 checks.append({'key':key,'selected_trial_path':r['path'],'annotation_sha256':r['annotation_sha256'],'cached_serial_vs_parallel_exact':True,'contactmap_sha256':a['contactmap_sha256'],'cached_seconds':b['solver_seconds']});print('PASS',key,'exact stages, trees and full contact map',flush=True)
(O/'serial_parallel_validation.json').write_text(json.dumps(checks,indent=2)+'\n')
