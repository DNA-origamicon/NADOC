"""Soft multiples-of-seven route preference and global annotation proposals."""
from pathlib import Path
src=Path(__file__).with_name('solver_sensitivity.py').read_text().split('for key in refs:\n before=')[0]
src=src.replace("'--mu-min',str(parameters['mu_min'])", "'--ordered-pruning','--seven-route-bonus',str(parameters.get('seven_route_bonus',0)),'--mu-min',str(parameters['mu_min'])")
exec(compile(src,str(Path(__file__).with_name('solver_sensitivity.py')),'exec'))
def settings(key,bonus=0):
 p=best[key]['parameters'];return {'mu_min':p.get('mu_min',6),'sigma':p.get('sigma',4),'beta':p.get('beta',.3),'ordered_pruning':True,'seven_route_bonus':bonus}
for bonus in [1,3,7]:
 for key in refs:
  a=json.loads((R/best[key]['path']/'annotations.json').read_text())
  run(key,f'route7bonus{bonus}',a,settings(key,bonus))
# Repeat strongest global alternatives with the best routing settings, rather
# than relying solely on their earlier default-setting tests.
for r in json.loads((O/'global_expanded_reports.json').read_text()):
 key=r['key'];selected=json.loads((O/f"{key}_{r['label']}_selected.json").read_text());current=json.loads((R/best[key]['path']/'annotations.json').read_text())
 for i,a in selected.items():current[int(i)]=a
 run(key,'tuned_'+r['label'],current,{**settings(key,best[key]['parameters'].get('seven_route_bonus',0)),'global_annotation_source':r['label']})
print('ROUTE PRIOR TESTS COMPLETE',flush=True)
