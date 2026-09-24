"""Build isolated 1N4E dimer/duplex comparison fixtures and native load probes."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import BASE, FF, source, write


def main(root, policies=('first', 'last')):
    root = root.resolve()
    source_pdb = root / '1N4E.pdb'
    lines = source_pdb.read_text().splitlines()
    # Deposited LINK records explicitly identify B15/B16 C5-C5 and C6-C6.
    links = [l for l in lines if l.startswith('LINK') and l[21] == 'B']
    assert len(links) == 2
    assert {l[12:16].strip() for l in links} == {'C5', 'C6'}
    assert all(l[22:26].strip() == '15' and l[52:56].strip() == '16' for l in links)
    report = []
    for kind in ['dimer', 'duplex', 'undamaged_control']:
        out = root / kind
        out.mkdir(exist_ok=True)
        chains = ['B'] if kind == 'dimer' else ['A', 'B']
        tcl = ['package require psfgen', 'resetpsf',
               f'topology {BASE / "top_all36_na.rtf"}',
               f'topology {root / "comparator.rtf"}']
        reference_heavy = {}
        for chain in chains:
            records, residues = [], {}
            for line in lines:
                if not line.startswith('ATOM  ') or line[21] != chain:
                    continue
                resid = int(line[22:26])
                if kind == 'dimer' and resid not in [15, 16]:
                    continue
                name = line[12:16].strip().replace('*', "'")
                name = {'OP1': 'O1P', 'OP2': 'O2P', 'C7': 'C5M'}.get(name, name)
                resname = {'DA': 'ADE', 'DT': 'THY', 'DC': 'CYT', 'DG': 'GUA'}[line[17:20].strip()]
                records.append(line[:12] + f'{name:>4}' + line[16:17] + resname + line[20:])
                residues[resid] = resname
                reference_heavy[f'{chain}:{resid}:{name}'] = [float(line[i:i+8]) for i in (30, 38, 46)]
            pdb = out / f'{chain}.pdb'
            pdb.write_text('\n'.join(records) + '\nEND\n')
            tcl += [f'segment {chain} {{', 'first 5TER', 'last 3TER',
                    'auto angles dihedrals', f'pdb {pdb}', '}']
            for i, resid in enumerate(sorted(residues)):
                tcl.append(f'patch {"DEO5" if i == 0 else "DEOX"} {chain}:{resid}')
            tcl.append(f'coordpdb {pdb} {chain}')
        if kind != 'undamaged_control':
            tcl.append('patch MVSY B:15 B:16')
        tcl += ['regenerate angles dihedrals', 'guesscoord',
                f'writepsf {out / "system.psf"}', f'writepdb {out / "system.pdb"}', 'exit']
        (out / 'build.tcl').write_text('\n'.join(tcl) + '\n')
        proc = subprocess.run(['psfgen', str(out / 'build.tcl')], capture_output=True, text=True)
        (out / 'build.log').write_text(proc.stdout + proc.stderr)
        proc.check_returncode()
        # Check that every surviving deposited heavy atom kept its coordinates.
        import numpy as np
        from openmm import app, unit
        psf = app.CharmmPsfFile(str(out / 'system.psf'))
        built = (out / 'system.pdb').read_text().splitlines()
        errors = []
        for line in built:
            if not line.startswith('ATOM'):
                continue
            key = f'{line[72:76].strip()}:{int(line[22:26])}:{line[12:16].strip()}'
            if key in reference_heavy:
                xyz = np.array([float(line[i:i+8]) for i in (30, 38, 46)])
                errors.append(float(np.linalg.norm(xyz - reference_heavy[key])))
        assert errors and max(errors) < 1e-8
        atom_masses = {a.idx + 1: a.mass.value_in_unit(unit.dalton) for a in psf.atom_list}
        fixed = []
        for line in built:
            if line.startswith('ATOM'):
                value = 1.0 if atom_masses[int(line[6:11])] > 2 else 0.0
                line = line[:60] + f'{value:6.2f}' + line[66:]
            fixed.append(line)
        (out / 'fixed_heavy.pdb').write_text('\n'.join(fixed) + '\n')
        for policy in (['first'] if kind == 'undamaged_control' else policies):
            prm = '' if kind == 'undamaged_control' else f'parameters {root}/comparator_{policy}.prm\n'
            config = f'''structure {out}/system.psf
coordinates {out}/system.pdb
paraTypeCharmm on
parameters {BASE}/par_all36_na.prm
parameters {FF}/par_all36_cgenff.prm
{prm}exclude scaled1-4
oneFourScaling 1.0
cutoff 100
switching off
pairlistdist 102
margin 2
stepspercycle 1
outputEnergies 1
outputName {out}/native_{policy}
temperature 0
rigidBonds none
timestep 1
run 0
'''
            conf = out / f'native_{policy}.conf'
            conf.write_text(config)
            p = subprocess.run(['namd3', '+p1', str(conf)], capture_output=True, text=True)
            log = p.stdout + p.stderr
            (out / f'native_{policy}.log').write_text(log)
            energy = [l for l in log.splitlines() if l.startswith('ENERGY:')]
            assert p.returncode == 0 and energy and 'FATAL ERROR' not in log
            relax = config.replace(f'outputName {out}/native_{policy}',
                                   f'outputName {out}/hydrogen_{policy}').replace(
                'run 0', f'fixedAtoms on\nfixedAtomsForces on\nfixedAtomsFile {out}/fixed_heavy.pdb\n'
                'fixedAtomsCol B\nminimize 500')
            relax_conf = out / f'hydrogen_{policy}.conf'
            relax_conf.write_text(relax)
            hp = subprocess.run(['namd3', '+p1', str(relax_conf)], capture_output=True, text=True)
            hlog = hp.stdout + hp.stderr
            (out / f'hydrogen_{policy}.log').write_text(hlog)
            he = [l for l in hlog.splitlines() if l.startswith('ENERGY:')]
            assert hp.returncode == 0 and he and 'FATAL ERROR' not in hlog
            assert int(he[-1].split()[1]) == 500
            report.append({'fixture': kind, 'policy': policy,
                           'particles': len(psf.atom_list),
                           'net_charge_e': sum(a.charge for a in psf.atom_list),
                           'preserved_reference_heavy_atoms': len(errors),
                           'max_reference_displacement_A': max(errors),
                           'native_energy_record': energy[-1], 'native_load': 'passed',
                           'hydrogen_relaxation_steps': 500,
                           'hydrogen_relaxation_final_energy_record': he[-1]})
    write(root / 'reference_build_assessment.json', {
        'simulation_ready': False, 'gate_effect': 'none', 'fixtures': report,
        'source': source(source_pdb), 'code': source(Path(__file__)),
        'scope': 'Deposited heavy-atom coordinates; guessed hydrogens; no solution or dynamics validation.',
        'control': 'Same deposited DNA coordinates with ordinary thymine parameters and no crosslinks; requires independent equilibration.',
    })
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--policies', nargs='+', choices=['first', 'last'], default=['first', 'last'])
    args = p.parse_args()
    main(args.root, args.policies)
