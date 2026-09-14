"""GPU HMC endpoint correction, rollback, and molecular NPT distribution."""
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pytest

from backend.core.oxdna_protocol import OxdnaStageSpec,render_stage_input
from backend.physics.oxdna_peg import PegParameters
from tools.oxdna_peg.chudoba_reference import chain_energy

BINARY=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'


def test_hmc_endpoint_energy_and_rejection(tmp_path):
    if not BINARY.exists():pytest.skip('Build Chudoba engine first')
    directory=tmp_path/'hmc'
    run=subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
        '--sampling','hmc','--n','9','--steps','200','--hmc-steps','100',
        '--dt-fs','8','--seed','901','--output',str(directory)],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=60)
    assert run.returncode==0,(run.stdout,run.stderr,(directory/'engine.log').read_text())
    accepted=[int(x) for x in re.findall(r'HMC_accepted=(\d)',(directory/'energy.dat').read_text())]
    assert 0 in accepted and 1 in accepted
    previous=np.loadtxt(directory/'conf.dat',skiprows=3)[:,:3]*.8518
    count=0
    with (directory/'trajectory.dat').open() as stream:
        while stream.readline():
            stream.readline()
            observed=float(stream.readline().split('=')[1].split()[1])
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(9)])*.8518
            assert observed==pytest.approx(chain_energy(xyz,294)/24.943387854/9,abs=2e-6)
            if not accepted[count]:assert np.allclose(xyz,previous,rtol=0,atol=2e-6)
            previous=xyz;count+=1
    assert count==200


def test_hmc_npt_ideal_volume(tmp_path):
    if not BINARY.exists():pytest.skip('Build Chudoba engine first')
    (tmp_path/'topology.top').write_text('1 1\n1 500 -1 -1\n')
    (tmp_path/'conf.dat').write_text('t = 0\nb = 12.5 12.5 12.5\nE = 0 0 0\n3 3 3 1 0 0 0 0 1 0 0 0 0 0 1e-6\n')
    stage=OxdnaStageSpec('hmc','production','MD',3000,'CUDA',dt=.001,
        thermostat='no',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=99)
    inp=render_stage_input(stage,'topology.top','conf.dat').replace('sim_type = MD','sim_type = PEG_HMC')
    inp='\n'.join(line for line in inp.splitlines() if not line.startswith('T ='))
    inp+='''
T = 294K
P = 0.0001
peg_chudoba = true
peg_chudoba_pure = true
peg_hmc_steps = 1
peg_hmc_volume_attempts = 10
peg_hmc_volume_delta = 1.5
data_output_1 = {
 name = density.dat
 print_every = 1
 col_1 = {
 type = density
 }
}
'''
    (tmp_path/'input').write_text(inp)
    run=subprocess.run([str(BINARY),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=60)
    assert run.returncode==0,run.stderr[-4000:]
    volume=1/np.loadtxt(tmp_path/'density.dat')[300:]
    assert volume.mean()==pytest.approx(2*(294/3000)/.0001,rel=.08)


def test_hmc_harmonic_bond_distribution(tmp_path):
    """Two bonded beads have analytic radial density r² exp[-k(r-b)²/(2RT)]."""
    if not BINARY.exists():pytest.skip('Build Chudoba engine first')
    directory=tmp_path/'bond'
    run=subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
        '--sampling','hmc','--n','2','--steps','5000','--hmc-steps','37',
        '--dt-fs','8','--seed','904','--output',str(directory)],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=180)
    assert run.returncode==0,(run.stdout,run.stderr)
    radii=[]
    with (directory/'trajectory.dat').open() as stream:
        while stream.readline():
            stream.readline();stream.readline()
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(2)])*.8518
            radii.append(np.linalg.norm(xyz[1]-xyz[0]))
    radii=np.array(radii)[len(radii)//5:]
    b=.33;s2=.008314462618*294/17000
    mean=(b**3+3*b*s2)/(b*b+s2)
    variance=(b**4+6*b*b*s2+3*s2*s2)/(b*b+s2)-mean**2
    # Negative-radius Gaussian tails are negligible (b/sigma > 27).
    assert radii.mean()==pytest.approx(mean,abs=.001)
    assert radii.var(ddof=1)==pytest.approx(variance,rel=.15)
