"""PSF/PDB input checks and rigid placement of existing parameterized PEG chains."""
from __future__ import annotations

import math
from pathlib import Path
import numpy as np


def read_pair(psf, pdb):
    text = Path(psf).read_text()
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if '!NATOM' in line), None)
    if start is None:
        raise ValueError('PSF lacks NATOM')
    count = int(lines[start].split()[0])
    atoms = [line.split() for line in lines[start + 1:start + 1 + count]]
    records = [line for line in Path(pdb).read_text().splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
    if count < 1 or len(records) != count or len(atoms) != count:
        raise ValueError('PSF/PDB atom count mismatch')
    xyz = []
    for i, (atom, line) in enumerate(zip(atoms, records), 1):
        if len(atom) < 8 or int(atom[0]) != i:
            raise ValueError('Malformed or nonsequential PSF atom indices')
        if (atom[1], atom[2], atom[3], atom[4]) != (line[72:76].strip(), line[22:26].strip(), line[17:21].strip(), line[12:16].strip()):
            raise ValueError(f'PSF/PDB identity or ordering mismatch at atom {i}')
        if not math.isfinite(float(atom[6])) or not math.isfinite(float(atom[7])) or float(atom[7]) <= 0:
            raise ValueError('Invalid charge or mass')
        xyz.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    xyz = np.array(xyz)
    if not np.isfinite(xyz).all():
        raise ValueError('Nonfinite coordinates')
    return dict(lines=lines, start=start, atoms=atoms, records=records, xyz=xyz)


def place_chain(pair, anchor_index, end_index, site_nm, angle_deg, box_nm):
    n = len(pair['atoms'])
    if not (isinstance(anchor_index, int) and isinstance(end_index, int) and 1 <= anchor_index <= n and 1 <= end_index <= n):
        raise ValueError('Anchor/end indices must be one-based PSF indices')
    xyz = pair['xyz'] - pair['xyz'][anchor_index - 1]
    axis = xyz[end_index - 1]
    norm = np.linalg.norm(axis)
    if norm < 1e-6:
        raise ValueError('Coincident chain anchor and end')
    z = axis / norm
    helper = np.array([1., 0., 0.]) if abs(z[0]) < .9 else np.array([0., 1., 0.])
    x = np.cross(helper, z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    coords = xyz @ np.array([x, y, z]).T
    theta = math.radians(angle_deg)
    rotation = np.array([[math.cos(theta), -math.sin(theta), 0], [math.sin(theta), math.cos(theta), 0], [0, 0, 1]])
    coords = coords @ rotation.T + np.array(site_nm) * 10
    # Preserve whole molecules laterally. VMD/NAMD may keep bonded chains outside
    # the primary cell; contact audit uses minimum-image lateral distances.
    if coords[:, 2].min() < 0 or coords[:, 2].max() >= box_nm[2] * 10 - 2:
        raise ValueError('Template does not fit the vertical cell: use an equilibrated shorter-height conformer')
    return coords


def write_chain(pair, coords, segid, stem):
    lines = list(pair['lines'])
    for i, atom in enumerate(pair['atoms']):
        fields = list(atom); fields[1] = segid
        lines[pair['start'] + 1 + i] = ' '.join(fields)
    Path(str(stem) + '.psf').write_text('\n'.join(lines) + '\n')
    records = []
    for line, (x, y, z) in zip(pair['records'], coords):
        line = line.ljust(80)
        records.append(line[:30] + f'{x:8.3f}{y:8.3f}{z:8.3f}' + line[54:72] + f'{segid:<4}' + line[76:])
    Path(str(stem) + '.pdb').write_text('\n'.join(records) + '\nEND\n')
