"""Source-faithful SI transcription and isolated full-nucleotide coverage probe.

No published-model identity or simulation readiness is asserted. Duplicate torsion
policies are explicit hypotheses; the source does not resolve their interpretation.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import warnings


REPO = Path(__file__).resolve().parents[2]
ARCHIVE = Path('/media/jojo/Archive/NADOC_archive/photoproduct_evidence')
OLD = ARCHIVE / 'alpine-qm-primary-syn-anti-fit-v1/local-run-v1'
FF = OLD / 'bundle/inputs/forcefield'
BASE = REPO / 'backend/data/forcefield'
SMOKE = OLD / 'gate-troubleshooting-v1/namd-integration-v2/engine_smoke'
PDF_SHA = 'f3ae73efc282af07671139946d2dbf58de2172aad8d68085edf300af79681e74'
# Figure S1, visually transcribed. Both residues have the same assignment.
ATOMS = {
    'N1': ('NG2S0', -.361), 'C2': ('CG2O6', .536),
    'O2': ('OG2D1', -.490), 'N3': ('NG2S1', -.233),
    'H3': ('HGP1', .345), 'C4': ('CG2O1', .509),
    'O4': ('OG2D1', -.503), 'C5': ('CG3RC1', .013),
    'C6': ('CG3RC1', .096), 'H6': ('HGA1', .090),
    'C5M': ('CG331', -.272), 'H51': ('HGA3', .090),
    'H52': ('HGA3', .090), 'H53': ('HGA3', .090),
}


def source(path):
    return {'path': str(path.resolve()),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def extract(text):
    rows = []
    section = None
    widths = {'BONDS': 2, 'ANGLES': 3, 'DIHEDRALS': 4, 'IMPROPERS': 4}
    for page, content in enumerate(text.split('\f'), 1):
        if page > 8:
            break
        for line in content.splitlines():
            for number, name in enumerate(widths, 1):
                if line.startswith(f'Table S{number}.'):
                    section = name
            fields = line.split()
            if not section or not fields or not re.match(r'^!?[A-Z][A-Z0-9]+$', fields[0]):
                continue
            n = widths[section]
            if len(fields) != n + (3 if section == 'DIHEDRALS' else 2):
                continue
            try:
                values = list(map(float, fields[n:]))
            except ValueError:
                continue
            rows.append({'section': section, 'types': [f.lstrip('!') for f in fields[:n]],
                         'values': values, 'commented': fields[0].startswith('!'),
                         'page': page, 'source_line': line.strip()})
    return rows


def key(row):
    types = tuple(row['types'])
    return (row['section'], min(types, types[::-1]),
            row['values'][1] if row['section'] == 'DIHEDRALS' else None)


def main(root):
    import openmm as mm
    from openmm import app

    root = root.resolve()
    pdf = root / 'ci7b00215_si_001.pdf'
    assert source(pdf)['sha256'] == PDF_SHA
    rows = extract((root / 'ci7b00215_si_001.txt').read_text())
    assert {s: sum(r['section'] == s for r in rows) for s in
            ['BONDS', 'ANGLES', 'IMPROPERS']} == {'BONDS': 15, 'ANGLES': 25, 'IMPROPERS': 3}
    assert abs(sum(v[1] for v in ATOMS.values())) < 1e-12
    grouped = defaultdict(list)
    for row in rows:
        if not row['commented']:
            grouped[key(row)].append(row)
    conflicts = [v for v in grouped.values() if len({tuple(r['values']) for r in v}) > 1]
    write(root / 'source_transcription.json', {
        'source': source(pdf), 'figure_s1_atoms': ATOMS, 'rows': rows,
        'conflicting_same_type_multiplicity_groups': conflicts,
        'commented_rows': [r for r in rows if r['commented']],
        'simulation_ready': False,
    })
    wanted = {v[0] for v in ATOMS.values()}
    masses = [line for line in (FF / 'par_all36_cgenff.prm').read_text().splitlines()
              if line.startswith('MASS') and line.split()[2] in wanted]
    assert len(masses) == len(wanted)
    rtf = ['* Isolated Ma/van der Vaart Figure S1 comparator; not a release\n*\n36 1',
           *masses, 'PRES MVSY 0.0']
    for res in (1, 2):
        for name, (typ, charge) in ATOMS.items():
            rtf.append(f'ATOM {res}{name} {typ} {charge:.6f}')
    rtf += ['BOND 1C5 2C5 1C6 2C6', 'END']
    (root / 'comparator.rtf').write_text('\n'.join(rtf) + '\n')
    # Fresh topology from unmodified nucleotide, never reuse historical anti graph.
    shutil.copyfile(SMOKE / 'reactant.pdb', root / 'precursor.pdb')
    tcl = f'''package require psfgen
resetpsf
topology {BASE / 'top_all36_na.rtf'}
topology {root / 'comparator.rtf'}
segment D000 {{
 first 5TER
 last 3TER
 auto angles dihedrals
 pdb {root / 'precursor.pdb'}
}}
patch DEO5 D000:1
patch DEOX D000:2
coordpdb {root / 'precursor.pdb'} D000
patch MVSY D000:1 D000:2
regenerate angles dihedrals
guesscoord
writepsf {root / 'comparator.psf'}
writepdb {root / 'unrelaxed_topology_probe.pdb'}
exit
'''
    (root / 'build.tcl').write_text(tcl)
    result = subprocess.run(['psfgen', str(root / 'build.tcl')], capture_output=True, text=True)
    (root / 'psfgen.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    psf = app.CharmmPsfFile(str(root / 'comparator.psf'))
    assert len(psf.atom_list) == 63
    assert abs(sum(a.charge for a in psf.atom_list) + 1) < 1e-8
    cross = []
    for b in psf.bond_list:
        a, c = b.atom1, b.atom2
        if a.residue.idx != c.residue.idx:
            cross.append(sorted([a.name, c.name]))
    assert sorted(cross) == sorted([['C5', 'C5'], ['C6', 'C6'], ["O3'", 'P']])
    results = []
    for policy in ['first', 'last']:
        selected = [v[0 if policy == 'first' else -1] for v in grouped.values()]
        prm = ['* Explicit duplicate resolution hypothesis: ' + policy, '*', '']
        for section in ['BONDS', 'ANGLES', 'DIHEDRALS', 'IMPROPERS']:
            prm.append(section)
            for r in selected:
                if r['section'] != section:
                    continue
                values = r['values']
                if section == 'IMPROPERS':
                    values = [values[0], 0, values[1]]
                prm.append(' '.join(r['types']) + ' ' + ' '.join(f'{v:g}' for v in values))
        prm.append('END')
        path = root / f'comparator_{policy}.prm'
        path.write_text('\n'.join(prm) + '\n')
        params = app.CharmmParameterSet(str(BASE / 'top_all36_na.rtf'),
                                     str(BASE / 'par_all36_na.prm'),
                                     str(FF / 'par_all36_cgenff.prm'))
        # Loading an override replaces matching multiplicities, but retains other
        # parent Fourier terms. Record this explicitly; do not call the result
        # an exact reproduction of the authors' unprovided parameter stream.
        parent_extras = []
        published_dihedrals = defaultdict(set)
        for r in selected:
            if r['section'] == 'DIHEDRALS':
                published_dihedrals[min(tuple(r['types']), tuple(r['types'][::-1]))].add(int(r['values'][1]))
        for types, multiplicities in published_dihedrals.items():
            for term in params.dihedral_types.get(types, []):
                if term.per not in multiplicities:
                    parent_extras.append({'types': types, 'multiplicity': term.per,
                                          'k': term.phi_k, 'phase': term.phase})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            params.readParameterFile(str(path))
        write(root / f'parameter_overlay_{policy}.json', {
            'parent_fourier_terms_retained': parent_extras,
            'replacement_warnings': [str(w.message) for w in caught],
        })
        try:
            system = psf.createSystem(params, nonbondedMethod=app.NoCutoff,
                                      constraints=None, rigidWater=False)
            (root / f'comparator_{policy}.xml').write_text(mm.XmlSerializer.serialize(system))
            results.append({'policy': policy, 'parameter_load': 'passed',
                            'particles': system.getNumParticles()})
        except Exception as exc:
            results.append({'policy': policy, 'parameter_load': 'failed', 'error': str(exc)})
    write(root / 'coverage_assessment.json', {
        'simulation_ready': False, 'gate_effect': 'none', 'nuclear_atoms': 63,
        'net_charge_e': sum(a.charge for a in psf.atom_list), 'cross_residue_bonds': cross,
        'duplicate_policy_hypotheses': results, 'conflicting_groups': len(conflicts),
        'coordinates': 'Unrelaxed precursor: topology probe only, not a cis-syn template',
        'sources': [source(p) for p in [pdf, Path(__file__), BASE / 'top_all36_na.rtf',
                                      BASE / 'par_all36_na.prm', FF / 'par_all36_cgenff.prm']],
    })
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    main(parser.parse_args().root)
