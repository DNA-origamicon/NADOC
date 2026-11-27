"""Recompute retained statistical results without trajectories or native engines."""
import argparse
import json
from pathlib import Path
import numpy as np
from backend.core.oxdna_vmmc_precision import precision_report


def replay(root):
    rows=[]
    for stats in sorted(Path(root).rglob('sufficient_statistics.npz')):
        original=json.loads((stats.parent/'full_analysis.json').read_text())['precision']
        data=np.load(stats);arrays=[data[k] for k in sorted(data.files) if k.startswith('replica_')]
        actual=precision_report(arrays,data['temperatures'],target=1,bootstrap=1000,max_looks=1,seed=99117)
        for key in ['tm_c','ci95_c','replica_tm_c','status','reasons']:
            if isinstance(actual[key],(float,list)) and key not in ['replica_tm_c','reasons'] and actual[key] is not None:
                assert np.allclose(actual[key],original[key],rtol=1e-12,atol=1e-12),key
            else:
                assert actual[key]==original[key],(stats,key)
        rows.append(dict(campaign=stats.parent.name,verified=True,tm_c=actual['tm_c'],ci95_c=actual['ci95_c']))
    if not rows: raise ValueError('No retained sufficient statistics')
    return rows

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');a=p.parse_args();print(json.dumps(replay(a.root),indent=2))
