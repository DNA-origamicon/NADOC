"""Continue settings tests with the isolated ordered-route pruning correction."""
from pathlib import Path
src=Path(__file__).with_name('solver_sensitivity.py').read_text().split('for key in refs:\n before=')[0]
src=src.replace("'--mu-min',str(parameters['mu_min'])", "'--ordered-pruning','--mu-min',str(parameters['mu_min'])")
exec(compile(src,str(Path(__file__).with_name('solver_sensitivity.py')),'exec'))
# Default maps must remain identical when the defect does not occur.
for key in refs:
 reference=O/key/'options_default_check';a=json.loads((reference/'annotations.json').read_text())
 result=run(key,'ordered_default_parity',a,{'mu_min':6,'sigma':4,'beta':.3,'ordered_pruning':True})
 assert json.loads((reference/'solver/summary.json').read_text())['contactmap_sha256']==json.loads((R/result['path']/'solver/summary.json').read_text())['contactmap_sha256']
for mu,sigma,beta in [(5,4,.3),(6,2,.3),(6,6,.3),(6,4,.2),(6,4,.5),(5,2,.3),(5,6,.3),(5,4,.2),(5,4,.5)]:
 for key in refs:
  a=json.loads((R/best[key]['path']/'annotations.json').read_text())
  run(key,f'ordered_mu{mu}_sigma{sigma}_beta{beta}',a,{'mu_min':mu,'sigma':sigma,'beta':beta,'ordered_pruning':True})
print('ORDERED SETTINGS TESTS COMPLETE',flush=True)
