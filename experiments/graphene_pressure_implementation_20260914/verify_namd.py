"""Actual NAMD axis constraints and NPAT -> restart -> NVT handoff smoke test.

Uses the prior wet bare-pore control; no existing job or research input is edited.
Three cyclic rigid permutations keep the force field and physical assembly identical.
The sheet is translated to 1.2 nm so the origin is deliberately off the box midpoint.
"""
from pathlib import Path
import json
import struct
import subprocess
import numpy as np
from backend.core.namd_graphene import configure_graphene_equilibration, graphene_pressure_conf

root = Path(__file__).resolve().parent
source = root.parent / 'cube_pore_cavity_20260914/open_pore/fill_100'
meta = json.loads((source / 'meta.json').read_text())
exe = '/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3'
results = {}
for axis, order in enumerate(([2, 0, 1], [1, 2, 0], [0, 1, 2])):
    directory = root / 'xyz'[axis]
    directory.mkdir(exist_ok=True)
    box = np.array(meta['box_nm'])[order] * 10
    shift = np.zeros(3); shift[axis] = -48
    center = np.array(meta['pore_center_nm'])[order] + shift / 10
    wall = {'dir': np.eye(3)[axis].tolist(), 'plane_point_nm': center.tolist()}
    configure_graphene_equilibration(wall)
    for ext in ['coor', 'vel']:
        data = (source / ('run.' + ext)).read_bytes()
        n, = struct.unpack('<i', data[:4])
        xyz = np.frombuffer(data, '<f8', offset=4).reshape(n, 3)[:, order].copy()
        if ext == 'coor': xyz += shift
        (directory / ('start.' + ext)).write_bytes(data[:4] + xyz.astype('<f8').tobytes())
    pdb = []
    for line in (source / 'system.pdb').read_text().splitlines():
        if line.startswith(('ATOM', 'HETATM')):
            xyz = np.array([float(line[i:i + 8]) for i in (30, 38, 46)])[order] + shift
            line = line[:30] + ''.join(f'{v:8.3f}' for v in xyz) + line[54:]
        pdb.append(line)
    (directory / 'system.pdb').write_text('\n'.join(pdb) + '\n')
    original = (source / 'run.conf').read_text().splitlines()
    previous = None
    records = []
    for name, npt in [('equilibrate', True), ('resume', True), ('production', False)]:
        conf = []
        for line in original:
            key = line.split()[0] if line.split() else ''
            if key in ['run', 'minimize', 'reinitvels', 'temperature', 'cellOrigin']: continue
            if key.startswith('cellBasisVector'):
                index = int(key[-1]) - 1
                line = key + ' ' + ' '.join(str(v) for v in np.eye(3)[index] * box[index])
            elif key in ['coordinates', 'consref']: line = key + ' ' + str(directory / 'system.pdb')
            elif key == 'langevinPiston': line = key + (' on' if npt else ' off')
            elif key == 'outputName': line = key + ' ' + str(directory / name)
            elif key == 'dcdFile': line = key + ' ' + str(directory / (name + '.dcd'))
            elif key in ['dcdFreq', 'restartfreq', 'xstFreq', 'outputEnergies']: line = key + ' 1000'
            conf.append(line)
        initial = directory / (previous or 'start')
        conf += ['binCoordinates ' + str(initial) + '.coor', 'binVelocities ' + str(initial) + '.vel']
        if previous: conf += ['extendedSystem ' + str(initial) + '.xsc']
        if npt: conf += ['langevinPistonTemp 300']
        conf += ['run 2000']
        text = graphene_pressure_conf('\n'.join(conf) + '\n', enabled=True, wall=wall)
        path = directory / (name + '.conf')
        path.write_text(text)
        log = directory / (name + '.log')
        with log.open('w') as handle:
            code = subprocess.run([exe, '+p1', '+devices', '0', str(path)], stdout=handle, stderr=subprocess.STDOUT).returncode
        output = log.read_text()
        assert code == 0 and 'End of program' in output and 'FATAL ERROR' not in output, str(log)
        xsc = np.array((directory / (name + '.xsc')).read_text().splitlines()[-1].split(), float)
        lengths = xsc[1:10].reshape(3, 3).diagonal()
        assert int(xsc[0]) == 2000
        assert np.allclose(xsc[10:13], center * 10, atol=1e-7)
        tangents = [i for i in range(3) if i != axis]
        assert np.allclose(lengths[tangents], box[tangents], atol=1e-7, rtol=0)
        if previous and not npt: assert np.allclose(lengths, records[-1]['box_angstrom'], atol=1e-7, rtol=0)
        if npt: assert abs(lengths[axis] - box[axis]) > .001
        records.append({'stage': name, 'completed_steps': 2000, 'box_angstrom': lengths.tolist(), 'origin_angstrom': xsc[10:13].tolist()})
        results['xyz'[axis]] = records
        (root / 'namd_verification.json').write_text(json.dumps(results, indent=2) + '\n')
        print('xyz'[axis], name, lengths.tolist(), flush=True)
        previous = name
