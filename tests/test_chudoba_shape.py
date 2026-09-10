"""Check online molecular shape against independently read configurations."""
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest


@pytest.mark.parametrize('sampling',['npt','md','hmc'])
def test_solution_online_shape(tmp_path,sampling):
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build Chudoba engine first')
    out=tmp_path/'run'
    run=subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_solution',
        '--sampling',sampling,'--n','9','--chains','3','--steps','20','--seed','743',
        '--concentration','5','--hmc-steps','7','--output',str(out)],
        capture_output=True,text=True,timeout=60)
    assert run.returncode==0,run.stderr
    online=np.atleast_2d(np.loadtxt(out/'shape.dat'))
    observed=[]
    with (out/'trajectory.dat').open() as stream:
        while stream.readline():
            box=np.array([float(x) for x in stream.readline().split('=')[1].split()])
            stream.readline()
            xyz=np.array([[float(x) for x in stream.readline().split()[:3]] for _ in range(27)]).reshape(3,9,3)
            bonds=np.diff(xyz,axis=1);bonds-=box*np.rint(bonds/box)
            xyz=np.concatenate([np.zeros((3,1,3)),np.cumsum(bonds,axis=1)],axis=1)*.8518
            rg2=np.mean(np.sum((xyz-xyz.mean(axis=1,keepdims=True))**2,axis=2),axis=1)
            observed.append([np.sqrt(rg2).mean(),rg2.mean()])
    assert len(online)==21 and len(observed)==20
    assert online[0,0]==0
    online=online[1:]  # Thermodynamic outputs include t=0; trajectory starts after the first step.
    assert np.allclose(online[:,1:],observed,rtol=2e-5,atol=2e-6)
    if sampling in ('npt','hmc'):
        from experiments.peg_chudoba.analyze_npt import analyze
        result=analyze(out)
        assert result['structure_trace_source']=='shape.dat'
        assert len(result['saved_rg_trace_nm'])==21
        full=np.loadtxt(out/'shape.dat')
        assert result['rms_chain_rg_nm']==pytest.approx(np.sqrt(full[10:,2].mean()))
