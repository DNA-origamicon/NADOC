"""Native CLI controls for global coupling, point rotations, and current-K A/B.

The optional LD_PRELOAD experiment affects only explicitly selected CPU child
processes. It does not alter the installed engine or application defaults.
"""
from pathlib import Path
import json
import os
import subprocess
import time

import numpy as np

ROOT = Path(os.environ.get('NADOC_OXDNA_AUDIT_DIR', str(Path(__file__).resolve().parents[3]/'workspace/validation/fundamental_audit_20260913'))).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
ENGINE = Path(os.environ.get('NADOC_OXDNA_AUDIT_ENGINE', str(Path.home()/'.local/share/nadoc/engines/oxdna/current/bin/oxDNA'))).resolve()
T = 296/3000


def fixture(n=64, protein=32, hot=False, drift=False):
    a = np.zeros((n, 15))
    a[:, 0] = (np.arange(n) % 8)*10+10
    a[:, 1] = (np.arange(n)//8)*10+10
    a[:, 2] = 10
    a[:, 3] = 1
    a[:, 8] = 1
    rng = np.random.default_rng(1819)
    a[:, 9:12] = rng.normal(size=(n, 3))*np.sqrt(T)
    for lo, hi, temperature in [(0, protein, .25*T if hot else T), (protein, n, 2*T if hot else T)]:
        if lo == hi:
            continue
        v = a[lo:hi, 9:12]
        v -= v.mean(axis=0)
        v *= np.sqrt(3*(hi-lo-1)*temperature/np.sum(v*v))
    a[protein:, 12:15] = rng.normal(size=(n-protein, 3))*np.sqrt(T)
    if drift:
        a[:, 9] += 1.
    return a


def read_frames(path, n):
    data = []
    lines = path.read_text().splitlines()
    for j in range(0, len(lines), n+3):
        if len(lines[j:j+n+3]) == n+3:
            data.append(np.array([[float(x) for x in line.split()] for line in lines[j+3:j+3+n]]))
    return np.array(data)


def run(name, backend, thermostat, a, protein, steps, dt=.001, stride=10,
        settings='', forces='', experimental=False, random_seed=1919):
    d = ROOT/'thermostats'/name
    d.mkdir(parents=True, exist_ok=True)
    n = len(a)
    with (d/'conf.dat').open('w') as f:
        f.write('t = 0\nb = 200 200 200\nE = 0 0 0\n')
        np.savetxt(f, a, fmt='%.17g')
    if protein:
        top = f'{n} {n} {n-protein} {protein} {n-protein}\n'
        top += ''.join(f'-{i+1} A -1 -1\n' for i in range(protein))
        top += ''.join(f'{i+1} G -1 -1\n' for i in range(n-protein))
        (d/'anm.par').write_text(f'{protein}\n')
    else:
        top = f'{n} {n}\n'+''.join(f'{i+1} G -1 -1\n' for i in range(n))
    (d/'topology.top').write_text(top)
    (d/'forces.txt').write_text(forces)
    (d/'input').write_text(f'''backend = {backend}
backend_precision = mixed
sim_type = MD
interaction_type = {'DNANM' if protein else 'DNA2'}
parfile = anm.par
topology = topology.top
conf_file = conf.dat
steps = {steps}
dt = {dt}
T = 296K
seed = {random_seed}
thermostat = {thermostat}
refresh_vel = false
fix_diffusion = false
restart_step_counter = true
external_forces = {'true' if forces else 'false'}
external_forces_file = forces.txt
salt_concentration = .5
verlet_skin = .2
CUDA_list = verlet
use_edge = true
trajectory_file = trajectory.dat
lastconf_file = last_conf.dat
energy_file = energy.dat
time_scale = linear
print_conf_interval = {stride}
print_energy_every = {stride}
max_io = 1000
{settings}
''')
    env = dict(os.environ, OMP_NUM_THREADS='1')
    if experimental:
        assert backend == 'CPU'
        library = 'baseline_experiment.so' if experimental == 'baseline' else 'current_k_experiment.so'
        env['LD_PRELOAD'] = str(ROOT/library)
    started = time.monotonic()
    with (d/'run.log').open('w') as log:
        p = subprocess.run([str(ENGINE), 'input'], cwd=d, stdout=log,
                           stderr=subprocess.STDOUT, env=env, timeout=90)
    if p.returncode:
        raise RuntimeError((d/'run.log').read_text()[-2000:])
    if experimental:
        marker = 'AUDIT ONLY unchanged' if experimental == 'baseline' else 'AUDIT ONLY current-K'
        assert marker in (d/'run.log').read_text()
    frames = read_frames(d/'trajectory.dat', n)
    last = np.loadtxt(d/'last_conf.dat', skiprows=3)
    tail = frames[len(frames)//2:]
    result = dict(name=name, backend=backend, thermostat=thermostat,
        random_seed=random_seed,
        experimental_current_K=bool(experimental and experimental != 'baseline'),
        experimental_variant=experimental, seconds=time.monotonic()-started,
        samples=len(tail), initial_COM_velocity=a[:, 9:12].mean(axis=0).tolist(),
        final_COM_velocity=last[:, 9:12].mean(axis=0).tolist(),
        point_initial_L2=float(np.sum(a[:protein, 12:15]**2)),
        point_final_L2=float(np.sum(last[:protein, 12:15]**2)),
        initial_relative_K=float(.5*np.sum((a[:, 9:12]-a[:, 9:12].mean(axis=0))**2)),
        final_relative_K=float(.5*np.sum((last[:, 9:12]-last[:, 9:12].mean(axis=0))**2)))
    if protein and len(tail):
        result.update(protein_T_ratio=float(np.mean(tail[:, :protein, 9:12]**2)/T),
            DNA_translation_T_ratio=float(np.mean(tail[:, protein:, 9:12]**2)/T),
            DNA_rotation_T_ratio=float(np.mean(tail[:, protein:, 12:15]**2)/T),
            point_rotation_energy_mean=float(.5*np.mean(np.sum(tail[:, :protein, 12:15]**2, axis=(1, 2)))))
    return result


def main():
    results = []
    def add(*args, **kwargs):
        r = run(*args, **kwargs)
        results.append(r)
        print(json.dumps(r), flush=True)
        (ROOT/'thermostat_report.json').write_text(json.dumps(results, indent=2))

    for backend in ['CPU', 'CUDA']:
        for thermostat, settings in [('bussi', 'newtonian_steps = 10\nbussi_tau = 1000'),
                                     ('john', 'newtonian_steps = 10\npt = 1')]:
            add(f'hot_cold_{backend}_{thermostat}', backend, thermostat,
                fixture(hot=True), 32, 20000, settings=settings)
    a = fixture(protein=0)
    a[:, 9:12] *= np.sqrt(2.)
    for backend, experimental in [('CPU', False), ('CUDA', False), ('CPU', 'baseline'), ('CPU', True)]:
        add(f'weak_{backend}_{experimental}', backend, 'bussi', a, 0, 1, stride=1,
            settings='newtonian_steps = 1\nbussi_tau = 1000000000', experimental=experimental)
    forces = '{\ntype = string\nparticle = -1\nF0 = .02\nrate = 0\ndir = 1,0,0\n}\n'
    for backend in ['CPU', 'CUDA']:
        for thermostat, settings in [('bussi', 'newtonian_steps = 10\nbussi_tau = 1000'),
                                     ('john', 'newtonian_steps = 10\ndiff_coeff = .1')]:
            add(f'drift_{backend}_{thermostat}', backend, thermostat,
                fixture(protein=0, drift=True), 0, 10000, stride=100,
                settings=settings, forces=forces)


if __name__ == '__main__':
    main()
