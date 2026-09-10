"""Store finite-density diagnostics; a completed pilot is not equilibration."""
import argparse
import json
from pathlib import Path
import numpy as np

from experiments.peg_chudoba.solution import molecular_pressure,NA
from experiments.peg_chudoba.analyze_chain import correlation_time


def analyze(directory):
    meta=json.loads((directory/'run.json').read_text())
    if meta['status']!='completed':raise ValueError('Run has not completed')
    count=meta['particles'];n=meta['n'];samples=[]
    with (directory/'trajectory.dat').open() as stream:
        while line:=stream.readline():
            step=int(line.split('=')[1]);box=float(stream.readline().split('=')[1].split()[0])*.8518
            stream.readline()
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(count)])*.8518
            chains=xyz.reshape(-1,n,3);offsets=chains-chains.mean(axis=1)[:,None,:]
            rg=np.sqrt(np.mean(np.sum(offsets**2,axis=2),axis=1))
            pressure=molecular_pressure(xyz,n,box,meta['temperature'])
            samples.append((step,pressure,rg.mean(),np.linalg.norm(np.diff(chains,axis=1),axis=2).max()))
    values=np.array(samples);kept=values[len(values)//2:]
    atomic=np.atleast_2d(np.loadtxt(directory/'thermo.dat'))[:,1]*(24.943387854/.8518**3)*1e27/NA
    atomic=atomic[len(atomic)//2:]
    result=dict(status='Pilot diagnostics only; equilibrium, finite-size and seed convergence not established',
        n=n,chains=meta['chains'],concentration_g_per_l=meta['concentration'],temperature_K=meta['temperature'],
        retained_frames=len(kept),discarded_fraction=.5,mean_molecular_pressure_kpa=float(kept[:,1].mean()),
        mean_atomic_pressure_kpa=float(atomic.mean()),mean_rg_nm=float(kept[:,2].mean()),
        max_bond_nm=float(values[:,3].max()),pressure_statistical_inefficiency_frames=correlation_time(kept[:,1]),
        pressure_sem_kpa=float(kept[:,1].std(ddof=1)*np.sqrt(correlation_time(kept[:,1])/len(kept))),
        ns_per_day=meta['physical_duration_ns']*86400/meta['elapsed_seconds'],
        pressure_convention='Molecular virial for the continuous force-consistent MD potential; no discontinuous MC correction included')
    np.savetxt(directory/'solution_observables.csv',values,delimiter=',',header='step,pressure_kpa,mean_rg_nm,max_bond_nm',comments='')
    (directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path)
    print(json.dumps(analyze(ap.parse_args().directory),indent=2))
