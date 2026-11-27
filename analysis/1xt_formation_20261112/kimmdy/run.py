"""Run the existing user-facing KIMMDY analysis CLI for every TT pair."""
import json,subprocess,sys,itertools
from pathlib import Path
O=Path(__file__).resolve().parent
m=json.loads((O.parent/'2bc15e9e2531/summary.json').read_text())
args=[sys.executable,'scripts/analyze_kimmdy_design.py','--job',m['job_dir'],'--topology',str(Path(m['package'])/m['files'][0]['config']['structure']),'--dcd',m['files'][0]['path'],'--out',str(O),'--mode','explicit','--pair-scope','all','--stride','1','--max-frames','0','--rate-model','upstream']
for a,b in itertools.combinations(m['sites'],2):args+=['--pair',f'{a[0]}:{a[1]}~{b[0]}:{b[1]}']
(O/'command.json').write_text(json.dumps(args,indent=2)+'\n')
subprocess.run(args,check=True)
