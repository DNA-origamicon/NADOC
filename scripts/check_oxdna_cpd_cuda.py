"""Numerical CUDA/CPU audit using an existing managed CPD job (no authored structures).

GPU outputs are temporary physical diagnostic data. CPU evaluates the exact same
GPU poses, avoiding chaotic trajectory divergence as a false force comparison.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np


def settings(job, plugin, directory, *, backend='CUDA', steps=2, edge=False, sort_every=1):
    job, plugin, directory = map(Path, (job, plugin, directory))
    metadata = json.loads((job / 'job.json').read_text())
    last = next(job / stage['name'] for stage in reversed(metadata['stages']) if (job / stage['name'] / 'last_conf.dat').is_file())
    text = (last / 'input.txt').read_text()
    inp = {k.strip(): v.strip() for line in text.splitlines() if '=' in line and not line.lstrip().startswith('#')
           for k, v in [line.split('=', 1)]}
    inp.update(backend=backend, backend_precision='mixed', steps=str(steps), refresh_vel='false',
               conf_file=str(last / 'last_conf.dat'), topology=str(job / 'topology.top'),
               cpd_file=str(job / 'cpd.dat'), plugin_search_path=str(plugin), external_forces='false',
               use_edge=str(edge).lower(), CUDA_sort_every=str(sort_every),
               trajectory_file=str(directory / 'trajectory.dat'), energy_file=str(directory / 'energy.dat'),
               lastconf_file=str(directory / 'last_conf.dat'), log_file=str(directory / 'native.log'))
    if 'seq_dep_file' in inp: inp['seq_dep_file'] = str(job / 'oxDNA2_average_sequence_parameters.txt')
    return inp


def check(job, plugin, binary, *, edge=False, steps=2):
    import oxpy
    with tempfile.TemporaryDirectory(prefix='nadoc-cpd-cuda-audit-') as td:
        directory = Path(td)
        inp = settings(job, plugin, directory, steps=steps, edge=edge)
        inp['verlet_skin'] = '.002'
        inp['cpd_cuda_audit_file'] = str(directory / 'forces.txt')
        path = directory / 'input'
        path.write_text('\n'.join(f'{k} = {v}' for k,v in inp.items()))
        run = subprocess.run([str(binary), str(path)], cwd=directory, capture_output=True, text=True)
        if run.returncode: raise RuntimeError((run.stdout + run.stderr)[-8000:])
        rows = np.loadtxt(directory / 'forces.txt')
        order = rows[:, 0].astype(int)
        assert set(order) == set(range(len(rows)))
        # Re-import the GPU physical frame through the native reader so cached
        # sites and orientation transposes are rebuilt, not stale oxpy fields.
        original = Path(inp['conf_file']).read_text().splitlines()
        lines = original[:3]
        ordered = rows[np.argsort(order)]
        for row in ordered:
            x,y,z,w = row[4:8]
            a1=[x*x-y*y-z*z+w*w,2*(x*y+z*w),2*(x*z-y*w)]
            a3=[2*(x*z+y*w),2*(y*z-x*w),-x*x-y*y+z*z+w*w]
            lines.append(' '.join(format(float(v),'.17g') for v in [*row[1:4],*a1,*a3,*([0]*6)]))
        frame = directory / 'gpu-frame.dat'
        frame.write_text('\n'.join(lines)+'\n')
        inp.update(backend='CPU', steps='0', conf_file=str(frame), refresh_vel='true')
        inp.pop('cpd_cuda_audit_file')
        native = oxpy.InputFile()
        for key, value in inp.items(): native[key] = value
        with oxpy.Context():
            manager = oxpy.OxpyManager(native)
            info = manager.config_info()
            particles = info.particles()
            for p in particles:
                p.force = np.zeros(3); p.torque = np.zeros(3)
            for i,p in enumerate(particles):
                for q in particles[i+1:]: info.interaction.pair_interaction(p,q,True,True)
            cpu = np.array([list(particles[i].force)+list(particles[i].torque) for i in order])
            gpu = rows[:, 8:14]
            error = np.abs(cpu-gpu)
            # CPU DNA2 uses angular interpolation meshes; CUDA evaluates angles
            # analytically. Audit the new CPD pair separately at float precision.
            for p in particles: p.force=np.zeros(3);p.torque=np.zeros(3)
            manifest=json.loads((Path(job)/'cpd_manifest.json').read_text())
            for weld in manifest['endpoints']:
                i,j=weld['particles']
                info.interaction.pair_interaction_bonded(particles[i],particles[j],True,True)
            pair_cpu=np.array([list(particles[i].force)+list(particles[i].torque) for i in order])
            pair_error=np.abs(pair_cpu-rows[:,14:20])
            passed = bool(np.isfinite(gpu).all() and np.all(error <= .05 + .01*np.abs(cpu))
                          and np.all(pair_error <= .002 + 1e-4*np.abs(pair_cpu)))
            result = dict(job=str(job), edge=edge, steps=steps, sorted=not np.array_equal(order,np.arange(len(rows))),
                          particles=len(rows), max_abs_error=float(error.max()),
                          max_scaled_error=float((error/(.05+.01*np.abs(cpu))).max()),
                          cpd_max_abs_error=float(pair_error.max()), cpd_max_scaled_error=float((pair_error/(.002+1e-4*np.abs(pair_cpu))).max()), passed=passed)
            del info, particles, manager
        if not passed:
            worst=np.unravel_index(error.argmax(),error.shape)
            result['worst']={'particle':int(order[worst[0]]),'component':int(worst[1]),'cpu':float(cpu[worst]),'gpu':float(gpu[worst])}
            raise AssertionError(result)
        return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job',type=Path);parser.add_argument('plugin',type=Path)
    parser.add_argument('--binary',type=Path,default=Path.home()/'.local/share/nadoc/engines/oxdna/current/bin/oxDNA')
    parser.add_argument('--edge',action='store_true');parser.add_argument('--steps',type=int,default=2)
    args=parser.parse_args()
    print(json.dumps(check(args.job.resolve(),args.plugin.resolve(),args.binary,edge=args.edge,steps=args.steps),indent=2))
