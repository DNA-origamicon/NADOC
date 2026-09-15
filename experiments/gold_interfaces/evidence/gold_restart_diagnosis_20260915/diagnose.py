"""Isolated restart mechanism experiments; no arbitrary pass/fail tolerances."""
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np
from backend.core.namd_gold_package import config, sha
from backend.core.md_charge import parse_psf_atoms
from experiments.gold_interfaces.native import read_binary, checkpoint_step

ROOT = Path(__file__).resolve().parents[4]/'workspace/gold_restart_diagnosis_20260915'
REPO = Path(__file__).resolve().parents[4]
BINARY = Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')

def prepare(name, source):
    dest = ROOT/name
    if dest.exists():
        return dest
    dest.mkdir()
    (dest/'output').mkdir()
    for p in source.iterdir():
        if p.name == 'forcefield':
            shutil.copytree(p, dest/p.name)
        elif p.is_file() and (p.suffix in ('.psf', '.pdb', '.so', '.params') or p.name == 'manifest.json'):
            shutil.copy2(p, dest/p.name)
    for ext in ('coor', 'vel', 'xsc'):
        shutil.copy2(source/'output'/f'equilibrate.{ext}', dest/'output'/f'seed.{ext}')
    return dest

def run(p, name, source, steps, dt=1., changes=(), tail=None):
    m = json.loads((p/'manifest.json').read_text())
    text = config(m, steps=steps, timestep_fs=dt, prefix=name, restart=source,
                  first_step=checkpoint_step(p, source), thermostat=False)
    # Explicit historical-default control even after the production generator fix.
    text = text.replace('COMmotion yes\n', '')
    text = text.replace('outputEnergies 100', 'outputEnergies 1')
    for a, b in changes:
        assert a in text, a
        text = text.replace(a, b)
    if tail:
        text = text.rsplit('run ', 1)[0]+tail+'\n'
    conf = p/f'{name}.conf'
    if conf.exists():
        assert conf.read_text() == text
        assert 'End of program' in (p/f'{name}.log').read_text()
        checkpoint_step(p, name)
        return
    conf.write_text(text)
    start = time.monotonic()
    with (p/f'{name}.log').open('x') as log:
        proc = subprocess.run([str(BINARY), '+p2', '+devices', '0', conf.name], cwd=p,
                              stdout=log, stderr=subprocess.STDOUT, timeout=180)
    log = (p/f'{name}.log').read_text()
    record = dict(returncode=proc.returncode, seconds=time.monotonic()-start,
                  config_sha256=sha(conf), engine_sha256=sha(BINARY))
    (p/f'{name}.execution.json').write_text(json.dumps(record, indent=2))
    if proc.returncode or 'End of program' not in log:
        raise RuntimeError(str(p/f'{name}.log'))
    checkpoint_step(p, name)

def compare(p, a, b):
    atoms = parse_psf_atoms((p/'system.psf').read_text())
    result = {}
    for ext in ('coor', 'vel'):
        d = read_binary(p/'output'/f'{a}.{ext}')-read_binary(p/'output'/f'{b}.{ext}')
        result[ext] = {'max': float(abs(d).max()), 'rms': float(np.sqrt(np.mean(d*d)))}
        for kind in sorted({x.atomtype for x in atoms}):
            v = d[np.array([x.atomtype == kind for x in atoms])]
            result[ext][kind] = float(abs(v).max())
    return result

def main():
    summary = {}
    for geometry, folder in [('particle', 'particle'), ('slab', 'slab_loading_1_18')]:
        source = REPO/'workspace/gold_validation_20260914'/folder
        variants = [('rigid', ()), ('flexible', (('rigidBonds water', 'rigidBonds none'),))]
        if geometry == 'particle':
            variants += [('offload', (('GPUresident on', 'GPUresident off'),)),
                         ('unrestrained', (('constraints on', 'constraints off'),))]
        for variant, changes in variants:
            p = prepare(geometry+'_'+variant, source)
            for dt in (1., .5):
                tag = str(dt).replace('.', '_')
                for name, src, steps in [('full', 'seed', 40), ('part', 'seed', 20),
                                         ('split', tag+'_part', 20), ('zero', tag+'_part', 0)]:
                    run(p, tag+'_'+name, src, steps, dt, changes)
                row = dict(split=compare(p, tag+'_full', tag+'_split'),
                           startup=compare(p, tag+'_part', tag+'_zero'))
                summary[p.name+'_'+tag] = row
                (ROOT/'mechanism.json').write_text(json.dumps(summary, indent=2))
                print(p.name, dt, row, flush=True)

if __name__ == '__main__':
    main()
