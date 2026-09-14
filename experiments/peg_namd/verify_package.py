"""Portable post-solvation integrity check; run with --seal once after VMD build."""
import hashlib
import json
import math
import sys
from itertools import zip_longest
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def psf_atoms(path):
    with Path(path).open() as stream:
        for line in stream:
            if '!NATOM' in line:
                for _ in range(int(line.split()[0])):
                    yield next(stream).split()
                return
    raise ValueError('No PSF atoms')


def pdb_atoms(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.startswith(('ATOM  ', 'HETATM')):
                yield line


def verify(seal=False):
    package = json.loads(Path('package.json').read_text())
    for item in package['files']:
        if sha(item['path']) != item['sha256']:
            raise ValueError('Staged input modified: ' + item['path'])
    built = ['system.psf', 'system.pdb', 'masks.pdb']
    if seal:
        if Path('built.json').exists():
            raise ValueError('Refusing to overwrite existing built.json')
        if not Path('build.complete').is_file():
            raise ValueError('VMD build did not complete')
        count = anchors = fixed = 0
        charge = 0.0
        for atom, pdb, mask in zip_longest(psf_atoms('system.psf'), pdb_atoms('system.pdb'), pdb_atoms('masks.pdb')):
            if atom is None or pdb is None or mask is None:
                raise ValueError('PSF/PDB/mask atom counts differ')
            count += 1
            for line in (pdb, mask):
                identity = (line[72:76].strip(), line[22:26].strip(), line[17:21].strip(), line[12:16].strip())
                if tuple(atom[1:5]) != identity:
                    raise ValueError(f'PSF/PDB/mask ordering mismatch at {count}')
                if not all(math.isfinite(float(line[a:a+8])) for a in (30, 38, 46)):
                    raise ValueError('Nonfinite coordinates')
            charge += float(atom[6])
            anchors += float(mask[60:66]) > 0
            fixed += float(mask[54:60]) > 0
        if count == 0 or fixed == 0 or anchors != package['case']['chains'] or abs(charge) > 1e-3:
            raise ValueError('Atom/anchor/gold/neutrality check failed')
        data = dict(status='file_integrity_verified_not_physics_validated', atoms=count,
                    anchors=anchors, fixed_atoms=fixed, charge_e=charge,
                    files=[dict(path=p, sha256=sha(p)) for p in built])
        Path('built.json').write_text(json.dumps(data, indent=2) + '\n')
    else:
        data = json.loads(Path('built.json').read_text())
        for item in data['files']:
            if sha(item['path']) != item['sha256']:
                raise ValueError('Built input modified: ' + item['path'])
    print(json.dumps({k: data[k] for k in ('status', 'atoms', 'anchors', 'fixed_atoms', 'charge_e')}))


if __name__ == '__main__':
    verify('--seal' in sys.argv[1:])
