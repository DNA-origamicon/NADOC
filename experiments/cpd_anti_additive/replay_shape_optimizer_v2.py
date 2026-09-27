"""Reconstruct the interrupted outer optimizer using saved residuals only."""
from pathlib import Path
import os,sys
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from scipy.optimize import least_squares
from experiments.cpd_anti_additive.shape_fit_protocol_v2 import require_fit_ready
from experiments.cpd_anti_additive.shape_fit_v2 import OUT
from experiments.cpd_anti_additive.validation_gate import read,checked,source
from experiments.cpd_anti_additive.sella_pilot import save,now


class UncomputedEvaluation(Exception):
    def __init__(self,x):self.x=np.array(x)


def replay():
    _,plan=require_fit_ready();progress=read(OUT/'progress.json')
    cache={};sources=[];seen=[];calls=0
    for row in progress['models']:
        if row['state']!='complete':continue
        r=read(checked(row['assessment']));p=OUT/f"model-{row['number']:03d}"/'residual.npy'
        cache[np.array(r['parameters']).tobytes()]=(row['number'],np.load(p));sources += [row['assessment'],source(p)]
    def evaluate(x):
        nonlocal calls
        calls+=1
        key=np.asarray(x).tobytes()
        if key not in cache:raise UncomputedEvaluation(x)
        number,residual=cache[key]
        if number not in seen:seen.append(number)
        return residual.copy()
    def jac(x):
        base=evaluate(x);cols=[]
        for j in range(len(x)):
            trial=np.array(x);h=.02 if x[j]+.02<=5 else -.02;trial[j]+=h
            cols.append((evaluate(trial)-base)/h)
        return np.array(cols).T
    try:
        least_squares(evaluate,np.clip(plan['initial_shifts'],-5+1e-8,5-1e-8),jac=jac,bounds=(-5.,5.),
            method='trf',max_nfev=12,ftol=.001,xtol=.001,gtol=.001,x_scale='jac')
    except UncomputedEvaluation as event:
        expected=read(OUT/'model-034/started.json')['parameters']
        assert seen==list(range(1,34)) and np.array_equal(event.x,expected)
        return dict(at=now(),source=source(Path(__file__)),sources=sources,unique_replayed_models=seen,
            callback_calls=calls,next_model=34,next_parameters=event.x.tolist(),next_parameters_bitwise_match=True,
            no_new_energy_or_geometry_evaluation=True,no_new_fit=True,minimum_certified=False)
    raise RuntimeError('Saved optimizer path unexpectedly terminated without reaching model34')


if __name__=='__main__':
    out=Path(sys.argv[1]);assert not out.exists();result=replay();save(out,result)
    print(dict(replayed=len(result['unique_replayed_models']),next_model=result['next_model'],bitwise_match=True,no_new_calculations=True))
