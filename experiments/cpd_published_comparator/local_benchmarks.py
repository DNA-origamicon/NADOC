"""Frozen local geometry/minimum benchmarks, without force-field optimization."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import ATOMS, ARCHIVE, FF, source, write


REF = ARCHIVE / 'tt-cpd-work-v1-completions/fit/cis-syn/charmm36-hybrid-v1'


def checked(record):
    p = Path(record['path'])
    assert source(p)['sha256'] == record['sha256']
    return p


def angle(xyz, indices):
    a, b, c = xyz[list(indices)]
    x, y = a - b, c - b
    return float(np.degrees(np.arccos(np.clip(np.dot(x, y) / np.linalg.norm(x) / np.linalg.norm(y), -1, 1))))


def volume(xyz, indices):
    a, b, c, d = xyz[indices]
    return float(np.dot(b-a, np.cross(c-a, d-a)))


def main(candidate, root, omit_c5_planarity=False):
    candidate, root = candidate.resolve(), root.resolve()
    root.mkdir(exist_ok=False)
    policy_path = Path(__file__).with_name('local_benchmark_policy_v1.json')
    policy = json.loads(policy_path.read_text())
    shutil.copyfile(policy_path, root / 'policy.json')
    shutil.copyfile(__file__, root / 'executed_source.py')
    manifest_path = REF / 'minimum_response_fixed_improper_v1/linear_response_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    amap = json.loads(checked(manifest['sources']['stable_atom_map']).read_text())
    names = [r['stable_atom_key'] for r in amap]
    idx = {n: i for i, n in enumerate(names)}
    xyz_path = checked(manifest['sources']['target_geometry'])
    xyz = np.array([list(map(float, l.split()[1:])) for l in xyz_path.read_text().splitlines()[2:] if l.strip()])
    assert xyz.shape == (36, 3)
    graph_system = mm.XmlSerializer.deserialize(checked(manifest['sources']['linear_fit_system']).read_text())
    # The fit system may use custom forces; recover graph from independently
    # recorded minimum bond list and verify expected syn crosslinks.
    old_audit = Path('.development-artifacts/cpd-canonical-syn-minimum-audit-v2/assessment.json').resolve()
    pairs = [tuple(idx[n] for n in b['atoms']) for b in json.loads(old_audit.read_text())['bonds']]
    assert len(pairs) == 38 and graph_system.getNumParticles() == 36
    cross = {tuple(sorted((names[a], names[b]))) for a, b in pairs if names[a][0] != names[b][0]}
    assert cross == {('1:C5', '2:C5'), ('1:C6', '2:C6')}
    cap = {'CM': ('CG331', -.27), 'HCM1': ('HGA3', .09),
           'HCM2': ('HGA3', .09), 'HCM3': ('HGA3', .09)}
    assignments = [cap[n.split(':')[1]] if n.split(':')[1] in cap else
                   ATOMS[{'C7': 'C5M'}.get(n.split(':')[1], n.split(':')[1])] for n in names]
    assert abs(sum(q for _, q in assignments)) < 1e-12
    wanted = {t for t, _ in assignments}
    masses = [l for l in (FF / 'par_all36_cgenff.prm').read_text().splitlines()
              if l.startswith('MASS') and l.split()[2] in wanted]
    rtf = ['* Explicit capped published-model test hypothesis\n*\n36 1', *masses,
           'AUTO ANGLES DIHE', 'RESI CPDM 0.0', 'GROUP']
    pdbnames = [r['pdb_atom_name'] for r in amap]
    for name, (typ, q) in zip(pdbnames, assignments):
        rtf.append(f'ATOM {name} {typ} {q:.6f}')
    for a, b in pairs:
        rtf.append(f'BOND {pdbnames[a]} {pdbnames[b]}')
    for res in (1, 2):
        for atoms in [('C2', 'N1', 'N3', 'O2'), ('C4', 'N3', 'C5', 'O4'), ('C5', 'C4', 'C6', 'C7')]:
            if omit_c5_planarity and atoms[0] == 'C5':
                continue
            rtf.append('IMPR ' + ' '.join(pdbnames[idx[f'{res}:{n}']] for n in atoms))
    rtf.append('END')
    (root / 'core.rtf').write_text('\n'.join(rtf) + '\n')
    pdb = []
    for i, (n, pos) in enumerate(zip(pdbnames, xyz), 1):
        pdb.append(f'ATOM  {i:5d} {n:4s} CPDM    1    {pos[0]:8.3f}{pos[1]:8.3f}{pos[2]:8.3f}  1.00  0.00      CORE')
    (root / 'core.pdb').write_text('\n'.join(pdb) + '\nEND\n')
    (root / 'build.tcl').write_text(f'''package require psfgen
resetpsf
topology {root}/core.rtf
segment CORE {{
first NONE
last NONE
residue 1 CPDM
}}
regenerate angles dihedrals
writepsf {root}/core.psf
exit
''')
    p = subprocess.run(['psfgen', str(root / 'build.tcl')], capture_output=True, text=True)
    (root / 'build.log').write_text(p.stdout + p.stderr)
    p.check_returncode()
    results = []
    for interpretation in ('first', 'last'):
        psf = app.CharmmPsfFile(str(root / 'core.psf'))
        assert [a.name for a in psf.atom_list] == pdbnames
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            params = app.CharmmParameterSet(str(root / 'core.rtf'), str(FF / 'par_all36_cgenff.prm'),
                                          str(candidate / f'comparator_{interpretation}.prm'))
        system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
        (root / f'{interpretation}_system.xml').write_text(mm.XmlSerializer.serialize(system))
        integrator = mm.VerletIntegrator(.001)
        context = mm.Context(system, integrator, mm.Platform.getPlatformByName('Reference'))

        def evaluate(flat, context=context):
            context.setPositions(flat.reshape(-1, 3) * u.angstrom)
            state = context.getState(getEnergy=True, getForces=True)
            e = state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            g = -np.asarray(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()
            return e, g

        initial_e, _ = evaluate(xyz.ravel())
        result = minimize(evaluate, xyz.ravel(), jac=True, method='L-BFGS-B',
                          options={'maxiter': 5000, 'ftol': 1e-15, 'gtol': 1e-7, 'maxls': 40})
        final = result.x.reshape(-1, 3)
        e, g = evaluate(result.x)
        hessian = np.empty((108, 108))
        step = 1e-4
        for i in range(108):
            plus, minus = result.x.copy(), result.x.copy()
            plus[i] += step
            minus[i] -= step
            hessian[:, i] = (evaluate(plus)[1] - evaluate(minus)[1]) / (2*step)
        centered = final-final.mean(axis=0)
        rigid = np.column_stack([np.tile(v, (36, 1)).ravel() for v in np.eye(3)] +
                                [np.cross(np.tile(v, (36, 1)), centered).ravel() for v in np.eye(3)])
        basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
        eigenvalues = np.linalg.eigvalsh(basis.T @ ((hessian+hessian.T)/2) @ basis)
        bonds = [{'atoms': [names[a], names[b]], 'error_A': float(np.linalg.norm(final[a]-final[b])-np.linalg.norm(xyz[a]-xyz[b])),
                  'heavy': all(not names[k].split(':')[1].startswith('H') for k in (a, b))} for a, b in pairs]
        angles = []
        for a in psf.angle_list:
            indices = (a.atom1.idx, a.atom2.idx, a.atom3.idx)
            angles.append({'atoms': [names[k] for k in indices], 'error_deg': angle(final, indices)-angle(xyz, indices),
                           'heavy': all(not names[k].split(':')[1].startswith('H') for k in indices)})
        centers = []
        for res in (1, 2):
            for center, neighbors in [('C5', [f'{res}:C4', f'{res}:C6', f'{res}:C7', f'{3-res}:C5']),
                                       ('C6', [f'{res}:N1', f'{res}:C5', f'{res}:H6', f'{3-res}:C6'])]:
                order = [idx[n] for n in neighbors]
                v0, v1 = volume(xyz, order), volume(final, order)
                centers.append({'center': f'{res}:{center}', 'reference': v0, 'final': v1,
                                'preserved': bool(v0*v1 > 0 and abs(v1) > 1e-6)})
        bond_max = max(abs(b['error_A']) for b in bonds)
        angle_max = max(abs(a['error_deg']) for a in angles)
        checks = {'bond_geometry': bond_max <= .03, 'angle_geometry': angle_max <= 3,
                  'stereochemistry': all(c['preserved'] for c in centers),
                  'stationary': bool(np.max(np.abs(g)) < .001),
                  'positive_internal_curvature': bool(eigenvalues.min() > -.001)}
        report = {'interpretation': interpretation, 'checks': checks,
                  'geometry_minimum_benchmarks_pass': all(checks.values()), 'local_acceptance': 'incomplete',
                  'max_bond_error_A': bond_max, 'max_angle_error_deg': angle_max,
                  'max_heavy_bond_error_A': max(abs(b['error_A']) for b in bonds if b['heavy']),
                  'max_heavy_angle_error_deg': max(abs(a['error_deg']) for a in angles if a['heavy']),
                  'initial_energy': initial_e, 'minimum_energy': e, 'max_force': float(np.max(np.abs(g))),
                  'minimum_internal_curvature': float(eigenvalues.min()), 'optimizer_message': str(result.message),
                  'bonds': bonds, 'angles': angles, 'centers': centers,
                  'parameter_overlay_warnings': [str(w.message) for w in caught]}
        np.savetxt(root / f'{interpretation}_minimum_A.txt', final)
        write(root / f'{interpretation}_assessment.json', report)
        results.append({k: v for k, v in report.items() if k not in ('bonds', 'angles', 'centers', 'parameter_overlay_warnings')})
        del context, integrator
    write(root / 'assessment.json', {'policy': policy, 'results': results, 'simulation_ready': False,
                                     'omit_c5_planarity': omit_c5_planarity,
                                     'selection_disclosure': 'C5 planarity removal motivated by first-round geometry diagnostic; this geometry is now development evidence for the corrected candidate, not fresh validation.' if omit_c5_planarity else 'Frozen original reconstruction benchmark',
                                     'sources': [source(p) for p in (manifest_path, xyz_path, old_audit, policy_path, Path(__file__))]})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--omit-c5-planarity', action='store_true')
    args = p.parse_args()
    main(args.candidate, args.root, args.omit_c5_planarity)
