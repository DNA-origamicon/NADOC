"""Apply an isolated junction candidate to the retained gold-free fixture."""
from pathlib import Path
import argparse
import json
import shutil
import sys

import numpy as np
import parmed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.core.models import Design
from backend.core.strep_biotin_namd import write_preparation, resolve_psf_identity
from experiments.strep_biotin_namd.prepare_parameterization import dump, digest
from experiments.strep_biotin_namd.build_dna_junction import psfgen, parameter_set


def complete_ligand_hydrogens(output, package, manifest):
    from rdkit import Chem
    mapping = json.loads((package / 'atom_mapping.json').read_text())
    template = Chem.MolFromMol2File(str(package / 'BTMP.mol2'), removeHs=False)
    if template is None:
        raise ValueError('Cannot read audited ligand model')
    heavy = Chem.RemoveHs(template)
    original_heavy = {a['name']: a for a in mapping if a['element'] != 'H'}
    for link in manifest['covalent_links']:
        lig_seg, lig_res, _ = link['ligand']
        dna_seg, dna_res, _ = link['dna']
        path = output / 'inputs' / f'{lig_seg}.pdb'
        lines = [line for line in path.read_text().splitlines() if line.startswith('ATOM')]
        dna_lines = [line for line in (output / 'inputs' / f'{dna_seg}.pdb').read_text().splitlines()
                     if line.startswith('ATOM') and int(line[22:26]) == dna_res]
        positions = {line[12:16].strip(): [float(line[a:b]) for a, b in [(30, 38), (38, 46), (46, 54)]]
                     for line in lines}
        dna_xyz = {line[12:16].strip(): [float(line[a:b]) for a, b in [(30, 38), (38, 46), (46, 54)]]
                   for line in dna_lines}
        positions.update({name: dna_xyz[alias] for name, alias in
                          [('P', 'P'), ('OP1', 'O1P'), ('OP2', 'O2P'), ('O5C', "O5'"), ('C5C', "C5'")]})
        model = Chem.Mol(heavy)
        conf = model.GetConformer()
        for name, entry in original_heavy.items():
            conf.SetAtomPosition(entry['index_1based']-1, positions[name])
        model = Chem.AddHs(model, addCoords=True)
        for atom, record in zip(model.GetAtoms(), mapping):
            if atom.GetSymbol() != record['element']:
                raise ValueError('Hydrogen completion changed ordering')
            if record['element'] != 'H' or record['role'] != 'ligand':
                continue
            parent = mapping[atom.GetNeighbors()[0].GetIdx()]['name']
            if parent != record['parent']:
                raise ValueError('Hydrogen parent mismatch')
            x, y, z = conf_xyz = np.array(model.GetConformer().GetAtomPosition(atom.GetIdx()))
            bond = np.linalg.norm(conf_xyz - positions[parent])
            if not .8 < bond < 1.3:
                raise ValueError('Invalid completed hydrogen bond length')
            lines.append(f'ATOM  {len(lines)+1:5d} {record["name"]:>4s} BTE L{lig_res:4d}    '
                         f'{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00      {lig_seg:<4} H  ')
        if len(lines) != 60:
            raise ValueError('Expected 28 heavy atoms plus 32 ligand H')
        path.write_text('\n'.join(lines) + '\nEND\n')


def build(source, package, junction, output):
    source, package, junction, output = [p.resolve() for p in (source, package, junction, output)]
    jm = json.loads((junction / 'junction_manifest.json').read_text())
    for name, sha in jm['files'].items():
        if digest(junction / name) != sha:
            raise ValueError('Junction candidate changed after audit')
    if digest(package / 'BTMP.str') != jm['source_stream_sha256']:
        raise ValueError('Source assignment hash mismatch')
    manifest = write_preparation(Design.from_json(source.read_text()), output)
    before = {p.name: p.read_text() for p in (output / 'inputs').glob('*.pdb')}
    ff = package / 'reference_forcefield'
    shutil.copyfile(junction / 'biotin_teg.rtf', output / 'biotin_teg.rtf')
    complete_ligand_hydrogens(output, package, manifest)
    script = (output / 'build_psfgen.tcl').read_text()
    script = script.replace(f'topology {output / "biotin_teg.rtf"}',
                            f'topology {{{ff / "top_all36_cgenff.rtf"}}}\ntopology {{{output / "biotin_teg.rtf"}}}')
    # CTER renames the existing terminal O to OT1. Supply that coordinate
    # explicitly; otherwise guesscoord rebuilds an already resolved heavy atom.
    terminal_coords = []
    for filename, text in before.items():
        if not filename.startswith('P'):
            continue
        records = [line for line in text.splitlines() if line.startswith('ATOM')]
        last = max(int(line[22:26]) for line in records)
        for line in records:
            if int(line[22:26]) == last and line[12:16].strip() in ('O', 'OXT'):
                name = {'O': 'OT1', 'OXT': 'OT2'}[line[12:16].strip()]
                xyz = ' '.join(line[a:b].strip() for a, b in [(30, 38), (38, 46), (46, 54)])
                terminal_coords.append(f'coord {filename[:-4]} {last} {name} {{{xyz}}}')
    script = script.replace('guesscoord', '\n'.join(terminal_coords) + '\nguesscoord')
    structure = psfgen(script, output, 'system')
    params = parameter_set(ff / 'top_all36_cgenff.rtf', ff / 'par_all36_cgenff.prm',
                           ff / 'par_all36m_prot.prm', ff / 'par_all36_na.prm',
                           package / 'BTMP.str', junction / 'biotin_teg_boundary.prm')
    structure.load_parameters(params)
    mapped = resolve_psf_identity((output / 'system.psf').read_text(), manifest['identity'])
    actual = parmed.load_file(str(output / 'system.pdb'))
    coords = {(a.residue.segid, a.residue.number, a.name): a for a in actual.atoms}
    preserved, max_delta = 0, 0.0
    for seg, text in before.items():
        for line in text.splitlines():
            if not line.startswith('ATOM'):
                continue
            name = line[12:16].strip()
            key = (seg[:-4], int(line[22:26]), name)
            if key not in coords:
                alias = {'O': 'OT1', 'OXT': 'OT2'}
                if line[17:20] == 'ILE':
                    alias['CD1'] = 'CD'
                key = (key[0], key[1], alias.get(name, name))
            atom = coords[key]
            xyz = np.array([float(line[a:b]) for a, b in [(30, 38), (38, 46), (46, 54)]])
            delta = np.linalg.norm(xyz - [atom.xx, atom.xy, atom.xz])
            max_delta = max(max_delta, float(delta))
            preserved += 1
    if max_delta > .001:
        raise ValueError('Authored heavy coordinates moved')
    charge = sum(a.charge for a in structure.atoms)
    if abs(charge - round(charge)) > 1e-6:
        raise ValueError('Noninteger full-complex charge')
    report = dict(status='isolated_complex_topology_complete', simulation_ready=False,
                  atoms=len(structure.atoms), charge=round(charge, 6),
                  mapped_heavy_atoms=len(mapped), preserved_heavy_atoms=preserved,
                  maximum_heavy_displacement_angstrom=max_delta,
                  parameters_resolved=True, bonds=len(structure.bonds), angles=len(structure.angles),
                  dihedrals=len(structure.dihedrals), impropers=len(structure.impropers), cmaps=len(structure.cmaps),
                  source_design_sha256=digest(source), junction_manifest_sha256=digest(junction / 'junction_manifest.json'),
                  remaining=['junction conformational/energetic validation', 'GPU NAMD physical validation'])
    dump(output / 'resolved_identity.json', mapped)
    dump(output / 'junction_complex_validation.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--junction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.package, args.junction, args.output), indent=2))
