"""End-to-end published PEG force checks against the physical-unit oracle."""
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.physics.oxdna_peg import PegParameters
from tools.oxdna_peg.chudoba_reference import finite_difference_forces, chain_energy, pair_energy_derivative


@pytest.mark.parametrize('temperature',[294,347,371,396])
@pytest.mark.parametrize('backend,edge',[('CPU',False),('CUDA',False),('CUDA',True)])
def test_chudoba_forces(tmp_path,temperature,backend,edge,cell_capacity_factor=None):
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():
        pytest.skip('Build isolated Chudoba engine first')
    xyz=np.array([[0,0,0],[.33,0,0],[.51,.27,0],[.7,.36,.25],[.91,.18,.4]])
    expected=finite_difference_forces(xyz,temperature)*.8518/24.943387854
    n=len(xyz)
    (tmp_path/'topology.top').write_text(f'{n} 1\n'+''.join(
        f'1 500 {i+1 if i+1<n else -1} {i-1}\n' for i in range(n)))
    (tmp_path/'conf.dat').write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n'+''.join(
        ' '.join(f'{v:.15g}' for v in pos/.8518+3)+' 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for pos in xyz))
    dt=1e-6
    stage=OxdnaStageSpec('force','production','MD',1,backend,dt=dt,
        thermostat='no',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=71)
    inp=render_stage_input(stage,'topology.top','conf.dat').replace('refresh_vel = true','refresh_vel = false')
    inp=inp.replace('use_edge = true',f'use_edge = {str(edge).lower()}')
    if cell_capacity_factor is not None:inp+=f'\nmax_density_multiplier = {cell_capacity_factor}\n'
    lines=[line for line in inp.splitlines() if not line.startswith('T =')]
    (tmp_path/'input').write_text('\n'.join(lines)+f'\nT = {temperature}K\npeg_chudoba = true\npeg_chudoba_pure = true\nT_force_value = true\n')
    with (tmp_path/'input').open('a') as stream:
        stream.write("""CUDA_update_stress_tensor_every = 1
 data_output_1 = {
 name = check.dat
 print_every = 1
 col_1 = {
 type = pressure
 }
 col_2 = {
 type = potential_energy
 }
 }
""")
    result=subprocess.run([str(binary),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-5000:]
    final=np.loadtxt(tmp_path/'last_conf.dat',skiprows=3)
    forces=final[:,9:12]/dt
    assert np.allclose(forces,expected,rtol=2e-4,atol=2e-4),(forces,expected)

    data=np.atleast_2d(np.loadtxt(tmp_path/'check.dat'))
    pressure=np.sum((xyz/.8518)*expected)/(3*20**3)
    assert data[-1,0]==pytest.approx(pressure,rel=2e-4,abs=2e-7)
    assert data[-1,1]==pytest.approx(chain_energy(xyz,temperature)/24.943387854/n,rel=2e-4)


@pytest.mark.parametrize('sampling',['mc','pivot'])
def test_mc_energy_accounting(tmp_path,sampling):
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():
        pytest.skip('Build isolated Chudoba engine first')
    directory=tmp_path/'run'
    result=subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
        '--n','9','--steps','100','--sampling',sampling,'--output',str(directory)],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,(result.stdout,result.stderr,(directory/'engine.log').read_text())
    # Every saved snapshot must agree with a separate physical-unit energy.
    # Legacy MC also checks its cached running energy every step.
    energy=np.atleast_2d(np.loadtxt(directory/'energy.dat'))
    with (directory/'trajectory.dat').open() as stream:
        frame=0
        while line:=stream.readline():
            step=int(line.split('=')[1])
            stream.readline();stream.readline()
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(9)])*.8518
            assert energy[step,1]==pytest.approx(chain_energy(xyz,294)/24.943387854/9,abs=1e-6)
            frame+=1
    assert frame>=100


@pytest.mark.parametrize('backend,edge',[('CPU',False),('CUDA',False),('CUDA',True)])
@pytest.mark.parametrize('shifted',[False,True])
def test_cutoff_crossing_energy(tmp_path,backend,edge,shifted):
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build isolated Chudoba engine first')
    (tmp_path/'topology.top').write_text('2 2\n1 500 -1 -1\n2 500 -1 -1\n')
    (tmp_path/'conf.dat').write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n'+''.join(
        f'{x} 3 3 1 0 0 0 0 1 {v} 0 0 0 0 1e-6\n'
        for x,v in [(3,-.03),(3+.898/.8518,.03)]))
    stage=OxdnaStageSpec('crossing','production','MD',100,backend,dt=.001,
        thermostat='no',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=71)
    inp=render_stage_input(stage,'topology.top','conf.dat').replace('refresh_vel = true','refresh_vel = false')
    inp=inp.replace('use_edge = true',f'use_edge = {str(edge).lower()}')
    inp='\n'.join(line for line in inp.splitlines() if not line.startswith('T ='))
    (tmp_path/'input').write_text(inp+f'\nT = 294K\npeg_chudoba = true\npeg_chudoba_pure = true\npeg_chudoba_shift = {str(shifted).lower()}\n')
    result=subprocess.run([str(binary),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-3000:]
    xyz=np.loadtxt(tmp_path/'last_conf.dat',skiprows=3)
    assert (xyz[1,0]-xyz[0,0])*.8518>.9
    energy=np.loadtxt(tmp_path/'energy.dat')
    drift=energy[-1,-1]-energy[0,-1]
    if shifted:
        assert abs(drift)<3e-6
    else:
        # Raw truncated energy has a boundary jump absent from the MD forces.
        expected=-pair_energy_derivative(.9,294,truncate=False)[0]/24.943387854/2
        assert drift==pytest.approx(expected,abs=3e-6)


def test_molecular_volume_ideal_gas_distribution(tmp_path):
    """One molecule has p(V) ∝ V exp(-PV/kT); mean V=2kT/P."""
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build isolated Chudoba engine first')
    (tmp_path/'topology.top').write_text('1 1\n1 500 -1 -1\n')
    (tmp_path/'conf.dat').write_text('t = 0\nb = 12.5 12.5 12.5\nE = 0 0 0\n3 3 3 1 0 0 0 0 1 0 0 0 0 0 1e-6\n')
    stage=OxdnaStageSpec('volume','production','MD',30000,'CPU',dt=.001,
        thermostat='no',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=99)
    inp=render_stage_input(stage,'topology.top','conf.dat').replace('sim_type = MD','sim_type = MC2')
    inp='\n'.join(line for line in inp.splitlines() if not line.startswith('T ='))
    inp+='''
T = 294K
P = 0.0001
peg_chudoba = true
peg_chudoba_pure = true
move_1 = {
 type = molecule_volume
 delta = 1.5
 prob = 1
}
data_output_1 = {
 name = density.dat
 print_every = 5
 col_1 = {
 type = density
 }
}
'''
    (tmp_path/'input').write_text(inp)
    result=subprocess.run([str(binary),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-3000:]
    volume=1/np.loadtxt(tmp_path/'density.dat')[600:]
    expected=2*(294/3000)/.0001
    assert volume.mean()==pytest.approx(expected,rel=.06)
    assert np.mean(1/volume)==pytest.approx(.0001/(294/3000),rel=.12)


@pytest.mark.parametrize('sampling,list_type',[('npt','cells'),('npt','verlet'),('hmc','verlet')])
@pytest.mark.parametrize('cutoff',['raw','zero_tail'])
def test_interacting_npt_snapshot_energy(tmp_path,sampling,list_type,cutoff):
    """Periodic multichain energy after translation, pivot and volume moves."""
    from experiments.peg_chudoba.solution import nonbonded_energy
    from tools.oxdna_peg.chudoba_reference import bonded_energy
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build isolated Chudoba engine first')
    directory=tmp_path/'npt'
    result=subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_solution',
        '--sampling',sampling,'--cutoff',cutoff,'--list-type',list_type,'--n','9','--chains','8',
        '--concentration','100','--pressure-kpa','100','--steps','200',
        '--output',str(directory)],cwd=Path(__file__).resolve().parents[1],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,(result.stdout,result.stderr)
    frames=0
    with (directory/'trajectory.dat').open() as stream:
        while stream.readline():
            box=float(stream.readline().split('=')[1].split()[0])*.8518
            observed=float(stream.readline().split('=')[1].split()[1])
            xyz=np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(72)])*.8518
            expected=sum(bonded_energy(c) for c in xyz.reshape(8,9,3))
            expected+=nonbonded_energy(xyz,9,box,294,zero_tail=cutoff=='zero_tail')
            assert observed==pytest.approx(expected/24.943387854/72,abs=1e-8)
            frames+=1
    assert frames==40


@pytest.mark.parametrize('backend,edge',[('CPU',False),('CUDA',False),('CUDA',True)])
def test_periodic_multichain_forces(tmp_path,backend,edge):
    from experiments.peg_chudoba.solution import nonbonded_energy
    from tools.oxdna_peg.chudoba_reference import bonded_energy
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build isolated Chudoba engine first')
    chain=np.array([[0,0,0],[.33,0,0],[.51,.27,0],[.7,.36,.25],[.91,.18,.4]])
    # Chains interact through the z boundary; the second crosses the x boundary.
    xyz=np.concatenate([chain+[2.3,1,.2],chain+[2.3,1,2.6]])
    box=3.
    def energy(x):
        return sum(bonded_energy(c) for c in x.reshape(2,5,3))+nonbonded_energy(x,5,box,371)
    expected=np.empty_like(xyz)
    for i in range(10):
        for axis in range(3):
            plus=xyz.copy();minus=xyz.copy()
            plus[i,axis]+=1e-6;minus[i,axis]-=1e-6
            expected[i,axis]=-(energy(plus)-energy(minus))/2e-6*.8518/24.943387854
    (tmp_path/'topology.top').write_text('10 2\n'+''.join(
        f'{i//5+1} 500 {i+1 if (i+1)%5 else -1} {i-1 if i%5 else -1}\n' for i in range(10)))
    (tmp_path/'conf.dat').write_text(f't = 0\nb = {box/.8518} {box/.8518} {box/.8518}\nE = 0 0 0\n'+''.join(
        ' '.join(f'{v:.15g}' for v in p/.8518)+' 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for p in xyz))
    dt=1e-6
    stage=OxdnaStageSpec('periodic','production','MD',1,backend,dt=dt,
        thermostat='no',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=71)
    inp=render_stage_input(stage,'topology.top','conf.dat').replace('refresh_vel = true','refresh_vel = false')
    inp=inp.replace('use_edge = true',f'use_edge = {str(edge).lower()}')
    inp='\n'.join(line for line in inp.splitlines() if not line.startswith('T ='))
    (tmp_path/'input').write_text(inp+'\nT = 371K\npeg_chudoba = true\npeg_chudoba_pure = true\nT_force_value = true\n')
    result=subprocess.run([str(binary),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-3000:]
    final=np.loadtxt(tmp_path/'last_conf.dat',skiprows=3)
    assert np.allclose(final[:,9:12]/dt,expected,rtol=3e-4,atol=3e-4)
    observed=np.atleast_2d(np.loadtxt(tmp_path/'energy.dat'))[-1,1]
    assert observed==pytest.approx(energy(xyz)/24.943387854/10,abs=2e-6)


@pytest.mark.parametrize('edge',[False,True])
def test_exactly_full_cuda_cell(tmp_path,edge):
    # All five beads fit in one cell of capacity five. Filling the final valid
    # slot must preserve all forces and energies, not report overflow.
    test_chudoba_forces(tmp_path,294,'CUDA',edge,cell_capacity_factor=1.)


def test_cuda_cell_actual_overflow_still_rejected(tmp_path):
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    if not binary.exists():pytest.skip('Build isolated Chudoba engine first')
    (tmp_path/'topology.top').write_text('6 6\n'+''.join(f'{i+1} 500 -1 -1\n' for i in range(6)))
    (tmp_path/'conf.dat').write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n'+''.join(
        f'{3+i*.5} 3 3 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for i in range(6)))
    stage=OxdnaStageSpec('overflow','production','MD',1,'CUDA',dt=1e-6,
        thermostat='no',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=71)
    inp=render_stage_input(stage,'topology.top','conf.dat')
    inp+='\npeg_chudoba = true\npeg_chudoba_pure = true\nmax_density_multiplier = 0.1\n'
    (tmp_path/'input').write_text(inp)
    result=subprocess.run([str(binary),'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode!=0
    assert 'more than _max_n_per_cell (5)' in result.stderr
