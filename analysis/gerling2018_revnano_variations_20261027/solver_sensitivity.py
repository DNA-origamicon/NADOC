"""Documented REVNANO settings; isolated adapter copy, no upstream edits."""
from pathlib import Path
base=Path(__file__).with_name('search.py');code=base.read_text().split('# Baseline archived')[0]
code=code.replace("str(R/'tools/revnano_accel/run.py')","str(O/'solver_options/run.py')")
code=code.replace("str(dest/'solver'),'--workers','4'", "str(dest/'solver'),'--workers','4','--mu-min',str(parameters['mu_min']),'--sigma',str(parameters['sigma']),'--beta',str(parameters['beta'])")
code=code.replace('if proc.returncode not in [0,2]:','if proc.returncode not in [0,2,3]:')
# Each explicitly named parameter experiment must run even with identical annotations.
code=code.replace("if (key,digest) in cache:return cache[key,digest]", "if False:return None")
exec(compile(code,str(base),'exec'))
results=json.loads((O/'search_results.json').read_text());best=json.loads((O/'best.json').read_text());cache={}
for key in refs:
 before=dict(best[key]);a=json.loads((R/before['path']/'annotations.json').read_text())
 baseline=run(key,'options_default_check',a,{'mu_min':6,'sigma':4,'beta':.3})
 # Prior stages use default settings. Confirm isolated options adapter is identical.
 assert json.loads((R/before['path']/'solver/summary.json').read_text())['contactmap_sha256']==json.loads((R/baseline['path']/'solver/summary.json').read_text())['contactmap_sha256']
for mu,sigma,beta in [(5,4,.3),(6,2,.3),(6,6,.3),(6,4,.2),(6,4,.5)]:
 for key in refs:
  a=json.loads((R/best[key]['path']/'annotations.json').read_text())
  run(key,f'options_mu{mu}_sigma{sigma}_beta{beta}',a,{'mu_min':mu,'sigma':sigma,'beta':beta})
print('SOLVER SENSITIVITY COMPLETE',flush=True)
