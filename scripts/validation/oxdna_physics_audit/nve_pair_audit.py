"""Does CUDA conserve its own (twice-strength) contact Hamiltonian?"""
import json
import os
import re
import subprocess
import numpy as np
from pair_audit import ROOT, ENGINE, oracle
from thermostat_audit import read_frames

results = []
for backend in ['CPU', 'CUDA']:
    for dt in [1e-4, 5e-5]:
        d = ROOT/'pair_nve'/f'{backend}_{dt}'
        d.mkdir(parents=True, exist_ok=True)
        base = ROOT/'pairs/back_core_rotated'/f'{backend}_1e-06'
        for name in ['conf.dat', 'topology.top', 'anm.par']:
            (d/name).write_bytes((base/name).read_bytes())
        text = (base/'input').read_text()
        for key, value in dict(steps=round(1/dt), dt=dt,
                print_conf_interval=round(.005/dt), print_energy_every=round(.005/dt)).items():
            text = re.sub(r'^'+key+r' = .*$', f'{key} = {value}', text, flags=re.M)
        (d/'input').write_text(text)
        with (d/'run.log').open('w') as log:
            p = subprocess.run([str(ENGINE), 'input'], cwd=d, stdout=log,
                stderr=subprocess.STDOUT, env=dict(os.environ, OMP_NUM_THREADS='1'), timeout=30)
        assert p.returncode == 0
        frames = read_frames(d/'trajectory.dat', 2)
        frames = np.concatenate([np.loadtxt(d/'conf.dat', skiprows=3)[None], frames])
        u = np.array([oracle(frame)[0] for frame in frames])
        kinetic = .5*(np.sum(frames[:, :, 9:12]**2, axis=(1, 2))+np.sum(frames[:, 1, 12:15]**2, axis=1))
        e_cpu = kinetic+u
        e_gpu = kinetic+2*u
        native_e = e_cpu if backend == 'CPU' else e_gpu
        row = dict(backend=backend, dt=dt, samples=len(frames),
            CPU_reference_energy_initial=float(e_cpu[0]),
            CPU_reference_energy_range=float(np.ptp(e_cpu)),
            own_Hamiltonian_initial=float(native_e[0]),
            own_Hamiltonian_range=float(np.ptp(native_e)),
            own_Hamiltonian_relative_range=float(np.ptp(native_e)/abs(native_e[0])))
        np.savez(d/'energy.npz', cpu_reference=e_cpu, twice_contact=e_gpu)
        results.append(row)
        (ROOT/'pair_nve_report.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(row), flush=True)
