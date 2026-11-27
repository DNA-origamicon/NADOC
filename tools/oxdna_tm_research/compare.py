"""Compact recorded-state diagnostics; no equilibrium certification."""
import json
from pathlib import Path
import numpy as np
from tools.oxdna_tm_research.analyze import passages

def summarize(root):
    rows=[]
    for p in sorted(Path(root).iterdir()):
        if not (p/'result.json').exists(): continue
        r=json.loads((p/'result.json').read_text())
        reps=[]
        for paths in r['production_directories']:
            q=np.concatenate([np.loadtxt(Path(x)/'energy.dat',ndmin=2)[1:,5] for x in paths]).astype(int)
            reps.append(dict(q_counts=np.bincount(q,minlength=9).tolist(),**passages(q,8),passages6=passages(q,6)['passages']))
        rows.append(dict(name=p.name,seconds=r['elapsed_seconds'],tm=r['tm_c'],ci=r['ci95_c'],replica_tm=r['replica_tm_c'],reasons=r['reasons'],replicas=reps))
    return rows
if __name__=='__main__':
    import sys
    print(json.dumps(summarize(sys.argv[1]),indent=2))
