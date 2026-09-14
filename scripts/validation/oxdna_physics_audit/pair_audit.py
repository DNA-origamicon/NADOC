"""Independent CLI impulse / analytic-potential audit; no original oxpy worker.

Run from the repository with .venv/bin/python. Only writes under this folder.
No thermostat, gold, linker, ANM spring, or random velocities in contact tests.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(os.environ.get('NADOC_OXDNA_AUDIT_DIR', str(Path(__file__).resolve().parents[3]/'workspace/validation/fundamental_audit_20260913'))).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
ENGINE = Path(os.environ.get('NADOC_OXDNA_AUDIT_ENGINE', str(Path.home()/'.local/share/nadoc/engines/oxdna/current/bin/oxDNA'))).resolve()
# Match literal parameter precision, not a fit to measured forces.
f32 = lambda x: float(np.float32(x))
PARAMS = {'back': list(map(f32, [.57, .569, 178699253.5, .572934])),
          'base': list(map(f32, [.36, .359, 296866090., .362897])),
          'protein': [f32(.35), f32(.349), f32(306484596.421), .352894]}
OFFSETS = {'back': np.array([f32(-.3400), f32(.3408), 0.]),
           'base': np.array([f32(.4), 0., 0.])}


def radial(r, kind, epsilon=1.):
    sigma, star, b, cutoff = PARAMS[kind]
    if r >= cutoff:
        return 0., 0.
    if r > star:
        return epsilon*b*(r-cutoff)**4, 4*epsilon*b*(r-cutoff)**3
    q = (sigma/r)**6
    return 4*epsilon*(q*q-q), 24*epsilon*(q-2*q*q)/r


def oracle(a, protein_only=False):
    energy = 0.
    force = np.zeros((2, 3))
    torque = np.zeros((2, 3))
    if protein_only:
        rvec = a[0, :3]-a[1, :3]
        r = np.linalg.norm(rvec)
        energy, du = radial(r, 'protein', 2.)
        force[0] = -du*rvec/r
        force[1] = -force[0]
    else:
        a1, a3 = a[1, 3:6], a[1, 6:9]
        axes = np.column_stack([a1, np.cross(a3, a1), a3])
        for kind, offset in OFFSETS.items():
            lever = axes@offset
            rvec = a[0, :3]-a[1, :3]-lever
            r = np.linalg.norm(rvec)
            u, du = radial(r, kind)
            f = -du*rvec/r
            energy += u
            force[0] += f
            force[1] -= f
            torque[1] += axes.T@np.cross(lever, -f)
    return energy, force, torque


def write_conf(path, a):
    with path.open('w') as f:
        f.write('t = 0\nb = 100 100 100\nE = 0 0 0\n')
        np.savetxt(f, a, fmt='%.17g')


def cli_run(folder, a, backend, dt, protein_only=False, thermostat='no', extra=''):
    folder.mkdir(parents=True, exist_ok=True)
    write_conf(folder/'conf.dat', a)
    top = '2 2 0 2 0\n-1 A -1 -1\n-2 A -1 -1\n' if protein_only else '2 2 1 1 1\n-1 A -1 -1\n1 G -1 -1\n'
    (folder/'topology.top').write_text(top)
    (folder/'anm.par').write_text('2\n' if protein_only else '1\n')
    (folder/'input').write_text(f'''backend = {backend}
backend_precision = mixed
sim_type = MD
interaction_type = DNANM
parfile = anm.par
topology = topology.top
conf_file = conf.dat
steps = 1
dt = {dt}
T = 296K
seed = 1919
thermostat = {thermostat}
refresh_vel = false
fix_diffusion = false
restart_step_counter = true
external_forces = false
salt_concentration = .5
verlet_skin = .2
CUDA_list = verlet
use_edge = true
trajectory_file = trajectory.dat
lastconf_file = last_conf.dat
energy_file = energy.dat
time_scale = linear
print_conf_interval = 1
print_energy_every = 1
max_io = 1000
{extra}
''')
    with (folder/'run.log').open('w') as log:
        p = subprocess.run([str(ENGINE), 'input'], cwd=folder, stdout=log,
                           stderr=subprocess.STDOUT, env=dict(os.environ, OMP_NUM_THREADS='1'), timeout=30)
    if p.returncode:
        raise RuntimeError((folder/'run.log').read_text()[-2500:])
    last = np.loadtxt(folder/'last_conf.dat', skiprows=3)
    return (last[:, 9:12]-a[:, 9:12])/dt, (last[:, 12:15]-a[:, 12:15])/dt


def finite_difference(a, protein_only=False):
    h = 1e-6
    f = np.zeros((2, 3))
    t = np.zeros((2, 3))
    for i in range(2):
        for j in range(3):
            plus, minus = a.copy(), a.copy()
            plus[i, j] += h
            minus[i, j] -= h
            f[i, j] = -(oracle(plus, protein_only)[0]-oracle(minus, protein_only)[0])/(2*h)
    if not protein_only:
        axes = np.column_stack([a[1, 3:6], np.cross(a[1, 6:9], a[1, 3:6]), a[1, 6:9]])
        for j in range(3):
            plus, minus = a.copy(), a.copy()
            for sign, arr in [(1, plus), (-1, minus)]:
                rot = Rotation.from_rotvec(sign*h*axes[:, j])
                arr[1, 3:6] = rot.apply(a[1, 3:6])
                arr[1, 6:9] = rot.apply(a[1, 6:9])
            t[1, j] = -(oracle(plus)[0]-oracle(minus)[0])/(2*h)
    return f, t


def main():
    results = []
    rotation = Rotation.from_rotvec([.31, -.47, .23]).as_matrix()
    for kind in ['back', 'base', 'protein']:
        sigma, star, _, cutoff = PARAMS[kind]
        for branch, r in [('core', star-.025), ('smooth', (star+cutoff)/2), ('outside', cutoff+.01)]:
            for rotated in ([False, True] if kind != 'protein' else [False]):
                a = np.zeros((2, 15))
                a[:, 3] = 1.
                a[:, 8] = 1.
                # Initial angular momentum must be nonzero for rigid nucleotide.
                if kind != 'protein':
                    a[1, 12:15] = [1e-9, -2e-9, 3e-9]
                a[1, :3] = 2.
                offset = OFFSETS.get(kind, np.zeros(3))
                direction = np.array([0., 0., 1.])
                a[0, :3] = a[1, :3]+offset+r*direction
                if rotated:
                    a[:, :3] = (a[:, :3]-2.)@rotation.T+2.
                    a[:, 3:6] = a[:, 3:6]@rotation.T
                    a[:, 6:9] = a[:, 6:9]@rotation.T
                name = f'{kind}_{branch}_{"rotated" if rotated else "identity"}'
                u, f, t = oracle(a, kind == 'protein')
                ff, tf = finite_difference(a, kind == 'protein')
                row = dict(name=name, energy=u, force=f.tolist(), torque=t.tolist(),
                           finite_difference_force_error=float(np.linalg.norm(ff-f)/max(1., np.linalg.norm(f))),
                           finite_difference_torque_error=float(np.linalg.norm(tf-t)/max(1., np.linalg.norm(t))), runs=[])
                for dt in [1e-5, 1e-6]:
                    values = {}
                    for backend in ['CPU', 'CUDA']:
                        fn, tn = cli_run(ROOT/'pairs'/name/f'{backend}_{dt}', a, backend, dt, kind == 'protein')
                        values[backend] = (fn, tn)
                        row['runs'].append(dict(backend=backend, dt=dt,
                            force=fn.tolist(), torque=tn.tolist(),
                            force_oracle_ratio=float(np.linalg.norm(fn)/np.linalg.norm(f)) if np.linalg.norm(f) else None,
                            torque_oracle_ratio=float(np.linalg.norm(tn)/np.linalg.norm(t)) if np.linalg.norm(t) else None,
                            force_oracle_error=float(np.linalg.norm(fn-f)/max(1., np.linalg.norm(f))),
                            torque_oracle_error=float(np.linalg.norm(tn-t)/max(1., np.linalg.norm(t))),
                            net_force=float(np.linalg.norm(fn.sum(axis=0)))))
                results.append(row)
                print(name, [(v['backend'], v['force_oracle_ratio'], v['torque_oracle_ratio']) for v in row['runs'][-2:]], flush=True)
                (ROOT/'pair_report.json').write_text(json.dumps(dict(engine=str(ENGINE.resolve()),
                    engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(), cases=results), indent=2))


if __name__ == '__main__':
    main()
