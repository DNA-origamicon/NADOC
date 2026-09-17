"""Build an isolated, provenance-tracked BTE/BTE5 CHARMM junction candidate.

No application geometry or simulation readiness is changed. This is a modular
parameter transfer, not a fitted or experimentally validated force field.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import tempfile
import warnings

import parmed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.core.namd_topology import find_psfgen
from experiments.strep_biotin_namd.prepare_parameterization import digest, dump


def parameter_set(*files):
    with warnings.catch_warnings():
        warnings.simplefilter('once')
        return parmed.charmm.CharmmParameterSet(*(str(f) for f in files))


def topology(package):
    source = package / 'BTMP.str'
    audit = json.loads((package / 'assignment_audit.json').read_text())
    if digest(source) != audit['sha256'] or not audit['parameters_resolved']:
        raise ValueError('Source assignment differs from the audited stream')
    ff = package / 'reference_forcefield'
    for row in json.loads((package / 'reference_forcefield.json').read_text()):
        if digest(package / row['file']) != row['sha256']:
            raise ValueError('Reference file changed')
    params = parameter_set(ff / 'top_all36_cgenff.rtf', ff / 'par_all36_cgenff.prm', source)
    residue = params.residues['BTMP']
    by_name = {a.name: a for a in residue.atoms}
    identity = json.loads((package / 'atom_mapping.json').read_text())
    ligand = {a['name'] for a in identity if a['role'] == 'ligand'}
    methyl_h = [a.name for a in by_name['C5C'].bond_partners if a.name.startswith('H')]
    if len(methyl_h) != 3 or len({by_name[h].charge for h in methyl_h}) != 1:
        raise ValueError('Expected three equivalent cap hydrogens')
    # Remove one equivalent cap H and fold its charge into the parent carbon.
    # The remaining two H become the native DNA H5'/H5''; DNA C4' replaces the
    # removed cap bond. No charge spreading over biotin or arbitrary rounding.
    c5_charge = by_name['C5C'].charge + by_name[methyl_h[-1]].charge
    mapping = {'P': ('P2', 'P'), 'O1P': ('ON3', 'OP1'), 'O2P': ('ON3', 'OP2'),
               "O5'": ('ON2', 'O5C')}
    updates = {n: dict(atom_type=t, charge=by_name[s].charge, source_atom=s)
               for n, (t, s) in mapping.items()}
    updates["C5'"] = dict(atom_type='CN8B', charge=c5_charge,
                           source_atom='C5C + one equivalent cap H')
    for name, h in zip(["H5'", "H5''"], methyl_h[:2]):
        updates[name] = dict(atom_type='HN8', charge=by_name[h].charge, source_atom=h)
    charge = sum(by_name[n].charge for n in ligand)
    lines = ['* Biotin-TEG candidate: supplied CGenFF 5.0 plus modular DNA boundary',
             '* Research only; not physically qualified', '*', '36 1',
             f'RESI BTE {charge:.6f}', 'GROUP']
    lines += [f'ATOM {a.name:<4} {a.type:<8} {a.charge:.6f}' for a in residue.atoms if a.name in ligand]
    for bond in residue.bonds:
        if {bond.atom1.name, bond.atom2.name} <= ligand:
            lines.append(f'BOND {bond.atom1.name} {bond.atom2.name}')
    # Keep the stream's explicit improper ordering rather than reconstruct it.
    for line in source.read_text().splitlines():
        fields = line.split('!')[0].split()
        if fields[:1] == ['IMPR']:
            if not set(fields[1:]) <= ligand:
                raise ValueError('Unexpected cap-dependent improper')
            lines.append(' '.join(fields))
    patch_charge = sum(a['charge'] for a in updates.values())
    lines += [f'PRES BTE5 {patch_charge:.6f}', 'GROUP']
    lines += [f'ATOM 2{name} {a["atom_type"]} {a["charge"]:.6f}' for name, a in updates.items()]
    lines += ['BOND 1O4T 2P', 'END', '']
    return '\n'.join(lines), updates, params, ligand


def psfgen(script, work, label):
    path = work / f'{label}.tcl'
    path.write_text(script)
    proc = subprocess.run([find_psfgen(), str(path)], capture_output=True, text=True, timeout=45)
    (work / f'{label}.log').write_text(proc.stdout + '\n' + proc.stderr)
    proc.check_returncode()
    return parmed.charmm.CharmmPsfFile(str(work / f'{label}.psf'))


def control_script(ff, rtf, output, bases, grafted=True):
    first = 'NONE' if grafted else '5TER'
    lines = [f'topology {{{ff / "top_all36_na.rtf"}}}',
             f'topology {{{ff / "top_all36_cgenff.rtf"}}}', f'topology {{{rtf}}}',
             f'segment DNA {{\nfirst {first}\nlast 3TER']
    lines += [f'residue {i+1} {base}' for i, base in enumerate(bases)]
    lines.append('}')
    lines += [f'patch {"DEO5" if i == 0 and not grafted else "DEOX"} DNA:{i+1}'
              for i in range(len(bases))]
    if grafted:
        lines += ['segment LIG {\nfirst NONE\nlast NONE\nresidue 1 BTE\n}',
                  'patch BTE5 LIG:1 DNA:1']
    lines += ['regenerate angles dihedrals', f'writepsf {{{output}}}', '']
    return '\n'.join(lines)


def mixed_terms(structure, cgenff, dna):
    """Transfer complete central-bond families, never mix Fourier sources."""
    aliases_na = {'OG303': 'ON2'}
    aliases_cg = {'P2': 'PG1', 'ON3': 'OG2P1', 'ON2': 'OG303'}
    result = {'bonds': {}, 'angles': {}, 'dihedrals': {}}
    ledger = []
    for kind, objects in [('bonds', structure.bonds), ('angles', structure.angles),
                          ('dihedrals', structure.dihedrals)]:
        for obj in objects:
            atoms = [getattr(obj, f'atom{i+1}') for i in range({'bonds': 2, 'angles': 3, 'dihedrals': 4}[kind])]
            if len({a.residue.segid for a in atoms}) != 2:
                continue
            types = tuple(a.type for a in atoms)
            # All phosphate-centered angles and P–O5' torsions remain CHARMM
            # DNA; O4T-centered angles and linker-side torsions use CGenFF.
            use_na = kind == 'bonds' or (kind == 'angles' and atoms[1].name == 'P') or (
                kind == 'dihedrals' and {a.name for a in atoms[1:3]} == {'P', "O5'"})
            family = 'CHARMM_DNA' if use_na else 'CGenFF'
            aliases, source = (aliases_na, dna) if use_na else (aliases_cg, cgenff)
            mapped = tuple(aliases.get(t, t) for t in types)
            table = getattr(source, {'bonds': 'bond_types', 'angles': 'angle_types', 'dihedrals': 'dihedral_types'}[kind])
            keys = [mapped, mapped[::-1]]
            if kind == 'dihedrals':
                keys += [('X', mapped[1], mapped[2], 'X'), ('X', mapped[2], mapped[1], 'X')]
            key = next((key for key in keys if key in table), None)
            if key is None:
                raise ValueError(f'No defensible {family} {kind} analogue: {types} -> {mapped}')
            parameter = table[key]
            canonical = min(types, types[::-1])
            if canonical in result[kind] and result[kind][canonical]['family'] != family:
                raise ValueError('Inconsistent central-bond parameter source')
            ub = source.urey_bradley_types.get(key) if kind == 'angles' else None
            result[kind][canonical] = dict(parameter=parameter, urey_bradley=ub, family=family)
            ledger.append(dict(kind=kind, atoms=[f'{a.residue.segid}:{a.residue.number}:{a.name}' for a in atoms],
                               target_types=types, source_types=key, source_family=family))
    return result, ledger


def parameter_text(terms):
    lines = ['* Explicit mixed BTE/DNA terms with source families in junction_manifest.json', '*']
    for kind, header in [('bonds', 'BONDS'), ('angles', 'ANGLES'), ('dihedrals', 'DIHEDRALS')]:
        lines.append(header)
        for types, row in sorted(terms[kind].items()):
            p = row['parameter']
            prefix = ' '.join(types)
            if kind == 'bonds':
                values = [f'{p.k:.10g} {p.req:.10g}']
            elif kind == 'angles':
                value = f'{p.k:.10g} {p.theteq:.10g}'
                ub = row['urey_bradley']
                if ub is not None and getattr(ub, 'k', 0):
                    value += f' {ub.k:.10g} {ub.req:.10g}'
                values = [value]
            else:
                values = [f'{t.phi_k:.10g} {t.per:d} {t.phase:.10g}' for t in p]
            lines += [f'{prefix} {value} ! {row["family"]}' for value in values]
    return '\n'.join(lines + ['END', ''])


def build(package, output):
    package, output = package.resolve(), output.resolve()
    rtf, updates, cg, ligand = topology(package)
    ff = package / 'reference_forcefield'
    dna = parameter_set(ff / 'par_all36_na.prm')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'biotin_teg.rtf').write_text(rtf)
    with tempfile.TemporaryDirectory(prefix='controls_', dir=output) as temp:
        work = Path(temp)
        seed = psfgen(control_script(ff, output / 'biotin_teg.rtf', work / 'seed.psf', ['ADE']), work, 'seed')
        terms, ledger = mixed_terms(seed, cg, dna)
        (output / 'biotin_teg_boundary.prm').write_text(parameter_text(terms))
        combined = parameter_set(ff / 'top_all36_cgenff.rtf', ff / 'par_all36_cgenff.prm',
                                 ff / 'par_all36_na.prm', package / 'BTMP.str', output / 'biotin_teg_boundary.prm')
        controls = []
        for bases in [['ADE'], ['CYT'], ['GUA'], ['THY'], ['ADE', 'CYT', 'GUA', 'THY']]:
            label = '_'.join(bases)
            s = psfgen(control_script(ff, output / 'biotin_teg.rtf', work / f'{label}.psf', bases), work, label)
            s.load_parameters(combined)
            baseline = psfgen(control_script(ff, output / 'biotin_teg.rtf', work / f'{label}_plain.psf', bases, False), work, label+'_plain')
            baseline.load_parameters(dna)
            q, q0 = sum(a.charge for a in s.atoms), sum(a.charge for a in baseline.atoms)
            if abs(q + len(bases)) > 1e-6 or abs((q-q0) + 1) > 1e-6:
                raise ValueError(f'Invalid junction charge {q} / baseline {q0}')
            atom = {(a.residue.segid, a.residue.number, a.name): a for a in s.atoms}
            if set(a.name for a in s.atoms if a.residue.segid == 'LIG') != ligand:
                raise ValueError('Methyl cap leaked into ligand')
            p = atom[('DNA', 1, 'P')]
            if len(p.bond_partners) != 4 or {a.name for a in p.bond_partners} != {'O4T', 'O1P', 'O2P', "O5'"}:
                raise ValueError('Phosphate connectivity invalid')
            untouched = 0
            for a in baseline.atoms:
                key = ('DNA', a.residue.number, a.name)
                if a.residue.number == 1 and a.name in {*updates, 'H5T'}:
                    continue
                b = atom[key]
                if a.type != b.type or abs(a.charge-b.charge) > 1e-8:
                    raise ValueError(f'Unintended DNA modification {key}')
                untouched += 1
            controls.append(dict(bases=bases, atoms=len(s.atoms), charge=round(q, 6),
                                 unmodified_charge=round(q0, 6), preserved_dna_atoms=untouched,
                                 parameters_resolved=True, phosphate_coordination=4))
        # Retain one actual nucleotide PSF for review; temporary controls auto-clean.
        import shutil
        shutil.copyfile(work / 'ADE.psf', output / 'biotin_dA.psf')
    report = dict(schema='nadoc.biotin-dna-junction.v1', simulation_ready=False,
                  status='candidate_topology_and_parameter_coverage_verified',
                  source_stream_sha256=digest(package / 'BTMP.str'),
                  charge_method='One equivalent methyl-cap H charge folded into C5; unchanged supplied ligand charges; native DNA types retained.',
                  dna_atom_updates=updates, ligand_charge=round(sum(a.charge for a in cg.residues['BTMP'].atoms if a.name in ligand), 6),
                  mixed_terms=ledger, controls=controls,
                  sources=['https://mackerell.umaryland.edu/cgenff_faq.php',
                           'https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/'],
                  remaining=['actual complex coordinate/H completion and mapping',
                             'junction conformational/energetic validation', 'GPU NAMD physical validation'],
                  files={name: digest(output / name) for name in ['biotin_teg.rtf', 'biotin_teg_boundary.prm', 'biotin_dA.psf']})
    dump(output / 'junction_manifest.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=ROOT / 'experiments/strep_biotin_namd/ws/parameterization_final')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.package, args.output), indent=2))
