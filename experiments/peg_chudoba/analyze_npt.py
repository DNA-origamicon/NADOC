"""NPT concentration from mean volume, as in the paper's EOS protocol."""
import argparse
import json
from pathlib import Path
import numpy as np

from experiments.peg_chudoba.analyze_chain import correlation_time
from experiments.peg_chudoba.solution import REPEAT_MASS


def analyze(directory):
    meta=json.loads((directory/'run.json').read_text())
    if meta['status']!='completed' or meta.get('sampling') not in ('npt','hmc'):
        raise ValueError('Expected completed NPT run')
    data=np.atleast_2d(np.loadtxt(directory/'thermo.dat'))
    volumes=meta['particles']/data[:,1]*.8518**3
    kept=volumes[len(volumes)//2:]
    ineff=correlation_time(kept)
    sem=kept.std(ddof=1)*np.sqrt(ineff/len(kept))
    frozen=bool(np.var(kept)==0)
    c=meta['particles']*REPEAT_MASS/(.602214076*kept.mean())
    result=dict(diagnostics_version=2,status='Unvalidated allocation: assess equilibration and independent seeds',
        n=meta['n'],chains=meta['chains'],temperature_K=meta['temperature'],pressure_kpa=meta['pressure_kpa'],
        cutoff=meta['cutoff'],mean_volume_nm3=float(kept.mean()),concentration_g_per_l=float(c),
        concentration_sem_g_per_l=None if frozen else float(c*sem/kept.mean()),
        effective_volume_samples=0. if frozen else len(kept)/ineff,frozen_volume_trace=frozen,
        volume_first_half_nm3=float(kept[:len(kept)//2].mean()),
        volume_second_half_nm3=float(kept[len(kept)//2:].mean()),
        elapsed_seconds=meta['elapsed_seconds'],sampling=meta['sampling'],
        sweeps=meta['steps'] if meta['sampling']=='npt' else None,
        hmc_proposals=meta['steps'] if meta['sampling']=='hmc' else None,discarded_fraction=.5)
    if meta['sampling']=='npt':
        final=np.atleast_2d(np.loadtxt(directory/'energy.dat'))[-1]
        result['cumulative_move_acceptance']=dict(zip(('translation','pivot','volume'),map(float,final[2:5])))
    rg_trace=[];max_bond=0.
    with (directory/'trajectory.dat').open() as stream:
        while stream.readline():
            stream.readline();stream.readline()
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(meta['particles'])])*.8518
            chains=xyz.reshape(meta['chains'],meta['n'],3)
            rg=np.sqrt(np.mean(np.sum((chains-chains.mean(axis=1,keepdims=True))**2,axis=2),axis=1))
            rg_trace.append(float(rg.mean()))
            if meta['n']>1:max_bond=max(max_bond,float(np.linalg.norm(np.diff(chains,axis=1),axis=2).max()))
    if rg_trace:
        retained=np.array(rg_trace[len(rg_trace)//2:])
        result.update(mean_chain_rg_nm=float(retained.mean()),maximum_bond_nm=max_bond,
            retained_rg_first_half_nm=float(retained[:max(1,len(retained)//2)].mean()),
            retained_rg_second_half_nm=float(retained[len(retained)//2:].mean()),
            saved_rg_trace_nm=rg_trace)
    if (directory/'shape.dat').exists():
        shape=np.atleast_2d(np.loadtxt(directory/'shape.dat'))
        if shape.shape[1]!=3 or not np.isfinite(shape).all():raise ValueError('Invalid online chain shape data')
        kept_shape=shape[len(shape)//2:,1]
        result.update(saved_rg_trace_nm=shape[:,1].tolist(),
            retained_rg_first_half_nm=float(kept_shape[:len(kept_shape)//2].mean()),
            retained_rg_second_half_nm=float(kept_shape[len(kept_shape)//2:].mean()),
            saved_mean_rg_squared_trace_nm2=shape[:,2].tolist(),
            structure_trace_source='shape.dat',
            mean_chain_rg_nm=float(shape[len(shape)//2:,1].mean()),
            rms_chain_rg_nm=float(np.sqrt(shape[len(shape)//2:,2].mean())))
    targets=json.loads((Path(__file__).parent/'reference/published_targets.json').read_text())['osmotic_pressure']
    matches=[r for r in targets if r['n']==meta['n'] and r['temperature_K']==meta['temperature']
             and abs(r['pressure_kpa']/meta['pressure_kpa']-1)<.02]
    if matches:
        target=matches[0]
        result.update(published_concentration_g_per_l=target['concentration_g_per_l'],
            digitization_relative_bound=target['digitization_relative_bound'],
            relative_difference=float(c/target['concentration_g_per_l']-1))
    (directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path)
    print(json.dumps(analyze(ap.parse_args().directory),indent=2))
