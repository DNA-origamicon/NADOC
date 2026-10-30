"""Test globally selected annotation combinations in ordinary full-list REVNANO."""
from pathlib import Path
base=Path(__file__).with_name('search.py');exec(compile(base.read_text().split('# Baseline archived')[0],str(base),'exec'))
results=json.loads((O/'search_results.json').read_text());best=json.loads((O/'best.json').read_text());cache={(r['key'],r['annotation_sha256']):r for r in results}
for reportfile in ['global_assignment_reports.json','global_expanded_reports.json']:
 for r in json.loads((O/reportfile).read_text()):
  key=r['key'];label=r['label'];selected=json.loads((O/f'{key}_{label}_selected.json').read_text());current=json.loads((R/best[key]['path']/'annotations.json').read_text())
  for i,a in selected.items():current[int(i)]=a
  run(key,label,current,{'global_exact_domain_assignment':True,'global_selected_staples':r['selected_staples'],'global_selected_bases':r['selected_paired_nt'],'source_assignment_report':reportfile})
print('GLOBAL REVNANO TESTS COMPLETE',flush=True)
