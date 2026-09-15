"""Reproduce the loop-origin abort and verify the fix with isolated short NAMD runs."""
from pathlib import Path
import json
import re
import subprocess
from backend.core import md_protocols
from backend.core.namd_graphene import configure_graphene_equilibration, graphene_pressure_conf

root = Path(__file__).resolve().parent
repo = root.parents[1]
source = repo / 'experiments/graphene_pressure_implementation_20260914/z/production.conf'
wall = {'dir': [0, 0, -1], 'plane_point_nm': [6.177, 6.148780367, 1.2]}
configure_graphene_equilibration(wall)
# Use the actual generated adaptive script, shortened to two chunks.
raw = md_protocols._min_conf('probe', 'probe', (120, 120, 120), False, 161600, .5, n_atoms=1615887)
loop = raw[raw.index('# NADOC_ADAPTIVE_MIN_BEGIN'):]
for key, value in [('max', 40), ('min', 40), ('chunk', 20)]:
    loop = re.sub(r'^set nadoc_min_' + key + r' \d+', f'set nadoc_min_{key} {value}', loop, flags=re.M)
records = []
for case in ['broken', 'fixed']:
    directory = root / case
    directory.mkdir(exist_ok=True)
    (directory / 'output').mkdir(exist_ok=True)
    lines = []
    omit = {'run', 'cellOrigin', 'binVelocities', 'extendedSystem'}
    for line in source.read_text().splitlines():
        key = line.split()[0] if line.split() else ''
        if key in omit:
            continue
        if key == 'outputName': line = 'outputName output/probe'
        elif key == 'dcdFile': line = 'dcdFile output/probe.dcd'
        elif key == 'dcdFreq': line = 'dcdFreq 0'
        elif key == 'outputEnergies': line = 'outputEnergies 20'
        elif key == 'rigidBonds': line = 'rigidBonds none'
        elif key == 'langevinTemp': line = 'langevinTemp 0'
        lines.append(line)
    text = '\n'.join(lines) + '\ntemperature 0\n' + loop
    text = graphene_pressure_conf(text, enabled=True, wall=wall)
    if case == 'broken':
        origin = next(line for line in text.splitlines() if line.startswith('cellOrigin '))
        text = text.replace(origin + '\n', '').replace('    minimize $nadoc_min_this', origin + '\n    minimize $nadoc_min_this')
    (directory / 'probe.conf').write_text(text)
    with (directory / 'probe.log').open('w') as log:
        result = subprocess.run(['/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3', '+p1', '+devices', '0', 'probe.conf'], cwd=directory, stdout=log, stderr=subprocess.STDOUT)
    output = (directory / 'probe.log').read_text()
    record = {'case': case, 'exit_code': result.returncode, 'chunks': re.findall(r'NADOC_ADAPTIVE_MIN step=(\d+)', output), 'cell_origin_abort': 'FATAL ERROR: Setting parameter cellOrigin from script failed!' in output}
    records.append(record)
    (root / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
    print(record, flush=True)
    if case == 'broken': assert record['cell_origin_abort'] and record['chunks'] == ['20']
    else:
        assert result.returncode == 0 and record['chunks'] == ['20', '40']
        xsc = (directory / 'output/probe.xsc').read_text().splitlines()[-1].split()
        assert all(abs(float(v) - c * 10) < 1e-6 for v,c in zip(xsc[10:13], wall['plane_point_nm']))
