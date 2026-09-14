"""Outer-tail removal preserves inner attraction and zeroes its exterior only."""
from pathlib import Path
import subprocess
import numpy as np
import pytest
from scipy.optimize import brentq
from backend.core.oxdna_protocol import OxdnaStageSpec,render_stage_input
from backend.physics.oxdna_peg import PegParameters
from tools.oxdna_peg.chudoba_reference import pair_energy_derivative,parameters


@pytest.mark.parametrize('temperature',[294,320,347,361,371,381,396])
def test_zero_tail_continuity_and_derivative(temperature):
    mu=parameters(temperature)['mu']
    root=brentq(lambda r:pair_energy_derivative(r,temperature,truncate=False)[0],mu,.9)
    assert pair_energy_derivative(root+1e-7,temperature,zero_tail=True)==(0.,0.)
    assert abs(pair_energy_derivative(root-1e-7,temperature,zero_tail=True)[0])<1e-5
    for r in [.47,.55,.7,root-.002,root+.002]:
        u,d=pair_energy_derivative(r,temperature,zero_tail=True)
        fd=(pair_energy_derivative(r+1e-6,temperature,zero_tail=True)[0]-pair_energy_derivative(r-1e-6,temperature,zero_tail=True)[0])/2e-6
        assert d==pytest.approx(fd,rel=1e-6,abs=1e-7)
        if r<mu:assert (u,d)==pair_energy_derivative(r,temperature)


@pytest.mark.parametrize('backend',['CPU','CUDA'])
@pytest.mark.parametrize('r',[.50,.80,.85,.89])
def test_zero_tail_engine_pair(tmp_path,backend,r):
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build Chudoba engine')
    (tmp_path/'topology.top').write_text('2 2\n1 500 -1 -1\n2 500 -1 -1\n')
    (tmp_path/'conf.dat').write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n'+''.join(
        f'{3+x/.8518} 3 3 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for x in [0,r]))
    dt=1e-6
    stage=OxdnaStageSpec('tail','production','MD',1,backend,dt=dt,thermostat='no',
        interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=71)
    inp=render_stage_input(stage,'topology.top','conf.dat').replace('refresh_vel = true','refresh_vel = false')
    inp='\n'.join(x for x in inp.splitlines() if not x.startswith('T ='))
    inp+='\nT = 371K\nT_force_value = true\npeg_chudoba = true\npeg_chudoba_pure = true\npeg_chudoba_zero_tail = true\n'
    (tmp_path/'input').write_text(inp)
    result=subprocess.run([str(binary),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    state=np.loadtxt(tmp_path/'last_conf.dat',skiprows=3)
    u,d=pair_energy_derivative(r,371,zero_tail=True)
    expected=np.array([[d,0,0],[-d,0,0]])*.8518/24.943387854
    assert np.allclose(state[:,9:12]/dt,expected,rtol=2e-4,atol=2e-5)
    energy=float((tmp_path/'last_conf.dat').read_text().splitlines()[2].split('=')[1].split()[1])
    assert energy==pytest.approx(u/24.943387854/2,abs=2e-6)


@pytest.mark.parametrize('sampling',['mc','pivot','hmc'])
def test_zero_tail_sampled_energy(tmp_path,sampling):
    import sys
    from tools.oxdna_peg.chudoba_reference import chain_energy
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build Chudoba engine')
    out=tmp_path/'run'
    result=subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
        '--cutoff','zero_tail','--sampling',sampling,'--n','9','--temperature','371',
        '--steps','40','--hmc-steps','20','--dt-fs','4','--output',str(out)],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    with (out/'trajectory.dat').open() as stream:
        count=0
        while stream.readline():
            stream.readline();observed=float(stream.readline().split('=')[1].split()[1])
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(9)])*.8518
            assert observed==pytest.approx(chain_energy(xyz,371,zero_tail=True)/24.943387854/9,abs=2e-6)
            count+=1
        assert count==40
