"""Persist chain observables and autocorrelation-aware sampling diagnostics."""
import argparse
import json
from pathlib import Path

import numpy as np


def correlation_time(values):
    x=np.asarray(values)-np.mean(values)
    if len(x)<4 or np.var(x)==0:
        return 1.0
    fft=np.fft.rfft(x,n=2*len(x))
    cov=np.fft.irfft(fft*fft.conjugate())[:len(x)]/np.arange(len(x),0,-1)
    rho=cov/cov[0]
    total=0.;previous=float('inf')
    # Geyer initial-positive, initial-monotone sequence: pair lags (0,1),
    # (2,3), ... . Cap ESS at the draw count rather than claim antithetic gain.
    for k in range(0,len(x)-1,2):
        pair=rho[k]+rho[k+1]
        if pair<=0:
            break
        pair=min(pair,previous);total+=pair;previous=pair
    return max(1.,-1+2*total)


def analyze(directory):
    meta=json.loads((directory/'run.json').read_text())
    if meta['status']!='completed':
        raise ValueError('Only analyze a completed run')
    n=meta['n'];rg=[];steps=[];max_bond=0.
    with (directory/'trajectory.dat').open() as stream:
        while line:=stream.readline():
            step=int(line.split('=')[1]);stream.readline();stream.readline()
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(n)])*.8518
            if xyz.shape!=(n,3) or not np.isfinite(xyz).all():
                raise ValueError('Invalid trajectory frame')
            # Engine writes connected molecules without wrapping individual beads.
            max_bond=max(max_bond,float(np.linalg.norm(np.diff(xyz,axis=0),axis=1).max()))
            rg.append(np.sqrt(np.mean(np.sum((xyz-xyz.mean(axis=0))**2,axis=1))))
            steps.append(step)
    values=np.array(rg);retained=values[len(values)//10:]
    inefficiency=correlation_time(retained)
    blocks=np.array([np.mean(b) for b in np.array_split(retained,18)])
    result=dict(diagnostics_version=2,n=n,temperature_K=meta['temperature'],frames=len(values),discarded_fraction=.1,
        mean_rg_nm=float(retained.mean()),rms_rg_nm=float(np.sqrt(np.mean(retained**2))),
        rg_sd_nm=float(retained.std(ddof=1)),statistical_inefficiency_frames=inefficiency,
        effective_samples=len(retained)/inefficiency,
        autocorrelation_sem_nm=float(retained.std(ddof=1)*np.sqrt(inefficiency/len(retained))),
        block_sem_nm=float(blocks.std(ddof=1)/np.sqrt(len(blocks))),
        first_half_mean_nm=float(retained[:len(retained)//2].mean()),
        second_half_mean_nm=float(retained[len(retained)//2:].mean()),
        maximum_bond_nm=max_bond,elapsed_seconds=meta['elapsed_seconds'],
        ns_per_day=meta['physical_duration_ns']*86400/meta['elapsed_seconds'] if meta['physical_duration_ns'] is not None else None,
        interpretation='Sampling diagnostics only; benchmark agreement and convergence not established.')
    np.savetxt(directory/'rg.csv',np.column_stack([steps,values]),delimiter=',',header='step,rg_nm',comments='')
    (directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path)
    print(json.dumps(analyze(ap.parse_args().directory),indent=2))
