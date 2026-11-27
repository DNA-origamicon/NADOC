"""Native fixed-window umbrella input and execution; no NADOC structure authoring."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import threading
import os
import tempfile
import numpy as np


_active=set()
_lock=threading.Lock()
_cancelled=threading.Event()


def cancel_active():
    """Stop only native children launched by this process, never a user job."""
    _cancelled.set()
    with _lock:
        for process in list(_active):
            if process.poll() is None:process.terminate()


def scratch_root():
    selected=os.environ.get('NADOC_TEST_SCRATCH_ROOT',tempfile.gettempdir())
    if not selected:raise ValueError('Empty scratch root; no fallback.')
    root=Path(selected).expanduser().resolve(strict=True)
    if not root.is_dir():raise ValueError('Scratch root must be an existing directory.')
    required=os.environ.get('NADOC_TEST_SCRATCH_MOUNT')
    if required is not None:
        mount=Path(required).expanduser().resolve(strict=True)
        if not required or not mount.is_mount() or not root.is_relative_to(mount) or root.stat().st_dev!=mount.stat().st_dev:
            raise ValueError('Required scratch mount unavailable; no fallback.')
    return root


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def restraint(group_a,group_b,center,stiffness,grid_max,grid_step=.005):
    # Match the piecewise-linear native potential exactly in analysis.
    count=int(round(grid_max/grid_step))+1
    if not np.isclose((count-1)*grid_step,grid_max):raise ValueError('Grid endpoint must be an exact multiple of spacing.')
    grid=.5*stiffness*(np.linspace(0,grid_max,count)-center)**2
    common=f'''type = meta_com_trap
p1a = {','.join(map(str,group_a))}
p2a = {','.join(map(str,group_b))}
PBC = true
xmin = 0
xmax = {grid_max:g}
N_grid = {count}
potential_grid = {','.join(f'{v:.15g}' for v in grid)}
'''
    return ''.join('{\n'+common+f'mode = {mode}\n}}\n' for mode in (1,2))


def input_text(root,conf,backend,steps,seed,temperature,salt,group_a,group_b,*,dt=.005,output_every=1000,trajectory_every=10000,forces=True,thermostat='brownian',refresh_vel=True,op=True):
    root=Path(root).resolve();conf=Path(conf).resolve()
    result=f'''backend = {backend}
backend_precision = {'mixed' if backend=='CUDA' else 'double'}
sim_type = MD
interaction_type = DNA2
T = {temperature}C
salt_concentration = {salt}
use_average_seq = false
seq_dep_file = {root/'oxDNA2_sequence_dependent_parameters.txt'}
topology = {root/'topology.top'}
conf_file = {conf}
steps = {steps}
seed = {seed}
dt = {dt}
thermostat = {thermostat}
newtonian_steps = 100
diff_coeff = 2.5
refresh_vel = {'true' if refresh_vel else 'false'}
restart_step_counter = true
verlet_skin = 0.2
CUDA_list = verlet
cells_auto_optimisation = false
max_density_multiplier = 10
CUDA_sort_every = 0
use_edge = 1
fix_diffusion = true
fix_diffusion_every = 10000
external_forces = {'true' if forces else 'false'}
external_forces_file = forces.txt
print_conf_interval = {trajectory_every}
print_energy_every = {output_every}
time_scale = linear
lastconf_file = last_conf.dat
trajectory_file = trajectory.dat
energy_file = energy.dat
max_io = 1000
no_stdout_energy = true
'''
    if output_every:
        result+='''data_output_1 = {
name = samples.dat
print_every = '''+str(output_every)+'''
col_1 = { type = step }
col_2 = {
type = distance
particle_1 = '''+','.join(map(str,group_a))+'''
particle_2 = '''+','.join(map(str,group_b))+'''
PBC = true
}
'''
        if op:result+='col_3 = {\ntype = hb_list\nonly_count = true\nop_file = '+str(root/'vmmc_op.txt')+'\n}\n'
        else:result+='col_3 = { type = potential_energy }\n'
        result+='}\n'
    return result


def execute(binary,directory,text,force_text=None):
    if _cancelled.is_set():raise RuntimeError('Campaign cancelled.')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    (directory/'input.txt').write_text(text)
    if force_text is not None:(directory/'forces.txt').write_text(force_text)
    start=time.monotonic()
    with (directory/'native.log').open('w') as log:
        with _lock:
            if _cancelled.is_set():raise RuntimeError('Campaign cancelled.')
            result=subprocess.Popen([str(binary),'input.txt'],cwd=directory,stdout=log,stderr=subprocess.STDOUT)
            _active.add(result)
        try:result.wait()
        finally:
            with _lock:_active.discard(result)
    elapsed=time.monotonic()-start
    log=(directory/'native.log').read_text()
    report={'returncode':result.returncode,'wall_seconds':elapsed,'input_sha256':digest(directory/'input.txt'),'forces_sha256':digest(directory/'forces.txt') if force_text is not None else None}
    (directory/'execution.json').write_text(json.dumps(report,indent=2)+'\n')
    if result.returncode or 'off grid!' in log or 'END OF THE SIMULATION' not in log:
        raise RuntimeError(f'Native umbrella stage failed: {directory}\n{log[-2000:]}')
    requested=int(next(line.split('=',1)[1] for line in text.splitlines() if line.split('=')[0].strip()=='steps'))
    completed=int((directory/'last_conf.dat').read_text().splitlines()[0].split('=')[1])
    if completed!=requested:raise ValueError(f'Incomplete native stage: {completed}/{requested}.')
    data=np.loadtxt(directory/'samples.dat',ndmin=2)
    conf=np.loadtxt(directory/'last_conf.dat',skiprows=3,ndmin=2)
    if not np.isfinite(data).all() or not np.isfinite(conf).all():raise ValueError('Nonfinite native output.')
    return report
