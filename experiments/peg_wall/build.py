"""Build an isolated methyl-capped PEG/TIP3P slit; never start NAMD.

Usage: python -m experiments.peg_wall.build --assets DIR --output NEW_DIR
Assets are the unmodified files from the official toppar_ether.tgz distribution.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
from scipy.spatial import cKDTree

from backend.core.namd_peg_wall import RepulsiveSlit, harmonic_graft_block
from experiments.peg_namd.structure import read_pair

ASSET_HASHES = {
    'top_all35_ethers.rtf': 'cce86e705c2cf9e0339f7123b4470b48525d7539393b4778f8641b412c4b6761',
    'par_all35_ethers.prm': 'f5da0b0b1c24160ae5a6a38003132956ec27b1438f664b5feffc078b6f4b701d',
}
SOURCE_URL = 'https://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files%2Ftoppar_ether.tgz'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def chain_script(repeat_units, grid, slit, graft_offset_nm):
    """Published PEGM + HYD1/HYD2 gives CH3-O-(CH2-CH2-O)n-CH3.

    There are n+1 PEGM residues/ether oxygens for n EO repeat units. Heavy atoms
    seed an all-trans zigzag; psfgen supplies hydrogens. This is new PEG geometry,
    isolated from every production DNA geometry builder.
    """
    if type(repeat_units) is not int or not 1 <= repeat_units <= 100:
        raise ValueError('repeat_units must be an integer from 1 to 100')
    if type(grid) is not int or not 1 <= grid <= 8:
        raise ValueError('grid must be an integer from 1 to 8')
    if slit.axis != 2:
        raise ValueError('qualification builder currently supports a Z-normal slit only')
    if not math.isfinite(graft_offset_nm) or graft_offset_nm < .15:
        raise ValueError('graft offset must be at least 0.15 nm to clear terminal hydrogens')
    lx, ly, lz = np.array(slit.box_nm)*10
    n = repeat_units + 1
    lines = ['package require psfgen', 'resetpsf', 'topology top_all35_ethers.rtf']
    for i in range(grid*grid):
        seg = f'P{i:03d}'
        lines += [f'segment {seg} {{', 'first HYD1', 'last HYD2']
        lines += [f'residue {r} PEGM' for r in range(1, n+1)] + ['}']
        xyz = np.array([(i % grid + .5)*lx/grid, (i//grid + .5)*ly/grid,
                        10*(slit.inset_nm+graft_offset_nm)])
        for j in range(3*n):
            if j:
                length = 1.53 if j % 3 == 0 else 1.415
                xyz += [(-1)**j*length*math.sin(math.radians(34)), 0,
                        length*math.cos(math.radians(34))]
            if xyz[2] > lz - 10*slit.inset_nm - 1.5:
                raise ValueError('extended chain does not fit the slit; enlarge the cell')
            lines.append(f'coord {seg} {j//3+1} {("C1", "O1", "C2")[j%3]} {{{xyz[0]:.6f} {xyz[1]:.6f} {xyz[2]:.6f}}}')
    lines += ['regenerate angles dihedrals', 'guesscoord', 'writepsf dry.psf', 'writepdb dry.pdb']
    return '\n'.join(lines) + '\n'


def solvent_script(slit):
    lx, ly, lz = np.array(slit.box_nm)*10
    lo, hi = 10*slit.inset_nm, lz-10*slit.inset_nm
    return f'''package require solvate
solvate dry.psf dry.pdb -minmax {{{{0 0 {lo}}} {{{lx} {ly} {hi}}}}} -b 2.4 -o water
mol new water.psf waitfor all
mol addfile water.pdb waitfor all
# Remove entire waters if ANY atom lies outside the intended primary slit/cell.
set keep [atomselect top "not (same residue as (water and (x < 0 or x >= {lx} or y < 0 or y >= {ly} or z < {lo} or z > {hi})))"]
$keep writepsf system.psf
$keep writepdb system.pdb
'''


def vmd(script, output, label):
    path = output / f'{label}.tcl'
    path.write_text('if {[catch {\n' + script + '\n} message]} {puts stderr $message; exit 1}\nquit\n')
    with (output/f'{label}.log').open('w') as log:
        subprocess.run([shutil.which('vmd') or 'vmd', '-dispdev', 'text', '-e', path.name],
                       cwd=output, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)


def repair_water_seams(output, slit):
    """Remove whole waters with severe minimum-image O/O contacts; preserve PEG."""
    pair = read_pair(output/'system.psf', output/'system.pdb')
    oxygen = [i for i, a in enumerate(pair['atoms']) if a[3] == 'TIP3' and a[4] == 'OH2']
    xyz = np.mod(pair['xyz'][oxygen], np.array(slit.box_nm)*10)
    contacts = sorted(cKDTree(xyz, boxsize=np.array(slit.box_nm)*10).query_pairs(2.2))
    removed = set()
    for i, j in contacts:
        if i not in removed and j not in removed:
            removed.add(j)
    if removed:
        indices = ' '.join(str(oxygen[i]) for i in sorted(removed))
        vmd(f'''mol new system.psf waitfor all
mol addfile system.pdb waitfor all
set keep [atomselect top "not (same residue as index {indices})"]
$keep writepsf repaired.psf
$keep writepdb repaired.pdb
''', output, 'repair_water')
        (output/'repaired.psf').replace(output/'system.psf')
        (output/'repaired.pdb').replace(output/'system.pdb')
    return len(removed)


def audit_system(pair, repeat_units, chains, slit):
    atoms, xyz = pair['atoms'], pair['xyz']
    peg = [i for i, a in enumerate(atoms) if a[1].startswith('P')]
    anchors = [i for i in peg if atoms[i][2] == '1' and atoms[i][4] == 'C1']
    if len(anchors) != chains or len(peg) != chains*(7*(repeat_units+1)+2):
        raise ValueError('incorrect PEG atom/anchor count')
    charge = sum(float(a[6]) for a in atoms)
    if abs(charge) > 1e-5:
        raise ValueError('system must be neutral with the published methyl caps')
    if slit.energy_forces(xyz)[0] > 1e-6:
        raise ValueError('initial atoms penetrate the slit')
    # Bonds must remain molecularly local, including hydrogens guessed by psfgen.
    lines = pair['lines']
    start = next(i for i, line in enumerate(lines) if '!NBOND' in line)
    count = int(lines[start].split()[0])
    indices = []
    for line in lines[start+1:]:
        if len(indices) >= 2*count:
            break
        indices.extend(map(int, line.split()))
    bonds = np.array(indices[:2*count]).reshape(-1, 2)-1
    distances = np.linalg.norm(xyz[bonds[:, 0]]-xyz[bonds[:, 1]], axis=1)
    if len(distances) == 0 or distances.min() < .65 or distances.max() > 1.8:
        raise ValueError('invalid initial bond lengths')
    heavy = [i for i, a in enumerate(atoms) if float(a[7]) > 2]
    bonded = {tuple(sorted(b)) for b in bonds}
    close = cKDTree(np.mod(xyz[heavy], np.array(slit.box_nm)*10),
                   boxsize=np.array(slit.box_nm)*10).query_pairs(1.8)
    if any(tuple(sorted((heavy[i], heavy[j]))) not in bonded for i, j in close):
        raise ValueError('severe nonbonded heavy-atom clash under periodic boundaries')
    return dict(atoms=len(atoms), peg_atoms=len(peg), chains=chains,
                waters=sum(a[3] == 'TIP3' and a[4] == 'OH2' for a in atoms),
                charge_e=charge, anchor_indices_0=anchors, peg_indices_0=peg,
                bond_range_A=[float(distances.min()), float(distances.max())])


def configurations(slit, graft_k, temperature_K, steps, seed):
    lx, ly, lz = np.array(slit.box_nm)*10
    common = f'''structure system.psf
coordinates system.pdb
paraTypeCharmm on
parameters par_all35_ethers.prm
cellBasisVector1 {lx} 0 0
cellBasisVector2 0 {ly} 0
cellBasisVector3 0 0 {lz}
cellOrigin {lx/2} {ly/2} {lz/2}
PME on
PMEGridSpacing 1.0
exclude scaled1-4
oneFourScaling 1
switching on
switchdist 10
cutoff 12
pairlistdist 14
rigidBonds all
timestep 1.0
nonbondedFreq 1
fullElectFrequency 1
stepspercycle 10
langevin on
langevinTemp {temperature_K}
langevinDamping 1
langevinHydrogen off
langevinPiston off
seed {seed}
wrapAll off
wrapWater on
{harmonic_graft_block(graft_k)}tclForces on
tclForcesScript wall.tcl
outputEnergies 10
outputTiming 100
DCDfreq 100
restartfreq 100
binaryrestart yes
'''
    return {
        'minimize': common + f'''GPUresident off
outputName output/minimize
temperature {temperature_K}
minimize 1000
''',
        'resident': common + f'''# Short qualification/relaxation only; not a production protocol.
GPUresident on
outputName output/resident
binCoordinates output/minimize.coor
temperature {temperature_K}
run {steps}
''',
    }


def build(assets, output, repeat_units=8, grid=2, box_nm=(4.8, 4.8, 4.8),
          wall_k=10., graft_k=5., graft_offset_nm=.2, temperature_K=294., steps=1000, seed=17):
    assets, output = Path(assets), Path(output).resolve()
    slit = RepulsiveSlit(tuple(box_nm), k_kcal_mol_A2=wall_k)
    if min(box_nm) < 3.2 or not 1 <= temperature_K <= 500:
        raise ValueError('cell must be >=3.2 nm and temperature in [1, 500] K')
    if type(steps) is not int or not 200 <= steps <= 100000 or steps % 100:
        raise ValueError('qualification steps must be 200..100000 and divisible by 100')
    if type(seed) is not int or not 1 <= seed <= 2147483647:
        raise ValueError('seed must be a positive signed 32-bit integer')
    script = chain_script(repeat_units, grid, slit, graft_offset_nm)
    configs = configurations(slit, graft_k, temperature_K, steps, seed)
    for name, digest in ASSET_HASHES.items():
        if sha256(assets/name) != digest:
            raise ValueError(f'{name}: expected the pinned official ether release')
    output.mkdir(parents=True, exist_ok=False)
    for name in ASSET_HASHES:
        shutil.copyfile(assets/name, output/name)
    vmd(script, output, 'build_chains')
    vmd(solvent_script(slit), output, 'solvate')
    removed = repair_water_seams(output, slit)
    pair = read_pair(output/'system.psf', output/'system.pdb')
    audit = audit_system(pair, repeat_units, grid*grid, slit)
    anchors = set(audit['anchor_indices_0'])
    mask = [line[:54] + f'{0.:6.2f}{float(i in anchors):6.2f}' + line[66:]
            for i, line in enumerate(pair['records'])]
    (output/'grafts.pdb').write_text('\n'.join(mask)+'\nEND\n')
    (output/'wall.tcl').write_text(slit.tcl_forces(range(1, audit['atoms']+1)))
    (output/'output').mkdir()
    for stage, config in configs.items():
        (output/f'{stage}.conf').write_text(config)
    manifest = dict(schema='nadoc.peg_wall_qualification.v1', status='prepared_not_run',
                    chemistry='CH3-O-(CH2-CH2-O)n-CH3', repeat_units=repeat_units,
                    peg_monomer_residues_per_chain=repeat_units+1, source_url=SOURCE_URL,
                    asset_hashes=ASSET_HASHES, slit=asdict(slit),
                    graft_k_kcal_mol_A2=graft_k, graft_offset_nm=graft_offset_nm,
                    temperature_K=temperature_K, timestep_fs=1., steps=steps, seed=seed,
                    removed_seam_waters=removed, audit=audit)
    manifest['input_hashes'] = {name: sha256(output/name) for name in
                              ['system.psf', 'system.pdb', 'grafts.pdb', 'wall.tcl',
                               'minimize.conf', 'resident.conf', *ASSET_HASHES]}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat-units', type=int, default=8)
    parser.add_argument('--grid', type=int, default=2)
    parser.add_argument('--box-nm', type=float, nargs=3, default=[4.8]*3)
    parser.add_argument('--wall-k', type=float, default=10.)
    parser.add_argument('--graft-k', type=float, default=5.)
    parser.add_argument('--graft-offset-nm', type=float, default=.2)
    parser.add_argument('--temperature-K', dest='temperature_K', type=float, default=294.)
    parser.add_argument('--steps', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=17)
    result = build(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in result['audit'].items() if not k.endswith('_0')}, indent=2))


if __name__ == '__main__':
    main()
