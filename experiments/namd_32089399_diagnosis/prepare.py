"""Prepare isolated checkpoint replays; never modify the original job package."""
from pathlib import Path
import re
import json
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PACKAGE = ROOT / 'workspace/md_jobs/7aa73d7afe93/package/small_plate_namd_solvated'
SOURCE = PACKAGE / 'small_plate_03_300K_NPT_ENM_k0p01_p10.conf'
variants = {'baseline': {}, 'margin4': {'margin': '4'}, 'margin6': {'margin': '6'}, 'offload': {'GPUresident': 'off'}, 'relax2fs': {'timestep': '2'}, 'enm_control': {'extraBondsFile': str(PACKAGE / 'small_plate_k0.1.enm.extra')}}
path_keys = {'structure', 'coordinates', 'consref', 'conskfile', 'parameters', 'extraBondsFile', 'binCoordinates', 'binVelocities', 'extendedSystem'}
for name, changes in variants.items():
    run_dir = HERE / name
    run_dir.mkdir(exist_ok=True)
    changes = {'outputEnergies': '10', 'xstFreq': '100', 'restartfreq': '100', 'dcdFreq': '100', 'run': '5000', **changes}
    result = []
    for line in SOURCE.read_text().splitlines():
        fields = line.split()
        if not fields:
            result.append(line)
            continue
        key = fields[0]
        if key in changes:
            line = f'{key} {changes[key]}'
        elif key in path_keys:
            line = f'{key} {PACKAGE / fields[1]}'
        elif key in {'outputName', 'dcdFile', 'xstFile'}:
            ext = {'outputName': '', 'dcdFile': '.dcd', 'xstFile': '.xst'}[key]
            line = f'{key} {run_dir / ("replay" + ext)}'
        result.append(line)
    (run_dir / 'replay.conf').write_text('\n'.join(result) + '\n')
(HERE / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
print('Prepared', ', '.join(variants))
